---
phase: 01-setup-foundation
plan: 03
subsystem: infra
tags: [jcodemunch, mcp, setup, bash, pytest, json-rpc]

# Dependency graph
requires:
  - phase: 01-setup-foundation/01-01
    provides: hook frontmatter on all 12 .claude/hooks/*.py files
  - phase: 01-setup-foundation/01-02
    provides: setup_helpers.py with generate_mcp_config, register_hooks, check_health, print_health_report CLI

provides:
  - scripts/jcodemunch_index.py — MCP JSON-RPC client for jcodemunch indexing via uvx subprocess
  - setup.sh extended with PROJECT_DIR, SSH alias prompt, MCP config, hook registration, jcodemunch indexing, and health report sections
  - Full test coverage in tests/test_setup.py (28 passing, 2 integration skips)

affects: [02-windows-claude-md, 03-memory-sync, any phase using setup.sh or jcodemunch indexing]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "MCP JSON-RPC over stdio: initialize → notifications/initialized → tools/call, read id=N response with threading timeout"
    - "setup.sh extensions: insert sections before Done banner, use PROJECT_DIR for absolute paths, if ! cmd ; then warn ; fi for soft failures"
    - "Mock subprocess.Popen with io.StringIO stdout for MCP client unit tests"

key-files:
  created:
    - scripts/jcodemunch_index.py
    - .planning/workstreams/gsd-and-jcodemunch-integration/phases/01-setup-foundation/deferred-items.md
  modified:
    - setup.sh
    - tests/test_setup.py

key-decisions:
  - "jcodemunch indexing failure treated as warning in setup.sh (if ! ...; then warn) — never stops setup with set -e"
  - "SSH alias prompt suppressed in --quiet mode; MCP config omits agent42-remote when alias is empty"
  - "Health report only printed in interactive mode (! $QUIET) — CI/deployment pipelines skip it"
  - "PROJECT_DIR set via cd $(dirname $0) && pwd to get absolute path regardless of invocation location"
  - "Threading-based response reader with join(timeout) for MCP subprocess — avoids blocking on unresponsive server"

patterns-established:
  - "Soft failures in setup: 'if ! python3 script.py; then warn; fi' — set -e friendly"
  - "MCP stdio client pattern: Popen + write JSON lines + threading.Thread reader + join(timeout)"
  - "Test strategy: mock subprocess.Popen with io.StringIO for synchronous stdout simulation"

requirements-completed: [SETUP-01, SETUP-02, SETUP-03, SETUP-04, SETUP-05]

# Metrics
duration: 8min
completed: 2026-03-18
---

# Phase 1 Plan 03: jcodemunch Indexing Script + Extended setup.sh Summary

**MCP JSON-RPC stdio client (jcodemunch_index.py) + setup.sh extended with SSH alias, MCP config, hook registration, jcodemunch indexing, and health report; all stubs replaced with 28 real tests**

## Performance

- **Duration:** 8 min
- **Started:** 2026-03-18T19:46:59Z
- **Completed:** 2026-03-18T19:54:25Z
- **Tasks:** 3
- **Files modified:** 3 (scripts/jcodemunch_index.py created, setup.sh extended, tests/test_setup.py rewritten)

## Accomplishments

- Created `scripts/jcodemunch_index.py` — stdlib-only MCP JSON-RPC client that spawns `uvx jcodemunch-mcp`, sends initialize + notifications/initialized + tools/call index_folder, reads response with threading timeout (default 120s), returns bool (never raises)
- Extended `setup.sh` with 4 new sections: SSH alias prompt (suppressed in --quiet), MCP config generation, hook registration, jcodemunch indexing (soft failure), health report (suppressed in --quiet); added PROJECT_DIR absolute path variable; updated Done banner
- Replaced all 26 `pytest.skip("Stub")` calls in `tests/test_setup.py` with real implementations covering all 9 test classes; 28 passing, 2 integration skips

## Task Commits

1. **Task 1: Create scripts/jcodemunch_index.py** — `2c913fb` (feat)
2. **Task 2: Extend setup.sh** — `89a68e2` (feat)
3. **Task 3: Implement test cases** — `ec41c29` (test)

## Files Created/Modified

- `scripts/jcodemunch_index.py` — MCP JSON-RPC stdio client with ensure_uvx(), index_project(), and CLI entry point
- `setup.sh` — Extended with PROJECT_DIR, SSH alias prompt, mcp-config, register-hooks, jcodemunch indexing (soft fail), health report
- `tests/test_setup.py` — All stubs replaced; tests for MCP config generation/merge, hook frontmatter, hook registration/merge, jcodemunch indexing (mocked), health report formatting

## Decisions Made

- jcodemunch indexing failure is a warning, not a hard error (`if ! ...; then warn`) — setup must complete even if uvx is absent
- SSH alias prompt is the first new section so the value is available to mcp-config immediately after
- Health report is suppressed in quiet mode — deployment scripts (`install-server.sh --quiet`) should not print interactive output
- `PROJECT_DIR` uses `cd "$(dirname "$0")" && pwd` — works regardless of where the script is invoked from
- Threading-based MCP reader with `join(timeout)` — avoids deadlock when jcodemunch subprocess hangs

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

Pre-existing test failure in `tests/test_auth_flow.py::TestAuthIntegration::test_protected_endpoint_requires_auth` (404 vs 401) — unrelated to setup scripts, logged to `deferred-items.md`. Not caused by this plan's changes.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

Phase 1 (Setup Foundation) is complete. All 3 plans delivered:
- 01-01: Hook frontmatter on 12 hook files + test stubs
- 01-02: setup_helpers.py (generate_mcp_config, register_hooks, check_health) + mcp_server.py --health
- 01-03: jcodemunch_index.py + extended setup.sh + 28 real tests

`bash setup.sh` on Linux/VPS now produces a fully configured Agent42 + Claude Code environment in one command.

Ready for Phase 2 (Windows + CLAUDE.md) or Phase 3 (Memory Sync) — both depend only on Phase 1.

---
*Phase: 01-setup-foundation*
*Completed: 2026-03-18*
