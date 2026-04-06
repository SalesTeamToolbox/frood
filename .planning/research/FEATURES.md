# Feature Research: Paperclip Integration (Plugin + Adapter)

**Domain:** AI agent orchestration platform integration — Agent42 as Paperclip intelligence layer
**Researched:** 2026-03-28
**Confidence:** HIGH (adapter spec), HIGH (plugin SDK), MEDIUM (sidecar endpoint contracts)

---

## Context: What Already Exists

Agent42 already has (do not rebuild):

- Semantic memory: ONNX embeddings + Qdrant, 4 collections, auto-sync from Claude Code
- Effectiveness tracking: SQLite, per-tool/per-task success rates, recommendations engine
- Tiered LLM routing: 9 providers, L1→free→L2 fallback, per-agent config
- Performance rewards: Bronze/Silver/Gold tiers with model upgrades, rate limits, concurrency caps
- MCP server: 41+ tools, 43+ skills
- TeamTool: multi-agent orchestration with 4 workflow modes
- AgentRuntime: Claude Code subprocess, PID tracking, log streaming
- FastAPI dashboard + WebSocket backbone

**Paperclip handles** (do not replicate): company org structure, budget management, board approval gates, heartbeat scheduling, audit trail, multi-company isolation, ticket/issue threading.

**The integration boundary:** Paperclip is the control plane. Agent42 is the intelligence layer. Each must remain independently useful.

---

## Adapter vs Plugin — The Two Extension Surfaces

Paperclip has two distinct extension points that serve different purposes:

**Adapter:** Defines how a specific agent runtime executes tasks. One adapter = one execution backend. The HTTP adapter is the pattern for Agent42 — Paperclip POSTs a heartbeat payload to Agent42's sidecar API; Agent42 processes it and returns an `AdapterExecutionResult`. This is how Paperclip users configure an agent to run "on Agent42."

**Plugin:** Extends Paperclip platform-wide (across all companies in the installation) with: agent-callable tools, background jobs, event listeners, UI slots (pages, tabs, dashboard widgets, sidebars). Plugins run as isolated Node.js child processes communicating via JSON-RPC 2.0 over stdin/stdout. One plugin instance = entire platform, not per-agent.

Agent42 needs both: the adapter routes execution into Agent42, the plugin enriches the platform with Agent42's intelligence (memory, routing, effectiveness data).

---

## Feature Landscape

### Table Stakes — Adapter Side

Features an Agent42 HTTP adapter must have to be a functional Paperclip citizen. Missing any makes the adapter unusable.

| Feature | Why Expected | Complexity | Depends On |
| --- | --- | --- | --- |
| HTTP heartbeat endpoint (`POST /api/paperclip/heartbeat`) | Paperclip HTTP adapter sends POST with `{runId, agentId, companyId, taskId, wakeReason, context}` — Agent42 must accept this exact shape | LOW | FastAPI sidecar mode |
| Synchronous `AdapterExecutionResult` response | Returns `{status, result, usage:{inputTokens,outputTokens,cachedInputTokens}, costUsd, model, provider}` — Paperclip parses this to update run records and budgets | LOW | Existing SpendingTracker + routing layer |
| Asynchronous 202 + callback pattern | Long-running agent executions must return `{status:"accepted", executionId}` and POST back to `paperclip.example.com/api/heartbeat-runs/:runId/callback` when done | MEDIUM | Background task runner |
| Agent identity resolution | Map Paperclip `agentId` to an Agent42 agent profile; fall back to a default profile if not found | LOW | AgentRoutingStore (exists) |
| `wakeReason` routing | `task_assigned` → immediate execution; `heartbeat` → proactive check; `manual` → forced run — different behaviors per reason | LOW | Execution controller |
| Error response shape | Return `{error, details}` with 4xx/5xx on failures; never leave Paperclip hanging with no response | LOW | Unified error taxonomy (exists) |
| Idempotency on `runId` | Paperclip may retry failed HTTP calls; same `runId` should not trigger duplicate execution | LOW | Simple runId dedup map |
| `testEnvironment()` equivalent | Health check endpoint (`GET /api/paperclip/health`) so Paperclip CLI's `doctor` command can validate connectivity | LOW | Existing `/health` endpoint, extend it |

### Table Stakes — Plugin Side

Features the Agent42 Paperclip plugin must expose to be installable and functional.

| Feature | Why Expected | Complexity | Depends On |
| --- | --- | --- | --- |
| Valid `manifest.json` (apiVersion: 1) | Plugin will be rejected at install without correct manifest: `id`, `apiVersion`, `version`, `displayName`, `description`, `categories`, `capabilities`, `entrypoints` | LOW | Plugin project scaffold |
| `setup(ctx)` worker entry point | Paperclip calls `setup(ctx)` on startup; all event handlers, job registrations, and tool declarations happen here | LOW | `@paperclipai/plugin-sdk` |
| `health()` handler | Paperclip polls this for liveness; must respond or plugin is marked error | LOW | Trivial implementation |
| `initialize(config)` handler | Receives plugin config (Agent42 base URL, API key) at startup | LOW | Config schema in manifest |
| `onShutdown()` hook | Clean shutdown when Paperclip restarts or uninstalls the plugin | LOW | Trivial implementation |
| Instance config schema | JSON Schema defining required fields: `agent42BaseUrl` (string, required), `apiKey` (string, required), and optionally `timeoutMs` | LOW | JSON Schema definition |
| Capability declarations | Must declare only what's used: `http.outbound`, `agent.tools.register`, and any UI slots — undeclared = runtime CAPABILITY_DENIED error | LOW | Manifest authoring |

### Table Stakes — Sidecar Mode

Agent42 needs a "headless" mode for Paperclip deployment. Currently Agent42 is always dashboard-first.

| Feature | Why Expected | Complexity | Depends On |
| --- | --- | --- | --- |
| `SIDECAR_MODE=true` env flag | Skip dashboard startup, reduce memory, only expose adapter API + plugin API endpoints | MEDIUM | FastAPI app factory pattern |
| Bearer token auth on sidecar endpoints | Paperclip HTTP adapter sends `Authorization: Bearer ${secrets.apiKey}` — sidecar must validate | LOW | Existing JWT middleware, extend it |
| Structured JSON logging (no color/progress) | In sidecar mode, stdout is consumed by Paperclip's log aggregator — no ANSI codes, no spinners | LOW | Log config flag |
| Docker image target | `docker build --target sidecar` produces a minimal image without dashboard UI assets | MEDIUM | Dockerfile multi-stage |

---

### Differentiators — Plugin Tools for Agents

Features that make Agent42's plugin meaningfully better than a bare Paperclip setup.

| Feature | Value Proposition | Complexity | Depends On |
| --- | --- | --- | --- |
| `memory_recall` agent tool | Agents call this tool to retrieve semantically relevant memories before executing tasks — replaces the prompt-stuffing hack of injecting everything | MEDIUM | Existing MemoryStore.search() |
| `memory_store` agent tool | Agents explicitly record learnings mid-task — supplements the automatic post-task extraction | LOW | Existing MemoryStore.store() |
| `route_task` agent tool | Agents call this to get the optimal provider+model recommendation for a given task type and quality target; Agent42 returns a routing decision | LOW | Existing tiered routing layer |
| Automatic memory injection on heartbeat | Plugin subscribes to `heartbeat.started` event; on fire, fetches top-K relevant memories for the agent+task and prepends to the heartbeat context via `promptTemplate` injection | HIGH | MemoryStore + Paperclip event system |
| `tool_effectiveness` agent tool | Agents query which tools/skills have highest success rates for their task type — drives autonomous tool selection | LOW | Existing effectiveness SQLite |
| `extract_learnings` job | Scheduled job (cron: hourly) processes completed Paperclip runs, extracts learnings from transcripts, stores in Agent42 Qdrant — extends existing CC-sync pattern to Paperclip runs | HIGH | Existing learning extraction pipeline |

### Differentiators — Plugin UI

| Feature | Value Proposition | Complexity | Depends On |
| --- | --- | --- | --- |
| Agent effectiveness `detailTab` | On Paperclip agent detail pages, show Agent42 tier (Bronze/Silver/Gold), success rates by task type, top tools, model routing history | MEDIUM | `@paperclipai/plugin-sdk/ui`, effectiveness SQLite |
| Memory browser `detailTab` on runs | On run detail pages, show which memories were injected for this run and which learnings were extracted — traceability for debugging | MEDIUM | MemoryStore + run correlation |
| Provider health `dashboardWidget` | Dashboard card showing Agent42 provider health status (free/L1/L2 tier availability) — helps operators understand why runs failed | LOW | Existing `/health` endpoint |
| Routing decisions `dashboardWidget` | Shows token spend distribution across providers over last 24h — surfaces cost anomalies | MEDIUM | SpendingTracker (exists) |

### Differentiators — TeamTool as Paperclip Task Strategy

| Feature | Value Proposition | Complexity | Depends On |
| --- | --- | --- | --- |
| Fan-out-fan-in as Paperclip strategy | When a Paperclip task is tagged `strategy:fan-out`, Agent42 spawns parallel sub-agents and aggregates results; final result returned to Paperclip as single run | HIGH | TeamTool + Paperclip run callback |
| Wave strategy | Sequential wave execution (e.g., research → draft → review) mapped to a single Paperclip ticket's lifecycle | HIGH | TeamTool.wave() + Paperclip comment threading |

### Differentiators — Migration Tooling

| Feature | Value Proposition | Complexity | Depends On |
| --- | --- | --- | --- |
| Agent import CLI (`agent42-to-paperclip`) | One command maps existing Agent42 agent profiles → Paperclip company/department/specialist structure | MEDIUM | Agent42 AgentStore + Paperclip API |
| Memory collection export | Export existing Qdrant memories in a format that survives Agent42 upgrades independently of Paperclip | LOW | Qdrant client (exists) |

---

### Anti-Features

Features that seem useful but create maintenance or architectural problems.

| Feature | Why Requested | Why Problematic | Alternative |
| --- | --- | --- | --- |
| Agent42 plugin managing budgets | "Agent42 already tracks token costs" | Budget authority belongs to Paperclip's control plane; dual accounting creates reconciliation drift and confusion about which system governs spend limits | Plugin reads Paperclip-managed cost data; Agent42 only surfaces its own `costUsd` in the heartbeat response for Paperclip to aggregate |
| Agent42 plugin scheduling heartbeats | "Agent42 knows when agents should run from effectiveness data" | Scheduling is Paperclip's core competency; bypassing it breaks audit trails, approval gates, and budget gates | Expose effectiveness data as a `tool_effectiveness` tool; let Paperclip's scheduling system use it to set heartbeat intervals |
| Replacing Paperclip's audit trail with Agent42's logs | "One less system to maintain" | Paperclip's append-only audit trail has governance implications; Agent42 logs are operational, not governance artifacts | Maintain both; Agent42 logs feed learning extraction, Paperclip audit trail remains authoritative |
| Full Agent42 dashboard embedded in Paperclip UI | "Unified UI" | Deep embedding creates a maintenance liability every time either UI changes; iframe resizing, auth bridging, and CSP conflicts are expensive | Use purpose-built `detailTab` and `dashboardWidget` slots for specific high-value panels; link out to Agent42 dashboard for full access |
| Plugin storing full conversation transcripts | "Searchable history in Agent42" | Transcripts live in Paperclip's `heartbeatRunEvents`; duplicating in Qdrant creates storage bloat and consistency problems | Plugin extracts only structured learnings (entities, patterns, decisions) from transcripts, not raw text |
| Per-company plugin instances | "Different companies need different Agent42 configs" | Paperclip plugins are installation-global by design (one process, all companies); fighting this creates architectural debt | Single plugin with per-company config in `plugin_state` (keyed by `companyId`); Agent42 sidecar can multi-tenant if needed |
| TypeScript rewrite of Agent42 sidecar | "Consistent with Paperclip's TypeScript stack" | Agent42's value (ONNX, Qdrant, asyncio) is Python-native; rewriting wastes months and risks correctness | Python FastAPI sidecar behind HTTP adapter; TypeScript wrapper in `packages/adapters/agent42-http/` is the right boundary |

---

## Feature Dependencies

```text
Sidecar Mode (SIDECAR_MODE=true + auth)
    └──required by──> HTTP Heartbeat Endpoint
                          └──required by──> AdapterExecutionResult response
                                                └──required by──> Async 202 + callback pattern
                                                └──required by──> Token cost reporting (uses SpendingTracker)

Plugin manifest + setup(ctx)
    └──required by──> All plugin features
    └──required by──> Agent Tool registrations (memory_recall, memory_store, route_task, tool_effectiveness)
    └──required by──> UI slots (detailTab, dashboardWidget)
    └──required by──> extract_learnings job

memory_recall agent tool
    └──requires──> MemoryStore.search() (exists in Agent42)
    └──enhances──> Automatic memory injection on heartbeat

extract_learnings job
    └──requires──> Paperclip run transcript access (via Paperclip API)
    └──requires──> Existing learning extraction pipeline (exists in Agent42)
    └──feeds──> memory_recall (richer memory over time)

TeamTool strategies
    └──requires──> Async 202 + callback pattern (strategies take >15s)
    └──requires──> TeamTool (exists in Agent42)
    └──requires──> Paperclip API write access (for comment threading)

detailTab / dashboardWidget UI
    └──requires──> Plugin manifest with ui.* capabilities
    └──requires──> Agent42 data API endpoints (effectiveness, provider health, routing decisions)
    └──requires──> @paperclipai/plugin-sdk/ui React components

Migration tooling
    └──requires──> Agent42 AgentStore read access (exists)
    └──requires──> Paperclip REST API (external)
    └──independent of──> Plugin and adapter (separate CLI tool)
```

### Dependency Notes

- **Sidecar mode blocks everything in the adapter:** Without a clean HTTP surface, Paperclip cannot invoke Agent42. This is Phase 1.
- **Plugin manifest + setup blocks all plugin features:** Can build adapter before any plugin work starts — they are independent tracks.
- **Memory tools require no new Agent42 backend code:** `MemoryStore.search()` and `MemoryStore.store()` already exist; plugin just wraps them as JSON-RPC agent tools via `ctx.tools` (manifest) + `executeTool` handler.
- **Automatic memory injection is highest complexity:** It requires correlating Paperclip's heartbeat event with the right memory query, injecting into `promptTemplate`, and doing so within the heartbeat window. Defer to post-MVP.
- **TeamTool strategies require async pattern:** TeamTool fan-out typically runs 2-5 minutes; synchronous HTTP adapter would timeout. Must implement 202+callback before exposing strategies.
- **UI slots have zero Python dependency:** The plugin's UI bundle is pure React/TypeScript fetching from Agent42's existing REST endpoints. The Python sidecar only needs to expose clean JSON endpoints; no UI work in Python.

---

## MVP Definition

### Phase 1 — Launch With (Adapter + Sidecar)

The minimum that makes Agent42 usable as a Paperclip agent runtime.

- [ ] `SIDECAR_MODE=true` env flag — skip dashboard, expose adapter API only
- [ ] Bearer token auth on sidecar endpoints (reuse JWT middleware)
- [ ] `POST /api/paperclip/heartbeat` — accept Paperclip run payload, execute via AgentRuntime, return `AdapterExecutionResult`
- [ ] Synchronous response for short tasks (<15s); 202 + callback for long tasks
- [ ] `runId` idempotency guard (in-memory map, sufficient for single-node)
- [ ] `GET /api/paperclip/health` — liveness check for Paperclip `doctor` command
- [ ] Token cost in response (`costUsd`, `usage`, `model`, `provider`) from existing SpendingTracker
- [ ] Docker image `--target sidecar` for clean deployment

### Phase 2 — Plugin Scaffold + Memory Tools

The minimum that makes Agent42 a differentiated Paperclip plugin (not just an adapter).

- [ ] Plugin project: `packages/paperclip-plugin-agent42/` with valid manifest and `setup(ctx)`
- [ ] `instanceConfigSchema`: `agent42BaseUrl` + `apiKey` fields
- [ ] `health()`, `initialize(config)`, `onShutdown()` handlers
- [ ] `memory_recall` agent tool — agents call with `{query, agentId, taskType, limit}`, returns relevant memories
- [ ] `memory_store` agent tool — agents call with `{content, agentId, taskType}`, stores as memory
- [ ] `route_task` agent tool — agents call with `{taskType, qualityTarget}`, returns `{provider, model, rationale}`
- [ ] `tool_effectiveness` agent tool — agents call with `{taskType}`, returns top-3 tools by success rate

### Phase 3 — Plugin UI + Extract Learnings

Closes the intelligence feedback loop and adds operator visibility.

- [ ] `extract_learnings` job: hourly cron, fetches recent Paperclip run transcripts, runs through learning extraction pipeline, stores in Qdrant
- [ ] Agent effectiveness `detailTab` on Paperclip agent pages: tier badge, success rates, model history
- [ ] Provider health `dashboardWidget`: current provider availability at a glance
- [ ] Memory browser `detailTab` on run pages: which memories were injected, which learnings were extracted

### Phase 4 — Advanced (Post-Validation)

Defer until Phase 1-3 are proven in production.

- [ ] Automatic memory injection on heartbeat — requires Paperclip `heartbeat.started` event (verify event exists before planning)
- [ ] TeamTool fan-out strategy exposed as Paperclip task strategy
- [ ] Wave strategy for multi-step ticket workflows
- [ ] Migration CLI (`agent42-to-paperclip`) for importing existing agents
- [ ] Routing decisions `dashboardWidget` (cost analytics)

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
| --- | --- | --- | --- |
| HTTP heartbeat endpoint | HIGH | LOW | P1 |
| Sidecar mode | HIGH | MEDIUM | P1 |
| Bearer auth on sidecar | HIGH | LOW | P1 |
| AdapterExecutionResult response | HIGH | LOW | P1 |
| Async 202 + callback | HIGH | MEDIUM | P1 |
| Plugin manifest + setup | HIGH | LOW | P1 |
| memory_recall agent tool | HIGH | LOW | P1 |
| memory_store agent tool | MEDIUM | LOW | P1 |
| route_task agent tool | HIGH | LOW | P2 |
| tool_effectiveness agent tool | MEDIUM | LOW | P2 |
| extract_learnings job | HIGH | HIGH | P2 |
| Agent effectiveness detailTab | MEDIUM | MEDIUM | P2 |
| Provider health dashboardWidget | MEDIUM | LOW | P2 |
| Memory browser detailTab on runs | MEDIUM | MEDIUM | P3 |
| Automatic memory injection | HIGH | HIGH | P3 |
| TeamTool fan-out strategy | MEDIUM | HIGH | P3 |
| Migration CLI | MEDIUM | MEDIUM | P3 |
| Docker sidecar image | HIGH | MEDIUM | P1 |

**Priority key:**

- P1: Phase 1-2 (MVP adapter + plugin scaffold)
- P2: Phase 3 (intelligence loop closure + operator visibility)
- P3: Phase 4 (advanced, post-validation)

---

## Adapter Reference Implementations Analyzed

| Adapter | Pattern | Relevance to Agent42 |
| --- | --- | --- |
| `claude-local` | Spawns `claude` CLI, captures stdout | Agent42 already does this via AgentRuntime |
| `openclaw-gateway` | WebSocket to remote agent, streaming events | Agent42 sidecar is a simpler HTTP pattern — no WebSocket needed |
| `hermes-local` | Spawns `hermes` CLI, session codec for state | Session key strategy (`issue`-scoped vs `run`-scoped) is directly applicable |
| HTTP adapter (built-in) | POST to external service, 202 async pattern | **This is Agent42's pattern** — Agent42 sidecar IS an HTTP adapter target |

Agent42 does not implement a Paperclip adapter package in the adapter-utils sense (that's a TypeScript package inside Paperclip's monorepo). Instead, Agent42 **is the HTTP endpoint** that Paperclip's built-in HTTP adapter calls. This distinction is important: the "adapter" is configuration in Paperclip (URL, headers, payloadTemplate), not code Agent42 ships.

---

## Key Interface Contracts

### Heartbeat Request (Paperclip to Agent42)

```json
{
  "runId": "run_abc123",
  "agentId": "agent_xyz789",
  "companyId": "company_456",
  "taskId": "task_123",
  "wakeReason": "task_assigned",
  "context": {
    "taskId": "task_123",
    "wakeReason": "task_assigned",
    "paperclipWorkspace": { "cwd": "/workspace", "source": "manual" }
  }
}
```

### Heartbeat Response (Agent42 to Paperclip)

```json
{
  "status": "completed",
  "result": "Summary of what was accomplished",
  "usage": { "inputTokens": 1234, "outputTokens": 567, "cachedInputTokens": 100 },
  "costUsd": 0.045,
  "model": "kimi-k2-5",
  "provider": "strongwall"
}
```

### Plugin Tool Call (Paperclip to Plugin to Agent42)

```text
Paperclip agent invokes tool "agent42:memory_recall"
    -> JSON-RPC executeTool(toolName, params, context)
    -> Plugin worker calls Agent42 GET /api/memory/search
    -> Returns [{content, score, metadata}] array
    -> Plugin returns structured result to agent
```

### Environment Variables Injected by Paperclip

Paperclip injects into all adapter processes (relevant for CLI adapter pattern, not HTTP):

- `PAPERCLIP_AGENT_ID`
- `PAPERCLIP_COMPANY_ID`
- `PAPERCLIP_API_URL`
- `PAPERCLIP_API_KEY` (if configured)

The HTTP adapter pattern does not use these — Agent42 receives all context in the POST body.

---

## Sources

- [Paperclip GitHub](https://github.com/paperclipai/paperclip) (HIGH confidence — official repo)
- [Paperclip PLUGIN_SPEC.md](https://github.com/paperclipai/paperclip/blob/master/doc/plugins/PLUGIN_SPEC.md) (HIGH confidence — official spec)
- [Plugin Architecture and Runtime — DeepWiki](https://deepwiki.com/paperclipai/paperclip/9.1-plugin-architecture-and-runtime) (HIGH confidence — official repo analysis)
- [Local CLI Adapters — DeepWiki](https://deepwiki.com/paperclipai/paperclip/5.2-local-cli-adapters) (HIGH confidence)
- [OpenClaw Gateway Adapter — DeepWiki](https://deepwiki.com/paperclipai/paperclip/5.3-openclaw-gateway-adapter) (HIGH confidence)
- [HTTP Adapter docs — Mintlify](https://www.mintlify.com/paperclipai/paperclip/agents/http-adapter) (HIGH confidence — official docs)
- [Hermes Paperclip Adapter](https://github.com/NousResearch/hermes-paperclip-adapter) (HIGH confidence — reference implementation)
- [RFC: Proactive heartbeat pattern](https://github.com/paperclipai/paperclip/issues/206) (MEDIUM confidence — RFC, not shipped)
- [Plugin System Discussion #258](https://github.com/paperclipai/paperclip/discussions/258) (MEDIUM confidence — community discussion)
- [Paperclip Monorepo Structure — DeepWiki](https://deepwiki.com/paperclipai/paperclip/1.2-monorepo-structure) (HIGH confidence)
- [@paperclipai/plugin-sdk npm](https://www.npmjs.com/package/@paperclipai/plugin-sdk) (HIGH confidence — released March 18, 2026)

---

*Feature research for: Agent42 v4.0 Paperclip Integration (Plugin + Adapter)*
*Researched: 2026-03-28*
