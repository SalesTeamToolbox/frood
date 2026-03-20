# Phase 4: Memory Quality - Context

**Gathered:** 2026-03-18
**Status:** Ready for planning

<domain>
## Phase Boundary

Keep the Agent42 Qdrant memory store accurate and navigable over time. Remove duplicate entries, rank search results by proven relevance (confidence + recall), and surface quality signals to Claude. Consolidation targets Qdrant only — MEMORY.md flat files are managed by Claude Code independently. Covers requirements QUAL-01 and QUAL-02.

</domain>

<decisions>
## Implementation Decisions

### Consolidation Trigger
- Dashboard button for manual trigger AND automatic trigger after 100+ new entries since last consolidation
- Auto-check runs on each `agent42_memory store` call — after the store completes, check entry count since last consolidation
- If threshold reached, spawn consolidation as background task (fire-and-forget, following Phase 1's cc-memory-sync-worker pattern)
- Track last consolidation timestamp and entry count in a status file
- Dashboard shows: last-run timestamp, entries scanned, duplicates removed

### Dedup Strategy
- Tiered approach: auto-remove at 0.95+ cosine similarity, flag 0.85-0.95 range for review
- When removing duplicates: keep the entry with the highest confidence score, delete the other
- Dedup only — no LLM-powered merging or clustering of related-but-different entries
- Consolidation output: dashboard stats AND log a semantic event in HISTORY.md (e.g., "consolidation: removed 12 duplicates from knowledge")

### Consolidation Scope
- Qdrant only — MEMORY.md flat files are NOT rewritten
- Claude Code's auto-memory system manages flat files independently; Qdrant is the enhanced store

### Search Result Scoring (QUAL-02)
- Combined relevance score: blend cosine similarity + confidence + recall_boost + decay into a single 0-1 score
- Formula follows Phase 2's lifecycle scoring: `relevance = cosine * confidence * recall_boost * decay`
- Raw fields (confidence, recall_count, last_recalled) available in metadata dict for dashboard/debugging
- Claude sees the combined relevance score as the primary ranking signal

### Claude's Discretion
- Which collections to scan during consolidation (both `memory` + `knowledge`, or prioritize where duplicates accumulate)
- Recall tracking approach: auto-increment on search result return vs only on explicit use
- Decay/removal policy: auto-archive below a threshold or decay-but-never-remove
- Exact dedup similarity thresholds (0.95 and 0.85 are starting points, may adjust)
- Dashboard widget layout for consolidation stats
- Status file format and location
- Consolidation batch size and concurrency

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Memory Infrastructure
- `memory/qdrant_store.py` — QdrantStore: `search()`, `upsert_vectors()`, `upsert_single()`, `_make_point_id()`, `collection_count()`, `clear_collection()`
- `memory/embeddings.py` — EmbeddingStore: `search()`, `embed_text()`, `_search_qdrant()`, lifecycle-unaware search currently
- `memory/store.py` — MemoryStore: `log_event_semantic()`, `semantic_search()`, `_schedule_reindex()` fire-and-forget pattern
- `memory/consolidation.py` — ConsolidationPipeline: existing conversation consolidation pattern (LLM-based summarization)

### Hooks & Workers
- `.claude/hooks/cc-memory-sync.py` + `.claude/hooks/cc-memory-sync-worker.py` — Background worker pattern (detached subprocess, ONNX embedding, Qdrant upsert)

### Tools
- `tools/memory_tool.py` — MemoryTool actions (store, recall, search, log) — `consolidate` action will be added here

### Dashboard
- `server.py` — FastAPI dashboard, Storage status endpoint
- `static/` — Dashboard frontend files

### Configuration
- `core/config.py` — Settings class, env vars

### Requirements
- `.planning/workstreams/intelligent-memory-bridge/REQUIREMENTS.md` — QUAL-01 and QUAL-02 acceptance criteria

### Prior Phase Context
- `.planning/workstreams/intelligent-memory-bridge/phases/01-auto-sync-hook/01-CONTEXT.md` — UUID5 dedup, sync architecture
- `.planning/workstreams/intelligent-memory-bridge/phases/02-intelligent-learning/02-CONTEXT.md` — Knowledge collection, confidence boosting, lifecycle metadata, 0.85 cosine threshold

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `QdrantStore.search()` — Returns `{text, source, section, score, metadata}` — needs confidence/recall fields added to results
- `QdrantStore._make_point_id()` — Deterministic UUID5 for content dedup on upsert (already handles exact duplicates)
- `QdrantStore.collection_count()` — Entry count for threshold checking
- `EmbeddingStore.embed_text()` — ONNX local embedding for computing similarity between entries
- `MemoryStore.log_event_semantic()` — Log consolidation events to HISTORY.md with semantic indexing
- `MemoryStore._schedule_reindex()` — Fire-and-forget async pattern for background tasks
- `ConsolidationPipeline` — Existing conversation consolidation (different purpose but similar async pattern)
- `cc-memory-sync-worker.py` — Detached background worker pattern (subprocess spawn, ONNX + Qdrant)

### Established Patterns
- All Qdrant writes use deterministic UUID5 point IDs — automatic exact-content dedup on upsert
- ONNX local embeddings (all-MiniLM-L6-v2, 384 dims) — no API calls for embedding
- Graceful degradation: check `is_available` before Qdrant operations, skip silently if unavailable
- Background workers are spawned as detached subprocesses (DETACHED_PROCESS on Windows, close_fds on Unix)
- Lifecycle metadata on knowledge entries: confidence (0-1), recall_count, last_recalled, status (active/forgotten)

### Integration Points
- `tools/memory_tool.py` — Add `consolidate` action for on-demand trigger
- `tools/memory_tool.py` — Modify `_handle_search` to return combined relevance score with confidence/recall
- `memory/qdrant_store.py` — Add `search_with_lifecycle()` or modify `search()` to include lifecycle scoring
- `server.py` — Add consolidation stats to Storage status endpoint + manual trigger endpoint
- Dashboard Storage section — Add consolidation stats widget and manual trigger button

</code_context>

<specifics>
## Specific Ideas

- The background consolidation worker should follow the same detached subprocess pattern as `cc-memory-sync-worker.py` — proven to work cross-platform
- Status file tracking (last_run, entries_since) could live alongside the cc-sync status file in `.agent42/`
- The 0.95/0.85 similarity thresholds should be configurable via env vars so they can be tuned without code changes
- When the dashboard shows "flagged for review" entries (0.85-0.95 range), provide a simple approve/dismiss UI

</specifics>

<deferred>
## Deferred Ideas

- LLM-powered cluster-and-merge of related-but-different entries — future enhancement if dedup alone isn't sufficient
- MEMORY.md flat file consolidation/rewrite — out of scope (CC manages its own flat files)
- Bidirectional sync (Qdrant → CC flat files) — out of scope per REQUIREMENTS.md
- Cross-project memory dedup — separate concern, handled by node_sync

</deferred>

---

*Phase: 04-memory-quality*
*Context gathered: 2026-03-18*
