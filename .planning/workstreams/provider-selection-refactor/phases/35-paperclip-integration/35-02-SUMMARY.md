---
phase: 35-paperclip-integration
plan: 02
status: complete
started: 2026-04-06
completed: 2026-04-06
subsystem: plugins/agent42-paperclip
tags: [typescript, paperclip, provider-health, model-discovery, client]
dependency_graph:
  requires: [35-01]
  provides: [available-models data handler, enhanced ProviderHealthWidget, getModels() client method]
  affects: [plugins/agent42-paperclip/src/types.ts, plugins/agent42-paperclip/src/client.ts, plugins/agent42-paperclip/src/worker.ts, plugins/agent42-paperclip/src/ui/ProviderHealthWidget.tsx]
tech_stack:
  added: []
  patterns: [public-no-auth GET endpoint pattern, backward-compatible UI fallback]
key_files:
  created: []
  modified:
    - plugins/agent42-paperclip/src/types.ts
    - plugins/agent42-paperclip/src/client.ts
    - plugins/agent42-paperclip/src/worker.ts
    - plugins/agent42-paperclip/src/ui/ProviderHealthWidget.tsx
decisions:
  - ProviderStatusDetail declared before SidecarHealthResponse in types.ts to satisfy TypeScript forward-reference rules
  - providers_detail typed as optional (?) in both SidecarHealthResponse and HealthData for backward compat with old sidecar versions
  - getModels() uses plain Content-Type header (no authHeaders()) matching the public endpoint contract from D-05
metrics:
  duration_seconds: 240
  tasks_completed: 2
  files_modified: 4
---

# Phase 35 Plan 02: Client-side Provider Model Discovery Summary

## One-liner

TypeScript plugin wired to GET /sidecar/models via getModels() client method and available-models data handler, with ProviderHealthWidget enhanced to show per-provider status detail with backward-compatible fallback.

## Objective

Connect the Paperclip TypeScript plugin to the server-side endpoints created in Plan 01. Plugin can now discover available models and display rich provider connectivity status.

## What Changed

### types.ts — Three new interfaces + updated SidecarHealthResponse

- `ProviderModelItem` — mirrors Python Pydantic model (model_id, display_name, provider, categories, available)
- `ModelsResponse` — GET /sidecar/models response body (models list + providers list)
- `ProviderStatusDetail` — per-provider detail in health response (name, configured, connected, model_count, last_check)
- `SidecarHealthResponse` — added optional `providers_detail?: ProviderStatusDetail[]` and `configured?` to providers type

### client.ts — getModels() public method

- Phase 35 section added between extractLearnings() and Phase 36 section
- `getModels()` calls GET /sidecar/models with plain headers (no auth), 5s timeout, 1 retry on 5xx
- `ModelsResponse` added to the import block

### worker.ts — available-models data handler

- Registered immediately after the existing `provider-health` handler
- Calls `client.getModels()`, returns result or null on error
- Follows identical pattern to all other data handlers in the file

### ProviderHealthWidget.tsx — Enhanced provider status display

- Added `ProviderDetail` interface (matches ProviderStatusDetail but local to widget)
- Updated `HealthData` interface to include optional `providers_detail?: ProviderDetail[]`
- New rendering branch: when `providers_detail` present, renders each provider as a row with:
  - Status dot (green=connected, amber=configured-not-connected, red=not-configured)
  - Provider name
  - Model count badge (when > 0)
  - Status text badge (connected / configured / not configured)
- Fallback branch: when `providers_detail` absent, renders original configured-dict badge layout
- Graceful degradation: null case renders nothing (no crash)

## Requirements Addressed

- **UI-02**: Provider selection dashboard shows available models from Synthetic.new (getModels() + available-models handler now available)
- **UI-03**: Agent configuration UI allows selection from dynamically discovered models (available-models data handler registered)
- **UI-04**: Provider status dashboard shows connectivity per provider (enhanced ProviderHealthWidget renders providers_detail)

## Commits

| Hash | Message |
|------|---------|
| d3d4b0e | feat(35-02): add TS types and getModels() client method for provider model discovery |
| ab6152d | feat(35-02): add available-models data handler and enhance ProviderHealthWidget |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical functionality] ProviderStatusDetail declared before SidecarHealthResponse**
- **Found during:** Task 1
- **Issue:** Plan placed Phase 35 interfaces at the end of the file, but `SidecarHealthResponse` (near top) needed to reference `providers_detail?: ProviderStatusDetail[]`. TypeScript requires the type be declared before use.
- **Fix:** Inserted the Phase 35 section at the top of the file, before the Health section, so `ProviderStatusDetail` is in scope when `SidecarHealthResponse` uses it.
- **Files modified:** plugins/agent42-paperclip/src/types.ts

### Pre-existing Issues (out of scope)

Two test files (`adapter.test.ts`, `worker-handlers.test.ts`) have pre-existing `@types/node` configuration errors unrelated to this plan's changes. All source file TypeScript compilation is clean.

## Known Stubs

None — all data handlers wire to real client methods which call real sidecar endpoints.

## Self-Check

- [x] plugins/agent42-paperclip/src/types.ts contains `export interface ProviderModelItem`
- [x] plugins/agent42-paperclip/src/types.ts contains `export interface ModelsResponse`
- [x] plugins/agent42-paperclip/src/types.ts contains `export interface ProviderStatusDetail`
- [x] plugins/agent42-paperclip/src/types.ts SidecarHealthResponse contains `providers_detail?: ProviderStatusDetail[]`
- [x] plugins/agent42-paperclip/src/client.ts contains `async getModels(): Promise<ModelsResponse>`
- [x] plugins/agent42-paperclip/src/client.ts getModels uses plain headers, NOT authHeaders()
- [x] plugins/agent42-paperclip/src/worker.ts contains `ctx.data.register("available-models"`
- [x] plugins/agent42-paperclip/src/ui/ProviderHealthWidget.tsx contains `providers_detail`
- [x] TypeScript source compilation clean (no new errors)
- [x] Commit d3d4b0e exists
- [x] Commit ab6152d exists
