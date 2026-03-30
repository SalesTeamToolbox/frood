---
phase: 27-paperclip-adapter
plan: "02"
subsystem: agent42-paperclip-adapter
tags: [typescript, esm, tdd, paperclip, adapter-module, session-codec, sidecar]
dependency_graph:
  requires:
    - adapters/agent42-paperclip/src/types.ts (Plan 01 — SidecarConfig, parseSidecarConfig, SidecarExecuteRequest)
    - adapters/agent42-paperclip/src/client.ts (Plan 01 — Agent42Client)
    - "@paperclipai/adapter-utils" (AdapterSessionCodec, ServerAdapterModule, AdapterExecutionContext)
  provides:
    - adapters/agent42-paperclip/src/session.ts (AdapterSessionCodec: serialize/deserialize/getDisplayId)
    - adapters/agent42-paperclip/src/adapter.ts (execute() and testEnvironment() functions)
    - adapters/agent42-paperclip/src/index.ts (ServerAdapterModule default export with type "agent42_local")
    - adapters/agent42-paperclip/tests/session.test.ts (18 session codec tests)
    - adapters/agent42-paperclip/tests/adapter.test.ts (28 adapter + index tests)
  affects:
    - Paperclip deployment: installs adapter package, loads index.ts default export
    - Agent42 sidecar: receives heartbeat POSTs from Paperclip via execute()
tech_stack:
  added: []
  patterns:
    - TDD red-green workflow for both session codec and adapter module
    - Near-identity serialize/deserialize preserving unknown fields (D-10 forward-compatibility)
    - JSON.stringify(sessionState) as adapterConfig.sessionKey string (D-08)
    - vi.stubGlobal("fetch") for HTTP mock isolation in adapter tests
    - makePaperclipCtx() factory pattern for AdapterExecutionContext test fixtures
key_files:
  created:
    - adapters/agent42-paperclip/src/session.ts
    - adapters/agent42-paperclip/src/adapter.ts
    - adapters/agent42-paperclip/src/index.ts
    - adapters/agent42-paperclip/tests/session.test.ts
    - adapters/agent42-paperclip/tests/adapter.test.ts
  modified: []
decisions:
  - Near-identity serialize/deserialize: codec's role is defensive parsing + forward-compat, not compression
  - agentId resolved as (config.agentId || ctx.agent.id): falsy empty-string also falls back to Paperclip ID
  - JSON.stringify(sessionState) as sessionKey string in POST body: matches Python Pydantic sessionKey field type
  - wakeReason warning via ctx.onLog("stderr") never throws: Paperclip heartbeats continue on unknown values
  - testEnvironment adds warn (not fail) for unavailable memory/qdrant subsystems: partial functionality acceptable
metrics:
  duration: "~5 minutes"
  completed: "2026-03-30"
  tasks_completed: 2
  tasks_total: 2
  files_changed: 5
---

# Phase 27 Plan 02: Adapter Module and Session Codec Summary

**One-liner:** ServerAdapterModule implementation bridging Paperclip's AdapterExecutionContext to Agent42 sidecar format, with defensive session codec, wakeReason validation, dual agentId population, and 58 tests across 3 files.

## What Was Built

Completed the `adapters/agent42-paperclip/` TypeScript package by adding the business logic layer on top of Plan 01's HTTP client and type definitions.

### src/session.ts

AdapterSessionCodec implementation with three methods:

- `serialize(params)`: returns `null` for null input; otherwise shallow-copies the Record, preserving all fields including unknown future ones (D-10 forward-compatibility)
- `deserialize(raw)`: rejects null, undefined, primitives, and arrays; shallow-copies valid objects — defensive parsing ensures Paperclip's stored state is always a clean Record
- `getDisplayId(params)`: returns `"agent42:{agentId}"` when agentId is a non-empty string, null otherwise

The serialize/deserialize pair is intentionally near-identity: Paperclip handles its own persistence serialization; the codec's job is defensive parsing and forward-compatibility via field spreading.

### src/adapter.ts

Two exported functions implementing the core business logic:

**execute(ctx: AdapterExecutionContext):**
1. Parses `ctx.agent.adapterConfig` via `parseSidecarConfig()` (defensive, never throws)
2. Resolves `agentId` as `config.agentId || ctx.agent.id` — falsy empty string also falls back (ADAPT-04)
3. Extracts `wakeReason` from `ctx.context.wakeReason`, defaulting to `"heartbeat"` (ADAPT-03); unknown values log a warning via `ctx.onLog("stderr")` but never throw (D-12)
4. Decodes session state via `sessionCodec.deserialize(ctx.runtime.sessionParams)` (ADAPT-05)
5. Builds `SidecarExecuteRequest` with agentId in both top-level and `adapterConfig.agentId` (D-14), `sessionKey` as `JSON.stringify(sessionState)` (D-08), and full context passthrough
6. Calls `client.execute()` and returns `exitCode:0` with incremented `executionCount` on success
7. On any error (HTTP or network): catches exception, returns `exitCode:1` with `errorMessage` — never unhandled throw (ADAPT-02)

**testEnvironment(ctx: AdapterEnvironmentTestContext):**
1. Checks for missing `sidecarUrl` — returns `status:"fail"` with `missing_sidecar_url` error check
2. Calls `client.health()` — on success: adds `sidecar_reachable` info check, warns on unavailable memory/qdrant subsystems
3. On network error: returns `status:"fail"` with `sidecar_unreachable` error check and hint

### src/index.ts

Minimal barrel export assembling the `ServerAdapterModule`:

```typescript
const adapter: ServerAdapterModule = {
  type: "agent42_local",
  execute,
  testEnvironment,
  sessionCodec,
};
export default adapter;
```

### tests/session.test.ts (18 tests)

Covers: serialize null-safety, identity, forward-compat, copy semantics; deserialize null/undefined/string/array/number rejection, valid Record passthrough, forward-compat; round-trip deep-equality; getDisplayId null params, missing agentId, agentId format.

### tests/adapter.test.ts (28 tests)

Covers: execute() runId/agentId/companyId in POST body, agentId from adapterConfig (ADAPT-04), empty-string fallback (ADAPT-04), dual agentId population (D-14), wakeReason from context (ADAPT-03), heartbeat default, unknown-value stderr warning (D-12), context passthrough, exitCode:0/1/timedOut, executionCount increment (ADAPT-05), sessionDisplayId, summary format, session state decoding, sessionKey JSON string (D-08), HTTP error → exitCode:1 (ADAPT-02), network throw → exitCode:1; testEnvironment pass/fail/warn/unreachable/testedAt; default export type/execute/testEnvironment/sessionCodec shape.

## Full Test Suite Results

```
Test Files  3 passed (3)
     Tests  58 passed (58)
   Duration  ~1.4s
```

Build: `npx tsc` produces all 10 dist/ files (5x .js + 5x .d.ts) with source maps. ESM import verified: `type: agent42_local`, `execute: function`, `testEnvironment: function`, `sessionCodec: true`.

## Requirement Coverage

- **ADAPT-01**: `testEnvironment()` implements `ServerAdapterModule.testEnvironment`, tsc confirms type compatibility
- **ADAPT-02**: `execute()` POSTs to sidecar, catches all errors → `exitCode:1` with `errorMessage`
- **ADAPT-03**: `wakeReason` extracted from `ctx.context.wakeReason`, validated against known set, unknown values warn via stderr
- **ADAPT-04**: `agentId` extracted from `adapterConfig.agentId` (or `ctx.agent.id` fallback), populated in both top-level and `adapterConfig`
- **ADAPT-05**: `sessionCodec.serialize/deserialize` round-trips state, preserves unknown fields, `getDisplayId` returns prefixed ID

## Deviations from Plan

None — plan executed exactly as written. All interfaces matched, all behavior tests implemented as specified.

## Known Stubs

None. All methods are fully implemented with live HTTP calls to the sidecar. The adapter package is complete and ready for installation in a Paperclip deployment.

## Self-Check: PASSED

Files created:
- FOUND: adapters/agent42-paperclip/src/session.ts
- FOUND: adapters/agent42-paperclip/src/adapter.ts
- FOUND: adapters/agent42-paperclip/src/index.ts
- FOUND: adapters/agent42-paperclip/tests/session.test.ts
- FOUND: adapters/agent42-paperclip/tests/adapter.test.ts

Commits:
- FOUND: c1122f0 (test: session RED phase)
- FOUND: 5ae495c (feat: session GREEN phase)
- FOUND: ebc902a (test: adapter RED phase)
- FOUND: 8cdac61 (feat: adapter GREEN phase)

Tests: 58/58 passed (18 session + 28 adapter + 12 client)
TypeScript: tsc --noEmit passes with zero errors
Build: tsc produces dist/ with 5 .js + 5 .d.ts + 10 .map files
ESM: node --input-type=module import verified with correct shape
