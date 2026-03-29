---
phase: 25-memory-bridge
plan: 02
subsystem: memory
tags: [fastapi, memory-bridge, sidecar, recall, learn-async, http-routes, bearer-auth, pytest, scope-isolation]
provides:
  - POST /memory/recall route with Bearer auth — scoped memory retrieval via MemoryBridge
  - POST /memory/store route with Bearer auth — direct learning persistence via qdrant
  - SidecarOrchestrator.execute_async() with recall (200ms timeout) before execution and learn_async (fire-and-forget) after callback
  - 28-test suite covering MEM-01 through MEM-05 requirements
requires:
  - core/memory_bridge.py (Phase 25-01 output)
  - core/sidecar_models.py with MemoryRecallRequest/Response, MemoryStoreRequest/Response
affects: [sidecar-routes, paperclip-adapter, phase-27-end-to-end]
tech-stack:
  added: []
  patterns: [asyncio-wait-for-200ms-timeout, asyncio-create-task-fire-and-forget, shared-instance-per-factory, fastapi-depends-auth-on-routes, pytest-asyncio-run-pattern]
key-files:
  created:
    - tests/test_memory_bridge.py
  modified:
    - dashboard/sidecar.py
    - core/sidecar_orchestrator.py
key-decisions:
  - "MemoryBridge instantiated once in create_sidecar_app() and shared between HTTP routes and SidecarOrchestrator to avoid duplicate store connections (pitfall P6)"
  - "learn_async fired via asyncio.create_task AFTER _post_callback in execute_async finally block — callback is never delayed by learning extraction (D-05)"
  - "asyncio.wait_for timeout=0.2 used in both the HTTP route and execute_async for consistent 200ms enforcement (MEM-02)"
  - "memory/store route gracefully returns stored=False when embeddings/qdrant unavailable rather than raising"
duration: 18min
completed: 2026-03-29
requirements: [MEM-01, MEM-02, MEM-03, MEM-04, MEM-05]
---

# Phase 25 Plan 02: MemoryBridge Wiring and Tests Summary

**MemoryBridge wired into sidecar HTTP routes (/memory/recall, /memory/store) and SidecarOrchestrator.execute_async() with 200ms recall timeout and fire-and-forget learn_async, plus 28-test suite proving all five MEM requirements.**

## Performance

- **Duration:** ~18 minutes
- **Tasks:** 2 completed
- **Files modified:** 2 modified, 1 created

## Accomplishments

- Extended `dashboard/sidecar.py`:
  - Instantiates `MemoryBridge(memory_store=memory_store)` once in `create_sidecar_app()` — shared instance prevents duplicate connections
  - Added `POST /memory/recall` route: uses `asyncio.wait_for(memory_bridge.recall(...), timeout=0.2)`, requires `Depends(get_current_user)`, returns `MemoryRecallResponse` (empty `[]` when memory infrastructure unavailable)
  - Added `POST /memory/store` route: embeds text, writes to Qdrant KNOWLEDGE collection via `asyncio.to_thread`, requires Bearer auth, graceful `stored=False` on any failure
  - Passes `memory_bridge` to `SidecarOrchestrator` so both routes and orchestrator share the same instance

- Extended `core/sidecar_orchestrator.py`:
  - Added `import asyncio` and `from core.memory_bridge import MemoryBridge`
  - `__init__` now accepts `memory_bridge: Any = None` parameter
  - `execute_async()` Step 1: recall with `asyncio.wait_for(..., timeout=0.2)` before execution stub, timeout/exception caught and logged, execution always continues
  - `execute_async()` Step 4 (in `finally`): `asyncio.create_task(memory_bridge.learn_async(...))` fired AFTER `_post_callback` — callback never delayed

- Created `tests/test_memory_bridge.py` with 28 tests across 5 classes:
  - `TestMemoryBridgeRecall` (MEM-01): 6 tests covering recall returns list, graceful degradation paths, embed_text invocation, and memory item shape
  - `TestMemoryBridgeTimeout` (MEM-02): 2 tests — timeout causes empty list, orchestrator proceeds when recall times out
  - `TestMemoryBridgeLearn` (MEM-03): 5 tests — fire-and-forget safety, empty inputs skip embed, failure logging, orchestrator fires learn_async after callback
  - `TestMemoryRoutes` (MEM-04): 9 tests — 200/401/422 status codes, missing memory_store returns empty, memory items returned from mock hits
  - `TestMemoryScopeIsolation` (MEM-05): 6 tests — ValueError on empty agent_id, FieldCondition with agent_id present, different agents produce different filters, company_id filter present/absent

## Task Commits

1. **Task 1: Wire MemoryBridge into sidecar routes and orchestrator** - `912dfa6`
2. **Task 2: Create comprehensive test suite for MEM-01 through MEM-05** - `6028fe1`

## Files Created/Modified

- `/c/Users/rickw/projects/agent42/dashboard/sidecar.py` — Added asyncio, MemoryBridge imports, memory routes, shared bridge instantiation
- `/c/Users/rickw/projects/agent42/core/sidecar_orchestrator.py` — Added asyncio/MemoryBridge imports, memory_bridge param, recall+learn_async in execute_async
- `/c/Users/rickw/projects/agent42/tests/test_memory_bridge.py` — 28-test suite (498 lines) covering MEM-01 through MEM-05

## Decisions & Deviations

**Decisions:**

- Shared MemoryBridge instance: one `MemoryBridge(memory_store=...)` created in `create_sidecar_app()` and passed to both the closure routes and `SidecarOrchestrator`. This prevents multiple embedding model loads and keeps Qdrant connection count stable.
- Timeout enforcement: both the HTTP route and orchestrator use `asyncio.wait_for(..., timeout=0.2)` identically — consistent 200ms limit across all recall paths.
- Fire-and-forget placement: `asyncio.create_task(learn_async(...))` is inside the `finally` block but after `_post_callback`. This guarantees Paperclip gets its callback without waiting for learning extraction, and the task still runs on the event loop.

**Deviations:**

None — plan executed exactly as written.

## Known Stubs

None — the execution stub in `execute_async()` (`result = {"summary": f"Executed task for agent..."}`) was already present from Phase 24 and is documented as intentional. The memory wiring (recall count in `recalledMemories` field) is functional, not a stub. Full AgentRuntime integration is deferred to a later phase (D-04).

## Self-Check: PASSED

- `dashboard/sidecar.py` contains `from core.memory_bridge import MemoryBridge`: PASSED
- `dashboard/sidecar.py` contains `@app.post("/memory/recall"`: PASSED
- `dashboard/sidecar.py` contains `@app.post("/memory/store"`: PASSED
- `core/sidecar_orchestrator.py` contains `self.memory_bridge = memory_bridge`: PASSED
- `core/sidecar_orchestrator.py` contains `asyncio.wait_for(` with `timeout=0.2`: PASSED
- `core/sidecar_orchestrator.py` contains `asyncio.create_task(`: PASSED
- `tests/test_memory_bridge.py` exists with 28 test methods: PASSED
- `python -m pytest tests/test_memory_bridge.py -x -q` exits 0: PASSED (28 passed)
- `python -m pytest tests/test_sidecar.py tests/test_memory_bridge.py -x -q` exits 0: PASSED (54 passed)
- Commits 912dfa6 and 6028fe1 exist in git log: PASSED
