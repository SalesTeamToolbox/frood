---
phase: 02-ide-surface-integration
plan: 03
subsystem: frontend/workspace-tab-bar, frontend/workspace-switching
tags: [javascript, workspace, tab-bar, stale-while-revalidate, localStorage, state-orchestration]
dependency_graph:
  requires: [02-01-SUMMARY, 02-02-SUMMARY]
  provides: [initWorkspaceTabs, switchWorkspace, ideRenderWorkspaceTabs, workspace-tab-bar-ui, workspace-persistence]
  affects: [dashboard/frontend/dist/app.js, dashboard/frontend/dist/style.css]
tech_stack:
  added: []
  patterns: [stale-while-revalidate-localStorage, workspace-state-orchestration, tab-bar-with-active-indicator]
key_files:
  created: []
  modified:
    - dashboard/frontend/dist/app.js
    - dashboard/frontend/dist/style.css
decisions:
  - "Tab bar hidden when only 1 workspace exists (<=1 workspaces) — no UI clutter for single-project users"
  - "Workspace list reconciliation: if persisted active_workspace_id no longer exists in server response, fall back to first workspace in list"
  - "switchWorkspace saves Monaco view state before swapping — cursor/scroll preserved across workspace switches"
  - "_wsTermSessions keyed dict queried directly for terminal show/hide in switchWorkspace (not through _termSessions alias) — avoids stale alias race"
  - "termFitAll() called via setTimeout(50ms) after terminal show — gives DOM time to layout before xterm measures"
  - "_ideTreeCache cleared and _ideExpandedDirs reset to Set(['']) on workspace switch — prevents cross-workspace file tree bleed"
metrics:
  duration: "8m"
  completed: "2026-03-24"
  tasks_completed: 1
  tasks_total: 2
  files_modified: 2
---

# Phase 02 Plan 03: Workspace Tab Bar and switchWorkspace() Orchestrator Summary

**One-liner:** Workspace tab bar rendered above editor tab bar with GitHub-dark styling and active underline indicator; switchWorkspace() atomically saves state, hides old terminals, swaps all IDE surfaces, and re-roots the file explorer; stale-while-revalidate localStorage cache renders workspaces immediately on reload then reconciles with server.

## What Was Built

### Task 1: Workspace tab bar HTML, CSS, switchWorkspace() orchestrator, initWorkspaceTabs() with stale-while-revalidate

**HTML insertion in renderCode() (app.js):**
- Added `<div id="ide-workspace-tabs" class="ide-workspace-tabs"></div>` above `#ide-tabs` inside the `ide-main-editor-area` container
- Added `initWorkspaceTabs()` call after `ideLoadTree("")`, `ideInitMonaco()`, `initDragHandle()`, and `initPanelDragHandle()` in the renderCode() initialization block

**initWorkspaceTabs() with stale-while-revalidate:**
- Reads `workspaces_cache` from localStorage — renders tab bar immediately from cache if available
- Reads `active_workspace_id` from localStorage — restores active tab selection across reloads
- Fetches fresh workspace list from `GET /api/workspaces` with Authorization header
- Reconciles: if persisted activeId no longer appears in server response, falls back to `workspaces[0].id`
- Saves reconciled list back to `workspaces_cache` in localStorage
- Calls `_setWorkspaceList(workspaces, activeId)` for both cache-render and server-response paths

**_setWorkspaceList():**
- Assigns `_workspaceList = workspaces` (used by ideRenderWorkspaceTabs)
- On first call (when `_activeWorkspaceId` is empty): sets `_activeWorkspaceId`, calls `_ensureWsState()` and `_syncAliasesToWorkspace()`, persists to localStorage
- Calls `ideRenderWorkspaceTabs()` to render/update tabs

**ideRenderWorkspaceTabs():**
- Clears container DOM children with `removeChild` loop (not innerHTML)
- Hides container (`display: none`) when `_workspaceList.length <= 1`
- Shows container (`display: flex`) when 2+ workspaces exist
- Creates `<button class="ide-ws-tab [active]">` for each workspace using `textContent` (safe, no XSS)
- Sets `data-ws-id` attribute and `onclick` handler via IIFE closure to capture wsId

**switchWorkspace() orchestrator (12-step sequence):**
1. Guard: returns immediately if `newId === _activeWorkspaceId`
2. Saves Monaco view state for currently active tab (saves into `currentTab.viewState`)
3. Calls `_saveCurrentWsState()` — snapshots `_ideTabs`, `_ideActiveTab`, `_termSessions`, `_termActiveIdx` to workspace-keyed dicts
4. Hides current workspace's terminal DOM elements via `oldTerms[t].el.style.display = "none"`
5. Sets `_activeWorkspaceId = newId`; calls `_ensureWsState(newId)`
6. Calls `_syncAliasesToWorkspace(newId)` — repopulates flat `_ideTabs`/`_termSessions` aliases from new workspace's keyed dicts
7. Clears `_ideTreeCache = {}` and resets `_ideExpandedDirs = new Set([""])` — prevents cross-workspace file bleed
8. Calls `ideRenderWorkspaceTabs()` — updates active indicator on tab bar
9. Calls `ideLoadTree("")` — re-roots file explorer to new workspace
10. Calls `ideRenderTabs()`; then either `ideActivateTab()` (if tabs exist) or shows welcome screen / hides editor containers
11. Shows new workspace's active terminal, calls `termRenderTabs()`, then `setTimeout(termFitAll, 50ms)` for layout
12. Persists `active_workspace_id` to localStorage

**CSS (style.css):**
- `.ide-workspace-tabs`: `display:none` default (flex when active), `background:#0d1117`, `border-bottom:1px solid #21262d`, `min-height:32px`, `overflow-x:auto`, `flex-shrink:0`
- `.ide-ws-tab`: transparent background, `color:#8b949e`, `border-bottom:2px solid transparent`, `font-size:12px`, `font-family:inherit`, `white-space:nowrap`, `transition:color/border-color 0.15s`
- `.ide-ws-tab:hover`: `color:#c9d1d9`, `background:#161b22`
- `.ide-ws-tab.active`: `color:#e6edf3`, `border-bottom-color:#58a6ff`, `background:#161b22`

### Checkpoint: human-verify (auto-approved, AUTO MODE active)

Visual verification checkpoint was auto-approved per AUTO MODE configuration. The complete workspace tab bar implementation requires a live server with 2+ registered workspaces for visual confirmation.

## Verification

```
grep -c "ide-workspace-tabs" dashboard/frontend/dist/app.js  → 2 (in HTML template + ideRenderWorkspaceTabs) ✓
grep -c "function switchWorkspace" dashboard/frontend/dist/app.js → 1 ✓
grep -c "function initWorkspaceTabs" dashboard/frontend/dist/app.js → 1 ✓
grep -c "function ideRenderWorkspaceTabs" dashboard/frontend/dist/app.js → 1 ✓
grep -c "workspaces_cache" dashboard/frontend/dist/app.js → 2 (localStorage read + write) ✓
grep -c "active_workspace_id" dashboard/frontend/dist/app.js → 3 (read, write in initWorkspaceTabs, write in switchWorkspace) ✓
grep -c "_syncAliasesToWorkspace" dashboard/frontend/dist/app.js → 3 (in _syncAliasesToWorkspace def, _setWorkspaceList, switchWorkspace) ✓
grep -c "_saveCurrentWsState" dashboard/frontend/dist/app.js → 4 (def, switchWorkspace, and 2 sync calls in 02-02) ✓
grep -c "ide-workspace-tabs" dashboard/frontend/dist/style.css → 1 ✓
grep -c "ide-ws-tab" dashboard/frontend/dist/style.css → 3 (.ide-ws-tab, .ide-ws-tab:hover, .ide-ws-tab.active) ✓
python -m pytest tests/test_ide_html.py tests/test_ide_workspace.py -x -q → 16 passed ✓
python -m pytest tests/test_security.py tests/test_tools.py tests/test_sandbox.py tests/test_command_filter.py -x -q → 164 passed ✓
```

## Deviations from Plan

None - plan executed exactly as written.

## Known Stubs

None. This plan is the activation trigger that sets `_activeWorkspaceId` — all workspace-keyed state plumbing from Plans 01 and 02 is now fully wired. With a single workspace, the tab bar is hidden; existing behavior is unchanged.

View state is saved to `_ideTabs[].viewState` (in-memory only). On page reload, Monaco cursor/scroll positions are not restored. This is intentional — persistent view state is out of scope for this milestone.

## Self-Check: PASSED

- `dashboard/frontend/dist/app.js` modified with workspace tab bar HTML, all four functions, and initWorkspaceTabs() call
- `dashboard/frontend/dist/style.css` modified with .ide-workspace-tabs, .ide-ws-tab, .ide-ws-tab:hover, .ide-ws-tab.active styles
- Commit `0731d1c` (Task 1) exists in git log
- IDE-specific tests: 16 passed, 0 failures
- Security/sandbox/tools tests: 164 passed, 0 failures
