# Phase 1: Memory Pipeline - Context

**Gathered:** 2026-03-20
**Status:** Ready for planning

<domain>
## Phase Boundary

Fix recall and learn hooks so memory operations produce visible, actionable feedback in VS Code Claude Code chat stream. Both hooks exist and are registered but the end-to-end pipeline has silent failures and suboptimal output formatting. This phase debugs, fixes, and polishes the pipeline — not creating new memory capabilities.

</domain>

<decisions>
## Implementation Decisions

### Recall display format
- Compact one-liner format: `[agent42-memory] Recall: N memories surfaced via {method}`
- Each memory on its own indented line: `  - [85%] [Memory: Section] text...`
- Silent when no matches found — no "no matches" message
- Skip prompts < 15 chars and slash commands (current behavior, keep as-is)
- Max 3 memories per recall (reduced from current 5)
- Max output ~2000 chars (~500 tokens)
- Source tag shows search method used (semantic, keyword, qdrant, history)

### Learn confirmations
- Summary of what was captured: files modified, tools used, keywords — plus storage destination
- Format: `[agent42-memory] Learn: captured to {destination} — {summary}`
- knowledge-learn (LLM extractor) stays silent — runs async in background, results in server logs only
- Skip trivial sessions: no files modified AND < 3 tool calls, or session < 30 seconds, or stop_reason is 'interrupted'
- Basic dedup: check last 10 HISTORY.md entries for > 80% keyword overlap, skip if duplicate

### Failure visibility
- Degrade silently to keyword fallback — user sees nothing different when Qdrant/search service is down
- Recall still works via MEMORY.md/HISTORY.md keyword search when backends fail
- Learn still works via HISTORY.md file append when Qdrant indexing fails
- All failures logged server-side at WARN level
- Source tag in recall output implicitly shows degradation (user sees "via keyword" instead of "via semantic")

### Server-side logging
- Use Agent42's existing logging setup with `memory.recall` and `memory.learn` logger names
- Log operations + errors: recall queries (keyword count, result count, method, latency), learn captures (what stored, where)
- No payload content in logs — just metadata (keyword count, char count, etc.)
- Server logs its own API calls (when /api/memory/search or /index is called), not hooks POSTing to a log endpoint
- Memory pipeline status added to `--health` flag: Qdrant connection, search service, MEMORY.md, HISTORY.md, hook registration
- `--health` includes last 24h stats: recall query count, learn capture count, average latency, error count

### Claude's Discretion
- Exact dedup algorithm for HISTORY.md entries (keyword overlap threshold, comparison window)
- Internal implementation of latency tracking for --health stats
- How to count 24h stats (in-memory counter vs parsing logs)
- Trivial session detection edge cases

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Memory hooks
- `.claude/hooks/memory-recall.py` — Current recall hook implementation (UserPromptSubmit, layered search)
- `.claude/hooks/memory-learn.py` — Current learn hook implementation (Stop, HISTORY.md + Qdrant)
- `.claude/hooks/knowledge-learn.py` — LLM-based knowledge extraction (Stop, background worker)
- `.claude/hooks/knowledge-learn-worker.py` — Background worker for knowledge extraction

### Hook configuration
- `.claude/settings.json` — Hook registration (UserPromptSubmit, Stop events)

### Memory storage
- `.agent42/memory/MEMORY.md` — Persistent memory sections (175 lines)
- `.agent42/memory/HISTORY.md` — Session history entries (380 entries)
- `.agent42/memory/embeddings.json` — Cached embeddings (295KB)

### Server infrastructure
- `mcp_server.py` — MCP server with --health flag (add memory pipeline status here)
- `memory/store.py` — MemoryStore with Qdrant integration
- `core/config.py` — Settings dataclass (AGENT42_SEARCH_URL, QDRANT_URL)

### Requirements
- `.planning/workstreams/agent42-ux-and-workflow-automation/REQUIREMENTS.md` — MEM-01 through MEM-04

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `memory-recall.py`: Fully implemented layered search (semantic → Agent42 API → Qdrant direct → MEMORY.md → HISTORY.md). Needs output format tuning and limit adjustment.
- `memory-learn.py`: Fully implemented session capture (extract summary → HISTORY.md → Qdrant index). Needs trivial-session skip and dedup logic.
- `knowledge-learn.py`: Background worker pattern for async LLM extraction. Already runs silently — no changes needed for visibility.
- `mcp_server.py --health`: Existing health check infrastructure to extend with memory pipeline status.

### Established Patterns
- Hook protocol: JSON on stdin, stderr for Claude context, exit 0 to allow
- Graceful degradation: All hooks use try/except with silent fallthrough
- Search service at `http://127.0.0.1:6380` for semantic search (separate from Agent42 API)
- Agent42 API at `http://127.0.0.1:8000` for memory search fallback

### Integration Points
- `settings.json` UserPromptSubmit → `memory-recall.py` (already wired)
- `settings.json` Stop → `memory-learn.py` (already wired)
- `mcp_server.py --health` → new memory pipeline status section
- Agent42 server logging → `memory.recall` and `memory.learn` logger names
- Server API endpoints `/api/memory/search` and `/index` → add structured logging

</code_context>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches. The core ask is making the existing pipeline work end-to-end and produce clean, visible output.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 01-memory-pipeline*
*Context gathered: 2026-03-20*
