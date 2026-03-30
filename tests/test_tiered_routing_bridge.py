"""Test suite for TieredRoutingBridge — ROUTE-01 through ROUTE-04 requirements.

Tests cover:
- ROUTE-01: Role-to-task-category mapping (engineer/researcher/writer/analyst + fallbacks)
- ROUTE-02: Tier-based model upgrades (gold/silver/bronze/provisional + reward_system=None)
- ROUTE-03: Provider selection chain (preferred override > synthetic > anthropic fallback)
- ROUTE-04: Cost estimation with static pricing table and fallback pricing
"""

import os
from dataclasses import fields
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from core.tiered_routing_bridge import RoutingDecision, TieredRoutingBridge

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_reward_system():
    """Mock RewardSystem with score() returning 0.5 by default."""
    rs = MagicMock()
    rs.is_enabled = True
    rs.score = AsyncMock(return_value=0.5)
    return rs


@pytest.fixture
def bridge(mock_reward_system):
    """TieredRoutingBridge with a mocked reward system and real TierDeterminator."""
    from core.reward_system import TierDeterminator

    return TieredRoutingBridge(
        reward_system=mock_reward_system,
        tier_determinator=TierDeterminator(),
    )


# ---------------------------------------------------------------------------
# TestRoleMapping (ROUTE-01)
# ---------------------------------------------------------------------------


class TestRoleMapping:
    """ROUTE-01: Paperclip role → Agent42 task category mapping."""

    @pytest.mark.asyncio
    async def test_engineer_routes_to_coding(self, bridge):
        decision = await bridge.resolve(role="engineer", agent_id="agent-1")
        assert decision.base_category == "coding"

    @pytest.mark.asyncio
    async def test_researcher_routes_to_research(self, bridge):
        decision = await bridge.resolve(role="researcher", agent_id="agent-1")
        assert decision.base_category == "research"

    @pytest.mark.asyncio
    async def test_writer_routes_to_content(self, bridge):
        decision = await bridge.resolve(role="writer", agent_id="agent-1")
        assert decision.base_category == "content"

    @pytest.mark.asyncio
    async def test_analyst_routes_to_strategy(self, bridge):
        decision = await bridge.resolve(role="analyst", agent_id="agent-1")
        assert decision.base_category == "strategy"

    @pytest.mark.asyncio
    async def test_unknown_role_falls_back_to_general(self, bridge):
        decision = await bridge.resolve(role="unknown_role", agent_id="agent-1")
        assert decision.base_category == "general"

    @pytest.mark.asyncio
    async def test_empty_role_falls_back_to_general(self, bridge):
        decision = await bridge.resolve(role="", agent_id="agent-1")
        assert decision.base_category == "general"

    @pytest.mark.asyncio
    async def test_none_role_falls_back_to_general(self, bridge):
        decision = await bridge.resolve(role=None, agent_id="agent-1")
        assert decision.base_category == "general"


# ---------------------------------------------------------------------------
# TestTierUpgrade (ROUTE-02)
# ---------------------------------------------------------------------------


class TestTierUpgrade:
    """ROUTE-02: Tier-based model upgrades via RewardSystem + TierDeterminator."""

    @pytest.mark.asyncio
    async def test_gold_tier_gets_reasoning_model(self, mock_reward_system):
        """High-scoring agent with enough observations should get gold/reasoning model."""
        from core.reward_system import TierDeterminator

        mock_reward_system.score = AsyncMock(return_value=0.9)
        # Patch min_observations to 0 so obs_count=0 doesn't force provisional
        with patch("core.config.settings") as mock_settings:
            mock_settings.rewards_min_observations = 0
            bridge = TieredRoutingBridge(
                reward_system=mock_reward_system,
                tier_determinator=TierDeterminator(),
            )
            decision = await bridge.resolve(
                role="engineer", agent_id="agent-gold", preferred_provider="anthropic"
            )
        assert decision.tier == "gold"
        # Reasoning model for anthropic is claude-opus-4-6-20260205
        assert "opus" in decision.model or decision.task_category == "reasoning"

    @pytest.mark.asyncio
    async def test_bronze_tier_gets_fast_model(self, mock_reward_system):
        """Low-scoring agent with enough observations should get bronze/fast model."""
        from core.reward_system import TierDeterminator

        mock_reward_system.score = AsyncMock(return_value=0.3)
        with patch("core.config.settings") as mock_settings:
            mock_settings.rewards_min_observations = 0
            bridge = TieredRoutingBridge(
                reward_system=mock_reward_system,
                tier_determinator=TierDeterminator(),
            )
            decision = await bridge.resolve(
                role="engineer", agent_id="agent-bronze", preferred_provider="anthropic"
            )
        assert decision.tier == "bronze"
        assert decision.task_category == "fast"

    @pytest.mark.asyncio
    async def test_provisional_tier_no_upgrade(self, bridge):
        """Default obs_count=0 with min_observations=10 → provisional, no upgrade."""
        # Default TierDeterminator uses settings.rewards_min_observations=10
        # obs_count is passed as 0 in the bridge → always provisional with default settings
        decision = await bridge.resolve(role="engineer", agent_id="agent-new")
        assert decision.tier == "provisional"
        # No upgrade: task_category stays as base_category
        assert decision.task_category == decision.base_category

    @pytest.mark.asyncio
    async def test_rewards_disabled_uses_base_category(self, mock_reward_system):
        """When reward_system returns 0.0 (disabled), tier is provisional, no upgrade."""
        from core.reward_system import TierDeterminator

        mock_reward_system.score = AsyncMock(return_value=0.0)
        bridge = TieredRoutingBridge(
            reward_system=mock_reward_system,
            tier_determinator=TierDeterminator(),
        )
        decision = await bridge.resolve(role="engineer", agent_id="agent-disabled")
        assert decision.tier == "provisional"
        assert decision.task_category == decision.base_category

    @pytest.mark.asyncio
    async def test_reward_system_none_graceful(self):
        """Bridge with reward_system=None must not crash and must return tier=''."""
        bridge = TieredRoutingBridge(reward_system=None)
        decision = await bridge.resolve(role="engineer", agent_id="agent-1")
        assert decision.tier == ""
        assert isinstance(decision.provider, str)
        assert isinstance(decision.model, str)


# ---------------------------------------------------------------------------
# TestProviderSelection (ROUTE-03)
# ---------------------------------------------------------------------------


class TestProviderSelection:
    """ROUTE-03: Provider selection chain — preferred > synthetic > anthropic."""

    @pytest.mark.asyncio
    async def test_preferred_provider_override(self, bridge):
        """preferred_provider='openrouter' should win regardless of other config."""
        decision = await bridge.resolve(
            role="engineer", agent_id="agent-1", preferred_provider="openrouter"
        )
        assert decision.provider == "openrouter"

    @pytest.mark.asyncio
    async def test_default_provider_is_synthetic(self, bridge):
        """When SYNTHETIC_API_KEY is set, default provider should be synthetic."""
        with patch.dict(os.environ, {"SYNTHETIC_API_KEY": "test-key"}):
            decision = await bridge.resolve(role="engineer", agent_id="agent-1")
        assert decision.provider == "synthetic"

    @pytest.mark.asyncio
    async def test_fallback_provider_is_anthropic(self, bridge):
        """When SYNTHETIC_API_KEY is not set, fallback provider is anthropic."""
        env = {k: v for k, v in os.environ.items() if k != "SYNTHETIC_API_KEY"}
        with patch.dict(os.environ, env, clear=True):
            decision = await bridge.resolve(role="engineer", agent_id="agent-1")
        assert decision.provider == "anthropic"

    @pytest.mark.asyncio
    async def test_preferred_provider_with_unmapped_category(self, bridge):
        """openrouter with role=analyst (strategy) should fall back via resolve_model general."""
        decision = await bridge.resolve(
            role="analyst", agent_id="agent-1", preferred_provider="openrouter"
        )
        assert decision.provider == "openrouter"
        # resolve_model should return a valid model (falls back to general)
        assert isinstance(decision.model, str)
        assert len(decision.model) > 0


# ---------------------------------------------------------------------------
# TestCostEstimation (ROUTE-04)
# ---------------------------------------------------------------------------


class TestCostEstimation:
    """ROUTE-04: Static pricing table and cost estimation."""

    def test_estimate_cost_known_model(self, bridge):
        """Known model uses exact pricing from static table."""
        # claude-sonnet-4-6-20260217: 3.0/M input, 15.0/M output
        cost = bridge.estimate_cost(
            "claude-sonnet-4-6-20260217", input_tokens=1000, output_tokens=500
        )
        expected = 1000 * (3.0 / 1_000_000) + 500 * (15.0 / 1_000_000)
        assert abs(cost - expected) < 1e-9

    def test_estimate_cost_unknown_model_uses_fallback(self, bridge):
        """Unknown model uses _PRICING_FALLBACK (5.0/M input, 15.0/M output)."""
        cost = bridge.estimate_cost("unknown-model-xyz", input_tokens=1000, output_tokens=500)
        expected = 1000 * (5.0 / 1_000_000) + 500 * (15.0 / 1_000_000)
        assert abs(cost - expected) < 1e-9

    def test_estimate_cost_zero_tokens(self, bridge):
        """Zero tokens returns 0.0."""
        cost = bridge.estimate_cost("claude-sonnet-4-6-20260217", input_tokens=0, output_tokens=0)
        assert cost == 0.0

    def test_routing_decision_has_all_fields(self, bridge):
        """RoutingDecision dataclass must have all 6 required fields."""
        field_names = {f.name for f in fields(RoutingDecision)}
        required = {"provider", "model", "tier", "task_category", "base_category", "cost_estimate"}
        assert required == field_names, f"Missing fields: {required - field_names}"
