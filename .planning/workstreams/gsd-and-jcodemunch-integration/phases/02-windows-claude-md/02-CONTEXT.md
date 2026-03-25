# Phase 2: Windows + CLAUDE.md - Context

**Gathered:** 2026-03-24 (assumptions mode)
**Status:** Ready for planning

<domain>
## Phase Boundary

Users on Windows with Git Bash can run `bash setup.sh` without path errors, CRLF failures, or Python venv activation errors — setup completes successfully. Any user can generate a project CLAUDE.md pre-loaded with Agent42 conventions and pitfall patterns, and the generated file is project-aware (references correct project name, repo identifier, and active workstream).

</domain>

<decisions>
## Implementation Decisions

### Windows Path and Venv Compatibility
- **D-01:** Add platform detection at the top of `setup.sh` using `case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*` (pattern already exists in the `create-shortcut` subcommand). Set `VENV_ACTIVATE` and `PYTHON_CMD` variables that all subsequent steps use instead of hardcoded `.venv/bin/activate` and `python3`.
- **D-02:** In `setup_helpers.py`, use `sys.platform == "win32"` to select `.venv/Scripts/python.exe` vs `.venv/bin/python` for MCP config generation and health checks. Keep stdlib-only (no external deps), consistent with Phase 1 decision.
- **D-03:** Fix `python3` → `python` on Windows. Git Bash ships `python` not `python3`. Platform detection sets `PYTHON_CMD=python` on Windows, `PYTHON_CMD=python3` on Linux/macOS.

### CRLF Prevention
- **D-04:** Add `.gitattributes` to the repo root enforcing LF line endings on `*.sh` and `*.py` files (`*.sh text eol=lf`, `*.py text eol=lf`). This prevents CRLF contamination at the git level — the root cause, not a runtime workaround.
- **D-05:** Do NOT add a runtime CRLF-stripping preamble to setup.sh. The `.gitattributes` approach is the correct fix. Runtime stripping doesn't protect Python shebang lines or hook scripts called from setup.sh.

### CLAUDE.md Template Generation
- **D-06:** Generate a parameterized CLAUDE.md template, NOT a verbatim copy of Agent42's own CLAUDE.md. The template includes: hook protocol table, memory system description, architecture patterns overview, curated pitfall patterns, and testing standards — but adapted for a project *using* Agent42 as an MCP server, not for Agent42 development itself.
- **D-07:** Template is project-aware — inject detected values: project name (from directory name or git remote), jcodemunch repo identifier, active GSD workstream name (if any), venv path, and MCP server configuration status.
- **D-08:** Invocation is a `setup.sh` subcommand: `bash setup.sh generate-claude-md`. This follows the existing subcommand pattern (`sync-auth`, `create-shortcut`). It is NOT part of the default `bash setup.sh` flow to avoid overwriting existing CLAUDE.md files without consent.
- **D-09:** If a CLAUDE.md already exists, merge new sections rather than overwrite. Print a diff summary showing what was added. If no CLAUDE.md exists, generate from scratch.

### Claude's Discretion
- Exact content curation for the pitfalls section (which of the 124 pitfalls are relevant to general users vs Agent42-internal)
- Template section ordering and formatting
- How to detect project name (directory basename vs git remote parsing)
- Whether to include the full Common Pitfalls table or a curated top-20

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Setup scripts (modify targets)
- `setup.sh` — Main setup script. Windows fixes apply here. Has `--quiet` mode, `set -e`, colored logging. Already has MINGW/MSYS detection in `create-shortcut` subcommand (lines 66-67) to reuse.
- `scripts/setup_helpers.py` — Python setup library. Hardcodes `.venv/bin/python` at lines 216, 391. Must add platform-aware venv paths.

### Configuration files
- `.mcp.json` — Already has correct Windows paths (manually configured). Template for generated configs.
- `.claude/settings.json` — Hook registration target. Commands use `cd /abs/path && python ...` format.
- `.claude/hooks/` — All hook scripts. Check shebangs and path references for Windows compatibility.

### Template source material
- `CLAUDE.md` — Agent42's own CLAUDE.md. Source material for the template generator. Contains hook protocol, architecture patterns, security requirements, testing standards, and 124 pitfalls.
- `.claude/reference/pitfalls-archive.md` — Pitfalls 1-80 archived here. May be needed for full pitfall inclusion.

### Requirements
- `.planning/workstreams/gsd-and-jcodemunch-integration/REQUIREMENTS.md` — SETUP-06 and SETUP-07 acceptance criteria.

### Prior phase context
- `.planning/workstreams/gsd-and-jcodemunch-integration/phases/01-setup-foundation/01-CONTEXT.md` — Phase 1 decisions on setup.sh structure, merge strategies, health reporting.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `setup.sh` create-shortcut subcommand (lines 58-97): Already has `MINGW*|MSYS*|CYGWIN*` platform detection pattern — extract and reuse at script top level.
- `setup_helpers.py` `CLAUDE_MD_TEMPLATE` (lines 80-117): Existing memory-section template. Extend or replace with full conventions template.
- `setup_helpers.py` `generate_claude_md_section()`: Existing generation function to expand.
- Colored logging helpers in `setup.sh` (`info()`, `warn()`, `error()`): All new output must use these.

### Established Patterns
- Subcommand pattern in setup.sh: `case "$1" in sync-auth|create-shortcut)` — add `generate-claude-md` here.
- Idempotency: `if [ ! -f ... ]; then ... else info "already exists — skipping"; fi` — same pattern for .gitattributes creation.
- stdlib-only in setup_helpers.py: No external deps. Use `sys.platform`, `os.name`, `pathlib` for platform detection.
- Phase 1 decisions: hook frontmatter reading, MCP config merge, health thresholds — all still apply.

### Integration Points
- `setup.sh` main flow: Platform detection must happen before venv activation (line ~275). All `python3` calls must use `$PYTHON_CMD`.
- `setup_helpers.py` CLI: Add `generate-claude-md` as a new subcommand alongside existing `hooks`, `mcp-config`, `claude-md`, `health`.
- `.gitattributes`: New file at repo root. Commit alongside other Phase 2 changes.

</code_context>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches.

</specifics>

<deferred>
## Deferred Ideas

- `setup.ps1` for native PowerShell users — could be a future enhancement but SETUP-06 only requires Git Bash support.
- Auto-update CLAUDE.md when new pitfalls accumulate (ENT-03 in v2 requirements) — out of scope, requires human approval gate.

</deferred>

---

*Phase: 02-windows-claude-md*
*Context gathered: 2026-03-24*
