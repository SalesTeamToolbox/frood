# Project Research Summary

**Project:** Agent42 v4.0 — Paperclip Integration (Plugin + Adapter)
**Domain:** Cross-language integration — Python AI platform as Paperclip intelligence layer
**Researched:** 2026-03-28
**Confidence:** HIGH

## Executive Summary

Agent42 v4.0 integrates with Paperclip as both an HTTP adapter (execution backend) and a Paperclip plugin (intelligence layer). The integration is cross-language by necessity: Paperclip's plugin and adapter systems are TypeScript/Node.js, while Agent42's intelligence stack (ONNX embeddings, Qdrant, asyncio tiered routing) is Python. The recommended architecture is a thin TypeScript wrapper layer over a Python FastAPI sidecar — not a TypeScript rewrite. The TypeScript packages (`adapters/agent42-paperclip/` and `plugins/agent42-paperclip-plugin/`) act as protocol bridges, translating JSON-RPC 2.0 and HTTP adapter contracts into calls to Agent42's existing REST endpoints. This boundary is well-defined and allows each language to do what it does best.

The recommended build order is adapter-first, plugin-second. The sidecar HTTP endpoint is a hard dependency for the adapter, and the adapter is a hard dependency for everything else — without a working sidecar, Paperclip cannot invoke Agent42 at all. Once the adapter is functional, the plugin scaffold and memory tools can be layered on top without touching the adapter code. The plugin's UI slots have zero Python dependency and can be developed in parallel with the sidecar work. This creates two independent tracks: Python (sidecar + orchestrator + memory bridge) and TypeScript (adapter package + plugin package), which converge at integration test points at each phase boundary.

The critical risks are startup race conditions (Paperclip probing Agent42 before it is ready), Windows CRLF breaking the JSON-RPC protocol in the plugin, duplicate budget tracking creating governance conflicts, and memory injection latency on the heartbeat hot path. All are well-understood and preventable with specific mitigations documented in PITFALLS.md. The most architecturally significant risk is scope creep — particularly the temptation to replicate Paperclip's budget enforcement, scheduling, or audit trail in Agent42. The research is emphatic: Agent42 is the intelligence layer, Paperclip is the control plane, and crossing that boundary creates long-term maintenance debt.

## Key Findings

### Recommended Stack

The existing Agent42 Python stack requires no new Python dependencies for the sidecar. The sidecar reuses FastAPI, uvicorn, existing MemoryStore, QdrantStore, AgentRuntime, and EffectivenessStore unchanged. The only new Python artifacts are thin wrapper classes (SidecarOrchestrator, MemoryBridge, TieredRoutingBridge) and a new FastAPI app entry point (`dashboard/sidecar.py`).

The new additions are entirely in the TypeScript/Node.js layer required by Paperclip's extension APIs. Both the adapter package and plugin package are independent npm packages built with pnpm, located at `adapters/agent42-paperclip/` and `plugins/agent42-paperclip-plugin/` at the repo root.

**Core technologies:**

- `TypeScript 5.7+` + `@paperclipai/plugin-sdk 2026.318.0+`: Required for Paperclip adapter and plugin development — no Python alternative exists
- `Node.js 20+` + `pnpm 9.15+`: Paperclip's runtime and package manager requirements
- `Docker Compose 2.x` + `PostgreSQL 16+`: Standard Paperclip deployment model; Agent42 sidecar joins as an additional service on the same Docker network
- Python FastAPI sidecar (existing stack): New `--sidecar` CLI flag activates stripped mode — no dashboard, no WebSocket manager, no static files, shares all core services with the full server

**What not to add:** Python JSON-RPC libraries (plugin communicates via HTTP to sidecar, not direct JSON-RPC), gRPC (HTTP REST is simpler and matches the Paperclip HTTP adapter spec), shared PostgreSQL from Agent42 (Paperclip owns PostgreSQL; Agent42 keeps Qdrant+SQLite), or a TypeScript rewrite of the Agent42 sidecar.

See `.planning/research/STACK.md` for full details and rationale.

### Expected Features

Paperclip has two distinct extension surfaces: the HTTP adapter (routes execution into Agent42) and the plugin (enriches the platform with Agent42 intelligence). Agent42 needs both.

**Must have — adapter side (table stakes):**

- `POST /api/paperclip/heartbeat` accepting `{runId, agentId, companyId, taskId, wakeReason, context}`
- Synchronous `AdapterExecutionResult` response with `{status, result, usage, costUsd, model, provider}`
- Async 202 + callback pattern for long-running tasks (>15s); Agent42 POSTs back to Paperclip's callback endpoint
- `runId` idempotency guard to prevent duplicate execution on Paperclip retries
- `GET /api/paperclip/health` for Paperclip's `doctor` command validation
- `SIDECAR_MODE=true` with Bearer token auth and structured JSON logging (no ANSI codes)
- Docker multi-stage `--target sidecar` image for clean deployment

**Must have — plugin side (table stakes):**

- Valid `manifest.json` with `apiVersion: 1`, correct capability declarations, and entrypoints
- `setup(ctx)` worker entry point registering all tool handlers
- `health()`, `initialize(config)`, and `onShutdown()` handlers
- `memory_recall` and `memory_store` agent tools (wrapping existing MemoryStore — zero new backend code required)
- `route_task` agent tool (wrapping existing tiered routing layer)

**Should have (differentiators):**

- `tool_effectiveness` agent tool returning top tools by success rate for a task type
- `extract_learnings` hourly cron job fetching Paperclip run transcripts, storing structured learnings in Qdrant
- Agent effectiveness `detailTab` on Paperclip agent pages (tier badge, success rates, model history)
- Provider health `dashboardWidget` showing Agent42 provider availability at a glance
- Memory browser `detailTab` on run pages showing injected memories and extracted learnings

**Defer to Phase 4 (post-validation):**

- Automatic memory injection on heartbeat (requires `heartbeat.started` event — must verify this event is shipped before designing against it)
- TeamTool fan-out and wave strategies exposed as Paperclip task strategies
- Migration CLI (`agent42-to-paperclip`) for importing existing agents into Paperclip
- Routing decisions `dashboardWidget` (cost analytics across providers)

**Anti-features to reject:**

- Agent42 managing Paperclip budgets — creates dual accounting and governance conflicts; SpendingTracker becomes a data source, not an enforcement gate
- Agent42 scheduling heartbeats — bypasses Paperclip's approval gates and audit trail
- Full Agent42 dashboard embedded in Paperclip via iframe — maintenance liability on every UI change
- TypeScript rewrite of Agent42 sidecar — wastes months and loses Python-native intelligence stack value

See `.planning/research/FEATURES.md` for the full feature dependency graph, interface contracts (heartbeat request/response shapes), and MVP definition.

### Architecture Approach

The integration uses three well-defined patterns running in concert: (1) HTTP adapter with async callback as the primary execution pattern — Paperclip POSTs to the sidecar, gets 202 Accepted, Agent42 works asynchronously and POSTs results back via callback; (2) plugin as out-of-process Node.js extension communicating via JSON-RPC 2.0 over stdin/stdout with the Paperclip host; (3) sidecar mode as a CLI run-mode flag (`--sidecar`) that starts a stripped FastAPI app sharing all core services with the full dashboard.

**Major components:**

1. `SidecarOrchestrator` (NEW Python, `core/sidecar_orchestrator.py`) — drives the inject-route-execute-learn cycle: recall memories, resolve provider/model, spawn AgentRuntime subprocess, extract learnings, POST callback to Paperclip
2. `MemoryBridge` (NEW Python, thin wrapper) — `recall()` before execution with 200ms hard timeout via `asyncio.timeout(0.2)`; `learn()` after via fire-and-forget `asyncio.create_task()`
3. `TieredRoutingBridge` (NEW Python, thin wrapper) — maps Paperclip task metadata (wakeReason, agentRole) to Agent42 provider/model selection via existing RewardSystem
4. `dashboard/sidecar.py` (NEW Python) — stripped FastAPI app with sidecar routes only; no WebSocket manager, no static files, no dashboard auth middleware
5. `adapters/agent42-paperclip/` (NEW TypeScript) — implements Paperclip's `ServerAdapterModule`: `execute()`, `testEnvironment()`, `sessionCodec()`
6. `plugins/agent42-paperclip-plugin/` (NEW TypeScript) — plugin worker with memory tools, MCP proxy, and UI slots (detailTab, dashboardWidget)
7. All existing Agent42 services — MemoryStore, QdrantStore, AgentRuntime, EffectivenessStore, RewardSystem, AgentManager, MCP server — unchanged

The SidecarOrchestrator execute cycle:

```text
Paperclip POST -> SidecarRoutes -> 202 Accepted
                    -> MemoryBridge.recall()  (200ms cap)
                    -> TieredRoutingBridge.resolve()
                    -> AgentRuntime.execute() (subprocess)
                    -> MemoryBridge.learn()   (fire-and-forget)
                    -> EffectivenessStore.record()
                    -> POST callback to Paperclip
```

See `.planning/research/ARCHITECTURE.md` for the full system diagram, all data flow sequences, and code patterns for each component.

### Critical Pitfalls

1. **Agent ID mismatch orphans all memories** — When importing agents into Paperclip, if IDs are regenerated, all Qdrant memories and SQLite effectiveness data become unreachable. Prevention: preserve Agent42 agent UUIDs as `adapterConfig.agentId` in Paperclip. Migration script must enforce 1:1 UUID mapping.

2. **Sidecar health check race on Docker startup** — Paperclip probes the adapter before Agent42 is ready. FastAPI+uvicorn takes 2-5s; Qdrant embedded mode takes longer. Prevention: Docker Compose `healthcheck` on Agent42 service plus exponential backoff retry in the TypeScript adapter.

3. **Duplicate budget tracking** — Both Paperclip and Agent42's SpendingTracker track costs. In sidecar mode, Agent42 must report costs to Paperclip but must NOT enforce its own budget limits. Budget enforcement is Paperclip's job; SpendingTracker becomes a data source only.

4. **Memory injection latency on heartbeat hot path** — Qdrant search adds 200-500ms. Prevention: hard-cap recall at 200ms via `asyncio.timeout(0.2)` and always use the async 202 callback pattern so memory injection does not block the heartbeat response.

5. **Windows CRLF in TypeScript build artifacts** — Git on Windows converts LF to CRLF, which breaks JSON-RPC newline-delimited protocol. Prevention: `.gitattributes` on `*.ts` and `*.json` files with `eol=lf` in both adapter and plugin packages — enforce on day one.

Additional documented pitfalls (MEDIUM severity): standalone mode regression (P6), multi-tenant memory isolation (P7), plugin SDK version drift (P8), duplicate transcript storage (P9), Docker Compose port conflicts (P10), iframe temptation (P11), TypeScript monorepo complexity (P12).

See `.planning/research/PITFALLS.md` for full list with phase assignments.

## Implications for Roadmap

The feature dependency graph drives a clear 4-phase structure. Two tracks can run partially in parallel within phases (Python sidecar track and TypeScript plugin/adapter track), but the sidecar must reach working status before end-to-end integration testing is possible. Phase boundaries are integration test gates.

### Phase 1: Sidecar + HTTP Adapter Foundation

**Rationale:** The sidecar endpoint is the hard dependency for everything. Without `POST /api/paperclip/heartbeat` responding correctly, Paperclip cannot invoke Agent42 and no other integration work can be validated end-to-end. The TypeScript adapter package can be scaffolded in parallel but requires the sidecar to exist before any live testing. This phase must be complete before plugin work begins.

**Delivers:** Agent42 is a functional Paperclip execution backend. Paperclip operators can configure an agent to run "on Agent42" and receive results with cost reporting in the AdapterExecutionResult shape. Docker Compose deployment is working.

**Addresses features:** All table-stakes adapter features — heartbeat endpoint, AdapterExecutionResult response, async 202+callback, runId idempotency, health check, sidecar mode, Bearer auth, structured logging, Docker `--target sidecar` image

**Avoids pitfalls:** P5 (CRLF — enforce via `.gitattributes` at project creation), P2 (Docker startup race — Docker Compose healthcheck), P6 (standalone mode regression — `--sidecar` is an additive flag, existing `python agent42.py` behavior unchanged)

**Research flag:** Standard patterns. No research phase needed. The HTTP adapter pattern is documented in Paperclip's official Mintlify docs and the hermes-paperclip-adapter is a high-quality reference implementation. Async 202+callback is standard HTTP. All components map to existing Agent42 code.

### Phase 2: Plugin Scaffold + Memory Tools

**Rationale:** Plugin scaffold is independent of adapter code (separate TypeScript package, separate Paperclip extension surface). Once the sidecar exposes memory endpoints, the plugin memory tools are thin HTTP wrappers — low complexity, high value. This phase closes the minimum viable integration: agents can recall context and store learnings within Paperclip heartbeat sessions. Memory tools require zero new Agent42 backend code — `MemoryStore.search()` and `MemoryStore.store()` already exist.

**Delivers:** Agent42's intelligence is accessible to Paperclip agents as callable tools. Operators install the plugin and immediately see memory-enhanced agent behavior. Routing decisions are available to agents via `route_task`. Effectiveness data is surfaced via `tool_effectiveness`.

**Uses:** `@paperclipai/plugin-sdk` (pin to specific version), existing MemoryStore, existing tiered routing layer, existing EffectivenessStore

**Implements:** Plugin scaffold (manifest + `setup(ctx)` + lifecycle handlers), `memory_recall` tool, `memory_store` tool, `route_task` tool, `tool_effectiveness` tool

**Avoids pitfalls:** P3 (duplicate budget — `route_task` returns recommendations, does not gate), P7 (multi-tenant isolation — start with one sidecar per company; add `company_id` Qdrant filter only if needed), P8 (SDK version drift — pin `@paperclipai/plugin-sdk` version, abstract SDK calls behind wrapper), P11 (iframe temptation — use native plugin UI slots only, no iframe)

**Research flag:** Needs `/gsd:research-phase` before implementation. Plugin SDK was released March 18, 2026 — 10 days before this research. The `executeTool` handler signatures, `ctx.http.fetch` contract, and plugin lifecycle sequence need hands-on verification from the SDK source before writing implementation code.

### Phase 3: Plugin UI + Learning Extraction

**Rationale:** The `extract_learnings` job closes the intelligence feedback loop — extracted learnings from Paperclip run transcripts feed back into memory_recall, making agents progressively smarter over time. UI slots give operators visibility into what Agent42 is doing inside Paperclip. Both require the Phase 2 plugin scaffold to be in place and stable.

**Delivers:** Operators can see agent effectiveness tiers (Bronze/Silver/Gold), provider health status, and memory traceability on Paperclip pages. The hourly extract_learnings job continuously improves agent memory quality by processing Paperclip run transcripts through the existing learning extraction pipeline. Full Docker Compose deployment including PostgreSQL.

**Uses:** `@paperclipai/plugin-sdk/ui` React components, Paperclip run transcript API (heartbeatRunEvents), existing learning extraction pipeline, existing SpendingTracker for provider health data

**Implements:** `extract_learnings` hourly cron job, agent effectiveness `detailTab`, provider health `dashboardWidget`, memory browser `detailTab` on run pages, Docker Compose with PostgreSQL

**Avoids pitfalls:** P1 (agent ID mismatch — extract_learnings must key memories to preserved agent UUIDs), P9 (duplicate transcripts — store only structured learnings/embeddings, not raw transcript text), P10 (Docker port conflicts — all five ports configurable via env vars)

**Research flag:** Needs `/gsd:research-phase` before planning. Two specific gaps: (a) how does a plugin access `heartbeatRunEvents` from within the plugin worker context (required for extract_learnings), and (b) what are the exact `detailTab` and `dashboardWidget` slot rendering APIs in the SDK. Neither is clearly documented in current sources.

### Phase 4: Advanced Features (Post-Validation)

**Rationale:** TeamTool strategies and automatic memory injection are high-complexity, high-value features that require production validation first. The `heartbeat.started` event (required for automatic injection) is documented only as RFC #206, not as a shipped feature. The TeamTool fan-out pattern requires async callback timing validation against Paperclip's run timeout policy. The wave strategy requires Paperclip comment threading API write access that has not been confirmed available.

**Delivers:** Agent42 can fan out parallel sub-agents within a single Paperclip task. Memory injection becomes automatic rather than tool-initiated. Migration tooling allows existing Agent42 users to import their agents and preserve their memory history.

**Implements:** Automatic memory injection on heartbeat (if `heartbeat.started` event exists), TeamTool fan-out strategy, TeamTool wave strategy, migration CLI (`agent42-to-paperclip`), routing decisions `dashboardWidget`

**Avoids pitfalls:** P1 (ID mismatch — migration CLI must enforce UUID preservation), P4 (memory latency — automatic injection must remain async and non-blocking)

**Research flag:** Needs `/gsd:research-phase` before planning Phase 4. Must verify: (a) `heartbeat.started` event exists in shipped Paperclip (RFC #206 only), (b) TeamTool async callback timing vs. Paperclip run timeout policy, (c) Paperclip API write access for comment threading (wave strategy dependency).

### Phase Ordering Rationale

- Sidecar first because it unblocks all integration testing. Nothing can be validated end-to-end without it.
- Plugin after adapter because they are independent TypeScript packages on separate extension surfaces, but memory tools require the sidecar's memory endpoints to exist before they can be tested.
- UI and learning extraction after memory tools because they depend on the plugin scaffold and because `extract_learnings` needs the memory data model from Phase 2 to be stable.
- Advanced features last because they depend on production validation and include unverified Paperclip API features (heartbeat.started event, comment threading write API).
- Python track (SidecarOrchestrator, MemoryBridge, sidecar.py) and TypeScript track (adapter package, plugin package) can run in parallel within each phase, but must converge at phase-boundary integration tests.

### Research Flags

Phases needing `/gsd:research-phase` before implementation:

- **Phase 2:** Plugin SDK `executeTool` handler signatures and `ctx.http.fetch` contract — SDK is 10 days old, verify against actual source before writing handlers.
- **Phase 3:** Paperclip run transcript access from plugin context (`heartbeatRunEvents` API) and `detailTab`/`dashboardWidget` slot rendering APIs — not found in current documentation.
- **Phase 4:** Three external dependencies must be verified before planning: `heartbeat.started` event availability, TeamTool async timing vs. Paperclip timeout policy, Paperclip comment threading write API.

Phases with standard patterns (skip research-phase):

- **Phase 1 — HTTP adapter + sidecar:** Well-documented via hermes-paperclip-adapter reference implementation, official Paperclip HTTP adapter Mintlify docs, and Paperclip PLUGIN_SPEC.md. Async 202+callback is standard HTTP. All maps directly to existing Agent42 code patterns.

## Confidence Assessment

| Area | Confidence | Notes |
| --- | --- | --- |
| Stack | HIGH | TypeScript/Node.js/pnpm requirements from official Paperclip docs. Python sidecar requirements from direct Agent42 codebase inspection. No speculation. |
| Features | HIGH (adapter), MEDIUM (plugin) | Adapter spec documented with reference implementations. Plugin SDK released March 18, 2026 — feature set documented, but runtime behavior and `executeTool` signatures need hands-on validation. |
| Architecture | HIGH | System diagram derived from Paperclip monorepo structure (DeepWiki), hermes-paperclip-adapter reference code, official adapter spec, and direct Agent42 codebase inspection. All component boundaries are concrete. |
| Pitfalls | HIGH (P1-P6), MEDIUM (P7-P12) | Critical pitfalls are well-documented cross-language integration patterns. Paperclip-specific pitfalls (SDK drift, transcript isolation) are based on platform maturity inference given rapid release cadence. |

**Overall confidence:** HIGH for Phase 1 and 2 scope. MEDIUM for Phase 3 plugin UI details. LOW for Phase 4 (depends on unverified Paperclip API features).

### Gaps to Address

- **`heartbeat.started` event existence:** RFC #206 proposes this event but it may not be in the shipped platform. Must verify before designing Phase 4 automatic memory injection. If it does not exist, automatic injection requires a polling alternative.
- **Plugin SDK `executeTool` handler interface:** SDK released March 18, 2026. Exact handler signatures and `ctx.http.fetch` contract should be verified from SDK source before Phase 2 implementation begins.
- **Paperclip run transcript access from plugin:** How a plugin reads `heartbeatRunEvents` from within the plugin worker context is not documented in current sources. Required for the Phase 3 `extract_learnings` job.
- **Paperclip comment threading write API:** Required for TeamTool wave strategy (Phase 4). Whether Paperclip exposes a write API for comment threading needs confirmation.
- **Multi-tenant sidecar at scale:** Research recommends one sidecar per company as the simplest approach, but at large Paperclip installations with many companies, this approach may not scale. Flag for validation during Phase 2 deployment and plan the `company_id` Qdrant filter (option b) as a fallback.

## Sources

### Primary (HIGH confidence)

- [Paperclip GitHub](https://github.com/paperclipai/paperclip) — official monorepo, adapter registry, heartbeat payload shapes
- [Paperclip PLUGIN_SPEC.md](https://github.com/paperclipai/paperclip/blob/master/doc/plugins/PLUGIN_SPEC.md) — plugin manifest format, capability declarations, JSON-RPC protocol
- [HTTP Adapter docs — Mintlify](https://www.mintlify.com/paperclipai/paperclip/agents/http-adapter) — AdapterExecutionContext/Result shapes, async callback pattern
- [@paperclipai/plugin-sdk npm](https://www.npmjs.com/package/@paperclipai/plugin-sdk) — released March 18, 2026; version 2026.318.0
- Agent42 codebase — direct inspection of MemoryStore, AgentRuntime, EffectivenessStore, RewardSystem, AgentManager, MCP server

### Secondary (MEDIUM confidence)

- [Plugin Architecture and Runtime — DeepWiki](https://deepwiki.com/paperclipai/paperclip/9.1-plugin-architecture-and-runtime) — system architecture analysis of Paperclip monorepo
- [Local CLI Adapters — DeepWiki](https://deepwiki.com/paperclipai/paperclip/5.2-local-cli-adapters) — adapter pattern analysis
- [Hermes Paperclip Adapter](https://github.com/NousResearch/hermes-paperclip-adapter) — reference implementation for sessionCodec, async callback, and session key strategy
- [OpenClaw Gateway Adapter — DeepWiki](https://deepwiki.com/paperclipai/paperclip/5.3-openclaw-gateway-adapter) — gateway adapter pattern (compared, not used)
- [Paperclip Monorepo Structure — DeepWiki](https://deepwiki.com/paperclipai/paperclip/1.2-monorepo-structure) — package layout and adapter registry structure

### Tertiary (LOW confidence / needs validation)

- [RFC: Proactive heartbeat pattern #206](https://github.com/paperclipai/paperclip/issues/206) — `heartbeat.started` event proposal; not confirmed shipped; Phase 4 depends on this
- [Plugin System Discussion #258](https://github.com/paperclipai/paperclip/discussions/258) — community discussion on plugin patterns; needs cross-reference with actual SDK

---
*Research completed: 2026-03-28*
*Ready for roadmap: yes*
