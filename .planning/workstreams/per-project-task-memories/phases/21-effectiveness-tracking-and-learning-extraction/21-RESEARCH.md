# Phase 21: Effectiveness Tracking and Learning Extraction - Research

**Researched:** 2026-03-17
**Domain:** Async SQLite telemetry, LLM-based extraction with instructor, Qdrant quarantine
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Tracking granularity**
- Minimal schema per tool invocation: tool_name, task_type, task_id, success (bool), duration_ms, timestamp
- Track ALL tools — both built-in (ToolRegistry) and MCP tools (from external servers)
- Success determined by `ToolResult.success` field; for MCP tools, non-error responses count as success
- Instrumentation point: ToolRegistry wrapper — single hook wraps all tool execution, times it, and fires off the record
- Fire-and-forget via `asyncio.create_task()` — tool call returns before any SQLite write is awaited

**Learning extraction**
- LLM-based extraction using `instructor` library + Pydantic schema
- LLM called via Agent42's provider router (uses existing tiered routing: Synthetic API, Gemini Flash, etc.)
- New Stop hook (separate from existing learning-engine.py and memory-learn.py — all three are complementary)
- Skip extraction for trivial sessions (<2 tool calls or <1 file modification)
- Extracted learning written to HISTORY.md in `[task_type][task_id][outcome]` format
- Extracted learning also indexed in Qdrant with task_id and task_type payload fields

**SQLite store design**
- File location: `.agent42/effectiveness.db` (alongside existing Qdrant storage, already gitignored)
- Module: `memory/effectiveness.py` (EffectivenessStore class)
- No retention/cleanup policy — keep all records (even 100K rows is <10MB)
- Async writes via `asyncio.create_task()` — same pattern as `store.py` recall recording
- New dependency: `aiosqlite`
- Graceful degradation: if SQLite DB is missing or unwritable, tool execution continues normally (EFFT-05)

**Quarantine mechanics**
- Observations counted by same-outcome tasks: a learning gets +1 when a later task of the same type produces a similar outcome
- Requires 3 independent task confirmations before quarantine lifts (LEARN-04)
- Quarantine state stored in Qdrant payload: `observation_count` and `confidence` fields on the learning entry
- Quarantined learnings have confidence capped at 0.6 — filtered out by downstream consumers that require higher confidence
- Once observation_count >= threshold: confidence unlocks to 1.0, normal lifecycle scoring takes over (decay, recall boosts)
- Config-driven: `LEARNING_MIN_EVIDENCE=3` and `LEARNING_QUARANTINE_CONFIDENCE=0.6` in .env (tunable without code changes)

### Claude's Discretion
- Exact instructor Pydantic schema for learning extraction
- EffectivenessStore table DDL beyond the agreed columns
- ToolRegistry wrapper implementation details (decorator vs middleware pattern)
- How to detect "similar outcome" for observation counting
- Stop hook implementation structure (standalone module vs integrated into existing hook)

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| EFFT-01 | EffectivenessStore (SQLite) records tool_name, task_type, success, duration_ms, task_id per invocation | aiosqlite DDL/upsert pattern; `get_task_context()` provides task_id + task_type |
| EFFT-02 | Tool outcome recording is async-buffered (no latency on tool execution hot path) | `asyncio.create_task()` fire-and-forget pattern from `store.py._record_recalls()`; ToolRegistry.execute() is the wrap point |
| EFFT-03 | MCP tool usage tracked via PostToolUse hook or MCPRegistryAdapter wrapper | Claude Code PostToolUse hook receives `tool_name` and `tool_output.is_error`; can call HTTP endpoint on Agent42 |
| EFFT-04 | Effectiveness aggregation query returns success_rate, avg_duration by tool+task_type pair | SQLite GROUP BY query; no ORM needed |
| EFFT-05 | Graceful degradation — agent continues without crashing if SQLite is unavailable | try/except around entire `_write_record()` coroutine; log warning, never raise |
| LEARN-01 | Stop hook auto-extracts task summary, outcome, tools used, files modified | Hook protocol (JSON stdin, stderr feedback, exit 0); `instructor` + `openai.AsyncOpenAI` for structured extraction |
| LEARN-02 | Extracted learnings written to HISTORY.md with `[task_type][task_id][outcome]` format | `MemoryStore.log_event_semantic()` — already writes to HISTORY.md AND indexes in Qdrant |
| LEARN-03 | Extracted learnings indexed in Qdrant with task_id and task_type payload fields | `EmbeddingStore.index_history_entry()` with task context active picks up task fields from `get_task_context()` |
| LEARN-04 | Learning entries have quarantine period (confidence capped at 0.6 until >= 3 observations) | Qdrant payload fields `observation_count` and `confidence`; `QdrantStore.update_payload()` for increment |
| LEARN-05 | No mid-task memory writes (only after task completion with known outcome) | Stop hook only fires after Claude ends the session; EffectivenessStore accumulates records during task, flush at end |
</phase_requirements>

---

## Summary

Phase 21 builds two complementary systems on top of Phase 20's task metadata foundation. The first is an **EffectivenessStore** — an `aiosqlite`-backed SQLite database that records every tool invocation with timing and success data, writing asynchronously via `asyncio.create_task()` so the hot path is never blocked. The instrumentation point is `ToolRegistry.execute()`, which is the single call site for all built-in tools. MCP tools (invoked by Claude Code itself via PostToolUse hook) require a separate thin HTTP-callback path. The second system is a **learning extraction pipeline** triggered by a new Stop hook that calls `instructor`-structured LLM extraction to convert session data into a durable HISTORY.md entry, then indexes it in Qdrant with quarantine fields (`observation_count`, `confidence`) to prevent premature recall.

The codebase already provides all essential patterns. `asyncio.create_task()` fire-and-forget is used in `store.py._record_recalls()` and `_schedule_reindex()`. `MemoryStore.log_event_semantic()` already writes to HISTORY.md and indexes in Qdrant in one call. `get_task_context()` returns `(task_id, task_type_str)` from contextvars, ready for Phase 21 consumers. The `instructor` library and `aiosqlite` are the only new dependencies — neither is in `requirements.txt` or installed in the venv yet. Both must be added.

The quarantine mechanism relies on Qdrant payload fields rather than a separate data store. When a learning entry is created, it gets `observation_count=1` and `confidence=0.6`. Each time a subsequent task of the same type with a similar outcome completes, a separate coroutine increments `observation_count`. Once `>= LEARNING_MIN_EVIDENCE` (default 3), confidence is unlocked to 1.0. This keeps the quarantine state co-located with the learning entry and requires no new storage.

**Primary recommendation:** Add `aiosqlite` and `instructor` to requirements.txt, wrap `ToolRegistry.execute()` with a timing/success recorder that fires a background task, build `memory/effectiveness.py` following the graceful-degradation pattern already in `memory/qdrant_store.py`, and implement the Stop hook following the exact protocol of the existing `learning-engine.py` hook.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `aiosqlite` | `>=0.20.0` | Async wrapper around Python's stdlib `sqlite3` | Zero extra C dependencies; fits async-first codebase; graceful degradation to sync sqlite3 if needed; ~50KB |
| `instructor` | `>=1.3.0` | Structured LLM output via Pydantic models | Wraps `openai.AsyncOpenAI` with automatic retry + validation; project already depends on `openai` |
| `asyncio` (stdlib) | Python 3.11 | `create_task()` fire-and-forget | Already used throughout codebase for non-blocking background writes |
| `sqlite3` (stdlib) | Python 3.11 | Underlying DB engine | No server needed; `.agent42/effectiveness.db` is gitignored already |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `openai` | `>=1.40.0` (already in requirements) | Provider for instructor calls | LLM extraction in Stop hook; existing dep, no new install |
| `pydantic` | `>=2.0` (transitively installed via openai/fastapi) | Schema for extracted learning | instructor requires Pydantic v2 models |
| `time` (stdlib) | — | `time.perf_counter_ns()` for sub-ms timing | Monotonic clock, no drift; better than `time.time()` for duration measurement |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `aiosqlite` | `databases` library | `databases` has more overhead; `aiosqlite` is minimal and purpose-built |
| `instructor` | Raw JSON mode + manual parsing | Instructor handles retry, validation, and model switching; no hand-rolled schema enforcement |
| SQLite | PostgreSQL/Redis for telemetry | Overkill; 100K rows <10MB; no server dependency |
| Stop hook for extraction | Always-on periodic job | Hook-per-session is simpler, zero idle cost; periodic job adds complexity for infrequent data |

**Installation:**
```bash
pip install aiosqlite>=0.20.0 instructor>=1.3.0
```

---

## Architecture Patterns

### Recommended Project Structure
```
memory/
├── effectiveness.py      # NEW: EffectivenessStore (SQLite, async)
├── store.py              # Existing: HISTORY.md + Qdrant writes (extend for LEARN-02/03)
├── embeddings.py         # Existing: Qdrant/ONNX indexing
└── qdrant_store.py       # Existing: update_payload() for quarantine increment

tools/
└── registry.py           # Modify execute() to wrap with timing + fire-and-forget record

.claude/hooks/
└── effectiveness-learn.py  # NEW: Stop hook for LLM extraction
```

### Pattern 1: ToolRegistry Execution Wrapper (EFFT-01, EFFT-02)

**What:** Wrap `ToolRegistry.execute()` to record timing and fire a background write.
**When to use:** This is the single instrumentation point for ALL built-in tool calls.

The wrapper must:
1. Record `start = time.perf_counter_ns()` before delegating
2. Call existing logic (rate limit, dispatch to `tool.execute()`)
3. Compute `duration_ms = (time.perf_counter_ns() - start) / 1_000_000`
4. Fire `asyncio.create_task(_write_record(...))` — does NOT await
5. Return the result immediately

```python
# In tools/registry.py ToolRegistry.execute()
# Source: existing _record_recalls() fire-and-forget in memory/store.py

async def execute(self, tool_name: str, agent_id: str = "default", **kwargs) -> ToolResult:
    start_ns = time.perf_counter_ns()
    # ... existing rate limit and dispatch logic ...
    result = await tool.execute(**kwargs)
    duration_ms = (time.perf_counter_ns() - start_ns) / 1_000_000

    if self._effectiveness_store:
        try:
            task_id, task_type = get_task_context()
            loop = asyncio.get_running_loop()
            loop.create_task(
                self._effectiveness_store.record(
                    tool_name=tool_name,
                    task_type=task_type or "general",
                    task_id=task_id or "",
                    success=result.success,
                    duration_ms=duration_ms,
                )
            )
        except Exception:
            pass  # Never block tool execution for tracking

    return result
```

Key: `asyncio.get_running_loop().create_task()` is used (not `asyncio.create_task()`) to avoid the deprecation warning in Python 3.10+ when called outside an async context. However since `execute()` is `async`, `asyncio.create_task()` works fine here.

### Pattern 2: EffectivenessStore Graceful Degradation (EFFT-05)

**What:** Wrap the entire `_write_record()` coroutine in try/except; never propagate exceptions.
**When to use:** Always. The store must silently degrade if `.agent42/` is not writable.

```python
# In memory/effectiveness.py
# Source: graceful degradation pattern from memory/qdrant_store.py

class EffectivenessStore:
    def __init__(self, db_path: str | Path):
        self._db_path = Path(db_path)
        self._available: bool | None = None  # None = untested

    async def record(self, tool_name: str, task_type: str, task_id: str,
                     success: bool, duration_ms: float) -> None:
        """Write one effectiveness record. Never raises."""
        try:
            await self._ensure_db()
            async with aiosqlite.connect(self._db_path) as db:
                await db.execute(
                    """INSERT INTO tool_invocations
                       (tool_name, task_type, task_id, success, duration_ms, ts)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (tool_name, task_type, task_id, int(success),
                     duration_ms, time.time())
                )
                await db.commit()
            self._available = True
        except Exception as e:
            self._available = False
            logger.warning("EffectivenessStore write failed (non-critical): %s", e)

    async def _ensure_db(self) -> None:
        """Create the DB file and table if they don't exist."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS tool_invocations (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    tool_name TEXT    NOT NULL,
                    task_type TEXT    NOT NULL,
                    task_id   TEXT    NOT NULL,
                    success   INTEGER NOT NULL,
                    duration_ms REAL  NOT NULL,
                    ts        REAL    NOT NULL
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_tool_task "
                "ON tool_invocations (tool_name, task_type)"
            )
            await db.commit()
```

### Pattern 3: MCP Tool Tracking via PostToolUse Hook (EFFT-03)

**What:** A `PostToolUse` hook that fires when Claude Code calls any tool (including Agent42 MCP tools). Sends a lightweight HTTP call to Agent42's dashboard API to log the invocation.
**When to use:** For tools invoked via Claude Code's MCP connection, which bypass `ToolRegistry.execute()`.

The hook reads `tool_name` and `tool_output.is_error` from the event JSON, then POSTs to Agent42's HTTP API. This is the same pattern as `memory-learn.py` calling `AGENT42_SEARCH_URL`. A dedicated endpoint `/api/effectiveness/record` accepts the payload.

Alternative approach (from CONTEXT.md): MCPRegistryAdapter wrapper inside `mcp_server.py` that wraps `call_tool()`. This is simpler since MCP server is already instrumented — no HTTP call needed. Either approach satisfies EFFT-03.

### Pattern 4: Learning Extraction Stop Hook (LEARN-01 through LEARN-03)

**What:** A new Stop hook (`effectiveness-learn.py`) that fires after every Claude Code session. Uses `instructor` to extract structured learnings from session data.
**When to use:** All Stop events, but skip trivial sessions early.

```python
# .claude/hooks/effectiveness-learn.py
# Source: existing hook protocol from learning-engine.py and memory-learn.py

import instructor
from openai import AsyncOpenAI
from pydantic import BaseModel

class ExtractedLearning(BaseModel):
    task_type: str           # One of: coding, debugging, research, etc.
    task_id: str             # From event metadata or generated
    outcome: str             # "success" | "failure" | "partial"
    summary: str             # 1-2 sentence description
    tools_used: list[str]
    files_modified: list[str]
    key_insight: str         # The durable learning — what to remember

# Trivial session guard (LEARN-05: no mid-task writes; also skip noise)
tool_calls = [t for t in event.get("tool_uses", [])]
files = [t for t in tool_calls if t.get("tool_name") in ("Write", "Edit")]
if len(tool_calls) < 2 or len(files) < 1:
    sys.exit(0)  # Skip extraction for trivial sessions

# instructor call (async, called via asyncio.run())
client = instructor.from_openai(AsyncOpenAI(api_key=api_key, base_url=base_url))
learning = await client.chat.completions.create(
    model="gemini-2-flash",
    response_model=ExtractedLearning,
    messages=[{"role": "user", "content": prompt}]
)
```

The hook then calls Agent42's HTTP API to:
1. Write to HISTORY.md via `MemoryStore.log_event_semantic()` (LEARN-02)
2. Index in Qdrant with quarantine fields (LEARN-03, LEARN-04)

Because hooks are standalone Python scripts without access to Agent42's internal objects, they call the running Agent42 HTTP API (same pattern as `memory-learn.py` using `AGENT42_SEARCH_URL`). Agent42 exposes a `/api/effectiveness/learn` endpoint.

### Pattern 5: Quarantine via Qdrant Payload (LEARN-04)

**What:** Store quarantine state (`observation_count`, `confidence`) in the Qdrant payload alongside existing lifecycle fields.
**When to use:** When creating any new learning entry; when a matching subsequent task completes.

On creation: payload includes `{"observation_count": 1, "confidence": 0.6, "quarantined": true}`.

On subsequent matching task: call `QdrantStore.update_payload()` with incremented `observation_count`. When `>= LEARNING_MIN_EVIDENCE`, also set `confidence = 1.0` and `quarantined = false`.

"Similar outcome" detection for observation counting:
- Same `task_type` (exact match on payload field)
- Same `outcome` label (success/failure) as returned by `ExtractedLearning.outcome`
- Semantic similarity >= 0.70 between the new summary and existing quarantined entries
- This avoids false matches from different problem domains with the same task type

```python
# In memory/qdrant_store.py or a new method on EmbeddingStore
# Source: existing QdrantStore.update_payload() pattern

async def maybe_promote_quarantined(self, task_type: str, outcome: str,
                                     summary_vector: list[float]) -> int:
    """Increment observation_count on matching quarantined learnings.
    Returns number of entries promoted (observation_count reached threshold).
    """
    threshold = int(os.getenv("LEARNING_MIN_EVIDENCE", "3"))
    quarantine_conf = float(os.getenv("LEARNING_QUARANTINE_CONFIDENCE", "0.6"))

    # Search for quarantined entries of same task_type
    results = self.search_with_lifecycle(
        QdrantStore.HISTORY, summary_vector, top_k=5,
        task_type_filter=task_type
    )
    promoted = 0
    for r in results:
        payload = r.get("payload", {})
        if not payload.get("quarantined"):
            continue
        if payload.get("outcome") != outcome:
            continue
        if r.get("score", 0) < 0.70:
            continue
        new_count = payload.get("observation_count", 1) + 1
        updates = {"observation_count": new_count}
        if new_count >= threshold:
            updates["confidence"] = 1.0
            updates["quarantined"] = False
            promoted += 1
        self.update_payload(QdrantStore.HISTORY, r["point_id"], updates)
    return promoted
```

### Anti-Patterns to Avoid

- **Awaiting the SQLite write inside `execute()`:** This adds 3-15ms per tool call, violating EFFT-02. Always use `create_task()`.
- **Calling `asyncio.run()` inside an already-running event loop:** The hook is a subprocess; use `asyncio.run()` at the top level. Inside async code in Agent42, use `await`.
- **Storing quarantine state in a separate table/dict:** Qdrant payload is the source of truth for memory lifecycle. Quarantine in a separate store creates split-brain state.
- **Raising exceptions from `EffectivenessStore.record()`:** Any unhandled exception in a `create_task()` coroutine is silently discarded by Python unless explicitly awaited. Log it in the store, but don't re-raise.
- **Running instructor extraction on every Stop event:** This costs 2-5s + tokens. The trivial session guard (`< 2 tool calls or < 1 file modification`) must run before any LLM call.
- **Using `asyncio.create_task()` outside async context for `_schedule_reindex`-style pattern:** `ToolRegistry.execute()` is already async, so `asyncio.create_task()` works fine without `get_running_loop()`.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Structured LLM output | Custom JSON parsing + retry loop | `instructor` library | Handles schema validation, automatic retry on malformed output, provider switching |
| Async SQLite I/O | Thread pool executor + `sqlite3` | `aiosqlite` | Thin, correct wrapper; avoids executor overhead; same API as `sqlite3` |
| Task context propagation | Thread-local or global variable | `contextvars.ContextVar` (already in `core/task_context.py`) | ContextVar copies to asyncio child tasks automatically; thread-local doesn't |
| Confidence/lifecycle fields | Separate metadata table | Qdrant payload fields | Already has `update_payload()`, `search_with_lifecycle()` uses payload; co-located with learning |
| LLM provider routing | Direct API key selection | Agent42's provider router / `ModelRouter` | Handles Synthetic API, Gemini Flash, rate limit fallback — already built |

**Key insight:** The project has all the right infrastructure (async I/O, Qdrant lifecycle, task context); Phase 21 wires them together rather than building new primitives.

---

## Common Pitfalls

### Pitfall 1: Task Context Not Active in Stop Hook
**What goes wrong:** `get_task_context()` returns `(None, None)` inside the Stop hook because contextvars don't persist across process boundaries.
**Why it happens:** Stop hook is a separate Python process. Contextvars are in-process only.
**How to avoid:** The Stop hook extracts `task_id` and `task_type` from the session event JSON (the event's `messages`, `tool_uses`, or a custom field injected by Agent42). The hook does NOT call `get_task_context()` — it reads from the event data.
**Warning signs:** All HISTORY.md entries written by the hook have empty task_type.

### Pitfall 2: `asyncio.create_task()` Silently Swallows Exceptions
**What goes wrong:** A bug in `_write_record()` is never surfaced — the task runs but its exception is garbage-collected.
**Why it happens:** Python does not log unhandled exceptions from `create_task()` coroutines by default in production (it does print a warning in some versions).
**How to avoid:** Wrap the entire coroutine body in `try/except Exception as e: logger.warning(...)`. The graceful degradation is intentional but the warning log is essential for diagnosability.
**Warning signs:** `effectiveness.db` file is never created, but no errors appear.

### Pitfall 3: aiosqlite Connection Per Write
**What goes wrong:** Overhead from opening/closing a new SQLite connection on every record (could be 50+ per task).
**Why it happens:** aiosqlite's `connect()` is a context manager that opens and closes the file on each use.
**How to avoid:** Keep a persistent connection via `aiosqlite.connect()` stored on the `EffectivenessStore` instance — OR accept the overhead since it's fire-and-forget (connection open is ~0.3ms, fully async, never blocks the tool path). Given the fire-and-forget design, per-write connections are acceptable for simplicity. A persistent connection requires lifecycle management (open on first use, close on shutdown).
**Warning signs:** `lsof` shows many file handles to `effectiveness.db`.

### Pitfall 4: instructor Schema Validation Failure Crashes Hook
**What goes wrong:** The LLM returns a response that doesn't match `ExtractedLearning`; `instructor` raises `ValidationError` after all retries.
**Why it happens:** instructor retries up to `max_retries=2` by default, then raises.
**How to avoid:** Wrap the `instructor` call in try/except. If extraction fails, log to stderr and `sys.exit(0)` (hook must not block the Stop event). The session data is not lost — `memory-learn.py` still writes to HISTORY.md.
**Warning signs:** Stop hook exits non-zero, blocking Claude Code from completing.

### Pitfall 5: Quarantine Promotion Runs in Stop Hook (Latency Risk)
**What goes wrong:** The quarantine promotion search (semantic similarity check on all quarantined HISTORY entries) adds 200-500ms to the Stop hook.
**Why it happens:** Qdrant search with vector comparison is fast but not free; multiple calls compound.
**How to avoid:** Quarantine promotion should be fire-and-forget too. The Stop hook writes the new learning entry with `quarantined=True`. A separate background coroutine (or a lazy check on next search) handles promotion. Alternatively, limit promotion check to the top-3 similarity matches with a score gate of 0.70.
**Warning signs:** Stop hook timeout (set to 15s in settings.json) hit on sessions with many quarantined entries.

### Pitfall 6: `ToolContext` Doesn't Have `effectiveness_store` Field
**What goes wrong:** `ToolRegistry` receives `EffectivenessStore` but `ToolContext` dataclass has no field for it. Tools that need to inject it cannot declare `requires = ["effectiveness_store"]`.
**Why it happens:** `ToolContext` in `tools/context.py` is a frozen-ish dataclass with fixed fields. `EffectivenessStore` does not need injection into tools — it's injected into `ToolRegistry` directly by `agent42.py`.
**How to avoid:** Pass `EffectivenessStore` to `ToolRegistry.__init__()` as a new optional parameter (`effectiveness_store=None`). Do not add it to `ToolContext`. Only `ToolRegistry.execute()` needs it.
**Warning signs:** AttributeError on `ToolRegistry(rate_limiter=..., effectiveness_store=...)`.

### Pitfall 7: Circular Import — `core.task_context` ↔ `memory.effectiveness`
**What goes wrong:** `memory/effectiveness.py` imports `from core.task_context import get_task_context`, but `core/task_context.py` has no memory imports, so the direction is acceptable (memory → core). However, `ToolRegistry` importing `EffectivenessStore` adds `tools → memory → core` chain.
**Why it happens:** Python resolves imports at module load time; circular chains cause `ImportError`.
**How to avoid:** Use lazy import inside `ToolRegistry.execute()` body: `from core.task_context import get_task_context`. This is already the established pattern in the codebase (see `store.py` lazy imports of `memory.qdrant_store`).
**Warning signs:** `ImportError: cannot import name 'EffectivenessStore' from partially initialized module`.

---

## Code Examples

### aiosqlite basic async write pattern
```python
# Source: aiosqlite official docs, consistent with aiosqlite>=0.20.0

import aiosqlite

async def write_record(db_path: str, row: tuple) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "INSERT INTO tool_invocations (tool_name, task_type, task_id, success, duration_ms, ts) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            row
        )
        await db.commit()
```

### instructor structured extraction pattern
```python
# Source: instructor library docs, openai>=1.40.0 compatible

import instructor
from openai import AsyncOpenAI
from pydantic import BaseModel

class ExtractedLearning(BaseModel):
    task_type: str
    outcome: str       # "success" | "failure" | "partial"
    summary: str       # 1-2 sentences
    key_insight: str   # The durable learning
    tools_used: list[str]
    files_modified: list[str]

async def extract_learning(prompt: str, api_key: str, base_url: str | None = None) -> ExtractedLearning | None:
    try:
        client = instructor.from_openai(
            AsyncOpenAI(api_key=api_key, base_url=base_url)
        )
        return await client.chat.completions.create(
            model="gemini-2-flash",
            response_model=ExtractedLearning,
            max_retries=2,
            messages=[{"role": "user", "content": prompt}]
        )
    except Exception as e:
        logger.warning("Learning extraction failed: %s", e)
        return None
```

### EffectivenessStore aggregation query (EFFT-04)
```python
# No ORM needed — direct SQL via aiosqlite

async def get_aggregated_stats(self, tool_name: str = "", task_type: str = "") -> list[dict]:
    """Returns success_rate + avg_duration by tool+task_type pair."""
    query = """
        SELECT
            tool_name,
            task_type,
            COUNT(*)                    AS invocations,
            AVG(CAST(success AS REAL))  AS success_rate,
            AVG(duration_ms)            AS avg_duration_ms
        FROM tool_invocations
        WHERE (? = '' OR tool_name = ?)
          AND (? = '' OR task_type = ?)
        GROUP BY tool_name, task_type
        ORDER BY invocations DESC
    """
    async with aiosqlite.connect(self._db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(query, (tool_name, tool_name, task_type, task_type)) as cursor:
            rows = await cursor.fetchall()
    return [dict(row) for row in rows]
```

### Fire-and-forget task in existing ToolRegistry (reference: store.py)
```python
# Source: memory/store.py _record_recalls() — same pattern to use in registry.py

def _record_recalls(self, results: list[dict]):
    """Fire-and-forget Qdrant update."""
    import asyncio
    # This method is called from within an async context, so create_task works
    for r in results:
        point_id = r.get("point_id")
        if not point_id:
            continue
        try:
            asyncio.create_task(self._async_record_recall(point_id, ...))
        except Exception:
            pass  # Non-critical
```

### HISTORY.md entry format (LEARN-02)
```
### [2026-03-17 14:23:11 UTC] [coding][abc-uuid-123][success]
Fixed ToolRegistry to wrap execute() with timing measurement.
Tools used: Read, Edit, Bash. Files modified: tools/registry.py, tests/test_effectiveness.py.
Key insight: asyncio.create_task() must be called from within async context; use get_running_loop() variant from sync code.

---
```

The `log_event_semantic()` call format:
```python
await memory_store.log_event_semantic(
    event_type=f"[{task_type}][{task_id}][{outcome}]",
    summary=learning.summary,
    details=f"Tools used: {', '.join(learning.tools_used)}.\n"
            f"Files modified: {', '.join(learning.files_modified)}.\n"
            f"Key insight: {learning.key_insight}"
)
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Manual JSON parsing of LLM output | `instructor` library with Pydantic models | ~2023 | Automatic retry, schema validation, no custom parsing code |
| Blocking `sqlite3` with thread executor | `aiosqlite` async wrapper | ~2022 | Native async; fits asyncio-first codebase; no ThreadPoolExecutor overhead |
| Global state for task metadata | `contextvars.ContextVar` | Python 3.7+ | Correct propagation to async child tasks; no global mutation |

**Deprecated/outdated:**
- Using `asyncio.ensure_future()`: Replaced by `asyncio.create_task()` since Python 3.7. `create_task()` is the correct modern form.
- Using thread-local for context propagation in async code: Contextvars are the correct tool since Python 3.7.

---

## Open Questions

1. **How does the Stop hook get the task_id and task_type from the session?**
   - What we know: The Stop event JSON contains `tool_uses`, `messages`, and `project_dir`. It does NOT contain a `task_id` field — that's an in-process contextvar.
   - What's unclear: Phase 20 set up `begin_task()`/`end_task()` but the Stop hook fires after the session ends. The contextvar is gone.
   - Recommendation: Two options. (A) Agent42's server writes a `.agent42/current-task.json` at `begin_task()` time and the Stop hook reads it. (B) The hook generates its own UUID as `task_id` from the session. Option A preserves the correct task_id from ToolRegistry tracking. Option B is simpler but creates a different task_id than what's in `effectiveness.db`. **Option A is preferred for LEARN-03 correctness** — the task_id in HISTORY.md must match the task_id in the SQLite records for future correlation.

2. **How does instructor handle Gemini Flash vs OpenAI-compatible providers?**
   - What we know: instructor uses `openai.AsyncOpenAI` with a custom `base_url`. Agent42's existing `OPENROUTER_API_KEY` and Gemini Flash route through an OpenAI-compatible endpoint.
   - What's unclear: Whether the specific Gemini Flash model ID used by the existing routing (`gemini-2-flash`) works with instructor's structured output mode.
   - Recommendation: instructor supports `mode=instructor.Mode.JSON` as a fallback that works with any model that supports JSON output. Default mode (function calling) may not work with all Gemini Flash endpoints. Use `instructor.from_openai(client, mode=instructor.Mode.JSON_SCHEMA)` initially and test.

3. **Where is the Agent42 HTTP API endpoint for the hook to call?**
   - What we know: `memory-learn.py` uses `AGENT42_SEARCH_URL` env var (default `http://127.0.0.1:6380`). Agent42's main HTTP server runs on port 8000.
   - What's unclear: Whether a new effectiveness endpoint belongs at port 8000 (dashboard API) or 6380 (search service).
   - Recommendation: Add to port 8000 (`dashboard/server.py`) as `/api/effectiveness/learn` — the dashboard API is the primary HTTP interface for all Agent42 functions.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest with pytest-asyncio |
| Config file | `pyproject.toml` (`[tool.pytest.ini_options]`, `asyncio_mode = "auto"`) |
| Quick run command | `python -m pytest tests/test_effectiveness.py -x -q` |
| Full suite command | `python -m pytest tests/ -x -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| EFFT-01 | EffectivenessStore records tool_name, task_type, success, duration_ms, task_id | unit | `python -m pytest tests/test_effectiveness.py::TestEffectivenessStore::test_record_writes_correct_schema -x` | ❌ Wave 0 |
| EFFT-02 | `ToolRegistry.execute()` returns before SQLite write completes | unit | `python -m pytest tests/test_effectiveness.py::TestEffectivenessStore::test_record_is_fire_and_forget -x` | ❌ Wave 0 |
| EFFT-03 | MCP tool invocations tracked (via hook or wrapper) | unit | `python -m pytest tests/test_effectiveness.py::TestMCPTracking -x` | ❌ Wave 0 |
| EFFT-04 | Aggregation query returns success_rate + avg_duration by tool+task_type | unit | `python -m pytest tests/test_effectiveness.py::TestEffectivenessStore::test_aggregation_query -x` | ❌ Wave 0 |
| EFFT-05 | Tool execution continues when SQLite is unwritable | unit | `python -m pytest tests/test_effectiveness.py::TestEffectivenessStore::test_graceful_degradation_unwritable -x` | ❌ Wave 0 |
| LEARN-01 | Stop hook extracts task summary, outcome, tools, files | unit | `python -m pytest tests/test_effectiveness.py::TestLearningExtraction::test_extract_learning_fields -x` | ❌ Wave 0 |
| LEARN-02 | Extracted learning written to HISTORY.md with correct format | unit | `python -m pytest tests/test_effectiveness.py::TestLearningExtraction::test_history_entry_format -x` | ❌ Wave 0 |
| LEARN-03 | Extracted learning indexed in Qdrant with task_id and task_type fields | unit | `python -m pytest tests/test_effectiveness.py::TestLearningExtraction::test_qdrant_payload_fields -x` | ❌ Wave 0 |
| LEARN-04 | Quarantine: confidence capped at 0.6 until 3 observations | unit | `python -m pytest tests/test_effectiveness.py::TestQuarantine -x` | ❌ Wave 0 |
| LEARN-05 | No writes during task execution — only after Stop | unit | `python -m pytest tests/test_effectiveness.py::TestLearningExtraction::test_no_mid_task_writes -x` | ❌ Wave 0 (design by hook placement) |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/test_effectiveness.py -x -q`
- **Per wave merge:** `python -m pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_effectiveness.py` — covers EFFT-01 through EFFT-05, LEARN-01 through LEARN-05, quarantine mechanics
- [ ] Install new dependencies: `pip install aiosqlite>=0.20.0 instructor>=1.3.0` and add to `requirements.txt`
- [ ] `tests/test_effectiveness.py` needs `tmp_path` fixture for SQLite DB path (no hardcoded paths per CLAUDE.md)
- [ ] Mock `aiosqlite.connect` for EFFT-05 test (simulate unwritable DB without filesystem manipulation)
- [ ] Mock `instructor.from_openai` for LEARN-01 tests (no real API calls in tests)

---

## Sources

### Primary (HIGH confidence)
- Direct code inspection: `tools/registry.py`, `memory/store.py`, `core/task_context.py`, `tools/base.py` — confirmed API surfaces and patterns
- `.claude/settings.json` — confirmed Stop hook protocol and existing hooks
- `.claude/hooks/learning-engine.py`, `memory-learn.py` — confirmed hook pattern (JSON stdin, stderr, exit 0)
- `21-CONTEXT.md` — all locked decisions

### Secondary (MEDIUM confidence)
- `aiosqlite` documentation pattern: async context manager `connect()` returning `Connection` object with `.execute()` and `.commit()` — consistent with stdlib sqlite3 API and verified against known aiosqlite 0.20.x behavior
- `instructor` library: `instructor.from_openai(AsyncOpenAI(...))` with `response_model=` parameter — consistent with instructor's documented API for Pydantic v2 models
- `asyncio.create_task()` fire-and-forget: verified in Python 3.11 docs and existing codebase usage

### Tertiary (LOW confidence)
- instructor's `Mode.JSON_SCHEMA` for Gemini Flash compatibility — not directly tested; flagged in Open Questions #2
- Gemini Flash model ID `gemini-2-flash` compatibility with instructor — flagged in Open Questions #2

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — aiosqlite and instructor are industry-standard, project patterns verified from source
- Architecture: HIGH — all patterns derived from existing working code in the codebase
- Pitfalls: HIGH — derived from inspected code paths and established patterns (circular imports, asyncio task behavior)
- Open Questions: MEDIUM — three questions identified but they have clear recommended resolutions

**Research date:** 2026-03-17
**Valid until:** 2026-04-17 (stable libraries, 30 days)
