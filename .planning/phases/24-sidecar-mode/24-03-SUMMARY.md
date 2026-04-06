---
phase: 24-sidecar-mode
plan: 03
subsystem: cli
tags: [cli, sidecar, testing, fastapi, paperclip, pytest]
provides:
  - --sidecar and --sidecar-port CLI flags wired through agent42.py main()
  - Agent42.__init__ sidecar=bool and sidecar_port=int|None parameters
  - Sidecar branch in Agent42.start() (if self.sidecar) before dashboard branch
  - configure_sidecar_logging() called before Agent42 construction in sidecar mode
  - 26-test suite covering SIDE-01 through SIDE-09 (all requirements)
affects: [sidecar-startup, cli-usage, all-9-side-requirements]
tech-stack:
  added: []
  patterns: [argparse-additive-flags, inspect-signature-testing, autouse-cleanup-fixture]
key-files:
  created:
    - tests/test_sidecar.py
  modified:
    - agent42.py
    - core/sidecar_models.py
key-decisions:
  - "SIDECAR_ENABLED env var supported as alternative to --sidecar flag via `is_sidecar = args.sidecar or settings.sidecar_enabled`"
  - "configure_sidecar_logging() called BEFORE Agent42() construction to ensure JSON formatter active during __init__ logging"
  - "Test uses pre-register approach for HTTP idempotency test — TestClient runs background tasks synchronously so unregister_run fires before second request"
  - "ExecuteResponse model needed populate_by_name=True to accept snake_case construction (Pydantic v2 requires this with aliased fields)"
duration: 12min
completed: 2026-03-29
requirements: [SIDE-01, SIDE-08]
---

# Phase 24 Plan 03: CLI Wiring and Test Suite Summary

**--sidecar CLI flag wired through agent42.py with three-mode branch (sidecar/dashboard/headless), plus 26-test suite covering all SIDE-01 through SIDE-09 requirements.**

## Performance

- **Duration:** ~12 minutes
- **Tasks:** 2 completed
- **Files modified:** 3 (1 created, 2 modified)

## Accomplishments

- Added `--sidecar` and `--sidecar-port` argparse arguments to `main()` in `agent42.py`
- Extended `Agent42.__init__` signature with `sidecar: bool = False` and `sidecar_port: int | None = None` parameters — core service initialization unchanged per D-02/SIDE-08
- Added `if self.sidecar:` branch in `Agent42.start()` before existing `elif not self.headless:` — creates sidecar app, starts uvicorn on `sidecar_port`, logs URL
- `configure_sidecar_logging()` called before `Agent42()` construction when sidecar is active, so JSON formatter installs before any `__init__` logging
- `SIDECAR_ENABLED` env var supported as alternative activation path via `is_sidecar = args.sidecar or settings.sidecar_enabled`
- Created `tests/test_sidecar.py` with 26 tests across 8 test classes covering all 9 SIDE-* requirements
- Fixed `ExecuteResponse` model — missing `populate_by_name=True` caused snake_case construction to silently use default `""` instead of the provided value

## Task Commits

1. **Task 1: Wire --sidecar CLI flag and Agent42 sidecar branch** - `527f972`
2. **Task 2: Create comprehensive sidecar test suite** - `434dfe9`

## Files Created/Modified

- `/c/Users/rickw/projects/agent42/agent42.py` — Added `--sidecar`/`--sidecar-port` args, extended `Agent42.__init__`, added sidecar branch to `start()`, updated `main()` instantiation
- `/c/Users/rickw/projects/agent42/tests/test_sidecar.py` — 26 tests: TestSidecarConfig, TestSidecarModels, TestSidecarHealth, TestSidecarExecute, TestIdempotencyGuard, TestSidecarJsonLogging, TestSidecarAppStructure, TestCoreServicesInit
- `/c/Users/rickw/projects/agent42/core/sidecar_models.py` — Added `model_config = ConfigDict(populate_by_name=True)` to `ExecuteResponse` (bug fix)

## Decisions & Deviations

**Decisions:**

- `is_sidecar = args.sidecar or settings.sidecar_enabled` supports both CLI flag and env var activation, giving operators flexibility for Docker deployments where CLI flags are inconvenient.
- `qdrant_store=self.memory_store._qdrant` passes the QdrantStore reference via the MemoryStore's `_qdrant` attribute (confirmed in `memory/store.py` line 61).

**Deviations:**

**1. [Rule 1 - Bug] Fixed ExecuteResponse missing populate_by_name=True**

- **Found during:** Task 2 (RED phase — test revealed `externalRunId: ""` in response)
- **Issue:** `ExecuteResponse` didn't have `model_config = ConfigDict(populate_by_name=True)`, so `ExecuteResponse(external_run_id=ctx.run_id)` silently used the default `""` — Pydantic v2 requires `populate_by_name=True` to accept snake_case field names when aliases are defined
- **Fix:** Added `model_config = ConfigDict(populate_by_name=True)` to `ExecuteResponse`
- **Files modified:** `core/sidecar_models.py`
- **Commit:** `434dfe9`

**2. [Rule 1 - Bug] Fixed incorrect 403 assumption in test**

- **Found during:** Task 2 (test failed — got 401 instead of expected 403)
- **Issue:** Plan comment stated "HTTPBearer returns 403 when header is missing" — actual behavior is 401 (HTTPBearer raises `HTTP_401_UNAUTHORIZED` for missing credentials in FastAPI)
- **Fix:** Renamed test to `test_execute_without_auth_returns_401` and changed assertion to `assert resp.status_code == 401`
- **Files modified:** `tests/test_sidecar.py`
- **Commit:** `434dfe9`

**3. [Rule 1 - Bug] Fixed HTTP idempotency test timing issue**

- **Found during:** Task 2 (second request returned `deduplicated=False` instead of `True`)
- **Issue:** `TestClient` runs `BackgroundTasks` synchronously before returning the response, so `execute_async` runs and calls `unregister_run` before the second HTTP request is made — the run was no longer registered as a duplicate
- **Fix:** Changed test to pre-register the run before sending the request, correctly simulating an in-flight job
- **Files modified:** `tests/test_sidecar.py`
- **Commit:** `434dfe9`

## Pre-existing Test Failures (Not Caused by This Plan)

- `tests/test_app_git.py::TestAppManagerGit::test_persistence_with_git_fields` — Pre-existing pathlib `ValueError` on Windows tempdir paths (documented in Plans 01 and 02)
- `tests/test_app_manager.py::TestAppManager::test_persistence` — Pre-existing pathlib `ValueError` on Windows tempdir paths (confirmed via `git stash` rollback)

## Known Stubs

None — this plan adds CLI wiring and tests. The `execute_async()` stub in `core/sidecar_orchestrator.py` is pre-existing from Plan 02 and intentionally deferred to Phase 25-27.

## Phase 24 Completion

All three plans (24-01, 24-02, 24-03) are complete. Phase 24 delivers:

- **SIDE-09**: Config fields (sidecar_port, api_url, sidecar_enabled) — Plan 01
- **SIDE-07**: SidecarJsonFormatter with ANSI stripping — Plan 01
- **SIDE-02**: Pydantic v2 models with camelCase aliases — Plan 01
- **SIDE-03**: 202 Accepted response — Plan 02
- **SIDE-04**: Structured health endpoint — Plan 02
- **SIDE-05**: Bearer auth on execute, health exempt — Plan 02
- **SIDE-06**: TTL-based idempotency guard — Plan 02
- **SIDE-01**: No dashboard routes in sidecar app — Plan 02
- **SIDE-08**: Core service init identical across modes — Plan 03

## Self-Check: PASSED

- `agent42.py` contains `--sidecar` flag: PASSED
- `agent42.py` contains `if self.sidecar:` before `elif not self.headless:`: PASSED
- `agent42.py` contains `configure_sidecar_logging()`: PASSED
- `tests/test_sidecar.py` exists (300 lines, 26 tests): PASSED
- `core/sidecar_models.py` has `populate_by_name=True` on ExecuteResponse: PASSED
- Commits 527f972 (Task 1) and 434dfe9 (Task 2) exist in git log: PASSED
- `python -m pytest tests/test_sidecar.py -x -q` exits 0: PASSED
- CLI integration check: `python -c "import agent42; import inspect; sig = inspect.signature(agent42.Agent42.__init__); assert 'sidecar' in sig.parameters; print('CLI integration OK')"` exits 0: PASSED
