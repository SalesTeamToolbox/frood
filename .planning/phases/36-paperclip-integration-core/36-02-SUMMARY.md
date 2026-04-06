---
phase: 36-paperclip-integration-core
plan: "02"
subsystem: paperclip-plugin
tags: [paperclip, typescript, worker, ui-components, terminal, apps, settings, tools-skills]
dependency_graph:
  requires: [36-01]
  provides: [PAPERCLIP-01, PAPERCLIP-02, PAPERCLIP-03, PAPERCLIP-04]
  affects: [plugins/agent42-paperclip]
tech_stack:
  added: []
  patterns: [usePluginData, usePluginAction, usePluginStream, ctx.data.register, ctx.actions.register, ctx.streams.emit]
key_files:
  created:
    - plugins/agent42-paperclip/src/ui/WorkspacePage.tsx
    - plugins/agent42-paperclip/src/ui/AppsPage.tsx
    - plugins/agent42-paperclip/src/ui/ToolsSkillsTab.tsx
    - plugins/agent42-paperclip/src/ui/SettingsPage.tsx
    - plugins/agent42-paperclip/src/ui/WorkspaceNavEntry.tsx
  modified:
    - plugins/agent42-paperclip/src/worker.ts
    - plugins/agent42-paperclip/src/ui/index.tsx
    - plugins/agent42-paperclip/dist/ (rebuilt)
decisions:
  - "Terminal uses short-lived session token (POST /ws/terminal-token) rather than API key in WebSocket URL — per CLAUDE.md rule 6 (never log/expose API keys)"
  - "terminalSessions Map at module level (not inside setup()) to survive across multiple handler invocations"
  - "WorkspaceNavEntry href pattern uses /plugins/agent42.paperclip-plugin/{pageId} from SDK README — may need host-specific adjustment at integration time (D-14 progressive enhancement)"
metrics:
  duration: "~4 minutes"
  completed_date: "2026-04-03"
  tasks: 2
  files_modified: 7
  commits: 3
---

# Phase 36 Plan 02: Worker Handlers and UI Components Summary

Worker handlers and React UI components wiring the Paperclip plugin to all Phase 36 sidecar endpoints: terminal I/O via WebSocket stream bridge, app lifecycle controls, tools/skills listing, and settings management.

## What Was Built

### Task 1: Worker Handlers (529c1be)

Added 9 new handlers to `worker.ts`:

**Data handlers** (3):
- `tools-skills` — fetches tools and skills in parallel via `Promise.all([client.getTools(), client.getSkills()])`
- `apps-list` — fetches sandboxed apps via `client.getApps()`
- `agent42-settings` — fetches masked API key config via `client.getSettings()`

**Action handlers** (5):
- `app-start` — calls `client.startApp(appId)` with graceful error return
- `app-stop` — calls `client.stopApp(appId)` with graceful error return
- `update-agent42-settings` — calls `client.updateSettings({key_name, value})`
- `terminal-start` — establishes authenticated WebSocket to sidecar `/ws/terminal`, emits `terminal-output` events via `ctx.streams.emit`
- `terminal-input` — sends data to active WebSocket session
- `terminal-close` — explicitly closes WebSocket and removes from session Map (Pitfall 4: PTY leak prevention)

**Stream channel** (1):
- `terminal-output` — pushed via `ctx.streams.emit` from WebSocket message/error/close handlers

Module-level `terminalSessions = new Map<string, WebSocket>()` tracks active sessions by sessionId.

### Task 2: UI Components (f2fd7c7)

Five new React components following the existing `ProviderHealthWidget` patterns (inline styles, loading/error/empty states, hook-based data fetching):

| Component | Prop Type | Hook Pattern | Feature |
|-----------|-----------|--------------|---------|
| `WorkspacePage` | `PluginPageProps` | `usePluginStream` + `usePluginAction` | Terminal I/O (PAPERCLIP-01) |
| `AppsPage` | `PluginPageProps` | `usePluginData` + `usePluginAction` | App lifecycle (PAPERCLIP-02) |
| `ToolsSkillsTab` | `PluginDetailTabProps` | `usePluginData` | Tools/skills list (PAPERCLIP-03) |
| `SettingsPage` | `PluginSettingsPageProps` | `usePluginData` + `usePluginAction` | API key mgmt (PAPERCLIP-04) |
| `WorkspaceNavEntry` | `PluginSidebarProps` | — | Sidebar nav (D-05) |

`index.tsx` updated from 4 to 9 exports. Plugin build produces updated `dist/` artifacts.

## Verification Results

- `npx tsc --noEmit`: PASS (0 errors)
- `npm run build`: PASS ("UI build complete -> dist/ui/")
- All 9 handlers registered in `worker.ts`
- All 5 component files created, all matching manifest `exportName` values from Plan 01
- `index.tsx` has 9 exports

## Deviations from Plan

### Auto-fixed Issues

None — plan executed exactly as written.

### Additional Commit

**[Rule 3 - Blocking] Committed updated dist/ artifacts**
- Found during: Post-task verification
- Issue: Build produced updated and new dist files (manifest.d.ts, manifest.js, worker-launcher.cjs) that were untracked; repo tracks dist/
- Fix: Added dist/ artifacts to Task 2 scope and committed (2266a84)
- Files modified: `plugins/agent42-paperclip/dist/` (12 files)

## Known Stubs

None — all components fetch real data via their respective worker handlers. WorkspaceNavEntry link paths use the SDK README pattern and may need host-specific adjustment at Paperclip integration time, but this is documented as D-14 progressive enhancement in the plan (not a blocking stub).

## Self-Check: PASSED

Files created:
- `plugins/agent42-paperclip/src/ui/WorkspacePage.tsx` — FOUND
- `plugins/agent42-paperclip/src/ui/AppsPage.tsx` — FOUND
- `plugins/agent42-paperclip/src/ui/ToolsSkillsTab.tsx` — FOUND
- `plugins/agent42-paperclip/src/ui/SettingsPage.tsx` — FOUND
- `plugins/agent42-paperclip/src/ui/WorkspaceNavEntry.tsx` — FOUND

Commits verified:
- 529c1be — FOUND
- f2fd7c7 — FOUND
- 2266a84 — FOUND
