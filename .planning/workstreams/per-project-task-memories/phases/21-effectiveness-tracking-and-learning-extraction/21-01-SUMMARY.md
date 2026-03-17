---
phase: 21-effectiveness-tracking-and-learning-extraction
plan: 01
subsystem: memory
tags: [aiosqlite, sqlite, effectiveness-tracking, tool-registry, async, fire-and-forget]

# Dependency graph
requires:
  - phase: 20-task-metadata-foundation
    provides: get_task_context() returning (task_id, task_type) — used to tag every tool invocation

provides:
  - EffectivenessStore async SQLite module at memory/effectiveness.py
  - tool_invocations table with tool_name/task_type/task_id/success/duration_ms/ts columns
  - Fire-and-forget timing wrapper in ToolRegistry.execute() via asyncio.create_task()
  - POST /api/effectiveness/record endpoint for MCP tool tracking from hooks
  - GET /api/effectiveness/stats endpoint for aggregated success_rate and avg_duration_ms
  - LEARNING_MIN_EVIDENCE and LEARNING_QUARANTINE_CONFIDENCE config fields in Settings

affects: [22-proactive-injection, 23-recommendations-engine, plan-02-learning-extraction]

# Tech tracking
tech-stack:
  added:
    - aiosqlite>=0.20.0 (async SQLite — effectiveness.db writes)
    - instructor>=1.3.0 (structured LLM extraction — used in Plan 02 learning pipeline)
  patterns:
    - "Fire-and-forget SQLite via asyncio.create_task() — tool result returns before write completes"
    - "try/except Exception + logger.warning for all SQLite operations — never propagates to caller"
    - "Lazy import of get_task_context inside execute() to prevent circular imports (memory -> core direction)"
    - "Binary-mode file reads required for CRLF files on Windows — use open(f, 'rb') not 'r'"

key-files:
  created:
    - memory/effectiveness.py
    - tests/test_effectiveness.py
  modified:
    - tools/registry.py
    - agent42.py
    - dashboard/server.py
    - requirements.txt
    - core/config.py
    - .env.example

key-decisions:
  - "Fire-and-forget is non-negotiable: synchronous SQLite adds 300-1500ms on a 100-call task; asyncio.create_task() used"
  - "EffectivenessStore never raises: all exceptions caught with logger.warning, tool execution continues"
  - "Rate limiter record() moved to fire only on result.success=True — failures should not count toward rate limiting"
  - "get_task_context() lazy-imported inside execute() to avoid circular imports (memory imports core, not reverse)"
  - "instructor added now (needed by Plan 02) to consolidate dependency installs"

patterns-established:
  - "Fire-and-forget pattern: asyncio.create_task(store.record(...)) inside try/except Exception: pass"
  - "Graceful degradation: _available flag tracks write health; never raises from record()"
  - "Binary file read/write required for CRLF-preserving edits on Windows-origin files"

requirements-completed: [EFFT-01, EFFT-02, EFFT-03, EFFT-04, EFFT-05]

# Metrics
duration: 19min
completed: 2026-03-17
---

# Phase 21 Plan 01: Effectiveness Tracking — EffectivenessStore Summary

**Async SQLite tool invocation tracker with fire-and-forget ToolRegistry integration and dashboard API endpoints for MCP hook tracking**

## Performance

- **Duration:** 19 min
- **Started:** 2026-03-17T23:32:12Z
- **Completed:** 2026-03-17T23:51:59Z
- **Tasks:** 2 (TDD: RED + GREEN + integration)
- **Files modified:** 8

## Accomplishments

- Created `memory/effectiveness.py` with EffectivenessStore class: `record()`, `get_aggregated_stats()`, `get_task_records()` — all async, all gracefully degrading
- Wired fire-and-forget tracking into `ToolRegistry.execute()` using `asyncio.create_task()` — tool result returns before SQLite write completes (EFFT-02)
- Added `POST /api/effectiveness/record` and `GET /api/effectiveness/stats` endpoints for MCP PostToolUse hook tracking (EFFT-03)
- Added `learning_min_evidence` and `learning_quarantine_confidence` config fields to Settings
- 14 tests, all passing — covers schema validation, aggregation, graceful degradation, timing, failure tracking

## Task Commits

Each task was committed atomically:

1. **TDD RED: Failing tests** - `7deeebc` (test)
2. **Task 1: EffectivenessStore implementation** - `8ea9ba3` (feat)
3. **Task 2: ToolRegistry wiring + dashboard endpoints** - `1544f18` (feat)

## Files Created/Modified

- `memory/effectiveness.py` — EffectivenessStore with async SQLite, graceful degradation, aggregation queries
- `tests/test_effectiveness.py` — 14 tests covering EFFT-01 through EFFT-05 (2 classes, 319 lines)
- `tools/registry.py` — Added asyncio/time imports, effectiveness_store param, perf_counter_ns timing, fire-and-forget tracking
- `agent42.py` — EffectivenessStore import, initialization, wiring into tool_registry and create_app
- `dashboard/server.py` — POST /api/effectiveness/record and GET /api/effectiveness/stats endpoints
- `requirements.txt` — Added aiosqlite>=0.20.0 and instructor>=1.3.0
- `core/config.py` — Added learning_min_evidence (int=3) and learning_quarantine_confidence (float=0.6) to Settings
- `.env.example` — Added LEARNING_MIN_EVIDENCE and LEARNING_QUARANTINE_CONFIDENCE with documentation

## Decisions Made

- Fire-and-forget via `asyncio.create_task()` is non-negotiable — synchronous SQLite writes would add 300-1500ms per tool call; the tracking must never appear in the tool execution latency budget
- `EffectivenessStore.record()` wraps everything in `try/except Exception` — the tracking subsystem is non-critical, tool execution must always succeed regardless of DB state
- Rate limiter `record()` call moved to fire only when `result.success=True` — failures should not consume rate limit budget
- `get_task_context()` is lazy-imported inside `execute()` to prevent circular imports (the `memory` module already imports from `core`)
- `instructor` dependency added in Plan 01 (needed by Plan 02 learning pipeline) to consolidate all new deps in one PR

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] CRLF line endings required binary-mode file operations on Windows**
- **Found during:** Task 1 and Task 2 (all file modifications)
- **Issue:** `tools/registry.py` and `agent42.py` use CRLF line endings (Windows-origin). Python string replacements with `\n` did not match. Initial import additions also silently failed.
- **Fix:** All file edits done via binary (`rb`/`wb`) mode with `\r\n` sequences in replacement strings. All Python scripts use binary I/O.
- **Files modified:** tools/registry.py, agent42.py
- **Verification:** `python -m pytest tests/test_effectiveness.py -x -q` — 14 passed
- **Committed in:** 1544f18 (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking — Windows CRLF)
**Impact on plan:** The CRLF issue affected multiple file edit attempts but was resolved cleanly. No scope change, no functionality change.

## Issues Encountered

- Pre-existing test failure in `tests/test_auth_flow.py::TestAuthIntegration::test_protected_endpoint_requires_auth` (returns 404 instead of 401) — confirmed pre-existing before our changes, logged to deferred items, not our regression.

## Next Phase Readiness

- Plan 02 (learning extraction) can now read from `tool_invocations` table via `EffectivenessStore.get_task_records()` and `get_aggregated_stats()`
- `instructor` dependency already installed — ready for structured LLM extraction
- Config fields (`learning_min_evidence`, `learning_quarantine_confidence`) already wired to environment variables

---
*Phase: 21-effectiveness-tracking-and-learning-extraction*
*Completed: 2026-03-17*
