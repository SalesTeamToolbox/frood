---
phase: 03-workspace-management
plan: "01"
subsystem: dashboard/frontend
tags: [workspace, ide, frontend, js, css]
dependency_graph:
  requires:
    - 02-03 (initWorkspaceTabs, switchWorkspace, _workspaceList state vars)
    - WorkspaceRegistry POST/PATCH/DELETE endpoints (01-01)
  provides:
    - showAddWorkspaceModal / submitAddWorkspace — create workspace via path input or app dropdown
    - removeWorkspace — delete workspace with guards + cleanup
    - enterWsRenameMode — inline tab rename with optimistic update + rollback
    - ideRenderWorkspaceTabs (v3) — composite tabs with name span + close button + add button; always visible
  affects:
    - dashboard/frontend/dist/app.js (workspace tab bar rendering, workspace lifecycle)
    - dashboard/frontend/dist/style.css (workspace tab styling)
tech_stack:
  added: []
  patterns:
    - Composite button element pattern (outer button + inner span + inner button with stopPropagation)
    - Optimistic update + catch rollback for rename (DOM + _workspaceList + localStorage in sync)
    - Hover-reveal close button via CSS opacity transition
    - Post-showModal DOM query pattern for _populateWsAppDropdown (Pitfall 5 compliance)
key_files:
  created: []
  modified:
    - dashboard/frontend/dist/app.js
    - dashboard/frontend/dist/style.css
decisions:
  - "Always show workspace tab bar (removed <=1 hide guard) — '+' button must always be accessible per D-02"
  - "Close button disabled (not hidden) when only 1 workspace — per D-10; CSS .ide-ws-tab-close:disabled uses display:none"
  - "Direct terminal cleanup in removeWorkspace (s.ws.close + s.term.dispose + s.el.remove) instead of termClose() — avoids _termSessions splice index mismatch"
  - "Optimistic rename update applied to both _workspaceList[i].name and nameSpan.textContent simultaneously — both rolled back on API failure per Pitfall 4"
  - "workspaces_cache localStorage written after every mutation (push, splice, rename) — stale-while-revalidate pattern per Pitfall 3"
metrics:
  duration: "13m"
  completed_date: "2026-03-24"
  tasks_completed: 3
  files_changed: 2
---

# Phase 03 Plan 01: Workspace Lifecycle Management Summary

**One-liner:** Workspace add/remove/rename UI with composite tab bar (name span + hover-reveal close + always-visible "+"), guarded removal, and optimistic inline rename with API rollback.

## What Was Built

Complete workspace lifecycle management for the IDE tab bar:

- **`ideRenderWorkspaceTabs()` rewrite** — now produces composite tab DOM: `<button.ide-ws-tab>` containing `<span.ide-ws-tab-name>` (clickable name, triggers rename on active tab) and `<button.ide-ws-tab-close>` (hover-reveal X, disabled when only 1 workspace). A `<button.ide-ws-tab-add>` "+" is appended after all workspace tabs. Tab bar always visible (hide guard removed per D-02).

- **`showAddWorkspaceModal()`** — opens a modal with a path text input and (optionally) an Agent42 app dropdown. The dropdown section is hidden until `_populateWsAppDropdown()` resolves `/api/apps`. If the server has no app_manager, the dropdown stays hidden gracefully.

- **`_populateWsAppDropdown()`** — fetches `/api/apps`, populates select options (using `opt.textContent = apps[i].name` for XSS safety), shows the apps section. Errors are swallowed (404 when app_manager unconfigured).

- **`onAddWsAppChange(value)`** — syncs the app dropdown selection into the path input field.

- **`submitAddWorkspace()`** — validates path non-empty, checks client-side duplicate by `root_path`, calls `POST /api/workspaces`, appends to `_workspaceList`, writes `workspaces_cache`, re-renders tabs, switches to new workspace.

- **`removeWorkspace(wsId)`** — last-workspace gate, counts unsaved files + CC sessions and prompts confirm() only when non-zero, switches active workspace to adjacent tab before teardown, calls `DELETE /api/workspaces/{id}`, directly closes terminal WebSocket connections (not `termClose()`), prunes `ws_{id}_*` localStorage keys, deletes `_wsTabState/_wsTermSessions/_wsTermActiveIdx` entries, splices `_workspaceList`, updates `workspaces_cache`, re-renders tabs.

- **`enterWsRenameMode(wsId, currentName, nameSpan)`** — double-activation guard, replaces nameSpan with inline input (maxLength=64, auto-selected), Enter/blur commits via `PATCH /api/workspaces/{id}` with optimistic update (DOM + `_workspaceList` + `workspaces_cache`), Escape discards, empty string restores original, API failure rolls back all three.

- **CSS additions** — `.ide-ws-tab` gains `position: relative` and adjusted padding (6px 24px 6px 12px). New selectors: `.ide-ws-tab-name` (cursor:pointer), `.ide-ws-tab-close` (absolute positioned, hover-reveal opacity, red on hover, display:none when disabled), `.ide-ws-tab-add` ("+"), `.ide-ws-rename-input` (blue-border inline input).

## Task Commits

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Rewrite ideRenderWorkspaceTabs with composite tabs, add-workspace modal, and CSS | 20a57c9 | dashboard/frontend/dist/app.js, dashboard/frontend/dist/style.css |
| 2 | removeWorkspace with guards and cleanup, enterWsRenameMode with inline input | 84d6b8e | dashboard/frontend/dist/app.js |
| 3 | Verify workspace management in browser | (auto-approved in auto mode) | — |

## Deviations from Plan

None — plan executed exactly as written.

## Verification Results

- `function showAddWorkspaceModal` in app.js: 1 match
- `function submitAddWorkspace` in app.js: 1 match
- `function _populateWsAppDropdown` in app.js: 1 match
- `function onAddWsAppChange` in app.js: 1 match
- `function removeWorkspace` in app.js: 1 match
- `function enterWsRenameMode` in app.js: 1 match
- `.ide-ws-tab-close` in style.css: 4 matches
- `.ide-ws-tab-add` in style.css: 2 matches
- `.ide-ws-rename-input` in style.css: 1 match
- `e.stopPropagation()` in close/name handlers: 2 occurrences
- `workspaces_cache` writes: 3 (submitAddWorkspace, removeWorkspace, enterWsRenameMode commit + rollback)
- `tests/test_workspace_registry.py`: 36 passed
- Security + sandbox + command_filter tests: 172 passed, 7 skipped

## Known Stubs

None — all workspace management flows are fully wired to live API endpoints.

## Self-Check: PASSED
