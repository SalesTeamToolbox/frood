# Phase 1: Registry & Namespacing - Context

**Gathered:** 2026-03-23
**Status:** Ready for planning

<domain>
## Phase Boundary

Server-side WorkspaceRegistry with CRUD API, default seeding from AGENT42_WORKSPACE, ID-based path resolution, and client-side storage/URI namespace conventions (Monaco model URIs, localStorage keys). No UI tab bar or IDE surface integration — that is Phase 2.

</domain>

<decisions>
## Implementation Decisions

### Workspace Identity Scheme
- **D-01:** Workspace IDs use `uuid4().hex[:12]` — 12-character opaque hex strings, matching every existing entity ID in the codebase (Project, Repo, Agent, App, Device)
- **D-02:** IDs are stable across renames — no slug or human-readable format that would break localStorage keys or Monaco model URIs on rename

### Persistence Backend
- **D-03:** Workspace registry persists as a JSON file (`.agent42/workspaces.json`), loaded into memory on startup, written atomically on mutation via temp file + `os.replace()`
- **D-04:** Follows the existing ProjectManager/AppManager pattern — in-memory dict + write-on-mutate via aiofiles. No aiosqlite for this data.

### API Migration Path
- **D-05:** Existing IDE endpoints (`/api/ide/tree`, `/api/ide/file`, `/ws/terminal`, `/ws/cc-chat`) gain an optional `workspace_id` query param — omitting it falls back to the default workspace
- **D-06:** No new nested routes or header-based context — query param approach is backward-compatible and matches existing WebSocket param patterns (`?token=`, `?session_id=`)
- **D-07:** Phase 1 defines the contract; Phase 2 threads `workspace_id` through all IDE surfaces

### Default Workspace Seeding
- **D-08:** On server startup, if `workspaces.json` does not exist, auto-seed a single default workspace from `AGENT42_WORKSPACE` (or cwd if unset)
- **D-09:** Default workspace display name is `Path(AGENT42_WORKSPACE).name` (e.g., "agent42"), falling back to "Default" if the path name is uninformative (".", "/")
- **D-10:** If registry file already exists, startup does not re-seed — preserves user renames and manual configuration
- **D-11:** Agent42 internal apps (`apps/` subdirectory) are NOT auto-seeded as workspaces — that is deferred to Phase 3 (MGMT-01)

### Claude's Discretion
- WorkspaceRegistry class internal structure and method signatures
- Exact JSON schema for `workspaces.json` fields beyond (id, name, path, created_at, ordering)
- Path validation implementation details (traversal blocking, symlink defense)
- Error response format for invalid workspace IDs

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Workspace architecture
- `.planning/workstreams/multi-project-workspace/ROADMAP.md` — Phase 1 success criteria, plan breakdown, full milestone scope
- `.planning/workstreams/multi-project-workspace/STATE.md` — Prior research decisions (namespace isolation, Monaco model swapping, stale-while-revalidate)

### Existing patterns to follow
- `dashboard/server.py` §1301-1350 — Current single-workspace resolution, IDE tree/file endpoints, path validation pattern
- `core/config.py` §75-77, §383-386 — `workspace_restrict` setting, `WORKSPACE_RESTRICT` env var
- `agent42.py` §175 — `workspace_path` injection into tools

### Project context
- `.planning/PROJECT.md` — Core value, constraints, key decisions table

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `ProjectManager` pattern (in-memory dict + JSON file + aiofiles write): exact template for WorkspaceRegistry
- `uuid.uuid4().hex[:12]` ID generation: used across all entity types — reuse same approach
- Path validation in `ide_tree` ([server.py:1307](dashboard/server.py#L1307)): `startswith(workspace.resolve())` pattern to reuse per-workspace

### Established Patterns
- Frozen dataclass config (`core/config.py`): workspace settings should follow this pattern
- FastAPI query params with defaults: existing endpoints use `path: str = ""` — add `workspace_id: str = None` similarly
- WebSocket query params: terminal and CC chat already pass `?token=...&session_id=...`

### Integration Points
- `dashboard/server.py` line 1301: `workspace = Path(os.environ.get("AGENT42_WORKSPACE", str(Path.cwd())))` — replace with WorkspaceRegistry default lookup
- `agent42.py` line 175: `workspace_path=str(workspace)` — tool context injection point for multi-workspace
- `app.js` localStorage keys: `agent42_token`, `cc_hist_<sessionId>`, `cc_active_session` — need workspace prefix for Phase 2
- Monaco model URIs: need `workspace://{id}/path` convention defined in Phase 1

</code_context>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches following existing codebase patterns.

</specifics>

<deferred>
## Deferred Ideas

- Auto-seeding `apps/` subdirectory as workspaces — deferred to Phase 3 (MGMT-01 "Add workspace" modal with app dropdown)
- Nested route API design (`/api/workspaces/{id}/...`) — revisit if API versioning or fetch-wrapper abstraction is added later

</deferred>

---

*Phase: 01-registry-namespacing*
*Context gathered: 2026-03-23*
