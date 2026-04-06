---
phase: 30-advanced-teamtool-auto-memory
plan: "02"
subsystem: paperclip-plugin
tags: [teamtool, fan-out, wave, events, typescript, testing]
dependency_graph:
  requires: [30-01]
  provides: [team_execute-tool, agent.run.started-handler, team-types, team-tests]
  affects: [plugins/agent42-paperclip/src, plugins/agent42-paperclip/tests]
tech_stack:
  added: []
  patterns: [fan-out-fan-in, wave-sequential, crash-recovery, ctx.agents.invoke, ctx.events.on]
key_files:
  created:
    - plugins/agent42-paperclip/tests/team.test.ts
  modified:
    - plugins/agent42-paperclip/src/types.ts
    - plugins/agent42-paperclip/manifest.json
    - plugins/agent42-paperclip/src/tools.ts
    - plugins/agent42-paperclip/src/worker.ts
    - plugins/agent42-paperclip/tests/worker.test.ts
decisions:
  - "ctx.agents.invoke is fire-and-forget per SDK — fan-out subResults have status=invoked and empty output by design"
  - "Wave crash recovery reads ctx.state.get at start with scopeKind=run then resumes from saved completedWaves index"
  - "agent.run.started is a valid PluginEventType per @paperclipai/shared constants — no type casting needed"
  - "Test harness invoke works with seeded agents (harness.seed) — no fetch mocking needed for team_execute tests"
metrics:
  duration_seconds: 372
  tasks_completed: 5
  tasks_total: 5
  files_modified: 5
  tests_added: 18
  completed_date: "2026-03-31"
---

# Phase 30 Plan 02: TeamTool Strategies + Event Handler Summary

**One-liner:** team_execute tool with fan-out (Promise.all) and wave (sequential crash-recovery) strategies, agent.run.started event handler, manifest capability updates, and 65 passing tests.

## What Was Built

Implemented the `team_execute` plugin tool with two dispatch strategies for orchestrating sub-agents in Paperclip:

**Fan-out strategy (ADV-02):** Uses `Promise.all` to invoke all `subAgentIds` in parallel via `ctx.agents.invoke`. Returns a `subResults` array where each entry has `{ agentId, runId, status: "invoked", output: "", costUsd: 0 }`. The SDK's `ctx.agents.invoke` is fire-and-forget — no output is available synchronously.

**Wave strategy (ADV-03):** Invokes agents sequentially in a loop. Each wave receives the task plus context from the previous wave's output in its prompt. Progress is persisted via `ctx.state.set` with `scopeKind: "run"` after each wave, and read via `ctx.state.get` at start for crash recovery — if a run restarts mid-wave, it picks up from the last completed wave.

**Event handler (ADV-01):** Registered `ctx.events.on("agent.run.started", ...)` inside `setup()` synchronously before setup resolves (per Pitfall 5 from research), logging agentId and companyId for auto-memory observability.

**Manifest updates:** Version bumped 1.1.0 → 1.2.0. Three capabilities added (`agents.invoke`, `events.subscribe`, `plugin.state.read`). `team_execute` tool declaration added with `strategy` enum schema.

**TypeScript types:** `SubAgentResult`, `WaveOutput`, `WaveDefinition`, `TeamExecuteParams`, `TeamExecuteResult` interfaces added to `types.ts`.

## Tasks Completed

| Task | Title | Commit |
|------|-------|--------|
| 30-02-01 | Add TypeScript types for team strategies | 8e684c9 |
| 30-02-02 | Update manifest with capabilities and team_execute | 37fe3a9 |
| 30-02-03 | Register team_execute tool in tools.ts | 89486f5 |
| 30-02-04 | Register agent.run.started event handler | 4fc33ab |
| 30-02-05 | Write unit tests for team_execute and manifest | bdf9a65 |

## Verification Results

```
npx vitest run
  Test Files  5 passed (5)
        Tests  65 passed (65)
     Duration  3.04s

npx tsc --noEmit
  (no output — passes)

node -e "..."
  caps: 9 tools: 6
```

## Decisions Made

1. **Fire-and-forget invoke design:** `ctx.agents.invoke` returns `{ runId }` immediately without waiting for completion. Fan-out `subResults` correctly have `status: "invoked"` and `output: ""` — this is SDK-correct behavior, not a stub. The plan's `must_haves.truths` explicitly states "output is empty — ctx.agents.invoke is fire-and-forget per SDK".

2. **Wave crash recovery via scopeKind=run:** State scoped to the specific run ensures crash recovery only applies to the current execution, not cross-contaminating other runs.

3. **agent.run.started event type confirmed:** Verified in `@paperclipai/shared/dist/constants.d.ts` — it is a member of `PLUGIN_EVENT_TYPES` and a valid `PluginEventType`. No type casting required.

4. **Test harness agent seeding for invoke:** The SDK test harness implements `ctx.agents.invoke` natively via seeded agents (`harness.seed({ agents: [...] })`). Tests use real harness invoke rather than fetch mocks, making them more realistic.

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None. The `output: ""` and `costUsd: 0` in `SubAgentResult` are intentional SDK-design stubs documented in the plan's `must_haves.truths` — `ctx.agents.invoke` is fire-and-forget and provides no output synchronously. These will be populated in future phases when run completion events are wired up.

## Self-Check: PASSED
