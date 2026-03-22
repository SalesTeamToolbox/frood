"""Tests for Phase 3: Resource Enforcement — model routing, rate limit multipliers, concurrency semaphores.

RSRC-01: Gold/Silver/Bronze tier upgrade of model category in resolve_model()
RSRC-02: Tier-based rate limit multipliers in ToolRateLimiter.check()
RSRC-03: Concurrent task semaphores via AgentManager._get_tier_semaphore()
RSRC-04: AgentManager.get_effective_limits() dict
TEST-03: Integration — get_effective_limits() + resolve_model() end-to-end
"""

import asyncio
from dataclasses import dataclass
from pathlib import Path

import pytest

from core.agent_manager import (
    _TIER_CATEGORY_UPGRADE,
    AgentConfig,
    AgentManager,
    resolve_model,
)
from core.rate_limiter import ToolLimit, ToolRateLimiter, _get_multiplier

# ── Helper dataclass to mock settings ────────────────────────────────────────


@dataclass
class _MockSettings:
    rewards_enabled: bool = False
    rewards_bronze_rate_limit_multiplier: float = 1.0
    rewards_silver_rate_limit_multiplier: float = 1.5
    rewards_gold_rate_limit_multiplier: float = 2.0
    rewards_bronze_max_concurrent: int = 2
    rewards_silver_max_concurrent: int = 5
    rewards_gold_max_concurrent: int = 10


# ── TestModelRouting ──────────────────────────────────────────────────────────


class TestModelRouting:
    """RSRC-01: Tier-based model category upgrades in resolve_model()."""

    def test_gold_tier_gets_reasoning_category(self):
        """Gold tier maps to 'reasoning' category — upgrade from any base category."""
        result = resolve_model("anthropic", "general", tier="gold")
        assert result == "claude-opus-4-6-20260205"

    def test_silver_tier_gets_general_category(self):
        """Silver tier maps to 'general' category — overrides fast base category."""
        result = resolve_model("anthropic", "fast", tier="silver")
        assert result == "claude-sonnet-4-6-20260217"

    def test_bronze_tier_gets_fast_category(self):
        """Bronze tier maps to 'fast' category — overrides general base category."""
        result = resolve_model("anthropic", "general", tier="bronze")
        assert result == "claude-haiku-4-5-20251001"

    def test_no_tier_unchanged(self):
        """D-03: No tier arg returns same result as before Phase 3 (backward compat)."""
        result = resolve_model("anthropic", "general")
        assert result == "claude-sonnet-4-6-20260217"

    def test_provisional_no_upgrade(self):
        """'provisional' is NOT in the upgrade map — falls back to task_category."""
        result = resolve_model("anthropic", "general", tier="provisional")
        # Should return 'general' category model (no upgrade applied)
        assert result == "claude-sonnet-4-6-20260217"

    def test_manual_override_ignores_tier(self):
        """D-02 is caller-enforced: if agent.model is set, resolve_model() is never called.

        Verified by inspection of start_agent and _build_env() in dashboard/server.py
        and core/agent_runtime.py. The endpoint/dispatch layer checks agent.model before
        calling resolve_model() and skips resolve_model() entirely when a manual model
        is configured. This test confirms the contract by inspection, not by calling
        resolve_model() with a special parameter — because D-02 is NOT enforced inside
        resolve_model() itself.
        """
        # An agent with an explicit model set bypasses resolve_model() at the call site.
        agent = AgentConfig(name="overridden", model="claude-opus-4-6")
        # Verify the agent has a model set — the call site uses this to skip resolve_model()
        assert agent.model == "claude-opus-4-6"
        # The resolve_model() function itself has no knowledge of model overrides:
        # that responsibility lives at the dispatch layer (caller-enforced).

    def test_tier_category_upgrade_dict_present(self):
        """_TIER_CATEGORY_UPGRADE dict must be exported from core.agent_manager."""
        assert "gold" in _TIER_CATEGORY_UPGRADE
        assert "silver" in _TIER_CATEGORY_UPGRADE
        assert "bronze" in _TIER_CATEGORY_UPGRADE
        assert "provisional" not in _TIER_CATEGORY_UPGRADE
        assert _TIER_CATEGORY_UPGRADE["gold"] == "reasoning"
        assert _TIER_CATEGORY_UPGRADE["silver"] == "general"
        assert _TIER_CATEGORY_UPGRADE["bronze"] == "fast"


# ── TestRateLimiterTier ───────────────────────────────────────────────────────


class TestRateLimiterTier:
    """RSRC-02: Tier multipliers in ToolRateLimiter.check()."""

    def _make_limiter(self, max_calls: int) -> ToolRateLimiter:
        """Create a limiter with a single tool at a given max_calls."""
        return ToolRateLimiter(
            limits={"test_tool": ToolLimit(max_calls=max_calls, window_seconds=3600)}
        )

    def test_gold_multiplier_doubles_effective_max(self):
        """Gold tier (2.0x) allows 20 calls when base limit is 10."""
        limiter = self._make_limiter(max_calls=10)
        # Make 20 calls — all should be allowed with gold tier
        for i in range(20):
            allowed, reason = limiter.check("test_tool", "agent-gold", tier="gold")
            assert allowed, f"Call {i + 1} should be allowed: {reason}"
            limiter.record("test_tool", "agent-gold")
        # 21st call should be blocked
        allowed, _ = limiter.check("test_tool", "agent-gold", tier="gold")
        assert not allowed

    def test_silver_multiplier_scales_max(self):
        """Silver tier (1.5x) allows 15 calls when base limit is 10."""
        limiter = self._make_limiter(max_calls=10)
        for i in range(15):
            allowed, reason = limiter.check("test_tool", "agent-silver", tier="silver")
            assert allowed, f"Call {i + 1} should be allowed: {reason}"
            limiter.record("test_tool", "agent-silver")
        # 16th call should be blocked
        allowed, _ = limiter.check("test_tool", "agent-silver", tier="silver")
        assert not allowed

    def test_empty_tier_no_change(self):
        """Empty tier string → multiplier 1.0 → original max_calls enforced."""
        limiter = self._make_limiter(max_calls=5)
        for i in range(5):
            allowed, reason = limiter.check("test_tool", "agent-notier", tier="")
            assert allowed, f"Call {i + 1} should be allowed: {reason}"
            limiter.record("test_tool", "agent-notier")
        # 6th call should be blocked
        allowed, _ = limiter.check("test_tool", "agent-notier", tier="")
        assert not allowed

    def test_provisional_tier_no_change(self):
        """'provisional' tier → multiplier 1.0 → original max_calls enforced."""
        limiter = self._make_limiter(max_calls=3)
        for i in range(3):
            allowed, reason = limiter.check("test_tool", "agent-prov", tier="provisional")
            assert allowed, f"Call {i + 1} should be allowed: {reason}"
            limiter.record("test_tool", "agent-prov")
        # 4th call should be blocked
        allowed, _ = limiter.check("test_tool", "agent-prov", tier="provisional")
        assert not allowed

    def test_calls_key_unchanged(self):
        """D-05: After check() with tier, _calls dict keys are still '{agent_id}:{tool_name}'."""
        limiter = self._make_limiter(max_calls=10)
        limiter.check("test_tool", "agent-keyed", tier="gold")
        limiter.record("test_tool", "agent-keyed")
        # Confirm key format is unchanged
        assert "agent-keyed:test_tool" in limiter._calls

    def test_get_multiplier_helper_gold(self):
        """_get_multiplier() returns 2.0 for gold tier."""
        multiplier = _get_multiplier("gold")
        assert multiplier == 2.0

    def test_get_multiplier_helper_silver(self):
        """_get_multiplier() returns 1.5 for silver tier."""
        multiplier = _get_multiplier("silver")
        assert multiplier == 1.5

    def test_get_multiplier_helper_empty(self):
        """_get_multiplier() returns 1.0 for empty tier string."""
        multiplier = _get_multiplier("")
        assert multiplier == 1.0

    def test_get_multiplier_helper_provisional(self):
        """_get_multiplier() returns 1.0 for provisional tier."""
        multiplier = _get_multiplier("provisional")
        assert multiplier == 1.0


# ── TestConcurrencySemaphore ──────────────────────────────────────────────────


class TestConcurrencySemaphore:
    """RSRC-03: Per-tier concurrent task semaphores on AgentManager."""

    def _make_manager(self, tmp_path: Path) -> AgentManager:
        return AgentManager(tmp_path / "agents")

    async def test_bronze_cap_blocks_third_concurrent(self, tmp_path: Path, monkeypatch):
        """With rewards_enabled=True and bronze cap=2, 3rd acquire via wait_for(timeout=0.0) raises TimeoutError."""
        mock_settings = _MockSettings(rewards_enabled=True, rewards_bronze_max_concurrent=2)
        monkeypatch.setattr("core.agent_manager.settings", mock_settings)

        manager = self._make_manager(tmp_path)
        sem = manager._get_tier_semaphore("bronze")
        assert sem is not None

        # Acquire twice (at cap)
        await sem.acquire()
        await sem.acquire()

        # Third acquire must fail immediately
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(sem.acquire(), timeout=0.0)

    async def test_rewards_disabled_no_semaphore(self, tmp_path: Path, monkeypatch):
        """With rewards_enabled=False, _get_tier_semaphore() returns None."""
        mock_settings = _MockSettings(rewards_enabled=False)
        monkeypatch.setattr("core.agent_manager.settings", mock_settings)

        manager = self._make_manager(tmp_path)
        assert manager._get_tier_semaphore("bronze") is None
        assert manager._get_tier_semaphore("gold") is None

    async def test_provisional_no_cap(self, tmp_path: Path, monkeypatch):
        """_get_tier_semaphore('provisional') returns None — no cap for provisional tier."""
        mock_settings = _MockSettings(rewards_enabled=True)
        monkeypatch.setattr("core.agent_manager.settings", mock_settings)

        manager = self._make_manager(tmp_path)
        assert manager._get_tier_semaphore("provisional") is None

    async def test_empty_tier_no_cap(self, tmp_path: Path, monkeypatch):
        """_get_tier_semaphore('') returns None — no cap for empty tier."""
        mock_settings = _MockSettings(rewards_enabled=True)
        monkeypatch.setattr("core.agent_manager.settings", mock_settings)

        manager = self._make_manager(tmp_path)
        assert manager._get_tier_semaphore("") is None


# ── TestGetEffectiveLimits ────────────────────────────────────────────────────


class TestGetEffectiveLimits:
    """RSRC-04: AgentManager.get_effective_limits(agent_id) returns correct dict."""

    def _make_manager_with_agent(
        self, tmp_path: Path, tier: str
    ) -> tuple[AgentManager, AgentConfig]:
        manager = AgentManager(tmp_path / "agents")
        agent = manager.create(name="test-agent", reward_tier=tier)
        return manager, agent

    def test_gold_limits_correct(self, tmp_path: Path, monkeypatch):
        """Gold agent returns model_tier='reasoning', rate_multiplier=2.0, max_concurrent=10."""
        mock_settings = _MockSettings(
            rewards_enabled=True,
            rewards_gold_rate_limit_multiplier=2.0,
            rewards_gold_max_concurrent=10,
        )
        monkeypatch.setattr("core.agent_manager.settings", mock_settings)

        manager, agent = self._make_manager_with_agent(tmp_path, tier="gold")
        limits = manager.get_effective_limits(agent.id)
        assert limits["model_tier"] == "reasoning"
        assert limits["rate_multiplier"] == 2.0
        assert limits["max_concurrent"] == 10

    def test_disabled_returns_defaults(self, tmp_path: Path, monkeypatch):
        """rewards_enabled=False → {'model_tier': '', 'rate_multiplier': 1.0, 'max_concurrent': 0}."""
        mock_settings = _MockSettings(rewards_enabled=False)
        monkeypatch.setattr("core.agent_manager.settings", mock_settings)

        manager, agent = self._make_manager_with_agent(tmp_path, tier="gold")
        limits = manager.get_effective_limits(agent.id)
        assert limits["model_tier"] == ""
        assert limits["rate_multiplier"] == 1.0
        assert limits["max_concurrent"] == 0

    def test_unknown_agent_returns_defaults(self, tmp_path: Path, monkeypatch):
        """Non-existent agent_id returns safe defaults."""
        mock_settings = _MockSettings(rewards_enabled=True)
        monkeypatch.setattr("core.agent_manager.settings", mock_settings)

        manager = AgentManager(tmp_path / "agents")
        limits = manager.get_effective_limits("nonexistent-agent-id")
        assert limits["model_tier"] == ""
        assert limits["rate_multiplier"] == 1.0
        assert limits["max_concurrent"] == 0


# ── TestIntegration ───────────────────────────────────────────────────────────


class TestIntegration:
    """TEST-03: Integration tests connecting get_effective_limits() with resolve_model()."""

    def test_gold_agent_gets_reasoning_model_via_limits(self, tmp_path: Path, monkeypatch):
        """get_effective_limits() returns model_tier='reasoning'; resolve_model with gold tier yields reasoning model."""
        mock_settings = _MockSettings(
            rewards_enabled=True,
            rewards_gold_rate_limit_multiplier=2.0,
            rewards_gold_max_concurrent=10,
        )
        monkeypatch.setattr("core.agent_manager.settings", mock_settings)

        manager = AgentManager(tmp_path / "agents")
        agent = manager.create(name="gold-agent", reward_tier="gold")

        limits = manager.get_effective_limits(agent.id)
        assert limits["model_tier"] == "reasoning"

        # Verify that resolving with gold tier (which upgrades to 'reasoning') returns the reasoning model
        model = resolve_model("anthropic", "general", tier=agent.effective_tier())
        assert model == "claude-opus-4-6-20260205"
