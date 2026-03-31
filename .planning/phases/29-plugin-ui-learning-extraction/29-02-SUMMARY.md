---
phase: 29-plugin-ui-learning-extraction
plan: "02"
subsystem: plugin
tags: [typescript, plugin, worker, manifest, data-handlers, jobs, testing]
dependency_graph:
  requires: ["29-01"]
  provides: ["manifest-ui-slots", "client-new-methods", "worker-data-handlers", "worker-job-handler"]
  affects: ["plugins/agent42-paperclip"]
tech_stack:
  added: []
  patterns: ["ctx.data.register", "ctx.jobs.register", "ctx.state.get/set watermark", "TestHarness.getData/runJob"]
key_files:
  created:
    - plugins/agent42-paperclip/tests/data-handlers.test.ts
  modified:
    - plugins/agent42-paperclip/manifest.json
    - plugins/agent42-paperclip/package.json
    - plugins/agent42-paperclip/src/types.ts
    - plugins/agent42-paperclip/src/client.ts
    - plugins/agent42-paperclip/src/worker.ts
    - plugins/agent42-paperclip/tests/client.test.ts
    - plugins/agent42-paperclip/tests/worker.test.ts
decisions:
  - "TestHarness.setup() does not exist in SDK — use plugin.definition.setup(harness.ctx) pattern matching existing worker.test.ts"
  - "routing-decisions handler calls client.getAgentSpend (not getRoutingHistory) per plan spec — spend data serves routing widget"
  - "watermark update skipped on extractLearnings failure — prevents re-processing guard from masking errors"
metrics:
  duration: "351 seconds"
  completed: "2026-03-31T17:26:50Z"
  tasks_completed: 2
  files_modified: 7
---

# Phase 29 Plan 02: Plugin TypeScript Wiring Summary

TypeScript plugin wiring: manifest v1.1.0 with 4 UI slots + 1 job + 4 capabilities, Agent42Client 6 new GET/POST methods, worker 5 data handlers + 1 job handler with watermark state management, and 12 new data/job handler tests.

## Tasks Completed

| Task | Description | Commit | Status |
|------|-------------|--------|--------|
| 1 | Manifest, types, Agent42Client 6 new methods, client tests | 26e7f15 | Done |
| 2 | Worker data handlers, job handler, handler tests | 356be64 | Done |

## What Was Built

### Task 1: Manifest, Types, Client (26e7f15)

**manifest.json v1.1.0:**
- 4 new capabilities: `ui.detailTab.register`, `ui.dashboardWidget.register`, `jobs.schedule`, `plugin.state.write`
- `entrypoints.ui` added: `./dist/ui`
- `ui.slots`: 4 slots — AgentEffectivenessTab (entityType: agent), ProviderHealthWidget, MemoryBrowserTab (entityType: run), RoutingDecisionsWidget
- `jobs`: extract-learnings with hourly cron `0 * * * *`

**src/types.ts:** 7 new interfaces — `AgentProfileResponse`, `TaskTypeStats`, `AgentEffectivenessResponse`, `RoutingHistoryEntry`, `RoutingHistoryResponse`, `MemoryTraceItem`, `MemoryRunTraceResponse`, `SpendEntry`, `AgentSpendResponse`, `ExtractLearningsRequest`, `ExtractLearningsResponse`

**src/client.ts:** 6 new methods:
- `getAgentProfile(agentId)` — GET /agent/{id}/profile
- `getAgentEffectiveness(agentId)` — GET /agent/{id}/effectiveness
- `getRoutingHistory(agentId, limit=20)` — GET /agent/{id}/routing-history?limit=N
- `getMemoryRunTrace(runId)` — GET /memory/run-trace/{runId}
- `getAgentSpend(agentId, hours=24)` — GET /agent/{id}/spend?hours=N
- `extractLearnings(body)` — POST /memory/extract

**package.json:** Added react, @types/react, esbuild to devDependencies. Build scripts updated.

**tests/client.test.ts:** 10 new tests (18 total), all passing.

### Task 2: Worker Handlers + Tests (356be64)

**src/worker.ts:** Added inside `setup()` after `registerTools()`:
- 5 `ctx.data.register()` handlers: agent-profile, provider-health, memory-run-trace, routing-decisions, agent-effectiveness
- All handlers return `null` on error or missing required params (graceful degradation)
- `ctx.jobs.register("extract-learnings")` handler:
  - Reads watermark via `ctx.state.get({ scopeKind: "instance", stateKey: "last-learn-at" })`
  - Calls `client.extractLearnings({ sinceTs, batchSize: 20 })`
  - Updates watermark via `ctx.state.set(...)` only on success
  - Returns early without watermark update on failure

**tests/worker.test.ts:** 2 new tests for handler registration verification (11 total).

**tests/data-handlers.test.ts (new):** 12 tests:
- agent-profile: returns data, returns null when agentId missing
- provider-health: returns health data, returns null on connection error
- memory-run-trace: returns trace data, returns null when runId missing
- routing-decisions: returns spend data
- agent-effectiveness: returns stats, returns null when agentId missing
- extract-learnings job: calls POST /memory/extract, does not update watermark on failure

## Test Results

```
Test Files: 4 passed (client, worker, tools, data-handlers)
Tests:      50 passed (18 client + 11 worker + 9 tools + 12 data-handlers)
TypeScript: tsc --noEmit exits 0
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] TestHarness API mismatch — plan used harness.setup() which does not exist**
- **Found during:** Task 2 (creating data-handlers.test.ts)
- **Issue:** The plan's data-handlers.test.ts template used `harness.setup()`, but `TestHarness` (from `@paperclipai/plugin-sdk/testing`) does not have a `setup()` method. The SDK only exposes `ctx` which is passed to `plugin.definition.setup(harness.ctx)`.
- **Fix:** Used `plugin.definition.setup(harness.ctx)` pattern matching the existing worker.test.ts pattern. Also moved health mock setup to be inline per test rather than in a shared beforeEach, since data handlers don't call health during setup.
- **Files modified:** plugins/agent42-paperclip/tests/data-handlers.test.ts
- **Commit:** 356be64

## Known Stubs

None. All data handlers are fully wired to client methods. No placeholder values or TODO stubs exist.

## Self-Check

- [x] plugins/agent42-paperclip/manifest.json — modified, contains ui.detailTab.register
- [x] plugins/agent42-paperclip/src/types.ts — modified, contains AgentProfileResponse
- [x] plugins/agent42-paperclip/src/client.ts — modified, contains getAgentProfile
- [x] plugins/agent42-paperclip/src/worker.ts — modified, contains ctx.data.register
- [x] plugins/agent42-paperclip/tests/data-handlers.test.ts — created
- [x] Commit 26e7f15 — Task 1
- [x] Commit 356be64 — Task 2
- [x] 50 tests pass, tsc --noEmit exits 0

## Self-Check: PASSED
