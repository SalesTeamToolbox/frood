# Architecture Research: Paperclip Integration (v4.0)

**Domain:** Paperclip adapter + plugin integration with existing Agent42 Python platform
**Researched:** 2026-03-28
**Confidence:** HIGH — based on direct Paperclip documentation, adapter SDK inspection (hermes-paperclip-adapter reference implementation), DeepWiki architecture docs, and direct Agent42 codebase inspection

---

## Standard Architecture

### System Overview

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Paperclip Control Plane (Node.js/Express, port 3100) │
│  ┌──────────────────┐  ┌──────────────────┐  ┌────────────────────────────┐ │
│  │  Heartbeat       │  │  Issue / Task    │  │  Plugin Runtime            │ │
│  │  Scheduler       │  │  Manager         │  │  (out-of-process JSON-RPC) │ │
│  └────────┬─────────┘  └────────┬─────────┘  └──────────────┬─────────────┘ │
│           │ invoke                │ context                   │ tool calls    │
│           └────────────────────── ┼ ──────────────────────────┘              │
│                                   │ ServerAdapterModule.execute()            │
│  ┌────────────────────────────────▼─────────────────────────────────────────┐│
│  │                      Adapter Registry                                     ││
│  │  claude_local | openclaw_gateway | http | process | agent42_local (NEW)  ││
│  └────────────────────────────────┬─────────────────────────────────────────┘│
└───────────────────────────────────┼─────────────────────────────────────────┘
                                    │ HTTP POST (async pattern)
                                    │ AdapterExecutionContext payload
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                     Agent42 Sidecar (Python/FastAPI, port 8001)              │
│                     (dashboard stripped, adapter-friendly endpoints only)    │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                    SidecarRoutes (NEW — dashboard/sidecar.py)         │   │
│  │  POST /sidecar/execute        ← receives AdapterExecutionContext      │   │
│  │  GET  /sidecar/status/{runId} ← Paperclip polls run status           │   │
│  │  POST /sidecar/callback       ← Agent42 posts result to Paperclip    │   │
│  │  GET  /sidecar/health         ← adapter testEnvironment() probe      │   │
│  └─────────────────────────┬────────────────────────────────────────────┘   │
│                             │                                                │
│  ┌──────────────────────────▼───────────────────────┐                       │
│  │              SidecarOrchestrator (NEW)            │                       │
│  │  1. Memory inject (recall relevant context)       │                       │
│  │  2. Route to provider (tiered routing)            │                       │
│  │  3. Spawn AgentRuntime subprocess                 │                       │
│  │  4. Collect transcript + extract learnings        │                       │
│  └──────┬────────────────────┬──────────────────────┘                       │
│         │                    │                                               │
│  ┌──────▼──────────┐  ┌──────▼──────────────────────────────────────────┐  │
│  │  MemoryBridge   │  │            AgentRuntime (existing)               │  │
│  │  (NEW)          │  │  Claude Code subprocess with provider env vars   │  │
│  │  recall()       │  │  captures stdout → TranscriptEntry[]             │  │
│  │  learn()        │  └─────────────────────────────────────────────────┘  │
│  └──────┬──────────┘                                                        │
│         │                                                                   │
│  ┌──────▼─────────────────────────────────────────────────────────────┐    │
│  │                    Existing Agent42 Services (unchanged)            │    │
│  │  MemoryStore  |  EmbeddingStore  |  QdrantStore  |  EffectivenessStore│  │
│  │  RewardSystem |  AgentManager   |  ToolRegistry  |  MCP Server      │  │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
┌───────────────────────────────────┼─────────────────────────────────────────┐
│   Paperclip Plugin Runtime        │                                          │
│   (out-of-process, stdin/stdout)  │                                          │
│  ┌────────────────────────────────▼────────────────────────────────────┐    │
│  │  agent42-paperclip-plugin (NEW TypeScript package)                  │    │
│  │  JSON-RPC 2.0 over stdin/stdout                                     │    │
│  │  ┌─────────────────┐  ┌───────────────────────┐  ┌───────────────┐ │    │
│  │  │  memory tools   │  │  MCP tool proxy        │  │  effectiveness│ │    │
│  │  │  recall / store │  │  (passthrough to A42)  │  │  panel UI     │ │    │
│  │  └─────────────────┘  └───────────────────────┘  └───────────────┘ │    │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | New vs Existing |
| --- | --- | --- |
| `agent42_local` adapter (TypeScript) | `ServerAdapterModule` that wraps HTTP calls to Agent42 sidecar; implements `execute()`, `testEnvironment()`, `sessionCodec()` | NEW |
| `dashboard/sidecar.py` | Stripped FastAPI app: sidecar-only routes, no auth, no dashboard static files, no WebSocket management | NEW |
| `SidecarOrchestrator` | Receives AdapterExecutionContext, drives memory inject → routing → subprocess → learning extract cycle | NEW |
| `MemoryBridge` | Wraps existing MemoryStore + QdrantStore: `recall(context)` before execution, `learn(transcript)` after | NEW (thin wrapper) |
| `TieredRoutingBridge` | Maps Paperclip task metadata (wakeReason, issueId, agentRole) to Agent42 provider/model selection | NEW (thin wrapper) |
| `agent42-paperclip-plugin` | Paperclip plugin package: memory tools, MCP tool proxy, effectiveness panel | NEW |
| `AgentRuntime` | Existing subprocess spawner — unchanged | EXISTING |
| `MemoryStore` / `QdrantStore` | Existing semantic memory — unchanged | EXISTING |
| `EffectivenessStore` | Existing SQLite effectiveness tracker — unchanged | EXISTING |
| `RewardSystem` | Existing tier-based model routing — unchanged | EXISTING |
| `AgentManager` | Existing agent CRUD — unchanged | EXISTING |
| `mcp_server.py` | Existing MCP stdio server — unchanged | EXISTING |
| `dashboard/server.py` | Existing full dashboard — unchanged (sidecar is a separate entry point) | EXISTING |

---

## Recommended Project Structure

```text
agent42/
├── dashboard/
│   ├── server.py               # EXISTING — full dashboard, untouched
│   └── sidecar.py              # NEW — sidecar FastAPI app (no dashboard UI)
│
├── core/
│   ├── sidecar_orchestrator.py # NEW — drives execute cycle
│   ├── memory_bridge.py        # NEW — recall() + learn() wrapper
│   ├── routing_bridge.py       # NEW — Paperclip context → provider/model
│   ├── config.py               # EXTEND — PAPERCLIP_SIDECAR_PORT, PAPERCLIP_CALLBACK_URL
│   └── ... (existing unchanged)
│
├── adapters/                   # NEW top-level directory
│   └── agent42-paperclip/      # TypeScript adapter package
│       ├── package.json
│       ├── src/
│       │   ├── index.ts        # exports adapter type, execute, testEnvironment
│       │   ├── execute.ts      # HTTP call to sidecar, async callback handling
│       │   ├── session.ts      # sessionCodec for cross-heartbeat state
│       │   └── types.ts        # AdapterExecutionContext/Result type aliases
│       └── tsconfig.json
│
├── plugins/                    # NEW top-level directory
│   └── agent42-paperclip-plugin/ # TypeScript plugin package
│       ├── package.json
│       ├── src/
│       │   ├── worker.ts       # Plugin worker entrypoint (JSON-RPC host)
│       │   ├── tools/
│       │   │   ├── memory.ts   # recall/store memory tools
│       │   │   └── mcp-proxy.ts # proxy calls to Agent42 MCP server
│       │   └── ui/
│       │       └── effectiveness-panel.tsx # Dashboard panel component
│       └── tsconfig.json
│
├── docker/
│   └── docker-compose.paperclip.yml # NEW — Paperclip + Agent42 + Qdrant + PG
│
└── scripts/
    └── migrate-agents-to-paperclip.py  # NEW — import JSON agents to Paperclip DB
```

### Structure Rationale

- **`adapters/` at repo root (not inside `dashboard/`):** Adapters are TypeScript/Node.js artifacts; grouping with the Python dashboard would create a mixed-runtime confusion. Top-level `adapters/` mirrors Paperclip's own `packages/adapters/` convention and makes the package publishable to npm.
- **`plugins/` at repo root:** Same reasoning — TypeScript plugin package separate from Python codebase. The plugin must be discoverable by Paperclip's plugin loader (either via `~/.paperclip/plugins/` or npm with `paperclip-plugin-` prefix).
- **`dashboard/sidecar.py` alongside `dashboard/server.py`:** Sidecar is a stripped variant of the same FastAPI application. Sibling placement makes it obvious that sidecar shares most infrastructure (config, memory, tools) with the full server but has different routes and no static file serving. Entry point is `python agent42.py --sidecar` (new CLI flag), not a separate startup file.
- **`core/sidecar_orchestrator.py` not inlined into sidecar.py:** The orchestration logic (inject→route→execute→learn) is testable in isolation. Keeping it in `core/` follows the project pattern where business logic lives in `core/` and `dashboard/server.py` / `sidecar.py` are thin FastAPI wrappers.

---

## Architectural Patterns

### Pattern 1: HTTP Adapter with Async Callback (primary integration pattern)

**What:** The TypeScript adapter POSTs to Agent42 sidecar and returns `202 Accepted` immediately. Agent42 runs the task asynchronously and POSTs results back to Paperclip's callback endpoint `POST /api/heartbeat-runs/:runId/callback`.

**When to use:** Any task that runs longer than a few seconds. All agent task execution falls into this category. Paperclip's HTTP adapter natively supports both synchronous and asynchronous patterns; async is required for tasks exceeding the HTTP timeout window.

**Trade-offs:** Adds a callback leg; requires Agent42 to know Paperclip's callback URL. The callback URL is injected via `PAPERCLIP_API_URL` environment variable (Paperclip sets `PAPERCLIP_API_URL` in the adapter environment automatically via `buildPaperclipEnv()`). No polling loop needed on either side.

**Data flow:**

```text
Paperclip Heartbeat Scheduler
    ↓  POST /sidecar/execute
    {
      runId, agentId, companyId, taskId,
      wakeReason,  // "heartbeat" | "task_assigned" | "manual"
      context: { tasks, company, workspace },
      adapterConfig: { sessionKey, memoryScope, preferredProvider }
    }
    ↓
Agent42 Sidecar responds: 202 Accepted + { externalRunId: runId }
    ↓  (asynchronous work)
SidecarOrchestrator:
  1. MemoryBridge.recall(agentId, taskContext) → relevant_memories[]
  2. TieredRoutingBridge.resolve(agentRole, wakeReason) → provider, model
  3. AgentRuntime.execute(prompt + memories, provider, model) → transcript
  4. MemoryBridge.learn(agentId, transcript) → new memories persisted
  5. EffectivenessStore.record(agentId, success, duration_ms)
    ↓
POST PAPERCLIP_API_URL/api/heartbeat-runs/:runId/callback
    {
      status: "succeeded" | "failed",
      result: { summary },
      usage: { inputTokens, outputTokens, costUsd }
    }
```

### Pattern 2: Plugin as Out-of-Process Extension (JSON-RPC 2.0 over stdin/stdout)

**What:** The plugin is a Node.js child process that communicates with the Paperclip host via newline-delimited JSON-RPC 2.0 on stdin/stdout. The plugin registers tool handlers during setup; Paperclip calls `executeTool` at runtime; the plugin can call back to the host via `state.get/set`, `http.fetch`, and `entities.upsert`.

**When to use:** For extending Paperclip's agent capabilities — giving agents access to Agent42's memory tools and MCP tools directly from within a Paperclip heartbeat session, without requiring the agent to make external HTTP calls.

**Trade-offs:** Plugin code is isolated (cannot crash the Paperclip host). Hot-reload supported during development via `PluginDevWatcher`. Plugin capability is declared in a manifest — the host enforces declared capabilities at runtime.

**Plugin tool handlers:**

```typescript
// worker.ts (setup phase)
export async function setup(ctx: PluginContext) {
  ctx.registerTool("memory_recall", async ({ agentId, query, topK }) => {
    const res = await ctx.http.fetch(`${AGENT42_SIDECAR_URL}/memory/recall`, {
      method: "POST",
      body: JSON.stringify({ agent_id: agentId, query, top_k: topK })
    });
    return res.json();  // returns { memories: [...] }
  });

  ctx.registerTool("memory_store", async ({ agentId, content, tags }) => {
    await ctx.http.fetch(`${AGENT42_SIDECAR_URL}/memory/store`, {
      method: "POST",
      body: JSON.stringify({ agent_id: agentId, content, tags })
    });
    return { stored: true };
  });

  ctx.registerTool("mcp_tool_proxy", async ({ toolName, args }) => {
    // Forward to Agent42's MCP server via the sidecar REST bridge
    const res = await ctx.http.fetch(`${AGENT42_SIDECAR_URL}/mcp/invoke`, {
      method: "POST",
      body: JSON.stringify({ tool: toolName, args })
    });
    return res.json();
  });
}
```

### Pattern 3: Sidecar Mode as a Run-Mode Flag (not a separate service)

**What:** Agent42 runs in sidecar mode when started with `python agent42.py --sidecar`. In sidecar mode, the application starts `dashboard/sidecar.py` (not `dashboard/server.py`) — a FastAPI app with only sidecar routes, no auth middleware, no static files, and no WebSocket manager. All core services (MemoryStore, QdrantStore, AgentRuntime, ToolRegistry) start identically.

**When to use:** When deploying alongside Paperclip in the same Docker Compose network. The full dashboard (`--port 8000`) can optionally run concurrently for local inspection, but the sidecar port (`8001`) is what Paperclip's adapter points to.

**Trade-offs:** Single process, shared memory — no IPC overhead between sidecar routes and core services. Avoids duplicating service initialization. The `--no-dashboard` flag already exists in `agent42.py`; sidecar mode extends this pattern with `--sidecar`.

```python
# agent42.py (extended)
parser.add_argument("--sidecar", action="store_true",
    help="Start in sidecar mode (adapter-friendly endpoints, no dashboard UI)")
parser.add_argument("--sidecar-port", type=int, default=8001,
    help="Port for sidecar endpoints")

# Startup logic:
if args.sidecar:
    from dashboard.sidecar import create_sidecar_app
    app = create_sidecar_app(memory_store, agent_manager, ...)
    uvicorn.run(app, port=args.sidecar_port)
else:
    from dashboard.server import create_app
    app = create_app(memory_store, agent_manager, ...)
    uvicorn.run(app, port=args.port)
```

### Pattern 4: Memory Bridge — Inject Before, Learn After

**What:** MemoryBridge wraps existing MemoryStore and QdrantStore with two operations called at the bookends of every task execution: `recall(agent_id, task_context)` injects relevant memories into the prompt before the agent subprocess starts; `learn(agent_id, transcript)` extracts learnings from the agent's output after it finishes.

**When to use:** Every sidecar execution. Memory inject and learning extraction are the core value of the Agent42 layer within Paperclip — they make agents smarter over time without requiring Paperclip to understand Agent42's memory model.

**Trade-offs:** `learn()` must be async and non-blocking (existing fire-and-forget pattern via `asyncio.create_task()`). Recall latency is on the hot path — cap at 200ms with a timeout guard. Memory scope follows Paperclip's agent hierarchy: `companyId` for shared memories, `agentId` for agent-specific.

```python
# core/memory_bridge.py
class MemoryBridge:
    async def recall(
        self, agent_id: str, task_context: dict, top_k: int = 5
    ) -> list[str]:
        """Return top-k relevant memories as a list of formatted strings."""
        query = self._build_query(task_context)
        try:
            async with asyncio.timeout(0.2):  # 200ms hard cap
                results = await self._memory_store.search(
                    query=query, agent_id=agent_id, top_k=top_k
                )
            return [r.content for r in results]
        except TimeoutError:
            logger.warning("memory_recall timeout for agent_id=%s", agent_id)
            return []

    def learn_async(self, agent_id: str, transcript: list[dict]) -> None:
        """Fire-and-forget learning extraction. Never blocks the response path."""
        asyncio.create_task(self._learn(agent_id, transcript))
```

---

## Integration Points

### New Components vs Modified vs Unchanged

| Component | Status | Integration Boundary |
| --- | --- | --- |
| `adapters/agent42-paperclip/` | NEW (TypeScript) | Paperclip adapter registry → Agent42 sidecar HTTP |
| `plugins/agent42-paperclip-plugin/` | NEW (TypeScript) | Paperclip plugin runtime (JSON-RPC) → Agent42 sidecar HTTP |
| `dashboard/sidecar.py` | NEW (Python) | Paperclip → POST `/sidecar/execute`; Agent42 → POST `/api/heartbeat-runs/:runId/callback` |
| `core/sidecar_orchestrator.py` | NEW (Python) | Calls: MemoryBridge, TieredRoutingBridge, AgentRuntime, EffectivenessStore |
| `core/memory_bridge.py` | NEW (Python, thin wrapper) | Wraps: MemoryStore.search(), QdrantStore.search(), EmbeddingStore.encode() |
| `core/routing_bridge.py` | NEW (Python, thin wrapper) | Wraps: existing `resolve_model()` and `AgentManager.get_effective_limits()` |
| `core/config.py` | EXTEND | Add: PAPERCLIP_SIDECAR_PORT, PAPERCLIP_API_URL, PAPERCLIP_MEMORY_SCOPE, SIDECAR_ENABLED |
| `agent42.py` | EXTEND | Add: `--sidecar` and `--sidecar-port` CLI flags |
| `dashboard/server.py` | UNCHANGED | Full dashboard continues to run on port 8000 |
| `core/agent_runtime.py` | UNCHANGED | Used as-is by SidecarOrchestrator |
| `memory/store.py` | UNCHANGED | Used as-is by MemoryBridge |
| `memory/qdrant_store.py` | UNCHANGED | Used as-is by MemoryBridge |
| `memory/effectiveness.py` | UNCHANGED | Used as-is by SidecarOrchestrator |
| `core/reward_system.py` | UNCHANGED | Used as-is by TieredRoutingBridge |
| `mcp_server.py` | UNCHANGED | Accessed by plugin via sidecar MCP proxy endpoint |
| `docker-compose.yml` | EXTEND | Add Paperclip service, PostgreSQL, expose sidecar port |
| `scripts/migrate-agents-to-paperclip.py` | NEW | One-way migration: Agent42 JSON agents → Paperclip PostgreSQL |

### Sidecar REST API (new endpoints in `dashboard/sidecar.py`)

```text
POST /sidecar/execute
  Request:  AdapterExecutionContext (runId, agentId, companyId, taskId, wakeReason, context, adapterConfig)
  Response: 202 Accepted + { externalRunId }

GET  /sidecar/status/{runId}
  Response: { status: "running"|"succeeded"|"failed", startedAt, completedAt? }

GET  /sidecar/health
  Response: { ok: true, memory: "connected"|"degraded", providers: [...] }

POST /memory/recall
  Request:  { agent_id, query, top_k, scope: "agent"|"company" }
  Response: { memories: [{ content, score, timestamp }] }

POST /memory/store
  Request:  { agent_id, content, tags, scope: "agent"|"company" }
  Response: { stored: true, id }

POST /mcp/invoke
  Request:  { tool: toolName, args: {...} }
  Response: { result: {...} }  (proxied from mcp_server via registry)
```

### External Service Boundaries

| Boundary | Direction | Protocol | Notes |
| --- | --- | --- | --- |
| Paperclip → Agent42 sidecar | Paperclip initiates | HTTP POST (REST) | Port 8001; no auth in Docker network (private subnet only) |
| Agent42 sidecar → Paperclip callback | Agent42 initiates | HTTP POST (REST) | `PAPERCLIP_API_URL/api/heartbeat-runs/:runId/callback`; Paperclip sets `PAPERCLIP_API_URL` in adapter env |
| Paperclip plugin → Agent42 sidecar | Plugin initiates | HTTP POST (REST) | Same sidecar port; `AGENT42_SIDECAR_URL` in plugin env config |
| Agent42 sidecar → QdrantDB | Agent42 initiates | gRPC/HTTP | Existing; `qdrant_url` in config |
| Agent42 sidecar → Redis | Agent42 initiates | TCP | Existing; `redis_url` in config |
| Agent42 MCP server | stdio (claude subprocess) | stdio | Unchanged; each AgentRuntime subprocess gets its own MCP session |
| Paperclip → PostgreSQL | Paperclip internal | TCP | Paperclip's own DB; Agent42 does NOT read Paperclip's PostgreSQL |
| Agent42 → SQLite effectiveness | Agent42 internal | File | Unchanged; `.agent42/effectiveness.db` |

---

## Data Flow

### Flow 1: Heartbeat Execution (primary path)

```text
Paperclip Scheduler fires (periodic or on task_assigned)
    ↓
agent42_local adapter.execute(ctx: AdapterExecutionContext)
    ↓
POST http://agent42-sidecar:8001/sidecar/execute
    { runId, agentId, taskContext, wakeReason, adapterConfig }
    ↓  → 202 Accepted
SidecarOrchestrator.execute_async(runId, ctx)   [asyncio.create_task]
    ↓
MemoryBridge.recall(agentId, taskContext)
    → QdrantStore.search(query, agent_id=agentId, top_k=5)
    → top memories (200ms timeout, fallback=[])
    ↓
TieredRoutingBridge.resolve(agentRole, wakeReason, tier)
    → RewardSystem.get_tier(agentId) → "gold"|"silver"|"bronze"
    → resolve_model(provider, task_category, tier) → model_id
    ↓
AgentRuntime._build_env(provider, model) + inject memories into prompt
    ↓
subprocess: claude --mcp-config .mcp.json -p "[prompt + memories]"
    → stdout captured as transcript lines
    ↓
EffectivenessStore.record(agentId, success, duration_ms)   [fire-and-forget]
MemoryBridge.learn_async(agentId, transcript)               [fire-and-forget]
    ↓
POST PAPERCLIP_API_URL/api/heartbeat-runs/{runId}/callback
    { status: "succeeded", result: { summary }, usage: { inputTokens, outputTokens, costUsd } }
    ↓
Paperclip marks run succeeded → triggers dependent tasks
```

### Flow 2: Plugin Tool Call (memory recall during agent execution)

```text
Agent (running inside Paperclip heartbeat) calls memory_recall tool
    ↓
Paperclip Plugin Runtime: executeTool("memory_recall", { agentId, query })
    ↓ JSON-RPC over stdin/stdout
Plugin worker: ctx.http.fetch(AGENT42_SIDECAR_URL + "/memory/recall", ...)
    ↓ HTTP POST
Agent42 sidecar /memory/recall handler
    → MemoryBridge.recall(agentId, query)
    → { memories: [...] }
    ↓
Plugin returns memories to Paperclip → injected into agent context
```

### Flow 3: Tiered Routing Bridge

```text
Paperclip sends wakeReason + agentRole in AdapterExecutionContext
    ↓
TieredRoutingBridge.resolve(adapterConfig)
    adapterConfig.agentRole   → maps to task_category
        "engineer"            → "coding"
        "researcher"          → "research"
        "writer"              → "content"
        "analyst"             → "analysis"
        default               → "general"
    adapterConfig.preferredProvider → overrides default provider (optional)
    RewardSystem.get_tier(agentId)  → "gold"|"silver"|"bronze"
    resolve_model(provider, task_category, tier) → specific model_id
    ↓
AgentRuntime._build_env(provider, model)
```

### Flow 4: Agent Migration

```text
scripts/migrate-agents-to-paperclip.py
    ↓
Read .agent42/agents/*.json   [existing agent JSON files]
    ↓
For each agent:
    POST http://paperclip:3100/api/companies/{companyId}/agents
    {
      name: agent.name,
      jobDescription: agent.description,
      adapterType: "agent42_local",
      adapterConfig: {
        agentId: agent.id,
        tools: agent.tools,
        sessionKey: "issue"    // per-issue context isolation
      }
    }
    ↓
Print summary: N agents migrated, M failed
```

---

## Suggested Build Order

Dependencies drive this order. Each phase can be independently tested before the next begins.

```text
Phase 1: Agent42 Sidecar Mode
  Deliverables:
  - agent42.py --sidecar flag
  - dashboard/sidecar.py with /sidecar/execute, /sidecar/health, /sidecar/status/{runId}
  - core/sidecar_orchestrator.py skeleton (no memory inject yet — just AgentRuntime.execute)
  - core/config.py: PAPERCLIP_SIDECAR_PORT, PAPERCLIP_API_URL, SIDECAR_ENABLED
  Tests:
  - POST /sidecar/execute returns 202
  - GET /sidecar/health returns { ok: true }
  - Async callback fires to PAPERCLIP_API_URL/api/heartbeat-runs/{id}/callback
  Why first: All subsequent phases depend on the sidecar HTTP surface existing

Phase 2: Paperclip Adapter Package
  Deliverables:
  - adapters/agent42-paperclip/ TypeScript package
  - execute() POSTs to sidecar and returns AdapterExecutionResult
  - testEnvironment() probes /sidecar/health
  - sessionCodec() preserves agentId across heartbeats
  Tests:
  - Adapter registers in local Paperclip instance
  - Single heartbeat runs to completion against real sidecar
  Why second: Tests the sidecar from the Paperclip side; catches protocol mismatches early

Phase 3: Memory Bridge
  Deliverables:
  - core/memory_bridge.py: recall() + learn_async()
  - /memory/recall and /memory/store sidecar endpoints
  - SidecarOrchestrator wired to call MemoryBridge.recall() before AgentRuntime.execute()
  - MemoryBridge.learn_async() wired after execution
  Tests:
  - recall() returns relevant memories from a seeded QdrantStore
  - learn_async() fires and stores a new memory entry
  - 200ms timeout guard verified (mock slow Qdrant)
  Why third: Depends on sidecar (Phase 1) but independent of adapter (Phase 2). Can be
  developed in parallel with Phase 2 once Phase 1 is stable.

Phase 4: Tiered Routing Bridge
  Deliverables:
  - core/routing_bridge.py: agentRole → task_category → provider/model
  - SidecarOrchestrator wired to use TieredRoutingBridge before AgentRuntime.execute()
  Tests:
  - "engineer" role routes to coding/Cerebras
  - "researcher" role routes to research/Groq
  - Gold-tier agent gets reasoning model upgrade
  Why fourth: Depends on sidecar (Phase 1) and existing reward system. Adds intelligence
  to model selection without blocking memory or adapter work.

Phase 5: Paperclip Plugin
  Deliverables:
  - plugins/agent42-paperclip-plugin/ TypeScript package
  - memory_recall, memory_store tool handlers
  - mcp_tool_proxy tool handler
  - /mcp/invoke sidecar endpoint (proxies to ToolRegistry)
  Tests:
  - Plugin registers in Paperclip
  - memory_recall tool returns memories from a running sidecar
  - mcp_tool_proxy proxies a simple tool call (e.g., memory_read)
  Why fifth: Depends on /memory/recall endpoint (Phase 3). Plugin is additive — agents
  work without it; plugin enables richer tool access from within Paperclip sessions.

Phase 6: Docker Compose + Migration
  Deliverables:
  - docker/docker-compose.paperclip.yml: Paperclip + Agent42 sidecar + Qdrant + PostgreSQL
  - scripts/migrate-agents-to-paperclip.py
  Tests:
  - `docker compose up` brings all services online
  - Migration script imports 3 test agents without error
  - End-to-end: Paperclip heartbeat triggers Agent42 agent, callback received
  Why last: Integration packaging. Depends on all previous phases being stable.
```

---

## Scaling Considerations

| Scale | Architecture Adjustments |
| --- | --- |
| 1 company, 1-10 agents | Current design sufficient. Single sidecar process, embedded Qdrant, single Redis instance. |
| 1 company, 10-50 agents | Add Qdrant server mode (already supported). Consider Redis cluster. Sidecar can handle ~20 concurrent agents with asyncio before needing workers. |
| Multi-company, 50+ agents | Run multiple Agent42 sidecar instances behind a simple nginx proxy; partition by company. Qdrant collection per company (existing prefix config). |

### Scaling Priorities

1. **First bottleneck:** Qdrant embedded mode under concurrent search load. Mitigation: switch to Qdrant server mode (one config change). Already architected for this in `qdrant_url` config.
2. **Second bottleneck:** AgentRuntime spawning N concurrent Claude Code subprocesses hitting provider rate limits. Mitigation: existing `asyncio.Semaphore` concurrency caps via `get_effective_limits()` already handle this.

---

## Anti-Patterns

### Anti-Pattern 1: Agent42 Reading Paperclip's PostgreSQL Directly

**What people do:** Add a Drizzle/asyncpg client to the Python sidecar to read task/issue data directly from Paperclip's DB instead of trusting the payload Paperclip sends.

**Why it's wrong:** Paperclip's schema is TypeScript-first (Drizzle ORM). Direct reads create a tight schema coupling — any Paperclip schema migration breaks the sidecar. Also bypasses Paperclip's access control.

**Do this instead:** Trust the `context` object in `AdapterExecutionContext`. Paperclip sends all task-relevant data in the payload. If more data is needed, call Paperclip's REST API with the agent's API key.

### Anti-Pattern 2: Running the Full Dashboard Server in Sidecar Mode

**What people do:** Re-use `dashboard/server.py` as the sidecar by adding `/sidecar/*` routes to it.

**Why it's wrong:** The full dashboard has CORS middleware, JWT auth, WebSocket connection limits, and static file serving — all designed for browser-facing use. Attaching adapter endpoints to this server means Paperclip's internal HTTP calls get caught by browser security policies (CORS), JWT validation, and rate limiters designed for human users.

**Do this instead:** `dashboard/sidecar.py` is a separate FastAPI app with no middleware except request logging. The sidecar port is never exposed publicly — only to the internal Docker network where Paperclip runs.

### Anti-Pattern 3: Synchronous Memory Recall on the Critical Path Without a Timeout

**What people do:** Call `await memory_store.search(...)` inside the execute handler with no timeout. If Qdrant is slow or unavailable, the sidecar stalls and Paperclip's adapter times out.

**Why it's wrong:** Paperclip's HTTP adapter has a configurable timeout (default ~60s). A slow Qdrant under load can stall all concurrent heartbeats, causing cascading failures.

**Do this instead:** Always wrap memory recall in `asyncio.timeout(0.2)` (200ms). Return empty memories on timeout — agent still runs, just without context injection. This is the graceful degradation pattern already established in Agent42's design philosophy.

### Anti-Pattern 4: One TypeScript Adapter Package for Both Adapter and Plugin

**What people do:** Combine the adapter (execution wrapper) and plugin (tool extension) into a single npm package.

**Why it's wrong:** Paperclip loads adapters and plugins via different mechanisms (adapter registry vs. plugin loader with separate manifest). Combining them makes the package ambiguous and prevents independent versioning — a breaking plugin change would require updating the adapter registration too.

**Do this instead:** Two separate TypeScript packages: `agent42-paperclip-adapter` (adapter, in `adapters/`) and `agent42-paperclip-plugin` (plugin, in `plugins/`). They share type aliases from `@paperclipai/adapter-utils` but have independent package.json files.

### Anti-Pattern 5: Migrating Agents Without Preserving AgentId

**What people do:** Let Paperclip auto-generate new agent IDs during migration instead of mapping existing Agent42 agent IDs to Paperclip `adapterConfig.agentId`.

**Why it's wrong:** All effectiveness history in SQLite and all memories in Qdrant are keyed by the original Agent42 `agent_id`. If the migration creates a new ID, the agent starts cold — no memory, no tier history, no effectiveness data.

**Do this instead:** Migration script stores the original Agent42 `agent_id` in `adapterConfig.agentId`. The adapter passes this ID to the sidecar in every execution. All existing memory and effectiveness data is immediately available to the migrated agent.

---

## Key Schema: AdapterExecutionContext (from Paperclip)

This is what Agent42 sidecar receives on every heartbeat invocation:

```typescript
interface AdapterExecutionContext {
  runId: string;           // Paperclip heartbeat run ID (use as externalRunId)
  agentId: string;         // Paperclip agent ID
  companyId: string;       // Paperclip company ID
  taskId?: string;         // Paperclip issue/task ID (if task-triggered)
  wakeReason: "heartbeat" | "task_assigned" | "manual" | "callback";
  context: {
    tasks: PaperclipTask[];   // pending/assigned tasks for this agent
    company: CompanyContext;  // org chart, mission
    workspace?: { cwd: string };
  };
  adapterConfig: {
    // Agent42-specific fields (set when creating agent in Paperclip)
    agentId?: string;           // Original Agent42 agent ID (for memory/effectiveness lookup)
    agentRole?: string;         // "engineer"|"researcher"|"writer"|"analyst" (routing hint)
    preferredProvider?: string; // override provider (optional)
    sessionKey?: string;        // "fixed"|"issue"|"run" (session persistence)
    memoryScope?: "agent"|"company";  // memory isolation level
  };
}
```

---

## Sources

- [Paperclip GitHub — main repository](https://github.com/paperclipai/paperclip) — HIGH confidence
- [Paperclip Plugin Architecture (DeepWiki)](https://deepwiki.com/paperclipai/paperclip/9.1-plugin-architecture-and-runtime) — HIGH confidence
- [Paperclip OpenClaw Gateway Adapter (DeepWiki)](https://deepwiki.com/paperclipai/paperclip/5.3-openclaw-gateway-adapter) — HIGH confidence
- [Paperclip Local CLI Adapters (DeepWiki)](https://deepwiki.com/paperclipai/paperclip/5.2-local-cli-adapters) — HIGH confidence
- [Paperclip Monorepo Structure (DeepWiki)](https://deepwiki.com/paperclipai/paperclip/1.2-monorepo-structure) — HIGH confidence
- [Paperclip HTTP Adapter docs](https://www.mintlify.com/paperclipai/paperclip/agents/http-adapter) — HIGH confidence
- [Hermes Paperclip Adapter — reference implementation](https://github.com/NousResearch/hermes-paperclip-adapter) — HIGH confidence
- [Paperclip Adapter Guide](https://www.mintlify.com/paperclipai/paperclip/guides/adapters) — MEDIUM confidence
- [Paperclip Custom Adapters Guide](https://www.mintlify.com/paperclipai/paperclip/agents/custom-adapters) — MEDIUM confidence
- Agent42 codebase — `core/agent_manager.py`, `core/agent_runtime.py`, `core/heartbeat.py`, `core/config.py`, `dashboard/server.py`, `agent42.py`, `memory/store.py` — HIGH confidence (direct inspection)
- `.planning/PROJECT.md` — v4.0 milestone target features — HIGH confidence

---

*Architecture research for: Agent42 v4.0 Paperclip Integration (adapter + plugin)*
*Researched: 2026-03-28*
