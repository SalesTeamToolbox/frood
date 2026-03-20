---
phase: 04-layout-diff-viewer
plan: 01
subsystem: testing
tags: [pytest, source-inspection, tdd, xfail, layout, monaco, diff-viewer]

# Dependency graph
requires:
  - phase: 03-tool-use-sessions
    provides: test_cc_tool_use.py source-inspection pattern that this plan replicates
provides:
  - Wave 0 test scaffold for LAYOUT-01 through LAYOUT-04 (12 source-inspection tests)
  - xfail stubs for TestCCPanelLayout, TestCCPanelCSS, TestDiffViewer classes
affects: [04-02-PLAN, 04-03-PLAN, 04-04-PLAN]

# Tech tracking
tech-stack:
  added: []
  patterns: [source-inspection xfail scaffolding per Phase 2/3 TDD pattern]

key-files:
  created:
    - tests/test_cc_layout.py
  modified: []

key-decisions:
  - "LAYOUT-02 and LAYOUT-03 features were already in app.js and style.css from prior work -- tests XPASS immediately (correct behavior with strict=False)"
  - "LAYOUT-04 (diff viewer: ideOpenDiffTab, createDiffEditor, View Diff) not yet implemented -- 4 tests remain XFAIL"
  - "Wave 0 scaffold uses source-text inspection (Path.read_text) -- identical to test_cc_tool_use.py and test_cc_chat_ui.py"

patterns-established:
  - "xfail(raises=AssertionError, strict=False) for unimplemented features; XPASS acceptable when feature already exists"

requirements-completed: [LAYOUT-01, LAYOUT-02, LAYOUT-03, LAYOUT-04]

# Metrics
duration: 13min
completed: 2026-03-20
---

# Phase 4 Plan 01: Layout + Diff Viewer Wave 0 Test Scaffold Summary

**Wave 0 source-inspection test scaffold for LAYOUT-01 through LAYOUT-04 using xfail pattern from Phases 2/3**

## Performance

- **Duration:** 13 min
- **Started:** 2026-03-20T16:52:32Z
- **Completed:** 2026-03-20T17:06:07Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments
- Created `tests/test_cc_layout.py` with 12 source-inspection tests across 3 classes
- Confirmed LAYOUT-01/02/03 JS and CSS patterns already present in app.js and style.css (8 XPASS)
- Established XFAIL stubs for LAYOUT-04 diff viewer (ideOpenDiffTab, createDiffEditor, View Diff) — 4 tests remain RED
- Full test suite runs without import errors, exits 0

## Task Commits

Each task was committed atomically:

1. **Task 1: Create test_cc_layout.py with xfail stubs for LAYOUT-01 through LAYOUT-04** - `0fe5d5a` (test)

**Plan metadata:** pending (docs: complete plan)

## Files Created/Modified
- `tests/test_cc_layout.py` — 12 source-inspection tests: TestCCPanelLayout (6), TestCCPanelCSS (2), TestDiffViewer (4)

## Decisions Made
- LAYOUT-02/03 features (`ideToggleCCPanel`, `_ccPanelMode`, `initPanelDragHandle`, `ide-cc-panel`, `ide-panel-drag-handle`, `cc_panel_width`, `.ide-cc-panel`, `.ide-panel-drag-handle`, `.ide-main-editor-area`) already exist in app.js and style.css from prior work, so 8 of 12 tests XPASS immediately. This is correct — `strict=False` explicitly allows XPASS.
- LAYOUT-04 diff viewer patterns (`ideOpenDiffTab`, `createDiffEditor`, `View Diff`) not yet implemented; 4 tests remain XFAIL for Plan 04-04 to flip GREEN.

## Deviations from Plan

None - plan executed exactly as written. The higher-than-expected XPASS count (8 vs expected 1) is a discovery, not a deviation — the xfail markers have `strict=False` which accommodates both outcomes.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Wave 0 test scaffold complete; Plans 04-02, 04-03, 04-04 can verify progress by running `python -m pytest tests/test_cc_layout.py -x -q`
- LAYOUT-02 panel layout and LAYOUT-03 toggle mode already implemented (8 XPASS confirms this)
- Plan 04-02 should validate the existing panel implementation passes regression tests
- Plan 04-04 must implement `ideOpenDiffTab`, `createDiffEditor`, and "View Diff" button to flip the 4 remaining XFAIL tests

---
*Phase: 04-layout-diff-viewer*
*Completed: 2026-03-20*
