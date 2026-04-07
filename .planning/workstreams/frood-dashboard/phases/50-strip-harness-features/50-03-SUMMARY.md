---
phase: 50-strip-harness-features
plan: "03"
subsystem: dashboard-auth-launcher
tags: [auth, websocket, launcher, cleanup]
dependency_graph:
  requires: []
  provides: [jwt-only-auth, clean-websocket-manager, clean-launcher]
  affects: [dashboard/auth.py, dashboard/websocket_manager.py, dashboard/server.py, agent42.py]
tech_stack:
  added: []
  patterns: [JWT-only auth, simplified WebSocket connection tracking]
key_files:
  created: []
  modified:
    - dashboard/auth.py
    - dashboard/websocket_manager.py
    - dashboard/server.py
    - agent42.py
decisions:
  - JWT-only auth in auth.py — removed API_KEY_PREFIX branch, _validate_api_key(), init_device_store(), and DeviceStore dependency
  - Kept standalone param in create_app() — server.py standalone_guard decorator still uses it (not removed by Plan 01 yet)
  - Fixed server.py WebSocket handler — removed API_KEY_PREFIX import and device auth branch as an auto-fix (Rule 3) to unblock agent42 import
metrics:
  duration: "~12 minutes"
  completed: "2026-04-07"
  tasks_completed: 2
  files_modified: 4
---

# Phase 50 Plan 03: Simplify Auth, WebSocket Manager, and Launcher Summary

JWT-only auth with device code fully removed from auth.py, websocket_manager.py stripped of device identity fields, and agent42.py launcher cleaned of all harness module imports and create_app harness parameters.

## What Was Built

**Task 1 — Simplify auth.py to JWT-only and clean websocket_manager.py**

- `dashboard/auth.py`: Removed `DeviceStore` and `API_KEY_PREFIX` imports from `core.device_auth`. Removed `init_device_store()`, `_validate_api_key()`, `_device_store` global. Simplified `get_auth_context()`, `get_current_user_optional()`, and `require_admin()` to JWT-only paths. Removed `device_id` and `device_name` fields from `AuthContext` dataclass.
- `dashboard/websocket_manager.py`: Removed `device_id` and `device_name` fields from `WSConnection` dataclass. Removed `connected_device_ids()` method. Removed `send_to_device()` method. Simplified `connect()` to accept only `user` parameter.

**Task 2 — Update agent42.py launcher**

- `agent42.py`: Removed imports for `DeviceStore`, `ProjectManager`, `RepositoryManager`, `WorkspaceRegistry`, and `init_device_store`. Removed `self.device_store`, `self.repo_manager`, `self.project_manager`, `self.workspace_registry` initializations. Removed `repo_manager.load()`, `project_manager.load()`, `workspace_registry.load()` and `seed_default()` calls from `start()`. Removed `github_account_store` creation. Stripped harness params from `create_app()` call.

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 1 | cfbd88d | feat(50-03): simplify auth.py to JWT-only and clean websocket_manager.py |
| 2 | 527f181 | feat(50-03): update agent42.py launcher — remove harness imports and create_app params |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Fixed server.py API_KEY_PREFIX import and WebSocket device auth branch**
- **Found during:** Task 2 (import test `python -c "import agent42"` failed)
- **Issue:** `dashboard/server.py` still imported `API_KEY_PREFIX` from `dashboard.auth` and contained a device API key auth branch in the WebSocket handler at line 5680. After auth.py removed `API_KEY_PREFIX`, this caused an `ImportError` that blocked the import test acceptance criterion.
- **Fix:** Removed `API_KEY_PREFIX` from the server.py import block. Replaced the `if token.startswith(API_KEY_PREFIX):` branch with direct JWT auth. Simplified `ws_manager.connect()` call to pass only `user` (matching the cleaned WebSocketManager signature).
- **Files modified:** `dashboard/server.py`
- **Commit:** 527f181 (included in Task 2 commit)

**Note:** Three pre-existing F841 warnings in server.py (unused `max_tokens` and `temperature` variables at lines 3671, 3672, 3778) are outside the scope of this plan's changes and were not fixed. These are in unrelated route handlers.

## Known Stubs

None — no placeholder data or TODO stubs introduced.

## Self-Check: PASSED

All files confirmed present. Both task commits verified in git log.
