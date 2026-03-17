# Phase 20: Task Metadata Foundation - Context

**Gathered:** 2026-03-17
**Status:** Ready for planning

<domain>
## Phase Boundary

Establish task_id and task_type payload fields in Qdrant memory entries, create a begin_task()/end_task() lifecycle protocol for task context propagation, add payload indexes for filtered queries, and extend existing search methods to support task-type-aware retrieval. No effectiveness tracking, learning extraction, or proactive injection (those are Phases 21-23).

</domain>

<decisions>
## Implementation Decisions

### Task type taxonomy
- Fixed enum (`TaskType`) matching existing IntentClassifier categories: coding, debugging, research, content, strategy, app_create, marketing, general
- Enum lives in `core/task_types.py` as a shared constant — importable by both memory layer and agent dispatch
- No free-form string types — all task_type values must be valid enum members

### Task lifecycle protocol
- Agent dispatch loop (e.g., `Agent._process_task()`) is responsible for calling `begin_task()` and `end_task()`
- Task context propagation via `contextvars.ContextVar` — memory writes auto-read current task_id/task_type without signature changes
- `begin_task()` auto-generates a UUID for task_id — callers never provide IDs manually
- `end_task()` is explicit — must be called when task completes (clears context var, provides clean boundary for Phase 21 effectiveness tracking)
- Lifecycle functions live in new `core/task_context.py` module alongside `TaskType` enum

### Backward compatibility
- Existing entries (no task_type/task_id fields) are **excluded** from filtered queries — a filter means a filter
- Existing entries remain fully queryable in **unfiltered** searches (no regression per TMETA-02)
- No migration or backfill — old entries age out naturally as new tagged entries accumulate
- Unfiltered searches treat tagged and untagged entries equally (rank by semantic similarity only)

### Search API
- Extend existing `EmbeddingStore.search()` and `QdrantStore.search()` with optional `task_type_filter` and `task_id_filter` parameters
- Follows existing pattern of `source_filter`/`channel_filter` — no new method needed
- `MemoryStore.build_context_semantic()` passes task_type through to filtered search (RETR-02)
- `search_with_lifecycle()` from RETR-01 is fulfilled by the extended `search()` signature

### Payload indexing
- Qdrant keyword index on `task_type` (string values, low cardinality ~8 values)
- Qdrant keyword index on `task_id` (UUID strings, high cardinality, exact-match lookups)
- Indexes created at collection creation time in `QdrantStore._ensure_collection()`
- Indexes applied to MEMORY and HISTORY collections only — CONVERSATIONS and KNOWLEDGE are unrelated to task scoping

### Claude's Discretion
- Exact ContextVar naming and helper function signatures
- How to handle edge case of memory write outside any task context (likely just omit task fields)
- Internal structure of `core/task_context.py` beyond the agreed public API
- Whether to add `_ensure_indexes()` as a separate method or inline in `_ensure_collection()`

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Memory layer
- `memory/qdrant_store.py` — Current Qdrant client: upsert_vectors (line 179), search (line 245), _ensure_collection (line 142). Payload merge pattern at line 209.
- `memory/embeddings.py` — EmbeddingStore: add_entry (line 236 area), search (line 274), index_history_entry (line 422). Qdrant delegation layer.
- `memory/store.py` — MemoryStore: build_context_semantic (line 264), log_event_semantic (line 230). Top-level API for memory operations.

### Tool interface
- `tools/memory_tool.py` — MemoryTool: store/recall/log/search actions. May need task context awareness.

### Classification
- `core/intent_classifier.py` — IntentClassifier with existing task type categories (coding, debugging, research, etc.). Source of truth for TaskType enum values.

### Requirements
- `.planning/workstreams/per-project-task-memories/REQUIREMENTS.md` — TMETA-01 through TMETA-04, RETR-01, RETR-02

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `QdrantStore.upsert_vectors()` already merges arbitrary payload dicts (`**payload` at line 209) — task fields flow through naturally
- `QdrantStore.search()` has `source_filter` and `channel_filter` pattern — `task_type_filter` follows identically
- `EmbeddingStore.add_entry()` accepts `metadata: dict` — task fields can be injected here via ContextVar
- `IntentClassifier` categories map directly to TaskType enum values

### Established Patterns
- All I/O is async — `contextvars.ContextVar` works natively with asyncio (auto-copies to child tasks)
- Payload indexes: Qdrant `_ensure_collection()` currently creates vectors-only; need to add `create_payload_index()` calls
- Filter construction: `QdrantStore.search()` builds a `must` filter list from source/channel — extend with task_type/task_id conditions

### Integration Points
- `Agent._process_task()` (or equivalent dispatch entry) — where `begin_task()`/`end_task()` calls go
- `EmbeddingStore.add_entry()` / `QdrantStore.upsert_vectors()` — where task fields get injected into payloads
- `MemoryStore.build_context_semantic()` — where `task_type_filter` gets passed through to search

</code_context>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 20-task-metadata-foundation*
*Context gathered: 2026-03-17*
