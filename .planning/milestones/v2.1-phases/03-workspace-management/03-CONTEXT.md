# Phase 3: Workspace Management - Context

**Gathered:** 2026-03-24 (auto mode)
**Status:** Ready for planning

<domain>
## Phase Boundary

Users can add a new workspace by path or Agent42 app, remove any workspace that is not the last one, and rename a workspace inline — with guards that prevent data loss. No new IDE surface integration or workspace registry changes beyond what Phases 1-2 delivered.

</domain>

<decisions>
## Implementation Decisions

### Add Workspace — Button Placement
- **D-01:** A "+" button is appended inside the `ide-workspace-tabs` container by `ideRenderWorkspaceTabs()`, right-justified after all workspace tabs — matches VS Code and browser tab bar conventions
- **D-02:** The tab bar's current "hide when only 1 workspace" logic (line 3534) is lifted — the bar is always visible when the "+" button is present, so users can always add a second workspace

### Add Workspace — Modal Layout
- **D-03:** Single-panel modal using existing `showModal()`/`closeModal()` pattern — path input always shown at top, Agent42 app dropdown below as optional shortcut ("Or choose an Agent42 app")
- **D-04:** Selecting an app from the dropdown auto-fills the path input with the app's directory path — submit always reads from the path field, one code path
- **D-05:** App dropdown populated via `GET /api/apps` fetch when modal opens; if `app_manager` is not configured, dropdown section is hidden entirely
- **D-06:** Modal footer has Cancel and Add buttons following the existing Create Task / Create App modal pattern

### Add Workspace — Validation
- **D-07:** No separate validation endpoint — `POST /api/workspaces` returns 400 on invalid path (WorkspaceRegistry.create() raises ValueError), caught by `catch(err) => toast(err.message, "error")`
- **D-08:** Client-side duplicate check before POST — scan `_workspaceList` for matching `root_path`; if found, show `toast("Workspace already open", "error")` without calling the API
- **D-09:** On successful creation, the new workspace is appended to `_workspaceList`, tab bar re-renders, and `switchWorkspace(newId)` activates it immediately

### Remove Workspace — Guards
- **D-10:** Last-workspace protection is a frontend gate: if `_workspaceList.length <= 1`, the close button is disabled (greyed out or hidden entirely) — the DELETE API is never called
- **D-11:** Guard checks `tab.modified` on the workspace's editor tabs (from `_wsTabState[wsId].tabs`) AND `ccTabCount` from `_wsTabState[wsId]` for open CC sessions
- **D-12:** Confirmation dialog uses `confirm()` (matching existing `ideCloseTab` pattern) with a message that names what will be lost: "This workspace has N unsaved file(s) and M CC session(s). Remove anyway?"
- **D-13:** If no unsaved files and no CC sessions, removal proceeds without confirmation

### Remove Workspace — Post-Removal Cleanup
- **D-14:** Terminal WebSocket connections for the removed workspace are closed immediately — iterate `_wsTermSessions[removedId]` and call `termClose()` on each
- **D-15:** CC sessions are left running (WS dies naturally on page reload or explicit close) — avoids silently killing in-flight agent tasks
- **D-16:** localStorage keys matching `ws_{id}_*` prefix are pruned at removal time; `cc_hist_{sessionId}` keys are excluded (session-UUID-prefixed, globally unique, not workspace-scoped)
- **D-17:** In-memory state (`_wsTabState[removedId]`, `_wsTermSessions[removedId]`, `_wsTermActiveIdx[removedId]`) is deleted
- **D-18:** Active workspace switches to adjacent tab (previous index - 1, else first remaining) before teardown — matches browser/VS Code tab close conventions

### Inline Rename
- **D-19:** Rename trigger: clicking the label text of an already-active workspace tab enters rename mode — the tab label is wrapped in a `<span class="ide-ws-tab-name">` with a separate click handler that checks `tab.classList.contains('active')` before activating
- **D-20:** Rename mode replaces the span with an `<input>` element, pre-filled with current name, auto-focused and text-selected
- **D-21:** Enter commits: calls `PATCH /api/workspaces/{id}` with new name, updates `_workspaceList`, re-renders tab bar
- **D-22:** Escape discards: restores original name, removes input
- **D-23:** Blur commits (not discards) — matches VS Code file explorer convention, prevents accidental data loss when clicking elsewhere
- **D-24:** Validation: trim whitespace, reject empty string (restore original name with brief error indication), `maxlength="64"` on the input element

### Claude's Discretion
- Close button visual style on workspace tabs (X icon, positioning, hover state)
- "+" button styling (icon, size, hover effect)
- Modal input placeholder text and help copy
- Toast message wording for validation errors
- Animation/transition for tab addition/removal
- Whether the app dropdown shows app status (running/stopped) or just names

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase 1-2 foundation (registry, API, tab bar)
- `.planning/workstreams/multi-project-workspace/phases/01-registry-namespacing/01-CONTEXT.md` — Registry decisions (D-01 through D-11), ID scheme, persistence, API query param pattern
- `.planning/workstreams/multi-project-workspace/phases/02-ide-surface-integration/02-CONTEXT.md` — Tab bar decisions (D-01 through D-17), switchWorkspace orchestrator, wsKey namespace, stale-while-revalidate

### Backend (workspace registry + API endpoints)
- `core/workspace_registry.py` — WorkspaceRegistry class: `create()`, `update()`, `delete()`, `resolve()`; Workspace dataclass
- `dashboard/server.py` lines 1297-1344 — `/api/workspaces` CRUD endpoints (GET list, POST create, PATCH update, DELETE)
- `dashboard/server.py` lines 1355-1364 — `_resolve_workspace()` helper

### Frontend (tab bar, modal pattern, workspace state)
- `dashboard/frontend/dist/app.js` lines 3444-3620 — Workspace state vars (`_activeWorkspaceId`, `_wsTabState`, `_wsTermSessions`), `initWorkspaceTabs()`, `ideRenderWorkspaceTabs()`, `switchWorkspace()`
- `dashboard/frontend/dist/app.js` lines 1497-1515 — `showModal()` / `closeModal()` pattern
- `dashboard/frontend/dist/app.js` line 4103 — Existing unsaved-files guard pattern (`tab.modified && confirm()`)

### App manager (for app dropdown)
- `dashboard/server.py` line 5383 — `GET /api/apps` endpoint via `app_manager.list_apps()`

### Roadmap
- `.planning/workstreams/multi-project-workspace/ROADMAP.md` — Phase 3 success criteria, requirements (MGMT-01, MGMT-02, MGMT-03)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `showModal()` / `closeModal()` (app.js:1497-1515): Modal overlay pattern — reuse directly for add-workspace modal
- `ideRenderWorkspaceTabs()` (app.js:3535-3551): Tab bar renderer — extend with "+" button and close buttons
- `switchWorkspace()` (app.js:3553-3619): Workspace switch orchestrator — call after add/remove to activate target workspace
- `WorkspaceRegistry.create(name, root_path)` (workspace_registry.py:141): Server-side workspace creation with path validation
- `WorkspaceRegistry.update(workspace_id, name)` (workspace_registry.py:161): Server-side rename
- `WorkspaceRegistry.delete(workspace_id)` (workspace_registry.py:179): Server-side deletion with default reassignment
- `wsKey(workspaceId, key)` (app.js:184): localStorage key namespacing — use for pruning on removal
- `app_manager.list_apps()` (server.py:5383): App listing for dropdown population

### Established Patterns
- `tab.modified` flag on editor tabs: existing unsaved-files signal (app.js:4103)
- `confirm()` for destructive actions: used in `ideCloseTab()` — reuse for workspace removal
- `toast(message, type)`: error/success feedback — reuse for validation errors
- textContent (not innerHTML) for all DOM text: XSS prevention convention

### Integration Points
- `ideRenderWorkspaceTabs()`: Add "+" button and close (X) buttons per tab
- `_wsTabState[wsId]`: Read `tabs` for modified-files check, `ccTabCount` for CC session check
- `_wsTermSessions[wsId]`: Iterate and close terminal WSs on removal
- `_workspaceList`: Client-side workspace array — push on add, splice on remove
- `localStorage`: Prune `ws_{id}_*` keys on removal

</code_context>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches following existing codebase patterns. Modal should feel consistent with the existing Create Task and Create App modals.

</specifics>

<deferred>
## Deferred Ideas

- Workspace-specific settings or preferences — future milestone
- Drag-to-reorder workspace tabs — future enhancement
- Workspace color coding or icons — future enhancement
- Bulk workspace import from a config file — future milestone
- Server-side guard preventing deletion of last workspace (currently frontend-only) — add if needed

</deferred>

---

*Phase: 03-workspace-management*
*Context gathered: 2026-03-24 (auto mode)*
