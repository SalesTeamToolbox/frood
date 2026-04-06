# Phase 25: Memory Bridge - Context

**Gathered:** 2026-03-29
**Status:** Ready for planning

<domain>
## Phase Boundary

Agent42 memory is injectable before and extractable after every Paperclip agent execution, with agent-level and company-level scope isolation. MemoryBridge.recall() returns relevant memories before execution (200ms hard timeout). MemoryBridge.learn_async() extracts learnings from agent transcripts in the background after execution. Sidecar exposes POST /memory/recall and POST /memory/store endpoints for plugin access. Two agents with different agent_ids do not see each other's memories.

</domain>

<decisions>
## Implementation Decisions

### Recall Integration
- **D-01:** Recall is pre-injected inside `SidecarOrchestrator.execute_async()` — orchestrator owns all memory ops, not the route layer or Paperclip caller
- **D-02:** `asyncio.wait_for(recall(...), timeout=0.2)` enforces the 200ms hard timeout (MEM-02) with empty-list fallback — never blocks execution
- **D-03:** `self.memory_store` is already injected into the orchestrator from Phase 24 — recall uses existing `semantic_search()` with scope filters
- **D-04:** Recalled memories are threaded into the agent prompt when AgentRuntime is wired in later phases — for now stored as part of the execution context

### Learning Extraction
- **D-05:** `asyncio.create_task(learn_async(...))` fires after `_post_callback()` inside `execute_async()` — fire-and-forget, callback never delayed (MEM-03)
- **D-06:** Matches existing `_maybe_promote_quarantined` fire-and-forget pattern in server.py
- **D-07:** Extract from result summary only (`result["summary"]`) — sufficient for Phase 25 MVP; upgrade to full agent transcript when AgentRuntime is wired without structural change to trigger point
- **D-08:** Reuse existing instructor+Pydantic extraction pipeline and quarantine/promotion system from Phase 20-21 — no new extraction infrastructure

### Scope Partitioning
- **D-09:** Single Qdrant collection with `agent_id` + `company_id` payload fields and `is_tenant=True` index (Qdrant 1.9+ optimized path) — co-locates vectors per tenant in HNSW storage
- **D-10:** `agent_id` is a **required** parameter on `MemoryBridge.recall()` — raises if omitted, never defaults to unfiltered search (prevents cross-agent memory leaks)
- **D-11:** Extends existing `_ensure_task_indexes` pattern in QdrantStore — add KEYWORD indexes for `agent_id` and `company_id` alongside existing `project_filter` and `task_type_filter`
- **D-12:** Forward-compatible with SCALE-01 (deferred multi-company partitioning) — `is_tenant` enables future per-company shard promotion without schema migration

### HTTP API Design
- **D-13:** `POST /memory/recall` returns structured objects: `list[{text, score, source, metadata}]` — consistent with internal `QdrantStore.search()` return shape, enables client-side score threshold filtering
- **D-14:** `POST /memory/store` accepts pre-extracted learnings: `{text, section, tags, agent_id, company_id}` — plugin controls what gets stored, no server-side NLP extraction needed
- **D-15:** Both endpoints use same `Depends(get_current_user)` Bearer auth as `/sidecar/execute` — one credential, scope enforcement via `agent_id` + `company_id` in request body
- **D-16:** Pydantic request/response models go in `core/sidecar_models.py`, routes in `dashboard/sidecar.py` — following established Phase 24 file split

### Claude's Discretion
- Exact Pydantic field names for MemoryRecallRequest/Response and MemoryStoreRequest/Response
- Top-K default value for recall (5 is reasonable, configurable via request param)
- Score threshold default for recall filtering
- Exact metadata fields included in recall response (timestamp, section, tags at minimum)
- Whether learn_async logs extraction failures to structured JSON log or silently drops

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase requirements
- `.planning/REQUIREMENTS.md` -- MEM-01 through MEM-05 define all Memory Bridge requirements
- `.planning/ROADMAP.md` -- Phase 25 success criteria (4 acceptance tests)

### Architecture research
- `.planning/research/ARCHITECTURE.md` -- Full system diagram, component responsibilities, data flow sequences
- `.planning/research/FEATURES.md` -- Feature dependency graph, interface contracts, MemoryBridge interface shape
- `.planning/research/PITFALLS.md` -- Critical pitfalls (P3: Qdrant timeout handling, P7: fire-and-forget error swallowing)

### Prior phase context
- `.planning/phases/24-sidecar-mode/24-CONTEXT.md` -- Sidecar architecture decisions (D-01 through D-10), reusable assets, integration points

### Existing codebase (key files to read)
- `core/sidecar_orchestrator.py` -- SidecarOrchestrator.execute_async() stub where recall and learn hook in
- `dashboard/sidecar.py` -- create_sidecar_app() factory where /memory/* routes are added
- `core/sidecar_models.py` -- Pydantic models for sidecar endpoints (add MemoryRecall/Store models here)
- `memory/store.py` -- MemoryStore with semantic_search(), Qdrant integration, workspace-scoped storage
- `memory/embeddings.py` -- EmbeddingStore with ONNX local embeddings (384 dims), Qdrant vector upsert/search
- `memory/search_service.py` -- Standalone search service pattern (reference for recall timeout handling)
- `core/effectiveness.py` -- EffectivenessStore fire-and-forget pattern to follow for learn_async
- `dashboard/server.py` -- `_maybe_promote_quarantined` pattern (line ~3924) as reference for fire-and-forget learning

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `memory/store.py:MemoryStore` — `semantic_search()` with project/task_type filters — MemoryBridge.recall() wraps this
- `memory/embeddings.py:EmbeddingStore` — ONNX local embeddings (384 dims) + Qdrant upsert/search — handles vector operations
- `core/sidecar_orchestrator.py:SidecarOrchestrator` — Already receives `memory_store` in constructor, has the stub where recall/learn hook in
- `dashboard/auth.py:get_current_user` — JWT Bearer auth dependency to reuse for /memory/* endpoints
- `core/sidecar_models.py` — Pydantic models for AdapterExecutionContext, CallbackPayload — extend with memory models
- Existing instructor+Pydantic learning extraction pipeline from Phase 20-21 — reuse for learn_async

### Established Patterns
- **Fire-and-forget:** `asyncio.create_task()` used in EffectivenessStore and `_maybe_promote_quarantined` — learn_async follows same pattern
- **Payload filtering:** QdrantStore uses `FieldCondition` with `project_filter`, `task_type_filter`, `source_filter` — extend with `agent_id` + `company_id`
- **Timeout with fallback:** `asyncio.wait_for()` pattern — apply to recall's 200ms budget
- **Sidecar file split:** Models in `core/sidecar_models.py`, routes in `dashboard/sidecar.py`, logic in `core/sidecar_orchestrator.py`

### Integration Points
- `SidecarOrchestrator.execute_async()` — Insert recall before agent execution, learn_async after `_post_callback()`
- `dashboard/sidecar.py:create_sidecar_app()` — Add `/memory/recall` and `/memory/store` routes
- `core/sidecar_models.py` — Add MemoryRecallRequest, MemoryRecallResponse, MemoryStoreRequest, MemoryStoreResponse
- `QdrantStore._ensure_task_indexes()` — Add `agent_id` and `company_id` KEYWORD indexes with `is_tenant=True`
- `EmbeddingStore.upsert_single()` / `upsert_vectors()` — Include `agent_id` + `company_id` in point payloads

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

*Phase: 25-memory-bridge*
*Context gathered: 2026-03-29*
