---
phase: 02-ide-surface-integration
plan: 02
subsystem: frontend/monaco-isolation, frontend/cc-session-scoping
tags: [javascript, monaco, view-state, workspace, cc-sessions, uri-migration]
dependency_graph:
  requires: [02-01-SUMMARY]
  provides: [makeWorkspaceUri-in-ideOpenFile, view-state-save-restore, per-workspace-cc-sessions, wsKey-cc-active-session]
  affects: [dashboard/frontend/dist/app.js]
tech_stack:
  added: []
  patterns: [monaco-view-state-swap, workspace-scoped-model-uris, wsKey-sessionStorage, per-workspace-cc-tab-counter]
key_files:
  created: []
  modified:
    - dashboard/frontend/dist/app.js
decisions:
  - "makeWorkspaceUri fallback is 'default' when _activeWorkspaceId is empty — ensures backward compat before Plan 03 sets the active workspace"
  - "View state save loop in ideActivateTab iterates _ideTabs to find matching model rather than tracking previous tab index — more robust against splice/reorder"
  - "Per-workspace ccTabCount added to _wsTabState so each workspace independently tracks first-open (session resume guard) rather than sharing global _ccTabCounter===1"
  - "wsKey-based session storage falls back to bare 'cc_active_session' key when _activeWorkspaceId is empty — single-workspace users see no behavior change"
metrics:
  duration: "10m"
  completed: "2026-03-24"
  tasks_completed: 2
  tasks_total: 2
  files_modified: 1
---

# Phase 02 Plan 02: Monaco Isolation and CC Session Scoping Summary

**One-liner:** Monaco model URIs migrated to makeWorkspaceUri() so two workspaces can open the same filename without collision; view state (cursor/scroll/selection) saved before tab switch and restored after; CC session sidebar filtered by workspace_id; active session key namespaced per-workspace via wsKey().

## What Was Built

### Task 1: Monaco view state save/restore and workspace URI migration (app.js)

**URI migration in ideOpenFile:**
- Replaced `monaco.Uri.parse("file:///" + path)` with `monaco.Uri.parse(makeWorkspaceUri(_activeWorkspaceId || "default", path))`
- Tab objects now carry `workspaceId: _activeWorkspaceId` property for tracking
- `_saveCurrentWsState()` called after `_ideTabs.push(...)` to keep workspace-keyed dict in sync

**View state save in ideActivateTab:**
- At the top of `ideActivateTab()`, iterates `_ideTabs` to find the currently displayed model (by comparing `_monacoEditor.getModel()`) and saves its view state via `_monacoEditor.saveViewState()`
- Saves into `_ideTabs[s].viewState` — persists across tab switches within the same workspace

**View state restore in ideActivateTab:**
- After `_monacoEditor.setModel(tab.model)` in the file-tab activation branch, calls `_monacoEditor.restoreViewState(tab.viewState)` when the property exists
- Ensures cursor position, scroll offset, and selection are restored on return

**_saveCurrentWsState sync after mutations:**
- Added `if (_activeWorkspaceId) _saveCurrentWsState()` after `_ideTabs.push()` in `ideOpenFile`
- Added `if (_activeWorkspaceId) _saveCurrentWsState()` after `_ideTabs.splice(index, 1)` in `ideCloseTab`

### Task 2: CC session scoping (app.js)

**ccGetStoredSessionId migration:**
- When `_activeWorkspaceId` is set: reads `sessionStorage.getItem(wsKey(_activeWorkspaceId, "cc_active_session"))`
- Falls back to bare `"cc_active_session"` key when no active workspace — backward compatible

**ccStoreSessionId migration:**
- When `_activeWorkspaceId` is set: writes `sessionStorage.setItem(wsKey(_activeWorkspaceId, "cc_active_session"), sessionId)`
- Falls back to bare `"cc_active_session"` key otherwise

**ccLoadSessionSidebar workspace filter:**
- Builds `sessionsUrl = "/api/cc/sessions"` and appends `?workspace_id=<id>` when `_activeWorkspaceId` is set
- Backend (already wired in Plan 01) filters sessions by workspace_id, including legacy sessions

**Per-workspace CC tab counter:**
- `_ensureWsState()` now initializes `ccTabCount: 0` for each workspace bucket
- `ideOpenCCChat()` computes `wsTabCount` from the workspace bucket instead of global `_ccTabCounter`
- Session resume guard changed from `_ccTabCounter === 1` to `wsTabCount === 0`
- `_wsTabState[_activeWorkspaceId].ccTabCount` incremented after each `ideOpenCCChat()` call per workspace

## Verification

```
grep "makeWorkspaceUri" dashboard/frontend/dist/app.js (in ideOpenFile) → match ✓
grep '"file:///"' dashboard/frontend/dist/app.js → no match in ideOpenFile ✓
grep "saveViewState" dashboard/frontend/dist/app.js → match in ideActivateTab ✓
grep "restoreViewState" dashboard/frontend/dist/app.js → match in ideActivateTab ✓
grep -c "wsKey.*cc_active_session" dashboard/frontend/dist/app.js → 3 (incl comment) ✓
grep "workspace_id.*_activeWorkspaceId" dashboard/frontend/dist/app.js → match in ccLoadSessionSidebar ✓
grep "ccTabCount" dashboard/frontend/dist/app.js → 4 matches ✓
python -m pytest tests/test_ide_html.py tests/test_ide_workspace.py -x -q → 16 passed ✓
python -m pytest tests/test_ide_html.py tests/test_ide_workspace.py tests/test_security.py tests/test_sandbox.py -q → 140 passed, 7 skipped ✓
```

## Deviations from Plan

None - plan executed exactly as written.

## Known Stubs

`_activeWorkspaceId` still defaults to `""` — Plan 03 will populate it from the workspace tab bar. All workspace-scoped logic is conditionally gated on `_activeWorkspaceId !== ""`, so single-workspace behavior is unchanged.

View state persistence is in-memory only (stored in `_ideTabs[].viewState`). On page reload, Monaco view states are lost. This is intentional — persistent view state (e.g., to localStorage) is out of scope for this milestone.

## Self-Check: PASSED

- `dashboard/frontend/dist/app.js` modified with URI migration, view state, and CC session scoping
- Commit `ab4139d` (Task 1) exists in git log
- Commit `aa469a4` (Task 2) exists in git log
- Tests pass: 16 IDE-specific tests green, 140+ key tests green, 0 failures
