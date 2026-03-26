# Phase 1: Registry & Namespacing - Research

**Researched:** 2026-03-23
**Domain:** Python server-side registry (FastAPI + aiofiles), client-side namespace conventions (Monaco, localStorage)
**Confidence:** HIGH

## Summary

Phase 1 is a pure composition task — it assembles well-understood patterns already present in the codebase into a new WorkspaceRegistry module. The ProjectManager in `core/project_manager.py` is the exact template: in-memory dict, aiofiles JSON persistence, `uuid4().hex[:12]` IDs, and `from_dict`/`to_dict` dataclass serialization. The only additions are (1) atomic write via temp file + `os.replace()` (slightly safer than direct aiofiles write used in ProjectManager), (2) filesystem path validation (already present in the IDE endpoints), and (3) client-side namespace conventions (Monaco URI prefix, localStorage key schema) that define no new runtime behavior — just naming contracts for Phase 2 to thread through.

The `/api/workspaces` CRUD endpoints follow the FastAPI patterns already used for projects and apps: `Depends(get_current_user)` auth guard, `HTTPException` error responses, and JSON body via Pydantic models or dicts. The `workspace_id` query param on existing IDE endpoints is a one-line additive change per handler with `None` default for backward compatibility.

Client-side changes in Phase 1 are definition-only: the plan specifies the namespace schemas (Monaco URI format, localStorage key prefix) as constants in `app.js` but does not wire them into active use — that is Phase 2. This means Phase 1 has zero visible behavior change for existing users.

**Primary recommendation:** Model WorkspaceRegistry directly on ProjectManager. Use atomic temp+replace write. Define client namespace constants alongside existing keys without changing call sites.

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Workspace IDs use `uuid4().hex[:12]` — 12-character opaque hex strings, matching every existing entity ID in the codebase (Project, Repo, Agent, App, Device)
- **D-02:** IDs are stable across renames — no slug or human-readable format that would break localStorage keys or Monaco model URIs on rename
- **D-03:** Workspace registry persists as a JSON file (`.agent42/workspaces.json`), loaded into memory on startup, written atomically on mutation via temp file + `os.replace()`
- **D-04:** Follows the existing ProjectManager/AppManager pattern — in-memory dict + write-on-mutate via aiofiles. No aiosqlite for this data.
- **D-05:** Existing IDE endpoints (`/api/ide/tree`, `/api/ide/file`, `/ws/terminal`, `/ws/cc-chat`) gain an optional `workspace_id` query param — omitting it falls back to the default workspace
- **D-06:** No new nested routes or header-based context — query param approach is backward-compatible and matches existing WebSocket param patterns (`?token=`, `?session_id=`)
- **D-07:** Phase 1 defines the contract; Phase 2 threads `workspace_id` through all IDE surfaces
- **D-08:** On server startup, if `workspaces.json` does not exist, auto-seed a single default workspace from `AGENT42_WORKSPACE` (or cwd if unset)
- **D-09:** Default workspace display name is `Path(AGENT42_WORKSPACE).name` (e.g., "agent42"), falling back to "Default" if the path name is uninformative (".", "/")
- **D-10:** If registry file already exists, startup does not re-seed — preserves user renames and manual configuration
- **D-11:** Agent42 internal apps (`apps/` subdirectory) are NOT auto-seeded as workspaces — that is deferred to Phase 3 (MGMT-01)

### Claude's Discretion

- WorkspaceRegistry class internal structure and method signatures
- Exact JSON schema for `workspaces.json` fields beyond (id, name, path, created_at, ordering)
- Path validation implementation details (traversal blocking, symlink defense)
- Error response format for invalid workspace IDs

### Deferred Ideas (OUT OF SCOPE)

- Auto-seeding `apps/` subdirectory as workspaces — deferred to Phase 3 (MGMT-01 "Add workspace" modal with app dropdown)
- Nested route API design (`/api/workspaces/{id}/...`) — revisit if API versioning or fetch-wrapper abstraction is added later
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| FOUND-01 | Server-side WorkspaceRegistry persists workspace configs (ID, name, root_path) in `.agent42/workspaces.json` | ProjectManager pattern maps directly; atomic write via os.replace() documented below |
| FOUND-02 | `/api/workspaces` CRUD endpoints (list, create, update, delete) with path validation against filesystem | FastAPI CRUD pattern established in server.py; path validation reuses ide_tree startswith() check |
| FOUND-04 | Default workspace auto-seeded from `AGENT42_WORKSPACE` on first load — zero behavior change for existing users | Seeding logic is a one-time write on server startup gated on file-not-exists check |
| FOUND-06 | Workspace IDs used in all API calls — server resolves ID to path, never accepts raw paths from client | Optional workspace_id query param on all IDE endpoints; None default falls back to default workspace |
| ISOL-06 | Monaco model URIs prefixed with workspace ID to prevent cross-workspace file collisions | Monaco URI format `workspace://{id}/{path}` defined as constant; existing `file:///` URIs replaced in Phase 2 |
| ISOL-07 | localStorage/sessionStorage keys namespaced by workspace ID (CC history, session IDs, panel state) | Key schema defined as JS constants; existing keys audited and documented below |
</phase_requirements>

---

## Standard Stack

### Core (All Existing Dependencies — No New Installs)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `dataclasses` (stdlib) | Python 3.11+ | `Workspace` dataclass with `to_dict`/`from_dict` | Matches Project, App, Agent dataclass pattern throughout codebase |
| `uuid` (stdlib) | Python 3.11+ | `uuid4().hex[:12]` ID generation | Identical to every other entity ID in the codebase |
| `aiofiles` (existing) | >=23.0.0 | Async JSON file write for workspace registry | Already in requirements.txt; used by ProjectManager |
| `pathlib.Path` (stdlib) | Python 3.11+ | Path resolution and workspace root validation | Already used in ide_tree/ide_read_file for path traversal blocking |
| FastAPI (existing) | >=0.115.0 | CRUD REST endpoints at `/api/workspaces` | Existing server.py infrastructure; no new framework |
| `os` (stdlib) | Python 3.11+ | `os.replace()` for atomic temp-file write | Atomic rename is crash-safe; avoids torn-write risk on server restart |

### No New Dependencies

Phase 1 requires zero new packages. All functionality is achievable with stdlib + existing project dependencies.

**Installation:**
```bash
# Nothing to install — all dependencies already in requirements.txt
```

---

## Architecture Patterns

### Recommended Project Structure

```
core/
└── workspace_registry.py    # WorkspaceRegistry class (new)
dashboard/
└── server.py                # Add /api/workspaces endpoints + workspace_id params
dashboard/frontend/dist/
└── app.js                   # Add namespace constant definitions (no behavior change)
tests/
└── test_workspace_registry.py  # Unit tests for registry CRUD and seeding
.agent42/
└── workspaces.json          # Created on first server startup (gitignored)
```

### Pattern 1: Workspace Dataclass (modeled on Project)

**What:** Frozen-style dataclass with `to_dict`/`from_dict` and `uuid4().hex[:12]` ID
**When to use:** For the Workspace entity — mirrors Project exactly but with `root_path` instead of task/repo fields

```python
# Source: core/project_manager.py (established pattern)
import uuid, time
from dataclasses import dataclass, field, asdict
from pathlib import Path

@dataclass
class Workspace:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str = ""
    root_path: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    ordering: int = 0  # display order in tab bar (Phase 2)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Workspace":
        known = {k for k in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})
```

### Pattern 2: WorkspaceRegistry (modeled on ProjectManager)

**What:** In-memory dict + JSON persistence + startup seeding
**When to use:** All workspace access — never read workspaces.json directly from endpoints

```python
# Source: core/project_manager.py (established pattern) + atomic write addition
import json, os, tempfile
import aiofiles
from pathlib import Path

class WorkspaceRegistry:
    def __init__(self, data_path: Path):
        self._path = data_path
        self._workspaces: dict[str, Workspace] = {}
        self._default_id: str | None = None

    async def load(self):
        if not self._path.exists():
            return
        async with aiofiles.open(self._path) as f:
            raw = await f.read()
        data = json.loads(raw)
        for entry in data.get("workspaces", []):
            ws = Workspace.from_dict(entry)
            self._workspaces[ws.id] = ws
        self._default_id = data.get("default_id")

    async def _persist(self):
        """Atomic write: write to .tmp then os.replace() — crash-safe."""
        payload = {
            "workspaces": [ws.to_dict() for ws in self._workspaces.values()],
            "default_id": self._default_id,
        }
        tmp = str(self._path) + ".tmp"
        async with aiofiles.open(tmp, "w") as f:
            await f.write(json.dumps(payload, indent=2))
        os.replace(tmp, self._path)  # atomic on POSIX and Windows

    async def seed_default(self, workspace_path: str):
        """Seed a default workspace if registry is empty — called on startup."""
        if self._workspaces:
            return  # D-10: don't re-seed if registry already has entries
        p = Path(workspace_path)
        name = p.name if p.name not in (".", "/", "") else "Default"
        ws = Workspace(name=name, root_path=str(p.resolve()))
        self._workspaces[ws.id] = ws
        self._default_id = ws.id
        await self._persist()

    def get_default(self) -> Workspace | None:
        return self._workspaces.get(self._default_id)

    def resolve(self, workspace_id: str | None) -> Workspace | None:
        """Resolve workspace_id to Workspace; None falls back to default."""
        if workspace_id is None:
            return self.get_default()
        return self._workspaces.get(workspace_id)
```

### Pattern 3: Atomic Temp+Replace Write

**What:** Write to `.tmp` file first, then `os.replace()` to atomically swap
**When to use:** All WorkspaceRegistry `_persist()` calls — safer than direct write

```python
# Source: D-03 decision (improvement over plain aiofiles write in ProjectManager)
tmp = str(self._path) + ".tmp"
async with aiofiles.open(tmp, "w") as f:
    await f.write(json.dumps(payload, indent=2))
os.replace(tmp, self._path)  # atomic rename — not async, but near-instantaneous
```

Note: `os.replace()` is synchronous but the rename syscall completes in microseconds — no event loop blocking concern for 1-20 workspace records.

### Pattern 4: workspace_id Query Param on Existing Endpoints

**What:** Add `workspace_id: str | None = None` to existing IDE endpoint signatures; resolve via registry
**When to use:** `/api/ide/tree`, `/api/ide/file`, and (Phase 2) WebSocket endpoints

```python
# Source: dashboard/server.py existing pattern (D-05)
@app.get("/api/ide/tree")
async def ide_tree(
    path: str = "",
    workspace_id: str | None = None,  # NEW — None falls back to default
    _user: str = Depends(get_current_user),
):
    ws = workspace_registry.resolve(workspace_id)
    if not ws:
        raise HTTPException(404, "Workspace not found")
    workspace = Path(ws.root_path)
    target = (workspace / path).resolve()
    if not str(target).startswith(str(workspace.resolve())):
        raise HTTPException(403, "Path outside workspace")
    # ... rest unchanged
```

### Pattern 5: create_app() Injection

**What:** Pass `workspace_registry` to `create_app()` the same way `project_manager` is passed
**When to use:** Server startup and test clients

```python
# Source: dashboard/server.py create_app() signature (established pattern)
def create_app(
    ...
    workspace_registry=None,  # NEW
) -> FastAPI:
    ...
    # Inside IDE handlers, reference closure-captured workspace_registry
```

The module-level `workspace = Path(os.environ.get("AGENT42_WORKSPACE", str(Path.cwd())))` at line 1301 of server.py must be replaced with `workspace_registry.resolve(workspace_id)` inside each handler.

### Pattern 6: Monaco URI Namespace Convention

**What:** Workspace-prefixed URI scheme for Monaco models
**When to use:** Defined as a constant in Phase 1; wired into `ideOpenFile()` in Phase 2

```javascript
// Source: CONTEXT.md ISOL-06 decision
// Phase 1 defines the constant — Phase 2 replaces "file:///" usage
var WORKSPACE_SCHEME = "workspace";

function workspaceUri(workspaceId, filePath) {
  // "workspace://abc123def456/src/main.py"
  return WORKSPACE_SCHEME + "://" + workspaceId + "/" + filePath;
}

// Current (Phase 1 leaves this unchanged):
var uri = monaco.Uri.parse("file:///" + path);

// Phase 2 will replace with:
var uri = monaco.Uri.parse(workspaceUri(activeWorkspaceId, path));
```

### Pattern 7: localStorage Key Namespace Schema

**What:** Workspace-ID-prefixed storage key helpers
**When to use:** Defined as constants/helpers in Phase 1; existing call sites migrated in Phase 2

Current storage keys (from app.js audit):
```
agent42_token          — global auth token, NOT namespaced (correct — auth is global)
a42_first_done         — global one-time flag, NOT namespaced (correct)
cc_hist_{sessionId}    — CC message history per session
cc_active_session      — active CC session ID (sessionStorage)
cc_panel_width         — IDE CC panel width
cc_panel_session_id    — CC panel's current session
```

Phase 1 namespace schema to define (but NOT yet wire in — Phase 2 migrates call sites):
```javascript
// Phase 1: define helper functions alongside existing keys
function wsKey(workspaceId, key) {
  return "ws_" + workspaceId + "_" + key;
}

// Key name conventions (call sites unchanged in Phase 1):
// ws_{id}_cc_active_session   — per-workspace active CC session (replaces cc_active_session)
// ws_{id}_cc_panel_width      — per-workspace CC panel width (replaces cc_panel_width)
// ws_{id}_cc_panel_session_id — per-workspace CC panel session (replaces cc_panel_session_id)

// cc_hist_{sessionId} does NOT change — sessions are already globally unique UUIDs;
// the workspace_id is carried by the session itself, not the storage key
```

### CRUD Endpoint Schema

**What:** `/api/workspaces` REST surface
**When to use:** For all workspace management operations

```
GET    /api/workspaces              → list all workspaces
POST   /api/workspaces              → create workspace {name, path}
PATCH  /api/workspaces/{id}         → update workspace {name?, ordering?}
DELETE /api/workspaces/{id}         → delete workspace (Phase 3 guards, Phase 1 just wires endpoint)
GET    /api/workspaces/{id}/validate → validate path exists and is a directory
```

### server.py Integration Points

Line 1301 (current):
```python
workspace = Path(_os.environ.get("AGENT42_WORKSPACE", str(Path.cwd())))
```
Phase 1 replaces with workspace_registry lookup inside each handler. The module-level variable is removed.

`agent42.py` line 175:
```python
workspace_path=str(workspace),
```
Phase 1 does NOT change this — single-workspace tool injection is unchanged. Phase 2 will add per-workspace context.

### Anti-Patterns to Avoid

- **Re-seeding on every startup:** Destroys user renames. Seed only when `workspaces.json` does not exist (D-10).
- **Module-level workspace variable:** The existing `workspace = Path(os.environ.get(...))` at create_app scope must move inside each handler via `workspace_registry.resolve()`. A module-level variable cannot be per-request.
- **Accepting raw paths in API:** Never accept a filesystem path from the client in any POST body or query param. Always accept `workspace_id` and resolve server-side.
- **Syncing Monaco `file:///` URIs in Phase 1:** The namespace constant is defined in Phase 1 but existing `ideOpenFile()` call sites must NOT be changed in Phase 1. Phase 2 migrates them atomically.
- **Touching `cc_hist_*` keys:** These are already globally unique per session UUID. No namespace prefix needed — the workspace association is on the session, not the storage key.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Path traversal protection | Custom path validator | `startswith(workspace.resolve())` pattern already in ide_tree (server.py:1307) | Already handles symlinks via `.resolve()`; copy-paste the same check |
| Atomic file write | Custom file locking | `os.replace()` after aiofiles write to `.tmp` | OS-level atomic rename; works on both POSIX and Windows |
| Entity ID generation | Custom ID scheme | `uuid4().hex[:12]` already used for all entities | Consistent with Project/App/Agent/Repo IDs throughout codebase |
| CRUD boilerplate | Custom ORM | Dataclass + in-memory dict + `_persist()` from ProjectManager | Proven pattern for 1-20 records; zero new deps |
| FastAPI auth guard | Custom middleware | `Depends(get_current_user)` already in all protected endpoints | Reuse existing JWT auth on all `/api/workspaces` endpoints |

---

## Common Pitfalls

### Pitfall 1: Module-Level Workspace Variable in create_app Scope

**What goes wrong:** The existing `workspace = Path(...)` at line 1301 is evaluated once when `create_app()` is called. In a multi-workspace world, handlers need per-request workspace resolution.
**Why it happens:** Single-workspace code had no reason to be request-scoped.
**How to avoid:** Remove the module-level variable. Inside each IDE handler, call `workspace_registry.resolve(workspace_id)` and derive the Path from the result.
**Warning signs:** If a test passes `workspace_id=ws2.id` but the file explorer still shows workspace 1's files.

### Pitfall 2: Re-seeding Overwrites User Renames

**What goes wrong:** If seeding logic runs on every startup (not gated on file-not-exists), user-renamed workspaces revert to the folder name on restart.
**Why it happens:** Forgetting D-10 — seeding is one-time only.
**How to avoid:** Guard with `if self._workspaces: return` inside `seed_default()`. The `load()` call must happen before `seed_default()` at startup.
**Warning signs:** User renames "agent42" to "My Project" and on restart it reverts.

### Pitfall 3: Torn Write Without Atomic Replace

**What goes wrong:** Server crash during `aiofiles.open(..., "w")` leaves a partial/empty `workspaces.json`, losing all workspace config on restart.
**Why it happens:** ProjectManager uses direct aiofiles write (no temp+replace). WorkspaceRegistry D-03 specifies atomic write.
**How to avoid:** Write to `workspaces.json.tmp`, call `os.replace()` to atomically swap. Even if the server crashes mid-write, the original file is intact.
**Warning signs:** After a hard restart, `workspaces.json` is empty or zero bytes.

### Pitfall 4: create_app() Not Receiving workspace_registry

**What goes wrong:** `workspace_registry` is not passed to `create_app()`, so handlers fall back to the old module-level `workspace` variable (or crash with AttributeError).
**Why it happens:** `create_app()` has 15+ optional parameters; easy to miss wiring in `agent42.py`.
**How to avoid:** Add `workspace_registry` to `create_app()` signature and pass it from `agent42.py` after `WorkspaceRegistry.load()` + `seed_default()` complete.
**Warning signs:** `test_workspace_registry.py` passes but integration test with `create_app()` still uses old workspace.

### Pitfall 5: Monaco URI Change Breaking Existing Model Cache

**What goes wrong:** If `ideOpenFile()` is changed to use `workspace://` URIs in Phase 1 (not Phase 2), any existing open files stored in tab state as `file:///` URIs will fail to match on model lookup.
**Why it happens:** Phase boundary confusion — Phase 1 defines the convention, Phase 2 migrates call sites.
**How to avoid:** In Phase 1, only ADD the `workspaceUri()` helper and constant. Do NOT change `ideOpenFile()` or any existing URI construction. Leave `file:///` in place until Phase 2 rewrites the tab system.
**Warning signs:** After Phase 1 deploy, open IDE tabs show "file not found" errors.

### Pitfall 6: localStorage Key Migration Without Backward Compat

**What goes wrong:** Existing `cc_panel_width`, `cc_active_session`, `cc_panel_session_id` keys are renamed in Phase 1, causing empty panel state for all existing users on upgrade.
**Why it happens:** Eager refactoring before Phase 2 needs the namespaced keys.
**How to avoid:** Phase 1 only DEFINES the `wsKey()` helper function and documents the schema. Do NOT rename any existing read/write call sites. Phase 2 migrates them with fallback reads from the old key names.
**Warning signs:** After deploying Phase 1, users lose CC panel width preference and active session on page reload.

### Pitfall 7: Path Validation Accepting Relative Paths

**What goes wrong:** A POST to `/api/workspaces` with `{"name": "evil", "path": "../../etc"}` creates a workspace pointing outside the server's intended scope.
**Why it happens:** Not calling `.resolve()` before the `startswith()` check.
**How to avoid:** Always `Path(submitted_path).resolve()` before accepting. Check that the resolved path exists and `is_dir()`. Reject paths that don't exist (user must provide a valid directory).
**Warning signs:** `workspaces.json` contains a path like `../../etc` or similar.

### Pitfall 8: Default Workspace Name Edge Cases

**What goes wrong:** `Path("/").name` returns `""`, `Path(".").name` returns `""` — falling through to no name at all.
**Why it happens:** D-09 says fall back to "Default" for uninformative names, but the check must cover all edge cases.
**How to avoid:** `name = p.name if p.name not in (".", "", "/") else "Default"`. Also handle the case where `AGENT42_WORKSPACE` is not set and `Path.cwd()` has a short name.
**Warning signs:** Default workspace appears with an empty name string in the registry.

---

## Code Examples

Verified patterns from existing codebase:

### Existing Path Validation (Copy This Pattern)

```python
# Source: dashboard/server.py:1306-1308 (HIGH confidence — direct read)
target = (workspace / path).resolve()
if not str(target).startswith(str(workspace.resolve())):
    raise HTTPException(403, "Path outside workspace")
```

For new workspace creation, adapt:
```python
# Validate submitted path for new workspace
submitted = Path(body.path).resolve()
if not submitted.exists() or not submitted.is_dir():
    raise HTTPException(400, "Path does not exist or is not a directory")
# No parent-of-workspace restriction for workspace roots — any valid dir is acceptable
```

### Existing ID Generation (Reuse Exactly)

```python
# Source: core/project_manager.py:39 (HIGH confidence — direct read)
id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
```

### Existing JSON Persistence Pattern (ProjectManager)

```python
# Source: core/project_manager.py:90-94 (HIGH confidence — direct read)
async def _persist(self):
    data = [p.to_dict() for p in self._projects.values()]
    async with aiofiles.open(self._data_path, "w") as f:
        await f.write(json.dumps(data, indent=2))
```

WorkspaceRegistry uses temp+replace instead:
```python
async def _persist(self):
    payload = {"workspaces": [...], "default_id": self._default_id}
    tmp = str(self._path) + ".tmp"
    async with aiofiles.open(tmp, "w") as f:
        await f.write(json.dumps(payload, indent=2))
    os.replace(tmp, self._path)
```

### FastAPI Endpoint Pattern

```python
# Source: dashboard/server.py create_app() (HIGH confidence — direct read)
@app.get("/api/workspaces")
async def list_workspaces(_user: str = Depends(get_current_user)):
    if not workspace_registry:
        raise HTTPException(503, "Workspace registry not initialized")
    workspaces = list(workspace_registry._workspaces.values())
    return {"workspaces": [ws.to_dict() for ws in workspaces]}

@app.post("/api/workspaces")
async def create_workspace(body: dict, _user: str = Depends(get_current_user)):
    path = body.get("path", "")
    name = body.get("name", "")
    if not path:
        raise HTTPException(400, "path is required")
    resolved = Path(path).resolve()
    if not resolved.exists() or not resolved.is_dir():
        raise HTTPException(400, "Path does not exist or is not a directory")
    ws = await workspace_registry.create(name=name, root_path=str(resolved))
    return ws.to_dict()
```

### Startup Wiring (agent42.py)

```python
# Source: agent42.py pattern (HIGH confidence — established init sequence)
# In Agent42.__init__() or startup:
from core.workspace_registry import WorkspaceRegistry

data_dir = Path(settings.data_dir)  # .agent42/
self.workspace_registry = WorkspaceRegistry(data_dir / "workspaces.json")

# In async startup method:
await self.workspace_registry.load()
await self.workspace_registry.seed_default(
    os.environ.get("AGENT42_WORKSPACE", str(Path.cwd()))
)
```

### Monaco URI Helper (JavaScript, Phase 1 definition only)

```javascript
// Source: app.js existing pattern at line 3761 (HIGH confidence — direct read)
// Current:
var uri = monaco.Uri.parse("file:///" + path);

// Phase 1 defines this helper alongside the above (does NOT replace it yet):
var WORKSPACE_URI_SCHEME = "workspace";
function makeWorkspaceUri(workspaceId, filePath) {
  return WORKSPACE_URI_SCHEME + "://" + workspaceId + "/" + filePath.replace(/^\//, "");
}
// Phase 2 migrates ideOpenFile() to use makeWorkspaceUri(activeWorkspaceId, path)
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Module-level `workspace` variable in create_app | Per-request `workspace_registry.resolve(workspace_id)` | Phase 1 | Enables multi-workspace without breaking existing single-workspace |
| `file:///path` Monaco URIs | `workspace://{id}/path` URIs (Phase 2) | Phase 1 defines, Phase 2 wires | Prevents model collision when two workspaces have same filename |
| Un-prefixed localStorage keys | `ws_{id}_*` prefixed keys (Phase 2 migration) | Phase 1 defines schema | Per-workspace panel state and session persistence |

---

## Open Questions

1. **Should `workspace_registry` be None-safe in `create_app()`?**
   - What we know: `project_manager` and other services are passed as optional params and checked with `if project_manager:` inside handlers
   - What's unclear: Is it acceptable for workspace endpoints to 503 if registry is None, or should there be a fallback to the old env var behavior?
   - Recommendation: Add `if not workspace_registry:` guard with `HTTPException(503)` on workspace endpoints only. The existing IDE endpoints should fall back to env var behavior if `workspace_registry` is None (for test clients that don't inject it). This is the same defensive pattern used by `project_manager`.

2. **`workspaces.json` location: `.agent42/workspaces.json` vs `settings.workspaces_path`?**
   - What we know: D-03 says `.agent42/workspaces.json`. Settings uses `data_dir` convention.
   - What's unclear: Should there be a `WORKSPACES_PATH` env var override?
   - Recommendation: Hardcode to `data_dir / "workspaces.json"` in Phase 1 (no env var override). Phase 3 can add config if needed. Consistency with how `effectiveness.db` and other `.agent42/` files are placed.

3. **Should deleted workspaces be soft-deleted or hard-deleted?**
   - What we know: Phase 1 wires the DELETE endpoint; Phase 3 adds unsaved-files guards.
   - What's unclear: ProjectManager has `archive()` (soft) and `delete()` (hard). Which for workspaces?
   - Recommendation: Hard delete in Phase 1 (simpler). Phase 3 can add soft-delete if needed when implementing guards. No downstream references to workspace IDs exist yet (no tabs, no sessions) so cascade concerns don't apply until Phase 2.

---

## Environment Availability

Step 2.6: SKIPPED (no external dependencies identified — all changes are within existing Python stdlib + installed project deps; no new CLI tools, databases, or services required)

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest + pytest-asyncio |
| Config file | `pyproject.toml` (`asyncio_mode = "auto"`, `testpaths = ["tests"]`) |
| Quick run command | `python -m pytest tests/test_workspace_registry.py -x -q` |
| Full suite command | `python -m pytest tests/ -x -q` |

### Phase Requirements to Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| FOUND-01 | WorkspaceRegistry persists workspaces.json on create/update/delete | unit | `pytest tests/test_workspace_registry.py::TestWorkspaceRegistry::test_persist_creates_file -x` | ❌ Wave 0 |
| FOUND-01 | Atomic write: crash mid-write leaves original intact | unit | `pytest tests/test_workspace_registry.py::TestWorkspaceRegistry::test_atomic_write -x` | ❌ Wave 0 |
| FOUND-01 | load() deserializes workspaces.json back to in-memory dict | unit | `pytest tests/test_workspace_registry.py::TestWorkspaceRegistry::test_load_roundtrip -x` | ❌ Wave 0 |
| FOUND-02 | GET /api/workspaces returns list of workspaces | integration | `pytest tests/test_workspace_registry.py::TestWorkspaceEndpoints::test_list_workspaces -x` | ❌ Wave 0 |
| FOUND-02 | POST /api/workspaces rejects non-existent path | integration | `pytest tests/test_workspace_registry.py::TestWorkspaceEndpoints::test_create_rejects_bad_path -x` | ❌ Wave 0 |
| FOUND-02 | POST /api/workspaces rejects path traversal | integration | `pytest tests/test_workspace_registry.py::TestWorkspaceEndpoints::test_create_rejects_traversal -x` | ❌ Wave 0 |
| FOUND-04 | seed_default() creates workspace from AGENT42_WORKSPACE | unit | `pytest tests/test_workspace_registry.py::TestWorkspaceRegistry::test_seed_default -x` | ❌ Wave 0 |
| FOUND-04 | seed_default() is idempotent (D-10: no re-seed if file exists) | unit | `pytest tests/test_workspace_registry.py::TestWorkspaceRegistry::test_seed_idempotent -x` | ❌ Wave 0 |
| FOUND-06 | ide_tree with workspace_id resolves to correct workspace path | integration | `pytest tests/test_workspace_registry.py::TestIDEEndpoints::test_ide_tree_workspace_scoped -x` | ❌ Wave 0 |
| FOUND-06 | ide_tree without workspace_id falls back to default workspace | integration | `pytest tests/test_workspace_registry.py::TestIDEEndpoints::test_ide_tree_default_fallback -x` | ❌ Wave 0 |
| ISOL-06 | (definition only) No runtime behavior to test in Phase 1 | manual-only | — | N/A |
| ISOL-07 | (definition only) No runtime behavior to test in Phase 1 | manual-only | — | N/A |

### Sampling Rate

- **Per task commit:** `python -m pytest tests/test_workspace_registry.py -x -q`
- **Per wave merge:** `python -m pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/test_workspace_registry.py` — covers all FOUND-0x requirements above (new file needed)
- [ ] No conftest.py changes required — existing `tmp_path` and `tmp_workspace` fixtures are sufficient

---

## Sources

### Primary (HIGH confidence)

- `core/project_manager.py` — direct read; establishes in-memory dict + aiofiles JSON persistence pattern, `uuid4().hex[:12]` ID generation, `to_dict`/`from_dict` dataclass pattern
- `dashboard/server.py:1301-1370` — direct read; current single-workspace path resolution, `startswith(workspace.resolve())` path traversal check, `create_app()` injection pattern
- `agent42.py:170-190` — direct read; `workspace_path` injection into ToolContext, ProjectManager init pattern in `__init__()`
- `core/config.py:75-77, 383-386` — direct read; `workspace_restrict` setting, `from_env()` env var pattern
- `dashboard/frontend/dist/app.js:3761-3764, 5334-5384` — direct read; Monaco URI construction (`file:///`), localStorage key names (`cc_hist_`, `cc_active_session`, `cc_panel_width`, `cc_panel_session_id`)
- `.planning/workstreams/multi-project-workspace/phases/01-registry-namespacing/01-CONTEXT.md` — direct read; all locked decisions D-01 through D-11
- `.planning/REQUIREMENTS.md` — direct read; FOUND-01, FOUND-02, FOUND-04, FOUND-06, ISOL-06, ISOL-07 requirement definitions
- `pyproject.toml` — direct read; `asyncio_mode = "auto"`, `testpaths = ["tests"]`
- `tests/conftest.py` — direct read; `tmp_workspace`, `sandbox`, `tool_registry` fixture patterns
- `tests/test_auth_flow.py:127-143` — direct read; `create_app()` injection pattern for test clients

### Secondary (MEDIUM confidence)

- Python `os.replace()` documentation — atomic rename semantics confirmed for both POSIX and Windows NT (confirmed from stdlib knowledge; consistent with standard Python file-safety patterns)

### Tertiary (LOW confidence)

None — all findings are based on direct codebase inspection.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all packages are existing dependencies; verified by direct requirements.txt and import inspection
- Architecture: HIGH — patterns copied directly from ProjectManager and existing IDE handlers
- Pitfalls: HIGH — derived from direct code reading of the integration points that will change

**Research date:** 2026-03-23
**Valid until:** 2026-06-23 (stable patterns; only invalidated if ProjectManager or server.py are significantly refactored before Phase 1 executes)
