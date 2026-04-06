---
phase: 30-advanced-teamtool-auto-memory
plan: 01
subsystem: sidecar
tags: [auto-memory, strategy-detection, pydantic-models, teamtool]
dependency_graph:
  requires: []
  provides: [auto_memory_injection, strategy_detection, team_strategy_models]
  affects: [core/sidecar_models.py, core/sidecar_orchestrator.py, tests/test_sidecar.py]
tech_stack:
  added: []
  patterns: [auto-memory injection via getattr guard, strategy detection with known_strategies set, datetime.now(UTC).isoformat() for timestamps]
key_files:
  created: []
  modified:
    - core/sidecar_models.py
    - core/sidecar_orchestrator.py
    - tests/test_sidecar.py
decisions:
  - auto_memory defaults to True in AdapterConfig — opt-in disabling via autoMemory:false in adapter payload
  - Strategy detection reads ctx.context.get('strategy', 'standard') — unknown values fall back to 'standard' with warning log
  - memoryContext injected into ctx.context dict between routing and execution — allows AgentRuntime to access memories when wired (D-04)
  - autoMemory metadata in callback result includes count + injectedAt timestamp for Paperclip to track injection events
  - UTC datetime import reformatted by ruff to modern form (from datetime import UTC, datetime) — Python 3.11+ idiomatic
metrics:
  duration_seconds: 272
  completed_date: "2026-03-31T21:35:47Z"
  tasks_completed: 3
  tasks_total: 3
  files_changed: 3
---

# Phase 30 Plan 01: Sidecar Auto-Memory Injection + Team Strategy Models Summary

**One-liner:** Auto-memory injection into execute_async context dict with ISO timestamps, team strategy Pydantic models (SubAgentResult/WaveOutput/TeamExecuteRequest), and strategy detection routing with fallback for unknown values.

## Tasks Completed

| Task | Title | Commit | Files |
|------|-------|--------|-------|
| 30-01-01 | Add auto_memory field to AdapterConfig + team strategy Pydantic models | 4183a7e | core/sidecar_models.py |
| 30-01-02 | Inject recalled memories into context dict in execute_async | b8517b4 | core/sidecar_orchestrator.py |
| 30-01-03 | Write unit tests for auto-memory injection and strategy detection | be7c180 | tests/test_sidecar.py |

## What Was Built

### Task 1 — AdapterConfig + Team Strategy Models (4183a7e)

Added `auto_memory: bool = Field(default=True, alias="autoMemory")` to `AdapterConfig` after the existing `agent_id` field.

Added three new Pydantic models at the end of `core/sidecar_models.py`:
- **SubAgentResult** — result from a single sub-agent invocation in fan-out strategy (agentId, runId, status, output, costUsd)
- **WaveOutput** — output from a single wave in wave strategy execution (wave, agentId, runId, status, output)
- **TeamExecuteRequest** — request body for team strategy execution (runId, agentId, companyId, strategy, subAgentIds, waves, task, context)

All three models use `ConfigDict(populate_by_name=True)` with camelCase aliases matching Paperclip conventions.

### Task 2 — Auto-Memory Injection in execute_async (b8517b4)

Modified `core/sidecar_orchestrator.py`:

1. Added `from datetime import UTC, datetime` import (ruff reformatted from `timezone` form)
2. **Step 1.6** — Auto-memory injection block: when `recalled_memories` is non-empty AND `ctx.adapter_config.auto_memory` is True, sets `ctx.context["memoryContext"]` with `memories` list, `injectedAt` ISO timestamp, and `count`
3. **Step 1.7** — Strategy detection: reads `ctx.context.get("strategy", "standard")`, validates against `{"standard", "fan-out", "wave"}`, warns on unknown values and resets to "standard", logs info for non-standard strategies
4. Updated `result` dict to include `autoMemory: {"count": N, "injectedAt": <iso_str>}` when memories were injected, `null` otherwise

Injection sits between routing decision logging (Step 1.5) and the execution stub (Step 2), preserving the existing execute_async flow.

### Task 3 — Unit Tests (be7c180)

Added `TestAutoMemoryInjection` class to `tests/test_sidecar.py` with 7 tests:

1. `test_auto_memory_injects_when_memories_recalled` — verifies ctx.context["memoryContext"] structure (count, memories list, injectedAt)
2. `test_auto_memory_in_callback` — captures callback result and verifies autoMemory metadata present
3. `test_auto_memory_disabled` — verifies no memoryContext when auto_memory=False
4. `test_auto_memory_no_memories` — verifies no memoryContext + autoMemory=None when recall returns []
5. `test_strategy_standard_default` — verifies no "Unknown strategy" warning for default case
6. `test_strategy_unknown_falls_back` — verifies warning log contains "Unknown strategy 'unknown'"
7. `test_strategy_fan_out_detected` — verifies info log contains "strategy 'fan-out'"

Pattern: direct `SidecarOrchestrator` instantiation with `AsyncMock` memory_bridge + `patch.object(orch, "_post_callback")` to avoid HTTP calls. Uses `caplog` for log assertion tests.

**Final test count:** 53 passed (7 new + 46 pre-existing), 0 failures.

## Verification Results

```
python -m pytest tests/test_sidecar.py -x -q
53 passed in 4.18s

python -c "from core.sidecar_models import AdapterConfig; ac = AdapterConfig(); assert ac.auto_memory is True; print('auto_memory default OK')"
auto_memory default OK

python -c "from core.sidecar_models import SubAgentResult, WaveOutput, TeamExecuteRequest; print('Models import OK')"
Models import OK
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Ruff auto-formatter stripped datetime import**
- **Found during:** Task 2
- **Issue:** After the first `Edit` adding `from datetime import datetime, timezone`, the PostToolUse ruff hook ran and removed the import (detecting it as potentially unused before the downstream Edit added `datetime.now(timezone.utc)`). This left `datetime.now(timezone.utc)` without an import.
- **Fix:** Re-added the import in a subsequent `Edit`. Ruff then reformatted it to `from datetime import UTC, datetime` (Python 3.11+ idiomatic) and rewrote `timezone.utc` to `UTC` throughout. This is equivalent and correct.
- **Files modified:** core/sidecar_orchestrator.py
- **Commit:** b8517b4

**2. [Rule 2 - Missing import] SidecarOrchestrator not imported in test file**
- **Found during:** Task 3
- **Issue:** The new `TestAutoMemoryInjection` class instantiates `SidecarOrchestrator` directly, but it was not in the existing imports.
- **Fix:** Added `SidecarOrchestrator` to the `from core.sidecar_orchestrator import (...)` block.
- **Files modified:** tests/test_sidecar.py
- **Commit:** be7c180

## Known Stubs

None — all new code paths are fully wired and tested. The execution stub comment in `execute_async` (Step 2) is pre-existing from Phase 24 and not introduced by this plan.

## Self-Check: PASSED
