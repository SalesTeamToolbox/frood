---
phase: 37-standalone-dashboard
plan: "01"
status: complete
started: 2026-04-03T17:16:00Z
completed: 2026-04-03T17:35:00Z
---

# Plan 37-01 Summary: Backend Standalone Infrastructure

## What was built

Added `STANDALONE_MODE` runtime feature flag that gates ~56 non-essential dashboard routes in standalone mode. When active, only the 4 required feature areas (settings, tools/skills, agent monitoring, provider configuration) plus 6 retained operational features remain accessible.

## Tasks completed

| # | Task | Status | Commit |
|---|------|--------|--------|
| 1 | Config field, CLI flag, guard decorator, /health update | Done | 04aed31 |
| 2 | Apply guard to 56 routes, add tool source field | Done | ebe0254 |

## Key files

### Created
(none)

### Modified
- `core/config.py` — Added `standalone_mode: bool = False` field + `from_env()` parse
- `agent42.py` — Added `--standalone` CLI flag, pass to `create_app()`
- `dashboard/server.py` — `standalone_guard` decorator + applied to 56 gated routes + `/health` reports mode
- `tools/registry.py` — `list_tools()` returns `source: "builtin"` field

## Decisions made

- `.env.example` update deferred — security gate blocks edits to credential files. STANDALONE_MODE documentation needs manual addition.
- Guard decorator uses closure over `standalone` boolean parameter (not `settings.standalone_mode` directly) — follows the same pattern as `sidecar_enabled` gate

## Self-Check: PASSED

- [x] `standalone_mode` field exists on Settings dataclass
- [x] `from_env()` parses STANDALONE_MODE env var
- [x] `--standalone` CLI flag exists in agent42.py
- [x] `standalone_guard` decorator defined in create_app()
- [x] 56 routes have `@standalone_guard` applied
- [x] Retained routes (settings, tools, skills, agents, providers, etc.) NOT gated
- [x] `/health` reports `standalone_mode: true` when active
- [x] `list_tools()` includes `source` field
