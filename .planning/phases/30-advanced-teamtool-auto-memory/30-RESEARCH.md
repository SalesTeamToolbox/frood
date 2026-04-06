# Phase 30: Advanced — TeamTool + Auto Memory - Research

**Researched:** 2026-03-31
**Domain:** Paperclip Plugin SDK agents.invoke, plugin event system, sidecar orchestrator extensions
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Strategy Orchestration Layer**
- D-01: Plugin-side orchestration via Paperclip SDK `ctx.agents.invoke(agentId, companyId, opts)` — sub-agent invocations go through Paperclip's agent lifecycle (audit trail, budget tracking, run records), not Agent42's internal TeamTool
- D-02: New `agents.invoke` and `events.subscribe` capabilities added to manifest.json
- D-03: Existing Agent42 TeamTool patterns (sequential, parallel, fan_out_fan_in) inform the design but are not reused directly — Paperclip agents ≠ Agent42 subprocess agents

**Fan-Out Strategy (ADV-02)**
- D-04: New plugin tool `team_execute` registered via `ctx.tools.register()` — agents call with `{strategy: "fan-out", subAgentIds: [...], task: "...", context: {...}}`
- D-05: Plugin spawns sub-agents in parallel via `Promise.all(subAgentIds.map(id => ctx.agents.invoke(id, companyId, opts)))` — all invocations are Paperclip-visible runs
- D-06: Aggregated results collected into `subResults[]` array — each entry contains `{agentId, output, status, costUsd}`
- D-07: Fan-out result written to originating run's transcript context via the sidecar callback

**Wave Strategy (ADV-03)**
- D-08: Wave execution uses sequential `ctx.agents.invoke()` calls — each wave's output becomes input context for the next wave
- D-09: Plugin persists wave state via `ctx.state.set({ scopeKind: "run", stateKey: "wave-progress" })` for crash recovery — interrupted waves resume from last completed wave
- D-10: Wave outputs accumulate in `waveOutputs[]` array — final callback includes full chain for traceability
- D-11: Wave execution stays within the same Paperclip ticket lifecycle — no new tickets created for individual waves

**Auto Memory Injection (ADV-01)**
- D-12: Sidecar-side injection in `SidecarOrchestrator.execute_async()` — recalled memories prepended to `context` dict as `memoryContext` field before agent execution
- D-13: Plugin subscribes to `agent.run.started` event (confirmed in SDK) for observability logging — NOT for injection (no documented prompt modification API from event handlers)
- D-14: New `auto_memory` boolean in `AdapterConfig` (default `true`) — operators can disable auto-injection per-agent
- D-15: Recalled memories formatted as structured context block: `{memories: [{text, score, source}], injectedAt: ISO8601, count: N}`
- D-16: Observable in run transcript: the callback `result` dict includes `autoMemory: {count, injectedAt}` metadata

**Strategy Detection**
- D-17: `strategy` field read from `AdapterExecutionContext.context` dict — values: `"fan-out"`, `"wave"`, `"standard"` (default)
- D-18: Adapter passes strategy through from Paperclip task metadata; sidecar detects and routes to appropriate handler
- D-19: Unknown strategy values fall back to `"standard"` with a warning log (matches existing unknown `wakeReason` pattern)

**Sidecar Extensions**
- D-20: New `POST /sidecar/execute/team` endpoint for strategy-aware execution — or extend existing `/sidecar/execute` to detect strategy in context (Claude's discretion on routing approach)
- D-21: New Pydantic models: `TeamExecuteRequest`, `SubAgentResult`, `WaveOutput` in `core/sidecar_models.py`
- D-22: Extend `CallbackPayload.result` dict with optional `subResults[]` and `waveOutputs[]` fields (additive, non-breaking)

### Claude's Discretion
- Whether to add a separate `/sidecar/execute/team` endpoint or detect strategy in existing `/sidecar/execute`
- Exact format of the `memoryContext` field in the context dict
- Whether `team_execute` is one tool or two (`team_fan_out` + `team_wave`)
- Timeout and retry behavior for sub-agent invocations
- Whether wave state uses `run` scope or `instance` scope in plugin state
- Plugin test file organization for new tools and event handlers
- Exact `ctx.agents.invoke()` options shape (goal, context, timeout)

### Deferred Ideas (OUT OF SCOPE)
None — analysis stayed within phase scope
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| ADV-01 | Automatic memory injection on heartbeat — plugin subscribes to heartbeat event and prepends relevant context to agent prompt | D-12 through D-16: sidecar-side injection confirmed as correct pattern; SDK `agent.run.started` event verified to exist; `auto_memory` flag in AdapterConfig; memoryContext in context dict |
| ADV-02 | TeamTool fan-out strategy — tasks tagged strategy:fan-out spawn parallel sub-agents and aggregate results | D-04 through D-07: `team_execute` tool via `ctx.tools.register`; `ctx.agents.invoke` confirmed in SDK types.d.ts with exact signature; `agents.invoke` capability confirmed in PLUGIN_CAPABILITIES; Promise.all parallelism pattern |
| ADV-03 | TeamTool wave strategy — sequential wave execution mapped to single Paperclip ticket lifecycle | D-08 through D-11: sequential invoke calls; `ctx.state` with `run` scopeKind for crash recovery; wave state schema confirmed; no new ticket creation |
</phase_requirements>

---

## Summary

Phase 30 adds two advanced orchestration strategies (fan-out and wave) and automatic memory injection to the existing Agent42-Paperclip integration. All three capabilities build directly on SDK surfaces confirmed as available in the installed `@paperclipai/plugin-sdk` (version in `node_modules`).

The most critical research finding is that `ctx.agents.invoke(agentId, companyId, opts)` exists in the SDK with a confirmed TypeScript signature: it takes `{ prompt: string, reason?: string }` as opts and returns `Promise<{ runId: string }>`. This is a **fire-and-forget invocation** — it returns a runId but does NOT stream or await the sub-agent's completion. The fan-out aggregation pattern therefore cannot await actual sub-agent results inline; instead sub-agent outputs must be communicated back through another channel (sidecar callback or a separate polling endpoint). This is the most significant architectural constraint for the planner to address.

The auto-memory injection is the simplest of the three features: the orchestrator already recalls memories in `execute_async()` at lines 98-127 of `core/sidecar_orchestrator.py`. The only change is to inject those recalled memories into `ctx.context['memoryContext']` before the (currently stubbed) agent execution step, and surface that injection in the callback result dict. The existing 200ms timeout on memory recall already satisfies the heartbeat latency constraint.

**Primary recommendation:** Implement auto-memory injection first (lowest risk, purely sidecar-side), then fan-out (one plugin tool + `Promise.all` of non-awaited invocations with results communicated through existing sidecar callback), then wave (sequential invocations with `ctx.state` crash recovery). All three are additive — no existing behavior is modified.

---

## Standard Stack

### Core (all already installed)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `@paperclipai/plugin-sdk` | installed in node_modules | Plugin worker lifecycle, `ctx.agents.invoke`, `ctx.events.on`, `ctx.state` | Official SDK — all agent invocation and event APIs live here |
| `@paperclipai/shared` | installed in node_modules | `PLUGIN_CAPABILITIES` constants, type definitions | Source of truth for capability strings and event type names |
| `pydantic` v2 | Python dep (existing) | New sidecar models (`TeamExecuteRequest`, `SubAgentResult`, `WaveOutput`) | Existing pattern in `core/sidecar_models.py` |
| `fastapi` | Python dep (existing) | New or extended sidecar route | Existing pattern in `dashboard/sidecar.py` |
| `asyncio` | Python stdlib | Async orchestration in `execute_async()` | Existing pattern throughout sidecar |
| `vitest` | dev dep (existing) | Plugin TypeScript unit tests | Already configured in `vitest.config.ts` |
| `pytest` | Python dev dep (existing) | Sidecar Python tests | Already configured in `tests/` |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `@paperclipai/plugin-sdk/testing` | installed | `createTestHarness` for plugin unit tests | Testing new `team_execute` tool and event handler |
| `httpx` | Python dep (existing) | HTTP client in sidecar for sub-agent callback polling (if needed) | Already in `SidecarOrchestrator._get_http_client()` |

**No new package installations required for this phase.**

---

## Architecture Patterns

### Confirmed SDK Interface: ctx.agents.invoke

From `dist/types.d.ts` in the installed SDK (HIGH confidence — read directly from node_modules):

```typescript
// Source: plugins/agent42-paperclip/node_modules/@paperclipai/plugin-sdk/dist/types.d.ts
interface PluginAgentsClient {
  invoke(agentId: string, companyId: string, opts: {
    prompt: string;
    reason?: string;
  }): Promise<{
    runId: string;
  }>;
}
```

**Critical constraint:** `invoke` returns `{ runId }` only — not the sub-agent's output. Sub-agents run asynchronously in Paperclip's own lifecycle. There is NO await-for-output pattern in the SDK.

**Implication for fan-out:** The `team_execute` tool cannot return aggregated sub-agent outputs synchronously. The planner must decide on a result-collection mechanism. Options (in order of decreasing complexity):
1. Return runIds to the calling agent immediately and let the agent poll or use a follow-up tool call
2. Use `ctx.agents.sessions` (two-way chat) via `agent.sessions.send` with `onEvent` callback for streaming — higher complexity, requires `agent.sessions.*` capabilities
3. Return only the invocation manifest (which agents were spawned) and let the sidecar callback include the fan-out metadata

The locked decision D-06 specifies `subResults[]` with `{agentId, output, status, costUsd}`. Since `invoke` is fire-and-forget, "output" at invocation time will be unavailable. The practical implementation is to return the invocation IDs and note this as a future enhancement, or use the agent sessions pattern for synchronous result collection.

### Confirmed SDK Interface: ctx.events.on for agent.run.started

From `PLUGIN_EVENT_TYPES` in `@paperclipai/shared/dist/constants.d.ts` (HIGH confidence):

```typescript
// Source: constants.d.ts PLUGIN_EVENT_TYPES array
"agent.run.started"  // confirmed in the readonly tuple
```

From `PluginEventsClient` in `types.d.ts`:
```typescript
on(
  name: PluginEventType | `plugin.${string}`,
  fn: (event: PluginEvent) => Promise<void>
): () => void;
```

**Implication for ADV-01:** The `agent.run.started` event fires when a run begins, but there is no prompt-modification API on `PluginEvent`. D-13 correctly identifies this: the event is for **observability logging only**, not injection. Injection happens sidecar-side (D-12).

### Confirmed SDK Interface: ctx.state for wave crash recovery

From `types.d.ts` `PluginStateScopeKind` and `PLUGIN_STATE_SCOPE_KINDS` (HIGH confidence):

```typescript
// Confirmed scope kinds include "run"
"run"  // per-run checkpoints — exactly right for wave progress state
```

```typescript
// Exact usage pattern for wave-progress state:
await ctx.state.set(
  { scopeKind: "run", scopeId: runId, stateKey: "wave-progress" },
  { completedWaves: number, waveOutputs: WaveOutput[] }
);
```

### Pattern 1: team_execute Plugin Tool

**What:** Single `ctx.tools.register("team_execute", ...)` handler that reads `strategy` from params and dispatches to fan-out or wave execution path.

**When to use:** Agents call this tool with `{strategy, subAgentIds, task, context}` or `{strategy: "wave", waves: [...], task}`.

```typescript
// Source: tools.ts pattern (existing tool registration shape)
ctx.tools.register(
  "team_execute",
  {
    displayName: "Team Execute",
    description: "Orchestrate parallel or sequential sub-agent execution",
    parametersSchema: {
      type: "object",
      properties: {
        strategy: { type: "string", enum: ["fan-out", "wave"] },
        subAgentIds: { type: "array", items: { type: "string" } },
        waves: { type: "array", items: { type: "object" } },
        task: { type: "string" },
        context: { type: "object", additionalProperties: true },
      },
      required: ["strategy", "task"],
    },
  },
  async (params, runCtx) => {
    // dispatch based on params.strategy
  }
);
```

### Pattern 2: Auto-Memory Injection in execute_async

**What:** After memory recall (which already exists), inject recalled memories into `ctx.context` before the agent execution step.

**When to use:** When `ctx.adapter_config.auto_memory` is `True` (new field, default `True`) and recalled_memories is non-empty.

```python
# Source: core/sidecar_orchestrator.py (extension of existing execute_async)
# After existing memory recall at lines 98-127:
if recalled_memories and ctx.adapter_config.auto_memory:
    ctx.context["memoryContext"] = {
        "memories": [
            {"text": m["text"], "score": m["score"], "source": m.get("source", "")}
            for m in recalled_memories
        ],
        "injectedAt": datetime.utcnow().isoformat() + "Z",
        "count": len(recalled_memories),
    }
```

And in the result dict at the existing Step 2 stub:
```python
result = {
    # ... existing fields ...
    "autoMemory": {
        "count": len(recalled_memories),
        "injectedAt": ctx.context.get("memoryContext", {}).get("injectedAt"),
    } if recalled_memories and ctx.adapter_config.auto_memory else None,
}
```

### Pattern 3: Wave State in Plugin State (run scope)

**What:** Plugin stores wave execution progress in `ctx.state` with `run` scope so interrupted waves can resume.

```typescript
// Source: worker.ts ctx.state pattern (established in extract-learnings job)
// Write after each completed wave:
await ctx.state.set(
  { scopeKind: "run", scopeId: runCtx.runId, stateKey: "wave-progress" },
  { completedWaves: completedIndex, waveOutputs }
);

// Read at start for crash recovery:
const savedProgress = await ctx.state.get(
  { scopeKind: "run", scopeId: runCtx.runId, stateKey: "wave-progress" }
) as { completedWaves: number; waveOutputs: WaveOutput[] } | null;
```

### Required manifest.json Changes

Current manifest has these capabilities:
```json
["http.outbound", "agent.tools.register", "ui.detailTab.register",
 "ui.dashboardWidget.register", "jobs.schedule", "plugin.state.write"]
```

Phase 30 requires adding:
```json
"agents.invoke",
"events.subscribe",
"plugin.state.read"
```

`plugin.state.read` is needed for wave crash recovery (`ctx.state.get`). The current manifest only has `plugin.state.write`.

### Anti-Patterns to Avoid

- **Awaiting sub-agent output from ctx.agents.invoke:** The SDK only returns `{ runId }`. Attempting to poll the run result from inside the plugin tool handler will timeout. Use sessions API or accept fire-and-forget semantics.
- **Prompt injection from event handlers:** `agent.run.started` event has no prompt-modification surface. All injection must happen sidecar-side before execution, not plugin-side in the event handler.
- **Using instance scope for wave state:** Wave state must use `run` scope (not `instance`) so multiple concurrent wave workflows don't collide.
- **Blocking the sidecar execute route for team strategies:** The sidecar already returns 202 Accepted immediately. Team execution must remain fully async via background task.
- **New Python models without camelCase aliases:** All existing sidecar models use `alias="camelCase"` pattern. New `TeamExecuteRequest`, `SubAgentResult`, `WaveOutput` must follow the same convention.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Sub-agent invocation | Custom HTTP call to Paperclip API | `ctx.agents.invoke()` | SDK method is capability-gated, audited, and handles auth — direct API calls would bypass Paperclip's run lifecycle |
| Wave state persistence | In-memory dict or custom SQLite table | `ctx.state.set/get` with `run` scope | SDK state is already crash-safe, scoped, and isolated per plugin |
| Event subscription | Polling or custom webhook | `ctx.events.on("agent.run.started", handler)` | SDK events are server-side filtered and delivered via the existing JSON-RPC channel |
| Plugin testing harness | Custom mock objects | `createTestHarness` from `@paperclipai/plugin-sdk/testing` | Already established pattern in `worker.test.ts` |
| Memory injection timing | Custom async queue | Extend existing `execute_async()` recall flow | Memory recall already runs with 200ms timeout at lines 98-127 — inject immediately after |

---

## Common Pitfalls

### Pitfall 1: ctx.agents.invoke is fire-and-forget — no output return

**What goes wrong:** Developer calls `ctx.agents.invoke()` and awaits the `{ runId }` response, expecting sub-agent output. The response is only a runId. There is no synchronous result retrieval path.

**Why it happens:** The SDK type signature (`Promise<{ runId: string }>`) looks similar to an HTTP response that could include output. But Paperclip's agent execution is always async and output flows through the agent's own run lifecycle.

**How to avoid:** Either (a) return invocation metadata to the calling agent and use a separate polling/callback mechanism, or (b) use `ctx.agents.sessions.sendMessage` with `onEvent` for streaming results (requires `agent.sessions.*` capabilities — not currently in manifest). The locked decisions (D-06) specify `subResults[]` with output fields — the planner needs to resolve this constraint given the fire-and-forget invocation model.

**Warning signs:** Tool handler returning `subResults` with non-empty `output` fields immediately after `Promise.all(invocations)`.

### Pitfall 2: Missing plugin.state.read capability for wave crash recovery

**What goes wrong:** `ctx.state.get()` throws `CAPABILITY_DENIED` at runtime because only `plugin.state.write` is declared in the current manifest.

**Why it happens:** The current manifest (v1.1.0) has `"plugin.state.write"` but not `"plugin.state.read"`. The existing extract-learnings job only writes watermarks (never reads), so this gap was never caught. Wave crash recovery requires `ctx.state.get()` which needs `plugin.state.read`.

**How to avoid:** Add `"plugin.state.read"` to `manifest.capabilities` array alongside `"agents.invoke"` and `"events.subscribe"`.

**Warning signs:** Wave progress not restoring after simulated crash in test harness.

### Pitfall 3: ctx.agents.invoke requires agents.invoke capability in manifest

**What goes wrong:** Calling `ctx.agents.invoke()` without `"agents.invoke"` in `manifest.capabilities` throws `CAPABILITY_DENIED` at runtime (SDK enforces this at the RPC boundary).

**Why it happens:** The current manifest (v1.1.0) does not include `"agents.invoke"` — it was not needed in Phases 28-29.

**How to avoid:** Add `"agents.invoke"` to the capabilities array before writing any `team_execute` handler code.

### Pitfall 4: Auto-memory injection must come before the execution stub, not after

**What goes wrong:** Memory context is injected into `ctx.context` AFTER the (currently stubbed) agent execution step, so the agent never sees it.

**Why it happens:** The `execute_async()` flow is: recall → routing → execute → callback. Injection must happen in the gap between recall and execute.

**How to avoid:** The injection code at the "memoryContext" assignment must be placed between the routing resolution block (line ~155) and the execution stub (line ~172) in `core/sidecar_orchestrator.py`.

### Pitfall 5: ctx.events.on registration must happen inside setup(), not deferred

**What goes wrong:** If the event handler registration is placed in a lazy callback or a later async function, the host never registers the subscription and no events are received.

**Why it happens:** The `PLUGIN_SPEC.md §16` contract requires all `ctx.events.on()` registrations to happen synchronously during `setup()`. The host scans the registered handlers at startup to build its subscription set.

**How to avoid:** Register `ctx.events.on("agent.run.started", handler)` directly inside `setup()` in `worker.ts`, before `setup()` resolves.

### Pitfall 6: Wave state scope collision when runId is not passed to plugin tool handler

**What goes wrong:** Multiple concurrent wave executions write to the same `ctx.state` key because `runCtx.runId` is not used as the `scopeId`.

**Why it happens:** Using `scopeKind: "instance"` instead of `scopeKind: "run"` with `scopeId: runCtx.runId` causes all waves across all agents to share state.

**How to avoid:** Always use `{ scopeKind: "run", scopeId: runCtx.runId }` for wave progress state. The `ToolRunContext` type provides `runId: string` in the tool handler's second argument.

---

## Code Examples

### Confirmed: ctx.agents.invoke exact signature

```typescript
// Source: dist/types.d.ts PluginAgentsClient interface
const result = await ctx.agents.invoke(agentId, companyId, {
  prompt: "Task description here",
  reason: "fan-out sub-task"
});
// result: { runId: string }
// NOTE: this is fire-and-forget — no output available synchronously
```

### Fan-out parallel invocation

```typescript
// Source: D-05 decision + types.d.ts PluginAgentsClient
const subAgentIds = params.subAgentIds as string[];
const invocations = await Promise.all(
  subAgentIds.map((id) =>
    ctx.agents.invoke(id, runCtx.companyId, {
      prompt: params.task as string,
      reason: "fan-out",
    })
  )
);
// invocations: Array<{ runId: string }>
```

### Wave sequential invocation with crash recovery

```typescript
// Source: D-08, D-09 decisions + ctx.state pattern from worker.ts
const savedProgress = await ctx.state.get({
  scopeKind: "run",
  scopeId: runCtx.runId,
  stateKey: "wave-progress",
}) as { completedWaves: number; waveOutputs: WaveOutput[] } | null;

const startWave = savedProgress?.completedWaves ?? 0;
const waveOutputs: WaveOutput[] = savedProgress?.waveOutputs ?? [];

for (let i = startWave; i < waves.length; i++) {
  const wavePrompt = i === 0
    ? waves[i].task
    : `${waves[i].task}\n\nContext from previous wave:\n${waveOutputs[i - 1].output}`;

  const result = await ctx.agents.invoke(waves[i].agentId, runCtx.companyId, {
    prompt: wavePrompt,
    reason: `wave-${i + 1}`,
  });

  waveOutputs.push({ wave: i + 1, agentId: waves[i].agentId, runId: result.runId, status: "invoked" });

  await ctx.state.set(
    { scopeKind: "run", scopeId: runCtx.runId, stateKey: "wave-progress" },
    { completedWaves: i + 1, waveOutputs }
  );
}
```

### Auto-memory injection in sidecar orchestrator

```python
# Source: core/sidecar_orchestrator.py execute_async() extension
# Place AFTER routing block (~line 155), BEFORE execution stub (~line 172)
if recalled_memories and getattr(ctx.adapter_config, "auto_memory", True):
    from datetime import datetime
    ctx.context["memoryContext"] = {
        "memories": [
            {"text": m["text"], "score": m["score"], "source": m.get("source", "")}
            for m in recalled_memories
        ],
        "injectedAt": datetime.utcnow().isoformat() + "Z",
        "count": len(recalled_memories),
    }
    logger.info(
        "Injected %d memories into context for run %s",
        len(recalled_memories),
        run_id,
    )
```

### New AdapterConfig field for auto_memory

```python
# Source: core/sidecar_models.py AdapterConfig (extend existing)
class AdapterConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    session_key: str = Field(default="", alias="sessionKey")
    memory_scope: str = Field(default="agent", alias="memoryScope")
    preferred_provider: str = Field(default="", alias="preferredProvider")
    agent_id: str = Field(default="", alias="agentId")
    auto_memory: bool = Field(default=True, alias="autoMemory")  # new field (D-14)
```

### agent.run.started event handler registration

```typescript
// Source: worker.ts setup() pattern + events.on from types.d.ts
ctx.events.on("agent.run.started", async (event) => {
  ctx.logger.info("Agent run started", {
    agentId: event.entityId,
    companyId: event.companyId,
    runId: event.payload?.runId,
  });
  // NOTE: cannot modify prompt here — observability only (D-13)
});
```

### Manifest capability additions

```json
// Source: manifest.json (add to existing capabilities array)
"capabilities": [
  "http.outbound",
  "agent.tools.register",
  "ui.detailTab.register",
  "ui.dashboardWidget.register",
  "jobs.schedule",
  "plugin.state.write",
  "plugin.state.read",
  "agents.invoke",
  "events.subscribe"
]
```

### New sidecar Pydantic models

```python
# Source: core/sidecar_models.py (new models per D-21)
class SubAgentResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    agent_id: str = Field(..., alias="agentId")
    run_id: str = Field(default="", alias="runId")
    status: str = "invoked"
    output: str = ""
    cost_usd: float = Field(default=0.0, alias="costUsd")


class WaveOutput(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    wave: int = 1
    agent_id: str = Field(default="", alias="agentId")
    run_id: str = Field(default="", alias="runId")
    status: str = "invoked"
    output: str = ""


class TeamExecuteRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    run_id: str = Field(..., alias="runId")
    agent_id: str = Field(..., alias="agentId")
    company_id: str = Field(default="", alias="companyId")
    strategy: str = "standard"
    sub_agent_ids: list[str] = Field(default_factory=list, alias="subAgentIds")
    waves: list[dict] = Field(default_factory=list)
    task: str = ""
    context: dict = Field(default_factory=dict)
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| memory_recall tool (explicit agent call) | Auto-injection on heartbeat (sidecar-side) | Phase 30 | Agents no longer need to call the tool — context is always available |
| No sub-agent invocation from plugin | ctx.agents.invoke() in plugin worker | Phase 30 | Plugins can orchestrate agents directly through Paperclip's lifecycle |
| Wave-state lost on crash | ctx.state.set/get with run scope for recovery | Phase 30 | Fan-out and wave strategies are crash-safe |

---

## Open Questions

1. **Fan-out result aggregation: fire-and-forget vs sessions**
   - What we know: `ctx.agents.invoke()` returns `{ runId }` only. D-06 specifies `subResults[]` with `{agentId, output, status, costUsd}`.
   - What's unclear: How does `output` get populated synchronously if invoke is fire-and-forget? The two options are (a) return only invocation metadata and mark output as "" with status "invoked", or (b) use `ctx.agents.sessions.sendMessage` with `onEvent` for streaming results (requires 3 more capabilities: `agent.sessions.create`, `agent.sessions.list`, `agent.sessions.send`).
   - Recommendation: Option (a) — return `subResults` with `status: "invoked"` and empty `output`. Add a comment to types that output is populated via callback when available. This matches D-06 structure without requiring additional SDK capabilities. The planner should make this explicit in the plan.

2. **Single `/sidecar/execute` vs separate `/sidecar/execute/team` endpoint (D-20)**
   - What we know: Current `/sidecar/execute` accepts `AdapterExecutionContext` which has a `context` dict. Strategy can be added to the context dict.
   - What's unclear: D-20 says "Claude's discretion on routing approach." A single endpoint keeps the surface small and is non-breaking; a separate endpoint has a cleaner contract.
   - Recommendation: Extend the existing `/sidecar/execute` endpoint — read `strategy` from `ctx.context.get("strategy", "standard")` and route to the appropriate handler inside `execute_async()`. This is additive and requires no changes to Paperclip's adapter configuration.

---

## Environment Availability

Step 2.6: The phase makes no use of new external tools or services beyond the already-installed plugin SDK and existing sidecar Python dependencies. All required components are confirmed present:

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `@paperclipai/plugin-sdk` | Plugin team_execute tool, events.on | Yes | installed in node_modules | — |
| `@paperclipai/shared` | PLUGIN_CAPABILITIES type validation | Yes | installed in node_modules | — |
| `pydantic` v2 | New sidecar models | Yes | existing dep | — |
| `fastapi` | Sidecar route (if extended) | Yes | existing dep | — |
| `vitest` | Plugin TypeScript tests | Yes | existing `vitest.config.ts` | — |
| `pytest` | Python sidecar tests | Yes | existing `tests/` infrastructure | — |

**Missing dependencies with no fallback:** None.

---

## Validation Architecture

nyquist_validation is enabled in `.planning/config.json` (`"nyquist_validation": true`).

### Test Framework

| Property | Value |
|----------|-------|
| Python Framework | pytest (existing) |
| TypeScript Framework | vitest (existing) |
| Python config | `tests/conftest.py` + `tests/test_sidecar.py` |
| TypeScript config | `plugins/agent42-paperclip/vitest.config.ts` |
| Quick run (Python) | `python -m pytest tests/test_sidecar.py -x -q` |
| Quick run (TypeScript) | `cd plugins/agent42-paperclip && npx vitest run` |
| Full suite | `python -m pytest tests/ -x -q && cd plugins/agent42-paperclip && npx vitest run` |

### Phase Requirements to Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| ADV-01 | Recalled memories injected as `memoryContext` in `ctx.context` before execution | unit | `pytest tests/test_sidecar.py::TestAutoMemoryInjection -x -q` | Wave 0 |
| ADV-01 | `autoMemory` metadata appears in callback `result` dict | unit | `pytest tests/test_sidecar.py::TestAutoMemoryInjection::test_auto_memory_in_callback -x -q` | Wave 0 |
| ADV-01 | `auto_memory: false` in adapterConfig disables injection | unit | `pytest tests/test_sidecar.py::TestAutoMemoryInjection::test_auto_memory_disabled -x -q` | Wave 0 |
| ADV-02 | `team_execute` tool registered with correct schema | unit | `cd plugins/agent42-paperclip && npx vitest run tests/team.test.ts` | Wave 0 |
| ADV-02 | fan-out spawns Promise.all of invoke calls with correct subAgentIds | unit | `cd plugins/agent42-paperclip && npx vitest run tests/team.test.ts` | Wave 0 |
| ADV-02 | fan-out result includes `subResults[]` with runIds | unit | `cd plugins/agent42-paperclip && npx vitest run tests/team.test.ts` | Wave 0 |
| ADV-03 | wave strategy invokes agents sequentially (not in parallel) | unit | `cd plugins/agent42-paperclip && npx vitest run tests/team.test.ts` | Wave 0 |
| ADV-03 | wave output from wave N appears as context in wave N+1 prompt | unit | `cd plugins/agent42-paperclip && npx vitest run tests/team.test.ts` | Wave 0 |
| ADV-03 | wave progress saved to ctx.state after each wave | unit | `cd plugins/agent42-paperclip && npx vitest run tests/team.test.ts` | Wave 0 |
| ADV-03 | wave resumes from saved state after simulated crash | unit | `cd plugins/agent42-paperclip && npx vitest run tests/team.test.ts` | Wave 0 |
| ADV-01/02/03 | manifest has `agents.invoke`, `events.subscribe`, `plugin.state.read` | unit | `cd plugins/agent42-paperclip && npx vitest run tests/worker.test.ts` | Partial (existing) |

### Sampling Rate

- **Per task commit:** `python -m pytest tests/test_sidecar.py -x -q && cd plugins/agent42-paperclip && npx vitest run`
- **Per wave merge:** `python -m pytest tests/ -x -q && cd plugins/agent42-paperclip && npx vitest run`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/test_sidecar.py::TestAutoMemoryInjection` class — covers ADV-01 (auto_memory injection, disabled flag, callback metadata)
- [ ] `plugins/agent42-paperclip/tests/team.test.ts` — covers ADV-02 (fan-out) and ADV-03 (wave)
- [ ] Extend `plugins/agent42-paperclip/tests/worker.test.ts` — verify manifest capabilities include new entries

---

## Project Constraints (from CLAUDE.md)

| Directive | Application to Phase 30 |
|-----------|------------------------|
| All I/O is async — use `aiofiles`, `httpx`, `asyncio`. Never blocking I/O | `auto_memory` injection in `execute_async()` must remain fully async; no blocking calls |
| Frozen config — `Settings` dataclass in `core/config.py` | No new settings needed for this phase (all config is per-agent in `AdapterConfig`) |
| Graceful degradation — Redis, Qdrant, MCP are optional | `auto_memory` injection must degrade gracefully when memory_bridge is None or recall returns [] |
| Sandbox always on — validate paths via `sandbox.resolve_path()` | No filesystem operations in this phase |
| New pitfalls — add to `.claude/reference/pitfalls-archive.md` | If agents.invoke fire-and-forget causes problems, document in pitfalls-archive |

---

## Sources

### Primary (HIGH confidence)

- `plugins/agent42-paperclip/node_modules/@paperclipai/plugin-sdk/dist/types.d.ts` — `ctx.agents.invoke()` exact signature, `ctx.state.set/get`, `PluginAgentsClient`, `ToolRunContext`, `PLUGIN_STATE_SCOPE_KINDS`
- `plugins/agent42-paperclip/node_modules/@paperclipai/shared/dist/constants.d.ts` — `PLUGIN_CAPABILITIES` array (confirms `agents.invoke`, `events.subscribe`), `PLUGIN_EVENT_TYPES` array (confirms `agent.run.started`)
- `plugins/agent42-paperclip/node_modules/@paperclipai/plugin-sdk/README.md` — SDK surface reference, events table, agents section
- `core/sidecar_orchestrator.py` — existing memory recall pattern (lines 98-127), injection insertion point
- `core/sidecar_models.py` — existing model pattern (camelCase aliases, AdapterConfig)
- `plugins/agent42-paperclip/src/worker.ts` — existing setup() pattern, ctx.state usage in extract-learnings job
- `plugins/agent42-paperclip/src/tools.ts` — existing tool registration pattern
- `plugins/agent42-paperclip/manifest.json` — current capabilities list
- `.planning/phases/30-advanced-teamtool-auto-memory/30-CONTEXT.md` — locked decisions D-01 through D-22

### Secondary (MEDIUM confidence)

- `plugins/agent42-paperclip/tests/worker.test.ts` — createTestHarness pattern for new test files
- `tools/team_tool.py` — TeamTool orchestration patterns (fan_out_fan_in, sequential) — informational only per D-03

---

## Metadata

**Confidence breakdown:**
- `ctx.agents.invoke` signature: HIGH — read directly from installed SDK dist/types.d.ts
- `agent.run.started` event existence: HIGH — confirmed in PLUGIN_EVENT_TYPES readonly tuple in constants.d.ts
- `agents.invoke` capability string: HIGH — confirmed in PLUGIN_CAPABILITIES readonly tuple in constants.d.ts
- `plugin.state.read` capability requirement: HIGH — `ctx.state.get()` requires `plugin.state.read` per types.d.ts comment
- Fan-out result aggregation (fire-and-forget constraint): HIGH — confirmed by invoke return type `Promise<{ runId: string }>`
- Auto-memory injection approach: HIGH — extending existing pattern in execute_async()
- Wave state crash recovery: HIGH — `run` scopeKind confirmed in PLUGIN_STATE_SCOPE_KINDS

**Research date:** 2026-03-31
**Valid until:** 2026-04-30 (SDK released 2026-03-18, stable API surface)
