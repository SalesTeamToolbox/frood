---
phase: 02-tier-assignment
plan: "02"
subsystem: rewards
tags: [tdd, tier-assignment, background-loop, agent-manager, startup-wiring]
dependency_graph:
  requires: [core/reward_system.py, core/agent_manager.py, agent42.py, dashboard/server.py]
  provides: [TierRecalcLoop class, TierRecalcLoop.start()/stop()/_recalc_loop()/_run_recalculation(), AgentManager in agent42.py scope, conditional TierRecalcLoop startup]
  affects: [Phase 3 resource enforcement, Phase 4 dashboard]
tech_stack:
  added: []
  patterns: [async background loop (HeartbeatService pattern), conditional startup gate (rewards_enabled), per-agent error isolation, sleep-first recalculation pattern]
key_files:
  created: []
  modified: [core/reward_system.py, tests/test_tier_assignment.py, agent42.py, dashboard/server.py]
decisions:
  - "TierRecalcLoop stop() is synchronous matching HeartbeatService pattern — not async"
  - "Loop sleeps first then recalculates (no thundering herd at startup)"
  - "AgentManager instantiated in Agent42.__init__() and shared to create_app() via agent_manager kwarg"
  - "create_app() uses agent_manager or AgentManager() fallback for backward compatibility in headless/test usage"
metrics:
  duration: "13 min"
  completed_date: "2026-03-22"
  tasks: 2
  files: 4
---

# Phase 02 Plan 02: TierRecalcLoop and Startup Wiring Summary

**One-liner:** TierRecalcLoop background service (HeartbeatService pattern) added to reward_system.py with per-agent error isolation and override-skip; AgentManager moved to Agent42.__init__() scope and wired to conditional startup gate.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add TierRecalcLoop to core/reward_system.py (TDD) | 761ef05 | core/reward_system.py, tests/test_tier_assignment.py |
| 2 | Move AgentManager to agent42.py scope and wire TierRecalcLoop startup | acf4cd3 | agent42.py, dashboard/server.py |

## What Was Built

### TierRecalcLoop (core/reward_system.py)

Background service class that periodically recomputes agent tiers. Follows the HeartbeatService pattern exactly:

- `start()` [async]: sets `_running = True`, creates asyncio task via `asyncio.create_task(self._recalc_loop())`
- `stop()` [synchronous]: sets `_running = False`, cancels and clears the task
- `_recalc_loop()` [private async]: sleeps first (no thundering herd at startup), then calls `_run_recalculation()`, catches `CancelledError` to break cleanly
- `_run_recalculation()` [private async]: iterates all agents via `agent_manager.list_all()`, skips agents where `tier_override is not None` (ADMN-01), calls `reward_system.score()` + `effectiveness_store.get_agent_stats()` per agent, delegates to `TierDeterminator.determine()`, updates `AgentConfig` via `agent_manager.update()`, logs tier changes

Per-agent exceptions are caught, logged as warnings, and the loop continues — one bad agent never aborts fleet-wide recalculation (ADMN-03).

Default interval: 900 seconds (15 minutes), matching TierCache TTL.

### AgentManager in agent42.py scope

AgentManager was moved from being instantiated inside `create_app()` (server.py) to being instantiated in `Agent42.__init__()`:

```python
agents_dir = data_dir / "agents"
self.agent_manager = AgentManager(agents_dir)
```

This makes it available to `TierRecalcLoop` at startup and passes it to `create_app()` via a new `agent_manager` keyword argument.

### Conditional TierRecalcLoop Startup

In `Agent42.__init__()`, TierRecalcLoop is created only when `settings.rewards_enabled` is `True`:

```python
self.tier_recalc = None
if settings.rewards_enabled:
    from core.reward_system import RewardSystem, TierRecalcLoop
    self.reward_system = RewardSystem(...)
    self.tier_recalc = TierRecalcLoop(...)
else:
    self.reward_system = None
```

In `Agent42.start()`, started after heartbeat:
```python
if self.tier_recalc:
    await self.tier_recalc.start()
```

In `Agent42.shutdown()`, stopped synchronously:
```python
if self.tier_recalc:
    self.tier_recalc.stop()
```

### dashboard/server.py Changes

`create_app()` signature extended with `agent_manager=None` parameter. The Agents section now uses the passed manager with fallback:

```python
_agent_manager = agent_manager or AgentManager(workspace / ".agent42" / "agents")
```

This preserves backward compatibility for headless/test usage where no agent_manager is passed.

## Test Results

- 21 tests in `tests/test_tier_assignment.py` — all pass
- 4 new `TestTierRecalcLoop` tests:
  - `test_overridden_agent_not_recalculated` — agent with `tier_override="gold"` skipped, plain agent processed
  - `test_non_overridden_agent_is_recalculated` — agent gets `score()` called and `update()` called with correct tier
  - `test_per_agent_error_does_not_abort_loop` — agent-b still processed when agent-a raises RuntimeError
  - `test_stats_none_produces_provisional` — `get_agent_stats()` returning None produces `obs_count=0`, tier="provisional"
- Full suite: 1654 passed, 0 regressions

## Decisions Made

| Decision | Rationale |
|----------|-----------|
| `stop()` synchronous | Matches HeartbeatService pattern exactly (D-07) |
| Sleep-first in `_recalc_loop()` | No thundering herd on startup; fleet-wide recalc deferred until first interval |
| Deferred `from core.reward_system import` inside `__init__` | Avoids circular import at module load; rewards_enabled gate keeps it clean |
| `agent_manager or AgentManager()` fallback | Preserves server.py backward compatibility for test/headless scenarios |
| `datetime.utcnow().isoformat() + "Z"` for `tier_computed_at` | Avoids importing `timezone` separately; produces valid ISO timestamp |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] datetime and asyncio imports stripped by ruff linter**
- **Found during:** Task 1 test run
- **Issue:** ruff auto-format stripped `asyncio` and `datetime` imports when added before the class body used them (treated as unused during intermediate edit states)
- **Fix:** Added imports in a single edit pass ensuring they appeared alongside the code that uses them; ruff preserved them when `asyncio.Task` and `datetime.utcnow()` were already present
- **Files modified:** core/reward_system.py
- **Commit:** 761ef05

**2. [Rule 1 - Bug] `pytest` module import stripped by linter in test file**
- **Found during:** Task 1 test execution
- **Issue:** ruff linter removed `import pytest` because it detected the import as added before `pytest.approx` usage — formatting pass treated it as unused during intermediate state
- **Fix:** Added `import pytest` as a module-level import that ruff preserves (it appears before the class that uses it); 21 tests pass
- **Files modified:** tests/test_tier_assignment.py
- **Commit:** 761ef05

## Known Stubs

None — TierRecalcLoop is fully wired. Data flows from `EffectivenessStore` through `RewardSystem.score()` and `TierDeterminator.determine()` into `AgentManager.update()`. Phase 3 (resource enforcement) and Phase 4 (dashboard) will consume `AgentConfig.effective_tier()`.

## Self-Check: PASSED

- [x] `core/reward_system.py` contains `class TierRecalcLoop`
- [x] `def stop` in `core/reward_system.py` is NOT `async def stop` (synchronous)
- [x] `if agent.tier_override is not None:` in `core/reward_system.py`
- [x] `asyncio.CancelledError` in `core/reward_system.py`
- [x] `class TestTierRecalcLoop` in `tests/test_tier_assignment.py`
- [x] 21 tests in `tests/test_tier_assignment.py` — all pass
- [x] `self.agent_manager = AgentManager(agents_dir)` in `agent42.py`
- [x] `if self.tier_recalc:` in `agent42.py`
- [x] `await self.tier_recalc.start()` in `agent42.py`
- [x] `self.tier_recalc.stop()` in `agent42.py`
- [x] `agent_manager=self.agent_manager` in `agent42.py` create_app() call
- [x] `agent_manager=None` in `dashboard/server.py` create_app() signature
- [x] `agent_manager or AgentManager` in `dashboard/server.py`
- [x] Commits 761ef05 and acf4cd3 present in git log
- [x] Full test suite: 1654 passed, 0 regressions
- [x] `python agent42.py --help` exits 0 (no import errors)
