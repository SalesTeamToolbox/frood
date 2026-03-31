# Roadmap: Agent42

## Milestones

- ✅ **v1.0 Free LLM Provider Expansion** — Phases 1-6 (shipped 2026-03-02)
- ✅ **v1.1** — (shipped)
- ✅ **v1.2 Claude Code Automation** — Phases 11-16 (shipped 2026-03-07)
- ✅ **v1.4 Per-Project/Task Memories** — Phases 20-23 (shipped 2026-03-22)
- ✅ **v1.5 Intelligent Memory Bridge** — 4 phases (shipped 2026-03-22)
- ✅ **v1.6 UX & Workflow Automation** — 4 phases (shipped 2026-03-22)
- ✅ **rewards-v1.0 Performance-Based Rewards** — 4 phases, 7 plans (shipped 2026-03-25)
- ✅ **v2.1 Multi-Project Workspace** — 3 phases (shipped 2026-03-24)
- 🚧 **v2.0 Custom Claude Code UI** — Phases 1-4 complete, 5-6 remaining
- 🚧 **v3.0 GSD & jcodemunch Integration** — Phase 1 complete, Phases 2-4 remaining
- 🚧 **v4.0 Paperclip Integration** — Phases 24-31 (in progress)

## Active Workstreams

Each workstream has its own ROADMAP.md, REQUIREMENTS.md, and phase directories.

### 🚧 GSD & jcodemunch Integration (active)

See: `workstreams/gsd-and-jcodemunch-integration/ROADMAP.md`

- [x] Phase 1: Setup Foundation (3/3 plans)
- [x] Phase 2: Windows + CLAUDE.md (2/2 plans)
- [x] Phase 3: Memory Sync (3/3 plans)
- [ ] Phase 4: Context Engine (0 plans — not started)

### 🚧 Custom Claude Code UI

See: `workstreams/custom-claude-code-ui/ROADMAP.md`

Phases 1-4 complete, Phases 5-6 remaining (PTY streaming + chat UX polish).

## 🚧 v4.0 Paperclip Integration (In Progress)

**Milestone Goal:** Integrate Agent42 with Paperclip as a plugin+adapter — Paperclip handles org management, scheduling, budgets, and governance; Agent42 contributes the intelligence layer (semantic memory, tiered routing, effectiveness tracking, MCP tools).

### Phases

- [x] **Phase 24: Sidecar Mode** — Agent42 runs as a stripped FastAPI sidecar with adapter-friendly endpoints
- [ ] **Phase 25: Memory Bridge** — MemoryBridge recalls and learns from Paperclip agent transcripts
- [ ] **Phase 26: Tiered Routing Bridge** — Paperclip agent roles map to Agent42 provider/model selection
- [ ] **Phase 27: Paperclip Adapter** — TypeScript adapter package implements Paperclip's ServerAdapterModule
- [ ] **Phase 28: Paperclip Plugin** — Plugin package registers memory tools, MCP proxy, and lifecycle handlers
- [ ] **Phase 29: Plugin UI + Learning Extraction** — Effectiveness panel, provider health widget, memory browser, hourly learning job
- [ ] **Phase 30: Advanced — TeamTool + Auto Memory** — Fan-out/wave strategies and automatic memory injection on heartbeat
- [ ] **Phase 31: Advanced — Migration + Docker** — Migration CLI and Docker Compose deployment

## Phase Details

### Phase 24: Sidecar Mode

**Goal**: Agent42 is a functional Paperclip execution backend that Paperclip operators can configure to run agents on, receiving results with cost reporting
**Depends on**: Nothing (first phase of this milestone)
**Requirements**: SIDE-01, SIDE-02, SIDE-03, SIDE-04, SIDE-05, SIDE-06, SIDE-07, SIDE-08, SIDE-09
**Success Criteria** (what must be TRUE):

1. Running `python agent42.py --sidecar` starts a stripped FastAPI server with no dashboard — the web UI does not load
2. A Paperclip operator can POST to `/sidecar/execute` with an AdapterExecutionContext payload and receive a 202 Accepted response, then a callback when execution completes
3. A second POST with the same runId returns without re-executing the task (idempotency guard works)
4. `GET /sidecar/health` returns memory, provider, and Qdrant connectivity status as structured JSON
5. All sidecar endpoints reject requests without a valid Bearer token with 401

**Plans:** 3 plans

Plans:
- [x] 24-01-PLAN.md — Foundation: config fields, Pydantic models, JSON formatter
- [x] 24-02-PLAN.md — Sidecar server: app factory with routes, orchestrator
- [x] 24-03-PLAN.md — Integration: CLI wiring, Agent42 sidecar branch, tests

### Phase 25: Memory Bridge

**Goal**: Agent42 memory is injectable before and extractable after every Paperclip agent execution, with agent-level and company-level scope isolation
**Depends on**: Phase 24
**Requirements**: MEM-01, MEM-02, MEM-03, MEM-04, MEM-05
**Success Criteria** (what must be TRUE):

1. Before execution, MemoryBridge.recall() returns relevant memories for an agent+task and completes within 200ms — if Qdrant is slow, it returns an empty list without blocking
2. After execution, MemoryBridge.learn_async() extracts learnings from the agent transcript in the background without adding latency to the callback response
3. A plugin client can POST to `/memory/recall` specifying an agentId or companyId and receive only memories scoped to that partition
4. Two agents with different agent_ids do not see each other's memories when recalling

**Plans:** 2 plans

Plans:
- [x] 25-01-PLAN.md — Pydantic models, QdrantStore indexes, MemoryBridge class
- [x] 25-02-PLAN.md — HTTP routes, orchestrator wiring, test suite

### Phase 26: Tiered Routing Bridge

**Goal**: Paperclip agent roles and task metadata drive Agent42 provider and model selection, with tier upgrades for high-performing agents and cost reporting back to Paperclip
**Depends on**: Phase 24
**Requirements**: ROUTE-01, ROUTE-02, ROUTE-03, ROUTE-04
**Success Criteria** (what must be TRUE):

1. A Paperclip agent with role "engineer" routes to Agent42's coding task category; a "researcher" routes to research — the mapping is observable in sidecar logs
2. A Gold-tier agent receives a higher-capability model than a Bronze-tier agent for the same task type
3. Setting AdapterConfig.preferredProvider overrides the default provider selection for that execution
4. Every callback response to Paperclip includes costUsd, token counts, model name, and provider name for budget tracking

**Plans:** 2 plans

Plans:
- [x] 26-01-PLAN.md — TieredRoutingBridge class, RoutingDecision dataclass, full test suite
- [x] 26-02-PLAN.md — Orchestrator wiring, app factory injection, integration tests

### Phase 27: Paperclip Adapter

**Goal**: A TypeScript adapter package fully implements Paperclip's ServerAdapterModule interface and can be installed in a Paperclip deployment to route agent executions to the Agent42 sidecar
**Depends on**: Phase 24, Phase 25, Phase 26
**Requirements**: ADAPT-01, ADAPT-02, ADAPT-03, ADAPT-04, ADAPT-05
**Success Criteria** (what must be TRUE):

1. Installing the adapter package and configuring it with a sidecar URL causes Paperclip to route agent heartbeats to Agent42 — end-to-end execution completes without error
2. When Agent42 returns 202 Accepted, the adapter waits for the async callback and surfaces the result to Paperclip correctly
3. A heartbeat with wakeReason "task_assigned" triggers a different execution path than "heartbeat" — observable in sidecar logs
4. Agent memory and effectiveness data persist across multiple heartbeat sessions because the adapter preserves the Agent42 agent UUID

**Plans:** 2 plans

Plans:
- [x] 27-01-PLAN.md -- Package scaffold, types.ts contracts, Agent42Client HTTP client
- [x] 27-02-PLAN.md -- Adapter module (execute + testEnvironment), session codec, test suite

### Phase 28: Paperclip Plugin

**Goal**: The Agent42 Paperclip plugin is installable, passes validation, and gives Paperclip agents access to memory recall, memory store, routing recommendations, effectiveness data, and MCP tool proxying as callable tools
**Depends on**: Phase 25, Phase 26
**Requirements**: PLUG-01, PLUG-02, PLUG-03, PLUG-04, PLUG-05, PLUG-06, PLUG-07
**Success Criteria** (what must be TRUE):

1. Running `paperclip doctor` against an installation with the plugin shows the plugin passes health checks
2. A Paperclip agent can call the `memory_recall` tool during execution and receive semantically relevant memories from Agent42
3. A Paperclip agent can call the `memory_store` tool and the stored content is retrievable in a subsequent `memory_recall` call
4. A Paperclip agent can call `route_task` and receive a provider+model recommendation; calling `tool_effectiveness` returns top tools by success rate
5. A Paperclip agent can invoke any Agent42 MCP tool via `mcp_tool_proxy` and receive the tool's output

**Plans:** 3 plans

Plans:
- [x] 28-01-PLAN.md — Sidecar extensions: Pydantic models, config, routing/effectiveness/MCP endpoints
- [x] 28-02-PLAN.md — Plugin package scaffold: manifest, types, Agent42Client, client tests
- [x] 28-03-PLAN.md — Plugin worker, tool registrations, lifecycle handlers, full test suite

### Phase 29: Plugin UI + Learning Extraction

**Goal**: Operators can see agent effectiveness tiers, provider health, and memory traceability in native Paperclip UI slots, and an hourly job continuously improves agent memory by extracting structured learnings from Paperclip run transcripts
**Depends on**: Phase 28
**Requirements**: UI-01, UI-02, UI-03, UI-04, LEARN-01, LEARN-02
**Success Criteria** (what must be TRUE):

1. Opening a Paperclip agent page shows an "Effectiveness" detail tab with the agent's Bronze/Silver/Gold tier badge, success rates by task type, and recent model routing history
2. The Paperclip dashboard shows a provider health widget displaying which Agent42 providers are currently available
3. Opening a Paperclip run page shows a memory browser tab listing which memories were injected before the run and which learnings were extracted after
4. One hour after the extract_learnings job runs, a subsequent `memory_recall` for the same agent type returns learnings derived from Paperclip run transcripts — demonstrating the feedback loop is closed

**Plans:** 3 plans

Plans:
- [x] 29-01-PLAN.md — Python sidecar data endpoints, run_id threading, transcript capture, SQLite tables
- [x] 29-02-PLAN.md — TypeScript plugin wiring: manifest, client methods, worker data/job handlers
- [ ] 29-03-PLAN.md — React UI components, esbuild build, visual checkpoint

### Phase 30: Advanced — TeamTool + Auto Memory

**Goal**: Agent42 can fan out parallel sub-agents and run sequential wave workflows within a single Paperclip task, and memory injection becomes automatic on heartbeat rather than requiring an explicit tool call
**Depends on**: Phase 28, Phase 29
**Requirements**: ADV-01, ADV-02, ADV-03
**Success Criteria** (what must be TRUE):

1. A task tagged with strategy:fan-out spawns parallel sub-agents and aggregates their results back into a single Paperclip run — all sub-agent outputs appear in the run transcript
2. A task using the wave strategy executes sub-agents sequentially, with each wave's output available as input to the next wave within the same Paperclip ticket lifecycle
3. On heartbeat start, relevant memories are automatically prepended to the agent prompt without the agent needing to call `memory_recall` — observable in the run transcript context

**Plans**: TBD

### Phase 31: Advanced — Migration + Docker

**Goal**: Existing Agent42 users can import their agents into Paperclip preserving all memory and effectiveness history, and the full stack can be deployed with a single Docker Compose command
**Depends on**: Phase 27, Phase 28
**Requirements**: ADV-04, ADV-05
**Success Criteria** (what must be TRUE):

1. Running the migration CLI with an existing Agent42 agent database imports agents into Paperclip company structure and the imported agents can recall their pre-migration memories immediately
2. Running `docker compose up` starts Paperclip, Agent42 sidecar, Qdrant, and PostgreSQL with health checks — all services reach healthy status without manual intervention
3. Agent42 sidecar in Docker Compose can be reached by the Paperclip container and processes a test heartbeat execution successfully

**Plans**: TBD

## Completed Workstreams

<details>
<summary>✅ rewards-v1.0 Performance-Based Rewards (4 phases) — SHIPPED 2026-03-25</summary>

- [x] Phase 1: Foundation (2/2 plans) — completed 2026-03-22
- [x] Phase 2: Tier Assignment (2/2 plans) — completed 2026-03-22
- [x] Phase 3: Resource Enforcement (1/1 plan) — completed 2026-03-23
- [x] Phase 4: Dashboard (2/2 plans) — completed 2026-03-23

Archive: `workstreams/performance-based-rewards/milestones/`

</details>

<details>
<summary>✅ v2.1 Multi-Project Workspace (3 phases) — SHIPPED 2026-03-24</summary>

- [x] Phase 1: Registry & Namespacing — completed 2026-03-24
- [x] Phase 2: IDE Surface Integration — completed 2026-03-24
- [x] Phase 3: Workspace Management — completed 2026-03-24

Archive: `workstreams/multi-project-workspace/`

</details>

<details>
<summary>✅ v1.6 UX & Workflow Automation (4 phases) — SHIPPED 2026-03-22</summary>

Archive: `milestones/v1.6-ROADMAP.md`

</details>

<details>
<summary>✅ v1.5 Intelligent Memory Bridge (4 phases) — SHIPPED 2026-03-22</summary>

Archive: `milestones/v1.5-ROADMAP.md`

</details>

<details>
<summary>✅ v1.4 Per-Project/Task Memories (4 phases) — SHIPPED 2026-03-22</summary>

Archive: `milestones/v1.4-ROADMAP.md`

</details>

<details>
<summary>✅ v1.2 Claude Code Automation (6 phases) — SHIPPED 2026-03-07</summary>

Archive: `milestones/v1.2-ROADMAP.md`

</details>

<details>
<summary>✅ v1.0 Free LLM Provider Expansion (6 phases) — SHIPPED 2026-03-02</summary>

Archive: `milestones/v1.0-ROADMAP.md`

</details>

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
| ------- | ----------- | ---------------- | -------- | ----------- |
| 24. Sidecar Mode | v4.0 | 3/3 | Complete | 2026-03-29 |
| 25. Memory Bridge | v4.0 | 2/2 | Complete    | 2026-03-29 |
| 26. Tiered Routing Bridge | v4.0 | 2/2 | Complete   | 2026-03-30 |
| 27. Paperclip Adapter | v4.0 | 2/2 | Complete    | 2026-03-30 |
| 28. Paperclip Plugin | v4.0 | 3/3 | Complete   | 2026-03-31 |
| 29. Plugin UI + Learning Extraction | v4.0 | 2/3 | In Progress|  |
| 30. Advanced — TeamTool + Auto Memory | v4.0 | 0/TBD | Not started | - |
| 31. Advanced — Migration + Docker | v4.0 | 0/TBD | Not started | - |

| Milestone | Phases | Plans | Status | Shipped |
| ----------- | -------- | ------- | -------- | --------- |
| v1.0 Free LLM Providers | 6 | 12 | Complete | 2026-03-02 |
| v1.1 | - | - | Complete | - |
| v1.2 CC Automation | 6 | 8 | Complete | 2026-03-07 |
| v1.4 Task Memories | 4 | 8 | Complete | 2026-03-22 |
| v1.5 Memory Bridge | 4 | 8 | Complete | 2026-03-22 |
| v1.6 UX & Workflow | 4 | 8 | Complete | 2026-03-22 |
| rewards-v1.0 Rewards | 4 | 7 | Complete | 2026-03-25 |
| v2.1 Workspaces | 3 | 6 | Complete | 2026-03-24 |
| v2.0 CC UI | 6 | - | In Progress | - |
| v3.0 GSD Integration | 4 | 8+ | In Progress | - |
| v4.0 Paperclip Integration | 8 | TBD | In Progress | - |
