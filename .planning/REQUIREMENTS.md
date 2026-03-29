# Requirements: Agent42 v4.0 Paperclip Integration

**Defined:** 2026-03-28
**Core Value:** Agent42 must always be able to run agents reliably, with tiered provider routing ensuring no single provider outage stops the platform.

## v1 Requirements

Requirements for this milestone. Each maps to roadmap phases.

### Sidecar Mode

- [x] **SIDE-01**: Agent42 starts in sidecar mode via `--sidecar` flag, exposing adapter-friendly endpoints without dashboard UI
- [x] **SIDE-02**: Sidecar accepts heartbeat execution requests via `POST /sidecar/execute` with Paperclip's AdapterExecutionContext payload
- [x] **SIDE-03**: Sidecar returns 202 Accepted for long-running tasks and POSTs results to Paperclip's callback endpoint when done
- [x] **SIDE-04**: Sidecar exposes `GET /sidecar/health` returning memory, provider, and Qdrant connectivity status
- [x] **SIDE-05**: Sidecar validates Bearer token auth on all endpoints (reuses existing JWT middleware)
- [x] **SIDE-06**: Sidecar deduplicates execution requests by `runId` to prevent duplicate work on retries
- [x] **SIDE-07**: Sidecar produces structured JSON logging (no ANSI codes, no spinners) suitable for log aggregation
- [x] **SIDE-08**: Core services (MemoryStore, QdrantStore, AgentRuntime, EffectivenessStore) start identically in sidecar and dashboard modes
- [x] **SIDE-09**: Config extends with PAPERCLIP_SIDECAR_PORT, PAPERCLIP_API_URL, SIDECAR_ENABLED settings

### Memory Bridge

- [ ] **MEM-01**: MemoryBridge.recall() retrieves top-K relevant memories for an agent+task before execution starts
- [ ] **MEM-02**: Memory recall has a 200ms hard timeout — returns empty list on timeout, never blocks execution
- [ ] **MEM-03**: MemoryBridge.learn_async() extracts learnings from agent transcripts via fire-and-forget after execution
- [ ] **MEM-04**: Sidecar exposes `POST /memory/recall` and `POST /memory/store` endpoints for plugin access
- [ ] **MEM-05**: Memory scope supports agent-level and company-level isolation (agent_id vs company_id partitioning)

### Tiered Routing Bridge

- [ ] **ROUTE-01**: TieredRoutingBridge maps Paperclip agent roles (engineer/researcher/writer/analyst) to Agent42 task categories
- [ ] **ROUTE-02**: Routing bridge queries RewardSystem for agent tier and upgrades model selection accordingly
- [ ] **ROUTE-03**: AdapterConfig.preferredProvider overrides default provider selection when set
- [ ] **ROUTE-04**: Routing bridge reports costUsd, usage tokens, model, and provider in callback response for Paperclip budget tracking

### Paperclip Adapter

- [ ] **ADAPT-01**: TypeScript adapter package implements Paperclip's ServerAdapterModule interface (execute, testEnvironment)
- [ ] **ADAPT-02**: Adapter POSTs to Agent42 sidecar and handles both synchronous and async (202+callback) response patterns
- [ ] **ADAPT-03**: Adapter maps wakeReason (heartbeat/task_assigned/manual) to appropriate execution behavior
- [ ] **ADAPT-04**: Adapter preserves Agent42 agent ID in adapterConfig.agentId for memory and effectiveness continuity
- [ ] **ADAPT-05**: Adapter includes sessionCodec for cross-heartbeat state persistence

### Paperclip Plugin

- [ ] **PLUG-01**: Plugin package has valid manifest.json with apiVersion 1, capability declarations, and instance config schema
- [ ] **PLUG-02**: Plugin registers `memory_recall` agent tool — agents query semantically relevant memories by providing query, agentId, taskType
- [ ] **PLUG-03**: Plugin registers `memory_store` agent tool — agents persist learnings with content, agentId, tags
- [ ] **PLUG-04**: Plugin registers `route_task` agent tool — agents get optimal provider+model recommendation for a task type and quality target
- [ ] **PLUG-05**: Plugin registers `tool_effectiveness` agent tool — agents query top tools by success rate for their task type
- [ ] **PLUG-06**: Plugin exposes `mcp_tool_proxy` tool — agents invoke any Agent42 MCP tool through the plugin
- [ ] **PLUG-07**: Plugin implements health(), initialize(config), and onShutdown() lifecycle handlers

### Plugin UI

- [ ] **UI-01**: Agent effectiveness detailTab on Paperclip agent pages shows tier badge, success rates by task type, model routing history
- [ ] **UI-02**: Provider health dashboardWidget shows Agent42 provider availability at a glance
- [ ] **UI-03**: Memory browser detailTab on run pages shows which memories were injected and which learnings were extracted
- [ ] **UI-04**: Routing decisions dashboardWidget shows token spend distribution across providers over last 24h

### Learning Extraction

- [ ] **LEARN-01**: extract_learnings job runs hourly, fetches recent Paperclip run transcripts, extracts structured learnings, stores in Qdrant
- [ ] **LEARN-02**: Extracted learnings feed into memory_recall results for future agent executions

### Advanced Features

- [ ] **ADV-01**: Automatic memory injection on heartbeat — plugin subscribes to heartbeat event and prepends relevant context to agent prompt
- [ ] **ADV-02**: TeamTool fan-out strategy — tasks tagged strategy:fan-out spawn parallel sub-agents and aggregate results
- [ ] **ADV-03**: TeamTool wave strategy — sequential wave execution mapped to single Paperclip ticket lifecycle
- [ ] **ADV-04**: Migration CLI imports existing Agent42 agents into Paperclip company structure preserving agent IDs
- [ ] **ADV-05**: Docker Compose config runs Paperclip + Agent42 sidecar + Qdrant + PostgreSQL with health checks and configurable ports

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Scaling & Multi-Tenant

- **SCALE-01**: Multi-company Qdrant partitioning (company_id filter on all collections)
- **SCALE-02**: Multiple sidecar instances behind nginx proxy for high-agent-count deployments
- **SCALE-03**: Plugin per-company config via plugin_state keyed by companyId

### Marketplace

- **MARKET-01**: Publish Agent42 plugin to ClipMart marketplace
- **MARKET-02**: Pre-built company templates featuring Agent42-powered agents

## Out of Scope

| Feature | Reason |
| ------- | ------ |
| TypeScript rewrite of Agent42 sidecar | Agent42's value (ONNX, Qdrant, asyncio) is Python-native; rewriting wastes months |
| Agent42 plugin managing Paperclip budgets | Budget authority belongs to Paperclip; dual accounting creates drift |
| Full Agent42 dashboard embedded via iframe | Maintenance liability; use native Paperclip UI slots instead |
| Plugin storing full conversation transcripts | Transcripts live in Paperclip's DB; duplicating creates bloat and consistency issues |
| Agent42 reading Paperclip's PostgreSQL directly | Creates tight schema coupling; trust the AdapterExecutionContext payload |
| Per-company plugin instances | Plugins are installation-global by design; use per-company config in plugin_state |

## Traceability

| Requirement | Phase | Status |
| ----------- | ----- | ------ |
| SIDE-01 | Phase 24 | Complete — 24-03 |
| SIDE-02 | Phase 24 | Complete — 24-02 |
| SIDE-03 | Phase 24 | Complete — 24-02 |
| SIDE-04 | Phase 24 | Complete — 24-02 |
| SIDE-05 | Phase 24 | Complete — 24-02 |
| SIDE-06 | Phase 24 | Complete — 24-02 |
| SIDE-07 | Phase 24 | Complete — 24-01 |
| SIDE-08 | Phase 24 | Complete — 24-03 |
| SIDE-09 | Phase 24 | Complete — 24-01 |
| MEM-01 | Phase 25 | Pending |
| MEM-02 | Phase 25 | Pending |
| MEM-03 | Phase 25 | Pending |
| MEM-04 | Phase 25 | Pending |
| MEM-05 | Phase 25 | Pending |
| ROUTE-01 | Phase 26 | Pending |
| ROUTE-02 | Phase 26 | Pending |
| ROUTE-03 | Phase 26 | Pending |
| ROUTE-04 | Phase 26 | Pending |
| ADAPT-01 | Phase 27 | Pending |
| ADAPT-02 | Phase 27 | Pending |
| ADAPT-03 | Phase 27 | Pending |
| ADAPT-04 | Phase 27 | Pending |
| ADAPT-05 | Phase 27 | Pending |
| PLUG-01 | Phase 28 | Pending |
| PLUG-02 | Phase 28 | Pending |
| PLUG-03 | Phase 28 | Pending |
| PLUG-04 | Phase 28 | Pending |
| PLUG-05 | Phase 28 | Pending |
| PLUG-06 | Phase 28 | Pending |
| PLUG-07 | Phase 28 | Pending |
| UI-01 | Phase 29 | Pending |
| UI-02 | Phase 29 | Pending |
| UI-03 | Phase 29 | Pending |
| UI-04 | Phase 29 | Pending |
| LEARN-01 | Phase 29 | Pending |
| LEARN-02 | Phase 29 | Pending |
| ADV-01 | Phase 30 | Pending |
| ADV-02 | Phase 30 | Pending |
| ADV-03 | Phase 30 | Pending |
| ADV-04 | Phase 31 | Pending |
| ADV-05 | Phase 31 | Pending |

**Coverage:**

- v1 requirements: 41 total
- Mapped to phases: 41
- Unmapped: 0 ✓

---

*Requirements defined: 2026-03-28*
*Last updated: 2026-03-28 — traceability updated with milestone phase numbers (24-31)*
