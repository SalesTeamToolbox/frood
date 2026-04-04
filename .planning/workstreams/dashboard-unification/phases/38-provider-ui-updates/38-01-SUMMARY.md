---
phase: 38-provider-ui-updates
plan: 01
subsystem: dashboard
tags: [provider-ui, synthetic-api, provider-status, strongwall-cleanup, test-scaffold]

# Dependency graph
requires: []
provides:
  - "GET /api/providers/synthetic/models — returns model catalog with count, free_count, cached_at, capability_mapping"
  - "GET /api/settings/provider-status — returns per-provider status with name, label, configured, status fields"
  - "StrongWall.ai comment removed from dashboard/server.py costs section"
  - "app.js.backup deleted from dashboard/frontend/dist"
  - "tests/test_provider_ui.py with 19 tests covering PROVIDER-01 through PROVIDER-05"
affects: [38-02-frontend-restructure]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Request-time module accessor: import core.agent_manager as _am; client = _am._synthetic_client (avoids module-load-time None capture)"
    - "Inline import pattern: import httpx and import os inside function body for graceful degradation (per /api/settings/storage pattern)"
    - "Admin auth override in tests: app.dependency_overrides[require_admin] = lambda: AuthContext(user='test-admin')"
    - "Patch at module attribute: patch('core.agent_manager._synthetic_client', ...) for request-time accessor testing"

key-files:
  created:
    - tests/test_provider_ui.py
  modified:
    - dashboard/server.py

key-decisions:
  - "Request-time accessor for _synthetic_client — avoids import-time None capture when module hasn't fully initialized"
  - "import os inside get_provider_status body — os not at module level in server.py, inline import required (Rule 1 auto-fix)"
  - "TestProvidersTabStructure tests intentionally red — they verify Plan 38-02 output, TDD red phase for UI structure"

requirements-completed: [PROVIDER-01, PROVIDER-03, PROVIDER-04]

# Metrics
duration: 14min
completed: 2026-04-04
---

# Phase 38 Plan 01: StrongWall Cleanup and Backend Provider Endpoints Summary

**StrongWall references removed, app.js.backup deleted, two new FastAPI endpoints added (GET /api/providers/synthetic/models and GET /api/settings/provider-status), and 19-test scaffold created covering PROVIDER-01 through PROVIDER-05**

## Performance

- **Duration:** 14 min
- **Started:** 2026-04-04T18:40:18Z
- **Completed:** 2026-04-04T18:54:01Z
- **Tasks:** 2/2
- **Files modified:** 2 (dashboard/server.py, tests/test_provider_ui.py)
- **Commits:** 2 (ef1928d, dd27c4f)

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | StrongWall cleanup + two new backend endpoints | ef1928d | dashboard/server.py |
| 2 | Test scaffold for Phase 38 backend endpoints and UI structure | dd27c4f | dashboard/server.py (bug fix), tests/test_provider_ui.py (new) |

## What Was Built

### PROVIDER-01: StrongWall cleanup
- Removed `(e.g. StrongWall $16/mo)` from `flat_rate` comment in `get_analytics()` (line 1344)
- Deleted untracked `dashboard/frontend/dist/app.js.backup` (stale backup, not served)

### PROVIDER-03: Synthetic models endpoint
- Added `GET /api/providers/synthetic/models` inside `create_app` under the Providers section
- Uses request-time accessor `import core.agent_manager as _am; client = _am._synthetic_client` to avoid import-time None capture
- Returns structured dict: `models`, `cached_at`, `count`, `free_count`, `capability_mapping`
- Gracefully returns empty result when `_synthetic_client is None`

### PROVIDER-04: Provider status endpoint
- Added `GET /api/settings/provider-status` inside `create_app`
- Covers 4 providers: claudecode (presence-only), synthetic, anthropic, openrouter
- Each provider returns `name`, `label`, `configured`, `status` fields
- Maps HTTP responses to status strings: ok, auth_error, unreachable, timeout, unconfigured
- Uses inline `import httpx` and `import os` per graceful degradation pattern

### Test scaffold (tests/test_provider_ui.py)
- `TestNoStrongwallArtifacts` (2 tests): PROVIDER-01 file-system checks
- `TestProvidersTabStructure` (8 tests): PROVIDER-02 UI structure — **intentionally red** until Plan 38-02 modifies app.js
- `TestSyntheticModelsEndpoint` (3 tests): PROVIDER-03 endpoint tests with mock client
- `TestProviderStatusEndpoint` (4 tests): PROVIDER-04 endpoint tests with env patching
- `TestAgentsModelsEndpoint` (2 tests): PROVIDER-05 /api/agents/models coverage
- **11 non-UI tests pass immediately; 8 PROVIDER-02 tests are red (TDD red phase)**

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Missing `import os` inside `get_provider_status` function body**
- **Found during:** Task 2 verification (pytest run)
- **Issue:** `os` is not imported at module level in `dashboard/server.py`. The plan noted "import os is already available at module level" but this was incorrect — os is only imported inline in specific functions throughout the file.
- **Fix:** Added `import os` at the top of `get_provider_status` function body, alongside `import time as _time` and `import httpx`
- **Files modified:** dashboard/server.py
- **Commit:** dd27c4f (included with test commit)

## Known Stubs

None — both endpoints return structured data with no placeholder values.

## Self-Check: PASSED
