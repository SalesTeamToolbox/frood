# Phase 4: Memory Quality - Context

**Gathered:** 2026-03-18
**Status:** Ready for planning

<domain>
## Phase Boundary

Keep the Agent42 Qdrant memory store accurate and navigable over time. Consolidation removes duplicates and merges related entries across both `memory` and `knowledge` collections. Confidence scoring ranks search results by proven relevance. MEMORY.md is regenerated from Qdrant truth after consolidation. New memory types, new extraction patterns, and cross-machine sync are out of scope.

</domain>

<decisions>
## Implementation Decisions

### Consolidation Trigger
- Session-end hook fires consolidation every 10th Stop event (counter in status file)
- Also available as manual `agent42_memory consolidate` tool action
- Hook auto-applies; manual action defaults to dry-run (shows merge candidates + counts), requires `confirm=true` to apply
- Counter reset after each consolidation pass

### Consolidation Scope
- Consolidates both `memory` collection (CC-synced flat files) and `knowledge` collection (Phase 2 extracted learnings)
- Different merge strategies may apply per collection type (Claude's discretion)

### Merge Strategy
- Identify merge candidates via cosine similarity >= 0.90 between entry embeddings
- Higher threshold than Phase 2's 0.85 dedup check — prevents over-merging distinct-but-related entries
- Cluster similar entries into groups, then merge each group
- **Merge result:** Keep the highest-confidence entry's text. Absorb metadata from others: sum recall counts, take max confidence, preserve all source tags. Delete absorbed entries from Qdrant
- No LLM calls for merge decisions — pure embedding similarity

### Audit & Safety
- Lightweight consolidation log (append-only): date, entries_scanned, merged_count, removed_count per run
- Same pattern as Phase 1 sync status file — stored in `.agent42/` directory
- No full entry content in audit log

### Confidence & Lifecycle Metadata
- Every Qdrant point payload includes: `confidence` (float 0-1), `recall_count` (int), `last_recalled` (ISO timestamp), `created_at` (ISO timestamp), `status` (active/forgotten)
- Initial confidence: 0.5-1.0 (set by Phase 2 LLM extraction for knowledge entries, default 0.7 for CC-synced memory entries)
- Boost: +0.1 per reoccurrence, capped at 1.0 (from Phase 2)
- Decay: entries not recalled in 30+ days lose up to 15% confidence (from Phase 2)

### Search Ranking
- Final score = cosine_similarity * 0.7 + confidence * 0.3
- Recall count used as tiebreaker when final scores are equal
- Confidence and recall_count included in search result response so Claude can reference them

### Recall Tracking
- Every time `agent42_memory search` returns an entry, auto-increment its `recall_count` and update `last_recalled`
- Adds a small async write per search — fire-and-forget pattern (same as Phase 1 sync)

### Pruning
- Entries below confidence 0.2 after decay are soft-deleted: `status: forgotten`
- Forgotten entries stop appearing in search results (filtered out)
- Entries that have been `forgotten` for 60+ days are hard-deleted during consolidation pass
- Soft-delete is reversible — a manual strengthen action can restore an entry before the 60-day window

### MEMORY.md Sync-back
- After consolidation, regenerate Agent42 workspace MEMORY.md from surviving Qdrant entries
- **Format:** Grouped by CC memory type (User, Feedback, Project, Reference) with original name/description preserved. Confidence scores shown as inline metadata
- **Scope:** Only rewrite Agent42's workspace MEMORY.md — CC's auto-memory index in `~/.claude/projects/*/memory/` is untouched (Phase 1 hook re-syncs CC changes back to Qdrant)
- Automatic during consolidation — no separate opt-in step

### Claude's Discretion
- Hook module structure (extend existing Stop hook vs new hook file)
- Background worker mechanism for consolidation pass
- Exact decay calculation formula (linear vs exponential)
- Batch size for pairwise similarity comparisons
- Status file format and location within `.agent42/`
- QdrantStore method names and signatures for lifecycle operations
- How to handle entries without lifecycle metadata (migration from pre-Phase 4)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Memory Infrastructure
- `memory/qdrant_store.py` — QdrantStore: `upsert_vectors()`, `upsert_single()`, `search()`, `_make_point_id()` (deterministic UUID5), `_ensure_collection()`. **No lifecycle methods exist yet — this phase adds them**
- `memory/embeddings.py` — EmbeddingStore: `embed_text()`, `search()`, `_search_qdrant()`, `add_entry()`. ONNX local embeddings (384 dims)
- `memory/store.py` — MemoryStore: `read_memory()`, `update_memory()`, `reindex_memory()`, `semantic_search()`
- `memory/consolidation.py` — ConsolidationPipeline: conversation summarization (NOT memory consolidation — different purpose, but reusable patterns)

### Hook Patterns
- `.claude/hooks/cc-memory-sync.py` + `.claude/hooks/cc-memory-sync-worker.py` — Phase 1 PostToolUse hook + detached background worker pattern
- `.claude/hooks/effectiveness-learn.py` — Stop hook with session threshold guard (2+ tool calls, 1+ file mods)
- `.claude/hooks/learning-engine.py` — Stop hook with heuristic extraction

### Tools
- `tools/memory_tool.py` — MemoryTool actions: store, recall, search, log, reindex_cc. **New `consolidate` action will be added here**

### Configuration
- `core/config.py` — Settings class, env vars
- `.claude/settings.json` — Hook registration format

### Requirements
- `.planning/workstreams/intelligent-memory-bridge/REQUIREMENTS.md` — QUAL-01 (consolidation), QUAL-02 (confidence scoring)

### Prior Phase Context
- `.planning/workstreams/intelligent-memory-bridge/phases/01-auto-sync-hook/01-CONTEXT.md` — UUID5 dedup, sync status file pattern, fire-and-forget async
- `.planning/workstreams/intelligent-memory-bridge/phases/02-intelligent-learning/02-CONTEXT.md` — `agent42_knowledge` collection, 0.85 similarity threshold, confidence model (0.5-1.0, +0.1 boost, 30-day decay)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `QdrantStore._make_point_id(text, source)` — Deterministic UUID5 for dedup
- `QdrantStore.search()` — Cosine similarity search with source/channel filters — extend for lifecycle-aware ranking
- `QdrantStore.upsert_single()` / `upsert_vectors()` — Point writes with payload — extend payloads with lifecycle fields
- `QdrantStore.collection_count()` — Entry counting for consolidation stats
- `EmbeddingStore.embed_text()` — ONNX local embedding for pairwise similarity
- `EmbeddingStore._cosine_similarity()` — Pure-Python cosine similarity function
- `ConsolidationPipeline` patterns — LLM summarization + Qdrant storage (reusable architecture, different purpose)
- `MemoryStore.update_memory()` — Overwrites MEMORY.md content (use for sync-back)
- Phase 1 sync status file pattern — lightweight JSON in `.agent42/`

### Established Patterns
- All Qdrant writes use deterministic UUID5 point IDs
- ONNX local embeddings (all-MiniLM-L6-v2, 384 dims) — no API calls
- Graceful degradation: check `is_available` before operations
- Hooks receive JSON on stdin, spawn detached background workers
- Fire-and-forget async for non-blocking writes

### Integration Points
- `memory/qdrant_store.py` — Add lifecycle methods: `strengthen_point()`, `search_with_lifecycle()`, `soft_delete()`, `prune_forgotten()`
- `tools/memory_tool.py` — Add `consolidate` action (dry-run + apply modes)
- `memory/store.py` — Extend `update_memory()` or add `regenerate_from_qdrant()` for sync-back
- `.claude/settings.json` Stop event — Register consolidation hook (or extend existing Stop hook)
- `.agent42/` directory — Consolidation status file and session counter

</code_context>

<specifics>
## Specific Ideas

- The 0.90 merge threshold is deliberately higher than Phase 2's 0.85 dedup threshold — merging requires stronger similarity than "probably the same thing"
- Consolidation should be non-blocking like Phase 1's sync — spawn a background worker so the Stop hook exits immediately
- Migration path: existing Qdrant entries without lifecycle metadata should get default values (confidence=0.7, recall_count=0, status=active) on first access
- The dry-run output for manual consolidation should be concise enough for Claude to read and relay to the user: "Found 12 merge groups across 47 entries. 8 entries would be absorbed. 3 forgotten entries eligible for hard-delete."

</specifics>

<deferred>
## Deferred Ideas

- Bidirectional sync (Qdrant → CC flat files in ~/.claude/) — out of scope per REQUIREMENTS.md
- LLM-powered memory summarization for merge — decided against for this phase (pure embedding similarity)
- Search/recall UI for learnings in dashboard — future enhancement
- Cross-machine memory sync — handled by existing node_sync tool, not this workstream
- Memory tagging/categorization UI — future enhancement

</deferred>

---

*Phase: 04-sambanova-integration*
*Context gathered: 2026-03-18*
