"""Performance-based rewards system -- scoring, caching, and persistence.

All public classes are no-ops when Settings.rewards_enabled is False.
The startup gate is checked once in RewardSystem.__init__() -- no scattered
if-checks throughout the codebase.

Patterns used:
- ScoreCalculator: pure computation, no I/O
- TierCache: time.monotonic() TTL dict (same pattern as ToolRateLimiter)
- RewardsConfig: mtime-cached file-backed config (same pattern as AgentRoutingStore)
- File persistence: os.replace() atomic write (same pattern as AgentRoutingStore)
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from core.rewards_config import RewardsConfig

if TYPE_CHECKING:
    from memory.effectiveness import EffectivenessStore

logger = logging.getLogger("agent42.reward_system")

# TTL for in-memory tier cache (seconds). Matches background recalculation interval.
_CACHE_TTL_SECONDS = 900  # 15 minutes

# Path for tier persistence file
_TIER_FILE = Path(".agent42/tier_assignments.json")


# ---------------------------------------------------------------------------
# Score Calculator
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScoreWeights:
    """Configurable weights for the composite score formula."""

    success: float = 0.60
    volume: float = 0.25
    speed: float = 0.15

    def __post_init__(self) -> None:
        if any(w < 0 for w in (self.success, self.volume, self.speed)):
            raise ValueError("All score weights must be non-negative")

    def normalized(self) -> ScoreWeights:
        """Return weights scaled so they sum to 1.0.

        Protects against misconfigured weights that don't sum to 1.
        """
        total = self.success + self.volume + self.speed
        if total == 0:
            # All-zero weights: fall back to success-only
            return ScoreWeights(success=1.0, volume=0.0, speed=0.0)
        return ScoreWeights(
            success=self.success / total,
            volume=self.volume / total,
            speed=self.speed / total,
        )


class ScoreCalculator:
    """Computes a composite performance score in [0.0, 1.0].

    Formula (after weight normalization):
        score = w_success * success_rate
              + w_volume  * volume_normalized
              + w_speed   * speed_normalized

    Volume normalization (min-max, higher is better):
        volume_normalized = agent_volume / fleet_max_volume   (clamped 0-1)

    Speed normalization (lower latency = higher score):
        speed_normalized = fleet_min_speed / agent_speed      (clamped 0-1)
        Special case: agent_speed == 0 -> 1.0 (instantaneous is perfect)
    """

    def compute(
        self,
        success_rate: float,
        task_volume: int,
        speed_ms: float,
        fleet_max_volume: int,
        fleet_min_speed: float,
        weights: ScoreWeights | None = None,
    ) -> float:
        """Return composite score in [0.0, 1.0].

        Args:
            success_rate: Fraction of successful tool calls (0.0-1.0).
            task_volume: Number of tool calls for this agent.
            speed_ms: Average tool call duration in milliseconds.
            fleet_max_volume: Maximum task_volume across all agents (for normalization).
            fleet_min_speed: Minimum avg duration across all agents (fastest agent).
            weights: Score weights. Uses defaults (0.60/0.25/0.15) if None.
        """
        w = (weights or ScoreWeights()).normalized()

        # Volume: higher is better, normalized against fleet max
        if fleet_max_volume > 0:
            vol_norm = min(1.0, task_volume / fleet_max_volume)
        else:
            vol_norm = 0.0

        # Speed: lower ms is better. Best agent in fleet = 1.0.
        if speed_ms <= 0:
            speed_norm = 1.0
        elif fleet_min_speed > 0:
            speed_norm = min(1.0, fleet_min_speed / speed_ms)
        else:
            speed_norm = 1.0

        score = w.success * success_rate + w.volume * vol_norm + w.speed * speed_norm
        # Clamp to [0, 1] to guard against floating-point drift
        return max(0.0, min(1.0, score))


# ---------------------------------------------------------------------------
# Tier Cache with TTL and File Persistence
# ---------------------------------------------------------------------------


@dataclass
class TierEntry:
    """A cached tier assignment with expiry timestamp."""

    score: float
    expires_at: float  # time.monotonic() timestamp


class TierCache:
    """In-memory TTL cache for computed performance scores, with file persistence.

    TTL pattern from core/rate_limiter.py (time.monotonic() timestamps).
    Persistence pattern from agents/agent_routing_store.py (os.replace() atomic write).

    Cache key: agent_id (str)
    Cache value: TierEntry (score + expiry)
    """

    def __init__(
        self,
        ttl_seconds: float = _CACHE_TTL_SECONDS,
        persistence_path: Path | None = None,
    ) -> None:
        self._ttl = ttl_seconds
        self._path = persistence_path or _TIER_FILE
        self._cache: dict[str, TierEntry] = {}

    # -- Public API -----------------------------------------------------------

    def get(self, agent_id: str) -> float | None:
        """Return cached score if not expired, else None."""
        entry = self._cache.get(agent_id)
        if entry is None:
            return None
        if time.monotonic() >= entry.expires_at:
            del self._cache[agent_id]
            return None
        return entry.score

    def set(self, agent_id: str, score: float) -> None:
        """Store score with TTL expiry. Persists to file immediately."""
        self._cache[agent_id] = TierEntry(
            score=score,
            expires_at=time.monotonic() + self._ttl,
        )
        self._persist()

    def warm_from_file(self) -> int:
        """Load persisted scores into cache on startup. Returns count loaded."""
        if not self._path.exists():
            return 0
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            count = 0
            for agent_id, score in data.items():
                if isinstance(score, (int, float)) and 0.0 <= score <= 1.0:
                    self._cache[agent_id] = TierEntry(
                        score=float(score),
                        expires_at=time.monotonic() + self._ttl,
                    )
                    count += 1
            logger.info("TierCache: warmed %d entries from %s", count, self._path)
            return count
        except Exception as exc:
            logger.warning("TierCache: failed to load %s: %s", self._path, exc)
            return 0

    # -- Private helpers -------------------------------------------------------

    def _persist(self) -> None:
        """Write current cache to file atomically. Never raises."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            data = {aid: entry.score for aid, entry in self._cache.items()}
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            os.replace(str(tmp), str(self._path))
        except Exception as exc:
            logger.warning("TierCache: persist failed (non-critical): %s", exc)


# ---------------------------------------------------------------------------
# RewardSystem -- top-level facade, gated by REWARDS_ENABLED
# ---------------------------------------------------------------------------


class RewardSystem:
    """Facade for the rewards system.

    When rewards_enabled=False (the default), all methods are no-ops:
    - score() returns 0.0
    - get_cached_score() returns None
    All cache and persistence operations are skipped.

    When enabled, coordinates ScoreCalculator, TierCache, and EffectivenessStore
    to produce and cache composite performance scores.
    """

    def __init__(
        self,
        effectiveness_store: EffectivenessStore | None = None,
        enabled: bool = False,
        weights: ScoreWeights | None = None,
        cache_ttl: float = _CACHE_TTL_SECONDS,
        persistence_path: Path | None = None,
    ) -> None:
        self._enabled = enabled
        self._store = effectiveness_store
        self._calculator = ScoreCalculator()
        self._weights = weights or ScoreWeights()
        self._cache = TierCache(ttl_seconds=cache_ttl, persistence_path=persistence_path)

        if self._enabled:
            warmed = self._cache.warm_from_file()
            logger.info("RewardSystem enabled -- cache warmed with %d entries", warmed)
        else:
            logger.debug("RewardSystem disabled (REWARDS_ENABLED=false) -- no-op mode")

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    async def score(self, agent_id: str) -> float:
        """Compute and cache composite score for agent_id.

        Returns 0.0 when rewards are disabled or agent has no data.
        Reads from EffectivenessStore.get_agent_stats() -- no raw SQL.
        """
        if not self._enabled or self._store is None:
            return 0.0

        # Check cache first
        cached = self._cache.get(agent_id)
        if cached is not None:
            return cached

        # Fetch agent stats
        stats = await self._store.get_agent_stats(agent_id)
        if stats is None:
            return 0.0

        # Fetch fleet context for normalization
        fleet_stats = await self._get_fleet_stats()

        computed = self._calculator.compute(
            success_rate=stats["success_rate"],
            task_volume=stats["task_volume"],
            speed_ms=stats["avg_speed"],
            fleet_max_volume=fleet_stats["max_volume"],
            fleet_min_speed=fleet_stats["min_speed"],
            weights=self._weights,
        )

        self._cache.set(agent_id, computed)
        return computed

    def get_cached_score(self, agent_id: str) -> float | None:
        """Return cached score without triggering a recompute.

        Returns None when disabled, not cached, or expired.
        Called on the routing hot path -- must be O(1).
        """
        if not self._enabled:
            return None
        return self._cache.get(agent_id)

    # -- Private helpers -------------------------------------------------------

    async def _get_fleet_stats(self) -> dict:
        """Return fleet-level max_volume and min_speed for normalization.

        Falls back to safe defaults if the store returns no data.
        """
        if self._store is None:
            return {"max_volume": 1, "min_speed": 1.0}
        try:
            all_stats = await self._store.get_aggregated_stats()
            if not all_stats:
                return {"max_volume": 1, "min_speed": 1.0}
            max_vol = max((r.get("invocations", 0) for r in all_stats), default=1)
            min_spd = min(
                (
                    r.get("avg_duration_ms", 1.0)
                    for r in all_stats
                    if r.get("avg_duration_ms", 0) > 0
                ),
                default=1.0,
            )
            return {"max_volume": max(1, max_vol), "min_speed": max(0.001, min_spd)}
        except Exception as exc:
            logger.warning("RewardSystem: fleet stats fetch failed: %s", exc)
            return {"max_volume": 1, "min_speed": 1.0}


# ---------------------------------------------------------------------------
# Tier Determinator
# ---------------------------------------------------------------------------


class TierDeterminator:
    """Maps (score, observation_count) to a tier string.

    Pure computation — no I/O, no side effects. Thresholds read from
    RewardsConfig (mtime-cached, cheap). Tier names are lowercase strings
    per D-06: 'provisional', 'bronze', 'silver', 'gold'.
    """

    def determine(self, score: float, observation_count: int) -> str:
        """Return tier string for the given score and observation count.

        Returns 'provisional' when observation_count is below the minimum
        required for tier assignment (settings.rewards_min_observations, default 10).
        This prevents new agents from being penalized to Bronze.

        Per D-03: None is the override sentinel; empty string is NOT None.
        """
        from core.config import settings  # deferred to avoid circular at module load

        if observation_count < settings.rewards_min_observations:
            return "provisional"
        cfg = RewardsConfig.load()
        if score >= cfg.gold_threshold:
            return "gold"
        if score >= cfg.silver_threshold:
            return "silver"
        return "bronze"
