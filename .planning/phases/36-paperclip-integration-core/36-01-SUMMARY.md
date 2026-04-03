---
phase: 36-paperclip-integration-core
plan: 01
subsystem: paperclip-integration
tags: [typescript, fastapi, sidecar, manifest, paperclip, dashboard-gate]
completed: "2026-04-03T21:24:52Z"
duration_minutes: 8

dependency_graph:
  requires: []
  provides:
    - "TypeScript interfaces for tools, skills, apps, settings (types.ts)"
    - "HTTP client methods for sidecar endpoints (client.ts)"
    - "Manifest slot declarations for page, settingsPage, sidebar, detailTab (manifest.ts)"
    - "Sidecar REST endpoints GET /tools, GET /skills, GET /apps, POST /apps/{id}/start, POST /apps/{id}/stop, GET /settings, POST /settings (sidecar.py)"
    - "Conditional dashboard gate for Paperclip mode (server.py)"
  affects:
    - "plugins/agent42-paperclip/src/ui/index.tsx (Plan 02 adds exports for new slots)"
    - "dashboard/sidecar.py (future plans add more sidecar endpoints)"

tech_stack:
  added: []
  patterns:
    - "SDK capability gating: each new UI slot type requires corresponding capability string (ui.page.register, ui.sidebar.register)"
    - "Graceful degradation: all sidecar endpoints return empty lists when service object is None"
    - "Conditional route registration: dashboard gate uses if settings.sidecar_enabled: block"
    - "Linter-aware import management: add imports alongside the code that uses them in same Edit call"

key_files:
  created:
    - plugins/agent42-paperclip/src/manifest.ts
  modified:
    - plugins/agent42-paperclip/src/types.ts
    - plugins/agent42-paperclip/src/client.ts
    - core/sidecar_models.py
    - dashboard/sidecar.py
    - dashboard/server.py
    - agent42.py

decisions:
  - "settingsPage slot type does not require a separate capability (ui.settingsPage.register does not exist in PLUGIN_CAPABILITIES) — SDK covers it implicitly"
  - "AppManager passed as None for sidecar mode — it is only instantiated in the non-sidecar elif branch; graceful degradation handles this per CLAUDE.md"
  - "Post /settings uses local HTTPException import alias (_HTTPException) to avoid shadowing outer scope"

metrics:
  tasks_completed: 3
  tasks_total: 3
  commits: 3
  files_modified: 7
---

# Phase 36 Plan 01: Contracts, Endpoints, and Dashboard Gate Summary

TypeScript types, HTTP client methods, manifest slot declarations, sidecar REST endpoints, and conditional dashboard gate establishing the blueprint for Phase 36 Paperclip Integration Core.

## Commits

| Hash | Message |
|------|---------|
| 839240e | feat(36-01): add Phase 36 TS types, client methods, and manifest slots |
| df6f4cf | feat(36-01): add Phase 36 sidecar REST endpoints for tools, skills, apps, settings |
| b27de3b | feat(36-01): implement PAPERCLIP-05 conditional dashboard gate for sidecar mode |

## Tasks Completed

### Task 1: TypeScript types, client methods, and manifest slot declarations

Added to `plugins/agent42-paperclip/src/types.ts`:
- `ToolItem`, `ToolsListResponse`
- `SkillItem`, `SkillsListResponse`
- `AppItem`, `AppsListResponse`, `AppActionResponse`
- `SettingsKeyEntry`, `SettingsResponse`, `SettingsUpdateRequest`, `SettingsUpdateResponse`
- `TerminalSessionInfo`, `TerminalOutputEvent`

Added to `plugins/agent42-paperclip/src/client.ts`:
- `getTools()`, `getSkills()`, `getApps()`, `startApp()`, `stopApp()`, `getSettings()`, `updateSettings()`

Added to `plugins/agent42-paperclip/src/manifest.ts` (new file from existing dist):
- 5 new slots: `page/workspace-terminal`, `page/sandboxed-apps`, `detailTab/tools-skills`, `settingsPage/agent42-settings`, `sidebar/workspace-nav`
- 2 new capabilities: `ui.page.register`, `ui.sidebar.register`
- TypeScript compiles without errors

### Task 2: Sidecar REST endpoints for tools, skills, apps, and settings

Added to `core/sidecar_models.py`:
- `SidecarToolItem`, `SidecarToolsResponse`
- `SidecarSkillItem`, `SidecarSkillsResponse`
- `SidecarAppItem`, `SidecarAppsResponse`, `SidecarAppActionResponse`
- `SidecarSettingsKeyEntry`, `SidecarSettingsResponse`, `SidecarSettingsUpdateRequest`, `SidecarSettingsUpdateResponse`

Added to `dashboard/sidecar.py`:
- `create_sidecar_app()` now accepts `tool_registry`, `skill_loader`, `app_manager`, `key_store` kwargs
- 7 new endpoints: `GET /tools`, `GET /skills`, `GET /apps`, `POST /apps/{id}/start`, `POST /apps/{id}/stop`, `GET /settings`, `POST /settings`
- All endpoints gracefully return empty lists/403/503 when service objects are None

Updated `agent42.py`:
- Passes `tool_registry`, `skill_loader`, `key_store` to `create_sidecar_app()`; `app_manager=None` per graceful degradation

### Task 3: Conditional dashboard gate for Paperclip mode (PAPERCLIP-05)

Added to `dashboard/server.py`:
- Root route `/` returns 503 JSON with `paperclip_mode` status when `settings.sidecar_enabled=True`
- `/health` endpoint adds `mode: "paperclip_sidecar"` to response when `sidecar_enabled=True`
- Both changes are fully conditional — standalone mode (`sidecar_enabled=False`) is completely unaffected

## Deviations from Plan

### Auto-noted: Linter import management

**Found during:** Task 2
**Issue:** The ruff linter auto-removes imports on every PostToolUse hook call if the imported symbols are not yet used in the file body. Adding imports before the endpoint code caused them to be stripped.
**Fix:** Combined import additions with the endpoint code addition in a single Edit call so the imports are immediately referenced.
**Impact:** None — same end result, different sequence of edits.

### Noted: settingsPage capability not in SDK

**Found during:** Task 1
**Issue:** PLUGIN_CAPABILITIES array in `@paperclipai/shared` does not include `ui.settingsPage.register`. The `settingsPage` slot type exists in PLUGIN_UI_SLOT_TYPES but has no dedicated capability.
**Fix:** Did not add `ui.settingsPage.register` capability (it would cause a TypeScript type error). The plan's note to "add it if the SDK types show a separate capability" was the correct guard.
**Files modified:** manifest.ts (did not add non-existent capability)

## Known Stubs

None — all endpoints return live data from injected service objects, with empty-list fallbacks for when services are None. No hardcoded placeholder values in data paths.

## Self-Check: PASSED

All 7 key files exist. All 3 task commits (839240e, df6f4cf, b27de3b) are present in git log. TypeScript compiles without errors. Python imports resolve cleanly.
