---
phase: 16-jcodemunch-deep-integration
plan: 01
subsystem: hooks
tags: [jcodemunch, mcp, context-loader, drift-detection, hooks]

requires:
  - phase: 11-mcp-server-integration
    provides: jcodemunch MCP server configured in .mcp.json
  - phase: 12-security-gate-hook
    provides: hook architecture and settings.json patterns
provides:
  - jcodemunch guidance emission in context-loader hook for 8 work types
  - mid-session drift detection via PostToolUse hook on get_symbol responses
  - settings.json registration for jcodemunch-reindex as PostToolUse hook
affects: [16-02 GSD workflow integration, context-loader, jcodemunch-reindex]

tech-stack:
  added: []
  patterns:
    - "Indirect MCP guidance via hook stderr output (hooks cannot call MCP directly)"
    - "Deduplication by (tool, key_param) tuple for combined work type guidance"
    - "Dual-event hook handling (PostToolUse + Stop) in single hook file"

key-files:
  created:
    - tests/test_context_loader_jcodemunch.py
    - tests/test_jcodemunch_drift.py
  modified:
    - .claude/hooks/context-loader.py
    - .claude/hooks/jcodemunch-reindex.py
    - .claude/settings.json

key-decisions:
  - "JCODEMUNCH_GUIDANCE dict does not hardcode repo_id; it is injected via emit_jcodemunch_guidance() parameter"
  - "Drift detection only checks get_symbol responses (not search_symbols or get_file_outline) since only get_symbol supports verify"
  - "jcodemunch-reindex.py registered in catch-all PostToolUse entry (no matcher) alongside token-tracker; hook self-filters for jcodemunch tools"
  - "PostToolUse drift detection always exits 0 (advisory); only Stop structural changes can block (exit 2)"

patterns-established:
  - "emit_jcodemunch_guidance returns list of strings (caller decides output format)"
  - "check_drift accepts both dict and JSON string tool_output for robustness"

requirements-completed: [JCMUNCH-01, JCMUNCH-05]

duration: 14min
completed: 2026-03-07
---

# Phase 16 Plan 01: jcodemunch Deep Integration - Hooks Summary

**Context-loader hook emits jcodemunch MCP tool guidance for 8 work types; jcodemunch-reindex hook detects mid-session source drift via PostToolUse content_verified checks**

## Performance

- **Duration:** 14 min
- **Started:** 2026-03-07T04:21:11Z
- **Completed:** 2026-03-07T04:35:23Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments
- Context-loader hook now emits structured jcodemunch MCP tool call recommendations for 8 work types (tools, security, providers, config, dashboard, memory, skills, testing)
- jcodemunch-reindex hook detects source code drift from PostToolUse get_symbol responses with content_verified=false
- Both enhancements are advisory (exit 0) and never block session flow
- 18 new tests covering guidance generation, drift detection, and integration scenarios

## Task Commits

Each task was committed atomically:

1. **Task 1: Add jcodemunch guidance emission to context-loader hook** - `13d8220` (test) + `7ea4611` (feat)
2. **Task 2: Add mid-session drift detection to jcodemunch-reindex hook** - `1199b31` (test) + `4929e54` (feat)

_Note: TDD tasks have separate test (RED) and feature (GREEN) commits_

## Files Created/Modified
- `tests/test_context_loader_jcodemunch.py` - 8 tests for guidance emission function and main() integration
- `tests/test_jcodemunch_drift.py` - 10 tests for drift detection and PostToolUse integration
- `.claude/hooks/context-loader.py` - Added JCODEMUNCH_GUIDANCE dict, emit_jcodemunch_guidance() function, and main() integration
- `.claude/hooks/jcodemunch-reindex.py` - Added check_drift() function and PostToolUse event handling
- `.claude/settings.json` - Registered jcodemunch-reindex.py for PostToolUse events

## Decisions Made
- JCODEMUNCH_GUIDANCE dict does not hardcode repo_id; it is injected via the emit_jcodemunch_guidance() parameter (default: "local/agent42")
- Drift detection only checks get_symbol responses since only get_symbol supports the verify parameter
- jcodemunch-reindex.py registered in the catch-all PostToolUse entry (no matcher) since the hook self-filters for jcodemunch tool names
- PostToolUse drift detection always exits 0 (advisory only); Stop structural changes retain blocking behavior (exit 2)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None - all tests passed on first implementation attempt.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Hook infrastructure ready for Phase 16 Plan 02 (GSD workflow integration)
- context-loader guidance pattern established and tested; can be extended with more work types
- Drift detection pattern established; future hooks can reuse check_drift() approach

## Self-Check: PASSED

All 6 files verified present. All 4 commits verified in git log. Test files exceed minimum line counts (134 >= 50, 149 >= 40).

---
*Phase: 16-jcodemunch-deep-integration*
*Completed: 2026-03-07*
