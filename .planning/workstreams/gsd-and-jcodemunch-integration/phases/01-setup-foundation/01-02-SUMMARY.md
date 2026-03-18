---
phase: 01-setup-foundation
plan: 02
subsystem: infra
tags: [mcp, setup, hooks, health-check, python-stdlib]

# Dependency graph
requires:
  - phase: 01-setup-foundation plan 01
    provides: Hook frontmatter format and setup.sh extension patterns
provides:
  - scripts/setup_helpers.py with generate_mcp_config, read_hook_metadata, register_hooks, check_health, print_health_report
  - mcp_server.py --health flag for post-setup health validation
  - CLI interface: mcp-config, register-hooks, health subcommands (stdlib only)
affects: [setup-foundation-plan-03, setup.sh integration]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "stdlib-only helper library: json, os, subprocess, urllib.request — no pip deps for setup tools"
    - "Hook frontmatter parsing: read leading # comment lines until first non-comment line"
    - "Idempotent JSON merge: load existing, add-only strategy, never overwrite existing entries"
    - "MCP health check via --health flag: exit 0 success, exit 1 failure, stderr for messages (stdout reserved for MCP protocol)"

key-files:
  created:
    - scripts/setup_helpers.py
  modified:
    - mcp_server.py

key-decisions:
  - "stdlib-only for setup_helpers.py — no external dependencies so setup can run before pip install"
  - "agent42 .mcp.json entry replaced only when command path does not exist on disk (stale path detection)"
  - "Health check exits 0 when >=3 of 5 services healthy — Qdrant and Redis are warnings not errors"
  - "Hook registration uses (event, matcher) tuple grouping to match existing settings.json block structure"

patterns-established:
  - "MCP health probe pattern: --health flag checks imports/config, exits without starting transport"
  - "Frontmatter parser: iterate # comment lines, stop at first non-comment line"

requirements-completed: [SETUP-01, SETUP-02, SETUP-04, SETUP-05]

# Metrics
duration: 12min
completed: 2026-03-18
---

# Phase 1 Plan 02: Python Setup Helpers and MCP Health Check Summary

stdlib-only Python helper library generating .mcp.json and .claude/settings.json, plus --health flag on mcp_server.py for post-setup validation

## Performance

- **Duration:** ~12 min
- **Started:** 2026-03-18T00:00:00Z
- **Completed:** 2026-03-18T00:12:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Created `scripts/setup_helpers.py` with all 5 required functions callable as module or CLI
- `generate_mcp_config()` merges into existing .mcp.json with stale-path detection for agent42 entry
- `register_hooks()` reads hook frontmatter and merges registrations into settings.json idempotently
- `check_health()` runs 5 probes (MCP server, jcodemunch, Qdrant, Redis, Claude CLI) with colored ANSI output
- Added `--health` flag to `mcp_server.py` — verifies imports/config without starting a transport

## Task Commits

Each task was committed atomically:

1. **Task 1: Create scripts/setup_helpers.py** - `6c3445c` (feat)
2. **Task 2: Add --health flag to mcp_server.py** - `ed7295b` (feat)

Auto-fix: `aadaa6f` (fix — directory creation in generate_mcp_config)

## Files Created/Modified

- `scripts/setup_helpers.py` - MCP config generation, hook registration, health probe library (stdlib only)
- `mcp_server.py` - Added --health CLI flag in main() before transport parsing

## Decisions Made

- Used stdlib only (json, os, subprocess, urllib.request) so setup_helpers.py runs before pip install
- Chose `settings = Settings.from_env()` as the health check payload — validates config is loadable
- Linter removed unused Tool/ToolResult/Agent imports from --health block; Settings import retained as the meaningful check
- `generate_mcp_config()` creates the target directory if it doesn't exist (needed for new projects)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Added os.makedirs() before writing .mcp.json**

- **Found during:** Post-task verification of mcp-config subcommand
- **Issue:** `generate_mcp_config()` crashed with FileNotFoundError when the target `project_dir` did not exist on disk
- **Fix:** Added `os.makedirs(project_dir, exist_ok=True)` before opening the output file
- **Files modified:** scripts/setup_helpers.py
- **Verification:** `python3 scripts/setup_helpers.py mcp-config <tmpdir>` succeeds when tmpdir is pre-created
- **Committed in:** aadaa6f (separate fix commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 — bug)

**Impact on plan:** Necessary fix for correct behavior on new projects. No scope creep.

## Issues Encountered

Pre-existing test failure in `tests/test_auth_flow.py::TestAuthIntegration::test_protected_endpoint_requires_auth` (404 vs 401). Confirmed pre-existing before my changes via git stash. Not caused by this plan.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `scripts/setup_helpers.py` ready for `setup.sh` integration (Plan 03)
- All 5 functions tested and importable
- `mcp_server.py --health` ready for health check section of setup.sh
- Verified: jcodemunch indexing helper (Plan 03) can call `register_hooks()` and `generate_mcp_config()` directly

## Self-Check: PASSED

- FOUND: scripts/setup_helpers.py
- FOUND: mcp_server.py (with --health flag)
- FOUND: 01-02-SUMMARY.md
- FOUND commit 6c3445c (Task 1: setup_helpers.py)
- FOUND commit ed7295b (Task 2: --health flag)
- FOUND commit aadaa6f (Auto-fix: directory creation)

---

*Phase: 01-setup-foundation*
*Completed: 2026-03-18*
