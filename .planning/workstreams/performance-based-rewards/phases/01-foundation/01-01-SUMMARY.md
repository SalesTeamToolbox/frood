---
phase: 01-foundation
plan: 01
subsystem: core/config + core/rewards_config + memory/effectiveness + tools/registry
tags: [rewards, config, effectiveness, agent_id, tdd]
requirements: [CONF-01, CONF-02, CONF-03, CONF-04, CONF-05, DATA-01, DATA-02, TEST-05]
dependency_graph:
  requires: [core/config.py (Settings frozen dataclass), memory/effectiveness.py (EffectivenessStore), tools/registry.py (ToolRegistry.execute()), agents/agent_routing_store.py (mtime-cache pattern)]
  provides: [Settings.rewards_enabled + 12 other REWARDS_* fields, RewardsConfig.load()/save()/set_path(), EffectivenessStore.get_agent_stats(), agent_id column in tool_invocations, agent_id threaded through ToolRegistry.execute()]
  affects: [Phase 02 tier assignment (consumes get_agent_stats()), Phase 03 resource enforcement (consumes per-tier limits from Settings)]
tech_stack:
  added: [core/rewards_config.py (new module)]
  patterns: [frozen dataclass env var expansion, mtime-cached file-backed config, SQLite ALTER TABLE ADD COLUMN migration, TDD red-green]
key_files:
  created: [core/rewards_config.py]
  modified: [core/config.py, memory/effectiveness.py, tools/registry.py, tests/test_effectiveness.py]
decisions:
  - "RewardsConfig uses class-level cache (not instance-level) — all callers share one in-memory copy with one disk read per mtime change, matching AgentRoutingStore pattern"
  - "ALTER TABLE ADD COLUMN wrapped in try/except — SQLite silently errors on duplicate column; idempotent-safe for existing databases"
  - "get_agent_stats() returns None (not empty dict) for unknown agent — distinguishes zero-data from zero-success"
  - "agent_id NOT added to Settings — agent_id is a runtime data concept, not a startup configuration field"
metrics:
  duration: 15 min
  completed: "2026-03-22T21:48:32Z"
  tasks_completed: 2
  files_modified: 5
---

# Phase 01 Plan 01: Configuration and Data Foundation Summary

**One-liner:** Settings frozen dataclass extended with 13 REWARDS_* fields + mtime-cached RewardsConfig module + agent_id column migration + get_agent_stats() + ToolRegistry threading.

## What Was Built

Two tasks completed under TDD (RED then GREEN):

**Task 1 — Settings extension and RewardsConfig module**
- Added 13 reward fields to Settings frozen dataclass in `core/config.py`:
  - `rewards_enabled: bool = False` (startup gate — zero impact when false)
  - Tier thresholds: `rewards_silver_threshold=0.65`, `rewards_gold_threshold=0.85`
  - Scoring weights: `rewards_weight_success=0.60`, `rewards_weight_volume=0.25`, `rewards_weight_speed=0.15`
  - Per-tier resource limits: `rewards_{bronze,silver,gold}_rate_limit_multiplier` and `rewards_{bronze,silver,gold}_max_concurrent`
- Added all 13 corresponding `REWARDS_*` env var entries in `from_env()`
- Created `core/rewards_config.py` with `RewardsConfig` dataclass:
  - Class-level mtime-cached load — shares one in-memory copy across all callers
  - `load()` returns defaults on missing/invalid file (never raises)
  - `save()` uses atomic `os.replace()` write and invalidates cache
  - `set_path()` for test isolation

**Task 2 — agent_id schema extension and get_agent_stats()**
- Added `ALTER TABLE tool_invocations ADD COLUMN agent_id TEXT DEFAULT ''` migration in `_ensure_db()` — idempotent-safe via `try/except`
- Extended `record()` signature with `agent_id: str = ""` (backward-compatible default)
- Updated INSERT statement to include `agent_id` column
- Added `get_agent_stats(agent_id) -> dict | None` method:
  - Returns `{success_rate, task_volume, avg_speed}` for a given agent_id
  - Returns `None` when no records exist (not a crash, not an empty dict)
  - Scoped to specific agent_id — ignores rows for other agents
- Threaded `agent_id=agent_id` into `ToolRegistry.execute()` → `effectiveness_store.record()` call
- Added `TestEffectivenessAgentId` (5 tests) and `TestRewardsGracefulDegradation` (3 tests) to `tests/test_effectiveness.py`

## Test Results

All 28 effectiveness tests pass. Full suite (1603 tests) passes with no regressions.

```
tests/test_effectiveness.py  28 passed
Full suite                   1603 passed, 11 skipped, 12 xfailed
```

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| Task 1 | 96e6c35 | feat(01-01): extend Settings with REWARDS_* fields and create RewardsConfig module |
| Task 2 | 8223d59 | feat(01-01): add agent_id to EffectivenessStore schema and thread through ToolRegistry |

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None. All data layer components are fully implemented and wired. Phase 02 will build tier assignment logic on top of `get_agent_stats()`.

## Self-Check: PASSED
