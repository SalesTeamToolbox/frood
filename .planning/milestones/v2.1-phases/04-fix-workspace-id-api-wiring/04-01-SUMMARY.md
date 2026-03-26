---
phase: 04-fix-workspace-id-api-wiring
plan: "01"
subsystem: ide-api
tags: [workspace, api-wiring, bug-fix, gap-closure]
dependency_graph:
  requires: [Phase 01 WorkspaceRegistry, Phase 02 IDE Surface Integration]
  provides: [correct workspace_id routing for file save and search]
  affects: [dashboard/server.py IDEWriteRequest, dashboard/frontend/dist/app.js ideDoSearch]
tech_stack:
  added: []
  patterns: [Pydantic request body field, query param URL construction]
key_files:
  created: [tests/test_ide_workspace.py (new test classes)]
  modified:
    - dashboard/server.py
    - dashboard/frontend/dist/app.js
    - tests/test_ide_workspace.py
decisions:
  - "workspace_id moved from standalone FastAPI query param into IDEWriteRequest Pydantic model body field — aligns with how frontend sends it via JSON body"
  - "ideDoSearch builds searchUrl variable before fetch, appending workspace_id only when _activeWorkspaceId is set — matches established ideLoadTree pattern"
  - "Integration tests use sibling directories for workspace A and B, not nested — prevents workspace A search from finding files inside workspace B subdirectory"
metrics:
  duration: "12m"
  completed: "2026-03-25"
  tasks: 2
  files: 3
---

# Phase 04 Plan 01: Fix Workspace ID API Wiring Summary

**One-liner:** Fixed workspace_id Pydantic model mismatch on file save and missing workspace_id query param on search, with integration tests proving both flows route to the correct non-default workspace.

## What Was Built

Two workspace_id API wiring gaps closed:

1. **File save (FLOW-01 — CRITICAL):** `IDEWriteRequest` Pydantic model now includes `workspace_id: str | None = None`. The `ide_write_file` function no longer accepts `workspace_id` as a standalone query parameter — it reads `req.workspace_id` from the JSON body instead. The frontend was already sending `workspace_id` in the JSON body; the server was silently ignoring it and always resolving to the default workspace.

2. **Search (FLOW-02 — MEDIUM):** `ideDoSearch` in `app.js` now builds a `searchUrl` variable and conditionally appends `workspace_id` as a query parameter when `_activeWorkspaceId` is set. This matches the established pattern used by `ideLoadTree` and `ideOpenFile`. The server-side `ide_search` endpoint already accepted `workspace_id` correctly.

3. **Tests:** Two new test classes added to `tests/test_ide_workspace.py`:
   - `TestIdeWriteFileWorkspaceWiring` — source-scan verifies model field and function signature; integration test POSTs to workspace B and asserts file appears in workspace B's directory only.
   - `TestIdeSearchWorkspaceWiring` — source-scan verifies `ideDoSearch` body contains `workspace_id`; integration test searches workspace B and confirms results come from workspace B only, not workspace A.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] WorkspaceRegistry method name mismatch**
- **Found during:** Task 1 integration test
- **Issue:** Plan instructed using `registry.add(name=..., root_path=...)` but `WorkspaceRegistry` has no `add` method — the correct method is `create(name, root_path)`
- **Fix:** Changed `registry.add(...)` to `registry.create(...)` in both test classes
- **Files modified:** tests/test_ide_workspace.py
- **Commit:** 4cbbf22

**2. [Rule 1 - Bug] registry.get_default() is synchronous, not async**
- **Found during:** Task 2 integration test
- **Issue:** Plan template suggested `asyncio.run(registry.get_default())` but `get_default()` is a synchronous method returning `Workspace` directly — calling with `asyncio.run()` raises `TypeError: An asyncio.Future, a coroutine or an awaitable is required`
- **Fix:** Changed to `default_ws = registry.get_default()` (no asyncio.run)
- **Files modified:** tests/test_ide_workspace.py
- **Commit:** 3ea69ee

**3. [Rule 1 - Bug] Workspace B nested inside Workspace A caused search result bleed**
- **Found during:** Task 2 integration test
- **Issue:** Creating workspace B at `tmp_path / "workspace_b"` when workspace A root is `tmp_path` means workspace A's recursive search finds files inside workspace B's subdirectory — integration test assertion that workspace A search returns 0 results failed
- **Fix:** Changed to use sibling directories: `ws_a_path = tmp_path / "workspace_a"` and `ws_b_path = tmp_path / "workspace_b"`, seeding default workspace as `ws_a_path` instead of `tmp_path`
- **Files modified:** tests/test_ide_workspace.py
- **Commit:** 3ea69ee

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 1 | 4cbbf22 | fix(04-01): add workspace_id to IDEWriteRequest Pydantic model |
| 2 | 3ea69ee | fix(04-01): append workspace_id to ideDoSearch search URL |

## Success Criteria Verification

- [x] FLOW-01 (CRITICAL) closed: File save in non-default workspace writes to correct workspace root — integration test POSTs with `workspace_id=B` and verifies file exists in `ws_b_path / "test.txt"` with `(tmp_path / "test.txt")` absent
- [x] FLOW-02 (MEDIUM) closed: Search in non-default workspace returns correct results — integration test creates `searchable.txt` in workspace B and confirms search with `workspace_id=B` finds it while `workspace_id=A` returns 0 results
- [x] FOUND-06 requirement fully satisfied: All IDE API calls (tree, file read, file write, search) correctly pass workspace_id
- [x] Full test suite passes: 15/15 tests in test_ide_workspace.py; no regressions in tests/ (pre-existing failure in test_app_git.py confirmed pre-existing, unrelated to this plan)

## Self-Check: PASSED

- dashboard/server.py modified: `grep -A3 "class IDEWriteRequest"` shows `workspace_id: str | None = None` field present
- dashboard/frontend/dist/app.js modified: `grep -n "workspace_id" ... | grep searchUrl` returns match at line 6337
- tests/test_ide_workspace.py modified: `TestIdeWriteFileWorkspaceWiring` and `TestIdeSearchWorkspaceWiring` classes present
- Commit 4cbbf22 exists in git log
- Commit 3ea69ee exists in git log
- All 15 tests pass: `python -m pytest tests/test_ide_workspace.py -x -q` exits 0
