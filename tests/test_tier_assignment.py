"""Tests for Phase 2: Tier Assignment — TierDeterminator, AgentConfig tier fields, and TierRecalcLoop.

TEST-02: Unit tests for tier determination (threshold boundaries, provisional tier, override precedence).
ADMN-01, ADMN-03: Recalculation skips overridden agents; per-agent errors do not abort loop.
"""

import pytest

from core.agent_manager import AgentConfig  # will fail for new fields until Task 2
from core.reward_system import TierDeterminator  # will fail until Task 2 implements it


class TestTierDeterminator:
    """TIER-02, TIER-03: Bronze/Silver/Gold assignment and provisional tier logic."""

    def setup_method(self):
        self.det = TierDeterminator()

    def test_below_min_observations_returns_provisional(self):
        assert self.det.determine(score=0.99, observation_count=9) == "provisional"

    def test_zero_observations_returns_provisional(self):
        assert self.det.determine(score=0.0, observation_count=0) == "provisional"

    def test_exactly_min_observations_enters_tier_ladder(self):
        assert self.det.determine(score=0.0, observation_count=10) == "bronze"

    def test_below_silver_threshold_returns_bronze(self):
        assert self.det.determine(score=0.64, observation_count=10) == "bronze"

    def test_at_silver_threshold_returns_silver(self):
        assert self.det.determine(score=0.65, observation_count=10) == "silver"

    def test_between_thresholds_returns_silver(self):
        assert self.det.determine(score=0.75, observation_count=10) == "silver"

    def test_at_gold_threshold_returns_gold(self):
        assert self.det.determine(score=0.85, observation_count=10) == "gold"

    def test_above_gold_threshold_returns_gold(self):
        assert self.det.determine(score=1.0, observation_count=10) == "gold"


class TestAgentConfigTierFields:
    """D-01, D-02, D-03: AgentConfig field defaults and effective_tier() logic."""

    def test_new_agent_has_empty_reward_tier(self):
        assert AgentConfig(name="test").reward_tier == ""

    def test_new_agent_has_none_tier_override(self):
        assert AgentConfig(name="test").tier_override is None

    def test_new_agent_has_zero_performance_score(self):
        assert AgentConfig(name="test").performance_score == 0.0

    def test_new_agent_has_empty_tier_computed_at(self):
        assert AgentConfig(name="test").tier_computed_at == ""

    def test_effective_tier_returns_reward_tier_when_no_override(self):
        assert AgentConfig(name="test", reward_tier="silver").effective_tier() == "silver"

    def test_effective_tier_returns_override_when_set(self):
        agent = AgentConfig(name="test", reward_tier="bronze", tier_override="gold")
        assert agent.effective_tier() == "gold"

    def test_effective_tier_with_none_override_returns_reward_tier(self):
        # None is the sentinel for "no override" (D-03)
        agent = AgentConfig(name="test", reward_tier="silver", tier_override=None)
        assert agent.effective_tier() == "silver"

    def test_tier_fields_roundtrip_through_dict(self):
        original = AgentConfig(
            name="roundtrip",
            reward_tier="gold",
            tier_override="silver",
            performance_score=0.78,
            tier_computed_at="2026-03-22T10:00:00Z",
        )
        restored = AgentConfig.from_dict(original.to_dict())
        assert restored.reward_tier == "gold"
        assert restored.tier_override == "silver"
        assert restored.performance_score == 0.78
        assert restored.tier_computed_at == "2026-03-22T10:00:00Z"

    def test_from_dict_without_new_fields_uses_defaults(self):
        agent = AgentConfig.from_dict({"id": "abc", "name": "Legacy"})
        assert agent.reward_tier == ""
        assert agent.tier_override is None
        assert agent.performance_score == 0.0
        assert agent.tier_computed_at == ""


class TestTierRecalcLoop:
    """ADMN-01, ADMN-03: Recalculation skips overridden agents; per-agent errors do not abort loop."""

    async def test_overridden_agent_not_recalculated(self):
        from unittest.mock import AsyncMock, MagicMock

        from core.agent_manager import AgentConfig
        from core.reward_system import TierRecalcLoop

        overridden = AgentConfig(id="agent-a", name="A", tier_override="gold")
        plain = AgentConfig(id="agent-b", name="B")

        mock_manager = MagicMock()
        mock_manager.list_all.return_value = [overridden, plain]

        mock_rs = AsyncMock()
        mock_rs.score.return_value = 0.5

        mock_store = AsyncMock()
        mock_store.get_agent_stats.return_value = {
            "task_volume": 20,
            "success_rate": 0.5,
            "avg_speed": 100.0,
        }

        loop = TierRecalcLoop(
            agent_manager=mock_manager,
            reward_system=mock_rs,
            effectiveness_store=mock_store,
        )
        await loop._run_recalculation()

        # agent-a (overridden) must NOT have triggered score()
        called_ids = [call.args[0] for call in mock_rs.score.call_args_list]
        assert "agent-a" not in called_ids
        assert "agent-b" in called_ids

    async def test_non_overridden_agent_is_recalculated(self):
        from unittest.mock import AsyncMock, MagicMock

        from core.agent_manager import AgentConfig
        from core.reward_system import TierRecalcLoop

        plain = AgentConfig(id="agent-c", name="C")  # tier_override is None

        mock_manager = MagicMock()
        mock_manager.list_all.return_value = [plain]

        mock_rs = AsyncMock()
        mock_rs.score.return_value = 0.9  # will produce "gold" with 20+ observations

        mock_store = AsyncMock()
        mock_store.get_agent_stats.return_value = {
            "task_volume": 20,
            "success_rate": 0.9,
            "avg_speed": 50.0,
        }

        loop = TierRecalcLoop(
            agent_manager=mock_manager,
            reward_system=mock_rs,
            effectiveness_store=mock_store,
        )
        await loop._run_recalculation()

        mock_manager.update.assert_called_once()
        call_kwargs = mock_manager.update.call_args
        assert call_kwargs.args[0] == "agent-c"
        assert call_kwargs.kwargs["reward_tier"] == "gold"
        assert call_kwargs.kwargs["performance_score"] == pytest.approx(0.9)
        assert "tier_computed_at" in call_kwargs.kwargs

    async def test_per_agent_error_does_not_abort_loop(self):
        from unittest.mock import AsyncMock, MagicMock

        from core.agent_manager import AgentConfig
        from core.reward_system import TierRecalcLoop

        agent_a = AgentConfig(id="agent-a", name="A")  # will error
        agent_b = AgentConfig(id="agent-b", name="B")  # should still be processed

        mock_manager = MagicMock()
        mock_manager.list_all.return_value = [agent_a, agent_b]

        mock_rs = AsyncMock()
        mock_rs.score.side_effect = [RuntimeError("DB failure"), 0.7]

        mock_store = AsyncMock()
        mock_store.get_agent_stats.return_value = {
            "task_volume": 15,
            "success_rate": 0.7,
            "avg_speed": 80.0,
        }

        loop = TierRecalcLoop(
            agent_manager=mock_manager,
            reward_system=mock_rs,
            effectiveness_store=mock_store,
        )
        await loop._run_recalculation()

        # agent-b must still have been updated despite agent-a's error
        update_calls = [c.args[0] for c in mock_manager.update.call_args_list]
        assert "agent-b" in update_calls

    async def test_stats_none_produces_provisional(self):
        """New agents with no stats get obs_count=0 and are assigned provisional."""
        from unittest.mock import AsyncMock, MagicMock

        from core.agent_manager import AgentConfig
        from core.reward_system import TierRecalcLoop

        new_agent = AgentConfig(id="agent-new", name="New")

        mock_manager = MagicMock()
        mock_manager.list_all.return_value = [new_agent]

        mock_rs = AsyncMock()
        mock_rs.score.return_value = 0.99  # high score, but not enough observations

        mock_store = AsyncMock()
        mock_store.get_agent_stats.return_value = None  # Phase 1 returns None for unknown agents

        loop = TierRecalcLoop(
            agent_manager=mock_manager,
            reward_system=mock_rs,
            effectiveness_store=mock_store,
        )
        await loop._run_recalculation()

        call_kwargs = mock_manager.update.call_args
        assert call_kwargs.kwargs["reward_tier"] == "provisional"
