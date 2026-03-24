# Phase 2: IDE Surface Integration - Context

**Gathered:** 2026-03-24 (auto mode)
**Status:** Ready for planning

<domain>
## Phase Boundary

Thread workspace_id into all IDE surfaces: file explorer, editor tabs, CC sessions, and terminals. Render the workspace tab bar. Switching the active tab instantly re-roots all surfaces to the selected workspace. No workspace management (add/remove/rename) — that is Phase 3.

</domain>

<decisions>
## Implementation Decisions

### Workspace Tab Bar
- **D-01:** Tab bar renders above the editor tab bar, inside the IDE page layout — clicking a tab switches all surfaces
- **D-02:** Active tab has a visual indicator (highlight/underline); inactive tabs are subdued
- **D-03:** Tab bar loads workspace list from `/api/workspaces` on page load, with stale-while-revalidate from localStorage
- **D-04:** Active workspace ID stored in `localStorage` under bare key `"active_workspace_id"` (global, not per-workspace — there is no workspace scope for "which workspace is active"). Persists across reloads.

### File Explorer Scoping
- **D-05:** File explorer calls `/api/ide/tree?workspace_id={activeId}` — re-roots to the active workspace folder on every tab switch
- **D-06:** Files from other workspaces are never visible in the tree — complete isolation per success criteria #2

### Editor Tab State
- **D-07:** Each workspace maintains its own editor tab list — `wsKey(workspaceId, "editor_tabs")` in localStorage
- **D-08:** On workspace switch: save current Monaco `saveViewState()` for each open tab, then restore the target workspace's tabs with `restoreViewState()` — cursor, scroll, selection all preserved
- **D-09:** Monaco model URIs use `makeWorkspaceUri(workspaceId, filePath)` — Phase 1 helper now wired into file open flow. Two workspaces can open the same filename without collision.

### CC Session Scoping
- **D-10:** CC sessions pass `workspace_id` via the `/ws/cc-chat?workspace_id={id}` query param — subprocess cwd set to workspace root
- **D-11:** CC session history filtered per workspace — only sessions started in the active workspace are shown in the sidebar
- **D-12:** The `cc_active_session` key becomes `wsKey(workspaceId, "cc_active_session")` — per-workspace active session tracking

### Terminal Session Scoping
- **D-13:** New terminals pass `workspace_id` via `/ws/terminal?workspace_id={id}` — cwd set to workspace root
- **D-14:** Switching workspace tabs hides current workspace's terminals and shows the target workspace's terminals — no terminal destruction on switch
- **D-15:** Terminal tab list is per-workspace — stored in memory, keyed by workspace_id

### Persistence Across Reloads
- **D-16:** Workspace tab state (which tabs exist, active workspace) persists via localStorage with stale-while-revalidate against `/api/workspaces`
- **D-17:** On reload: read cached workspace list from localStorage, render tabs immediately, then fetch fresh list from server and reconcile

### Claude's Discretion
- Tab bar styling details (colors, padding, font)
- Animation/transition on workspace switch
- Loading state while workspace data fetches
- Error handling for stale workspace IDs in localStorage
- Terminal re-fit timing after show/hide

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase 1 foundation (MUST read — provides registry API and namespace helpers)
- `.planning/workstreams/multi-project-workspace/phases/01-registry-namespacing/01-CONTEXT.md` — All Phase 1 decisions (D-01 through D-11), especially API migration path (query params) and namespace conventions
- `core/workspace_registry.py` — WorkspaceRegistry API: `list()`, `get()`, `create()`, `update()`, `delete()`, `resolve()`
- `dashboard/server.py` §workspace CRUD endpoints — `/api/workspaces` list/create/update/delete + `_resolve_workspace()` helper

### Client-side namespace helpers (Phase 1 output, used in Phase 2)
- `dashboard/frontend/dist/app.js` §164-191 — `WORKSPACE_URI_SCHEME`, `makeWorkspaceUri()`, `wsKey()` definitions

### Existing IDE code (what Phase 2 modifies)
- `dashboard/frontend/dist/app.js` §3535-3545 — Terminal panel layout, terminal tabs
- `dashboard/frontend/dist/app.js` §3800-3860 — Monaco editor tab management, model creation, setModel
- `dashboard/frontend/dist/app.js` §4562-5492 — CC chat session management, history, sidebar

### Roadmap and state
- `.planning/workstreams/multi-project-workspace/ROADMAP.md` — Phase 2 success criteria, plan breakdown
- `.planning/workstreams/multi-project-workspace/STATE.md` — Prior decisions: Monaco model swapping, stale-while-revalidate pattern

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `makeWorkspaceUri(workspaceId, filePath)` (app.js:173): Ready to use for Monaco model URIs
- `wsKey(workspaceId, key)` (app.js:184): Ready to use for all localStorage/sessionStorage keys
- `_resolve_workspace()` (server.py): Server-side workspace resolution helper already in place
- `/api/workspaces` CRUD (server.py): List endpoint provides workspace data for tab bar
- Monaco `getModel`/`createModel`/`setModel` pattern (app.js:3803-3852): Existing tab switching logic to extend

### Established Patterns
- Editor tabs managed as array of objects with `model`, `path`, `language` properties (app.js)
- Terminal tabs managed with `ide-terminal-tabs` container (app.js:3541)
- CC sessions use `ccSessionId` on tab objects + `sessionStorage` for active session
- `stale-while-revalidate`: Load from localStorage first, then fetch fresh — used for CC session resume

### Integration Points
- `loadFileExplorer()` or `ideLoadTree()`: Must accept workspace_id param
- `openFile()` / `openTab()`: Must use `makeWorkspaceUri()` for model URIs
- `termNew()`: Must pass workspace_id to WS connection
- `ccCreateSession()`: Must pass workspace_id to WS connection
- `ccLoadSessionSidebar()`: Must filter sessions by workspace_id

</code_context>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches following existing codebase patterns. Tab bar should feel like VS Code's workspace tabs — clean, functional, not decorative.

</specifics>

<deferred>
## Deferred Ideas

- Add/remove/rename workspaces — Phase 3 (MGMT-01, MGMT-02, MGMT-03)
- Auto-seeding apps/ as workspaces — Phase 3
- Workspace-specific settings or preferences — future milestone

</deferred>

---

*Phase: 02-ide-surface-integration*
*Context gathered: 2026-03-24 (auto mode)*
