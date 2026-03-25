---
phase: 02-windows-claude-md
plan: 02
subsystem: setup-tooling
tags: [claude-md, template-generation, project-context, tdd, windows-compat]
dependency_graph:
  requires: [02-01]
  provides: [generate-claude-md subcommand, _detect_project_context, generate_full_claude_md]
  affects: [setup.sh, scripts/setup_helpers.py, tests/test_setup.py]
tech_stack:
  added: []
  patterns: [marker-based merge, TDD red-green, parameterized template, difflib diff summary]
key_files:
  created: []
  modified:
    - scripts/setup_helpers.py
    - tests/test_setup.py
    - setup.sh
decisions:
  - "Template is for consumer projects using Agent42 as MCP server, not a copy of Agent42's own CLAUDE.md (per D-06)"
  - "generate-claude-md is a standalone subcommand, not part of default setup flow (per D-08)"
  - "Reused existing _CLAUDE_MD_BEGIN/_CLAUDE_MD_END marker merge logic for idempotency (per D-09)"
  - "difflib unified diff used for change summary output (no new dependencies)"
metrics:
  duration: 9 min
  completed: "2026-03-25T02:38:27Z"
  tasks: 2
  files: 3
---

# Phase 02 Plan 02: CLAUDE.md Template Generation Summary

CLAUDE.md template generation with project-aware context detection using `_detect_project_context()` and `generate_full_claude_md()`, wired into `setup.sh` as an opt-in `generate-claude-md` subcommand.

## What Was Built

### Task 1: _detect_project_context() + generate_full_claude_md() + tests

**`_detect_project_context(project_dir)`** detects:
- Project name from directory basename or git remote URL (HTTPS and SSH formats both handled)
- jcodemunch repo ID as `local/{project_name}`
- Active GSD workstream by scanning `.planning/workstreams/*/STATE.md` for `status: active`
- Platform-correct venv python path via existing `_venv_python()`

**`_FULL_CLAUDE_MD_TEMPLATE`** contains these sections (parameterized with `{project_name}` and `{jcodemunch_repo}`):
- Quick Reference — pytest commands
- Codebase Navigation (jcodemunch) — tool usage table with repo identifier
- Agent42 Hook Protocol — hook trigger table explaining what hooks do for users
- Agent42 Memory — search/store/log instructions for `agent42_memory` tool
- Testing Standards — pytest conventions, `tmp_path`, `pytest-asyncio`
- Common Pitfalls — 20-row table covering async I/O, security, Windows compat, jcodemunch, deployment
- Project — project name, jcodemunch repo, optional active workstream

**`generate_full_claude_md(project_dir)`**:
- Creates CLAUDE.md from scratch if absent
- Merges into existing CLAUDE.md using `_CLAUDE_MD_BEGIN`/`_CLAUDE_MD_END` markers
- Appends to end of file if no markers found
- Prints unified diff summary of lines added/removed
- Fully idempotent (same output on re-run)

**Tests added (20 new tests across 2 classes):**
- `TestProjectContext` (6 tests): directory name, HTTPS remote, SSH remote, jcodemunch_repo, active workstream, no workstream
- `TestClaudeMdFull` (14 tests): hook protocol, memory instructions, project name, jcodemunch repo, merge into existing, idempotency, pitfalls, testing standards, codebase nav, outside-marker preservation, hook table rows, marker replacement, project section, quick reference

### Task 2: generate-claude-md subcommand in setup.sh

Added `if [ "$1" = "generate-claude-md" ]; then` block:
- Positioned after `create-shortcut` and before `QUIET=false`
- Uses `$PYTHON_CMD` (set by platform detection block from Plan 01) for Windows compat
- Delegates to `scripts/setup_helpers.py generate-claude-md "$PROJECT_DIR"`
- Updated header comments to document the new subcommand

## Commits

| Commit | Message |
|--------|---------|
| `9d5b40b` | feat(02-02): add _detect_project_context + generate_full_claude_md + 20 tests |
| `5759293` | feat(02-02): wire generate-claude-md subcommand into setup.sh |

## Verification Results

```
python -m pytest tests/test_setup.py -x -q       → 60 passed, 2 skipped
python -m pytest tests/test_setup.py -k "TestProjectContext or TestClaudeMdFull"  → 20 passed
bash -n setup.sh                                  → syntax OK
grep "generate-claude-md" setup.sh                → found in header + subcommand block
grep "generate_full_claude_md" scripts/setup_helpers.py  → found
grep "_detect_project_context" scripts/setup_helpers.py  → found
```

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None. All template sections are fully populated with real content. The `{active_workstream_line}` placeholder renders as empty string when no workstream is active (intentional behavior per plan).

## Self-Check: PASSED

- `scripts/setup_helpers.py` modified: confirmed (contains `_detect_project_context`, `generate_full_claude_md`, `_FULL_CLAUDE_MD_TEMPLATE`, `generate-claude-md` CLI dispatch)
- `tests/test_setup.py` modified: confirmed (contains `TestProjectContext`, `TestClaudeMdFull`, 20 new tests)
- `setup.sh` modified: confirmed (contains `generate-claude-md` subcommand block, header comment)
- Commits exist: `9d5b40b`, `5759293` — both verified via `git log --oneline -5`
