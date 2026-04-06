# Phase 30: Advanced — TeamTool + Auto Memory - Discussion Log (Auto Mode)

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions captured in CONTEXT.md — this log preserves the analysis.

**Date:** 2026-03-31
**Phase:** 30-advanced-teamtool-auto-memory
**Mode:** auto (discuss mode, all decisions auto-selected)
**Areas analyzed:** Strategy Orchestration, Fan-Out Implementation, Wave Strategy, Auto Memory Injection, Result Aggregation, Strategy Detection

---

## Strategy Orchestration Layer

| Option | Description | Selected |
|--------|-------------|----------|
| Plugin-side via Paperclip SDK | Use ctx.agents.invoke() for sub-agent spawning — Paperclip audit trail, budget tracking | [auto] |
| Sidecar-side via TeamTool | Reuse existing TeamTool patterns with subprocess agents | |
| Hybrid plugin+sidecar | Plugin orchestrates, sidecar provides intelligence per sub-agent | |

**Auto-selected:** Plugin-side via Paperclip SDK (recommended default)
**Rationale:** Sub-runs must be Paperclip-visible for audit/budget. TeamTool uses Agent42 subprocess runtime, not Paperclip agents.

---

## Fan-Out Implementation

| Option | Description | Selected |
|--------|-------------|----------|
| New `team_execute` tool with strategy param | Single tool for both strategies, plugin spawns in parallel | [auto] |
| Separate fan-out tool | Dedicated `team_fan_out` tool with simpler API | |
| Sidecar endpoint only | No plugin tool, sidecar handles all orchestration | |

**Auto-selected:** New `team_execute` tool with strategy parameter (recommended default)
**Rationale:** Consistent with existing tool registration pattern. Single tool avoids API fragmentation.

---

## Wave Strategy

| Option | Description | Selected |
|--------|-------------|----------|
| Sequential ctx.agents.invoke() with state | Plugin chains invokes, persists wave progress in ctx.state | [auto] |
| Sidecar wave orchestration | Sidecar manages waves internally, plugin just triggers | |
| Job-based waves | Each wave is a separate scheduled job | |

**Auto-selected:** Sequential ctx.agents.invoke() with state persistence (recommended default)
**Rationale:** Plugin state supports crash recovery. Job-based approach adds unnecessary scheduling complexity.

---

## Auto Memory Injection

| Option | Description | Selected |
|--------|-------------|----------|
| Sidecar-side in execute_async() | Enhance existing recall to prepend memories to context dict | [auto] |
| Plugin event handler | Subscribe to agent.run.started, inject memories via adapter | |
| New auto_memory config flag | Sidecar injects when flag is set, operators can disable | [auto] |

**Auto-selected:** Sidecar-side injection + config flag (recommended default)
**Rationale:** Sidecar already recalls memories. No documented SDK API for prompt modification from event handlers. Config flag provides operator control.

**Key finding:** `heartbeat.started` event unconfirmed (STATE.md blocker). `agent.run.started` is confirmed in SDK — used for observability only, not injection.

---

## Result Aggregation

| Option | Description | Selected |
|--------|-------------|----------|
| Single aggregated callback | All sub-agent results in one callback payload | [auto] |
| Per-sub-agent callbacks | Each sub-agent sends its own callback | |
| Streaming results | Use plugin streams for real-time result delivery | |

**Auto-selected:** Single aggregated callback (recommended default)
**Rationale:** Matches existing CallbackPayload pattern. Per-agent callbacks would fragment Paperclip's run tracking.

---

## Strategy Detection

| Option | Description | Selected |
|--------|-------------|----------|
| `strategy` field in context dict | Read from AdapterExecutionContext.context, default "standard" | [auto] |
| Separate endpoint per strategy | POST /sidecar/execute/fan-out, /execute/wave | |
| Adapter-level routing | Adapter detects strategy before sidecar call | |

**Auto-selected:** `strategy` field in context dict (recommended default)
**Rationale:** Context dict is already `dict[str, Any]` passthrough. Unknown values fall back to "standard" (matches wakeReason pattern).

---

## Claude's Discretion

- Endpoint routing approach (extend existing vs. new endpoint)
- memoryContext field format
- Tool naming (one vs. two tools)
- Sub-agent timeout/retry policy
- Plugin state scope for wave progress
- Test organization

## Deferred Ideas

None — analysis stayed within phase scope
