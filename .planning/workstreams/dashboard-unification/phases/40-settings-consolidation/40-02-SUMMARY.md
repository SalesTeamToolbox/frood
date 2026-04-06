---
phase: 40-settings-consolidation
plan: "02"
subsystem: paperclip-plugin
tags: [typescript, types, client, worker, settings, memory, toggle]
dependency_graph:
  requires: []
  provides: [toggleTool, toggleSkill, getMemoryStats, getStorageStatus, purgeMemory client methods, memory-stats/storage-status data handlers, toggle-tool/toggle-skill/purge-memory action handlers]
  affects: [plugins/agent42-paperclip/src/types.ts, plugins/agent42-paperclip/src/client.ts, plugins/agent42-paperclip/src/worker.ts]
tech_stack:
  added: []
  patterns: [fetchWithRetry pattern for all new HTTP methods, ctx.data.register for read-only data endpoints, ctx.actions.register for mutation/delete operations]
key_files:
  created: []
  modified:
    - plugins/agent42-paperclip/src/types.ts
    - plugins/agent42-paperclip/src/client.ts
    - plugins/agent42-paperclip/src/worker.ts
decisions:
  - Pre-existing test file TypeScript errors (@types/node missing in adapter.test.ts and worker-handlers.test.ts) are out of scope — they existed before this plan and are not caused by these changes
metrics:
  duration: ~8 minutes
  completed: "2026-04-05T08:43:34Z"
  tasks: 2/2
  files_modified: 3
---

# Phase 40 Plan 02: TypeScript Layer Extension for Settings Consolidation Summary

TypeScript types, client methods, and worker handlers for tool/skill toggles, memory stats retrieval, storage status, and memory purge — providing SDK plumbing for SettingsPage.tsx (Plan 03).

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add TypeScript types | 7a1e135 | plugins/agent42-paperclip/src/types.ts |
| 2 | Add client methods and worker handlers | a0e5c82 | plugins/agent42-paperclip/src/client.ts, plugins/agent42-paperclip/src/worker.ts |

## What Was Built

### types.ts
- `SettingsKeyEntry.source` field added (`"admin" | "env" | "none"`) per D-07
- `MemoryStatsResponse` — mirrors GET /memory-stats response: recall_count, learn_count, error_count, avg_latency_ms, period_start
- `StorageStatusResponse` — mirrors GET /storage-status response: mode, qdrant_available, learning_enabled
- `ToggleResponse` — mirrors PATCH /tools/{name} and /skills/{name}: name, enabled
- `PurgeMemoryResponse` — mirrors DELETE /memory/{collection}: ok, collection

### client.ts
- `toggleTool(name, enabled)` — PATCH /tools/{name} with `{ enabled }` body
- `toggleSkill(name, enabled)` — PATCH /skills/{name} with `{ enabled }` body
- `getMemoryStats()` — GET /memory-stats
- `getStorageStatus()` — GET /storage-status
- `purgeMemory(collection)` — DELETE /memory/{collection}

All methods follow the existing `fetchWithRetry` pattern with Bearer auth.

### worker.ts
- Data handlers: `memory-stats`, `storage-status` (follow ctx.data.register pattern)
- Action handlers: `toggle-tool`, `toggle-skill`, `purge-memory` (follow ctx.actions.register pattern)

## Verification

```
Source files TypeScript compilation: PASSED (no errors in types.ts, client.ts, worker.ts)
Pre-existing test file errors: OUT OF SCOPE (adapter.test.ts, worker-handlers.test.ts missing @types/node — pre-existed before this plan)

grep -c "toggleTool|toggleSkill|getMemoryStats|getStorageStatus|purgeMemory" client.ts => 10
grep -c "toggle-tool|toggle-skill|purge-memory|memory-stats|storage-status" worker.ts => 10
```

## Deviations from Plan

None - plan executed exactly as written.

## Known Stubs

None - all new methods are fully wired to HTTP endpoints defined in plan specification. The sidecar Python endpoints (PATCH /tools/{name}, PATCH /skills/{name}, GET /memory-stats, GET /storage-status, DELETE /memory/{collection}) are owned by Plan 01. Plan 03 (SettingsPage.tsx) consumes these client/worker methods to build the UI.

## Self-Check: PASSED

Files exist:
- plugins/agent42-paperclip/src/types.ts — FOUND
- plugins/agent42-paperclip/src/client.ts — FOUND  
- plugins/agent42-paperclip/src/worker.ts — FOUND

Commits exist:
- 7a1e135 (feat(40-02): add TypeScript types) — FOUND
- a0e5c82 (feat(40-02): add client methods and worker handlers) — FOUND
