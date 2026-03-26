---
phase: 01-registry-namespacing
verified: 2026-03-24T16:04:02Z
status: passed
score: 9/9 must-haves verified
re_verification: false
---

# Phase 1: Registry & Namespacing Verification Report

**Phase Goal:** The workspace data model is locked server-side and client-side — every IDE surface has a stable workspace_id to key against, raw paths never cross the API boundary, and existing single-workspace users see zero behavior change

**Verified:** 2026-03-24T16:04:02Z
**Status:** passed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | WorkspaceRegistry persists workspace configs to .agent42/workspaces.json and loads them back on startup | VERIFIED | `core/workspace_registry.py`: `_persist()` uses `aiofiles.open(tmp, "w")` + `os.replace(tmp, path)`. `load()` reads and deserializes JSON. `agent42.py:212-214` calls both on startup. |
| 2 | Server auto-seeds a default workspace from AGENT42_WORKSPACE on first startup with no existing registry file | VERIFIED | `seed_default()` at line 99 guards with `if self._workspaces: return` (idempotent). `agent42.py:213-215` calls `seed_default(os.environ.get("AGENT42_WORKSPACE", str(Path.cwd())))`. |
| 3 | Creating a workspace from a valid directory path succeeds; creating from a non-existent path returns an error | VERIFIED | `create()` validates `resolved.exists()` and `resolved.is_dir()`, raises `ValueError` on failure. POST `/api/workspaces` maps this to HTTP 400. 36 tests pass including `test_create_with_nonexistent_path_raises` and `test_create_workspace_rejects_bad_path`. |
| 4 | An IDE request scoped to workspace A never returns files from workspace B's directory | VERIFIED | `_resolve_workspace(workspace_id)` resolves the ID to a `Path` and returns it. All 4 IDE endpoints (`ide_tree`, `ide_read_file`, `ide_write_file`, `ide_search`) use `ws_root = _resolve_workspace(workspace_id)` and enforce `str(target).startswith(str(ws_root.resolve()))` path boundary check. An invalid ID raises HTTP 404. |
| 5 | Omitting workspace_id on IDE endpoints falls back to the default workspace — zero behavior change for existing users | VERIFIED | `_resolve_workspace(None)` calls `workspace_registry.resolve(None)` which returns `get_default()`. If registry is None (legacy mode), falls back to `workspace` local var (env var). `test_ide_tree_default_fallback` passes. |
| 6 | A JavaScript function makeWorkspaceUri(workspaceId, filePath) exists that produces workspace://{id}/{path} URIs | VERIFIED | `app.js:173-175`: `function makeWorkspaceUri(workspaceId, filePath) { return WORKSPACE_URI_SCHEME + "://" + workspaceId + "/" + filePath.replace(/^\//, ""); }` |
| 7 | A JavaScript function wsKey(workspaceId, key) exists that produces ws_{id}_{key} storage keys | VERIFIED | `app.js:184-186`: `function wsKey(workspaceId, key) { return "ws_" + workspaceId + "_" + key; }` |
| 8 | The WORKSPACE_URI_SCHEME constant is defined as 'workspace' | VERIFIED | `app.js:164`: `var WORKSPACE_URI_SCHEME = "workspace";` |
| 9 | Existing Monaco file:/// URIs and localStorage keys are NOT changed — definition only, no behavior change | VERIFIED | `app.js:3802` still contains `monaco.Uri.parse("file:///" + path)`. Lines 4854, 4858, 6383, 6403 still use original `cc_active_session`, `cc_panel_width` keys. No existing call sites were modified. |

**Score:** 9/9 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `core/workspace_registry.py` | Workspace dataclass + WorkspaceRegistry class with CRUD, persistence, seeding | VERIFIED | 193 lines. All required classes and methods present: `Workspace`, `WorkspaceRegistry`, `load`, `_persist`, `seed_default`, `get_default`, `resolve`, `list_all`, `create`, `update`, `delete`. Atomic write via `os.replace`. |
| `dashboard/server.py` | /api/workspaces CRUD endpoints + workspace_id param on IDE endpoints | VERIFIED | `workspace_registry=None` param at line 475. `_resolve_workspace()` at line 1355. All 4 IDE endpoints accept `workspace_id: str | None = None`. All 4 CRUD routes present: GET/POST `/api/workspaces`, PATCH/DELETE `/api/workspaces/{ws_id}`. |
| `agent42.py` | WorkspaceRegistry init, load, seed_default, and injection into create_app() | VERIFIED | Import at line 43. `self.workspace_registry = WorkspaceRegistry(...)` at line 175. `await self.workspace_registry.load()` at line 212. `await self.workspace_registry.seed_default(...)` at line 213. `workspace_registry=self.workspace_registry` at line 251. |
| `tests/test_workspace_registry.py` | Unit tests for registry CRUD/persistence/seeding + integration tests for API endpoints | VERIFIED | 413 lines, 36 test methods across 3 classes: `TestWorkspace` (5), `TestWorkspaceRegistry` (23), `TestWorkspaceEndpoints` (8). All 36 pass. |
| `dashboard/frontend/dist/app.js` | Workspace URI helper, storage key namespace helper, scheme constant | VERIFIED | `WORKSPACE_URI_SCHEME`, `makeWorkspaceUri()`, `wsKey()` all present. No existing code modified. |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `agent42.py` | `core/workspace_registry.py` | `import` + `WorkspaceRegistry()` init | WIRED | `from core.workspace_registry import WorkspaceRegistry` at line 43. `self.workspace_registry = WorkspaceRegistry(data_dir / "workspaces.json")` at line 175. |
| `agent42.py` | `dashboard/server.py` | `workspace_registry=` kwarg to `create_app()` | WIRED | `workspace_registry=self.workspace_registry` at line 251 of `agent42.py`. |
| `dashboard/server.py` | `core/workspace_registry.py` | `_resolve_workspace()` calls `workspace_registry.resolve(workspace_id)` | WIRED | `_resolve_workspace()` at line 1355 calls `workspace_registry.resolve(workspace_id)` and returns `Path(ws.root_path)`. Used by all 4 IDE endpoints. |
| `dashboard/frontend/dist/app.js` | Phase 2 plans | `makeWorkspaceUri()` and `wsKey()` defined for Phase 2 call sites | DEFINED (intentional) | Functions exist but are not called yet by production code paths — this is the explicit design for Plan 02: definition-only, Phase 2 wires the call sites. |

---

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|--------------|--------|--------------------|--------|
| `GET /api/workspaces` | `workspaces` list | `workspace_registry.list_all()` → `self._workspaces` dict → populated by `load()` or `seed_default()` from `workspaces.json` | Yes — reads JSON file on startup, falls back to seeding from env var | FLOWING |
| `GET /api/ide/tree` | `entries` list | `_resolve_workspace(workspace_id)` → real `Path` object → `target.iterdir()` | Yes — reads actual filesystem directory | FLOWING |
| `core/workspace_registry.py` | `_workspaces` dict | Populated by `load()` from `workspaces.json` or by `seed_default()` / `create()` | Yes — filesystem-backed | FLOWING |

Note: `app.js` helpers (`makeWorkspaceUri`, `wsKey`) are definition-only this phase. They are not yet called by any production code path — this is intentional per Plan 02 design. Level 4 does not apply until Phase 2 wires the call sites.

---

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| WorkspaceRegistry module imports and resolve(None) returns None on empty registry | `python -c "from core.workspace_registry import Workspace, WorkspaceRegistry; r = WorkspaceRegistry('/tmp/test.json'); print(r.resolve(None))"` | `None` | PASS |
| All 36 workspace registry tests pass | `python -m pytest tests/test_workspace_registry.py -x -q` | `36 passed, 16 warnings in 2.35s` | PASS |
| No regression in security/sandbox tests | `python -m pytest tests/test_workspace_registry.py tests/test_security.py tests/test_sandbox.py -q --tb=short` | `160 passed, 7 skipped, 26 warnings in 19.52s` | PASS |
| app.js namespace helpers exist and existing file:/// URI untouched | `grep -n "WORKSPACE_URI_SCHEME\|makeWorkspaceUri\|wsKey\|file:///"` in app.js | Lines 164, 173, 184, 3802 — all present | PASS |

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| FOUND-01 | 01-01-PLAN.md | Server-side WorkspaceRegistry persists workspace configs (ID, name, root_path) in `.agent42/workspaces.json` | SATISFIED | `core/workspace_registry.py` implements full persistence via `aiofiles` + `os.replace`. `agent42.py` wires `data_dir / "workspaces.json"` as the storage path. |
| FOUND-02 | 01-01-PLAN.md | `/api/workspaces` CRUD endpoints (list, create, update, delete) with path validation against filesystem | SATISFIED | GET, POST, PATCH, DELETE endpoints at `dashboard/server.py:1299-1344`. `create()` validates path exists and is a directory. POST endpoint maps `ValueError` to HTTP 400. |
| FOUND-04 | 01-01-PLAN.md | Default workspace auto-seeded from `AGENT42_WORKSPACE` on first load — zero behavior change for existing users | SATISFIED | `seed_default()` is idempotent (no-op if workspaces exist). `_resolve_workspace(None)` falls back to env var if registry has no default. `test_ide_tree_default_fallback` confirms zero behavior change. |
| FOUND-06 | 01-01-PLAN.md | Workspace IDs used in all API calls — server resolves ID to path, never accepts raw paths from client | SATISFIED | All 4 IDE endpoints accept `workspace_id: str | None = None` and resolve via `_resolve_workspace()`. The registry stores and returns paths; clients only ever send IDs. POST `/api/workspaces` is the registration endpoint where raw path is accepted exactly once to register a new workspace. |
| ISOL-06 | 01-02-PLAN.md | Monaco model URIs prefixed with workspace ID to prevent cross-workspace file collisions | SATISFIED (definition) | `WORKSPACE_URI_SCHEME = "workspace"` and `makeWorkspaceUri(workspaceId, filePath)` defined in `app.js:164-175`. Migration of call sites deferred to Phase 2 per plan design. |
| ISOL-07 | 01-02-PLAN.md | localStorage/sessionStorage keys namespaced by workspace ID (CC history, session IDs, panel state) | SATISFIED (definition) | `wsKey(workspaceId, key)` defined in `app.js:184-186` with documented key mapping. Namespacing commented for `cc_active_session`, `cc_panel_width`, `cc_panel_session_id`. Migration deferred to Phase 2 per plan design. |

**Orphaned requirements check:** No additional Phase 1 requirements appear in REQUIREMENTS.md traceability table beyond the 6 declared in the plan frontmatter.

**Note on ISOL-06/ISOL-07:** Both requirements say "prefixed/namespaced by workspace ID" — the plan explicitly scopes Phase 1 as definition-only and Phase 2 as the migration. The definitions are complete and correct. The call-site migration is intentionally deferred to Phase 2. This is the correct interpretation of the phase goal.

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| None | — | — | — | — |

No TODOs, FIXMEs, placeholder returns, or empty handlers found in the phase-modified files (`core/workspace_registry.py`, `tests/test_workspace_registry.py`, workspace sections of `dashboard/server.py`, `agent42.py`).

---

### Human Verification Required

None. All phase 1 goals are verifiable programmatically:

- Persistence is tested by the test suite
- API endpoints are exercised by `TestWorkspaceEndpoints`
- IDE endpoint scoping is confirmed by grep and `test_ide_tree_workspace_scoped`
- JS helpers are definition-only with no UI behavior this phase

---

### Gaps Summary

No gaps. All 9 observable truths are verified. All 6 requirements are satisfied. All 36 tests pass with no regressions in the broader test suite.

The phase goal is achieved: the workspace data model is locked server-side (`WorkspaceRegistry` with JSON persistence, CRUD endpoints, workspace_id on IDE endpoints) and client-side (URI scheme constant and namespace helpers defined). Existing single-workspace users see zero behavior change — the `_resolve_workspace(None)` fallback ensures backward compatibility.

---

_Verified: 2026-03-24T16:04:02Z_
_Verifier: Claude (gsd-verifier)_
