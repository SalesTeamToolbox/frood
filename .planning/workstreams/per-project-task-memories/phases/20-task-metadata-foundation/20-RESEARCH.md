# Phase 20: Task Metadata Foundation - Research

**Researched:** 2026-03-17
**Domain:** Qdrant payload indexing, Python contextvars, task lifecycle protocol
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Task type taxonomy**
- Fixed enum (`TaskType`) matching existing IntentClassifier categories: coding, debugging, research, content, strategy, app_create, marketing, general
- Enum lives in `core/task_types.py` as a shared constant — importable by both memory layer and agent dispatch
- No free-form string types — all task_type values must be valid enum members

**Task lifecycle protocol**
- Agent dispatch loop (e.g., `Agent._process_task()`) is responsible for calling `begin_task()` and `end_task()`
- Task context propagation via `contextvars.ContextVar` — memory writes auto-read current task_id/task_type without signature changes
- `begin_task()` auto-generates a UUID for task_id — callers never provide IDs manually
- `end_task()` is explicit — must be called when task completes
- Lifecycle functions live in new `core/task_context.py` module alongside `TaskType` enum

**Backward compatibility**
- Existing entries (no task_type/task_id fields) are excluded from filtered queries — a filter means a filter
- Existing entries remain fully queryable in unfiltered searches (no regression per TMETA-02)
- No migration or backfill — old entries age out naturally

**Search API**
- Extend existing `EmbeddingStore.search()` and `QdrantStore.search()` with optional `task_type_filter` and `task_id_filter` parameters
- Follows existing pattern of `source_filter`/`channel_filter`
- `MemoryStore.build_context_semantic()` passes task_type through to filtered search (RETR-02)
- `search_with_lifecycle()` from RETR-01 fulfilled by extended `search()` signature

**Payload indexing**
- Qdrant keyword index on `task_type` (string values, low cardinality ~8 values)
- Qdrant keyword index on `task_id` (UUID strings, high cardinality, exact-match lookups)
- Indexes created at collection creation time in `QdrantStore._ensure_collection()`
- Indexes applied to MEMORY and HISTORY collections only

### Claude's Discretion
- Exact ContextVar naming and helper function signatures
- How to handle edge case of memory write outside any task context (likely just omit task fields)
- Internal structure of `core/task_context.py` beyond the agreed public API
- Whether to add `_ensure_indexes()` as a separate method or inline in `_ensure_collection()`

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope
</user_constraints>

---

## Summary

Phase 20 extends the existing Qdrant-backed memory system to carry task provenance (task_id, task_type) in payloads. The work spans three layers: a new `core/task_context.py` module introducing the `TaskType` enum and `contextvars`-based lifecycle API; payload injection at the `EmbeddingStore.add_entry()` / `QdrantStore.upsert_vectors()` boundary; and Qdrant keyword indexes on `task_type` and `task_id` for filtered queries.

The implementation is straightforward because the existing codebase already has all the needed extension points. `QdrantStore.upsert_vectors()` accepts arbitrary `**payload` dicts, `QdrantStore.search()` already builds filter conditions from `source_filter`/`channel_filter`, and `EmbeddingStore.add_entry()` already accepts a `metadata: dict` parameter. The pattern for each addition is copy-extend an existing pattern, not introduce a new abstraction.

The one non-obvious concern is the `TaskType` enum definition location. The enum is currently defined (as a stub) in `dashboard/server.py`, and referenced (as a missing module) via `from core.task_queue import TaskType` in `agents/agent_routing_store.py` and test files. Phase 20 creates `core/task_types.py` to hold the canonical enum. The dashboard stub and the `core.task_queue` import path are separate issues that require care during integration.

**Primary recommendation:** Create `core/task_types.py` and `core/task_context.py` first; inject task context into payload at `EmbeddingStore.add_entry()`; add Qdrant indexes in `_ensure_collection()`; extend `QdrantStore.search()` and `search_with_lifecycle()` with filter params; surface through `MemoryStore.build_context_semantic()`.

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| TMETA-01 | New memory entries include `task_id` and `task_type` in Qdrant payload | ContextVar read in `EmbeddingStore.add_entry()` → merged into payload at `upsert_vectors()` |
| TMETA-02 | Existing entries without task fields remain queryable (no regression) | Qdrant `FieldCondition` with `MatchValue` only applies to entries that have the field; entries without it pass through unfiltered searches |
| TMETA-03 | Qdrant payload indexes created on `task_type` and `task_id` | `client.create_payload_index(collection, "task_type", PayloadSchemaType.KEYWORD)` called in `_ensure_collection()` |
| TMETA-04 | `begin_task()` / `end_task()` protocol propagates task context through memory operations | `contextvars.ContextVar` copies to asyncio child tasks automatically; no signature changes needed in callers |
| RETR-01 | `search_with_lifecycle()` accepts optional `task_type_filter` parameter | Extend `QdrantStore.search_with_lifecycle()` signature following `source_filter` pattern |
| RETR-02 | `build_context_semantic()` passes task_type through to filtered search | `MemoryStore.build_context_semantic()` at line 380 of `memory/store.py` calls `self.embeddings.search()` — extend that call with `task_type_filter` param |
</phase_requirements>

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `qdrant-client` | Installed (verified) | Payload indexing and filtered queries | Already in use; `create_payload_index()` and `PayloadSchemaType.KEYWORD` available |
| `contextvars` | Python stdlib 3.7+ | Task context propagation | Zero dependencies; asyncio-native; auto-copies to child tasks |
| `uuid` | Python stdlib | Task ID generation | Already imported in `memory/qdrant_store.py`; `uuid.uuid4()` for random IDs |
| `enum` | Python stdlib | TaskType enum | Pattern matches `TaskStatus` in `dashboard/server.py` |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `pytest-asyncio` | Installed (`asyncio_mode = "auto"` in pyproject.toml) | Async test support | All async tests for lifecycle functions |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `contextvars.ContextVar` | Thread-local, explicit parameter passing | ContextVar is the correct choice: asyncio-native, copies to child tasks, no signature pollution |
| `PayloadSchemaType.KEYWORD` for task_id | `PayloadSchemaType.UUID` | UUID schema is more precise but KEYWORD works for UUID strings and keeps filter construction identical |

**Installation:** No new packages needed. Everything is stdlib or already installed.

---

## Architecture Patterns

### Recommended Project Structure (new files only)
```
core/
├── task_types.py      # TaskType enum — shared constant
└── task_context.py    # begin_task(), end_task(), get_task_context() + ContextVar
```

No other new files. All changes are extensions to existing files:
- `memory/qdrant_store.py` — `_ensure_collection()`, `search()`, `search_with_lifecycle()`
- `memory/embeddings.py` — `add_entry()`, `_search_qdrant()`
- `memory/store.py` — `build_context_semantic()`
- `tests/test_task_context.py` — new test file

### Pattern 1: TaskType Enum Definition

The canonical location is `core/task_types.py`. The values must match the CONTEXT.md decision: `coding, debugging, research, content, strategy, app_create, marketing, general`.

**Critical discovery:** `dashboard/server.py` line 72 already defines a `TaskType` enum with different values (`CODING, CONTENT, RESEARCH, EMAIL, MARKETING, DEBUG, REVIEW, PLANNING, PROJECT_SETUP, APP_CREATE, APP_UPDATE`). This is a local stub from the v2.0 pivot. The new `core/task_types.py` enum is a separate canonical definition that does NOT need to replace the dashboard stub in this phase — they serve different purposes (the dashboard enum drives UI task creation; the new enum drives memory tagging). The planner should NOT task the implementer with migrating the dashboard enum.

**Also:** `from core.task_queue import TaskType` appears in `agents/agent_routing_store.py` and several test files. `core/task_queue.py` does not exist as a file — this import is a dead reference from the v2.0 migration. The new `core/task_types.py` is a clean new module; updating dead imports is out of scope for Phase 20.

### Pattern 2: ContextVar Lifecycle

Verified behavior (Python stdlib, executed):
- `ContextVar.set()` returns a `Token` for reverting
- `ContextVar.reset(token)` reverts to prior value (used in `end_task()`)
- `asyncio.create_task()` **copies** the current context — child tasks automatically inherit `task_id` and `task_type`
- No locking needed; ContextVar is per-asyncio-task, not global

```python
# core/task_context.py
import contextvars
import uuid
from core.task_types import TaskType

_task_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("task_id", default=None)
_task_type_var: contextvars.ContextVar[TaskType | None] = contextvars.ContextVar("task_type", default=None)

class _TaskContext:
    """Holds reset tokens for end_task() cleanup."""
    def __init__(self, id_token, type_token, task_id: str):
        self._id_token = id_token
        self._type_token = type_token
        self.task_id = task_id

def begin_task(task_type: TaskType) -> _TaskContext:
    task_id = str(uuid.uuid4())
    id_token = _task_id_var.set(task_id)
    type_token = _task_type_var.set(task_type)
    return _TaskContext(id_token, type_token, task_id)

def end_task(ctx: _TaskContext) -> None:
    _task_id_var.reset(ctx._id_token)
    _task_type_var.reset(ctx._type_token)

def get_task_context() -> tuple[str | None, TaskType | None]:
    """Read current task_id and task_type. Returns (None, None) outside any task."""
    return _task_id_var.get(), _task_type_var.get()
```

### Pattern 3: Payload Injection at add_entry()

`EmbeddingStore.add_entry()` already accepts `metadata: dict`. Task fields are injected by reading the ContextVar:

```python
# memory/embeddings.py — modify add_entry()
async def add_entry(
    self, text: str, source: str = "", section: str = "", metadata: dict | None = None
):
    from core.task_context import get_task_context
    task_id, task_type = get_task_context()
    effective_metadata = dict(metadata or {})
    if task_id is not None:
        effective_metadata["task_id"] = task_id
    if task_type is not None:
        effective_metadata["task_type"] = task_type.value  # store string, not enum
    # ... rest of existing method unchanged
```

The same pattern applies to `index_history_entry()` — that method builds a payload dict directly for `upsert_single()`.

### Pattern 4: Qdrant Payload Indexes

`create_payload_index()` signature verified against installed qdrant-client:
```
create_payload_index(
    collection_name: str,
    field_name: str,
    field_schema: PayloadSchemaType | ... | None = None,
    ...
) -> UpdateResult
```

Call in `_ensure_collection()` after `create_collection()`:
```python
# memory/qdrant_store.py — add to _ensure_collection() for MEMORY and HISTORY
from qdrant_client.models import PayloadSchemaType

if suffix in (self.MEMORY, self.HISTORY):
    try:
        self._client.create_payload_index(name, "task_type", PayloadSchemaType.KEYWORD)
        self._client.create_payload_index(name, "task_id", PayloadSchemaType.KEYWORD)
    except Exception as e:
        logger.warning("Qdrant: payload index creation failed (non-critical): %s", e)
```

Note: `create_payload_index()` is idempotent on existing collections — calling it when the index already exists does not raise an error. This means existing deployed collections will get indexes on next restart.

### Pattern 5: Filter Extension in QdrantStore.search()

Follows the existing `source_filter`/`channel_filter` pattern exactly:

```python
def search(
    self,
    collection_suffix: str,
    query_vector: list[float],
    top_k: int = 5,
    source_filter: str = "",
    channel_filter: str = "",
    time_after: float = 0.0,
    task_type_filter: str = "",   # new
    task_id_filter: str = "",     # new
) -> list[dict]:
    ...
    if task_type_filter:
        conditions.append(FieldCondition(key="task_type", match=MatchValue(value=task_type_filter)))
    if task_id_filter:
        conditions.append(FieldCondition(key="task_id", match=MatchValue(value=task_id_filter)))
```

`search_with_lifecycle()` gets the same two parameters with identical filter construction.

### Pattern 6: EmbeddingStore.search() Extension

`EmbeddingStore.search()` already has `source_filter: str = ""`. Add `task_type_filter: str = ""` and pass through to `_search_qdrant()`:

```python
async def search(
    self, query: str, top_k: int = 5, source_filter: str = "", collection: str = "",
    task_type_filter: str = ""  # new
) -> list[dict]:
```

`_search_qdrant()` also needs the parameter to pass to `self._qdrant.search()`.

### Pattern 7: MemoryStore.build_context_semantic() Extension

`build_context_semantic()` at line 380 of `memory/store.py` calls `self.embeddings.search(query, top_k=top_k)`. To satisfy RETR-02, it needs a `task_type` parameter:

```python
async def build_context_semantic(
    self, query: str, top_k: int = 5, max_memory_lines: int = 50,
    task_type: str = ""  # new
) -> str:
    ...
    results = await self.embeddings.search(query, top_k=top_k, task_type_filter=task_type)
```

The `task_type` parameter is a plain string (not `TaskType` enum) at this interface boundary — callers pass `task_type.value` or `""`. This avoids a circular import between `memory/` and `core/`.

### Anti-Patterns to Avoid

- **Storing TaskType enum instance in Qdrant payload:** Qdrant payloads are JSON-serialized. Always store `task_type.value` (string) not the enum object.
- **Blocking ContextVar reads in sync code:** `get_task_context()` is a sync function (ContextVar read is synchronous). No await needed.
- **Adding task_type field to CONVERSATIONS or KNOWLEDGE collections:** CONTEXT.md decision: indexes apply to MEMORY and HISTORY only. No change to the other two.
- **Raising on missing task context:** Outside `begin_task()` / `end_task()`, both vars return `None`. Memory writes proceed without task fields — this is expected behavior for conversational/tool writes outside task dispatch.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Task ID generation | UUID v4 manual implementation | `str(uuid.uuid4())` | Already in stdlib; already imported in qdrant_store.py |
| Context propagation | Thread-locals, explicit param passing | `contextvars.ContextVar` | asyncio-native, automatic child task inheritance |
| Payload indexing | Manual field-based filtering in Python | Qdrant `create_payload_index` + `FieldCondition` | Already in project; server-side filtering at 50ms for 100K points |

**Key insight:** Every building block already exists in the project. This phase is pure extension, not new infrastructure.

---

## Common Pitfalls

### Pitfall 1: TaskType enum duplication
**What goes wrong:** `dashboard/server.py` line 72 already defines `class TaskType` with different values. The implementer might try to import from there or refactor it.
**Why it happens:** The name collision is invisible until you look at both files.
**How to avoid:** Create `core/task_types.py` as the new canonical source. Leave `dashboard/server.py` untouched. The dashboard enum is a stub for UI task creation; the new enum is for memory tagging. They can coexist in this phase.
**Warning signs:** If an import from `dashboard.server` appears in memory code, something went wrong.

### Pitfall 2: Dead import of core.task_queue
**What goes wrong:** `agents/agent_routing_store.py` and test files import `from core.task_queue import TaskType`. `core/task_queue.py` does not exist. This will cause `ImportError` if those files are imported in tests.
**Why it happens:** Leftover from v2.0 MCP pivot; `core/task_queue` was deleted.
**How to avoid:** The new module is `core/task_types.py`, not `core/task_queue.py`. Do NOT create `core/task_queue.py` to fix this. The broken imports are pre-existing; fixing them is out of Phase 20 scope. Test files that reference `core.task_queue` are in the disabled `_DisabledScopeTracking` class — they don't run.
**Warning signs:** If a test run starts failing on `ImportError: core.task_queue`, the fix is to update just that import, not to recreate the old module.

### Pitfall 3: Index creation on existing collections
**What goes wrong:** `_ensure_collection()` uses `self._initialized_collections` to skip collections already seen in the session. On an upgrade scenario (server restart with existing data), a collection may already exist but have no payload indexes.
**Why it happens:** `_initialized_collections` is a session-level cache, not persistent.
**How to avoid:** `create_payload_index()` is idempotent — call it even when the collection already exists. The fix: create indexes both in the new-collection branch AND after loading existing collections. Alternatively, call `create_payload_index()` unconditionally whenever `_ensure_collection()` runs for MEMORY/HISTORY (the `if suffix in (self.MEMORY, self.HISTORY)` guard handles the collection check). Wrap in try/except since failure is non-fatal.

### Pitfall 4: EmbeddingStore.add_entry() doesn't write to Qdrant directly
**What goes wrong:** `add_entry()` at line 371 of `memory/embeddings.py` writes to the JSON store only — it doesn't call `_qdrant.upsert_single()`. The Qdrant path in the write chain is through `index_memory()` and `index_history_entry()`. Task fields added to `add_entry()` only reach Qdrant if those higher-level indexing methods are used.
**Why it happens:** The JSON and Qdrant paths are separate in the write flow.
**How to avoid:** Task field injection needs to happen at both `add_entry()` (for the JSON fallback path) AND in `index_history_entry()` (for the Qdrant path). Read `add_entry()` at line 371 and `index_history_entry()` at line 539 before implementing.

### Pitfall 5: Circular import between core/ and memory/
**What goes wrong:** If `memory/embeddings.py` imports `from core.task_context import get_task_context` and `core/task_context.py` imports from `memory/`, a circular import results.
**Why it happens:** `core/` and `memory/` are peer packages; the existing code uses late `from memory.qdrant_store import QdrantStore` imports inside methods precisely to avoid circularity.
**How to avoid:** `core/task_context.py` must NOT import from `memory/`. The import direction is memory → core (one-way). `from core.task_context import get_task_context` inside `memory/embeddings.py` methods is safe.

### Pitfall 6: search_with_lifecycle() filter construction complexity
**What goes wrong:** `search_with_lifecycle()` has complex nested filter logic for `project_filter`/`exclude_forgotten` that modifies `forgotten_filter` in-place. Adding `task_type_filter` by appending to `conditions` before the complex block may be ignored (conditions list is used only when `forgotten_filter is None`).
**Why it happens:** The filter assembly in `search_with_lifecycle()` has two separate code paths — the `conditions` list and the `forgotten_filter` object — and they don't merge cleanly.
**How to avoid:** Read `search_with_lifecycle()` lines 500-560 carefully before extending it. The safest approach: after the `forgotten_filter` is fully assembled, append task_type/task_id conditions to `forgotten_filter.must` (or create a new `Filter(must=[...])` that combines `forgotten_filter` and task conditions).

---

## Code Examples

Verified patterns from official sources and codebase inspection:

### Payload Index Creation (verified against installed qdrant-client)
```python
# Source: qdrant_client.QdrantClient.create_payload_index (verified via inspect.signature)
from qdrant_client.models import PayloadSchemaType

self._client.create_payload_index(
    collection_name=name,
    field_name="task_type",
    field_schema=PayloadSchemaType.KEYWORD,  # Low cardinality string
)
self._client.create_payload_index(
    collection_name=name,
    field_name="task_id",
    field_schema=PayloadSchemaType.KEYWORD,  # UUID stored as keyword string
)
```

### ContextVar Lifecycle (verified by execution)
```python
# Verified: parent sets, child task inherits, reset reverts
import contextvars, uuid

_task_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("task_id", default=None)

# In begin_task():
token = _task_id_var.set(str(uuid.uuid4()))
# Returns token for reset

# In end_task():
_task_id_var.reset(token)  # Reverts to previous value (None if no nesting)

# asyncio.create_task() copies context — child inherits without any extra code
```

### Existing Filter Pattern (from QdrantStore.search() lines 274-284)
```python
# Source: memory/qdrant_store.py lines 274-284
conditions = []
if source_filter:
    conditions.append(FieldCondition(key="source", match=MatchValue(value=source_filter)))
if channel_filter:
    conditions.append(FieldCondition(key="channel_type", match=MatchValue(value=channel_filter)))
# Extend identically:
if task_type_filter:
    conditions.append(FieldCondition(key="task_type", match=MatchValue(value=task_type_filter)))
query_filter = Filter(must=conditions) if conditions else None
```

### MemoryTool store path (existing, shows where task context injection lands)
```python
# Source: tools/memory_tool.py lines 244-264
# log_event_semantic() → index_history_entry() → upsert_single()
await self._store.log_event_semantic(
    event_type="memory",
    summary=f"[{section}] {content}",
    details=content,
)
# Task fields injected via ContextVar at index_history_entry() level
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `from core.task_queue import TaskType` (broken) | New `core/task_types.py` | Phase 20 | Provides a real module for the enum |
| No task provenance in memory | `task_id`/`task_type` in Qdrant payload | Phase 20 | Enables downstream filtered retrieval (Phases 21-23) |
| No payload indexes | `create_payload_index()` on MEMORY/HISTORY | Phase 20 | Filtered queries avoid full collection scan |

**Deprecated/outdated:**
- `from core.task_queue import TaskType`: This import pattern exists in `agents/agent_routing_store.py` and disabled test code. It is broken (module doesn't exist) but doesn't affect running tests because it's only in dead code paths. Phase 20 does not fix these.

---

## Open Questions

1. **`search_with_lifecycle()` filter assembly**
   - What we know: The method has complex nested filter logic that doesn't use the simple `conditions` list for the `exclude_forgotten`/`project_filter` path (lines 500-560)
   - What's unclear: The cleanest way to add task_type/task_id conditions without breaking the existing must_not/should logic
   - Recommendation: Read lines 500-560 carefully. Approach: build conditions list first, then merge into `forgotten_filter.must` after the full forgotten/project filter is assembled. Use `forgotten_filter.must = (forgotten_filter.must or []) + task_conditions`.

2. **`begin_task()` call site in agent dispatch**
   - What we know: CONTEXT.md says the agent dispatch loop calls `begin_task()` / `end_task()`. The project no longer has an `Agent._process_task()` method (MCP pivot removed it). The dispatch happens via dashboard/server.py task creation and agent_manager.py.
   - What's unclear: The exact entry point for `begin_task()` call — there's no single `Agent` class with a `_process_task()` method in the current codebase.
   - Recommendation: The planner should scope the `begin_task()` integration narrowly — add it to whatever the current task dispatch entry point is in `core/agent_manager.py` or agent runtime. This may be a `run_agent()` or similar function. Check `core/agent_manager.py` and `core/agent_runtime.py` before planning this task.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.x with pytest-asyncio |
| Config file | `pyproject.toml` — `asyncio_mode = "auto"`, testpaths = ["tests"] |
| Quick run command | `python -m pytest tests/test_task_context.py tests/test_memory.py -x -q` |
| Full suite command | `python -m pytest tests/ -x -q` |

Current baseline: 161 passed, 1 unrelated failure (venv creation timeout in `test_app_manager.py::TestEnsureAppVenv::test_idempotent_when_venv_exists`).

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| TMETA-01 | Memory entry includes `task_id`/`task_type` in Qdrant payload after `begin_task()` | unit | `pytest tests/test_task_context.py::TestPayloadInjection -x` | ❌ Wave 0 |
| TMETA-02 | Existing entries without task fields returned by unfiltered search | unit | `pytest tests/test_task_context.py::TestBackwardCompat -x` | ❌ Wave 0 |
| TMETA-03 | Qdrant payload indexes exist on `task_type` and `task_id` in MEMORY/HISTORY | unit | `pytest tests/test_task_context.py::TestPayloadIndexes -x` | ❌ Wave 0 |
| TMETA-04 | `begin_task()` sets context so all subsequent writes inherit task fields | unit | `pytest tests/test_task_context.py::TestLifecycle -x` | ❌ Wave 0 |
| RETR-01 | `search_with_lifecycle()` with `task_type_filter="coding"` returns only coding entries | unit | `pytest tests/test_task_context.py::TestFilteredSearch -x` | ❌ Wave 0 |
| RETR-02 | `build_context_semantic()` passes task_type through to filtered search | unit | `pytest tests/test_task_context.py::TestBuildContextSemantic -x` | ❌ Wave 0 |

All tests for this phase live in a single new file `tests/test_task_context.py`. Unit tests mock Qdrant (using MagicMock patterns from existing `tests/test_memory.py`) — no live Qdrant connection required.

### Sampling Rate
- **Per task commit:** `python -m pytest tests/test_task_context.py tests/test_memory.py -x -q`
- **Per wave merge:** `python -m pytest tests/ -x -q` (skip slow/integration markers)
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_task_context.py` — covers all 6 phase requirements (TMETA-01 through RETR-02)
- [ ] No framework install needed — pytest + pytest-asyncio already installed

---

## Sources

### Primary (HIGH confidence)
- Codebase direct inspection — `memory/qdrant_store.py`, `memory/embeddings.py`, `memory/store.py`, `tools/memory_tool.py`, `dashboard/server.py`, `tests/test_memory.py`, `tests/conftest.py`
- Python stdlib docs — `contextvars.ContextVar` (verified by execution in project venv)
- `qdrant-client` installed package — `create_payload_index()` signature verified via `inspect.signature()`; `PayloadSchemaType.KEYWORD` value verified

### Secondary (MEDIUM confidence)
- Qdrant documentation (behavior of payload indexes on existing collections) — `create_payload_index()` is idempotent per API design; applied when collection already exists, indexes are added without error

### Tertiary (LOW confidence)
- None

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — stdlib + already-installed qdrant-client, verified by execution
- Architecture: HIGH — all patterns are direct extensions of existing code, verified by codebase read
- Pitfalls: HIGH — discovered from direct code inspection (TaskType duplication, filter assembly complexity, add_entry Qdrant path)

**Research date:** 2026-03-17
**Valid until:** 2026-04-17 (stable Python stdlib + qdrant-client patterns)
