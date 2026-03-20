# Phase 2: Intelligent Learning - Context

**Gathered:** 2026-03-18
**Status:** Ready for planning

<domain>
## Phase Boundary

At session end, the Stop hook extracts structured, categorized learnings from the Claude Code conversation and stores them in Qdrant with enough context to be useful on future recall. Learnings include architectural decisions, user corrections/feedback, deployment/debugging patterns, and category-aware tagging. Cross-session pattern detection boosts confidence on recurring learnings. Memory quality (dedup, consolidation) is Phase 4.

</domain>

<decisions>
## Implementation Decisions

### Extraction Approach
- LLM-based extraction using instructor + Pydantic structured output
- Route through Agent42's own API endpoint (localhost:8000) — lets Agent42's tiered routing pick the provider (Synthetic, Gemini, free tier, etc.)
- Hook stays provider-agnostic — never hardcodes a specific LLM provider
- If Agent42 API is unreachable (server not running), silently skip extraction entirely — learning is best-effort
- No fallback to direct API calls or heuristics — keep the hook simple

### Learning Types & Schema
- Extract all 5 types from requirements: decisions (LEARN-01), corrections/feedback (LEARN-02), deployment/debug patterns (LEARN-03), cross-session confidence (LEARN-04), category tagging (LEARN-05)
- One Qdrant point per learning — a session producing 3 learnings creates 3 separate points
- Each learning embeds independently for targeted semantic search
- Store in new dedicated Qdrant collection: `agent42_knowledge` (separate from user-written memories)

### Category Taxonomy
- Start with 4 categories from requirements: security, feature, refactor, deploy
- LLM can suggest additional categories if a learning doesn't fit the predefined list
- Open-ended but anchored — prevents force-fitting edge cases

### Cross-session Confidence
- Before storing, search `agent42_knowledge` for semantically similar entries (cosine similarity >= 0.85)
- If match found: boost existing point's confidence (+0.1 per reoccurrence, capped at 1.0) and skip storing the duplicate
- If no match: store as new point
- Initial confidence: LLM-assessed (0.5-1.0) based on how clearly the learning was expressed — definitive "we decided X" gets ~0.9, vague pattern gets ~0.5
- Gradual decay: learnings not recalled in 30+ days lose up to 15% confidence (matches existing Qdrant lifecycle scoring)

### Noise Filtering
- Minimum threshold: 2+ tool calls AND 1+ file modification — same as effectiveness-learn.py
- LLM decides final relevance: `outcome: trivial` is a valid extraction response — if returned, skip storage
- Send last 20 messages + tool usage summary (tools used, files modified) as extraction context
- For very long sessions (100+ tool calls): truncate to last 20 messages — recent context is most relevant, conclusions matter most
- No additional keyword pre-filtering — the tool/file threshold plus LLM relevance check is sufficient

### Claude's Discretion
- Pydantic model field definitions (exact field names, types, validation rules)
- Agent42 API endpoint path for LLM extraction requests
- Background worker mechanism (subprocess vs threading)
- Status file format and location
- Similarity threshold tuning (0.85 is a starting point, may adjust after testing)
- How to construct the extraction prompt from session messages
- Exact confidence boost/decay parameters

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Hook Patterns
- `.claude/hooks/effectiveness-learn.py` — Stop hook with instructor + Pydantic structured LLM extraction, provider fallback chain, trivial session guard
- `.claude/hooks/learning-engine.py` — Stop hook with heuristic pattern extraction, learned-patterns.json persistence
- `.claude/hooks/memory-learn.py` — Stop hook with HISTORY.md append, session summary extraction from last assistant message
- `.claude/hooks/cc-memory-sync.py` + `.claude/hooks/cc-memory-sync-worker.py` — Detached background worker pattern (non-blocking)

### Memory Infrastructure
- `memory/qdrant_store.py` — QdrantStore: collections, `upsert_vectors()`, `search_with_lifecycle()`, `strengthen_point()`, lifecycle scoring (confidence * recall_boost * decay)
- `memory/embeddings.py` — EmbeddingStore: ONNX local embeddings (all-MiniLM-L6-v2, 384 dims), `embed_text()`, `add_entry()`
- `memory/store.py` — MemoryStore: `log_event_semantic()`, `semantic_search()`, `strengthen_memory()`
- `memory/effectiveness.py` — EffectivenessTracker: SQLite tool success/failure tracking, `get_task_records()`

### Tools
- `tools/memory_tool.py` — MemoryTool actions (store, recall, search, strengthen, reindex_cc)

### Configuration
- `core/config.py` — Settings class, env vars
- `.claude/settings.json` — Hook registration format

### Requirements
- `.planning/workstreams/intelligent-memory-bridge/REQUIREMENTS.md` — LEARN-01 through LEARN-05 acceptance criteria

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `effectiveness-learn.py`: Complete Stop hook with instructor + Pydantic extraction — template for this phase
- `cc-memory-sync-worker.py`: Detached background worker with ONNX embedding + Qdrant upsert — reuse spawn pattern
- `QdrantStore.search_with_lifecycle()`: Lifecycle-aware search with confidence/recall/decay scoring — use for duplicate detection
- `QdrantStore.strengthen_point()`: Confidence boost on existing points — use for cross-session pattern reinforcement
- `QdrantStore.upsert_vectors()`: Batch upsert with payload — use for storing extracted learnings
- `EmbeddingStore.embed_text()`: ONNX local embedding generation — use in worker for vector creation

### Established Patterns
- Stop hooks receive JSON on stdin with `hook_event_name`, `tool_results`, `messages`
- Background workers are spawned as detached subprocesses (DETACHED_PROCESS on Windows, close_fds on Unix)
- All Qdrant writes use deterministic UUID5 point IDs for dedup
- Lifecycle metadata: confidence (0-1), recall_count, last_recalled, status (active/forgotten)
- Graceful degradation: check `is_available` before Qdrant operations, skip silently if unavailable

### Integration Points
- `.claude/settings.json` Stop event array — register new hook
- `memory/qdrant_store.py` — add `agent42_knowledge` collection constant and ensure-collection logic
- `tools/memory_tool.py` — potential `search_learned` action for explicit knowledge queries
- Agent42 API (`server.py`) — extraction LLM calls routed through Agent42's tiered routing

</code_context>

<specifics>
## Specific Ideas

- Route LLM calls through Agent42 API (localhost:8000) rather than direct provider API — keeps the hook provider-agnostic and leverages existing tiered routing (Synthetic + CC Subscription combo)
- The existing `effectiveness-learn.py` is the closest template — same Stop event, same instructor pattern, same Pydantic output
- Phase 1 decision: "No LLM calls in hooks" is superseded — the user explicitly chose LLM extraction for this phase, accepting the tradeoff since it runs in a background worker (no CC latency)

</specifics>

<deferred>
## Deferred Ideas

- Memory consolidation and dedup passes — Phase 4
- Bidirectional sync (Qdrant -> CC flat files) — out of scope for this milestone
- LLM-powered memory summarization for recall — out of scope per REQUIREMENTS.md
- Search/recall UI for learnings in dashboard — future enhancement

</deferred>

---

*Phase: 02-intelligent-learning*
*Context gathered: 2026-03-18*
