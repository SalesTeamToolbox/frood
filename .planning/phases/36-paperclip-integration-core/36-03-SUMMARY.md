---
phase: 36-paperclip-integration-core
plan: "03"
subsystem: paperclip-integration
tags: [testing, sidecar, manifest, worker, phase36, paperclip]
dependency_graph:
  requires: [36-01, 36-02]
  provides: [test-coverage-paperclip-phase36]
  affects: [ci-validation, paperclip-requirements]
tech_stack:
  added: []
  patterns: [pytest-fastapi-testclient, vitest-static-analysis, dependency-override-pattern]
key_files:
  created:
    - tests/test_sidecar_phase36.py
    - plugins/agent42-paperclip/src/__tests__/manifest.test.ts
    - plugins/agent42-paperclip/src/__tests__/worker-handlers.test.ts
  modified:
    - dashboard/sidecar.py
    - plugins/agent42-paperclip/vitest.config.ts
    - plugins/agent42-paperclip/tests/data-handlers.test.ts
    - plugins/agent42-paperclip/tests/team.test.ts
    - plugins/agent42-paperclip/tests/tools.test.ts
    - plugins/agent42-paperclip/tests/worker.test.ts
decisions:
  - "Tests for get_sidecar_settings use full ADMIN_CONFIGURABLE_KEYS dict from get_masked_keys() — mock provides complete key set"
  - "worker-handlers.test.ts uses static source analysis (readFileSync) rather than runtime execution — Paperclip SDK runtime not available in test environment"
  - "TypeScript tests placed in src/__tests__/ per plan spec; vitest.config.ts updated to include that directory"
  - "Pre-existing manifest.json import failures in 4 test files fixed as Rule 1/3 deviation — manifest.json deleted in Plan 36-01 without updating imports"
metrics:
  duration: "~10 minutes"
  completed: "2026-04-03"
  tasks_completed: 2
  files_created: 3
  files_modified: 8
  commits: 2
---

# Phase 36 Plan 03: Test Coverage for Paperclip Integration Summary

**One-liner:** 21 Python + 97 TypeScript tests validate all Phase 36 PAPERCLIP-01 through PAPERCLIP-05 requirements with zero regressions.

## What Was Built

### Task 1: Python tests for sidecar endpoints and dashboard gate

`tests/test_sidecar_phase36.py` — 21 pytest tests organized in 5 classes:

- `TestSidecarTools` (3 tests): GET /tools with null registry, with data, disabled flag mapping
- `TestSidecarSkills` (3 tests): GET /skills with null loader, with data, multiple skills
- `TestSidecarApps` (5 tests): GET /apps, POST start/stop with/without app_manager
- `TestSidecarSettings` (6 tests): GET/POST /settings, invalid key 400, valid key 200, no-store 503, all ADMIN_CONFIGURABLE_KEYS
- `TestDashboardGate` (4 tests): 503 in sidecar mode, non-503 in standalone, Settings flag, sidecar_port in response

All tests use `FastAPI.dependency_overrides[get_current_user]` to bypass auth for unit testing.

### Task 2: TypeScript tests for manifest and worker handlers

`plugins/agent42-paperclip/src/__tests__/manifest.test.ts` — 15 vitest tests:
- 9 tests for slot declarations (workspace-terminal, sandboxed-apps, tools-skills, agent42-settings, workspace-nav + 4 existing)
- 6 tests for capabilities (ui.page.register, ui.sidebar.register + 4 existing)

`plugins/agent42-paperclip/src/__tests__/worker-handlers.test.ts` — 17 vitest tests:
- 7 tests for data handler registrations (tools-skills, apps-list, agent42-settings + client method calls)
- 6 tests for action handler registrations (app-start, app-stop, update-agent42-settings, terminal-start, terminal-input, terminal-close)
- 4 tests for terminal stream (emit pattern, Map tracking, session token auth, cleanup)

## Verification

```
python -m pytest tests/test_sidecar_phase36.py -x -q
21 passed, 46 warnings

cd plugins/agent42-paperclip && npm test
Test Files  7 passed (7)
Tests  97 passed (97)
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed get_sidecar_settings passing dict to str field**
- **Found during:** Task 1 (test revealed ValidationError at runtime)
- **Issue:** `dashboard/sidecar.py` line 697-706 called `masked.get(key_name, "")` which returns `{"configured": bool, "source": str, "masked_value": str}` (a dict) instead of the masked value string. Pydantic raised `ValidationError: masked_value — Input should be a valid string`
- **Fix:** Changed to `masked.get(key_name, {}).get("masked_value", "")` and `masked.get(key_name, {}).get("configured", False)` to correctly extract fields from the nested dict
- **Files modified:** `dashboard/sidecar.py`
- **Commit:** d252a3d

**2. [Rule 1 - Bug] Fixed 4 existing test files importing deleted manifest.json**
- **Found during:** Task 2 (npm test showed 4 failing suites)
- **Issue:** Plan 36-01 deleted `manifest.json` and replaced it with `manifest.ts`, but 4 existing test files still imported `from "../manifest.json" with { type: "json" }`. Tests failed with ENOENT.
- **Fix:** Updated imports to `import manifest from "../dist/manifest.js"` in all 4 files. Also fixed 1 test that read `manifest.json` via `readFileSync` to use the already-imported `manifest` object.
- **Files modified:** `tests/data-handlers.test.ts`, `tests/team.test.ts`, `tests/tools.test.ts`, `tests/worker.test.ts`
- **Commit:** c098c72

**3. [Deviation] TypeScript test file location**
- **Planned:** `src/__tests__/manifest.test.ts` and `src/__tests__/worker-handlers.test.ts`
- **Issue:** vitest.config.ts only included `tests/**/*.test.ts` — the `src/__tests__/` directory was not covered
- **Fix:** Updated `vitest.config.ts` to add `src/__tests__/**/*.test.ts` to include pattern, preserving plan-specified file paths
- **Files modified:** `vitest.config.ts`

## Known Stubs

None. All test assertions verify real endpoint behavior and real source patterns.

## Commits

| Hash | Message |
|------|---------|
| d252a3d | test(36-03): add Python tests for Phase 36 sidecar endpoints and dashboard gate |
| c098c72 | test(36-03): add TypeScript tests for manifest slots, capabilities, and worker handlers |

## Self-Check: PASSED
