---
phase: 50-strip-harness-features
plan: "04"
subsystem: testing
tags: [pytest, test-cleanup, harness-removal, ruff]

# Dependency graph
requires:
  - phase: 50-strip-harness-features/50-01
    provides: server.py harness routes removed
  - phase: 50-strip-harness-features/50-02
    provides: app.js harness UI removed
  - phase: 50-strip-harness-features/50-03
    provides: auth.py, agent42.py harness code removed
provides:
  - Clean test suite with zero harness feature tests
  - Full regression validation that stripped dashboard works
  - Green test suite (2025 passed, 10 skipped, 0 failed)
affects: [frood-dashboard, phase-51-onward]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Delete test files entirely when all tests target removed features"
    - "Keep core module tests when module has non-server callers"
    - "Delete endpoint tests when route is removed from server.py"

key-files:
  created: []
  modified:
    - tests/test_device_auth.py (removed TestDeviceAPIKeyAuth, TestDashboardAPIKeyEndpoints)
    - tests/test_provider_ui.py (removed TestAgentsModels)
    - tests/test_auth_flow.py (fixed imports for removed auth.py functions)
    - tests/test_workspace_registry.py (retained core module tests only)
  deleted:
    - tests/test_cc_bridge.py
    - tests/test_cc_chat_ui.py
    - tests/test_cc_layout.py
    - tests/test_cc_pty.py
    - tests/test_cc_tool_use.py
    - tests/test_ide_html.py
    - tests/test_ide_workspace.py
    - tests/test_rewards_api.py
    - tests/test_websocket_terminal.py
    - tests/test_unified_agents.py
    - tests/test_standalone_mode.py
    - tests/test_github_accounts.py
    - tests/test_github_oauth.py
    - tests/test_remote_status.py

key-decisions:
  - "Delete test_github_accounts.py and test_github_oauth.py — no callers for core modules outside server.py and tests"
  - "Keep test_cc_memory_sync.py — TestDashboardCcSync is self-contained (reimplements logic locally, no server.py import)"
  - "Keep test_workspace_registry.py — tests core WorkspaceRegistry module which may be reused"
  - "Delete test_remote_status.py — /api/remote/status endpoint removed in plans 01-03, file not in original plan"

patterns-established:
  - "When a harness route is removed and the core module has no other callers, delete the entire test file"
  - "When a test class checks for source-code patterns of removed functions, delete those test classes"

requirements-completed: [STRIP-09, STRIP-11, CLEAN-04]

# Metrics
duration: 20min
completed: 2026-04-07
---

# Phase 50 Plan 04: Test Suite Cleanup Summary

**Deleted 14 harness test files and cleaned 4 mixed test files; full test suite passes with 2025 tests (0 failures)**

## Performance

- **Duration:** ~20 min
- **Started:** 2026-04-07T19:15:00Z
- **Completed:** 2026-04-07T19:35:15Z
- **Tasks:** 2 (plus 1 deviation fix)
- **Files modified:** 17 deleted + 4 modified

## Accomplishments

- Deleted 11 harness-only test files (cc_bridge, cc_chat_ui, cc_layout, cc_pty, cc_tool_use, ide_html, ide_workspace, rewards_api, websocket_terminal, unified_agents, standalone_mode)
- Deleted 3 additional test files: test_github_accounts.py, test_github_oauth.py (no callers outside server.py), test_remote_status.py (testing removed endpoint — deviation fix)
- Cleaned 4 mixed test files: removed harness test classes, kept intelligence layer tests
- Full test suite green: 2025 passed, 10 skipped, 0 failed
- Ruff lint clean across all dashboard/server.py, auth.py, websocket_manager.py, agent42.py

## Task Commits

1. **Task 1: Delete harness-only test files and clean mixed test files** - `8387d7b` (feat)
2. **Task 2 deviation fix: Delete test_remote_status.py (removed endpoint)** - `36dca53` (fix)

## Files Deleted

- `tests/test_cc_bridge.py` - Claude Code bridge tests (removed feature)
- `tests/test_cc_chat_ui.py` - CC chat UI tests (removed feature)
- `tests/test_cc_layout.py` - CC layout tests (removed feature)
- `tests/test_cc_pty.py` - PTY terminal tests (removed feature)
- `tests/test_cc_tool_use.py` - CC tool use tests (removed feature)
- `tests/test_ide_html.py` - IDE HTML tests (removed feature)
- `tests/test_ide_workspace.py` - IDE workspace tests (removed feature)
- `tests/test_rewards_api.py` - Rewards API tests (removed feature)
- `tests/test_websocket_terminal.py` - WebSocket terminal tests (removed feature)
- `tests/test_unified_agents.py` - Unified agents tests (removed feature)
- `tests/test_standalone_mode.py` - Standalone mode tests (standalone_guard removed)
- `tests/test_github_accounts.py` - GitHub accounts tests (no callers outside server.py)
- `tests/test_github_oauth.py` - GitHub OAuth tests (no callers outside server.py)
- `tests/test_remote_status.py` - Remote status tests (/api/remote/status route removed)

## Files Modified

- `tests/test_device_auth.py` - Removed TestDeviceAPIKeyAuth, TestDashboardAPIKeyEndpoints; kept DeviceStore tests
- `tests/test_provider_ui.py` - Removed TestAgentsModels (/api/agents/models removed); kept provider status tests
- `tests/test_auth_flow.py` - Fixed imports for removed auth.py functions
- `tests/test_workspace_registry.py` - Retained core WorkspaceRegistry module tests only

## Decisions Made

- `test_github_accounts.py` and `test_github_oauth.py` deleted: grep confirmed no callers for `core.github_accounts` or `core.github_oauth` outside server.py and tests — both modules were exclusively used by removed harness routes
- `test_cc_memory_sync.py` kept entirely: `TestDashboardCcSync` class reimplements `_load_cc_sync_status` logic locally — does not import from server.py, so it's safe and tests real intelligence layer behavior
- `test_workspace_registry.py` kept: core `WorkspaceRegistry` module may be reused; only endpoint tests were the concern, but previous agent already retained only core module tests

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Deleted test_remote_status.py — tests for removed /api/remote/status endpoint**

- **Found during:** Task 2 (full validation)
- **Issue:** `test_remote_status.py` was not in the plan's list of files to handle, but 3 of its tests checked for source-code patterns (`AGENT42_REMOTE_HOST`, `async def remote_status`, `/api/remote/status`) that were removed from `dashboard/server.py` in plans 01-03. These tests were failing with AssertionError.
- **Fix:** Deleted `tests/test_remote_status.py` entirely — all 3 failing tests were testing removed functionality. (2 remaining tests in the file tested inline logic with no server.py dependency — those are now also gone since the whole file was deleted.)
- **Files modified:** `tests/test_remote_status.py` (deleted)
- **Verification:** Full test suite re-run: 2025 passed, 10 skipped, 0 failed
- **Committed in:** `36dca53` (separate fix commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - bug: test for removed feature)
**Impact on plan:** Necessary fix — file was not in the original plan because the planner didn't know /api/remote/status had been removed. No scope creep.

## Issues Encountered

None beyond the deviation above.

## Validation Results

- **Line counts (vs baselines):**
  - server.py: 2,496 lines (baseline 6,455 — 3,959 removed)
  - auth.py: 175 lines (baseline 218 — 43 removed)
  - app.js: 2,249 lines (baseline 8,924 — 6,675 removed)
  - websocket_manager.py: 64 lines (baseline 101 — 37 removed)
  - agent42.py: 402 lines (baseline 436 — 34 removed)
- **All harness route patterns** grep to 0 in server.py
- **All kept route patterns** (api/memory, api/tools, api/providers, etc.) confirmed present
- **Ruff lint:** zero findings (F401, F841) across all modified files
- **create_app() signature:** imports and calls successfully

## Next Phase Readiness

Phase 50 (strip-harness-features) is COMPLETE. All 4 plans executed:
- 50-01: Removed 16 harness route groups from server.py
- 50-02: Stripped harness UI from app.js
- 50-03: Cleaned auth.py, websocket_manager.py, agent42.py
- 50-04: Cleaned test suite, validated full green test run

The Frood intelligence layer dashboard is now clean — ready for the next phase of development.

---
*Phase: 50-strip-harness-features*
*Completed: 2026-04-07*
