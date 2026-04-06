---
phase: 29-plugin-ui-learning-extraction
plan: "03"
subsystem: plugins/agent42-paperclip
tags: [react, typescript, esbuild, plugin-ui, paperclip]
dependency_graph:
  requires: ["29-02"]
  provides: ["UI-01", "UI-02", "UI-03", "UI-04"]
  affects: ["plugins/agent42-paperclip/dist/ui"]
tech_stack:
  added:
    - "React 18.3 — UI components for plugin slots"
    - "esbuild 0.25 — browser ESM bundler via createPluginBundlerPresets()"
  patterns:
    - "usePluginData() hook pattern for all UI data fetching"
    - "Plain React + inline styles (no shared component SDK dependency)"
    - "TSC for worker, esbuild for UI (separate compile pipelines)"
key_files:
  created:
    - plugins/agent42-paperclip/src/ui/AgentEffectivenessTab.tsx
    - plugins/agent42-paperclip/src/ui/ProviderHealthWidget.tsx
    - plugins/agent42-paperclip/src/ui/MemoryBrowserTab.tsx
    - plugins/agent42-paperclip/src/ui/RoutingDecisionsWidget.tsx
    - plugins/agent42-paperclip/src/ui/index.tsx
    - plugins/agent42-paperclip/build-ui.mjs
    - plugins/agent42-paperclip/dist/ui/index.js
  modified:
    - plugins/agent42-paperclip/tsconfig.json
    - plugins/agent42-paperclip/pnpm-lock.yaml
decisions:
  - "Exclude src/ui from tsc compilation — esbuild handles TSX, preventing rootDir conflict"
  - "context._context renamed to _context in RoutingDecisionsWidget to suppress unused-var lint warning"
  - "companyId passed as `context.companyId ?? undefined` to match PluginHostContext nullable type"
metrics:
  duration: "~15 minutes"
  completed_date: "2026-03-31"
  tasks_completed: 2
  files_changed: 9
---

# Phase 29 Plan 03: React UI Components and esbuild Build Summary

**One-liner:** 4 Paperclip plugin UI slot components (tier badge, provider health, memory browser, routing spend) using usePluginData() hook with esbuild browser ESM build.

## What Was Built

Four React components registered as Paperclip plugin UI slots, backed by data handlers from Plan 02:

1. **AgentEffectivenessTab** — Detail tab for agent entities. Shows tier badge (bronze/silver/gold with color), overall success rate, task volume, avg speed, composite score, and per-task-type breakdown table from `agent-effectiveness` handler.

2. **ProviderHealthWidget** — Dashboard widget. Shows sidecar status indicator (green/amber dot), memory + Qdrant availability cards, and configured provider pills (green=active, red=inactive) from `provider-health` handler.

3. **MemoryBrowserTab** — Detail tab for run entities. Shows injected memories with relevance badges and source tags, plus extracted learnings with tag pills. Both sections have proper empty states with explanatory text.

4. **RoutingDecisionsWidget** — Dashboard widget. Shows last-24h token spend, stacked bar distribution across providers, and per-provider breakdown (tokens + cost) from `routing-decisions` handler.

All 4 components use `usePluginData()` from `@paperclipai/plugin-sdk/ui` with the exact data keys registered in Plan 02's `worker.ts`.

## Build Toolchain

`build-ui.mjs` uses `createPluginBundlerPresets()` from the SDK to produce a browser ESM bundle at `dist/ui/index.js`. The tsconfig excludes `src/ui/` from tsc (esbuild handles TSX transpilation), so the worker compilation stays clean.

Build command: `pnpm run build` (tsc for worker, then esbuild for UI). Both succeed.

## Verification Results

- `pnpm run build` exits 0
- `dist/ui/index.js` (15KB) produced
- Manifest: 4 UI slots, 6 capabilities, 1 job — all correct
- 50 plugin TypeScript tests pass (vitest)
- 78 Python tests pass (test_sidecar.py + test_memory_bridge.py)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Type Safety] Nullable companyId in PluginHostContext**
- **Found during:** Task 1 implementation
- **Issue:** Plan spec shows `companyId: string` but actual SDK type is `companyId: string | null`. `ProviderHealthWidget` received `PluginWidgetProps` where `context.companyId` is nullable.
- **Fix:** Pass `context.companyId ?? undefined` to `usePluginData` params to maintain type safety.
- **Files modified:** `src/ui/ProviderHealthWidget.tsx`
- **Commit:** 7380aa6

**2. [Rule 2 - Lint Safety] Unused context parameter in RoutingDecisionsWidget**
- **Found during:** Task 1 implementation
- **Issue:** `RoutingDecisionsWidget` widget doesn't use `context` (shows company-wide spend, not entity-scoped). TypeScript strict mode would flag unused destructured parameter.
- **Fix:** Use `{ context: _context }` destructuring pattern to acknowledge the parameter while marking it unused.
- **Files modified:** `src/ui/RoutingDecisionsWidget.tsx`
- **Commit:** 7380aa6

**3. [Rule 3 - Missing Install] react and esbuild not installed**
- **Found during:** Pre-build verification
- **Issue:** `package.json` listed `react`, `@types/react`, `esbuild` in devDependencies but they were not yet installed (pnpm had only installed test dependencies previously).
- **Fix:** Ran `pnpm install` to add missing packages.
- **Files modified:** `pnpm-lock.yaml`
- **Commit:** 7380aa6

### Checkpoint

Task 2 was a `checkpoint:human-verify` — auto-approved under auto-mode. All automated verification commands passed before approval.

## Known Stubs

None. All 4 components are fully wired to real data handlers from Plan 02. Loading, error, and empty states are handled explicitly. No placeholder text or hardcoded empty data flows to UI rendering.

## Self-Check: PASSED

| Item | Status |
|------|--------|
| src/ui/AgentEffectivenessTab.tsx | FOUND |
| src/ui/ProviderHealthWidget.tsx | FOUND |
| src/ui/MemoryBrowserTab.tsx | FOUND |
| src/ui/RoutingDecisionsWidget.tsx | FOUND |
| src/ui/index.tsx | FOUND |
| build-ui.mjs | FOUND |
| dist/ui/index.js | FOUND |
| Commit 7380aa6 | FOUND |
