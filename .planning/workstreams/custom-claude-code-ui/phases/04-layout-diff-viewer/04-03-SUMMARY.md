---
phase: 04-layout-diff-viewer
plan: 03
subsystem: ui
tags: [javascript, ide, panel-layout, dom-reparenting, websocket, session-transfer]

# Dependency graph
requires:
  - phase: 04-02
    provides: "#ide-cc-panel, #ide-panel-drag-handle, .ide-main-editor-area wrapper, ideToggleCCPanel() stub, _ccPanelMode flag, initPanelDragHandle()"
provides:
  - "ideToggleCCPanel() full three-state toggle (panel->tab, tab->panel, no-CC->new-panel)"
  - "ideOpenCCPanel() with localStorage width restore and flex layout"
  - "ideCloseCCPanel() persisting panel width before hide"
  - "ideMoveSessionsToPanel() reparenting tab.el via appendChild (WS preserved)"
  - "ideMoveSessionsToTab() restoring CC sessions to #ide-cc-container"
  - "ideActivateTab() panel-mode early return branch for in-panel CC tab switching"
  - "ideRenderTabs() hides CC tabs from tab bar when inPanel=true"
  - "tab.inPanel boolean property for panel tracking"
affects: [04-04]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "DOM reparenting via appendChild() moves CC session without closing WS — tab.ws untouched"
    - "tab.inPanel boolean tracks which container holds the CC session element"
    - "panel-mode early return in ideActivateTab() handles in-panel CC tab switching before normal flow"
    - "ideRenderTabs() filters inPanel tabs to return empty string — removes from tab bar without splicing array"

key-files:
  created: []
  modified:
    - "dashboard/frontend/dist/app.js"

key-decisions:
  - "ideMoveSessionsToPanel() uses appendChild (move, not clone) — preserves all event listeners and tab.ws"
  - "ideToggleCCPanel three-state: panel-open->close+move-to-tab, CC-tabs-exist->open+move-to-panel, no-CC->open+new-session+50ms-move"
  - "50ms setTimeout for ideMoveSessionsToPanel after ideOpenCCChat ensures newly created tab is in _ideTabs before move"
  - "ideActivateTab panel-mode branch added before normal claude tab logic with early return"
  - "ideRenderTabs hides panel-mode tabs using return '' in map() to exclude from join"

patterns-established:
  - "Pattern: DOM move for session transfer — appendChild on existing node moves without clone"
  - "Pattern: WS preservation — only ideCloseTab/ccResumeSession call tab.ws.close(); move functions never do"

requirements-completed: [LAYOUT-03]

# Metrics
duration: 12min
completed: 2026-03-20
---

# Phase 04 Plan 03: Layout + Diff Viewer - CC Tab-to-Panel Mode Switching Summary

**Full ideToggleCCPanel three-state toggle with DOM reparenting preserving live WS connections — CC sessions transfer seamlessly between editor tab and right-side panel**

## Performance

- **Duration:** 12 min
- **Started:** 2026-03-20T00:15:00Z
- **Completed:** 2026-03-20T00:27:00Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments
- Replaced `ideToggleCCPanel()` stub with full three-state toggle logic: panel-open closes and restores to tab, CC-in-tab moves to panel, no-CC opens new session in panel
- Added `ideOpenCCPanel()` that restores saved width from `cc_panel_width` localStorage and sets `_ccPanelMode = true`
- Added `ideCloseCCPanel()` that persists current width to localStorage and sets `_ccPanelMode = false`
- Added `ideMoveSessionsToPanel()` using `panel.appendChild(tab.el)` to reparent CC session DOM without touching `tab.ws` — connection survives the transfer
- Added `ideMoveSessionsToTab()` restoring CC session DOM back to `#ide-cc-container` and activating first CC tab
- Updated `ideActivateTab()` with panel-mode early return branch that switches visible session within the panel instead of touching `#ide-cc-container`
- Updated `ideRenderTabs()` to filter out CC tabs with `inPanel=true` from the tab bar (they appear in the panel, not the tab strip)

## Task Commits

1. **Task 1: Replace ideToggleCCPanel stub with full three-state toggle logic** - `a202ad2` (feat)

## Files Created/Modified
- `dashboard/frontend/dist/app.js` - ideToggleCCPanel full implementation + ideOpenCCPanel + ideCloseCCPanel + ideMoveSessionsToPanel + ideMoveSessionsToTab + ideActivateTab panel-mode branch + ideRenderTabs panel filter

## Decisions Made
- Used `panel.appendChild(tab.el)` for DOM reparenting — moves the existing DOM node (no clone), preserving all inline `onclick` handlers and the `tab.ws` WebSocket connection which is independent of DOM position
- Added 50ms `setTimeout` before `ideMoveSessionsToPanel` when opening a new CC session, ensuring the newly-created tab is pushed to `_ideTabs` before the move function iterates over them
- `ideActivateTab` panel-mode branch uses early return so it doesn't fall through to the normal `#ide-cc-container` visibility logic — prevents container flash
- `ideRenderTabs` uses `return ""` in the map callback to exclude panel-mode CC tabs from the rendered HTML — tabs remain in `_ideTabs` for state tracking but are invisible in the tab bar

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

Pre-existing test failure: `tests/test_app_manager.py::TestEnsureAppVenv::test_returns_correct_python_path` fails with `RuntimeError: venv creation timed out after 60s` — a Windows-specific timeout creating a Python venv in a temp directory during testing. Confirmed pre-existing (not introduced by this plan's JS-only changes).

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Full LAYOUT-03 implementation complete — CC sessions transfer between tab and panel without WS interruption
- All 8 LAYOUT-01/02/03 tests XPASS; 4 LAYOUT-04 (diff viewer) tests remain xfail awaiting Plan 04-04
- Plan 04-04 can implement `ideOpenDiffTab()` and Monaco diff editor with "View Diff" tool card buttons

---
*Phase: 04-layout-diff-viewer*
*Completed: 2026-03-20*
