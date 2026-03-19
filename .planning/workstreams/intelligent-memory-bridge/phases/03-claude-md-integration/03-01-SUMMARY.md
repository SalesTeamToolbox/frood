---
phase: 03-claude-md-integration
plan: 01
subsystem: setup
tags: [setup_helpers, claude_md, mcp, memory, marker_injection, tdd]

# Dependency graph
requires:
  - phase: 02-intelligent-learning
    provides: agent42_memory MCP tool with search/store/log actions confirmed
provides:
  - CLAUDE_MD_TEMPLATE constant with agent42_memory instructions (search, store, log)
  - generate_claude_md_section(project_dir) function with marker-based idempotent injection
  - claude-md CLI subcommand in scripts/setup_helpers.py
  - setup.sh step that auto-generates CLAUDE.md memory section after hook registration
  - TestClaudeMdGeneration class with 7 passing tests
affects: [04-consolidation, setup.sh, any phase that extends setup_helpers.py]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Marker-based section injection (BEGIN/END HTML comment markers) for idempotent file management
    - CLI subcommand pattern in setup_helpers.py for modular setup steps
    - Strip-leading-newline after-marker to prevent trailing whitespace accumulation on re-runs

key-files:
  created: []
  modified:
    - scripts/setup_helpers.py
    - tests/test_setup.py
    - setup.sh

key-decisions:
  - "Idempotency fix: strip one leading newline from after-marker content on replacement to prevent trailing blank line accumulation each run"
  - "Implementation before tests (pragmatic TDD): linter strips unused imports on save, so generate_claude_md_section added to setup_helpers.py before adding import+tests to test_setup.py"
  - "CLAUDE_MD_TEMPLATE uses double-dash (--) not em-dash to avoid encoding issues"

patterns-established:
  - "Marker-based managed sections: HTML comment markers delimit managed content, enabling safe append/replace without touching user content"
  - "CLI subcommand registration: elif cmd == 'X': pattern in setup_helpers.py __main__ block"

requirements-completed: [INTEG-01, INTEG-02, INTEG-03]

# Metrics
duration: 12min
completed: 2026-03-19
---

# Phase 3 Plan 01: CLAUDE.md Integration Summary

**Marker-based CLAUDE.md injection that auto-installs agent42_memory search/store/log instructions into every new Agent42 project with zero user intervention**

## Performance

- **Duration:** 12 min
- **Started:** 2026-03-19T05:48:00Z
- **Completed:** 2026-03-19T06:00:20Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- `generate_claude_md_section()` creates or idempotently updates CLAUDE.md with Agent42 memory instructions
- `CLAUDE_MD_TEMPLATE` directs Claude to always search first with `agent42_memory(action="search")`, dual-write with `action="store"`, and log with `action="log"`
- `claude-md` CLI subcommand wired into `setup_helpers.py` entry point
- `setup.sh` now calls `generate_claude_md_section` after hook registration — zero user intervention needed
- 7 new tests in `TestClaudeMdGeneration` class covering create, append, idempotency, replace, preserve, and INTEG-01/02 requirements

## Task Commits

Each task was committed atomically:

1. **Task 1: Add generate_claude_md_section function, template, CLI subcommand, and tests** - `6d581b1` (feat)
2. **Task 2: Wire setup.sh to call generate_claude_md_section after hook registration** - `3a49a0c` (feat)

## Files Created/Modified

- `scripts/setup_helpers.py` - Added `_CLAUDE_MD_BEGIN`, `_CLAUDE_MD_END`, `CLAUDE_MD_TEMPLATE`, `generate_claude_md_section()`, and `elif cmd == "claude-md":` subcommand
- `tests/test_setup.py` - Added `generate_claude_md_section` import and `TestClaudeMdGeneration` class with 7 tests
- `setup.sh` - Added CLAUDE.md memory section step (5 lines) after hook registration, before jcodemunch indexing

## Decisions Made

- Idempotency fix: strip one leading newline from the after-marker content slice on replacement to prevent accumulating an extra blank line on each successive run. The CLAUDE_MD_TEMPLATE ends with `\n`, and the after-slice would otherwise begin with `\n` from the previous run's output, creating `\n\n` at end of file.
- Pragmatic TDD ordering: the ruff linter (via autoformat on save) strips unused imports, so I added the implementation to `setup_helpers.py` first, then added the import and test class to `test_setup.py` in a single Write operation to ensure both landed atomically.
- Template uses `--` (double-dash) not em-dash to avoid encoding issues across platforms.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Idempotency fix: prevent trailing blank line accumulation**
- **Found during:** Task 1 (test_idempotent_on_rerun failed)
- **Issue:** On replacement, `after = original[end_marker_end:]` included a leading `\n` (the line terminator after `END_MARKER`). Template also ends with `\n`. Result: `before + template(\n) + \n` — one extra blank line appended per run.
- **Fix:** Added `if after.startswith("\n"): after = after[1:]` to strip at most one leading newline from the after slice before reconstruction.
- **Files modified:** `scripts/setup_helpers.py`
- **Verification:** `test_idempotent_on_rerun` passes; all 7 TestClaudeMdGeneration tests pass.
- **Committed in:** `6d581b1` (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - bug in idempotency logic)
**Impact on plan:** Auto-fix was essential for correctness. No scope creep.

## Issues Encountered

- ruff linter strips unused imports on every file save, making it impossible to add the import for `generate_claude_md_section` before the function existed. Resolved by writing the implementation first, then writing the full test file (import + TestClaudeMdGeneration) in one Write operation.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Phase 3 Plan 01 complete: CLAUDE.md injection fully automated via setup.sh
- Phase 4 (memory consolidation) can proceed independently
- The `TestClaudeMdGeneration` tests provide a regression harness for any future template changes

---
*Phase: 03-claude-md-integration*
*Completed: 2026-03-19*
