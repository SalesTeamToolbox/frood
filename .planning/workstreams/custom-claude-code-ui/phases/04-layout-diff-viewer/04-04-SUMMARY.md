---
phase: 04-layout-diff-viewer
plan: "04"
subsystem: ui
tags: [monaco, diff-editor, javascript, css, ide, tool-cards]

# Dependency graph
requires:
  - phase: 04-02
    provides: "ideActivateTab, ideCloseTab, _ideTabs structure, IDE tab infrastructure"
  - phase: 04-03
    provides: "ideToggleCCPanel, ideMoveSessionsToPanel, panel-mode tab branches"
provides:
  - "ideOpenDiffTab: creates Monaco diff editor tabs with side-by-side view"
  - "ideDetectLanguage: maps file extensions to Monaco language IDs"
  - "ccOpenDiffFromToolCard: fetches original file via GET /api/ide/file and opens diff tab"
  - "ccIsWriteTool + _CC_WRITE_TOOLS: identifies Write/Edit/MultiEdit tool operations"
  - "View Diff + Open File action buttons on Write/Edit tool cards in ccFinalizeToolCard"
  - "CSS: .cc-tool-actions, .cc-tool-action-btn, .cc-tool-diff-btn"
affects: [phase-05-streaming-pty, future-diff-features]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Diff tab object shape: {type:diff, diffEditor, diffOriginalModel, diffModifiedModel, el:.ide-diff-container}"
    - "ideActivateTab/ideCloseTab extended with diff branch before file else-branch"
    - "ccOpenDiffFromToolCard: fetch original + get modified from tool output pre element"
    - ".ide-diff-container class for querySelectorAll hide-all pattern"

key-files:
  created: []
  modified:
    - dashboard/frontend/dist/app.js
    - dashboard/frontend/dist/style.css

key-decisions:
  - "Diff container uses .ide-diff-container class for targeted hide-all in ideActivateTab (cleaner than style attribute selector)"
  - "ccOpenDiffFromToolCard includes Authorization header on fetch (consistent with other IDE API calls)"
  - "Both diff editor panes forced read-only: originalEditable:false in options + getOriginalEditor/getModifiedEditor().updateOptions({readOnly:true})"
  - "ccOpenDiffFromToolCard placed after ideOpenDiffTab in Monaco Diff section (same logical group)"

patterns-established:
  - "Pattern: Monaco diff tabs use type='diff' object shape with diffEditor, diffOriginalModel, diffModifiedModel, el fields"
  - "Pattern: ideActivateTab diff branch hides .ide-diff-container elements, shows tab.el, calls diffEditor.layout()"
  - "Pattern: ideCloseTab diff branch disposes diffEditor then both models then removes el"
  - "Pattern: Tool card action buttons use .cc-tool-actions container with .cc-tool-action-btn buttons"

requirements-completed: [LAYOUT-04]

# Metrics
duration: 12min
completed: 2026-03-20
---

# Phase 04 Plan 04: Monaco Diff Editor Tabs + View Diff Buttons Summary

**Monaco diff editor tabs with side-by-side syntax-highlighted read-only panes, triggered by View Diff button on Write/Edit tool cards fetching original via /api/ide/file**

## Performance

- **Duration:** 12 min
- **Started:** 2026-03-20T17:40:01Z
- **Completed:** 2026-03-20T17:52:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- `ideDetectLanguage()` maps 25+ file extensions to Monaco language IDs
- `ideOpenDiffTab()` creates Monaco diff editor tabs with agent42-dark theme, both panes read-only
- `ideActivateTab()` and `ideCloseTab()` extended with diff tab branches (proper resource disposal)
- `ccOpenDiffFromToolCard()` fetches original file content and opens diff tab with modified content from tool output
- View Diff + Open File action buttons added to Write/Edit/MultiEdit tool cards in `ccFinalizeToolCard()`
- CSS styling for `.cc-tool-actions`, `.cc-tool-action-btn`, `.cc-tool-diff-btn` added
- All 12 LAYOUT tests now XPASS (4 LAYOUT-04 tests flipped from XFAIL to XPASS)

## Task Commits

Each task was committed atomically:

1. **Task 1 + Task 2: Diff editor infrastructure + View Diff buttons** - `6d57c41` (feat)

**Plan metadata:** (forthcoming)

## Files Created/Modified
- `dashboard/frontend/dist/app.js` - Added ideDetectLanguage, ideOpenDiffTab, ccOpenDiffFromToolCard, diff branches in ideActivateTab/ideCloseTab, _CC_WRITE_TOOLS, ccIsWriteTool, action buttons in ccFinalizeToolCard
- `dashboard/frontend/dist/style.css` - Added .cc-tool-actions, .cc-tool-action-btn, .cc-tool-diff-btn styles

## Decisions Made
- Diff container uses `.ide-diff-container` class for targeted hide-all in `ideActivateTab` (cleaner than filtering by inline style attribute)
- `ccOpenDiffFromToolCard` includes `Authorization` header on fetch call (consistent with `ideOpenFile` API pattern)
- Both diff editor panes forced read-only via two mechanisms: `originalEditable: false` in createDiffEditor options AND `getOriginalEditor/getModifiedEditor().updateOptions({readOnly: true})` (belt-and-suspenders as per research Pitfall 3)
- Tasks 1 and 2 combined into a single commit because both tasks modify `app.js` and changes are interdependent (ccOpenDiffFromToolCard is part of Task 1 infrastructure used by Task 2 button wiring)

## Deviations from Plan

None — plan executed exactly as written. The plan already specified combining `ccOpenDiffFromToolCard` near `ideOpenDiffTab`.

## Issues Encountered
- Pre-existing test failure: `test_memory_tool.py::TestMemoryToolSearchScoring::test_search_shows_relevance_label` fails due to `patch.object` on a property without setter — confirmed pre-existing before any changes in this plan, unrelated to diff viewer work.

## User Setup Required
None — no external service configuration required.

## Next Phase Readiness
- Phase 4 complete: all 12 LAYOUT-01/02/03/04 tests XPASS
- Monaco diff editor ready for use in production
- No blockers for future phases

## Self-Check: PASSED

- FOUND: `.planning/workstreams/custom-claude-code-ui/phases/04-layout-diff-viewer/04-04-SUMMARY.md`
- FOUND: commit `6d57c41` (feat(04-04): add Monaco diff editor tabs and View Diff buttons on tool cards)

---
*Phase: 04-layout-diff-viewer*
*Completed: 2026-03-20*
