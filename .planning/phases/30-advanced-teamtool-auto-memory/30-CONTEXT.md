# Phase 30: Advanced — TeamTool + Auto Memory - Context

**Gathered:** 2026-03-31 (auto mode)
**Status:** Ready for planning

<domain>
## Phase Boundary

Agent42 can fan out parallel sub-agents and run sequential wave workflows within a single Paperclip task, and memory injection becomes automatic on heartbeat rather than requiring an explicit tool call. All sub-agent outputs appear in the run transcript and wave outputs chain sequentially.

Requirements: ADV-01, ADV-02, ADV-03.

</domain>

<decisions>
## Implementation Decisions

### Strategy Orchestration Layer
- **D-01:** Plugin-side orchestration via Paperclip SDK `ctx.agents.invoke(agentId, companyId, opts)` — sub-agent invocations go through Paperclip's agent lifecycle (audit trail, budget tracking, run records), not Agent42's internal TeamTool
- **D-02:** New `agents.invoke` and `events.subscribe` capabilities added to manifest.json
- **D-03:** Existing Agent42 TeamTool patterns (sequential, parallel, fan_out_fan_in) inform the design but are not reused directly — Paperclip agents ≠ Agent42 subprocess agents

### Fan-Out Strategy (ADV-02)
- **D-04:** New plugin tool `team_execute` registered via `ctx.tools.register()` — agents call with `{strategy: "fan-out", subAgentIds: [...], task: "...", context: {...}}`
- **D-05:** Plugin spawns sub-agents in parallel via `Promise.all(subAgentIds.map(id => ctx.agents.invoke(id, companyId, opts)))` — all invocations are Paperclip-visible runs
- **D-06:** Aggregated results collected into `subResults[]` array — each entry contains `{agentId, output, status, costUsd}`
- **D-07:** Fan-out result written to originating run's transcript context via the sidecar callback

### Wave Strategy (ADV-03)
- **D-08:** Wave execution uses sequential `ctx.agents.invoke()` calls — each wave's output becomes input context for the next wave
- **D-09:** Plugin persists wave state via `ctx.state.set({ scopeKind: "run", stateKey: "wave-progress" })` for crash recovery — interrupted waves resume from last completed wave
- **D-10:** Wave outputs accumulate in `waveOutputs[]` array — final callback includes full chain for traceability
- **D-11:** Wave execution stays within the same Paperclip ticket lifecycle — no new tickets created for individual waves

### Auto Memory Injection (ADV-01)
- **D-12:** Sidecar-side injection in `SidecarOrchestrator.execute_async()` — recalled memories prepended to `context` dict as `memoryContext` field before agent execution
- **D-13:** Plugin subscribes to `agent.run.started` event (confirmed in SDK) for observability logging — NOT for injection (no documented prompt modification API from event handlers)
- **D-14:** New `auto_memory` boolean in `AdapterConfig` (default `true`) — operators can disable auto-injection per-agent
- **D-15:** Recalled memories formatted as structured context block: `{memories: [{text, score, source}], injectedAt: ISO8601, count: N}`
- **D-16:** Observable in run transcript: the callback `result` dict includes `autoMemory: {count, injectedAt}` metadata

### Strategy Detection
- **D-17:** `strategy` field read from `AdapterExecutionContext.context` dict — values: `"fan-out"`, `"wave"`, `"standard"` (default)
- **D-18:** Adapter passes strategy through from Paperclip task metadata; sidecar detects and routes to appropriate handler
- **D-19:** Unknown strategy values fall back to `"standard"` with a warning log (matches existing unknown `wakeReason` pattern)

### Sidecar Extensions
- **D-20:** New `POST /sidecar/execute/team` endpoint for strategy-aware execution — or extend existing `/sidecar/execute` to detect strategy in context (Claude's discretion on routing approach)
- **D-21:** New Pydantic models: `TeamExecuteRequest`, `SubAgentResult`, `WaveOutput` in `core/sidecar_models.py`
- **D-22:** Extend `CallbackPayload.result` dict with optional `subResults[]` and `waveOutputs[]` fields (additive, non-breaking)

### Claude's Discretion
- Whether to add a separate `/sidecar/execute/team` endpoint or detect strategy in existing `/sidecar/execute`
- Exact format of the `memoryContext` field in the context dict
- Whether `team_execute` is one tool or two (`team_fan_out` + `team_wave`)
- Timeout and retry behavior for sub-agent invocations
- Whether wave state uses `run` scope or `instance` scope in plugin state
- Plugin test file organization for new tools and event handlers
- Exact `ctx.agents.invoke()` options shape (goal, context, timeout)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase requirements
- `.planning/REQUIREMENTS.md` — ADV-01, ADV-02, ADV-03 define all Phase 30 requirements
- `.planning/ROADMAP.md` — Phase 30 success criteria (3 acceptance tests)

### Architecture research
- `.planning/research/FEATURES.md` — Plugin SDK interface contracts, event system, agent invocation APIs
- `.planning/research/ARCHITECTURE.md` — System diagram, component responsibilities

### Paperclip Plugin SDK (installed)
- `plugins/agent42-paperclip/node_modules/@paperclipai/plugin-sdk/README.md` — Full SDK reference: events (§16), agent invocation (§22), capabilities (§15), agent sessions (§23)
- `plugins/agent42-paperclip/node_modules/@paperclipai/shared/dist/constants.d.ts` — `PLUGIN_CAPABILITIES` including `agents.invoke`, `events.subscribe`

### Prior phase context (dependencies)
- `.planning/phases/28-paperclip-plugin/28-CONTEXT.md` — Plugin package structure, Agent42Client, tool registration pattern, manifest format
- `.planning/phases/29-plugin-ui-learning-extraction/29-CONTEXT.md` — Event subscription pattern, job registration, data handlers, UI slot architecture

### Existing codebase (key files to read)
- `core/sidecar_orchestrator.py` — `SidecarOrchestrator.execute_async()` — where auto-memory injection is added (memory recall already at lines 98-127)
- `core/memory_bridge.py` — `MemoryBridge.recall()` — memory retrieval with agent/company scoping
- `core/sidecar_models.py` — Pydantic models for sidecar API (extend with team strategy models)
- `dashboard/sidecar.py` — Sidecar FastAPI routes (extend for strategy-aware execution)
- `plugins/agent42-paperclip/src/worker.ts` — Plugin lifecycle, event handlers, job registration
- `plugins/agent42-paperclip/src/tools.ts` — Existing tool registrations (add team_execute tool)
- `plugins/agent42-paperclip/src/client.ts` — Agent42Client HTTP methods (extend for team endpoints)
- `plugins/agent42-paperclip/src/types.ts` — TypeScript types (add team strategy types)
- `plugins/agent42-paperclip/manifest.json` — Current manifest (add capabilities, new tool)
- `tools/team_tool.py` — Existing TeamTool with sequential/parallel/fan_out_fan_in patterns (reference for strategy design, not reused directly)
- `adapters/agent42-paperclip/src/adapter.ts` — Adapter execute() flow (strategy passthrough)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `SidecarOrchestrator.execute_async()` — already recalls memories with 200ms timeout; enhance to inject into context
- `MemoryBridge.recall()` — scope-filtered semantic search, returns `[{text, score, source, metadata}]`
- `TeamTool._run_parallel()` and `_run_fan_out_fan_in()` — orchestration patterns to reference for strategy design
- `Agent42Client` in plugin — HTTP client wrapping sidecar endpoints; extend with team strategy methods
- `registerTools(ctx, client)` in tools.ts — existing tool registration pattern to follow
- `ctx.agents.invoke(agentId, companyId, opts)` — Paperclip SDK one-shot agent invocation

### Established Patterns
- **camelCase Pydantic aliases:** All sidecar models use `alias="camelCase"` — new models follow same pattern
- **Bearer JWT auth:** All endpoints except /health require auth — new endpoints follow same pattern
- **Plugin tool handler shape:** `async (params, runCtx) => { return { content, data } }` with auto-injected agentId/companyId
- **Event subscription:** `ctx.events.on(name, handler)` with `events.subscribe` capability
- **Unknown value fallback:** Unknown `wakeReason` logs warning but doesn't throw (sidecar_orchestrator.py line 59)
- **Fire-and-forget for non-critical ops:** `asyncio.create_task()` pattern for learning extraction
- **Plugin state for watermarks:** `ctx.state.set/get` with scopeKind for crash recovery (extract-learnings job pattern)

### Integration Points
- `dashboard/sidecar.py:create_sidecar_app()` — Add strategy-aware route or extend existing `/sidecar/execute`
- `core/sidecar_orchestrator.py:execute_async()` — Inject recalled memories into context dict
- `core/sidecar_models.py` — Add team strategy Pydantic models
- `plugins/agent42-paperclip/manifest.json` — Add `agents.invoke`, `events.subscribe` capabilities + new tool
- `plugins/agent42-paperclip/src/worker.ts:setup()` — Register `agent.run.started` event handler
- `plugins/agent42-paperclip/src/tools.ts` — Register `team_execute` tool
- `plugins/agent42-paperclip/src/client.ts` — Add team execution client methods

</code_context>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches

</specifics>

<deferred>
## Deferred Ideas

None — analysis stayed within phase scope

</deferred>

---

*Phase: 30-advanced-teamtool-auto-memory*
*Context gathered: 2026-03-31*
