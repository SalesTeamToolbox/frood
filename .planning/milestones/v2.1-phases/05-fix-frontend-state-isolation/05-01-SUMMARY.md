---
phase: 05-fix-frontend-state-isolation
plan: 01
status: complete
started: "2026-03-25T00:00:00.000Z"
completed: "2026-03-25T00:00:00.000Z"
duration: "3m"
tasks_completed: 2
tasks_total: 2
---

# Plan 05-01 Summary: Migrate bare localStorage keys to wsKey() and fix unsaved guard

## What Was Built

Closed the last two v2.1 milestone audit gaps (ISOL-07 and MGMT-02) for frontend state isolation:

1. **wsKey() localStorage migration (ISOL-07):** Replaced 5 bare `localStorage` calls for `cc_panel_width` (3 sites: mouseup handler, ideOpenChatPanel, ideCloseChatPanel) and `cc_panel_session_id` (2 sites: _connectPanelWS get/set) with `wsKey(_activeWorkspaceId, ...)` namespaced versions. Switching workspaces now restores per-workspace panel width and CC session ID.

2. **Unsaved-files guard fix (MGMT-02):** Added `_saveCurrentWsState()` call in `removeWorkspace()` after the last-workspace gate but before the unsaved count loop. This syncs live `_ideTabs` modified flags into `_wsTabState` so editing a file and immediately closing the workspace triggers the confirmation dialog.

## Key Files

### key-files.modified
- `dashboard/frontend/dist/app.js` — All 6 edits (5 wsKey migrations + 1 guard sync)

### key-files.created
- None

## Deviations

None. All changes matched the plan exactly.

## Self-Check: PASSED

- [x] No bare `cc_panel_width` or `cc_panel_session_id` localStorage calls remain (only inside comments)
- [x] `wsKey(_activeWorkspaceId, "cc_panel_width")` appears 3 times (2 setItem + 1 getItem)
- [x] `wsKey(_activeWorkspaceId, "cc_panel_session_id")` appears 2 times (1 setItem + 1 getItem)
- [x] `_saveCurrentWsState()` in removeWorkspace before unsavedCount (line 3775 < line 3779)
- [x] wsKey function signature unchanged
- [x] No JS syntax errors (`node --check` passes)
