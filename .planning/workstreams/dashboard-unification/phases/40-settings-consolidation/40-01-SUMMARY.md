---
phase: 40-settings-consolidation
plan: 01
status: complete
started: "2026-04-05T08:40:00Z"
completed: "2026-04-05T09:00:00Z"
---

# Plan 40-01 Summary: Backend Settings Infrastructure

## What was delivered

### Task 1: Source field, delete-on-empty, LEARNING_ENABLED config
- `core/sidecar_models.py` — Added `source: str = "none"` field to `SidecarSettingsKeyEntry` (D-07)
- `core/config.py` — Added `learning_enabled: bool = True` to Settings dataclass + `from_env()` (D-14)
- `dashboard/server.py` — Added `"LEARNING_ENABLED"` to `_DASHBOARD_EDITABLE_SETTINGS`
- `dashboard/sidecar.py` — `get_sidecar_settings()` passes `source=` from `get_masked_keys()`, `update_sidecar_settings()` calls `delete_key` on empty value (D-08)

### Task 2: Learning guards, memory purge, sidecar proxies, toggle endpoints, tests
- `core/memory_bridge.py` — `learn_async()` checks `settings.learning_enabled`, returns early when False
- `memory/effectiveness.py` — `drain_pending_transcripts()` checks `settings.learning_enabled`, returns `[]` when False
- `dashboard/server.py` — `DELETE /api/settings/memory/{collection}` with admin auth, validates against `{memory, knowledge, history}`
- `dashboard/sidecar.py` — 5 new endpoints:
  - `GET /memory-stats` — proxy memory operation counters
  - `GET /storage-status` — proxy storage config status + learning_enabled
  - `DELETE /memory/{collection}` — purge via sidecar
  - `PATCH /tools/{name}` — toggle tool enabled state
  - `PATCH /skills/{name}` — toggle skill enabled state
- `tests/test_settings_consolidation.py` — 11 tests all passing

## Commits

- `a978a8b` — feat(40-01): add source field to sidecar settings, learning_enabled config, delete-on-empty
- `772de1c` — feat(40-01): add learning guards, memory purge, sidecar proxies, tool/skill PATCH endpoints

## Decisions

- Local imports for `settings` in `learn_async()` and `drain_pending_transcripts()` per project convention (avoid circular imports)
- `SidecarToggleRequest(BaseModel)` defined inside sidecar factory function scope
- Server purge endpoint uses `app.state.qdrant_store` with fallback to `memory_store._qdrant`
- `asyncio.get_running_loop().run_in_executor()` for sync `clear_collection` call

## Files Modified

| File | Changes |
|------|---------|
| core/config.py | +learning_enabled field |
| core/sidecar_models.py | +source field |
| core/memory_bridge.py | +learning_enabled guard |
| memory/effectiveness.py | +learning_enabled guard |
| dashboard/server.py | +LEARNING_ENABLED editable, +purge endpoint |
| dashboard/sidecar.py | +source passthrough, +delete-on-empty, +5 new endpoints |
| tests/test_settings_consolidation.py | 11 tests (new file) |

## Metrics

- Tasks: 2/2 completed
- Files modified: 7
- Commits: 2
- Tests: 11/11 passing
