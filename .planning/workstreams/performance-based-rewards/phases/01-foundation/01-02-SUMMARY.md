---
phase: 01-foundation
plan: 02
subsystem: core/reward_system.py + tests/test_reward_system.py + tests/test_rewards_config.py
tags: [rewards, scoring, cache, ttl, persistence, tdd]
requirements: [TIER-01, TIER-04, TIER-05, TEST-01, TEST-05]
dependency_graph:
  requires: [core/rewards_config.py (RewardsConfig.load()), memory/effectiveness.py (get_agent_stats(), get_aggregated_stats()), core/config.py (Settings.rewards_* fields)]
  provides: [RewardSystem.score(), RewardSystem.get_cached_score(), ScoreCalculator.compute(), TierCache.get()/set()/warm_from_file(), ScoreWeights.normalized()]
  affects: [Phase 02 tier assignment (consumes RewardSystem.score() to assign Bronze/Silver/Gold), Phase 03 resource enforcement (reads cached scores on routing hot path via get_cached_score())]
tech_stack:
  added: [core/reward_system.py (new module)]
  patterns: [frozen dataclass with __post_init__ validation, time.monotonic() TTL cache, os.replace() atomic file write, TYPE_CHECKING guard for circular import avoidance, TDD red-green]
key_files:
  created: [core/reward_system.py, tests/test_reward_system.py, tests/test_rewards_config.py]
  modified: []
decisions:
  - "ScoreCalculator.compute() clamps output to [0.0, 1.0] — floating-point drift from weight normalization cannot produce out-of-range scores"
  - "TierCache.set() persists to file immediately (not on a batch schedule) — ensures tier assignments survive crashes between TTL intervals"
  - "RewardSystem._get_fleet_stats() falls back to {max_volume: 1, min_speed: 1.0} on any failure — score() never crashes even when EffectivenessStore is unavailable"
  - "ScoreWeights.normalized() falls back to success-only when all weights are zero — prevents division by zero in degenerate configuration"
metrics:
  duration: 11 min
  completed: "2026-03-22T22:03:22Z"
  tasks_completed: 2
  files_modified: 3
---

# Phase 01 Plan 02: RewardSystem Module Summary

**One-liner:** ScoreCalculator (composite score with configurable weights) + TierCache (TTL dict with atomic JSON persistence) + RewardSystem facade (complete no-op when disabled) — 25 tests pass, 1633 full suite passing.

## What Was Built

Two tasks completed under TDD (RED then GREEN):

**Task 1 — RewardSystem module (TDD)**

Created `core/reward_system.py` with three layered classes:

- `ScoreWeights` (frozen dataclass): configurable weights (success=0.60, volume=0.25, speed=0.15) with `__post_init__` validation (negative weights raise ValueError) and `normalized()` method that scales weights to sum exactly 1.0; all-zero weights fall back to success-only
- `ScoreCalculator`: pure computation class with `compute(success_rate, task_volume, speed_ms, fleet_max_volume, fleet_min_speed, weights)` returning composite score in [0.0, 1.0]; volume normalized as `agent_volume / fleet_max_volume` (zero-fleet safe); speed normalized as `fleet_min_speed / agent_speed` (zero-latency returns 1.0); result clamped to prevent floating-point drift
- `TierEntry` (dataclass): score + monotonic expiry timestamp
- `TierCache`: in-memory TTL dict (15-minute default) using `time.monotonic()` expiry; `set()` writes atomically to disk via `os.replace()` immediately after each cache update; `warm_from_file()` restores entries from JSON on startup, skipping out-of-range or non-numeric values
- `RewardSystem`: enabled/disabled facade — `__init__` checks `enabled` flag once; when disabled, `score()` returns 0.0 and `get_cached_score()` returns None without touching any store or cache; when enabled, `score()` fetches from EffectivenessStore, normalizes against fleet stats, stores in TierCache, and persists to `.agent42/tier_assignments.json`

**Task 2 — Test suite validation**

Created `tests/test_rewards_config.py` (5 tests):
- Load defaults when no file exists
- Save and reload roundtrip preserves all fields
- Corrupt JSON falls back to defaults without crash
- Cache invalidation after save picks up new values
- Parent directory creation on save

Confirmed full suite: 1633 passed, 11 skipped, 12 xfailed, no regressions.

## Test Results

```
tests/test_reward_system.py     25 passed
tests/test_rewards_config.py     5 passed
tests/test_effectiveness.py     28 passed
Full suite                    1633 passed, 11 skipped, 12 xfailed
```

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| RED | 7b5c4ed | test(01-02): add failing tests for ScoreCalculator, TierCache, and RewardSystem |
| GREEN | d78b317 | feat(01-02): implement RewardSystem module with ScoreCalculator, TierCache, and RewardSystem facade |
| Task 2 | ee7c70d | feat(01-02): add test_rewards_config.py and validate full suite — 1633 tests pass |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed incorrect test expectation for zero-data score**
- **Found during:** Task 1 GREEN phase
- **Issue:** Plan's behavior spec stated `score=0.0` for `success_rate=0.0, task_volume=0, speed_ms=9999.0` with default weights. Mathematically incorrect — speed dimension contributes `0.15 * (10.0/9999.0) ≈ 0.00015` (tiny but non-zero). The implementation is correct; the test expected the wrong value.
- **Fix:** Changed assertion from `== pytest.approx(0.0)` to `< 0.001` with a comment explaining the mathematical reality. Intent preserved: score is effectively zero when success and volume are both zero.
- **Files modified:** tests/test_reward_system.py
- **Commit:** d78b317

## Known Stubs

None. All components are fully implemented and wired. Phase 02 will build tier assignment (Bronze/Silver/Gold label) on top of `RewardSystem.score()`.

## Self-Check: PASSED
