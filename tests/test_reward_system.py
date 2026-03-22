"""Tests for core/reward_system.py — Phase 1 Foundation.

TEST-01: Score calculation (composite weights, edge cases, zero data)
TIER-04: TTL cache (O(1) hit on cached entries, expiry evicts)
TIER-05: Persistence (write to file, warm from file on restart)
TEST-05: Graceful degradation (rewards disabled = no-op, returns 0.0/None)
"""

import json
import time
from unittest.mock import AsyncMock

import pytest


class TestScoreWeights:
    """ScoreWeights normalization and validation."""

    def test_default_weights_sum_to_one(self):
        from core.reward_system import ScoreWeights

        w = ScoreWeights()
        assert abs(w.success + w.volume + w.speed - 1.0) < 1e-9

    def test_normalized_weights_sum_to_one(self):
        from core.reward_system import ScoreWeights

        w = ScoreWeights(success=3.0, volume=1.0, speed=1.0)
        n = w.normalized()
        assert abs(n.success + n.volume + n.speed - 1.0) < 1e-9
        assert n.success == pytest.approx(3 / 5)

    def test_zero_weights_falls_back_to_success_only(self):
        from core.reward_system import ScoreWeights

        w = ScoreWeights(success=0.0, volume=0.0, speed=0.0)
        n = w.normalized()
        assert n.success == pytest.approx(1.0)
        assert n.volume == pytest.approx(0.0)
        assert n.speed == pytest.approx(0.0)

    def test_negative_weight_raises(self):
        from core.reward_system import ScoreWeights

        with pytest.raises(ValueError, match="non-negative"):
            ScoreWeights(success=-0.1, volume=0.5, speed=0.5)


class TestScoreCalculator:
    """TEST-01: Composite score calculation edge cases and formula correctness."""

    def setup_method(self):
        from core.reward_system import ScoreCalculator, ScoreWeights

        self.calc = ScoreCalculator()
        self.default_weights = ScoreWeights()

    def test_perfect_agent_scores_one(self):
        """All dimensions at max -> score = 1.0."""

        score = self.calc.compute(
            success_rate=1.0,
            task_volume=100,
            speed_ms=10.0,
            fleet_max_volume=100,
            fleet_min_speed=10.0,
            weights=self.default_weights,
        )
        assert score == pytest.approx(1.0)

    def test_zero_data_scores_zero(self):
        """Zero success, zero volume, zero speed (perfect speed) -> near-zero.

        Note: speed_ms=0 gives speed_norm=1.0, so with speed weight=0.15 the
        minimum achievable score with zero success and zero volume is not exactly 0.
        This tests that the score is effectively zero when all meaningful work
        dimensions (success and volume) are zero, even if the speed dim contributes
        a tiny amount from a very slow agent.
        """
        score = self.calc.compute(
            success_rate=0.0,
            task_volume=0,
            speed_ms=9999.0,
            fleet_max_volume=100,
            fleet_min_speed=10.0,
            weights=self.default_weights,
        )
        # success=0, volume=0, speed=tiny (10/9999 * 0.15 ~ 0.00015) — effectively 0
        assert score < 0.001

    def test_formula_with_default_weights(self):
        """0.60 * 0.8 + 0.25 * 0.5 + 0.15 * 0.5 = 0.68."""
        from core.reward_system import ScoreWeights

        # volume_normalized = 50/100 = 0.5
        # speed_normalized = 10.0/20.0 = 0.5
        score = self.calc.compute(
            success_rate=0.8,
            task_volume=50,
            speed_ms=20.0,
            fleet_max_volume=100,
            fleet_min_speed=10.0,
            weights=ScoreWeights(success=0.60, volume=0.25, speed=0.15),
        )
        assert score == pytest.approx(0.68, abs=0.001)

    def test_zero_fleet_max_volume_no_division_error(self):
        """fleet_max_volume=0 -> volume_normalized=0, no ZeroDivisionError."""
        score = self.calc.compute(
            success_rate=1.0,
            task_volume=10,
            speed_ms=10.0,
            fleet_max_volume=0,
            fleet_min_speed=10.0,
        )
        # Only success and speed contribute when vol=0
        assert 0.0 <= score <= 1.0

    def test_zero_agent_speed_is_perfect(self):
        """speed_ms=0 -> speed_normalized=1.0 (no division by zero)."""
        from core.reward_system import ScoreWeights

        score_zero_speed = self.calc.compute(
            success_rate=0.0,
            task_volume=0,
            speed_ms=0.0,
            fleet_max_volume=1,
            fleet_min_speed=10.0,
            weights=ScoreWeights(success=0.0, volume=0.0, speed=1.0),
        )
        assert score_zero_speed == pytest.approx(1.0)

    def test_score_clamped_to_zero_one(self):
        """Floating-point drift cannot produce out-of-range scores."""
        score = self.calc.compute(
            success_rate=2.0,  # Invalid but must not crash
            task_volume=999999,
            speed_ms=0.001,
            fleet_max_volume=1,
            fleet_min_speed=10.0,
        )
        assert 0.0 <= score <= 1.0

    def test_non_default_weights_applied(self):
        """Custom weights (success-only) ignore volume and speed."""
        from core.reward_system import ScoreWeights

        score = self.calc.compute(
            success_rate=0.5,
            task_volume=100,
            speed_ms=10.0,
            fleet_max_volume=100,
            fleet_min_speed=10.0,
            weights=ScoreWeights(success=1.0, volume=0.0, speed=0.0),
        )
        assert score == pytest.approx(0.5)


class TestTierCache:
    """TIER-04: TTL cache correctness and TIER-05: file persistence."""

    def test_cache_miss_returns_none(self, tmp_path):
        from core.reward_system import TierCache

        cache = TierCache(persistence_path=tmp_path / "tiers.json")
        assert cache.get("nonexistent") is None

    def test_cache_hit_returns_score(self, tmp_path):
        from core.reward_system import TierCache

        cache = TierCache(persistence_path=tmp_path / "tiers.json")
        cache.set("agent-abc", 0.75)
        assert cache.get("agent-abc") == pytest.approx(0.75)

    def test_expired_entry_returns_none(self, tmp_path):
        """TTL=0 means every entry is immediately expired."""
        from core.reward_system import TierCache

        cache = TierCache(ttl_seconds=0, persistence_path=tmp_path / "tiers.json")
        cache.set("agent-abc", 0.75)
        # Sleep 1ms to ensure monotonic clock advances past zero TTL
        time.sleep(0.001)
        assert cache.get("agent-abc") is None

    def test_persist_writes_json_file(self, tmp_path):
        """TIER-05: set() writes to persistence file immediately."""
        from core.reward_system import TierCache

        path = tmp_path / "tiers.json"
        cache = TierCache(persistence_path=path)
        cache.set("agent-abc", 0.75)
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["agent-abc"] == pytest.approx(0.75)

    def test_warm_from_file_restores_cache(self, tmp_path):
        """TIER-05: cache warmed from file on startup."""
        path = tmp_path / "tiers.json"
        path.write_text(json.dumps({"agent-abc": 0.75, "agent-xyz": 0.42}))

        from core.reward_system import TierCache

        cache = TierCache(ttl_seconds=60, persistence_path=path)
        count = cache.warm_from_file()
        assert count == 2
        assert cache.get("agent-abc") == pytest.approx(0.75)
        assert cache.get("agent-xyz") == pytest.approx(0.42)

    def test_warm_from_file_missing_file_returns_zero(self, tmp_path):
        """Missing file -> warm_from_file returns 0, no crash."""
        from core.reward_system import TierCache

        cache = TierCache(persistence_path=tmp_path / "nonexistent.json")
        count = cache.warm_from_file()
        assert count == 0

    def test_warm_from_file_ignores_invalid_scores(self, tmp_path):
        """Out-of-range or non-numeric values are silently skipped."""
        path = tmp_path / "tiers.json"
        path.write_text(json.dumps({"agent-a": 0.5, "agent-b": -1.0, "agent-c": "bad"}))

        from core.reward_system import TierCache

        cache = TierCache(ttl_seconds=60, persistence_path=path)
        count = cache.warm_from_file()
        assert count == 1  # Only agent-a is valid
        assert cache.get("agent-a") == pytest.approx(0.5)

    def test_multiple_agents_cached_independently(self, tmp_path):
        from core.reward_system import TierCache

        cache = TierCache(persistence_path=tmp_path / "tiers.json")
        cache.set("agent-a", 0.3)
        cache.set("agent-b", 0.9)
        assert cache.get("agent-a") == pytest.approx(0.3)
        assert cache.get("agent-b") == pytest.approx(0.9)


class TestRewardSystem:
    """Integration tests for the RewardSystem facade."""

    @pytest.mark.asyncio
    async def test_disabled_score_returns_zero(self, tmp_path):
        """TEST-05: rewards disabled -> score() always returns 0.0."""
        from core.reward_system import RewardSystem

        mock_store = AsyncMock()
        rs = RewardSystem(
            effectiveness_store=mock_store,
            enabled=False,
            persistence_path=tmp_path / "tiers.json",
        )
        result = await rs.score("any-agent")
        assert result == 0.0
        mock_store.get_agent_stats.assert_not_called()

    @pytest.mark.asyncio
    async def test_disabled_get_cached_score_returns_none(self, tmp_path):
        """TEST-05: rewards disabled -> get_cached_score() always returns None."""
        from core.reward_system import RewardSystem

        rs = RewardSystem(enabled=False, persistence_path=tmp_path / "tiers.json")
        assert rs.get_cached_score("any-agent") is None

    @pytest.mark.asyncio
    async def test_enabled_no_agent_data_returns_zero(self, tmp_path):
        """Agent with no effectiveness data -> score=0.0, no crash."""
        from core.reward_system import RewardSystem

        mock_store = AsyncMock()
        mock_store.get_agent_stats.return_value = None
        mock_store.get_aggregated_stats.return_value = []
        rs = RewardSystem(
            effectiveness_store=mock_store,
            enabled=True,
            persistence_path=tmp_path / "tiers.json",
        )
        result = await rs.score("unknown-agent")
        assert result == 0.0

    @pytest.mark.asyncio
    async def test_enabled_computes_and_caches_score(self, tmp_path):
        """Score computed from effectiveness data and then served from cache."""
        from core.reward_system import RewardSystem

        mock_store = AsyncMock()
        mock_store.get_agent_stats.return_value = {
            "success_rate": 1.0,
            "task_volume": 10,
            "avg_speed": 10.0,
        }
        mock_store.get_aggregated_stats.return_value = [
            {"invocations": 10, "avg_duration_ms": 10.0}
        ]
        rs = RewardSystem(
            effectiveness_store=mock_store,
            enabled=True,
            cache_ttl=60,
            persistence_path=tmp_path / "tiers.json",
        )
        score1 = await rs.score("agent-abc")
        assert score1 > 0.0

        # Second call should hit cache -- get_agent_stats called only once
        score2 = await rs.score("agent-abc")
        assert score2 == score1
        mock_store.get_agent_stats.assert_called_once()

    @pytest.mark.asyncio
    async def test_enabled_score_persisted_to_file(self, tmp_path):
        """TIER-05: computed score written to tier_assignments.json."""
        from core.reward_system import RewardSystem

        mock_store = AsyncMock()
        mock_store.get_agent_stats.return_value = {
            "success_rate": 0.8,
            "task_volume": 5,
            "avg_speed": 20.0,
        }
        mock_store.get_aggregated_stats.return_value = [{"invocations": 5, "avg_duration_ms": 20.0}]
        path = tmp_path / "tiers.json"
        rs = RewardSystem(
            effectiveness_store=mock_store,
            enabled=True,
            cache_ttl=60,
            persistence_path=path,
        )
        await rs.score("agent-abc")
        assert path.exists()
        data = json.loads(path.read_text())
        assert "agent-abc" in data
        assert 0.0 <= data["agent-abc"] <= 1.0

    def test_warm_from_file_on_startup(self, tmp_path):
        """TIER-05: RewardSystem reads persistence file during __init__ when enabled."""
        path = tmp_path / "tiers.json"
        path.write_text(json.dumps({"agent-abc": 0.77}))

        from core.reward_system import RewardSystem

        rs = RewardSystem(
            enabled=True,
            cache_ttl=60,
            persistence_path=path,
        )
        # Score should be available immediately without calling score()
        assert rs.get_cached_score("agent-abc") == pytest.approx(0.77)
