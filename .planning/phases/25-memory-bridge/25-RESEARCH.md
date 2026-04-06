# Phase 25: Memory Bridge - Research

**Researched:** 2026-03-29
**Domain:** Async memory injection/extraction for Paperclip agent execution (Python/asyncio, Qdrant, ONNX)
**Confidence:** HIGH — all decisions verified against live codebase; no third-party API speculation needed

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Recall Integration**
- D-01: Recall is pre-injected inside `SidecarOrchestrator.execute_async()` — orchestrator owns all memory ops, not the route layer or Paperclip caller
- D-02: `asyncio.wait_for(recall(...), timeout=0.2)` enforces the 200ms hard timeout (MEM-02) with empty-list fallback — never blocks execution
- D-03: `self.memory_store` is already injected into the orchestrator from Phase 24 — recall uses existing `semantic_search()` with scope filters
- D-04: Recalled memories are threaded into the agent prompt when AgentRuntime is wired in later phases — for now stored as part of the execution context

**Learning Extraction**
- D-05: `asyncio.create_task(learn_async(...))` fires after `_post_callback()` inside `execute_async()` — fire-and-forget, callback never delayed (MEM-03)
- D-06: Matches existing `_maybe_promote_quarantined` fire-and-forget pattern in server.py
- D-07: Extract from result summary only (`result["summary"]`) — sufficient for Phase 25 MVP; upgrade to full agent transcript when AgentRuntime is wired without structural change to trigger point
- D-08: Reuse existing instructor+Pydantic extraction pipeline and quarantine/promotion system from Phase 20-21 — no new extraction infrastructure

**Scope Partitioning**
- D-09: Single Qdrant collection with `agent_id` + `company_id` payload fields and `is_tenant=True` index (Qdrant 1.9+ optimized path) — co-locates vectors per tenant in HNSW storage
- D-10: `agent_id` is a **required** parameter on `MemoryBridge.recall()` — raises if omitted, never defaults to unfiltered search (prevents cross-agent memory leaks)
- D-11: Extends existing `_ensure_task_indexes` pattern in QdrantStore — add KEYWORD indexes for `agent_id` and `company_id` alongside existing `project_filter` and `task_type_filter`
- D-12: Forward-compatible with SCALE-01 (deferred multi-company partitioning) — `is_tenant` enables future per-company shard promotion without schema migration

**HTTP API Design**
- D-13: `POST /memory/recall` returns structured objects: `list[{text, score, source, metadata}]` — consistent with internal `QdrantStore.search()` return shape, enables client-side score threshold filtering
- D-14: `POST /memory/store` accepts pre-extracted learnings: `{text, section, tags, agent_id, company_id}` — plugin controls what gets stored, no server-side NLP extraction needed
- D-15: Both endpoints use same `Depends(get_current_user)` Bearer auth as `/sidecar/execute` — one credential, scope enforcement via `agent_id` + `company_id` in request body
- D-16: Pydantic request/response models go in `core/sidecar_models.py`, routes in `dashboard/sidecar.py` — following established Phase 24 file split

### Claude's Discretion
- Exact Pydantic field names for MemoryRecallRequest/Response and MemoryStoreRequest/Response
- Top-K default value for recall (5 is reasonable, configurable via request param)
- Score threshold default for recall filtering
- Exact metadata fields included in recall response (timestamp, section, tags at minimum)
- Whether learn_async logs extraction failures to structured JSON log or silently drops

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope.

</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| MEM-01 | MemoryBridge.recall() retrieves top-K relevant memories for an agent+task before execution starts | QdrantStore.search() + semantic_search() fully support this; agent_id FieldCondition filter needed |
| MEM-02 | Memory recall has 200ms hard timeout — returns empty list on timeout, never blocks execution | asyncio.wait_for() with TimeoutError catch; verified pattern works with async QdrantStore calls |
| MEM-03 | MemoryBridge.learn_async() extracts learnings from agent transcripts via fire-and-forget after execution | asyncio.create_task() pattern confirmed in _maybe_promote_quarantined; instructor pipeline already in codebase but requires install |
| MEM-04 | Sidecar exposes POST /memory/recall and POST /memory/store endpoints for plugin access | create_sidecar_app() factory in dashboard/sidecar.py; pattern mirrors existing /sidecar/execute route |
| MEM-05 | Memory scope supports agent-level and company-level isolation (agent_id vs company_id partitioning) | QdrantStore._ensure_task_indexes() pattern; add KEYWORD indexes via create_payload_index() |

</phase_requirements>

---

## Summary

Phase 25 wires Agent42's existing memory system into the Paperclip sidecar execution loop. The codebase already has all the building blocks: `QdrantStore.search()` with payload filtering, `asyncio.create_task()` fire-and-forget for learning extraction, an `instructor`+Pydantic pipeline for structured extraction, and a `create_sidecar_app()` factory where new routes are added. The gap is a thin `MemoryBridge` class that combines these with scope partitioning by `agent_id`/`company_id`, two new Pydantic models and two new HTTP routes, and KEYWORD indexes for the new payload fields.

The only non-trivial risk is that `instructor` is listed in `requirements.txt` but is NOT installed in the current virtualenv (confirmed via `ModuleNotFoundError`). The `learn_async` path must guard with `try/except ImportError` — which the existing `_sync_extract()` in server.py already does. The `recall()` path has no such dependency risk since it uses only `QdrantStore.search()`.

The `asyncio.wait_for(recall(...), timeout=0.2)` pattern is critical: Qdrant embedded mode is sync, meaning recall must run in `asyncio.to_thread()` if using the embedded client, or the coroutine wrapping must handle the sync/async impedance mismatch. The existing `search_with_lifecycle()` call in `MemoryStore.semantic_search()` is already async-wrapped correctly and can be reused directly.

**Primary recommendation:** Implement `MemoryBridge` as a standalone class in `core/memory_bridge.py` (not a method of `SidecarOrchestrator`), injected into the orchestrator at construction time. This keeps concerns separated and makes the bridge independently testable.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| qdrant-client | installed (verified) | Qdrant vector search + payload filtering | Already powering all memory ops in Agent42 |
| onnxruntime | installed (verified) | ONNX embeddings (384 dims, ~23 MB RAM) | Established in project, no API key needed |
| asyncio (stdlib) | Python 3.11+ | wait_for timeout, create_task fire-and-forget | Decision D-02 and D-05 explicitly require it |
| pydantic v2 | installed | Request/response models for /memory/* routes | Used across all sidecar models |
| fastapi | installed | New routes in create_sidecar_app() | Same factory as Phase 24 |
| httpx | installed | Outbound HTTP (already used for callbacks) | Established in SidecarOrchestrator |
| instructor | requirements.txt but NOT installed | Structured learning extraction (learn_async) | Required for D-08 — MUST guard with try/except ImportError |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| openai (sync) | installed | instructor backend for learning extraction | Only if OPENROUTER_API_KEY or OPENAI_API_KEY set |
| asyncio.to_thread | stdlib | Wrap sync QdrantStore calls in async context | Needed if using embedded Qdrant (sync client) |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| asyncio.wait_for for timeout | anyio timeout | asyncio.wait_for is stdlib, zero deps — correct choice |
| Single Qdrant collection with payload filter | Separate collection per agent | Payload filter on indexed KEYWORD field is O(1) in Qdrant; separate collections would multiply collection management overhead |
| asyncio.create_task for learn_async | BackgroundTasks (FastAPI) | create_task is cleaner inside the orchestrator (not route-coupled); BackgroundTasks is route-lifecycle-bound |

**Installation (instructor — missing from venv):**
```bash
pip install instructor>=1.3.0
```
Note: learn_async must still guard `import instructor` with try/except — graceful degradation is required by project rules.

---

## Architecture Patterns

### Recommended Project Structure

```
core/
├── memory_bridge.py         # NEW: MemoryBridge class (recall + learn_async)
├── sidecar_models.py        # EXTEND: Add MemoryRecallRequest/Response, MemoryStoreRequest/Response
├── sidecar_orchestrator.py  # EXTEND: inject MemoryBridge, call recall + create_task(learn_async)
dashboard/
├── sidecar.py               # EXTEND: Add POST /memory/recall and POST /memory/store routes
memory/
├── qdrant_store.py          # EXTEND: _ensure_task_indexes adds agent_id + company_id KEYWORD indexes
tests/
├── test_memory_bridge.py    # NEW: unit tests for MEM-01 through MEM-05
```

### Pattern 1: MemoryBridge Class Structure

**What:** Thin wrapper around `MemoryStore.semantic_search()` that adds agent_id/company_id scope filtering and exposes recall/learn_async as first-class methods.

**When to use:** Called from `SidecarOrchestrator.execute_async()` only — not directly from routes.

```python
# core/memory_bridge.py
import asyncio
import logging
from typing import Any

logger = logging.getLogger("agent42.sidecar.memory")

class MemoryBridge:
    """Memory injection and extraction for sidecar execution.

    recall() — pre-execution: fetch relevant memories with 200ms timeout
    learn_async() — post-execution: extract learnings fire-and-forget
    """

    def __init__(self, memory_store: Any = None):
        self.memory_store = memory_store

    async def recall(
        self,
        query: str,
        agent_id: str,
        company_id: str = "",
        top_k: int = 5,
        score_threshold: float = 0.25,
    ) -> list[dict]:
        """Retrieve relevant memories for an agent+task. Requires agent_id.

        Returns empty list if memory_store unavailable or timeout exceeded.
        Never raises — caller always gets a list back.
        """
        if not agent_id:
            raise ValueError("agent_id is required for recall() — never search unfiltered")
        if not self.memory_store:
            return []
        # ... semantic_search with agent_id filter ...

    async def learn_async(
        self,
        summary: str,
        agent_id: str,
        company_id: str = "",
        task_type: str = "",
    ) -> None:
        """Extract and store learnings from execution summary. Fire-and-forget."""
        # ... instructor extraction + upsert ...
```

### Pattern 2: Timeout Enforcement in execute_async

**What:** `asyncio.wait_for()` wraps the entire recall coroutine with a 0.2-second budget.

**When to use:** Any memory operation in the hot path of execution.

```python
# core/sidecar_orchestrator.py — inside execute_async()
import asyncio

# Step 1: Memory recall with hard timeout (MEM-01, MEM-02)
recalled_memories: list[dict] = []
if self.memory_bridge and ctx.agent_id:
    try:
        recalled_memories = await asyncio.wait_for(
            self.memory_bridge.recall(
                query=ctx.context.get("taskDescription", ""),
                agent_id=ctx.agent_id,
                company_id=ctx.company_id,
                top_k=5,
            ),
            timeout=0.2,  # 200ms hard limit (MEM-02)
        )
        logger.info(
            "Recalled %d memories for agent %s",
            len(recalled_memories),
            ctx.agent_id,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "Memory recall timed out for run %s — proceeding without memories",
            run_id,
        )

# ... agent execution ...

result = { "summary": f"Executed task for agent {ctx.agent_id}", ... }

# Step 2: Callback (never delayed)
await self._post_callback(run_id, status, result, usage, error)

# Step 3: Learn fire-and-forget (MEM-03)
if self.memory_bridge and ctx.agent_id:
    asyncio.create_task(
        self.memory_bridge.learn_async(
            summary=result.get("summary", ""),
            agent_id=ctx.agent_id,
            company_id=ctx.company_id,
        )
    )
```

### Pattern 3: QdrantStore Index Extension

**What:** Extend `_ensure_task_indexes()` to add KEYWORD indexes for `agent_id` and `company_id`.

**When to use:** Called during collection initialization — idempotent, safe to run on existing collections.

```python
# memory/qdrant_store.py — extend _ensure_task_indexes()
def _ensure_task_indexes(self, collection_name: str):
    """Create payload indexes for task_type, task_id, agent_id, company_id (idempotent)."""
    from qdrant_client.models import PayloadSchemaType

    indexes = [
        ("task_type", PayloadSchemaType.KEYWORD),
        ("task_id", PayloadSchemaType.KEYWORD),
        ("agent_id", PayloadSchemaType.KEYWORD),    # NEW — MEM-05
        ("company_id", PayloadSchemaType.KEYWORD),  # NEW — MEM-05
    ]
    for field_name, schema in indexes:
        try:
            self._client.create_payload_index(
                collection_name=collection_name,
                field_name=field_name,
                field_schema=schema,
            )
        except Exception as e:
            logger.warning(
                "Qdrant: %s index creation failed (non-critical): %s", field_name, e
            )
```

### Pattern 4: HTTP Endpoint Wiring

**What:** Two new routes added to `create_sidecar_app()` following the existing `/sidecar/execute` pattern.

```python
# dashboard/sidecar.py — inside create_sidecar_app()
from core.sidecar_models import (
    MemoryRecallRequest,
    MemoryRecallResponse,
    MemoryStoreRequest,
    MemoryStoreResponse,
)

@app.post("/memory/recall", response_model=MemoryRecallResponse)
async def memory_recall(
    req: MemoryRecallRequest,
    _user: str = Depends(get_current_user),  # D-15
) -> MemoryRecallResponse:
    """Retrieve relevant memories scoped to agent_id/company_id (MEM-04)."""
    if not memory_bridge:
        return MemoryRecallResponse(memories=[])
    try:
        memories = await asyncio.wait_for(
            memory_bridge.recall(
                query=req.query,
                agent_id=req.agent_id,
                company_id=req.company_id,
                top_k=req.top_k,
            ),
            timeout=0.2,
        )
    except asyncio.TimeoutError:
        memories = []
    return MemoryRecallResponse(memories=memories)

@app.post("/memory/store", response_model=MemoryStoreResponse)
async def memory_store_endpoint(
    req: MemoryStoreRequest,
    _user: str = Depends(get_current_user),  # D-15
) -> MemoryStoreResponse:
    """Store a pre-extracted learning scoped to agent_id/company_id (MEM-04)."""
    ...
```

### Pattern 5: Pydantic Models (core/sidecar_models.py)

**What:** New models following existing ConfigDict patterns in that file.

```python
# core/sidecar_models.py — append after existing models

class MemoryRecallRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    query: str
    agent_id: str = Field(..., alias="agentId")   # required — D-10
    company_id: str = Field(default="", alias="companyId")
    top_k: int = Field(default=5, ge=1, le=50)
    score_threshold: float = Field(default=0.25, ge=0.0, le=1.0)

class MemoryItem(BaseModel):
    text: str
    score: float
    source: str = ""
    metadata: dict = Field(default_factory=dict)

class MemoryRecallResponse(BaseModel):
    memories: list[MemoryItem] = Field(default_factory=list)

class MemoryStoreRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    text: str
    section: str = ""
    tags: list[str] = Field(default_factory=list)
    agent_id: str = Field(..., alias="agentId")
    company_id: str = Field(default="", alias="companyId")

class MemoryStoreResponse(BaseModel):
    stored: bool = True
    point_id: str = ""
```

### Anti-Patterns to Avoid

- **Unfiltered semantic_search in recall:** Never call `semantic_search()` without `agent_id` filter — leads to cross-agent memory leaks (violates MEM-05). D-10 requires `raise ValueError` if agent_id is missing.
- **Blocking recall in route handler:** Never `await memory_bridge.recall()` without `wait_for(timeout=0.2)` — Qdrant server mode can be slow under load.
- **Putting learn_async before _post_callback:** The fire-and-forget task must be created AFTER `_post_callback()` completes — ensure callback latency is zero-impacted (D-05).
- **Swallowing learn_async exceptions silently without logging:** P7 from PITFALLS.md — fire-and-forget tasks that fail silently make debugging impossible. Log at WARNING level on extraction failure even if not re-raising.
- **Using asyncio.run() inside learn_async:** learn_async runs inside an existing event loop. Never nest `asyncio.run()` — use `asyncio.to_thread()` for sync calls within async context.
- **Instructor calls directly in the async event loop:** The `_sync_extract()` pattern in server.py wraps instructor in `asyncio.to_thread()` — follow the same pattern in learn_async to avoid blocking the loop.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Vector similarity search with scope filter | Custom cosine + filter loop | `QdrantStore.search()` with FieldCondition | Qdrant HNSW with indexed payload filter is O(log n) vs O(n) scan |
| Timeout enforcement | Polling loop with time.time() | `asyncio.wait_for(coro, timeout=0.2)` | Stdlib, composable, no busy-wait |
| Structured learning extraction | Custom JSON prompt parser | `instructor.from_openai()` + Pydantic model | instructor handles retry logic, schema validation, mode selection |
| KEYWORD index creation | Manual SQL-style indexes | `QdrantStore._ensure_task_indexes()` extension | Idempotent, already called during collection init |
| Fire-and-forget async task | Thread pool executor | `asyncio.create_task()` | Already the pattern in `_maybe_promote_quarantined` and `_schedule_reindex` |
| Bearer auth on new routes | New auth middleware | `Depends(get_current_user)` from `dashboard/auth.py` | Existing JWT dependency, no new code |

**Key insight:** The entire memory system already exists. Phase 25 is orchestration — wiring recall and learn_async into `execute_async()`, adding scope filters to existing search, and exposing two HTTP routes. No new storage backends, embedding models, or auth systems.

---

## Common Pitfalls

### Pitfall 1: Sync Qdrant Client in Async Context

**What goes wrong:** `QdrantStore.search()` is synchronous (it wraps `self._client.query_points()` which is a sync qdrant-client call). Calling it directly in an async function without `asyncio.to_thread()` blocks the event loop. Under load this will delay ALL concurrent sidecar requests.

**Why it happens:** The existing `MemoryStore.semantic_search()` correctly wraps Qdrant calls with `asyncio.to_thread()` indirectly through the embeddings layer. But if `MemoryBridge.recall()` calls `QdrantStore.search()` directly (bypassing `MemoryStore.semantic_search()`), it will block.

**How to avoid:** Route recall through `self.memory_store.semantic_search()` (which already handles the async/sync bridge) rather than calling `self.memory_store._qdrant.search()` directly. Alternatively, wrap direct QdrantStore calls in `asyncio.to_thread()`.

**Warning signs:** Sidecar requests queue up; `asyncio.wait_for()` always fires TimeoutError even when Qdrant is fast.

### Pitfall 2: Missing `instructor` Module at Runtime

**What goes wrong:** `instructor` is in `requirements.txt` but confirmed NOT installed in the current virtualenv. If `learn_async` imports instructor at module level, the entire `memory_bridge` module fails to load.

**Why it happens:** Development environment drift between requirements.txt and installed packages.

**How to avoid:** Follow the `_sync_extract()` pattern in `server.py` exactly — wrap instructor import inside `try: import instructor / except ImportError: return []`. This is consistent with the project rule "Graceful degradation — handle absence, never crash."

**Warning signs:** `ModuleNotFoundError: No module named 'instructor'` at sidecar startup.

### Pitfall 3: asyncio.TimeoutError vs concurrent.futures.TimeoutError

**What goes wrong:** `asyncio.wait_for()` raises `asyncio.TimeoutError` (not `concurrent.futures.TimeoutError` or the built-in `TimeoutError`). Code that catches `TimeoutError` (built-in) will catch it in Python 3.11+ (they are aliases), but older code catching `concurrent.futures.TimeoutError` will NOT catch `asyncio.TimeoutError`.

**Why it happens:** Python's TimeoutError aliasing is version-dependent.

**How to avoid:** Always catch `asyncio.TimeoutError` explicitly in the except clause for `asyncio.wait_for()` calls.

**Warning signs:** TimeoutError passes through uncaught; execution blocks past 200ms.

### Pitfall 4: learn_async Fires Before Event Loop Is Ready

**What goes wrong:** `asyncio.create_task()` called inside `execute_async()` after `_post_callback()`. If `execute_async` is not running in an active event loop (e.g. in tests using `asyncio.run()` per-test), the task is created but the loop exits before it runs.

**Why it happens:** Test harnesses often use `asyncio.run()` per test, which creates and immediately closes a loop.

**How to avoid:** In tests, explicitly `await` the task or use `asyncio.gather()` to let tasks complete before loop exits. Production code is fine — FastAPI's event loop stays alive for the sidecar lifetime.

**Warning signs:** learn_async "appears" to work but no memories are ever stored in tests.

### Pitfall 5: Score Threshold Too High Silences All Results

**What goes wrong:** ONNX all-MiniLM-L6-v2 produces cosine similarity scores in the 0.2-0.5 range for semantically relevant content. A default threshold of 0.5 or higher will silently return zero memories, appearing as a timeout or empty recall even when relevant memories exist.

**Why it happens:** Confusion between normalized cosine similarity (max 1.0) and "percentage match" intuition.

**How to avoid:** Use 0.25 as the default score threshold (matches existing `search_service.py` default). Make it configurable via request param (D-13 permits client-side threshold filtering).

**Warning signs:** Recall always returns empty list; no timeout logged.

### Pitfall 6: Missing `memory_bridge` in create_sidecar_app

**What goes wrong:** `SidecarOrchestrator` is instantiated inside `create_sidecar_app()`. If `MemoryBridge` is not instantiated and passed to both the orchestrator AND the route closures, the `/memory/recall` and `/memory/store` routes have no access to it.

**Why it happens:** The orchestrator and the route functions are separate closures — they don't share state unless explicitly passed.

**How to avoid:** Instantiate `MemoryBridge(memory_store=memory_store)` once at the top of `create_sidecar_app()` and pass it to both the orchestrator constructor and the route closures via closure capture.

**Warning signs:** `memory_bridge` is `None` in route handlers; `/memory/recall` always returns `{"memories": []}`.

---

## Code Examples

Verified patterns from existing codebase:

### Fire-and-Forget (from server.py line ~3924)
```python
# Source: dashboard/server.py — _maybe_promote_quarantined pattern
_asyncio.create_task(
    _maybe_promote_quarantined(memory_store, task_type, outcome, summary)
)
```

### QdrantStore KEYWORD Index Creation (from qdrant_store.py line ~174)
```python
# Source: memory/qdrant_store.py — _ensure_task_indexes()
self._client.create_payload_index(
    collection_name=collection_name,
    field_name="task_type",
    field_schema=PayloadSchemaType.KEYWORD,
)
```

### QdrantStore FieldCondition Filter (from qdrant_store.py line ~324)
```python
# Source: memory/qdrant_store.py — search()
conditions.append(FieldCondition(key="task_type", match=MatchValue(value=task_type_filter)))
```

### Instructor Extraction with ImportError Guard (from server.py line ~4110)
```python
# Source: dashboard/server.py — _sync_extract()
def _sync_extract(prompt_text):
    try:
        import instructor
        from openai import OpenAI
    except ImportError:
        return {"learnings": []}
    ...
    client = instructor.from_openai(OpenAI(**client_kwargs), mode=instructor.Mode.JSON)
    result = client.chat.completions.create(
        model="google/gemini-2.0-flash-001",
        response_model=ExtractionResult,
        max_retries=2,
        messages=[{"role": "user", "content": prompt_text}],
    )
    return result.model_dump()

try:
    extraction = await asyncio.to_thread(_sync_extract, prompt)
except Exception as e:
    logger.warning("Knowledge extraction failed: %s", e)
```

### MemoryStore.semantic_search signature (from store.py line ~317)
```python
# Source: memory/store.py — semantic_search()
async def semantic_search(
    self,
    query: str,
    top_k: int = 5,
    source: str = "",
    project: str = "",
    lifecycle_aware: bool = True,
    task_type: str = "",
) -> list[dict]:
```
Note: This does NOT currently accept `agent_id` or `company_id` as filters. MemoryBridge.recall() must either (a) extend semantic_search() with new kwargs, or (b) call `self._qdrant.search()` directly with agent_id FieldCondition appended. Option (b) is simpler for Phase 25 and avoids modifying the existing semantic_search interface.

### SidecarOrchestrator constructor (from sidecar_orchestrator.py line ~52)
```python
# Source: core/sidecar_orchestrator.py
class SidecarOrchestrator:
    def __init__(
        self,
        memory_store: Any = None,
        agent_manager: Any = None,
        effectiveness_store: Any = None,
        reward_system: Any = None,
    ):
```
Extend to accept `memory_bridge: Any = None`.

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| MemoryStore without scope filters | QdrantStore KEYWORD payload indexes for project/task_type | Phase 20-21 | agent_id/company_id indexes follow same pattern |
| Blocking learning extraction in HTTP handler | asyncio.to_thread() + fire-and-forget task | Phase 21 | learn_async follows same non-blocking pattern |
| instructor imported at module level | Lazy import inside sync function body | Phase 21 | Required pattern for graceful degradation |

**No deprecated patterns apply to this phase.** The Qdrant client `query_points()` API used in this codebase is current (qdrant-client v1.x). The `search()` method was renamed to `query_points()` — the codebase already uses the current API.

---

## Open Questions

1. **Does `semantic_search()` need agent_id/company_id parameters, or should MemoryBridge call QdrantStore.search() directly?**
   - What we know: `semantic_search()` has `project` and `task_type` filter params, but not `agent_id`. Adding them would be a clean interface extension.
   - What's unclear: Adding params to `semantic_search()` expands its interface; bypassing it means MemoryBridge duplicates some embedding logic.
   - Recommendation: For Phase 25 MVP, MemoryBridge calls `self.memory_store.embeddings.embed_text(query)` to get the vector, then calls `self.memory_store._qdrant.search()` with agent_id FieldCondition directly. This is surgical and does not modify the existing interface. Add agent_id to `semantic_search()` in a later phase if needed.

2. **Should learn_async use the existing QuarantineEntry/promotion system or a simpler direct upsert?**
   - What we know: D-08 says "reuse existing instructor+Pydantic extraction pipeline and quarantine/promotion system from Phase 20-21."
   - What's unclear: The quarantine system (in server.py) is tightly coupled to the dashboard route context and uses task_type/task_id from the Claude Code session context.
   - Recommendation: For Phase 25 MVP, skip quarantine and do a direct upsert into the KNOWLEDGE collection with `agent_id` and `company_id` in the payload. The quarantine system adds value only when there are many repeated learnings — not needed for initial wiring.

3. **What query string should be used for recall when AgentRuntime is not yet wired?**
   - What we know: D-04 says recalled memories are stored as part of execution context for now. The query must come from AdapterExecutionContext.
   - What's unclear: `AdapterExecutionContext.context` is a free-form dict. The task description may or may not be present.
   - Recommendation: Use `ctx.context.get("taskDescription", "") or ctx.task_id` as the recall query. If both are empty, skip recall entirely and log at DEBUG level.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| qdrant-client | MEM-01, MEM-05 | Yes | installed | Graceful — memory bridge returns empty list |
| onnxruntime | MEM-01 (embeddings) | Yes | installed | Graceful — falls back to grep search |
| instructor | MEM-03 (learn_async) | No (NOT installed) | — in requirements.txt | Graceful — learn_async returns without extracting |
| openai (sync) | MEM-03 (instructor backend) | Yes | installed | Only needed if instructor present |
| Python asyncio | MEM-02, MEM-03 | stdlib | 3.11+ | No fallback needed |
| FastAPI | MEM-04 | Yes | installed | No fallback needed |
| pydantic v2 | MEM-04 | Yes | installed | No fallback needed |

**Missing dependencies with no fallback:**
- None — all blocking deps are installed; instructor absence is a graceful-degrade scenario per project rules.

**Missing dependencies with fallback:**
- `instructor` (not installed): learn_async guards with `try: import instructor / except ImportError: return`. Install with `pip install instructor>=1.3.0`. Planning should include a Wave 0 task to verify or install.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.2 |
| Config file | pytest.ini (or pyproject.toml — check project root) |
| Quick run command | `python -m pytest tests/test_memory_bridge.py -x -q` |
| Full suite command | `python -m pytest tests/ -x -q` |

### Phase Requirements to Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| MEM-01 | recall() returns top-K memories for agent+task | unit | `python -m pytest tests/test_memory_bridge.py::TestMemoryBridgeRecall -x -q` | No — Wave 0 |
| MEM-02 | recall() returns empty list when timeout exceeded | unit | `python -m pytest tests/test_memory_bridge.py::TestMemoryBridgeTimeout -x -q` | No — Wave 0 |
| MEM-03 | learn_async() runs fire-and-forget, does not delay callback | unit | `python -m pytest tests/test_memory_bridge.py::TestMemoryBridgeLearn -x -q` | No — Wave 0 |
| MEM-04 | POST /memory/recall and POST /memory/store respond correctly | integration | `python -m pytest tests/test_memory_bridge.py::TestMemoryRoutes -x -q` | No — Wave 0 |
| MEM-05 | Two agents with different agent_ids do not share memories | unit | `python -m pytest tests/test_memory_bridge.py::TestMemoryScopeIsolation -x -q` | No — Wave 0 |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/test_memory_bridge.py -x -q`
- **Per wave merge:** `python -m pytest tests/test_sidecar.py tests/test_memory_bridge.py -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_memory_bridge.py` — covers MEM-01 through MEM-05 (new file needed)
- [ ] `core/memory_bridge.py` — new class (implementation target, not just test gap)

*(Existing test infrastructure: conftest.py, pytest, fastapi TestClient, all installed — no framework setup needed)*

---

## Project Constraints (from CLAUDE.md)

| Directive | Impact on Phase 25 |
|-----------|-------------------|
| All I/O is async — use `aiofiles`, `httpx`, `asyncio`. Never blocking I/O in tools. | recall() must be async; QdrantStore sync calls must be wrapped in asyncio.to_thread() |
| Graceful degradation — Redis, Qdrant, MCP are optional. Handle absence, never crash. | MemoryBridge must return [] when memory_store is None or Qdrant unavailable |
| Sandbox always on — validate paths via sandbox.resolve_path(). | Not directly applicable to memory bridge (no file I/O in the bridge itself) |
| New pitfalls — add to `.claude/reference/pitfalls-archive.md` when discovered. | If new non-obvious issues found during implementation, document them |
| New modules need `tests/test_*.py`. Full standards: development-workflow.md | `tests/test_memory_bridge.py` is required — included in Wave 0 gaps |
| GSD Workflow Enforcement — use GSD commands before file-changing tools. | Standard — follow /gsd:execute-phase |

---

## Sources

### Primary (HIGH confidence)
- `core/sidecar_orchestrator.py` — execute_async() stub, constructor signatures, callback pattern
- `dashboard/sidecar.py` — create_sidecar_app() factory, route patterns, dependency injection
- `core/sidecar_models.py` — existing Pydantic model patterns (ConfigDict, Field aliases)
- `memory/qdrant_store.py` — _ensure_task_indexes(), search(), upsert_vectors(), search_with_lifecycle()
- `memory/store.py` — semantic_search() signature, filter params, lifecycle-aware search path
- `memory/embeddings.py` — ONNX embedder, EmbeddingStore.embed_text()
- `dashboard/server.py` lines 3780-3926 — _maybe_promote_quarantined() pattern (fire-and-forget reference)
- `dashboard/server.py` lines 4040-4157 — instructor+Pydantic extraction pipeline (learn_async reference)
- `.planning/phases/25-memory-bridge/25-CONTEXT.md` — All locked decisions D-01 through D-16
- `.planning/research/PITFALLS.md` — P4 (heartbeat timeout vs memory injection), P7 (multi-tenant isolation)
- `requirements.txt` — confirmed instructor>=1.3.0 listed but not installed

### Secondary (MEDIUM confidence)
- `.planning/research/ARCHITECTURE.md` — MemoryBridge component responsibilities diagram
- `.planning/research/FEATURES.md` — memory_recall agent tool interface contracts
- `tests/test_sidecar.py` — test patterns to follow for test_memory_bridge.py
- `tests/test_learning_extraction.py` — learning extraction test patterns

### Tertiary (LOW confidence)
- None — all findings are from direct codebase inspection

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries verified by `python3 -c "import X"` commands; instructor absence confirmed
- Architecture: HIGH — all patterns verified against live source files with line references
- Pitfalls: HIGH — all pitfalls derived from actual codebase patterns and confirmed antipatterns

**Research date:** 2026-03-29
**Valid until:** 2026-05-01 (stable Python/Qdrant stack; instructor API unlikely to change)
