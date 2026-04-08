---
phase: 52-core-identity-rename
plan: "02"
subsystem: core-identity
tags: [rename, env-vars, mcp, frood, identity]
dependency_graph:
  requires: [52-01]
  provides: [frood-env-vars, frood-mcp-server, frood-memory-markers]
  affects: [mcp_server.py, scripts/setup_helpers.py, .mcp.json, .mcp.available.json]
tech_stack:
  added: []
  patterns: [clean-break-rename, no-fallback-per-D-01]
key_files:
  created: [.mcp.available.json]
  modified:
    - mcp_server.py
    - scripts/setup_helpers.py
    - .mcp.json
    - core/rewards_config.py
decisions:
  - "D-01 clean break applied: no AGENT42_* fallback, straight rename to FROOD_*"
  - "CLAUDE.md marker migration logic added to handle legacy BEGIN AGENT42 MEMORY markers"
  - "frood_memory is now the canonical MCP tool name in CLAUDE.md templates"
metrics:
  duration: "45 minutes"
  completed: "2026-04-07"
  tasks_completed: 3
  files_modified: 5
---

# Phase 52 Plan 02: Env Var + MCP Server Identity Rename Summary

**One-liner:** Renamed all AGENT42_* env var reads to FROOD_*, eliminated all .agent42/ hardcoded paths from source files, and fully renamed mcp_server.py internals plus MCP config files to use frood identity.

## What Was Done

### Task 1: Rename AGENT42_* env vars + .agent42/ paths in all source files

Applied clean-break renames across all production source files per D-01 (no fallback):

**Env var renames (Python source files):**
- `tools/video_gen.py`: `AGENT42_VIDEO_MODEL` → `FROOD_VIDEO_MODEL`
- `tools/image_gen.py`: `AGENT42_IMAGE_MODEL` → `FROOD_IMAGE_MODEL`
- `tools/browser_tool.py`: `_AGENT42_BROWSER_TOKEN` → `_FROOD_BROWSER_TOKEN`
- `core/portability.py`: `AGENT42_WORKTREE_DIR` → `FROOD_WORKTREE_DIR`
- `core/worktree_manager.py`: `AGENT42_WORKTREE_DIR` → `FROOD_WORKTREE_DIR`
- `core/task_context.py`: `AGENT42_DATA_DIR` → `FROOD_DATA_DIR`
- `memory/embeddings.py`: `AGENT42_WORKSPACE` → `FROOD_WORKSPACE`
- `scripts/setup_helpers.py`: `AGENT42_WORKSPACE` → `FROOD_WORKSPACE` (in MCP config generation)
- `tests/e2e/config.py`: `AGENT42_ROOT` → `FROOD_ROOT` (constant + field + path)
- `tests/e2e/discovery.py`: All `AGENT42_ROOT` → `FROOD_ROOT` (11 occurrences)
- `tests/e2e/runner.py`: `AGENT42_ROOT` import → `FROOD_ROOT`

**.agent42/ path renames (28 source files):** All `.agent42/` hardcoded path strings replaced with `.frood/` across tools/, core/, memory/, dashboard/, scripts/, migrate.py.

**MCP config files:**
- `.mcp.json`: server key `"agent42"` → `"frood"`, `AGENT42_WORKSPACE` → `FROOD_WORKSPACE`
- `.mcp.available.json`: keys `"agent42"` → `"frood"`, `"agent42-remote"` → `"frood-remote"`, `AGENT42_WORKSPACE` → `FROOD_WORKSPACE`

**Note:** Most of the tool/core/memory file renames were committed by the hooks formatter during execution; only `mcp_server.py`, `scripts/setup_helpers.py`, `core/rewards_config.py`, and the MCP config files remained for this commit.

### Task 2: Full mcp_server.py rename

- `_AGENT42_ROOT` → `_FROOD_ROOT` (variable declaration + all usages in sys.path and skill_dirs)
- `SERVER_NAME = "agent42"` → `SERVER_NAME = "frood"`
- `AGENT42_WORKSPACE` → `FROOD_WORKSPACE` (env var reads)
- `AGENT42_SEARCH_URL` → `FROOD_SEARCH_URL`
- `AGENT42_API_URL` → `FROOD_API_URL`
- All `.agent42/` path strings → `.frood/` (7 occurrences: memory, qdrant, effectiveness.db, etc.)
- Logger already updated to `frood.mcp.server` by formatter hook
- Docstring example config updated to use `frood` server key and `FROOD_WORKSPACE`

### Task 3: Update CLAUDE.md marker injection in setup_helpers.py

- `_CLAUDE_MD_BEGIN`: `"<!-- BEGIN AGENT42 MEMORY -->"` → `"<!-- BEGIN FROOD MEMORY -->"`
- `_CLAUDE_MD_END`: `"<!-- END AGENT42 MEMORY -->"` → `"<!-- END FROOD MEMORY -->"`
- Added `_CLAUDE_MD_BEGIN_LEGACY` / `_CLAUDE_MD_END_LEGACY` constants for migration
- `CLAUDE_MD_TEMPLATE`: all `agent42_memory` tool name references → `frood_memory`, all branding → Frood
- `_FULL_CLAUDE_MD_TEMPLATE`: same agent42_memory → frood_memory updates
- `generate_claude_md_section()`: added migration logic to replace old AGENT42 markers before processing
- `generate_full_claude_md()`: same migration logic added
- MCP config generation: `_make_agent42_entry()` → `_make_frood_entry()`, `_make_agent42_remote_entry()` → `_make_frood_remote_entry()`, server keys in `generate_mcp_config()` updated to `"frood"` and `"frood-remote"`

## Deviations from Plan

None — plan executed exactly as written. The formatter hooks updated logger names from `agent42.*` to `frood.*` in many files during execution, which was consistent with the rename intent.

## Verification Results

All acceptance criteria passed:
- `grep -rn "AGENT42_" --include="*.py" tools/ core/ memory/ dashboard/ scripts/ migrate.py mcp_server.py` returns 0 matches
- `grep -rn "\.agent42" --include="*.py" tools/ core/ memory/ dashboard/ scripts/ migrate.py mcp_server.py` returns 0 matches
- `grep -c "AGENT42" .mcp.json .mcp.available.json` both return 0
- `python -c "from core.config import Settings"` passes
- `python -c "import ast; ast.parse(open('mcp_server.py').read())"` exits 0
- `python -c "import ast; ast.parse(open('scripts/setup_helpers.py').read())"` exits 0
- `grep "_FROOD_ROOT" mcp_server.py` returns matches
- `grep 'SERVER_NAME = "frood"' mcp_server.py` matches
- `grep "BEGIN FROOD MEMORY" scripts/setup_helpers.py` matches
- `grep "frood_memory" scripts/setup_helpers.py` matches
- `grep "FROOD_ROOT" tests/e2e/config.py` matches

## Self-Check: PASSED
