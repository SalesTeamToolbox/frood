# Phase 3: CLAUDE.md Integration - Context

**Gathered:** 2026-03-18
**Status:** Ready for planning

<domain>
## Phase Boundary

Make Claude prefer Agent42 memory for both reads and writes by default via CLAUDE.md instructions, and have `setup.sh` automatically generate the memory section when Agent42 is installed — no user intervention needed. Covers requirements INTEG-01, INTEG-02, INTEG-03.

</domain>

<decisions>
## Implementation Decisions

### Memory Read Instructions (INTEG-01)
- **Always search first**: CLAUDE.md must instruct Claude to ALWAYS call `agent42_memory search` before answering from memory
- This applies to every memory-related question — no "prefer" or "when you feel like it"
- Unified view: instructions reference `agent42_memory search` only — the tool internally searches both `memory` and `knowledge` collections. Claude doesn't need to know about the internal split

### Memory Write Instructions (INTEG-02)
- **Dual-write**: Claude must call `agent42_memory store` AND use its built-in auto-memory
- Belt-and-suspenders approach — CC auto-memory still works as backup, Phase 1 hook syncs CC→Qdrant anyway
- Operation-specific instructions: separate guidance for (1) search/recall — "always search before answering", (2) store — "store important decisions and learnings", (3) log — "log significant events"

### Setup.sh Generation (INTEG-03)
- **Append section**: setup.sh appends a clearly-delimited memory section to existing CLAUDE.md using marker comments (`<!-- BEGIN AGENT42 MEMORY -->` / `<!-- END AGENT42 MEMORY -->`)
- Preserves all user content outside the markers
- **Memory section only**: does NOT generate broader project instructions (test commands, architecture, conventions). Users maintain the rest of CLAUDE.md themselves
- **If no CLAUDE.md exists**: create a new file containing just the Agent42 memory section plus a brief header
- **Static text**: the memory section is identical for every project — no dynamic substitution (workspace path, project name). Agent42 MCP tools already know the workspace from their config
- **Template location**: multi-line string constant in `setup_helpers.py` alongside `generate_mcp_config()` and `register_hooks()`. One file for all setup logic, stdlib-only

### Idempotency & Updates
- **Marker-based replacement**: on re-run, find markers and replace everything between them with latest template version
- User content outside markers is preserved
- User edits between markers are overwritten — clear contract: markers = managed by setup.sh
- No hash comparison, no backup, no warning — just replace

### Claude's Discretion
- Exact wording of the memory instructions (as long as "always search first" and "dual-write" semantics are preserved)
- Marker comment format (HTML comments, or another convention that Claude Code won't interpret)
- Whether to add a brief explanation paragraph before the instruction list
- `setup_helpers.py` function name and internal structure
- How `setup.sh` calls the new function (new CLI subcommand or integrated into existing flow)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Setup Infrastructure
- `setup.sh` — Main setup script; currently generates .mcp.json + hooks but no CLAUDE.md step. New step goes here
- `scripts/setup_helpers.py` — Python helpers for setup (MCP config, hook registration). Memory section template + injection logic goes here

### Memory Tools
- `tools/memory_tool.py` — MemoryTool with store/recall/search/log/reindex_cc actions. Instructions must reference these actions accurately
- `mcp_server.py` — MCP server tool exposure; `agent42_memory` tool registration

### Existing CLAUDE.md Patterns
- `CLAUDE.md` (project root) — The project's own CLAUDE.md as a reference for style and structure
- `tools/context_assembler.py` — Already reads CLAUDE.md as part of context assembly (line 169)

### Requirements
- `.planning/workstreams/intelligent-memory-bridge/REQUIREMENTS.md` — INTEG-01, INTEG-02, INTEG-03 acceptance criteria

### Prior Phase Context
- `.planning/workstreams/intelligent-memory-bridge/phases/01-auto-sync-hook/01-CONTEXT.md` — Hook architecture, sync visibility, reindex_cc action
- `.planning/workstreams/intelligent-memory-bridge/phases/02-intelligent-learning/02-CONTEXT.md` — Knowledge collection, extraction approach, unified view decision

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `setup_helpers.py` — `generate_mcp_config()` and `register_hooks()` provide the pattern for a new `generate_claude_md_section()` function. All stdlib-only, CLI-callable
- `setup.sh` — Existing hook registration step (line 116-117) shows the bash-calls-Python pattern for the new CLAUDE.md step

### Established Patterns
- `setup_helpers.py` uses `os.path.join()` for cross-platform paths
- Setup functions are callable as CLI subcommands: `python3 scripts/setup_helpers.py <subcommand> <args>`
- `setup.sh` uses `info()`, `warn()`, `error()` functions for colored output

### Integration Points
- `setup.sh` — Add new step after hook registration (line ~118) to call `python3 scripts/setup_helpers.py claude-md <project_dir>`
- `scripts/setup_helpers.py` — Add `generate_claude_md_section()` function + `claude-md` CLI subcommand
- `CLAUDE.md` in target project — Append/replace memory section between markers

</code_context>

<specifics>
## Specific Ideas

- The memory instructions should reference the actual `agent42_memory` tool actions by name (search, store, log) so Claude knows exactly what to call
- Marker comments should be HTML-style (`<!-- -->`) since CLAUDE.md is Markdown and HTML comments are invisible to renderers
- The section should be self-contained — a user who reads it should understand what it does without needing to read Agent42 docs

</specifics>

<deferred>
## Deferred Ideas

- Memory consolidation and dedup — Phase 4
- Full CLAUDE.md template generation (project scaffold, conventions, architecture) — future enhancement, separate workstream
- Bidirectional sync (Qdrant → CC flat files) — out of scope per REQUIREMENTS.md

</deferred>

---

*Phase: 03-claude-md-integration*
*Context gathered: 2026-03-18*
