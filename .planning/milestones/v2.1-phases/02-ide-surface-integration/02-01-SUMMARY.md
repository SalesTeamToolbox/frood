---
phase: 02-ide-surface-integration
plan: 01
subsystem: backend/workspace-wiring, frontend/state-management
tags: [python, javascript, websocket, workspace, terminal, cc-chat, state-management]
dependency_graph:
  requires: [01-01-SUMMARY, 01-02-SUMMARY]
  provides: [workspace_id-on-terminal-ws, workspace_id-on-cc-chat-ws, cc-sessions-filter, _activeWorkspaceId, workspace-keyed-state]
  affects: [dashboard/server.py, dashboard/frontend/dist/app.js, tests/test_ide_workspace.py]
tech_stack:
  added: []
  patterns: [workspace-keyed-state-dicts, alias-array-mutation, ws-query-param-routing]
key_files:
  created:
    - tests/test_ide_workspace.py
  modified:
    - dashboard/server.py
    - dashboard/frontend/dist/app.js
decisions:
  - "Used workspace_path local variable in WS handlers to avoid shadowing module-level workspace variable (kept for CC warm-pool and CC panel chat)"
  - "_chat_via_cc helper left using module-level workspace (not workspace_path) — it has no workspace context parameter and is called from the dashboard sidebar chat, not cc_chat_ws"
  - "Legacy CC sessions (no workspace_id field) are always included in workspace_id filter results — backward compatibility for pre-Phase-2 sessions"
  - "_activeWorkspaceId defaults to empty string so all workspace_id query params are conditionally appended — preserves existing behavior until Plan 03 populates it"
  - "State alias helpers mutate existing _ideTabs/termSessions arrays in-place (length=0 then push) — const _ideTabs cannot be reassigned but can be mutated"
metrics:
  duration: "19m"
  completed: "2026-03-24"
  tasks_completed: 2
  tasks_total: 2
  files_modified: 3
---

# Phase 02 Plan 01: IDE Surface Workspace Wiring Summary

**One-liner:** workspace_id query param wired into terminal_ws, cc_chat_ws, and CC session filter on the backend; frontend state promoted to workspace-keyed dicts with _activeWorkspaceId threaded into all IDE fetch/WS URLs.

## What Was Built

### Task 1: Backend workspace_id wiring (server.py)

**terminal_ws handler:**
- Reads `workspace_id` query param after token validation
- Resolves to path via `_resolve_workspace(ws_workspace_id)` → `workspace_path`
- All three cwd assignments (Windows PTY, Unix PTY, PIPE fallback) now use `workspace_path`

**cc_chat_ws handler:**
- Reads `workspace_id` query param after session_id extraction
- Resolves to path via `_resolve_workspace(ws_workspace_id)` → `workspace_path`
- `_read_gsd_workstream(workspace)` updated to `_read_gsd_workstream(workspace_path)`
- Unix PTY cwd uses `workspace_path`
- PIPE mode Windows cwd uses `workspace_path`
- `_save_session` call now persists `"workspace_id": ws_workspace_id or ""` field

**cc_sessions REST endpoint:**
- Signature updated: `workspace_id: str | None = None` optional query param
- When filter provided: includes sessions whose `workspace_id` matches + legacy sessions (no `workspace_id` field — backward compatible with pre-Phase-2 data)
- When no filter: returns all sessions unchanged

**New test file (tests/test_ide_workspace.py):**
- 3 source-scan tests: verify `terminal_ws` reads `workspace_id`, calls `_resolve_workspace`, uses `workspace_path` for cwd
- 3 source-scan tests: verify `cc_chat_ws` reads `workspace_id`, calls `_resolve_workspace`, saves `workspace_id` in session
- 4 integration tests: TestClient with seeded sessions verifies filter logic (matching, legacy, exclusion, unknown workspace)

### Task 2: Frontend state promotion (app.js)

**New globals and workspace-keyed state:**
```javascript
var _activeWorkspaceId = "";        // active workspace (Plan 03 sets this)
var _wsTabState = {};               // { wsId: { tabs: [], activeTab: -1 } }
var _wsTermSessions = {};           // { wsId: [ ...sessions ] }
var _wsTermActiveIdx = {};          // { wsId: number }
```

**New helper functions:**
- `_ensureWsState(wsId)` — lazily initializes per-workspace state buckets
- `_syncAliasesToWorkspace(wsId)` — repopulates the flat `_ideTabs`/`_termSessions` aliases from workspace-keyed state (Plan 03 calls this on tab switch)
- `_saveCurrentWsState()` — snapshots current flat state into the active workspace bucket (Plan 03 calls this before switching)

**workspace_id threading (all conditional on `_activeWorkspaceId !== ""`)**:
- `ideLoadTree()` → `GET /api/ide/tree?path=...&workspace_id=...`
- `ideOpenFile()` → `GET /api/ide/file?path=...&workspace_id=...`
- `ideOpenFile()` save → `POST /api/ide/file` body includes `workspace_id`
- Diff viewer fetch → `GET /api/ide/file?path=...&workspace_id=...`
- `termNew()` → `/ws/terminal?...&workspace_id=...`
- `termNewClaude()` → `/ws/terminal?...&workspace_id=...`
- `ideOpenCCChat()` → `/ws/cc-chat?...&workspace_id=...`
- `ccResumeSession()` → `/ws/cc-chat?...&workspace_id=...`
- Side panel CC chat → `/ws/cc-chat?...&workspace_id=...`

## Verification

```
grep -c "_resolve_workspace(ws_workspace_id)" dashboard/server.py  → 2 ✓
grep -c "_activeWorkspaceId" dashboard/frontend/dist/app.js        → 16 ✓
grep -c "workspace_id" dashboard/server.py                         → 24 ✓
python -m pytest tests/test_ide_workspace.py tests/test_ide_html.py -x -q → 16 passed ✓
python -m pytest tests/ -x -q  → 1744 passed, 11 skipped, no failures ✓
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing functionality] monkeypatch AGENT42_WORKSPACE in test fixture**
- **Found during:** Task 1 test execution
- **Issue:** `cc_sessions` reads from `workspace / ".agent42" / "cc-sessions"` where `workspace` is set from `AGENT42_WORKSPACE` env var. Test wrote sessions to `tmp_path`, but endpoint read from `Path.cwd()`.
- **Fix:** Added `monkeypatch.setenv("AGENT42_WORKSPACE", str(tmp_path))` to test fixture so server reads from the test directory.
- **Files modified:** `tests/test_ide_workspace.py`
- **Commit:** d2b9b1c

**2. [Rule 1 - Bug] exist_ok=True on cc-sessions mkdir in test fixture**
- **Found during:** Task 1 test execution (second run)
- **Issue:** `create_app()` startup event creates `cc-sessions` dir; test fixture also called `mkdir()` without `exist_ok=True` → `FileExistsError`.
- **Fix:** Changed to `cc_dir.mkdir(parents=True, exist_ok=True)`.
- **Files modified:** `tests/test_ide_workspace.py`
- **Commit:** d2b9b1c (same commit, fixed before staging)

**3. [Design boundary] _chat_via_cc side-panel subprocess left using module-level workspace**
- **Found during:** Task 1 implementation
- **Issue:** Plan mentioned updating `cwd=str(workspace)` at ~line 3092 (cc_chat_panel subprocess). However, `_chat_via_cc` is a standalone helper called from the dashboard sidebar chat endpoint — it has no `workspace_id` parameter and no WS query param context.
- **Decision:** Left `_chat_via_cc` using module-level `workspace`. The sidebar chat is not workspace-scoped (it is the global dashboard chat, not the IDE CC chat). Only `cc_chat_ws` was in scope for this plan.
- **Impact:** None — dashboard sidebar chat remains scoped to the default workspace. IDE CC chat (cc_chat_ws) is correctly scoped.

## Known Stubs

`_activeWorkspaceId` defaults to `""` — all workspace_id query params are conditionally omitted when empty, so behavior is identical to pre-Phase-2. This is intentional: Plan 03 (workspace tab bar) will populate `_activeWorkspaceId` from the workspace list. The data plumbing is complete; the trigger is in the next plan.

`_syncAliasesToWorkspace` and `_saveCurrentWsState` are defined but not called — Plan 03 will call them on workspace tab switches. These helpers are not stubs that block Plan 01's goal; they are pre-wired infrastructure for Plan 03.

## Self-Check: PASSED

- `dashboard/server.py` modified with workspace_id wiring in terminal_ws and cc_chat_ws
- `dashboard/frontend/dist/app.js` modified with _activeWorkspaceId globals and workspace_id threading
- `tests/test_ide_workspace.py` created with 10 tests, all passing
- Commit `d2b9b1c` (Task 1) exists in git log
- Commit `43d7856` (Task 2) exists in git log
- Full test suite: 1744 passed, 0 failures
