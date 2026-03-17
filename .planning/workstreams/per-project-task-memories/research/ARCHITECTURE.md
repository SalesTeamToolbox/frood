# Architecture Research

**Domain:** Task-aware memory integration for AI agent platform
**Researched:** 2026-03-17
**Confidence:** HIGH — based on direct codebase analysis of all relevant modules

## Standard Architecture

### System Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│  ENTRY POINTS (unchanged)                                               │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────────┐  │
│  │  MCP tool call   │  │  Post-task hook  │  │  context tool query  │  │
│  │  (Claude Code)   │  │  (task complete) │  │  (task start)        │  │
│  └────────┬─────────┘  └────────┬─────────┘  └──────────┬───────────┘  │
└───────────┼─────────────────────┼────────────────────────┼─────────────┘
            │                     │                         │
┌───────────▼─────────────────────▼────────────────────────▼─────────────┐
│  NEW MIDDLEWARE LAYER                                                   │
│  ┌──────────────────────┐  ┌──────────────────┐  ┌───────────────────┐ │
│  │  MCPCallTracker      │  │  PostTaskLearner │  │  RecommendEngine  │ │
│  │  (mcp_registry.py    │  │  (new module     │  │  (new module      │ │
│  │   wrapper)           │  │   memory/task_   │  │   memory/reco_    │ │
│  │                      │  │   learner.py)    │  │   engine.py)      │ │
│  └──────────┬───────────┘  └────────┬─────────┘  └──────────┬────────┘ │
└─────────────┼────────────────────────┼─────────────────────────┼────────┘
              │                         │                          │
┌─────────────▼─────────────────────────▼──────────────────────────▼─────┐
│  EXISTING MEMORY LAYER (modified)                                       │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │  QdrantStore — extended payload schema                             │ │
│  │  Collections:  agent42_memory  agent42_history  agent42_knowledge  │ │
│  │  NEW:          agent42_task_outcomes (new collection)              │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │  ContextAssemblerTool — extended with task-type filter             │ │
│  └────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | Status |
|-----------|----------------|--------|
| `memory/store.py` (MemoryStore) | Two-layer file + Qdrant storage. Entry point for all writes. | Existing — add task_id/task_type payload propagation |
| `memory/qdrant_store.py` (QdrantStore) | HNSW vector store, lifecycle scoring, payload filtering | Existing — add task-scoped filter methods + new collection constant |
| `memory/project_memory.py` (ProjectMemoryStore) | Per-project namespace + global fallback | Existing — no changes needed; task_id is a payload field, not a directory |
| `memory/consolidation.py` (ConsolidationPipeline) | Conversation → summary → Qdrant | Existing — extend to accept task metadata |
| `mcp_registry.py` (MCPRegistryAdapter) | Routes MCP tool calls to ToolRegistry | Existing — wrap `call_tool()` with usage tracking (latency + outcome) |
| `tools/context_assembler.py` (ContextAssemblerTool) | Assembles context from memory, docs, git, skills | Existing — add task-type-aware memory filter + recommendation injection |
| `memory/task_learner.py` | Extracts learnings from completed tasks and writes to knowledge collection | **NEW** |
| `memory/reco_engine.py` | Scores tools/skills by historical effectiveness for a task type | **NEW** |
| `memory/tool_tracker.py` | Lightweight call log (tool, duration, success, task_id, task_type) | **NEW** |

## Recommended Project Structure

```
memory/
├── store.py              # existing — minimal change (pass task metadata through)
├── qdrant_store.py       # existing — add TASK_OUTCOMES constant + filter method
├── project_memory.py     # existing — unchanged
├── consolidation.py      # existing — add task_id/task_type to payload
├── embeddings.py         # existing — unchanged
├── session.py            # existing — unchanged
├── redis_session.py      # existing — unchanged
├── search_service.py     # existing — unchanged
├── task_learner.py       # NEW — post-task learning extraction
├── tool_tracker.py       # NEW — MCP tool call tracking store
└── reco_engine.py        # NEW — effectiveness scoring + recommendations

tools/
├── context_assembler.py  # existing — extend execute() with task_type param
└── memory_tool.py        # existing — add task_type param to store/log actions

mcp_registry.py           # existing — wrap call_tool() with tracker
```

### Structure Rationale

- **memory/ stays self-contained:** All new modules live in `memory/` because they read/write Qdrant. No new top-level modules needed.
- **mcp_registry.py is the single intercept point:** Every MCP tool call passes through `MCPRegistryAdapter.call_tool()`. Adding a two-line wrapper here captures all tool usage without touching individual tools.
- **No new collections for task metadata:** `task_id` and `task_type` are payload fields added to existing collections. Only tool outcomes get a dedicated collection because they have a fundamentally different structure (aggregate stats, not text chunks).

## Architectural Patterns

### Pattern 1: Payload Field Extension (for task_id / task_type)

**What:** Add `task_id` and `task_type` as optional fields to every Qdrant payload write, propagated from call context. Existing entries without these fields are unaffected.

**When to use:** For memory, history, and knowledge entries created during a task. Not needed for conversation summaries.

**Trade-offs:** Zero migration needed (Qdrant's schemaless payloads accept new fields immediately). Existing lifecycle scoring (`search_with_lifecycle`) is unaffected — task fields appear in `metadata` passthrough. Query-time filtering uses `FieldCondition(key="task_type", match=MatchValue(value=...))`.

**Example — adding fields at write time:**
```python
# In MemoryStore.log_event_semantic(), pass task metadata through:
async def log_event_semantic(
    self,
    event_type: str,
    summary: str,
    details: str = "",
    task_id: str = "",
    task_type: str = "",
):
    self.log_event(event_type, summary, details)
    if self.embeddings.is_available:
        await self.embeddings.index_history_entry(
            event_type, summary, details,
            extra_payload={"task_id": task_id, "task_type": task_type},
        )
```

**Example — task-scoped retrieval:**
```python
# In QdrantStore.search_with_lifecycle(), add task_type_filter parameter:
def search_with_lifecycle(
    self,
    collection_suffix: str,
    query_vector: list[float],
    top_k: int = 5,
    task_type_filter: str = "",   # NEW
    ...
```

### Pattern 2: Dedicated Collection for Task Outcomes (agent42_task_outcomes)

**What:** A separate Qdrant collection that stores structured task outcome records — one point per task completion. These are NOT text chunks for retrieval; they are aggregate records for effectiveness scoring.

**When to use:** Tool/skill effectiveness tracking. Answering "which tools worked for flask builds?" requires aggregating over many task records, not semantic similarity search.

**Trade-offs:** Separate collection avoids polluting the memory/history search space with aggregate statistics. The collection is smaller (one record per task, not per memory chunk) and queried by exact filter (task_type, tool_name), not by vector similarity.

**Schema:**
```python
# agent42_task_outcomes payload (no vector needed — use zero vector or skip)
{
    "task_id": "uuid",
    "task_type": "coding",        # from ToolRegistry._CODE_TASK_TYPES
    "project_id": "my-project",
    "status": "success",          # success | failure | partial
    "duration_seconds": 142.3,
    "tools_used": ["git", "test_runner", "shell"],
    "skills_used": ["debugging", "code-review"],
    "tool_outcomes": {            # per-tool: calls, successes, avg_ms
        "git": {"calls": 5, "successes": 5, "avg_ms": 180},
        "test_runner": {"calls": 2, "successes": 1, "avg_ms": 4200},
    },
    "learnings_extracted": 3,     # count of knowledge entries written
    "timestamp": 1710000000.0,
}
```

**Why not extend existing collections:** The existing `agent42_knowledge` collection stores text chunks. Task outcomes have no meaningful text to embed and no semantic retrieval use case. Storing them in `agent42_knowledge` would require dummy vectors and make payload filtering messy.

### Pattern 3: Call Tracker as a Thin Wrapper (no latency overhead)

**What:** `MCPCallTracker` wraps `MCPRegistryAdapter.call_tool()` and records tool name, latency, and outcome to an in-memory ring buffer. The ring buffer is flushed to `ToolTracker` (SQLite or JSONL) asynchronously.

**When to use:** MCP tool call interception without adding latency to the critical path.

**Trade-offs:** Async flush means the last few calls before server shutdown may not be persisted. This is acceptable for an effectiveness tracking use case — we don't need perfect durability for statistics.

**Implementation in mcp_registry.py:**
```python
async def call_tool(self, name: str, arguments: dict):
    t0 = time.monotonic()
    result = await self._original_call_tool(name, arguments)
    latency_ms = (time.monotonic() - t0) * 1000
    success = not self.call_tool_is_error(name, result)
    # fire-and-forget, same pattern as _record_recalls()
    asyncio.get_event_loop().create_task(
        self._tracker.record(name, latency_ms, success,
                              self._current_task_id, self._current_task_type)
    )
    return result
```

**Task context propagation:** The tracker needs `task_id` and `task_type` at call time. The simplest approach: `MCPRegistryAdapter` holds a mutable `current_task` dict set by a `begin_task()` / `end_task()` protocol (called by the post-task learner). This avoids threading `task_id` through every tool call signature.

### Pattern 4: Post-Task Learner as a Hook in the Task Completion Path

**What:** `PostTaskLearner.run(task_id, task_type, tool_log)` is called when a task transitions to `completed` or `failed`. It runs an LLM summarization over the tool log and task context, then writes extracted learnings to `agent42_knowledge` and the task outcome to `agent42_task_outcomes`.

**When to use:** Task completion. The hook point is wherever the task status is set to `completed` — currently in `WorkOrder.transition()` and any future task queue completion paths.

**Trade-offs:** LLM summarization adds latency to task completion (10-30s). This is acceptable because task completion is not latency-sensitive (unlike tool calls). If the LLM call fails, the task outcome is still recorded without extracted learnings.

**Where it fits:**
- For MCP-server-driven work orders: after `WorkOrder.transition("completed")` in `core/work_order.py`
- For dashboard agent tasks: in `core/agent_manager.py` after task loop exits
- The learner can be invoked as a fire-and-forget background task to avoid blocking the completion signal

### Pattern 5: Proactive Recommendations via Context Assembler Extension

**What:** `ContextAssemblerTool` adds a `task_type` parameter. When provided, it calls `RecoEngine.get_recommendations(task_type, project_id)` and prepends the result to the assembled context bundle.

**When to use:** When Claude Code calls `agent42_context` at the start of a task. The `task_type` parameter signals intent.

**Trade-offs:** Recommendations are purely additive to the existing context assembly. If `RecoEngine` is unavailable or returns empty, context assembly proceeds unchanged. This is a clean extension with no behavior change for callers that don't pass `task_type`.

**Extension to context tool parameters:**
```python
"task_type": {
    "type": "string",
    "description": "Task type hint for proactive recommendations "
                   "(e.g. 'coding', 'debugging', 'app_create'). "
                   "When provided, surfaces relevant tool/skill learnings.",
},
```

## Data Flow

### Task Start Flow (proactive recommendations)

```
Claude Code calls agent42_context(topic="flask app", task_type="app_create")
    ↓
ContextAssemblerTool.execute()
    ↓ (new branch when task_type provided)
RecoEngine.get_recommendations("app_create", project_id)
    ↓
QdrantStore.filter(agent42_task_outcomes, task_type="app_create")
    → aggregate tool_outcomes across matching records
    → rank by success_rate × recency_weight
    ↓
MemoryStore.semantic_search(topic, task_type_filter="app_create")
    ↓
Merged result: [recommendations] + [semantic memory] + [docs] + [git] + [skills]
    ↓
Return context bundle to Claude Code
```

### Tool Call Tracking Flow (zero latency impact)

```
Claude Code calls agent42_git (or any tool)
    ↓
MCPRegistryAdapter.call_tool("agent42_git", {...})
    ↓ (synchronous: <1ms)
record start_time = time.monotonic()
    ↓
ToolRegistry.execute("git", ...)     ← unchanged
    ↓ (result returns)
latency_ms = (time.monotonic() - start_time) * 1000
asyncio.create_task(tracker.record(...))    ← fire-and-forget
    ↓
return result to Claude Code (no added latency)
```

### Post-Task Learning Flow

```
Task transitions to "completed" (WorkOrder or agent_manager)
    ↓
PostTaskLearner.run(task_id, task_type, tool_log) [background task]
    ↓
1. ToolTracker.get_session_log(task_id)
    → list of {tool, latency_ms, success, timestamp}
    ↓
2. LLM summarization (reuse ConsolidationPipeline model_router)
    prompt: "What worked, what failed, key learnings from this {task_type} task?"
    context: tool log + task prompt + completion status
    ↓
3. EmbeddingStore.embed_text(learning_text)
    ↓
4. QdrantStore.upsert_single(
       KNOWLEDGE,
       learning_text,
       vector,
       {task_id, task_type, project_id, source="task_learning"}
   )
    ↓
5. QdrantStore.upsert_single(
       TASK_OUTCOMES,
       "",   ← no text needed
       zero_vector_or_skip,
       {task_id, task_type, tools_used, tool_outcomes, status, duration}
   )
```

### Recommendations Retrieval Flow

```
RecoEngine.get_recommendations(task_type, project_id)
    ↓
1. QdrantStore.scroll(TASK_OUTCOMES, filter={task_type: "app_create"}, limit=50)
    → recent task outcome records
    ↓
2. Aggregate tool_outcomes across records:
    for each tool: success_rate = successes / calls (weighted by recency)
    ↓
3. MemoryStore.semantic_search(
       query=f"{task_type} learnings tips pitfalls",
       task_type_filter=task_type,
       collection=KNOWLEDGE,
       top_k=5
   )
    ↓
4. Return {
       "recommended_tools": ["git", "test_runner"],   # ranked by success_rate
       "avoid_tools": ["browser"],                     # high failure rate
       "relevant_learnings": [...],                    # semantic search results
   }
```

## Integration Points

### Existing Modules — What Changes

| Module | Change Required | Scope |
|--------|-----------------|-------|
| `memory/qdrant_store.py` | Add `TASK_OUTCOMES = "task_outcomes"` constant; add `task_type_filter` param to `search_with_lifecycle()`; add `scroll()` wrapper for aggregate queries | Small — 3 additions |
| `memory/store.py` | Thread `task_id`, `task_type` kwargs through `log_event_semantic()` and `semantic_search()` | Small — 2 method signatures |
| `memory/embeddings.py` | Accept `extra_payload` dict in `index_history_entry()` and `add_entry()` to pass through task fields | Small — 2 method signatures |
| `mcp_registry.py` | Wrap `call_tool()` to record latency + outcome; add `begin_task()` / `end_task()` for task context | Small — ~30 lines |
| `tools/context_assembler.py` | Add `task_type` parameter to `parameters` schema; call `RecoEngine` when provided | Small — ~40 lines |
| `tools/memory_tool.py` | Add `task_type` parameter to `store` and `log` actions; pass through to store | Small — 2 parameter additions |
| `core/work_order.py` | Call `PostTaskLearner.run()` in background after `transition("completed")` | Small — ~10 lines |

### New Modules — What to Build

| Module | Dependencies | Complexity |
|--------|--------------|------------|
| `memory/tool_tracker.py` | `aiofiles` (already in requirements), no new deps | Low — JSONL append + in-memory buffer |
| `memory/task_learner.py` | `ConsolidationPipeline` (existing), `QdrantStore` (existing), `EmbeddingStore` (existing) | Medium — LLM prompt + async writes |
| `memory/reco_engine.py` | `QdrantStore` (existing) only | Low — aggregate math on scroll results |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| `MCPRegistryAdapter` → `ToolTracker` | Direct async method call (fire-and-forget) | Tracker must never block the registry |
| `PostTaskLearner` → `ConsolidationPipeline` | Reuses existing `model_router` reference | Learner needs model_router injected at construction time |
| `PostTaskLearner` → `QdrantStore` | Direct write to KNOWLEDGE + TASK_OUTCOMES | Both collections via the single shared `qdrant_store` instance |
| `RecoEngine` → `QdrantStore` | Read-only: `scroll()` on TASK_OUTCOMES + `search_with_lifecycle()` on KNOWLEDGE | No writes from reco engine |
| `ContextAssemblerTool` → `RecoEngine` | Direct call when `task_type` provided | RecoEngine must be injected at tool construction time in `mcp_server.py` |

### Qdrant Payload Schema — Final State

**Existing collections gain two optional fields:**
```
agent42_memory, agent42_history, agent42_knowledge payloads:
  (existing fields unchanged)
  task_id:   str   [optional, "" when not task-scoped]
  task_type: str   [optional, "" when not task-scoped]
```

**New collection:**
```
agent42_task_outcomes payloads:
  task_id:           str
  task_type:         str
  project_id:        str
  status:            "success" | "failure" | "partial"
  duration_seconds:  float
  tools_used:        list[str]
  skills_used:       list[str]
  tool_outcomes:     dict[str, {calls: int, successes: int, avg_ms: float}]
  learnings_extracted: int
  timestamp:         float
```

Note: `agent42_task_outcomes` does not require vector search. Use a zero vector (all zeros matching `vector_dim`) and rely entirely on payload filtering + `scroll()`. This is valid Qdrant usage for a "structured records with optional search" pattern.

## Scaling Considerations

| Scale | Architecture Adjustments |
|-------|--------------------------|
| Single developer, <100 tasks | JSONL-backed ToolTracker, no Qdrant for task outcomes. QdrantStore fallback path in RecoEngine. |
| Team, 100-1K tasks/month | Qdrant for all storage. scroll() with limit=100 handles aggregation at this scale without indexing. |
| 1K+ tasks/month | Add `payload_index` on `task_type` field in QdrantStore for fast filtering. Consider materialized aggregate table. |

### Scaling Priorities

1. **First bottleneck:** Qdrant scroll() for aggregate queries across task_outcomes. Mitigation: add payload index on `task_type` (one `create_payload_index()` call, already supported by qdrant-client).
2. **Second bottleneck:** LLM summarization during PostTaskLearner. Mitigation: already fire-and-forget; if router is busy, task learning simply takes longer — does not affect task throughput.

## Anti-Patterns

### Anti-Pattern 1: New Collection Per Task Type

**What people do:** Create `agent42_coding_outcomes`, `agent42_debugging_outcomes`, etc.

**Why it's wrong:** Qdrant collection creation is expensive and not lazy. Collections proliferate as new task types appear. Filter queries across multiple collections require client-side merge.

**Do this instead:** Single `agent42_task_outcomes` collection with `task_type` as a payload field. Use `FieldCondition` for filtering. Add a payload index when the collection grows beyond ~10K records.

### Anti-Pattern 2: Synchronous Tool Tracking

**What people do:** Await the tracker write inside `call_tool()` before returning result.

**Why it's wrong:** Adds 1-10ms to every MCP tool call, which is measured and visible to the user. The tracker write is not on the critical path.

**Do this instead:** Fire-and-forget `asyncio.create_task()` for tracker writes, identical to the existing `_record_recalls()` pattern in `memory/store.py`.

### Anti-Pattern 3: Threading task_id Through All Tool Signatures

**What people do:** Add `task_id: str = ""` to every Tool's `execute()` method signature and `parameters` schema.

**Why it's wrong:** Breaks every existing tool's schema, requires LLM to pass task_id on every call (it won't know to), and leaks infrastructure concerns into tool APIs.

**Do this instead:** Store current task context on the `MCPRegistryAdapter` instance (`self._current_task`). The adapter updates it via `begin_task()` / `end_task()`. Tools never see task_id — only the tracker wrapper does.

### Anti-Pattern 4: Using agent42_knowledge for Task Outcome Aggregates

**What people do:** Store task outcome records as text in `agent42_knowledge` because "it's already there."

**Why it's wrong:** Aggregate queries (success_rate by tool and task_type) require scanning all KNOWLEDGE entries and filtering by source, which is slow and returns semantic search results contaminated with structured data. Knowledge is for text retrieval; task outcomes are for structured aggregation.

**Do this instead:** Separate `agent42_task_outcomes` collection. `RecoEngine` scrolls it directly.

## Build Order

Based on dependencies between the components:

**Phase 1 — Payload Schema Extension (no new files, purely additive)**
1. `memory/qdrant_store.py`: add `TASK_OUTCOMES` constant, `task_type_filter` param to `search_with_lifecycle()`, and a `scroll()` wrapper method
2. `memory/embeddings.py`: accept `extra_payload` in `index_history_entry()` and `add_entry()`
3. `memory/store.py`: thread `task_id`/`task_type` kwargs through `log_event_semantic()` and `semantic_search()`
4. `tools/memory_tool.py`: expose `task_type` parameter on `store` and `log` actions

Rationale: Everything downstream depends on these plumbing changes being correct. Zero behavior change for existing callers (kwargs are optional with empty string defaults).

**Phase 2 — Tool Call Tracking (new file, small mcp_registry change)**
5. `memory/tool_tracker.py`: JSONL append store with in-memory ring buffer, async `record()` and `get_session_log()` methods
6. `mcp_registry.py`: add `begin_task()` / `end_task()`, wrap `call_tool()` with tracker

Rationale: Tracker must exist before PostTaskLearner can consume its data. MCPRegistry change is small and independently testable.

**Phase 3 — Post-Task Learning (new file, small work_order change)**
7. `memory/task_learner.py`: PostTaskLearner with LLM summarization, writes to KNOWLEDGE + TASK_OUTCOMES
8. `core/work_order.py`: fire-and-forget `PostTaskLearner.run()` on task completion

Rationale: Depends on Phase 1 (payload fields) and Phase 2 (tool log). Can be tested with a mock tool log before Phase 2 is wired in.

**Phase 4 — Recommendations Engine + Context Integration**
9. `memory/reco_engine.py`: aggregate TASK_OUTCOMES, rank tools, pull semantic learnings
10. `tools/context_assembler.py`: add `task_type` parameter, inject RecoEngine, prepend recommendations
11. `mcp_server.py`: construct RecoEngine + PostTaskLearner + ToolTracker and inject into registry/tools

Rationale: RecoEngine needs data from Phase 3 to return meaningful results. Context integration is the final user-facing surface.

## Sources

- Direct analysis of `memory/store.py`, `memory/qdrant_store.py`, `memory/consolidation.py`, `memory/project_memory.py`
- Direct analysis of `tools/memory_tool.py`, `tools/context_assembler.py`, `tools/registry.py`
- Direct analysis of `mcp_registry.py`, `mcp_server.py`, `core/work_order.py`
- Qdrant payload index documentation (HIGH confidence — standard qdrant-client feature)
- Existing `_record_recalls()` pattern in `memory/store.py` confirms fire-and-forget async write is the established pattern in this codebase

---
*Architecture research for: task-aware memory integration (v1.4 Per-Project/Task Memories)*
*Researched: 2026-03-17*
