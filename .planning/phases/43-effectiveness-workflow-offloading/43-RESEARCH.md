# Phase 43: Effectiveness-Driven Workflow Offloading - Research

**Researched:** 2026-04-06
**Domain:** SQLite pattern tracking, async Python, prompt injection, Agent42 effectiveness pipeline
**Confidence:** HIGH

## Summary

Phase 43 is a well-scoped internal extension: new SQLite tables in the existing `effectiveness.db`, a module-level accumulator in `task_context.py`, a new `record_sequence()` method on `EffectivenessStore`, and a prompt injection in `_build_prompt()`. All integration points are clearly identified in CONTEXT.md and confirmed by reading the actual source files.

The work is pure Python — no new runtime dependencies, no new external services. The N8N tools from Phase 42 are already registered in `mcp_server.py` and the `n8n_create_workflow` tool's full API is available. The effectiveness system's `_ensure_db()` lazy initialization pattern must be followed exactly for the three new tables.

The one subtlety that needs attention: `task_context.py` uses `contextvars.ContextVar` for task_id/task_type, but the per-task tool accumulator (D-06) must use a **plain module-level dict** keyed by `task_id`, not a ContextVar. ContextVar values are not safely mutated across async boundaries the way a dict is — and the task_id from `get_task_context()` gives a stable key. `end_task()` must pop the key from the dict after flushing.

**Primary recommendation:** Implement in three logical units — (1) DB schema + `record_sequence()`, (2) accumulator wiring in ToolRegistry + end_task(), (3) prompt injection in `_build_prompt()`. Keep all DB writes fire-and-forget via `asyncio.create_task()`.

## Project Constraints (from CLAUDE.md)

- All I/O is async — use `aiofiles`, `httpx`, `asyncio`. Never blocking I/O.
- `Settings` dataclass in `core/config.py` is frozen — add fields via `from_env()` + `.env.example`.
- Graceful degradation — missing config never crashes Agent42.
- Sandbox always on — not relevant to this phase (no path ops).
- New pitfalls discovered during implementation go to `.claude/reference/pitfalls-archive.md`.
- Tests required: new modules need `tests/test_*.py`.
- Run `python -m pytest tests/ -x -q` to validate.

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Pattern Detection**
- D-01: New `tool_sequences` table in effectiveness.db: `(id, agent_id, task_type, tool_sequence TEXT JSON, execution_count INT, first_seen REAL, last_seen REAL, fingerprint TEXT UNIQUE, status TEXT DEFAULT 'active')`
- D-02: Pattern = ordered list of tool names per task, fingerprinted with MD5 of `json.dumps(tool_names)`, grouped by agent_id + task_type
- D-03: Accumulate tool names in ToolRegistry.execute() per-task context; flush on task_context.end_task() via `effectiveness_store.record_sequence()`
- D-04: Threshold = 3+ executions of same fingerprint; configurable via `N8N_PATTERN_THRESHOLD` env var (default 3)

**Effectiveness Integration**
- D-05: Hook into ToolRegistry.execute() at lines 131-148 (after effectiveness.record() call)
- D-06: Task-scoped accumulator: `_current_task_tools: dict[str, list[str]]` at module level in task_context, keyed by task_id
- D-07: On task_context.end_task(), call `effectiveness_store.record_sequence(agent_id, task_type, tool_names)`
- D-08: Token savings estimated as `execution_count * 1000` tokens (heuristic, no spend_history dependency)

**Suggestion Mechanism**
- D-09: Prompt injection in agent_runtime.py `_build_prompt()` — query patterns >= threshold, inject before task execution
- D-10: Suggestion format: "Pattern '{tool1 → tool2 → tool3}' has repeated {N} times. Estimated savings: ~{N*1000} tokens. Use n8n_create_workflow to automate this."
- D-11: New `workflow_suggestions` table: `(id, agent_id, task_type, fingerprint TEXT, tool_sequence TEXT JSON, execution_count INT, tokens_saved_estimate INT, suggested_at REAL, status TEXT DEFAULT 'pending')` — status: pending, accepted, dismissed, created
- D-12: No dashboard panel in this phase — prompt injection only

**Auto-Creation Flow**
- D-13: When agent calls `n8n_create_workflow` in response to suggestion, store mapping in `workflow_mappings` table: `(id, agent_id, fingerprint TEXT, workflow_id TEXT, webhook_url TEXT, template TEXT, created_at REAL, last_triggered REAL, trigger_count INT DEFAULT 0, status TEXT DEFAULT 'active')`
- D-14: Template selection heuristic: http_client/web_fetch → `webhook_to_multi_step`; data_tool/content_analyzer → `webhook_to_transform`; default → `webhook_to_http`
- D-15: Auto-generated workflow name: `"Agent42: {agent_id} - {task_type} automation"`, webhook path `"agent42-{fingerprint[:12]}"`
- D-16: `N8N_AUTO_CREATE_WORKFLOWS` bool (default false) — when true, skip confirmation

**Configuration**
- D-17: Add to Settings: `n8n_pattern_threshold: int = 3`, `n8n_auto_create_workflows: bool = False`
- D-18: Env vars: `N8N_PATTERN_THRESHOLD=3`, `N8N_AUTO_CREATE_WORKFLOWS=false`
- D-19: Add to `.env.example` with documentation

### Claude's Discretion
- Exact SQL query optimization for pattern detection
- Whether to use a background asyncio task or synchronous check for threshold
- Error handling and retry logic for failed workflow creation attempts
- How to handle patterns that don't map well to N8N (non-HTTP tool chains)

### Deferred Ideas (OUT OF SCOPE)
- Dashboard panel for workflow suggestions — future
- Pre-execution routing hook to existing workflows — Phase 44
- Hybrid task splitting (deterministic subtasks to N8N, reasoning to agent) — Phase 44
- spend_history integration for exact token cost tracking — backport Phase 29
- Workflow performance monitoring — future phase
</user_constraints>

---

## Standard Stack

### Core (all already in the project, no new installs)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| aiosqlite | existing | Async SQLite writes for new tables | Already used in effectiveness.py |
| asyncio | stdlib | Fire-and-forget task pattern | Established pattern in EffectivenessStore |
| hashlib | stdlib | MD5 fingerprinting of tool sequences | Lightweight, no dependencies |
| json | stdlib | Serialize tool_sequence list to TEXT | Established in effectiveness.py |

### No New Dependencies
This phase introduces zero new packages. All required capabilities (aiosqlite, asyncio, hashlib, json) are already present.

**Version verification:** N/A — no new packages.

## Architecture Patterns

### Recommended File Structure for Phase 43

```
memory/effectiveness.py      # Add record_sequence(), get_pending_suggestions(),
                             # get_workflow_mappings() + 3 new tables in _ensure_db()
core/task_context.py         # Add _current_task_tools dict + end_task() flush hook
tools/registry.py            # Add tool name accumulation after effectiveness.record()
core/agent_runtime.py        # Add suggestion injection in _build_prompt()
core/config.py               # Add n8n_pattern_threshold, n8n_auto_create_workflows
.env.example                 # Document new env vars
tests/test_phase43_patterns.py  # New test file for all new behavior
```

### Pattern 1: Lazy DB Init (ESTABLISHED — follow exactly)

All new tables go inside `EffectivenessStore._ensure_db()`. The guard `if self._db_initialized: return` runs first, so all tables in the block are created atomically on first use.

```python
# Source: memory/effectiveness.py lines 52-140 (confirmed by reading)
async def _ensure_db(self) -> None:
    if self._db_initialized:
        return
    self._db_path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(self._db_path) as db:
        # ... existing tables ...
        await db.execute("""
            CREATE TABLE IF NOT EXISTS tool_sequences (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id        TEXT    NOT NULL DEFAULT '',
                task_type       TEXT    NOT NULL DEFAULT '',
                tool_sequence   TEXT    NOT NULL,
                execution_count INTEGER NOT NULL DEFAULT 1,
                first_seen      REAL    NOT NULL,
                last_seen       REAL    NOT NULL,
                fingerprint     TEXT    NOT NULL UNIQUE,
                status          TEXT    NOT NULL DEFAULT 'active'
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS workflow_suggestions (
                id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id              TEXT    NOT NULL DEFAULT '',
                task_type             TEXT    NOT NULL DEFAULT '',
                fingerprint           TEXT    NOT NULL,
                tool_sequence         TEXT    NOT NULL,
                execution_count       INTEGER NOT NULL,
                tokens_saved_estimate INTEGER NOT NULL DEFAULT 0,
                suggested_at          REAL    NOT NULL,
                status                TEXT    NOT NULL DEFAULT 'pending'
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS workflow_mappings (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id      TEXT    NOT NULL DEFAULT '',
                fingerprint   TEXT    NOT NULL,
                workflow_id   TEXT    NOT NULL,
                webhook_url   TEXT    NOT NULL,
                template      TEXT    NOT NULL DEFAULT '',
                created_at    REAL    NOT NULL,
                last_triggered REAL   NOT NULL DEFAULT 0.0,
                trigger_count  INTEGER NOT NULL DEFAULT 0,
                status         TEXT   NOT NULL DEFAULT 'active'
            )
        """)
        await db.commit()
    self._db_initialized = True
```

### Pattern 2: Fire-and-Forget Writes (ESTABLISHED — follow exactly)

```python
# Source: tools/registry.py lines 131-148 (confirmed by reading)
# Never block tool return for tracking writes
asyncio.create_task(
    self._effectiveness_store.record_sequence(
        agent_id=agent_id,
        task_type=task_type or "general",
        task_id=task_id or "",
        tool_names=tool_list,
    )
)
```

### Pattern 3: Module-Level Dict Accumulator (NEW for Phase 43)

The ContextVar approach is used for scalar values (task_id, task_type). The per-task tool list must use a plain module-level dict keyed by task_id — this is safe because each task has a unique UUID task_id, and both the ToolRegistry (writer) and end_task() (reader/flusher) access the same module-level dict.

```python
# In core/task_context.py — add after existing ContextVar declarations
# Source: design decision D-06
_current_task_tools: dict[str, list[str]] = {}

def append_tool_to_task(task_id: str, tool_name: str) -> None:
    """Add a tool name to the accumulator for the given task_id."""
    if task_id:
        if task_id not in _current_task_tools:
            _current_task_tools[task_id] = []
        _current_task_tools[task_id].append(tool_name)

def pop_task_tools(task_id: str) -> list[str]:
    """Remove and return the tool list for the given task_id."""
    return _current_task_tools.pop(task_id, [])
```

### Pattern 4: MD5 Fingerprinting

```python
import hashlib, json

def _fingerprint(tool_names: list[str]) -> str:
    """Stable MD5 fingerprint for an ordered tool sequence."""
    return hashlib.md5(json.dumps(tool_names).encode()).hexdigest()
```

### Pattern 5: Upsert Pattern for tool_sequences

Increment execution_count on collision, never duplicate rows for the same fingerprint+agent_id+task_type combination:

```python
await db.execute("""
    INSERT INTO tool_sequences
        (agent_id, task_type, tool_sequence, execution_count, first_seen, last_seen, fingerprint)
    VALUES (?, ?, ?, 1, ?, ?, ?)
    ON CONFLICT(fingerprint) DO UPDATE SET
        execution_count = execution_count + 1,
        last_seen = excluded.last_seen
""", (agent_id, task_type, json.dumps(tool_names), now, now, fp))
```

Note: The CONTEXT.md schema has `fingerprint TEXT UNIQUE` — this enables the `ON CONFLICT(fingerprint)` clause. However, two different agents executing the same tool chain would share a fingerprint if they have the same tool order. Consider whether the UNIQUE constraint should span `(agent_id, task_type, fingerprint)` instead. The planner should decide — this is left as Claude's discretion per D-06 grouping language ("grouped by agent_id + task_type").

**Recommendation:** Use a compound unique index `(agent_id, task_type, fingerprint)` and use `ON CONFLICT` targeting those columns. This is more correct than a bare `fingerprint UNIQUE`.

### Pattern 6: Prompt Injection Point (CONFIRMED)

`_build_prompt()` in `core/agent_runtime.py` lines 72-95 is confirmed as the injection point. It builds a list of string parts and joins them. The suggestion block should query pending suggestions for the agent and inject them just before the N8N guidance block.

```python
# core/agent_runtime.py _build_prompt() — add after N8N guidance block
# Confirmed injection point at lines 92-99
if self._effectiveness_store:
    suggestions = asyncio.run(
        self._effectiveness_store.get_pending_suggestions(agent_id)
    )
    for s in suggestions:
        tools_str = " → ".join(json.loads(s["tool_sequence"]))
        savings = s["tokens_saved_estimate"]
        parts.append(
            f"\nAUTOMATION SUGGESTION: Pattern '{tools_str}' has repeated "
            f"{s['execution_count']} times. Estimated savings: ~{savings} tokens. "
            "Use n8n_create_workflow to automate this."
        )
```

**Important:** `_build_prompt()` is synchronous. Using `asyncio.run()` inside an async context will raise `RuntimeError: This event loop is already running`. The planner must address this — options:
1. Make `_build_prompt()` async and `await` it from `start_agent()`
2. Use `asyncio.get_event_loop().run_until_complete()` (deprecated, fragile)
3. Pre-fetch suggestions synchronously using a separate sync DB connection
4. Cache suggestions from a background coroutine, read from cache synchronously

**Recommended approach (Claude's discretion):** Make `_build_prompt()` async. `start_agent()` already uses `async def` and calls `_build_prompt()` synchronously — changing to `await self._build_prompt(agent_config)` is a one-line call site change.

### Anti-Patterns to Avoid

- **Awaiting inside fire-and-forget:** `asyncio.create_task()` wraps a coroutine — do NOT await it at the call site. The effectiveness.record() pattern is the model.
- **Blocking SQLite in hot path:** All DB calls go through `asyncio.create_task()` wrappers, never blocking the tool return path.
- **Global dict without pop:** If `pop_task_tools()` isn't called in `end_task()`, the dict grows unbounded. Always pop in the finally/cleanup path.
- **Calling asyncio.run() inside running loop:** See prompt injection caveat above.
- **UNIQUE on fingerprint only:** Same tool chain from two different agents would collide. Use compound unique index.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Async SQLite | Sync sqlite3 | aiosqlite (already dep) | Blocks event loop |
| MD5 hashing | Custom hash | hashlib.md5 | stdlib, stable, fast |
| JSON serialization | Custom format | json.dumps/loads | Already used in effectiveness.py |
| Workflow creation | Custom N8N API client | N8nCreateWorkflowTool.execute() | Already built in Phase 42 |
| Deduplication | Manual loop | `ON CONFLICT ... DO UPDATE` SQLite upsert | Single atomic operation |

**Key insight:** All hard problems in this domain are already solved — the effectiveness store's async/graceful-degradation pattern is proven across 500+ lines of existing code. Follow it exactly.

## Common Pitfalls

### Pitfall 1: asyncio.run() Inside Async Context
**What goes wrong:** `_build_prompt()` is currently sync. If it calls `asyncio.run()` to fetch suggestions while an event loop is running (which it always is in an async FastAPI/agent context), Python raises `RuntimeError: This event loop is already running`.
**Why it happens:** `asyncio.run()` creates a new event loop, which is not allowed when one is already running.
**How to avoid:** Make `_build_prompt()` async (preferred) or pre-load suggestions before calling `_build_prompt()` and pass them as a parameter.
**Warning signs:** `RuntimeError: This event loop is already running` in agent startup logs.

### Pitfall 2: UNIQUE Fingerprint Collision Across Agents
**What goes wrong:** Two different agents with the same tool chain (e.g., both run `[http_client, data_tool]`) hit the UNIQUE constraint on `fingerprint`, causing one write to silently overwrite the other's execution_count.
**Why it happens:** CONTEXT.md D-01 says `fingerprint TEXT UNIQUE` but D-02 says "grouped by agent_id + task_type". These are contradictory if fingerprint alone is unique.
**How to avoid:** Use `CREATE UNIQUE INDEX ON tool_sequences (agent_id, task_type, fingerprint)` and remove bare UNIQUE from column definition. Update upsert to `ON CONFLICT(agent_id, task_type, fingerprint)`.
**Warning signs:** Execution counts jumping by more than 1 per actual run.

### Pitfall 3: _current_task_tools Memory Leak
**What goes wrong:** If `end_task()` is not called (e.g., agent crashes mid-task), the task's tool list stays in `_current_task_tools` forever. On a long-running server, this accumulates over time.
**Why it happens:** Plain dicts have no TTL.
**How to avoid:** In `end_task()`, always call `pop_task_tools(ctx.task_id)` — even if flushing fails, pop the key to prevent the leak. Use try/finally in end_task.
**Warning signs:** Memory growth in long-running Agent42 processes.

### Pitfall 4: Suggestion Re-injection on Every Prompt
**What goes wrong:** If `get_pending_suggestions()` always returns 'pending' suggestions, the same suggestion injects into every prompt for an agent until they act on it — becoming a nag.
**Why it happens:** Status stays 'pending' until agent explicitly calls `n8n_create_workflow` or dismisses.
**How to avoid:** Per CONTEXT.md specifics: "Only suggest once per pattern, mark as 'dismissed' if agent ignores it." The planner needs a mechanism: either mark 'suggested' after first injection, or check `suggested_at` and only re-inject after a cooldown. Recommended: add a `suggested` status and set it after first injection. Only return `pending` (never-injected) suggestions from `get_pending_suggestions()`.
**Warning signs:** User/agent feedback about repetitive suggestions.

### Pitfall 5: Single-Tool "Patterns"
**What goes wrong:** A task that calls only one tool generates a one-item sequence `["shell"]`. This isn't useful for N8N offloading — a single tool doesn't constitute a repeatable workflow pattern.
**Why it happens:** No minimum sequence length check.
**How to avoid:** Skip sequences with `len(tool_names) < 2` in `record_sequence()`. A workflow that only invokes one tool adds no value over calling that tool directly.
**Warning signs:** `tool_sequences` table filling up with single-item sequences.

### Pitfall 6: Async end_task() Contract
**What goes wrong:** `end_task()` is currently synchronous (`def end_task(ctx) -> None`). The flush call `effectiveness_store.record_sequence()` is async. If you add an `await` inside a sync function, you get a SyntaxError.
**Why it happens:** The flush needs to be async but the caller is sync.
**How to avoid:** Use `asyncio.create_task(store.record_sequence(...))` — fire-and-forget. This is the established pattern for effectiveness writes. Do NOT make `end_task()` async (it would break all 8+ existing call sites).
**Warning signs:** SyntaxError or missing event loop when calling end_task.

## Code Examples

### record_sequence() Method Skeleton

```python
# Source: design — follows established EffectivenessStore.record() pattern
async def record_sequence(
    self,
    agent_id: str,
    task_type: str,
    tool_names: list[str],
) -> int | None:
    """Record a tool sequence and return execution_count if threshold reached.

    Returns the new execution_count if >= n8n_pattern_threshold, else None.
    Never raises.
    """
    if not AIOSQLITE_AVAILABLE or len(tool_names) < 2:
        return None
    try:
        await self._ensure_db()
        from core.config import settings
        fp = hashlib.md5(json.dumps(tool_names).encode()).hexdigest()
        now = time.time()
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("""
                INSERT INTO tool_sequences
                    (agent_id, task_type, tool_sequence, execution_count,
                     first_seen, last_seen, fingerprint)
                VALUES (?, ?, ?, 1, ?, ?, ?)
                ON CONFLICT(agent_id, task_type, fingerprint) DO UPDATE SET
                    execution_count = execution_count + 1,
                    last_seen = excluded.last_seen
            """, (agent_id, task_type, json.dumps(tool_names), now, now, fp))
            await db.commit()
            async with db.execute(
                "SELECT execution_count FROM tool_sequences "
                "WHERE agent_id=? AND task_type=? AND fingerprint=?",
                (agent_id, task_type, fp)
            ) as cur:
                row = await cur.fetchone()
            count = row[0] if row else 0
        threshold = settings.n8n_pattern_threshold
        return count if count >= threshold else None
    except Exception as e:
        logger.warning("record_sequence failed (non-critical): %s", e)
        return None
```

### get_pending_suggestions() Method Skeleton

```python
async def get_pending_suggestions(self, agent_id: str) -> list[dict]:
    """Return never-injected suggestions for an agent. Never raises."""
    if not AIOSQLITE_AVAILABLE:
        return []
    try:
        await self._ensure_db()
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT fingerprint, tool_sequence, execution_count,
                       tokens_saved_estimate, task_type
                FROM workflow_suggestions
                WHERE agent_id = ? AND status = 'pending'
                ORDER BY execution_count DESC
                LIMIT 3
            """, (agent_id,)) as cur:
                rows = await cur.fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning("get_pending_suggestions failed: %s", e)
        return []
```

### ToolRegistry Accumulator Hook

```python
# tools/registry.py — inside execute(), after effectiveness tracking block (line ~147)
# Fire-and-forget tool name accumulation for pattern detection (Phase 43)
if self._effectiveness_store:
    try:
        from core.task_context import get_task_context, append_tool_to_task
        task_id, _ = get_task_context()
        if task_id:
            append_tool_to_task(task_id, tool_name)
    except Exception:
        pass  # Never block tool execution for pattern tracking
```

### end_task() Flush Hook

```python
# core/task_context.py — end_task() modification
def end_task(ctx: TaskContext) -> None:
    """End task context, flush tool sequence for pattern detection."""
    tool_names = pop_task_tools(ctx.task_id)  # Always pop, even on error path

    # Fire-and-forget sequence flush (Phase 43)
    # Import here to avoid circular imports (same pattern as registry.py)
    try:
        import asyncio
        from memory.effectiveness import _get_shared_store  # or pass store differently
        store = _get_shared_store()
        if store and tool_names and len(tool_names) >= 2:
            asyncio.create_task(store.record_sequence(
                agent_id=ctx.agent_id if hasattr(ctx, 'agent_id') else "",
                task_type=ctx.task_type.value if ctx.task_type else "general",
                tool_names=tool_names,
            ))
    except Exception:
        pass  # Non-critical

    _task_id_var.reset(ctx._id_token)
    _task_type_var.reset(ctx._type_token)
    _remove_task_file()
```

**Note:** The current `TaskContext` dataclass does NOT have an `agent_id` field (only `task_id` and `task_type`). The planner must decide: either add `agent_id` to `TaskContext` (requires updating all `begin_task()` call sites), or pass `agent_id=""` and group only by task_type. Alternatively, `begin_task()` can accept an optional `agent_id` parameter. This is a **key design gap** the planner must resolve.

**Recommendation:** Add `agent_id: str = ""` to `TaskContext.__slots__` and `begin_task(task_type, agent_id="")` signature. Call sites that don't pass agent_id get `""` (backward compatible).

### Config Additions

```python
# core/config.py — add after n8n_allow_code_nodes (line 337)
# N8N Pattern Offloading (Phase 43)
n8n_pattern_threshold: int = 3      # Executions before suggesting N8N workflow
n8n_auto_create_workflows: bool = False  # When true, create without confirmation
```

```python
# in from_env() classmethod — add after n8n_allow_code_nodes line (~650)
n8n_pattern_threshold=int(os.getenv("N8N_PATTERN_THRESHOLD", "3")),
n8n_auto_create_workflows=os.getenv("N8N_AUTO_CREATE_WORKFLOWS", "false").lower() == "true",
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Blocking SQLite writes | Fire-and-forget asyncio.create_task | Phase 20 | Tool hot path never blocked |
| Per-call effectiveness only | Sequence-level pattern tracking | Phase 43 (new) | Enables workflow offloading suggestions |
| Static agent prompts | Dynamic injection from effectiveness data | Phase 43 (new) | Agents get actionable optimization hints |

**Deprecated/outdated:**
- Nothing deprecated in this phase. All new additions are additive.

## Open Questions

1. **agent_id propagation to TaskContext**
   - What we know: TaskContext has `task_id` and `task_type` but NO `agent_id` field
   - What's unclear: Whether to add agent_id to begin_task() or use a different mechanism
   - Recommendation: Add `agent_id: str = ""` parameter to `begin_task()` and `TaskContext.__slots__`. Backward compatible — existing callers pass nothing.

2. **Shared store access from task_context.py**
   - What we know: task_context.py currently imports nothing from memory/. Calling `record_sequence()` from `end_task()` requires accessing the EffectivenessStore instance.
   - What's unclear: The store is instantiated in `agent42.py` / `mcp_server.py` — there's no singleton accessor. `_get_shared_store()` doesn't exist yet.
   - Recommendation: Add a module-level `_shared_effectiveness_store: EffectivenessStore | None = None` to `memory/effectiveness.py` with `set_shared_store(store)` and `get_shared_store()` functions. Wire in `agent42.py` at startup. Alternative: pass the store to `end_task()` as an optional parameter.

3. **Suggestion injection timing vs async _build_prompt()**
   - What we know: `_build_prompt()` is sync, `get_pending_suggestions()` is async
   - What's unclear: Best approach for making sync code call async DB
   - Recommendation: Make `_build_prompt()` async (one-line change at call site in `start_agent()`).

4. **Minimum sequence length**
   - What we know: D-02 doesn't specify a minimum; single-tool sequences are useless for N8N
   - Recommendation: Skip sequences with len < 2 in `record_sequence()`. Document in code comment.

## Environment Availability

Step 2.6: SKIPPED (no external dependencies introduced in this phase — all work is pure Python against existing aiosqlite/asyncio stack; N8N tools from Phase 42 are already deployed and optional via graceful degradation).

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest + pytest-asyncio |
| Config file | `pyproject.toml` (`[tool.pytest.ini_options]`, `asyncio_mode = "auto"`) |
| Quick run command | `python -m pytest tests/test_phase43_patterns.py -x -q` |
| Full suite command | `python -m pytest tests/ -x -q` |

### Phase Requirements to Test Map

| Behavior | Test Type | Automated Command | File Exists? |
|----------|-----------|-------------------|-------------|
| tool_sequences table created with correct schema | unit | `pytest tests/test_phase43_patterns.py::TestToolSequencesTable -x` | Wave 0 |
| record_sequence() upserts and increments execution_count | unit | `pytest tests/test_phase43_patterns.py::TestRecordSequence -x` | Wave 0 |
| record_sequence() returns count when >= threshold | unit | `pytest tests/test_phase43_patterns.py::TestThresholdDetection -x` | Wave 0 |
| record_sequence() skips single-tool sequences | unit | `pytest tests/test_phase43_patterns.py::TestMinLength -x` | Wave 0 |
| ToolRegistry accumulates tools per task_id | unit | `pytest tests/test_phase43_patterns.py::TestAccumulator -x` | Wave 0 |
| end_task() flushes and pops accumulator | unit | `pytest tests/test_phase43_patterns.py::TestEndTaskFlush -x` | Wave 0 |
| _build_prompt() injects suggestion text | unit | `pytest tests/test_phase43_patterns.py::TestPromptInjection -x` | Wave 0 |
| workflow_suggestions table records suggestions | unit | `pytest tests/test_phase43_patterns.py::TestSuggestionsTable -x` | Wave 0 |
| Graceful degradation when N8N not configured | unit | `pytest tests/test_phase43_patterns.py::TestGracefulDegradation -x` | Wave 0 |
| Settings: n8n_pattern_threshold defaults to 3 | unit | `pytest tests/test_phase43_patterns.py::TestConfig -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/test_phase43_patterns.py -x -q`
- **Per wave merge:** `python -m pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_phase43_patterns.py` — all new behavior for Phase 43 (does not exist yet)

*(All other test infrastructure exists: pytest.ini in pyproject.toml, asyncio_mode=auto, existing test patterns in test_effectiveness.py to follow)*

## Sources

### Primary (HIGH confidence)
- `memory/effectiveness.py` (read directly) — EffectivenessStore patterns, table schemas, _ensure_db() structure, record() fire-and-forget pattern
- `tools/registry.py` (read directly) — execute() hook point at lines 131-148, confirmed effectiveness.record() location
- `core/task_context.py` (read directly) — begin_task/end_task lifecycle, ContextVar usage, TaskContext dataclass (no agent_id field confirmed)
- `core/agent_runtime.py` (read directly) — _build_prompt() at lines 72-105, confirmed sync nature and injection point
- `tools/n8n_create_workflow.py` (read directly) — full N8N workflow creation API, template loading, DANGEROUS_NODE_TYPES
- `core/config.py` (read directly) — n8n fields at lines 332-337, from_env() pattern at lines 648-650
- `pyproject.toml` (read directly) — pytest config, asyncio_mode=auto

### Secondary (MEDIUM confidence)
- `.planning/phases/43-effectiveness-workflow-offloading/43-CONTEXT.md` — locked decisions (D-01 through D-19)
- `.planning/phases/42-n8n-workflow-integration/42-CONTEXT.md` — Phase 42 prior decisions confirming N8N tool availability

### Tertiary (LOW confidence)
- None. All critical claims verified against actual source files.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — zero new dependencies, all verified in active codebase
- Architecture: HIGH — all integration points confirmed by reading actual source files
- Pitfalls: HIGH for pitfalls 1-4, MEDIUM for 5-6 (edge cases, but patterns from reading code)

**Research date:** 2026-04-06
**Valid until:** 2026-05-06 (stable Python codebase, no fast-moving dependencies)
