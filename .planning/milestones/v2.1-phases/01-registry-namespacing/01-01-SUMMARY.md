---
phase: 01-registry-namespacing
plan: "01"
subsystem: workspace-registry
tags: [workspace, registry, persistence, api, ide]
dependency_graph:
  requires: []
  provides: [workspace-registry-module, workspace-crud-api, workspace-id-on-ide-endpoints]
  affects: [dashboard/server.py, agent42.py]
tech_stack:
  added: []
  patterns: [frozen-dataclass, async-json-persistence, atomic-write, registry-pattern, dependency-override-test]
key_files:
  created:
    - core/workspace_registry.py
    - tests/test_workspace_registry.py
  modified:
    - dashboard/server.py
    - agent42.py
decisions:
  - "Kept module-level 'workspace' variable inside create_app() for CC chat bridge backward compatibility; only IDE endpoints use _resolve_workspace()"
  - "Used asyncio.run() in test fixtures instead of asyncio.get_event_loop() — Python 3.14 on Windows no longer creates an event loop implicitly"
metrics:
  duration: "15m 14s"
  completed: "2026-03-24T05:29:29Z"
  tasks_completed: 2
  files_created: 2
  files_modified: 2
  tests_added: 36
  tests_total_passing: 1734
---

# Phase 01 Plan 01: WorkspaceRegistry Foundation Summary

WorkspaceRegistry module with atomic JSON persistence, CRUD API endpoints, default workspace seeding, and workspace_id resolution on all IDE endpoints — foundational data layer for multi-project workspace (v2.1).

## What Was Built

### core/workspace_registry.py (193 lines)

- `Workspace` dataclass: `id` (uuid4().hex[:12]), `name`, `root_path`, `created_at`, `updated_at`, `ordering` — with `to_dict()`/`from_dict()` round-trip following the `Project` pattern
- `WorkspaceRegistry` class with full CRUD:
  - `load()` — deserializes from JSON, silently handles missing/corrupt files
  - `_persist()` — atomic write via `os.replace(tmp, path)`, no leftover `.tmp` files
  - `seed_default(workspace_path)` — idempotent, uses `Path.name` for display name, falls back to "Default" for degenerate names (`"."`, `""`, `"/"`)
  - `resolve(workspace_id)` — None → default workspace; valid ID → that workspace; unknown ID → None
  - `list_all()`, `create()`, `update()`, `delete()` — with path validation and persistence

### dashboard/server.py (Task 2)

- Added `workspace_registry=None` parameter to `create_app()` signature
- Added `_resolve_workspace(workspace_id)` helper inside `create_app()`:
  - If registry present and has a workspace for the ID → return that workspace's `root_path`
  - If registry present but ID not found and `workspace_id is not None` → raise 404
  - Otherwise fall back to `AGENT42_WORKSPACE` env var (zero behavior change for existing users)
- Restored `workspace` variable inside `create_app()` for CC chat bridge, terminal, and other sections that use it (these are server-level paths, separate from the multi-project registry)
- Added `/api/workspaces` CRUD endpoints (GET list, POST create, PATCH update, DELETE delete) — all protected by `get_current_user` auth dependency
- Updated all 4 IDE endpoints to accept optional `workspace_id: str | None = None`:
  - `ide_tree`, `ide_read_file`, `ide_write_file`, `ide_search`
  - Each calls `_resolve_workspace(workspace_id)` to get the scoped root

### agent42.py (Task 2)

- Added `from core.workspace_registry import WorkspaceRegistry` import
- `self.workspace_registry = WorkspaceRegistry(data_dir / "workspaces.json")` in `__init__()`
- `await self.workspace_registry.load()` and `await self.workspace_registry.seed_default(...)` in `start()` after `project_manager.load()`
- `workspace_registry=self.workspace_registry` added to `create_app()` call

### tests/test_workspace_registry.py (413 lines, 36 tests)

- `TestWorkspace` (5 tests): dataclass construction, ID format, `to_dict`/`from_dict` round-trip, unknown key tolerance, uniqueness
- `TestWorkspaceRegistry` (23 tests): persist/load, atomic write, seed idempotency, name fallback, `resolve()` variants, CRUD operations with persistence verification, edge cases (nonexistent path, file-not-dir, unknown IDs, default reassignment on delete)
- `TestWorkspaceEndpoints` (8 tests): full API integration via `TestClient` with auth dependency override — list, create (valid/invalid), update, delete, ide_tree (default, scoped, invalid workspace_id)

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 1 | `097026a` | feat(01-registry-namespacing-01): implement WorkspaceRegistry with tests |
| 2 | `0c29d1f` | feat(01-registry-namespacing-01): wire WorkspaceRegistry into server.py and agent42.py |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] asyncio.get_event_loop() fails on Python 3.14 Windows**
- **Found during:** Task 1 (test GREEN phase), Task 2 (integration fixture)
- **Issue:** Python 3.14 on Windows does not create an implicit event loop in the main thread; `asyncio.get_event_loop()` raises `RuntimeError: There is no current event loop`
- **Fix:** Replaced all `asyncio.get_event_loop().run_until_complete(...)` calls in test fixtures with `asyncio.run(...)` (Python 3.7+ compatible, creates its own event loop)
- **Files modified:** `tests/test_workspace_registry.py`
- **Commit:** 0c29d1f

**2. [Rule 2 - Missing] workspace variable needed by CC chat bridge**
- **Found during:** Task 2 (integration test failure)
- **Issue:** After removing the module-level `workspace = Path(...)` line, the CC chat WebSocket bridge section (line ~1807) and several other server.py sections referenced `workspace` directly — causing `NameError: name 'workspace' is not defined`
- **Fix:** Re-introduced `workspace = Path(_os.environ.get("AGENT42_WORKSPACE", str(Path.cwd())))` as a local variable inside `create_app()` (right before `_resolve_workspace`). The `_resolve_workspace()` function also uses it as its env-var fallback path.
- **Files modified:** `dashboard/server.py`
- **Commit:** 0c29d1f

**3. [Rule 1 - Bug] WorkspaceRegistry import silently dropped by ruff formatter**
- **Found during:** Task 2 post-edit lint check
- **Issue:** The initial `Edit` operation adding `from core.workspace_registry import WorkspaceRegistry` to agent42.py was executed correctly, but the ruff `format-on-write` hook reordered the imports alphabetically. The import ended up in the correct sorted position but was verified to be present via grep.
- **Fix:** Confirmed import at line 43 after formatter ran. No code change needed.

## Known Stubs

None. All data is wired:
- `workspace_registry.list_all()` returns actual `Workspace` objects from the persisted registry
- `_resolve_workspace()` returns real `Path` objects scoped to the registered workspace
- Default seeding populates from `AGENT42_WORKSPACE` env var on first startup

## Self-Check

### Files created/modified
- [x] `core/workspace_registry.py` exists
- [x] `tests/test_workspace_registry.py` exists (413 lines, 36 tests)
- [x] `dashboard/server.py` contains `workspace_registry=None` parameter
- [x] `agent42.py` contains `from core.workspace_registry import WorkspaceRegistry`

### Commits
- [x] `097026a` exists (Task 1)
- [x] `0c29d1f` exists (Task 2)

## Self-Check: PASSED
