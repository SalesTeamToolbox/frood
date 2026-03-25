# Phase 4: Context Engine - Research

**Researched:** 2026-03-25
**Domain:** Unified context assembly — jcodemunch MCP, GSD workstream state, effectiveness ranking
**Confidence:** HIGH (based on direct codebase analysis of all integration points)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Create a new `UnifiedContextTool` in `tools/unified_context.py` that wraps the existing `ContextAssemblerTool` rather than modifying it in-place
- **D-02:** `ContextAssemblerTool` (`context` MCP tool) continues to work unchanged — backward compatible
- **D-03:** `UnifiedContextTool` delegates to ContextAssemblerTool for memory + docs + git + skills, then adds jcodemunch + GSD + effectiveness on top
- **D-04:** Call jcodemunch via MCP client async protocol (`mcp` library's `ClientSession`) — proper MCP-to-MCP communication
- **D-05:** Graceful degradation: when jcodemunch server is unavailable (not running, connection refused), omit code symbols from response and return remaining sources without error
- **D-06:** Use `search_symbols` and `search_text` jcodemunch tools as primary code search actions, with `get_file_outline` for structural context
- **D-07:** Read active workstream by scanning `.planning/workstreams/*/STATE.md` files for the one with `status != Complete`
- **D-08:** When a GSD workstream is active, include current phase goal and open plan items in the response only when query topic keyword-matches the phase name or plan task descriptions
- **D-09:** Parse STATE.md YAML frontmatter for `stopped_at`, `status`, phase/plan progress; read active phase PLAN.md for open task list
- **D-10:** Use existing `EffectivenessStore.get_recommendations(task_type)` to rank tools/skills by success rate for the inferred task type
- **D-11:** Infer task type from query keywords using the same keyword-to-task-type mapping that `context-loader.py` hook uses (coding, debugging, research, etc.)
- **D-12:** Tools/skills with effectiveness history appear ranked above those without history for the detected task type
- **D-13:** Rebalance token budget across 6 sources: memory 30%, code symbols 25%, GSD state 15%, git history 10%, skills 10%, effectiveness 10%
- **D-14:** When a source returns nothing (e.g., jcodemunch unavailable), redistribute its budget proportionally to remaining sources
- **D-15:** Register as new `agent42_context` MCP tool name in `mcp_server.py`
- **D-16:** Keep existing `context` tool (ContextAssemblerTool) registered separately — no breaking change
- **D-17:** `agent42_context` parameters: `topic` (required), `scope`, `depth`, `max_tokens`, `task_type` (optional override for effectiveness ranking)

### Claude's Discretion

- MCP client connection management (persistent vs per-call, timeout values)
- Deduplication algorithm between jcodemunch results and memory results
- Exact keyword extraction and matching logic for GSD state relevance
- Output formatting and section ordering within the response

### Deferred Ideas (OUT OF SCOPE)

None — analysis stayed within phase scope.

</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| CTX-01 | User can call `agent42_context` and receive code symbols from jcodemunch merged with memory results in a single response | `MCPConnection.call_tool()` in `tools/mcp_client.py` provides the async jcodemunch integration path; `_search_memory()` in ContextAssemblerTool is the memory pipeline. Both merge via SHA256 dedup. |
| CTX-02 | User can call `agent42_context` and see the active GSD workstream phase plan when the query matches current work context | STATE.md YAML frontmatter + glob for `!= Complete` status gives active workstream; PLAN.md task list read for open items. |
| CTX-03 | User can call `agent42_context` and see effectiveness-ranked tools/skills for the current task type at the top of results | `EffectivenessStore.get_recommendations(task_type)` in `memory/effectiveness.py` returns ranked tools ready to inject. Task type inferred from `WORK_TYPE_KEYWORDS` in `context-loader.py`. |

</phase_requirements>

---

## Summary

Phase 4 delivers a new `agent42_context` MCP tool (registered as `UnifiedContextTool` in `tools/unified_context.py`) that extends the existing `ContextAssemblerTool` by adding three sources: jcodemunch code symbols via MCP-to-MCP async call, active GSD workstream state via `.planning/` file reads, and effectiveness-ranked tool/skill injection via `EffectivenessStore.get_recommendations()`. The existing `context` tool registration is untouched — backward compatible.

All three integrations have direct code paths already implemented in the codebase. The `MCPConnection` class in `tools/mcp_client.py` provides the exact async jcodemunch call pattern (`connect()` → `call_tool()`). The `EffectivenessStore.get_recommendations(task_type)` method in `memory/effectiveness.py` is ready to consume. The task type inference keyword map is already defined in `.claude/hooks/context-loader.py` as `WORK_TYPE_KEYWORDS` and reusable as-is. The token budget rebalancing formula is a straightforward extension of the four-source budget constants already in `context_assembler.py`.

The two discretion areas requiring design decisions are: (1) whether jcodemunch connections are per-call (safe, no resource leaks) or persistent (faster, requires cleanup), and (2) the GSD state keyword relevance matching algorithm (token-overlap or substring).

**Primary recommendation:** Use per-call (connect/disconnect-per-execute) jcodemunch connections wrapped in `asyncio.wait_for(..., timeout=3.0)` to prevent blocking on unavailable servers. Use token-overlap keyword matching for GSD state relevance (same approach as `_search_docs` in ContextAssemblerTool).

---

## Standard Stack

### Core (all existing — zero new dependencies)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `mcp` SDK | existing | `ClientSession`, `StdioServerParameters`, `stdio_client` | Already used in `tools/mcp_client.py` for the MCPConnection class — direct reuse |
| `aiofiles` | existing | Async `.planning/` file reads | Project pattern: all file I/O must be async (CLAUDE.md) |
| `asyncio` | stdlib | `asyncio.wait_for()`, `asyncio.gather()` for parallel source assembly | All I/O is async per project constraint |
| `yaml` | stdlib (PyYAML) | Parse STATE.md YAML frontmatter | Already used in project; frontmatter is standard YAML |
| `hashlib` | stdlib | SHA256 dedup (already in ContextAssemblerTool) | Reuse existing pattern exactly |
| `re` | stdlib | Keyword extraction and GSD state matching | Already used in `_extract_keywords()` |
| `pathlib.Path` | stdlib | `.planning/` directory traversal | Project convention throughout |

### No New Dependencies Required

The `mcp` library, `aiofiles`, `PyYAML`, and all other needed packages are already installed. The tool builds entirely on existing project infrastructure.

**Verification:**

```bash
# Confirm mcp SDK is importable
python -c "from mcp import ClientSession, StdioServerParameters; from mcp.client.stdio import stdio_client; print('ok')"

# Confirm aiofiles is importable
python -c "import aiofiles; print('ok')"

# Confirm yaml is importable
python -c "import yaml; print('ok')"
```

---

## Architecture Patterns

### Recommended Project Structure

```
tools/
└── unified_context.py    # UnifiedContextTool — new file only
mcp_server.py             # Add UnifiedContextTool registration (existing file, small change)
tests/
└── test_unified_context.py  # New test file (Wave 0 gap)
```

No new directories. One new tool file, one new test file, and a small addition to `mcp_server.py`.

### Pattern 1: Per-Call jcodemunch Connection with Timeout Guard

**What:** Open a fresh `MCPConnection` on each `execute()` call, wrapped in `asyncio.wait_for(..., timeout=3.0)`. Close it in a `finally` block.

**When to use:** When the external server (jcodemunch) may not be running. Per-call connections avoid resource leaks and fail-fast on unavailability.

**Why not persistent:** A persistent connection held across requests requires explicit lifecycle management (startup/shutdown hooks in `mcp_server.py`) and fails silently if jcodemunch restarts mid-session. Per-call is simpler and safer.

**Example:**

```python
# Source: tools/mcp_client.py MCPConnection pattern
async def _fetch_code_symbols(self, query: str, max_tokens: int) -> str | None:
    """Return jcodemunch search results, or None if unavailable."""
    config = {
        "command": "uvx",
        "args": ["jcodemunch-mcp"],
    }
    conn = MCPConnection("jcodemunch", config)
    try:
        await asyncio.wait_for(conn.connect(), timeout=3.0)
        result = await asyncio.wait_for(
            conn.call_tool("search_symbols", {"query": query, "repo": "local/agent42"}),
            timeout=5.0
        )
        return _truncate_to_budget(result, max_tokens)
    except Exception as e:
        logger.debug(f"jcodemunch unavailable: {e}")
        return None
    finally:
        try:
            await conn.disconnect()
        except Exception:
            pass
```

### Pattern 2: Source-Parallel Assembly with asyncio.gather()

**What:** Launch all sources concurrently, collect results, deduplicate, then assemble.

**When to use:** Context assembly involves I/O across 4+ sources (memory, jcodemunch, GSD files, effectiveness DB). Parallel is latency = max(slowest) not sum(all).

**Example:**

```python
# Based on architecture research ARCHITECTURE.md Pattern 3
async def execute(self, topic="", max_tokens=4000, task_type="", **kwargs):
    keywords = _extract_keywords(topic)
    inferred_type = task_type or _infer_task_type(topic)
    seen = set()  # SHA256 dedup set shared across sources

    # Budget allocation (D-13)
    budgets = {
        "memory":       int(max_tokens * 0.30),
        "code":         int(max_tokens * 0.25),
        "gsd":          int(max_tokens * 0.15),
        "git":          int(max_tokens * 0.10),
        "skills":       int(max_tokens * 0.10),
        "effectiveness":int(max_tokens * 0.10),
    }

    # Run all sources concurrently
    results = await asyncio.gather(
        self._assembler.execute(topic=topic, max_tokens=max_tokens, **kwargs),
        self._fetch_code_symbols(topic, budgets["code"]),
        self._fetch_gsd_state(keywords, budgets["gsd"]),
        self._fetch_effectiveness(inferred_type, budgets["effectiveness"]),
        return_exceptions=True,
    )
    # Assemble non-None, non-exception results
```

### Pattern 3: GSD State Reader — Glob + YAML Frontmatter Parse

**What:** Scan `.planning/workstreams/*/STATE.md` with `Path.glob()`, parse YAML frontmatter, find the one with `status != "Complete"`. Then read the active phase PLAN.md for open task list.

**When to use:** D-07 requires scanning for active workstream. The frontmatter structure is known from the STATE.md inspected in context setup.

**STATE.md frontmatter structure (verified):**

```yaml
---
gsd_state_version: 1.0
milestone: v3.0
status: Ready to plan          # Values: "Ready to plan", "Complete", etc.
stopped_at: Phase 4 context gathered (auto mode)
last_updated: "2026-03-25T15:44:40.818Z"
progress:
  total_phases: 4
  completed_phases: 3
---
```

**Example:**

```python
async def _fetch_gsd_state(self, keywords: list[str], max_tokens: int) -> str | None:
    """Return active GSD workstream context if query matches current phase."""
    workspace = Path(self._workspace)
    state_files = list(workspace.glob(".planning/workstreams/*/STATE.md"))
    for state_path in state_files:
        try:
            content = await _async_read(state_path)
            fm = _parse_yaml_frontmatter(content)
            if fm.get("status", "").lower() == "complete":
                continue
            # Found active workstream — check keyword relevance
            stopped_at = fm.get("stopped_at", "")
            # keyword match check...
```

### Pattern 4: Effectiveness Ranking Section

**What:** Call `EffectivenessStore.get_recommendations(task_type)` and format top tools as a context section. The store returns `[{tool_name, task_type, invocations, success_rate, avg_duration_ms}, ...]`.

**When to use:** Always when task type is determinable and store has >= 5 observations for the task type (the store's `min_observations` default).

**Example:**

```python
# Source: memory/effectiveness.py get_recommendations() signature
async def _fetch_effectiveness(self, task_type: str, max_tokens: int) -> str | None:
    if not self._effectiveness_store or not task_type:
        return None
    try:
        recs = await self._effectiveness_store.get_recommendations(
            task_type=task_type, top_k=3
        )
        if not recs:
            return None
        lines = []
        for r in recs:
            rate = int(r["success_rate"] * 100)
            lines.append(f"- **{r['tool_name']}**: {rate}% success on {task_type} tasks "
                        f"({r['invocations']} calls)")
        content = "\n".join(lines)
        return _truncate_to_budget(
            f"## Effective Tools for {task_type}\n\n{content}", max_tokens
        )
    except Exception as e:
        logger.debug(f"Effectiveness ranking failed: {e}")
        return None
```

### Pattern 5: Task Type Inference from Keywords

**What:** Reuse `WORK_TYPE_KEYWORDS` from `context-loader.py` mapped to Agent42's effectiveness task types. The hook's `detect_work_types()` function returns a set of work types (e.g., `{"tools", "security"}`). Map these to effectiveness task types (e.g., `"coding"`, `"debugging"`).

**Mapping verified from `tools/registry.py` `_CODE_TASK_TYPES`:**

```python
# _CODE_TASK_TYPES from tools/registry.py (existing, verified)
_CODE_TASK_TYPES = {"coding", "debugging", "refactoring", "app_create", "app_update", "project_setup"}

# Work type → effectiveness task type mapping (new, for UnifiedContextTool)
_WORK_TYPE_TO_TASK_TYPE = {
    "security":   "debugging",
    "tools":      "coding",
    "testing":    "debugging",
    "providers":  "coding",
    "dashboard":  "coding",
    "memory":     "coding",
    "skills":     "coding",
    "deployment": "project_setup",
    "config":     "project_setup",
    "async":      "coding",
}
```

### Anti-Patterns to Avoid

- **Persistent jcodemunch connection held open:** Complicates lifecycle management in `mcp_server.py` and fails silently on server restart. Use per-call connections with timeout instead.
- **Blocking the ContextAssemblerTool call while fetching jcodemunch:** Call both in parallel via `asyncio.gather()`. Total latency = max(slowest), not sum.
- **Adding jcodemunch for all queries:** Only fetch code symbols when `task_type` is in `_CODE_TASK_TYPES` or when `scope` includes `"code"`. Adding it to non-code queries (e.g., marketing, content) is pure token noise.
- **Modifying ContextAssemblerTool:** D-01 and D-02 lock this. Wrap, never modify.
- **Assuming jcodemunch is running:** Always wrap in `try/except` with `return None` fallback. D-05 mandates graceful degradation.
- **Using blocking YAML parser for frontmatter:** `yaml.safe_load()` is sync. For STATE.md parsing, read the file with `aiofiles` then parse synchronously — the parse itself is trivial CPU work, no I/O.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| jcodemunch MCP calls | Custom subprocess JSON-RPC | `MCPConnection` + `call_tool()` in `tools/mcp_client.py` | Already implemented with security validation, error handling, and timeout support |
| Memory context assembly | Any new memory search | Delegate to `ContextAssemblerTool.execute()` | Has SHA256 dedup, token budgeting, CLAUDE.md + MEMORY.md search, git history, skills — all tested |
| Content deduplication | Custom string similarity | `hashlib.sha256(text[:200])` set (already in `_search_memory()`) | Project-established pattern; SHA256 on first 200 chars is fast and sufficient for dedup |
| Token truncation | Character counting | `_truncate_to_budget(text, max_tokens)` from `context_assembler.py` | Already handles the 4-chars-per-token approximation; import directly |
| Keyword extraction | Regex from scratch | `_extract_keywords(text)` from `context_assembler.py` | Stop-word filtered, 3+ char minimum — exactly what's needed |
| Task type detection | New keyword map | `WORK_TYPE_KEYWORDS` from `context-loader.py` | Already covers all Agent42 work types with 150+ keywords tested |
| Effectiveness ranking | Custom scoring | `EffectivenessStore.get_recommendations(task_type)` | Full SQL aggregation with `min_observations` guard already implemented |

**Key insight:** This phase is almost entirely integration work. The hard parts (memory pipeline, MCP client, dedup, token budget, keyword extraction, effectiveness ranking) are all pre-built. The implementation is: wire these existing pieces together in `tools/unified_context.py`.

---

## Common Pitfalls

### Pitfall 1: jcodemunch MCP Connection Hangs

**What goes wrong:** `MCPConnection.connect()` blocks indefinitely when `uvx jcodemunch-mcp` subprocess starts but never sends the MCP initialize response (e.g., wrong uvx version, indexing in progress, process crashes silently).

**Why it happens:** The `stdio_client` context manager reads from stdout. If jcodemunch doesn't respond to `initialize`, the coroutine waits forever.

**How to avoid:** Wrap EVERY jcodemunch call in `asyncio.wait_for(..., timeout=3.0)`. This is the same pattern used in `scripts/jcodemunch_index.py` (threading timeout) and `_search_git()` in ContextAssemblerTool (`asyncio.wait_for(proc.communicate(), timeout=10)`).

**Warning signs:** Tool call takes > 3 seconds with no result.

### Pitfall 2: Budget Redistribution When Sources Return Nothing

**What goes wrong:** When jcodemunch is unavailable (25% budget slice unused), the total response is 25% shorter than max_tokens — a wasted opportunity when the user set max_tokens=4000 and only gets ~3000 tokens of content.

**Why it happens:** D-14 requires redistributing unused budget, but the naive approach of running all sources with their fixed budgets results in short output.

**How to avoid:** Collect results from all sources first, then redistribute unused budget proportionally to sources that returned content. The `_truncate_to_budget()` function can accept a larger budget on the second pass.

**Pattern:**

```python
# Two-pass approach: collect then redistribute
active_sources = [(name, result) for name, result in zip(budget_keys, results)
                  if result is not None]
# Redistribute unused slices to active sources proportionally
total_used = sum(budgets[name] for name, _ in active_sources)
scale = max_tokens / max(total_used, 1)
for name, content in active_sources:
    final_budgets[name] = int(budgets[name] * scale)
```

### Pitfall 3: STATE.md Glob Finds Multiple Active Workstreams

**What goes wrong:** If multiple workstreams have `status != Complete` (e.g., a paused workstream from months ago), the GSD source picks the wrong one.

**Why it happens:** The `glob(".planning/workstreams/*/STATE.md")` returns all matches. The "active" one is ambiguous when multiple are incomplete.

**How to avoid:** Use `stopped_at` and `last_updated` from frontmatter to select the most recently updated non-complete workstream. Parse `last_updated` as an ISO timestamp and take the max.

### Pitfall 4: `context` Tool Name Collision

**What goes wrong:** `UnifiedContextTool` registered as `agent42_context` in MCP, but `ContextAssemblerTool` is registered as `context`. MCP tool names are prefixed with `agent42_` by `to_mcp_schema()`. This means `ContextAssemblerTool` becomes `agent42_context` in MCP — the same name as the new tool.

**Why it happens:** `to_mcp_schema()` in `tools/base.py` line 74: `f"{prefix}_{self.name}"` — prefix defaults to "agent42". `ContextAssemblerTool.name` returns `"context"`, so its MCP name is `agent42_context`. The new `UnifiedContextTool.name` must return `"agent42_context"` to match D-15 — but the prefix is added automatically.

**How to avoid:** `UnifiedContextTool.name` property must return `"unified_context"` (not `"agent42_context"`). The `to_mcp_schema()` prefix will produce `"agent42_unified_context"` in the MCP protocol. The MCP tool exposed to Claude Code is `agent42_unified_context`. **OR** if D-15 literally requires the tool to be called `agent42_context` from Claude Code's perspective, then `UnifiedContextTool.name` returns `"context"` and `ContextAssemblerTool` must be unregistered or renamed.

**Research finding:** Based on D-16 ("Keep existing `context` tool registered separately"), the correct interpretation is:
- `ContextAssemblerTool.name = "context"` → MCP name: `agent42_context`
- `UnifiedContextTool.name = "unified_context"` → MCP name: `agent42_unified_context`

This satisfies D-16 (no breaking change to existing `context` tool) but conflicts with D-15 which says register as `agent42_context`. The planner must resolve this: either the new tool is `agent42_unified_context` (safest, no collision), or the old `context` tool gets renamed to `agent42_legacy_context` (breaking change, contradicts D-16).

**Recommendation:** Name `UnifiedContextTool.name = "unified_context"` → exposed as `agent42_unified_context`. This is the only collision-free option that satisfies D-16.

### Pitfall 5: `asyncio.gather(return_exceptions=True)` Swallows Critical Errors

**What goes wrong:** Using `return_exceptions=True` in `asyncio.gather()` means a runtime error in `_assembler.execute()` (the base ContextAssemblerTool) returns an Exception object silently rather than raising. The response appears empty without logging the cause.

**How to avoid:** Check each result after gather: `if isinstance(result, Exception): logger.warning(...)`. The base assembler failure is not fatal but should be logged at WARNING, not DEBUG.

### Pitfall 6: YAML Frontmatter Parse Failure on State Files

**What goes wrong:** `yaml.safe_load()` raises if the STATE.md has YAML syntax errors (e.g., unquoted colons in strings like `stopped_at: Phase 4: context gathered`).

**Why it happens:** STATE.md frontmatter is maintained by GSD tooling, which sometimes includes colons in `stopped_at` values.

**How to avoid:** Wrap YAML parse in `try/except yaml.YAMLError`. On failure, fall back to regex extraction of `status:` value from the raw frontmatter string.

---

## Code Examples

Verified patterns from the codebase:

### MCPConnection Call Pattern (from tools/mcp_client.py)

```python
# Source: tools/mcp_client.py lines 114-126
async def call_tool(self, tool_name: str, arguments: dict) -> str:
    if not self._session:
        raise RuntimeError(f"MCP server {self.name} not connected")
    result = await self._session.call_tool(tool_name, arguments=arguments)
    texts = []
    for block in result.content:
        if hasattr(block, "text"):
            texts.append(block.text)
    return "\n".join(texts) if texts else str(result)
```

### ContextAssemblerTool Delegation Pattern

```python
# UnifiedContextTool wraps ContextAssemblerTool (D-01 through D-03)
# The base tool handles memory + docs + git + skills unchanged.
# We call it and then append additional sections.

class UnifiedContextTool(Tool):
    requires = ["memory_store", "skill_loader", "workspace"]

    def __init__(self, memory_store=None, skill_loader=None, workspace="",
                 effectiveness_store=None, **kwargs):
        self._workspace = workspace
        self._effectiveness_store = effectiveness_store
        # Delegate to existing ContextAssemblerTool for base sources
        self._assembler = ContextAssemblerTool(
            memory_store=memory_store,
            skill_loader=skill_loader,
            workspace=workspace,
        )

    @property
    def name(self) -> str:
        return "unified_context"  # MCP name: agent42_unified_context
```

### EffectivenessStore.get_recommendations() Signature (from memory/effectiveness.py)

```python
# Source: memory/effectiveness.py lines 206-243
async def get_recommendations(
    self,
    task_type: str,
    min_observations: int = 5,
    top_k: int = 3,
) -> list:
    # Returns: [{tool_name, task_type, invocations, success_rate, avg_duration_ms}, ...]
    # Returns [] on insufficient data or any failure
```

### SHA256 Deduplication Pattern (from tools/context_assembler.py)

```python
# Source: tools/context_assembler.py lines 152-157
# The seen set is shared across ALL sources for cross-source dedup
h = hashlib.sha256(text[:200].encode()).hexdigest()[:16]
if h in seen:
    continue
seen.add(h)
```

### Token Budget Constants (from tools/context_assembler.py)

```python
# Source: tools/context_assembler.py lines 26-29 (existing, DO NOT change these)
_BUDGET_MEMORY = 0.35  # ContextAssemblerTool budget — unchanged
_BUDGET_DOCS   = 0.25
_BUDGET_GIT    = 0.20
_BUDGET_SKILLS = 0.20

# New UnifiedContextTool budget (D-13) — separate constants in unified_context.py
_UCT_BUDGET_MEMORY      = 0.30
_UCT_BUDGET_CODE        = 0.25
_UCT_BUDGET_GSD         = 0.15
_UCT_BUDGET_GIT         = 0.10
_UCT_BUDGET_SKILLS      = 0.10
_UCT_BUDGET_EFFECTIVENESS = 0.10
```

### MCP Tool Registration Pattern (from mcp_server.py lines 254-266)

```python
# Source: mcp_server.py _build_registry() pattern for ContextAssemblerTool
ContextAssemblerTool = _safe_import("tools.context_assembler", "ContextAssemblerTool")
_register(
    ContextAssemblerTool(
        memory_store=memory_store,
        skill_loader=None,  # Note: skill_loader added in _create_server()
        workspace=workspace_str,
    )
    if ContextAssemblerTool
    else None
)

# New UnifiedContextTool registration (add after ContextAssemblerTool block)
UnifiedContextTool = _safe_import("tools.unified_context", "UnifiedContextTool")
effectiveness_store = None  # optional; initialize if .agent42/effectiveness.db exists
_register(
    UnifiedContextTool(
        memory_store=memory_store,
        skill_loader=None,
        workspace=workspace_str,
        effectiveness_store=effectiveness_store,
    )
    if UnifiedContextTool
    else None
)
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| ContextAssemblerTool with 4 sources | UnifiedContextTool with 6 sources | Phase 4 | Code symbols + GSD state added |
| Fixed 4-source budget (35/25/20/20) | Rebalanced 6-source budget (30/25/15/10/10/10) | Phase 4 | GSD + effectiveness get budget slices |
| No jcodemunch in context API | jcodemunch via MCP-to-MCP call | Phase 4 | Code symbol search in context |
| No effectiveness injection in context | EffectivenessStore ranking | Phase 4 | Best tools surfaced per task type |

---

## Open Questions

1. **Tool name collision — `agent42_context` vs `agent42_unified_context`**
   - What we know: D-15 says register as `agent42_context`; D-16 says keep existing `context` tool unchanged; `to_mcp_schema()` auto-prefixes with `agent42_`; existing `ContextAssemblerTool.name = "context"` → MCP name `agent42_context`
   - What's unclear: Does D-15 mean the *internal tool name* is `agent42_context`, or the *MCP-exposed name* is `agent42_context`?
   - Recommendation: Planner should resolve as: `UnifiedContextTool.name = "unified_context"` (MCP: `agent42_unified_context`). Explicitly documents in plan that D-15 is satisfied by convention (the tool is the "agent42 context" tool, just namespaced as `unified_context` internally to avoid collision with existing `context`).

2. **effectiveness_store injection in mcp_server.py**
   - What we know: `EffectivenessStore` exists in `memory/effectiveness.py`; `ToolRegistry` already accepts `effectiveness_store` parameter (line 53 of `tools/registry.py`); `_build_registry()` in `mcp_server.py` does NOT currently instantiate an `EffectivenessStore` and pass it to the registry
   - What's unclear: Where exactly should `effectiveness_store` be instantiated in `mcp_server.py` — at the registry level (current pattern for tool-level tracking) or passed directly to `UnifiedContextTool`?
   - Recommendation: Instantiate `EffectivenessStore(workspace / ".agent42" / "effectiveness.db")` in `_build_registry()` and pass it directly to `UnifiedContextTool` constructor. Separate from the registry-level instance (which tracks invocations). Two separate instances of `EffectivenessStore` pointing to the same DB file is safe — `aiosqlite` handles concurrent connections.

3. **GSD state: does ContextAssemblerTool already search `.planning/` files?**
   - What we know: `_search_docs()` only looks at `CLAUDE.md` and `.agent42/memory/MEMORY.md` (lines 168-170 of context_assembler.py)
   - What's unclear: Should the GSD source read from the delegated ContextAssemblerTool result or bypass it entirely?
   - Recommendation: GSD state is a separate source added by UnifiedContextTool, not part of ContextAssemblerTool's doc search. No overlap.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `uvx jcodemunch-mcp` | CTX-01 code symbols | Check on target | via uvx | D-05: graceful omission |
| `aiofiles` | GSD state async reads | Already in requirements.txt | existing | None needed |
| `mcp` SDK | jcodemunch MCP client | Already imported in tools/mcp_client.py | existing | None needed |
| `aiosqlite` | EffectivenessStore | `AIOSQLITE_AVAILABLE` guard in effectiveness.py | existing | Returns `[]` gracefully |
| PyYAML (`yaml`) | STATE.md frontmatter parse | Check in requirements.txt | existing | Regex fallback for status field |

**Missing dependencies with no fallback:** None identified.

**Missing dependencies with fallback:**
- `uvx jcodemunch-mcp`: If not installed/indexed, D-05 mandates omitting code symbols and returning other sources normally. Test this path explicitly.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest + pytest-asyncio (asyncio_mode = "auto") |
| Config file | `pyproject.toml` |
| Quick run command | `python -m pytest tests/test_unified_context.py -x -q` |
| Full suite command | `python -m pytest tests/ -q --ignore=tests/test_app_git.py` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| CTX-01 | `agent42_context` returns jcodemunch symbols merged with memory, no duplicates | unit (mock MCPConnection) | `pytest tests/test_unified_context.py::TestUnifiedContextTool::test_code_symbols_merged -x` | Wave 0 gap |
| CTX-01 | Dedup: same content from jcodemunch and memory appears only once | unit | `pytest tests/test_unified_context.py::TestUnifiedContextTool::test_deduplication_across_sources -x` | Wave 0 gap |
| CTX-02 | Active GSD workstream state included when query matches current phase | unit (tmp_path STATE.md) | `pytest tests/test_unified_context.py::TestGSDStateReader::test_active_workstream_returned -x` | Wave 0 gap |
| CTX-02 | GSD state excluded when query does NOT match phase keywords | unit | `pytest tests/test_unified_context.py::TestGSDStateReader::test_irrelevant_query_omits_gsd -x` | Wave 0 gap |
| CTX-03 | Effectiveness section ranks tools by success_rate for task type | unit (mock EffectivenessStore) | `pytest tests/test_unified_context.py::TestEffectivenessRanking::test_tools_ranked_by_success_rate -x` | Wave 0 gap |
| CTX-03 | Effectiveness omitted when no history for task type | unit | `pytest tests/test_unified_context.py::TestEffectivenessRanking::test_empty_recommendations_omitted -x` | Wave 0 gap |
| Success 4 | jcodemunch unavailable → response still returns memory + GSD without error | unit (mock connect raises) | `pytest tests/test_unified_context.py::TestGracefulDegradation::test_jcodemunch_unavailable -x` | Wave 0 gap |

### Sampling Rate

- **Per task commit:** `python -m pytest tests/test_unified_context.py -x -q`
- **Per wave merge:** `python -m pytest tests/ -q --ignore=tests/test_app_git.py`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/test_unified_context.py` — covers all CTX-01, CTX-02, CTX-03 requirements (all 7 tests above)
- [ ] No new conftest.py fixtures needed — `tmp_path` and existing `mock_tool` patterns suffice

*(Existing test infrastructure covers framework setup; only the test file is new.)*

---

## Project Constraints (from CLAUDE.md)

These directives from `CLAUDE.md` apply to this phase and must be verified in every plan task:

| Directive | Applies To |
|-----------|-----------|
| All I/O is async — never use blocking file open | `_fetch_gsd_state()` file reads must use `aiofiles` |
| Never disable sandbox in production | Not relevant (no sandbox changes) |
| `requires = [...]` for ToolContext injection | `UnifiedContextTool.requires = ["memory_store", "skill_loader", "workspace"]` |
| Graceful degradation for all optional deps | jcodemunch, effectiveness_store both optional |
| After writing code: `make format`, `pytest -x -q` | Per plan task commit |
| Every new module needs a `tests/test_*.py` file | `tests/test_unified_context.py` is a Wave 0 gap |
| Never log API keys, passwords, or tokens | Not relevant (no auth changes) |
| Use GSD for multi-step work | Already in GSD — this constraint is satisfied |

---

## Sources

### Primary (HIGH confidence)

- `tools/context_assembler.py` — Full implementation of existing ContextAssemblerTool (4 sources, budget constants, SHA256 dedup, `_extract_keywords`, `_truncate_to_budget`)
- `tools/mcp_client.py` — MCPConnection class: `connect()`, `call_tool()`, `disconnect()` — exact jcodemunch integration pattern
- `memory/effectiveness.py` — `EffectivenessStore.get_recommendations(task_type)` full implementation
- `mcp_server.py` (lines 86-291) — `_build_registry()` tool registration pattern; `_safe_import()` graceful skip
- `tools/registry.py` (lines 39-47) — `_CODE_TASK_TYPES` set for task type inference
- `.claude/hooks/context-loader.py` — `WORK_TYPE_KEYWORDS` (12 types, 150+ keywords); `detect_work_types()` function
- `tools/base.py` (lines 68-78) — `to_mcp_schema()` auto-prefix behavior
- `.planning/phases/04-context-engine/04-CONTEXT.md` — All 17 locked decisions
- `.planning/workstreams/gsd-and-jcodemunch-integration/research/ARCHITECTURE.md` — Unified Context Engine architecture, parallel source assembly pattern, token budget design
- `.planning/workstreams/gsd-and-jcodemunch-integration/REQUIREMENTS.md` — CTX-01, CTX-02, CTX-03 definitions

### Secondary (MEDIUM confidence)

- `.planning/workstreams/gsd-and-jcodemunch-integration/STATE.md` — STATE.md frontmatter structure (verified by inspection)
- `tests/test_context_loader.py`, `tests/test_context_loader_jcodemunch.py` — Test conventions (class-based, tmp_path, no external calls)

### Tertiary (LOW confidence)

- None — all critical findings are from direct codebase inspection (HIGH).

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — zero new deps, all existing packages verified importable
- Architecture: HIGH — all integration points inspected directly in source files
- Pitfalls: HIGH — pitfalls derived from direct code inspection (name collision from `to_mcp_schema()`, timeout gap from `_search_git()` pattern)

**Research date:** 2026-03-25
**Valid until:** 2026-04-25 (stable codebase, no external API changes expected)
