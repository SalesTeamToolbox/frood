# Phase 1: Auto-Sync Hook - Context

**Gathered:** 2026-03-18
**Status:** Ready for planning

<domain>
## Phase Boundary

Install a PostToolUse hook that intercepts every Claude Code Write/Edit to memory files and automatically mirrors the content to Agent42's Qdrant store. The hook is invisible to the user during normal operation, handles failures silently, and produces no duplicate entries. A dashboard indicator shows sync status, and a manual reindex command handles catch-up after Qdrant downtime.

</domain>

<decisions>
## Implementation Decisions

### Memory Scope
- Sync only the current project's memory directory: `~/.claude/projects/{current-project}/memory/`
- Do NOT sync global memories or other projects' memories
- Sync ALL CC memory file types: user, feedback, project, reference (satisfies SYNC-02)
- Intercept both Write and Edit tool calls (new files + updates)

### Memory File Detection
- Path pattern match only: check if `file_path` matches `~/.claude/projects/*/memory/*.md`
- No frontmatter validation needed — CC always writes memories to this exact path
- Simple, reliable, no false positives

### Content Mapping
- Extract full YAML frontmatter: name, description, type, plus source_file path
- Store in Qdrant payload alongside the embedding for type-filtered search
- Single embedding per file — CC memory files are small (1-5 paragraphs), one file = one Qdrant point
- Store in Agent42's existing `{prefix}_memory` collection (not a separate collection)
- Tag with `source='claude_code'` in payload to distinguish from Agent42-native memories
- On update (Edit): upsert replaces the existing point (same file path → same deterministic UUID5 point ID → Qdrant upsert overwrites)

### Sync Visibility
- Silent by default — no stderr output on success
- Only emit stderr on failure (which CC shows as a notice)
- Dashboard indicator: last sync timestamp, total CC memories synced, Qdrant health status
- Displayed in the existing Storage section of the Agent42 dashboard
- Hook writes a small status file that dashboard reads (summary stats only, no full audit trail)

### Failure & Retry
- Silent drop when Qdrant is unreachable — memory still exists in CC's flat file (SYNC-04)
- No automatic queue or retry — keep it simple
- Manual catch-up via `agent42_memory reindex_cc` action: scans all CC memory files and syncs any missing to Qdrant
- Embedding generation failure (ONNX missing/corrupted): skip sync entirely, log warning to status file
- No API fallback for embeddings — ONNX only in hook context

### Performance
- Fire-and-forget async: hook spawns sync as background process and exits immediately (exit 0)
- Near-zero added latency to CC's Write/Edit operations
- CC never waits for Qdrant write to complete

### Claude's Discretion
- Hook module structure (single file vs package)
- Background process mechanism (subprocess, threading, or asyncio)
- Status file format and location
- Dashboard UI placement within Storage section
- `reindex_cc` implementation details (batch size, progress reporting)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Hook System
- `.claude/settings.json` — Hook registration format, event matchers, existing PostToolUse hooks
- `.claude/hooks/security-monitor.py` — PostToolUse Write|Edit hook pattern (path filtering, stderr output, exit codes)
- `.claude/hooks/format-on-write.py` — PostToolUse Write|Edit hook pattern (tool_input parsing)

### Memory Storage
- `memory/store.py` — MemoryStore class: `append_to_section()`, `update_memory()`, `_schedule_reindex()` fire-and-forget pattern
- `memory/embeddings.py` — EmbeddingStore: `add_entry()`, `index_memory()`, ONNX embedding generation, chunking strategy
- `memory/qdrant_store.py` — QdrantStore: `upsert_single()`, `_make_point_id()` (deterministic UUID5 dedup), `is_available` probe

### Tools
- `tools/memory_tool.py` — MemoryTool actions (store, recall, search) — `reindex_cc` action will be added here
- `mcp_server.py` — MCP server tool exposure, how `agent42_memory` is registered

### Dashboard
- `server.py` — FastAPI dashboard, Storage status endpoint pattern
- `static/` — Dashboard frontend files

### Configuration
- `core/config.py` — Settings class, `AGENT42_WORKSPACE` env var
- `.mcp.json` — Claude Code MCP server configuration

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `QdrantStore._make_point_id(text, source)` — Deterministic UUID5 for dedup. Use `source="claude_code"` + file path for stable IDs
- `QdrantStore.upsert_single()` — Single-entry write with payload
- `QdrantStore.is_available` — Cached connectivity probe (60s success TTL, 15s fail TTL)
- `EmbeddingStore.add_entry()` — Embeds text and stores to Qdrant + JSON fallback
- `MemoryStore._schedule_reindex()` — Fire-and-forget async pattern (asyncio task or sync fallback)
- PostToolUse hook pattern from `security-monitor.py` — JSON stdin parsing, tool_input extraction, stderr output, exit 0

### Established Patterns
- All Qdrant writes use deterministic point IDs (UUID5 from content hash) — automatic dedup on upsert
- ONNX local embeddings (all-MiniLM-L6-v2, 384 dims) — no API calls needed
- Graceful degradation: check `is_available` before operations, skip silently if unavailable
- Hooks receive JSON on stdin: `hook_event_name`, `tool_name`, `tool_input` (with `file_path`), `tool_output`, `project_dir`

### Integration Points
- `.claude/settings.json` PostToolUse array — register new hook with `Write|Edit` matcher
- `tools/memory_tool.py` — add `reindex_cc` action
- `server.py` Storage status endpoint — extend to include CC sync stats
- Dashboard Storage section — add sync indicator widget

</code_context>

<specifics>
## Specific Ideas

- The hook should be a standalone Python script in `.claude/hooks/` like existing hooks
- Point ID should incorporate file path (not just content) so the same content in different files gets separate entries
- The `reindex_cc` action should report how many files were found, how many were already synced, and how many were newly synced
- Status file could be a simple JSON in `.agent42/` directory alongside existing state files

</specifics>

<deferred>
## Deferred Ideas

- Intelligent learning extraction from conversation context — Phase 2
- CLAUDE.md instructions for memory preference — Phase 3
- Memory consolidation and dedup across both systems — Phase 4
- Bidirectional sync (Qdrant → CC flat files) — out of scope for this milestone
- Real-time memory streaming — out of scope per REQUIREMENTS.md

</deferred>

---

*Phase: 01-auto-sync-hook*
*Context gathered: 2026-03-18*
