---
phase: 24-sidecar-mode
plan: 02
subsystem: sidecar
tags: [fastapi, httpx, sidecar, paperclip, orchestrator, idempotency, background-tasks]
provides:
  - SidecarOrchestrator class driving the execute-to-callback lifecycle with idempotency guard
  - create_sidecar_app() factory returning an isolated FastAPI app with health and execute routes
  - Module-level idempotency functions (is_duplicate_run, register_run, unregister_run) with TTL-based expiry
  - Callback delivery to Paperclip via httpx.AsyncClient with graceful degradation when PAPERCLIP_API_URL is unset
affects: [24-03, cli-wiring, sidecar-server-startup]
tech-stack:
  added: []
  patterns: [fastapi-app-factory, background-tasks-not-raw-asyncio, lazy-init-httpx-client, module-level-idempotency-dict]
key-files:
  created:
    - core/sidecar_orchestrator.py
    - dashboard/sidecar.py
  modified: []
key-decisions:
  - "SidecarOrchestrator is separate from existing AgentRuntime — Phase 24 provides a stub execution path; full integration deferred to Phase 25-27"
  - "BackgroundTasks used instead of raw asyncio.create_task for proper FastAPI lifecycle management (RESEARCH.md pitfall 3)"
  - "httpx.AsyncClient lazy-initialized per SidecarOrchestrator instance and closed on shutdown event (RESEARCH.md pitfall 6)"
  - "Idempotency guard uses module-level dict (not Redis) — in-memory TTL is sufficient for Phase 24 single-process sidecar"
duration: 5min
completed: 2026-03-29
requirements: [SIDE-02, SIDE-03, SIDE-04, SIDE-05, SIDE-06]
---

# Phase 24 Plan 02: Sidecar HTTP Server and Execution Orchestrator Summary

**Isolated FastAPI sidecar app factory with health (public) and execute (authed) routes backed by a TTL-idempotent SidecarOrchestrator that fires callbacks to Paperclip via httpx.**

## Performance

- **Duration:** ~5 minutes (continuation — Task 1 was pre-committed, Task 2 verified and committed)
- **Tasks:** 2 completed
- **Files modified:** 2 created

## Accomplishments

- Created `core/sidecar_orchestrator.py` with `SidecarOrchestrator` class: lazy-init httpx client, `execute_async()` stub (Phase 24 minimal execution, full runtime in Phase 25-27), and `_post_callback()` that POSTs to `{PAPERCLIP_API_URL}/api/heartbeat-runs/{runId}/callback` with camelCase aliases
- Added module-level idempotency functions (`is_duplicate_run`, `register_run`, `unregister_run`) using a TTL-keyed dict (`RUN_TTL_SECONDS = 3600`) — `_prune_expired_runs()` called on every check
- Created `dashboard/sidecar.py` with `create_sidecar_app()` factory: separate `FastAPI` instance (no dashboard UI, no Swagger/ReDoc), `GET /sidecar/health` public endpoint with Qdrant health probe, `POST /sidecar/execute` with `Depends(get_current_user)` and `status_code=202`
- Idempotency guard in execute endpoint: duplicate `runId` returns `deduplicated=True` without re-executing
- Graceful degradation in `_post_callback`: warning logged and callback skipped when `PAPERCLIP_API_URL` is empty
- All acceptance criteria verified; 86 pre-existing tests still pass (1 pre-existing failure in `test_app_git.py` unrelated to this plan)

## Task Commits

1. **Task 1: Create SidecarOrchestrator for execute-to-callback lifecycle** - `d70aa71`
2. **Task 2: Create sidecar FastAPI app factory with all routes** - `f94678a`

## Files Created/Modified

- `core/sidecar_orchestrator.py` — SidecarOrchestrator class + module-level idempotency guard (is_duplicate_run, register_run, unregister_run, _active_runs); httpx callback delivery to Paperclip
- `dashboard/sidecar.py` — create_sidecar_app() factory with GET /sidecar/health (public) and POST /sidecar/execute (Bearer auth, 202 Accepted, background task execution)

## Decisions & Deviations

**Decisions:**

- `execute_async()` is a stub for Phase 24 — it records the execution shape (result dict + usage dict) but does not wire to `AgentRuntime`. Full integration comes in Phase 25-27 when agent execution logic is wired.
- `BackgroundTasks.add_task()` used instead of `asyncio.create_task()` per RESEARCH.md pitfall 3 — FastAPI's BackgroundTasks integrates with ASGI lifecycle and avoids orphaned coroutines.
- Health endpoint probes `qdrant_store.health_check()` only when the store object is provided — graceful degradation if Qdrant is unavailable matches CLAUDE.md rule.
- `docs_url=None` and `redoc_url=None` on the sidecar FastAPI instance — no API docs exposure in production sidecar per D-01 (minimal attack surface).

**Deviations:**

None — plan executed exactly as written.

## Pre-existing Test Failures (Not Caused by This Plan)

`tests/test_app_git.py::TestAppManagerGit::test_persistence_with_git_fields` — Pre-existing pathlib `ValueError` on Windows tempdir paths. Confirmed failure exists before and after this plan's changes (verified via `git stash` rollback test).

## Known Stubs

- `core/sidecar_orchestrator.py` lines 92-106: `execute_async()` produces a minimal result dict (`summary`, `wakeReason`, `taskId`) without calling `AgentRuntime`. This is intentional for Phase 24 — full execution is wired in Phase 25-27. The stub does POST a callback to Paperclip, so the lifecycle shape is complete.

## Next Phase Readiness

Plan 24-03 (CLI wiring — `--sidecar` flag) can now import:

```python
from dashboard.sidecar import create_sidecar_app
from core.sidecar_orchestrator import SidecarOrchestrator
```

The sidecar app factory accepts the same service objects as `create_app()`, so the CLI wiring plan just needs to pass the already-instantiated stores.

## Self-Check: PASSED

- `core/sidecar_orchestrator.py` exists: PASSED (170 lines, all required symbols present)
- `dashboard/sidecar.py` exists: PASSED (142 lines, all required symbols present)
- Route verification: PASSED (`/sidecar/health` and `/sidecar/execute` confirmed via `create_sidecar_app().routes`)
- Idempotency test: PASSED (`register_run` / `is_duplicate_run` / `unregister_run` all work correctly)
- Commits d70aa71 (Task 1) and f94678a (Task 2) exist in git log: PASSED
