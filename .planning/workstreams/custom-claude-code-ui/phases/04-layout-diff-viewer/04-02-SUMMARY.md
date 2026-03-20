---
phase: 04-layout-diff-viewer
plan: 02
subsystem: ui
tags: [javascript, css, monaco, ide, panel-layout, drag-handle, localstorage]

# Dependency graph
requires:
  - phase: 04-01
    provides: "Wave 0 test scaffold (tests/test_cc_layout.py) with xfail stubs for LAYOUT-01 through LAYOUT-04"
provides:
  - ".ide-main-editor-area wrapper div containing tabs+editor+cc-container+welcome"
  - "#ide-cc-panel right-side panel container (hidden by default)"
  - "#ide-panel-drag-handle vertical resize handle (hidden by default)"
  - "ideToggleCCPanel() stub function for panel toggle"
  - "initPanelDragHandle() with mousedown/mousemove/mouseup handlers and cc_panel_width localStorage persistence"
  - "_ccPanelMode and _isPanelDragging state variables"
  - "Activity bar CC icon button"
  - "CSS rules for .ide-main-editor-area, .ide-cc-panel, .ide-panel-drag-handle"
affects: [04-03, 04-04]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Horizontal drag handle uses separate _isPanelDragging namespace from vertical terminal drag _isDragging"
    - "Panel width persisted via localStorage.setItem('cc_panel_width') in mouseup handler"
    - "Wrapper div (.ide-main-editor-area) with min-width:0 prevents flex overflow in nested flex containers"
    - "Panel display toggled via style.display not CSS class to enable width preservation"

key-files:
  created: []
  modified:
    - "dashboard/frontend/dist/app.js"
    - "dashboard/frontend/dist/style.css"

key-decisions:
  - "ideToggleCCPanel() added as a full stub (not just placeholder comment) so Wave 1 tests can verify toggle works immediately"
  - "Panel uses display:flex when visible (not display:block) to support internal flex column layout"
  - ".ide-main flex-direction changed from column to row to place panel as sibling of .ide-main-editor-area"
  - "initPanelDragHandle() called at renderCode init time alongside initDragHandle() — both set up on page load"

patterns-established:
  - "Pattern: Drag handle init functions paired — initDragHandle() (vertical) + initPanelDragHandle() (horizontal)"
  - "Pattern: Panel width restoration from localStorage on ideToggleCCPanel() open"

requirements-completed: [LAYOUT-01, LAYOUT-02]

# Metrics
duration: 8min
completed: 2026-03-20
---

# Phase 04 Plan 02: Layout + Diff Viewer - Panel Container Infrastructure Summary

**Right-side CC panel container wired with horizontal drag resize, localStorage width persistence, and activity bar toggle icon — all 8 LAYOUT-01/LAYOUT-02 tests XPASS**

## Performance

- **Duration:** 8 min
- **Started:** 2026-03-20T00:00:00Z
- **Completed:** 2026-03-20T00:08:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Restructured `.ide-main` from flex-column to flex-row; wrapped existing children in `.ide-main-editor-area` (prevents tab bar width collapse with `min-width:0`)
- Added `#ide-cc-panel` and `#ide-panel-drag-handle` as siblings of `.ide-main-editor-area` inside `.ide-main`
- Implemented `initPanelDragHandle()` with full mousedown/mousemove/mouseup lifecycle using separate `_isPanelDragging` namespace, 250px min/60% max width constraints, and `cc_panel_width` localStorage persistence
- Added `ideToggleCCPanel()` stub that restores saved width on open and toggles `_ccPanelMode` flag
- Added CC icon button to activity bar with `onclick="ideToggleCCPanel()"`
- Added CSS for all three new elements: `.ide-main-editor-area`, `.ide-cc-panel`, `.ide-panel-drag-handle` (with hover highlight and extended hit target)

## Task Commits

Each task was committed atomically:

1. **Task 1: Restructure HTML template and add panel container, drag handle, activity bar icon, and initPanelDragHandle** - `617e264` (feat)
2. **Task 2: Add CSS for panel container, drag handle, and editor area wrapper** - `dedae6e` (feat)

## Files Created/Modified
- `dashboard/frontend/dist/app.js` - HTML template restructured, initPanelDragHandle() + ideToggleCCPanel() + _ccPanelMode + _isPanelDragging added, initPanelDragHandle() called at init
- `dashboard/frontend/dist/style.css` - Phase 4 CC panel layout section added with .ide-main-editor-area, .ide-cc-panel, .ide-panel-drag-handle rules

## Decisions Made
- `ideToggleCCPanel()` implemented as a functional stub (not just a no-op) — enables Wave 1 test verification that panel can open/close and tests XPASS immediately without waiting for Plan 04-03
- Panel uses `display:flex` (not `display:block`) when visible to support its internal flex column child layout
- `_ccPanelMode` and `_isPanelDragging` use separate variable names from the terminal drag variables (`_isDragging`) to prevent namespace collision in the `create_app()` closure scope

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

Pre-existing test failure in `tests/test_memory_tool.py::TestMemoryToolSearchScoring::test_search_shows_relevance_label` — confirmed pre-existing before this plan's changes (AttributeError in mock library, unrelated to frontend work). Not introduced by this plan.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Panel container infrastructure complete — `#ide-cc-panel`, `#ide-panel-drag-handle`, `.ide-main-editor-area` wrapper all in place
- Plan 04-03 can implement full `ideToggleCCPanel()` (move CC chat iframe into panel, handle mode switching, restore session continuity)
- All 8 LAYOUT-01/LAYOUT-02 tests XPASS; 4 LAYOUT-04 (diff viewer) tests remain xfail awaiting Plan 04-04

---
*Phase: 04-layout-diff-viewer*
*Completed: 2026-03-20*
