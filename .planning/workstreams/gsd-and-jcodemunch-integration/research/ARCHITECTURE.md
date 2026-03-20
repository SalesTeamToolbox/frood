# Architecture Research

**Domain:** AI Agent Platform — GSD & jcodemunch Integration
**Researched:** 2026-03-17
**Confidence:** HIGH (based on direct codebase analysis + verified external sources)

## Existing Architecture Map

Before describing new components, the current system must be understood precisely. Every new feature integrates into existing seams.

### Current System Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│                        Claude Code (Client)                          │
│           Uses .mcp.json to connect to local MCP server              │
└───────────────────────────┬──────────────────────────────────────────┘
                            │ stdio transport
┌───────────────────────────▼──────────────────────────────────────────┐
│                      mcp_server.py (MCP Layer)                       │
│   36+ tools exposed as MCP tools | 43 skills as MCP prompts          │
│   MCPRegistryAdapter → ToolRegistry (tools/registry.py)              │
└───┬──────────────┬──────────────────────┬────────────────────────────┘
    │              │                      │
    ▼              ▼                      ▼
┌────────┐  ┌──────────────┐  ┌──────────────────────────────────┐
│ Tools  │  │ ContextAssem │  │          Memory Stack            │
│ 50+    │  │ blerTool     │  │  ┌──────────────────────────┐    │
│ files  │  │ (tools/      │  │  │ MemoryStore (store.py)   │    │
│ in     │  │ context_     │  │  │ MEMORY.md + HISTORY.md   │    │
│ tools/ │  │ assembler.py)│  │  └──────────┬───────────────┘    │
└────────┘  └──────────────┘  │             │                    │
                              │  ┌──────────▼───────────────┐    │
                              │  │ EmbeddingStore           │    │
                              │  │ (memory/embeddings.py)   │    │
                              │  │ ONNX (384d) or OpenAI    │    │
                              │  └──────────┬───────────────┘    │
                              │             │                    │
                              │  ┌──────────▼───────────────┐    │
                              │  │ QdrantStore              │    │
                              │  │ (memory/qdrant_store.py) │    │
                              │  │ 4 collections: memory,   │    │
                              │  │ history, conversations,  │    │
                              │  │ knowledge                │    │
                              │  └──────────────────────────┘    │
                              └──────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────┐
│                   .claude/hooks/ (Claude Code hooks)                 │
│  context-loader    memory-recall    jcodemunch-reindex               │
│  security-monitor  learning-engine  memory-learn                     │
│  test-validator    session-handoff  jcodemunch-token-tracker         │
└──────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────┐
│                    FastAPI Dashboard (server.py)                     │
│   JWT auth (bcrypt) | WebSocket heartbeat | REST API                 │
│   agent_manager.py | project_manager.py | task_context.py            │
└──────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────┐
│                     NodeSyncTool (tools/node_sync.py)                │
│   rsync MEMORY.md + HISTORY.md | SSH reindex trigger                 │
│   Strategy: markdown = source of truth, vectors re-derived           │
└──────────────────────────────────────────────────────────────────────┘
```

### Existing Integration Points (What New Features Must Respect)

| Integration Point | Where | Contract |
|-------------------|-------|----------|
| ToolRegistry | `tools/registry.py` | `Tool` ABC, `requires` for injection |
| ToolContext injection | `tools/context.py` | workspace, memory_store, skill_loader |
| MemoryStore | `memory/store.py` | `.semantic_search()`, `.log_event_semantic()` |
| QdrantStore collections | `memory/qdrant_store.py` | 4 named suffixes (MEMORY/HISTORY/CONVERSATIONS/KNOWLEDGE) |
| EmbeddingStore | `memory/embeddings.py` | ONNX (384d) or OpenAI (1536d) — not both at once |
| Settings frozen dataclass | `core/config.py` | Must add fields + `os.getenv()`, never mutate |
| Hook protocol | `.claude/hooks/*.py` | stdin JSON, stderr output, exit code contract |
| MCP server | `mcp_server.py` | `to_mcp_schema()` on Tool, `_safe_import()` |
| FastAPI auth | `server.py` | JWT via `python-jose`, bcrypt passwords |

---

## New Components Architecture

### 1. Bi-directional Qdrant Sync Layer

**Current gap:** NodeSyncTool only syncs flat markdown files (MEMORY.md, HISTORY.md). Qdrant vectors are re-derived locally after sync. This loses vector metadata (lifecycle scores, recall counts, task_type tags, confidence fields).

**New component:** `tools/qdrant_sync.py` — `QdrantSyncTool`

**Integration approach:**

Qdrant's native snapshot API (`create_snapshot()`, `recover_from_snapshot()`) is the correct mechanism for collection-level sync. However, snapshots require server mode (not embedded), and the VPS already runs Qdrant in server mode. The laptop uses embedded mode.

The sync strategy must account for this asymmetry:

```
Laptop (embedded Qdrant at .agent42/qdrant/)
    ↕ via QdrantSyncTool (new)
VPS (server Qdrant at localhost:6333 via SSH tunnel)
```

**Sync operations:**

```
push_collection(collection, target_host)
    → export collection as JSONL payload dump (not snapshot — embedded can export)
    → scp payload dump to remote
    → remote imports via HTTP API upsert

pull_collection(collection, source_host)
    → SSH tunnel to remote Qdrant port 6333
    → scroll all points from remote collection
    → upsert into local embedded Qdrant

sync_all(strategy="merge")
    → For each collection in [MEMORY, HISTORY, CONVERSATIONS, KNOWLEDGE]:
        → compare point counts + latest timestamp
        → merge: newer-timestamp-wins per point_id
        → upsert both sides with merged result
```

**Conflict resolution:** Point IDs are deterministic UUIDs (uuid5 from text content — see `_make_point_id`). The same text produces the same point ID on both nodes. Conflicts are resolved by `payload["timestamp"]` — higher timestamp wins. Lifecycle metadata (recall_count, confidence) is merged by taking the maximum value.

**Component boundaries:**

```
QdrantSyncTool
├── requires: ["workspace"]  (no memory_store — operates directly on Qdrant)
├── uses: QdrantStore directly (bypasses MemoryStore)
├── uses: SSH subprocess for tunnel + SCP (pattern: tools/ssh_tool.py)
└── triggers: local EmbeddingStore re-verify after pull (optional validation)
```

**Does NOT replace NodeSyncTool.** Both run independently. Recommendation: after Qdrant sync, skip the rsync reindex step in NodeSyncTool (vectors already synced). Add a `--skip-reindex` flag to `node_sync merge`.

---

### 2. Unified Context Engine

**Current gap:** Context comes from three independent systems:
- jcodemunch MCP server (code symbols, file outlines, text search)
- ContextAssemblerTool (memory + git + skills, `tools/context_assembler.py`)
- memory-recall hook (Qdrant semantic search at prompt-submit time)

These don't coordinate. A Claude Code session may get jcodemunch results, then duplicate memory results from the hook, with no deduplication or token budget enforcement across sources.

**New component:** `tools/unified_context.py` — `UnifiedContextTool`

**Architecture:**

```
UnifiedContextTool.execute(query, sources=["memory","code","gsd","skills"], max_tokens=4000)
    │
    ├── MemorySource
    │   └── calls memory_store.build_context_semantic(query, top_k=5)
    │       → existing MemoryStore + QdrantStore pipeline (unchanged)
    │
    ├── CodeSource
    │   └── calls jcodemunch MCP tools via tools/mcp_client.py
    │       search_symbols(query) + get_file_outline(relevant_files)
    │       → deduplicated against MemorySource results
    │
    ├── GSDSource
    │   └── reads .planning/workstreams/*/STATE.md + active phase PLAN.md
    │       → returns current milestone context + open tasks
    │
    └── SkillsSource
        └── existing skill_loader.get_relevant_skills(query) logic
            (already in ContextAssemblerTool, extracted here)
```

**Token budget enforcement:** Budget fractions remain `_BUDGET_MEMORY=0.35, _BUDGET_DOCS=0.25, _BUDGET_GIT=0.20, _BUDGET_SKILLS=0.20` from context_assembler.py. GSD source replaces part of the docs budget (`.20` split: `.10` git + `.10` GSD).

**Integration into hook pipeline:**

The `context-loader.py` hook (UserPromptSubmit) currently loads from `.claude/reference/` files. It should optionally call UnifiedContextTool when Agent42 MCP is available. This is the only hook that needs modification — add a fast path:

```python
# In context-loader.py (UserPromptSubmit hook)
# If agent42 MCP server is reachable, call unified_context tool
# Otherwise: fall back to current reference file loading
```

**Does NOT replace ContextAssemblerTool.** UnifiedContextTool wraps it. ContextAssemblerTool keeps its `context` MCP tool name and existing behavior. UnifiedContextTool is a new `unified_context` MCP tool that adds jcodemunch and GSD sources on top.

---

### 3. RBAC Layer

**Current gap:** FastAPI dashboard uses single-user JWT auth. All authenticated users get full access. No per-feature or per-agent permission control.

**New component:** `core/rbac.py` — `RBACStore` + `require_role` dependency

**Architecture approach:** Add roles to JWT payload. Use FastAPI dependency injection for enforcement. No external auth service — Agent42 is a self-hosted tool.

```
Roles (ordered, additive):
    viewer  → read-only dashboard, no tool execution, no config
    operator → viewer + run agents, trigger tasks, use tools
    admin   → operator + manage agents, configure settings, create users
    superadmin → admin + security config, RBAC management, system ops
```

**JWT payload change:**

```python
# Current token payload (server.py create_access_token)
{"sub": username, "exp": expiry}

# New payload (backward compatible — missing "role" = "admin" for migration)
{"sub": username, "role": "admin", "exp": expiry}
```

**Enforcement via FastAPI dependency:**

```python
# core/rbac.py
def require_role(minimum_role: str):
    """FastAPI dependency factory for role enforcement."""
    async def _check(token: str = Depends(oauth2_scheme)) -> dict:
        payload = verify_token(token)  # existing verify_token()
        role = payload.get("role", "admin")  # backward compat default
        if ROLE_ORDER.index(role) < ROLE_ORDER.index(minimum_role):
            raise HTTPException(403, "Insufficient permissions")
        return payload
    return _check

# Usage in server.py endpoints:
@app.get("/api/admin/settings")
async def get_settings(user=Depends(require_role("admin"))):
    ...
```

**Storage:** User-role mappings stored in `.agent42/settings.json` (already used for device auth). No new store needed.

**MCP tool RBAC:** The MCP server does not use the JWT auth path — it runs as a local stdio process trusted by the OS user. MCP tool restrictions are enforced via the existing `ToolRateLimiter` and `CommandFilter` layers, not RBAC. RBAC applies only to the FastAPI dashboard.

**Migration path:** On first startup after upgrade, all existing JWT tokens are treated as `admin` (backward compat default). New tokens issued after upgrade include explicit role claim.

---

### 4. Multi-Agent Orchestration

**Current gap:** The existing `cowork` skill + `subagent` tool enable single-agent delegation and VPS handoff. There is no native concurrent multi-agent execution, shared state, or result aggregation.

**Existing building blocks to reuse:**

| Existing Component | How It's Used |
|--------------------|---------------|
| `core/agent_manager.py` | Agent definitions, templates, PROVIDER_MODELS |
| `core/agent_runtime.py` | Single-agent execution loop |
| `tools/subagent.py` | Spawn sub-tasks within a single agent |
| `tools/team_tool.py` | Existing team coordination tool |
| `core/task_context.py` | Task ID/type propagation via contextvars |
| `asyncio.gather()` | Parallel async execution (Python stdlib) |

**New component:** `core/orchestrator.py` — `MultiAgentOrchestrator`

**Architecture:**

```
MultiAgentOrchestrator
│
├── plan(task) → AgentPlan
│   └── Uses LLM (gemini-2-flash) to decompose task into sub-tasks
│       Returns: list of {agent_type, task, dependencies, output_schema}
│
├── dispatch(plan) → asyncio.gather(all agents)
│   └── For each independent sub-task (no dependencies):
│       AgentRuntime.run(agent_config, task) via create_task()
│       Stagger launches by AGENT_DISPATCH_DELAY (pitfall #93)
│
├── aggregate(results) → str
│   └── Merge outputs from all agents using result schemas
│       Conflict resolution: LLM-mediated synthesis
│
└── SharedStateStore (new)
    └── Redis-backed if available, asyncio.Queue fallback
        Agents can read/write shared context during execution
        Namespace: {orchestration_id}/{key}
```

**SharedStateStore design:**

```
SharedStateStore
├── Redis path: HSET agent42:orch:{id} key value (with TTL)
├── Fallback: in-process asyncio.Queue per orchestration_id
└── API: get(id, key), set(id, key, value), subscribe(id, key)
```

**Integration with existing agent dispatch:** The current `agent42.py` `_process_queue()` method already staggers agent dispatch with `AGENT_DISPATCH_DELAY`. MultiAgentOrchestrator uses the same mechanism but adds parallel execution awareness — it tracks which agents are running concurrently and only staggers when multiple agents target the same LLM provider (to avoid TPM rate limits, pitfall #93).

**MCP exposure:** `orchestrate` tool added to mcp_server.py. Claude Code can call it to spin up agent teams.

---

## Full System Overview (Post-Integration)

```
┌──────────────────────────────────────────────────────────────────────┐
│                        Claude Code (Client)                          │
└───────────────────────────┬──────────────────────────────────────────┘
                            │ stdio transport
┌───────────────────────────▼──────────────────────────────────────────┐
│                       mcp_server.py (unchanged interface)            │
│                                                                      │
│  New MCP tools:                                                      │
│    agent42_qdrant_sync     ← QdrantSyncTool                          │
│    agent42_unified_context ← UnifiedContextTool                      │
│    agent42_orchestrate     ← MultiAgentOrchestrator                  │
│  Existing tools unchanged (50+ tools, 43 skills)                     │
└───┬──────────────┬──────────────────────┬────────────────────────────┘
    │              │                      │
    ▼              ▼                      ▼
┌────────┐  ┌──────────────────────┐  ┌──────────────────────────────┐
│ Tools  │  │  Unified Context     │  │     Multi-Agent              │
│ (incl. │  │  Engine              │  │     Orchestrator             │
│ Qdrant │  │  ┌────────────────┐  │  │  ┌────────────────────────┐  │
│ Sync)  │  │  │MemorySource    │  │  │  │ AgentPlan              │  │
└────────┘  │  │ (→MemoryStore) │  │  │  │ parallel dispatch      │  │
            │  ├────────────────┤  │  │  │ SharedStateStore       │  │
            │  │CodeSource      │  │  │  └────────────────────────┘  │
            │  │ (→jcodemunch)  │  │  └──────────────────────────────┘
            │  ├────────────────┤  │
            │  │GSDSource       │  │
            │  │ (→.planning/)  │  │
            │  ├────────────────┤  │
            │  │SkillsSource    │  │
            │  │ (→skill_loader)│  │
            │  └────────────────┘  │
            └──────────────────────┘

┌──────────────────────────────────────────────────────────────────────┐
│                     Memory Stack (largely unchanged)                 │
│                                                                      │
│  MemoryStore ─→ EmbeddingStore ─→ QdrantStore (4 collections)       │
│                                        ↑                             │
│                               QdrantSyncTool (new)                  │
│                               syncs vectors between nodes            │
│                               (supplements NodeSyncTool)             │
└──────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────┐
│              FastAPI Dashboard (RBAC layer added)                    │
│                                                                      │
│  core/rbac.py: require_role() dependency                             │
│  Roles: viewer → operator → admin → superadmin                       │
│  JWT payload: adds "role" claim (backward compat default: admin)     │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Component Boundaries

| New Component | File | Depends On | New Dependencies |
|---------------|------|------------|------------------|
| QdrantSyncTool | `tools/qdrant_sync.py` | QdrantStore, SSH subprocess | None (stdlib only) |
| UnifiedContextTool | `tools/unified_context.py` | MemoryStore, SkillLoader, mcp_client | None |
| GSDSource | `tools/unified_context.py` (inner class) | Path(.planning/) only | None |
| RBACStore | `core/rbac.py` | Settings, existing JWT (python-jose) | None |
| require_role() | `core/rbac.py` | RBACStore, FastAPI Depends | None |
| MultiAgentOrchestrator | `core/orchestrator.py` | AgentRuntime, Redis (optional) | None new |
| SharedStateStore | `core/orchestrator.py` | Redis (optional), asyncio | None |

**Zero new Python package dependencies** is the goal. All new components use existing dependencies: `qdrant-client`, `python-jose`, `aiofiles`, `httpx`, `redis`, `asyncio`. This is achievable because the patterns needed (scrolling Qdrant points, JWT role claims, asyncio.gather) are already supported by installed packages.

---

## Data Flow Changes

### Qdrant Sync Flow

```
QdrantSyncTool.execute(action="merge", host="agent42-prod")
    │
    ├── Open SSH tunnel: ssh -L 16333:localhost:6333 agent42-prod -N
    │
    ├── For each collection in [MEMORY, HISTORY, CONVERSATIONS, KNOWLEDGE]:
    │   ├── local_points = qdrant_store.scroll_all(collection)
    │   ├── remote_points = QdrantClient(url="localhost:16333").scroll_all(collection)
    │   ├── merged = merge_by_point_id(local_points, remote_points)
    │   ├── qdrant_store.upsert_vectors(collection, merged)       # local update
    │   └── remote_client.upsert(collection_name, merged)         # remote update
    │
    └── Close SSH tunnel
        (NodeSyncTool markdown sync runs separately — no change needed)
```

### Unified Context Assembly Flow

```
UnifiedContextTool.execute(query="fix auth bug", max_tokens=4000)
    │
    ├── [async] MemorySource: memory_store.build_context_semantic(query, top_k=5)
    │    budget: 1400 tokens (35%)
    │
    ├── [async] CodeSource: mcp_client.call("jcodemunch/search_symbols", {query})
    │    budget: 800 tokens (20%) — only if jcodemunch reachable
    │
    ├── [async] GSDSource: read active workstream STATE.md + current PLAN.md
    │    budget: 400 tokens (10%)
    │
    ├── [async] SkillsSource: skill_loader.get_relevant_skills(query)
    │    budget: 800 tokens (20%) — maps to existing _BUDGET_SKILLS
    │
    └── Deduplicate + assemble within token budget
        Return formatted context string
```

### Multi-Agent Execution Flow

```
MultiAgentOrchestrator.run(goal="refactor auth module")
    │
    ├── plan(goal)
    │   └── LLM call: decompose into [coder, tester, reviewer] sub-tasks
    │
    ├── dispatch(plan)
    │   ├── asyncio.create_task(AgentRuntime.run(coder_config, coder_task))
    │   ├── await asyncio.sleep(AGENT_DISPATCH_DELAY)   # pitfall #93
    │   ├── asyncio.create_task(AgentRuntime.run(tester_config, tester_task))
    │   └── asyncio.gather(*all_tasks)
    │
    ├── SharedStateStore: agents read/write shared context
    │   └── Redis HSET agent42:orch:{id} {key} {value}
    │
    └── aggregate(results)
        └── LLM synthesis of outputs → final result
```

---

## Recommended Project Structure (New Files Only)

```
tools/
├── qdrant_sync.py         # QdrantSyncTool — bi-directional Qdrant sync
├── unified_context.py     # UnifiedContextTool — cross-source context assembly
core/
├── rbac.py                # RBACStore, require_role(), role constants
├── orchestrator.py        # MultiAgentOrchestrator, SharedStateStore, AgentPlan
```

No new directories. All new code fits existing module conventions. Four files total for the four new feature areas.

---

## Architectural Patterns

### Pattern 1: Scroll-Based Qdrant Export

**What:** Use `qdrant_client.scroll()` with `with_vectors=True` to dump all points from a collection for sync. Unlike snapshots, scroll works with embedded mode.

**When to use:** Any time you need to export vectors from an embedded Qdrant instance (laptop) to a server-mode Qdrant (VPS).

**Trade-offs:** Slower than snapshot for large collections (scroll is paginated), but works without server mode. For Agent42's collection sizes (thousands, not millions of vectors), scroll performance is acceptable.

**Example:**
```python
async def scroll_all_points(client, collection_name: str) -> list:
    """Scroll all points from a Qdrant collection."""
    all_points = []
    offset = None
    while True:
        result, next_offset = client.scroll(
            collection_name=collection_name,
            with_vectors=True,
            with_payload=True,
            limit=100,
            offset=offset,
        )
        all_points.extend(result)
        if next_offset is None:
            break
        offset = next_offset
    return all_points
```

### Pattern 2: Role Claim in JWT (Backward Compatible)

**What:** Add `role` to JWT payload. Default to `"admin"` when `role` key is absent (all existing tokens). New tokens always include explicit role.

**When to use:** Any FastAPI endpoint needing per-role access control.

**Trade-offs:** Simple and self-contained. No external auth service. The downside is that role changes require re-login (new token). Acceptable for a self-hosted single-user-ish platform.

### Pattern 3: Source-Parallel Context Assembly

**What:** Launch all context sources concurrently with `asyncio.gather()`, apply per-source token budgets, deduplicate by semantic hash before assembling final output.

**When to use:** Any time context assembly involves multiple I/O sources (memory, MCP calls, file reads).

**Trade-offs:** Latency = max(slowest source) rather than sum(all sources). Risk: if one source hangs, wrap each in `asyncio.wait_for(..., timeout=3.0)` to fail fast.

### Pattern 4: Staggered Parallel Agent Launch

**What:** Use `asyncio.create_task()` for parallel execution but insert `AGENT_DISPATCH_DELAY` between launches when multiple agents target the same LLM provider.

**When to use:** Multi-agent orchestration. Prevents TPM (tokens-per-minute) spikes on shared providers (pitfall #93).

**Trade-offs:** Slightly increases total orchestration time, but prevents rate-limit cascades that cause much larger delays.

---

## Anti-Patterns

### Anti-Pattern 1: Replacing NodeSyncTool with QdrantSyncTool

**What people do:** Assume Qdrant sync makes markdown sync redundant.

**Why it's wrong:** MEMORY.md and HISTORY.md are the human-readable, human-editable source of truth. The Qdrant vectors are derivatives. If vectors get corrupted, you need the markdown to re-derive. Both sync mechanisms serve different purposes and must coexist.

**Do this instead:** Run both NodeSyncTool (markdown) and QdrantSyncTool (vectors) on the same merge cycle. Add `--skip-reindex` to NodeSyncTool merge when QdrantSyncTool has already synced vectors.

### Anti-Pattern 2: Using FastAPI Middleware for RBAC

**What people do:** Implement role checking in global middleware rather than per-endpoint dependencies.

**Why it's wrong:** Some endpoints are public (health checks, login), some need auth but not roles, some need specific roles. Global middleware can't express this cleanly without complex path filtering.

**Do this instead:** Use FastAPI's `Depends()` system. `require_role("admin")` is a dependency factory — it composes cleanly, is testable in isolation, and doesn't affect public endpoints.

### Anti-Pattern 3: Storing Orchestration State in Files

**What people do:** Write inter-agent communication to JSON files in the workspace.

**Why it's wrong:** File writes from multiple concurrent async tasks require locking. Race conditions cause data corruption. File I/O latency hurts orchestration throughput.

**Do this instead:** Use the SharedStateStore pattern (Redis-backed with asyncio.Queue fallback). All reads/writes go through the store API with proper async semantics.

### Anti-Pattern 4: Adding jcodemunch to Every Context Request

**What people do:** Always include code symbols in context assembly, even for non-code queries (support tickets, marketing copy).

**Why it's wrong:** jcodemunch is only valuable for code-oriented queries. Including it for unrelated queries adds token noise and slows assembly.

**Do this instead:** UnifiedContextTool accepts a `sources` parameter. Default to `["memory", "skills"]` for non-code tasks. Only add `"code"` when task_type is in `_CODE_TASK_TYPES` (already defined in `tools/registry.py`).

---

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| Qdrant (embedded) | Direct QdrantClient(path=...) | Laptop-local, no server needed |
| Qdrant (server, VPS) | SSH tunnel + QdrantClient(url="localhost:16333") | Tunnel opened by QdrantSyncTool |
| jcodemunch MCP | Via tools/mcp_client.py (existing) | Already used by context_assembler |
| Redis | Existing RedisBackend (memory/redis_session.py) | SharedStateStore uses same backend |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| QdrantSyncTool ↔ QdrantStore | Direct QdrantStore methods (scroll, upsert) | QdrantSyncTool gets QdrantStore via ToolContext injection |
| UnifiedContextTool ↔ MemoryStore | Existing `.build_context_semantic()` | No changes to MemoryStore |
| UnifiedContextTool ↔ jcodemunch | MCP client call (tools/mcp_client.py) | Gracefully disabled if jcodemunch unavailable |
| UnifiedContextTool ↔ GSDSource | Direct file reads (.planning/ path relative to workspace) | Read-only, no coupling to GSD codebase |
| RBAC ↔ FastAPI server.py | FastAPI Depends() injection | server.py adds `require_role()` to protected routes |
| Orchestrator ↔ AgentRuntime | Direct method call (core/agent_runtime.py) | Existing AgentRuntime.run() signature unchanged |
| Orchestrator ↔ SharedStateStore | API methods (get/set/subscribe) | Redis-backed or asyncio.Queue fallback |

---

## Scaling Considerations

| Scale | Architecture Adjustments |
|-------|--------------------------|
| 1 user (current) | Everything as described above — no changes needed |
| 5-10 users | RBAC becomes essential; add user management to dashboard (separate phase) |
| 10+ users | SharedStateStore must use Redis (not in-memory Queue); consider Qdrant server mode on laptop |

Current scale is 1 user (self-hosted). The architecture is designed to be correct at current scale and extensible to small team scale without rewrite.

### Scaling Priorities

1. **First bottleneck:** SharedStateStore asyncio.Queue is in-process only — fails for multi-process deployments. Redis backend is the fix (already implemented in memory/redis_session.py pattern).
2. **Second bottleneck:** Qdrant scroll-based sync is O(n) in collection size. At 100K+ vectors, switch to Qdrant's native snapshot transfer. Not relevant at current Agent42 scale.

---

## Build Order (Dependency-Driven)

The four new features have these dependencies:

```
RBAC              → no dependencies (builds on existing JWT only)
    ↓
QdrantSyncTool    → no dependencies (builds on existing QdrantStore only)
    ↓
UnifiedContextTool → depends on: existing MemoryStore, jcodemunch (optional), .planning/ structure
    ↓
MultiAgentOrchestrator → depends on: existing AgentRuntime + RBAC (for role-gated orchestration)
```

**Recommended build order:**
1. RBAC (`core/rbac.py`) — self-contained, unblocks everything, smallest risk
2. QdrantSyncTool (`tools/qdrant_sync.py`) — no dependencies, high value, verifiable
3. UnifiedContextTool (`tools/unified_context.py`) — depends on stable memory stack
4. MultiAgentOrchestrator (`core/orchestrator.py`) — most complex, builds on all prior work

This order ensures each phase ships independently-testable value and no phase is blocked waiting for another phase's code.

---

## Sources

- Direct codebase analysis: `memory/store.py`, `memory/qdrant_store.py`, `memory/embeddings.py`, `tools/node_sync.py`, `tools/context_assembler.py`, `tools/registry.py`, `tools/base.py`, `core/config.py`, `core/agent_manager.py`, `.claude/hooks/` (all hooks)
- [Qdrant Distributed Deployment](https://qdrant.tech/documentation/guides/distributed_deployment/) — replication and sync patterns
- [Qdrant Snapshots API](https://qdrant.tech/documentation/database-tutorials/create-snapshot/) — collection export/import mechanism
- [Qdrant Python Client](https://python-client.qdrant.tech/qdrant_client.qdrant_client) — scroll(), upsert() API reference
- [Qdrant Sync MCP Server](https://glama.ai/mcp/servers/@No-Smoke/qdrant-sync-mcp) — reference implementation for bidirectional sync approach
- [FastAPI RBAC with JWT](https://www.permit.io/blog/fastapi-rbac-full-implementation-tutorial) — dependency injection pattern for role enforcement
- [FastAPI Role-Based Access Control](https://developer.auth0.com/resources/code-samples/api/fastapi/basic-role-based-access-control) — JWT role claim patterns
- [Multi-Agent Orchestration Patterns 2026](https://www.ai-agentsplus.com/blog/multi-agent-orchestration-patterns-2026) — asyncio.gather(), staggering, shared state patterns
- [asyncio Queues for AI Task Orchestration](https://dasroot.net/posts/2026/02/using-asyncio-queues-ai-task-orchestration/) — producer/consumer patterns for agent coordination

---

*Architecture research for: Agent42 GSD & jcodemunch Integration*
*Researched: 2026-03-17*
