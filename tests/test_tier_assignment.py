"""Tests for Phase 2: Tier Assignment — TierDeterminator and AgentConfig tier fields.

TEST-02: Unit tests for tier determination (threshold boundaries, provisional tier, override precedence).
"""

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
