# Phase 2: IDE Surface Integration - Research

**Researched:** 2026-03-24
**Domain:** Frontend state management (vanilla JS), Monaco editor, xterm.js, FastAPI WebSocket, workspace scoping
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Workspace Tab Bar**
- D-01: Tab bar renders above the editor tab bar, inside the IDE page layout — clicking a tab switches all surfaces
- D-02: Active tab has a visual indicator (highlight/underline); inactive tabs are subdued
- D-03: Tab bar loads workspace list from `/api/workspaces` on page load, with stale-while-revalidate from localStorage
- D-04: Active workspace ID stored in `localStorage` via `wsKey(id, "active_workspace")` — persists across reloads

**File Explorer Scoping**
- D-05: File explorer calls `/api/ide/tree?workspace_id={activeId}` — re-roots to the active workspace folder on every tab switch
- D-06: Files from other workspaces are never visible in the tree — complete isolation per success criteria #2

**Editor Tab State**
- D-07: Each workspace maintains its own editor tab list — `wsKey(workspaceId, "editor_tabs")` in localStorage
- D-08: On workspace switch: save current Monaco `saveViewState()` for each open tab, then restore the target workspace's tabs with `restoreViewState()` — cursor, scroll, selection all preserved
- D-09: Monaco model URIs use `makeWorkspaceUri(workspaceId, filePath)` — Phase 1 helper now wired into file open flow. Two workspaces can open the same filename without collision.

**CC Session Scoping**
- D-10: CC sessions pass `workspace_id` via the `/ws/cc-chat?workspace_id={id}` query param — subprocess cwd set to workspace root
- D-11: CC session history filtered per workspace — only sessions started in the active workspace are shown in the sidebar
- D-12: The `cc_active_session` key becomes `wsKey(workspaceId, "cc_active_session")` — per-workspace active session tracking

**Terminal Session Scoping**
- D-13: New terminals pass `workspace_id` via `/ws/terminal?workspace_id={id}` — cwd set to workspace root
- D-14: Switching workspace tabs hides current workspace's terminals and shows the target workspace's terminals — no terminal destruction on switch
- D-15: Terminal tab list is per-workspace — stored in memory, keyed by workspace_id

**Persistence Across Reloads**
- D-16: Workspace tab state (which tabs exist, active workspace) persists via localStorage with stale-while-revalidate against `/api/workspaces`
- D-17: On reload: read cached workspace list from localStorage, render tabs immediately, then fetch fresh list from server and reconcile

### Claude's Discretion
- Tab bar styling details (colors, padding, font)
- Animation/transition on workspace switch
- Loading state while workspace data fetches
- Error handling for stale workspace IDs in localStorage
- Terminal re-fit timing after show/hide

### Deferred Ideas (OUT OF SCOPE)
- Add/remove/rename workspaces — Phase 3 (MGMT-01, MGMT-02, MGMT-03)
- Auto-seeding apps/ as workspaces — Phase 3
- Workspace-specific settings or preferences — future milestone
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| FOUND-03 | Workspace tab bar renders above editor tab bar; clicking switches all surfaces | renderCode() HTML structure identified — workspace tabs inject above `#ide-tabs`; `switchWorkspace()` orchestrates all surface updates |
| FOUND-05 | Active workspace ID persists in localStorage with stale-while-revalidate on reload | stale-while-revalidate pattern already used in CC session resume — same localStorage-first, then fetch-and-reconcile approach |
| ISOL-01 | File explorer re-roots to active workspace — no cross-workspace file visibility | `ideLoadTree()` at line 3729 uses global `_ideTreeCache`; must scope cache by workspace_id and pass `workspace_id` query param |
| ISOL-02 | Editor tabs are per-workspace; view state (cursor/scroll/selection) preserved on switch | `saveViewState()`/`restoreViewState()` exist on Monaco editor instance; `_ideTabs` global array must be partitioned by workspace_id |
| ISOL-03 | CC sessions use workspace cwd; history filtered per workspace | `cc_chat_ws` uses module-level `workspace` variable (line 2481); must read `workspace_id` query param and call `_resolve_workspace()`; session JSON must store `workspace_id` |
| ISOL-04 | Terminals start in workspace cwd; switching shows/hides per-workspace terminals | `termNew()` at line 5810 uses `workspace` variable in WS URL; must pass `workspace_id`; `_termSessions` global must be partitioned |
| ISOL-05 | Workspace state persists across page reloads | Same pattern as FOUND-05 — localStorage keyed by `wsKey()` |
</phase_requirements>

---

## Summary

Phase 2 is pure state-management and UI wiring work — no new backend infrastructure, no new frontend libraries. Phase 1 already delivered: `WorkspaceRegistry`, `/api/workspaces` CRUD, `_resolve_workspace()` helper, `makeWorkspaceUri()`, and `wsKey()`. Phase 2 threads `workspace_id` into the four IDE surfaces (file explorer, editor tabs, CC sessions, terminals) and renders the workspace tab bar.

The critical challenge is that all four IDE surfaces share global state arrays (`_ideTabs`, `_termSessions`, `_ideTreeCache`) in a single-file vanilla JS application (`app.js`). Each must be promoted from a flat array/dict to a workspace-keyed structure. The Monaco `saveViewState()`/`restoreViewState()` API handles editor state. Terminal show/hide is already a pattern used internally.

The backend has two points that need `workspace_id` wired in: (1) `cc_chat_ws` currently uses the module-level `workspace` variable (line 2481) instead of calling `_resolve_workspace()`; (2) `/api/cc/sessions` currently reads from `workspace / ".agent42" / "cc-sessions"` (line 2820) — sessions need a `workspace_id` field stored in their JSON so the client can filter, or the server endpoint gains a `workspace_id` query param filter.

**Primary recommendation:** Implement in three plans matching ROADMAP.md: 02-01 (backend wiring + file explorer + terminal scoping), 02-02 (editor tab state + CC session scoping), 02-03 (workspace tab bar UI + localStorage persistence).

---

## Standard Stack

### Core (All Existing — No New Dependencies)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Vanilla JS (app.js) | — | All frontend IDE logic | Project uses no frontend build tool; single-file JS |
| Monaco Editor | CDN loaded | Editor model management | Already used; `saveViewState`/`restoreViewState`/`setModel` API in use |
| xterm.js + FitAddon | CDN loaded | Terminal sessions | Already used; `termNew()`, `_termSessions[]`, `termRenderTabs()` in place |
| FastAPI WebSocket | 0.115+ | WS endpoints for terminal, CC chat | Already used; query param pattern established |
| localStorage | Browser API | Workspace ID + tab state persistence | Already used for CC session resume |

**No new dependencies required.**

---

## Architecture Patterns

### Recommended Project Structure

No new directories. All changes are within:
```
dashboard/
  server.py                    # cc_chat_ws workspace_id param, cc_sessions filter
  frontend/dist/
    app.js                     # workspace tab bar, state partitioning, surface wiring
```

---

### Pattern 1: Workspace-Keyed Global State

The four global state arrays/dicts must be promoted from flat to workspace-keyed.

**Current state (flat):**
- `_ideTabs = []` — all editor tabs, all workspaces
- `_ideActiveTab = -1`
- `_ideTreeCache = {}` — path -> entries, all workspaces
- `_termSessions = []` — all terminal sessions, all workspaces

**After promotion:**
- `_wsTabState = {}` — structure: `{ [workspaceId]: { tabs: [], activeTab: -1 } }`
- `_ideTreeCache` — keys become `workspaceId + ":" + path` to prevent cross-workspace bleed
- `_wsTermSessions = {}` — structure: `{ [workspaceId]: [ ...sessions ] }`
- `_wsTermActiveIdx = {}` — structure: `{ [workspaceId]: number }`

`_ideTabs` and `_ideActiveTab` remain as aliases pointing to the active workspace's entry. All existing call sites (`ideActivateTab()`, `ideRenderTabs()`, etc.) continue to work without modification. The alias is reassigned in `switchWorkspace()`.

**When to use:** Any global that currently holds IDE state for a single workspace must be promoted. The aliasing approach means zero changes to the 100+ call sites that reference `_ideTabs` and `_termSessions`.

### Pattern 2: Workspace Switch Orchestrator

A single `switchWorkspace(newId)` function coordinates all surface updates in order:

1. Save Monaco view states for all tabs in the current workspace
2. Hide current workspace's terminal DOM elements
3. Reassign `_activeWorkspaceId = newId`
4. Swap `_ideTabs` alias to new workspace's tab array
5. Swap `_termSessions` alias to new workspace's terminal array
6. Clear `_ideTreeCache` (forces re-fetch under new workspace)
7. Re-render workspace tab bar
8. Call `ideLoadTree("")` to re-root file explorer
9. Call `ideActivateTab()` or show welcome screen depending on open tabs
10. Call `termRenderTabs()` and re-show the active terminal with `fitAddon.fit()` in a 50ms timeout

All surface updates happen through existing functions — `switchWorkspace()` only manages ordering and alias swaps.

### Pattern 3: File Explorer workspace_id Threading

`ideLoadTree()` appends `&workspace_id=` to the fetch URL using `_activeWorkspaceId`. The cache key becomes `(_activeWorkspaceId || "") + ":" + path` instead of bare `path`. The tree is cleared on workspace switch before `ideLoadTree("")` is called.

The backend `ide_tree` endpoint already accepts `workspace_id` (server.py line 1368-1400) — no backend change needed for file explorer.

### Pattern 4: Monaco View State Save/Restore

Monaco provides `saveViewState()` and `restoreViewState()` on the editor instance. These are stored directly on the tab object in `_ideTabs` as `tab.viewState`. The `ideActivateTab()` file-tab branch calls `restoreViewState(tab.viewState)` after `setModel(tab.model)`. On workspace switch, the current tab's view state is saved to `tab.viewState` before the alias swap.

Monaco model URIs already use `makeWorkspaceUri(workspaceId, filePath)` per D-09. Models are not disposed on workspace switch — they persist in memory and are swapped via `setModel()`.

The critical migration in `ideOpenFile()`: change `monaco.Uri.parse("file:///" + path)` (line 3802) to `monaco.Uri.parse(makeWorkspaceUri(_activeWorkspaceId, path))`. This is the only place where `file:///` URIs are currently created for new file tabs.

### Pattern 5: CC Session workspace_id — Backend

Two surgical changes to `server.py`:

**Change A — `cc_chat_ws`:** Read `workspace_id` query param at the top of the handler (near line 2338) and call `_resolve_workspace(ws_workspace_id)` to get `workspace_path`. Replace the four occurrences of `str(workspace)` inside `cc_chat_ws` with `str(workspace_path)`. Also pass `workspace_id` to `_read_gsd_workstream()` if it accepts a path.

**Change B — `_save_session()`:** Add `workspace_id` field to the session dict written at line 2794. This allows `/api/cc/sessions` to filter by workspace.

**Change C — `/api/cc/sessions` endpoint (line 2816):** Add optional `workspace_id: str | None = None` query param. When provided, filter sessions: include sessions whose stored `workspace_id` matches, plus sessions with no `workspace_id` field (legacy sessions, treated as default workspace).

### Pattern 6: Terminal workspace_id — Backend

Single change to `terminal_ws` (server.py line 1539): read `workspace_id = websocket.query_params.get("workspace_id")` after reading `node` and `cmd` (line 1561). Then call `workspace_path = _resolve_workspace(workspace_id)` to get the path. Replace the three occurrences of `str(workspace)` inside `terminal_ws` (lines 1647, 1659, 1768) with `str(workspace_path)`.

### Pattern 7: Workspace Tab Bar HTML

The `renderCode()` function at line 3485 uses a single `innerHTML` template string. The workspace tab bar `div` is added to the template, just above `<div id="ide-tabs" class="ide-tabs">` (line 3518):

```
<div id="ide-workspace-tabs" class="ide-workspace-tabs"></div>
```

The div starts empty. `initWorkspaceTabs()` is called immediately after `renderCode()` builds the layout (it can be called from within the existing `ideInit()` sequence or directly after the `innerHTML` assignment). `ideRenderWorkspaceTabs()` populates the div using `document.createElement` / `textContent` (not innerHTML with user data) to build tab elements — workspace names are set via `textContent = ws.name`.

### Pattern 8: stale-while-revalidate for Workspace Tab State

`initWorkspaceTabs()` runs on IDE init:
1. Read `localStorage.getItem("workspaces_cache")` — if present, render tabs immediately
2. Read `localStorage.getItem("active_workspace_id")` — restore last active workspace
3. Fetch `/api/workspaces` in background
4. On success: update `localStorage.setItem("workspaces_cache", ...)` and reconcile — if `active_workspace_id` no longer exists in the fresh list, fall back to `default_id`
5. Re-render workspace tabs with fresh data

This is the exact same pattern used for CC session resume (app.js line 5076-5088: read from sessionStorage, restore, then reconnect).

### Anti-Patterns to Avoid

- **Destroying terminals on workspace switch:** Do not call `term.dispose()` or `ws.close()` when switching workspaces. Terminals survive in the background — only their DOM elements are hidden. This matches D-14 and avoids reconnect latency.
- **Rebuilding Monaco models on workspace switch:** Models persist. Only call `setModel()` to swap to the correct model — do not `dispose()` and `createModel()` on every switch.
- **Passing raw paths from client to API:** Never pass `root_path` directly to any endpoint. Always pass `workspace_id` and let `_resolve_workspace()` do the path lookup.
- **Hardcoding `workspace` in WS handlers:** The `cc_chat_ws` and `terminal_ws` functions currently use the module-level `workspace` variable for subprocess cwd. The fix is surgical — add query param read and `_resolve_workspace()` call.
- **Sharing `_ideTreeCache` across workspaces:** The existing `_ideTreeCache` is keyed by path string only. Must either clear on switch or use workspace-prefixed keys to prevent cross-workspace tree bleed.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Editor cursor/scroll persistence | Custom serialization | `monaco.editor.saveViewState()` / `restoreViewState()` | Monaco built-in — handles cursor, scroll, and selection atomically |
| Terminal resize after show/hide | Complex resize observer | `fitAddon.fit()` with 50ms `setTimeout` | FitAddon already integrated; timing delay handles DOM reflow |
| Workspace-scoped localStorage | Custom prefix scheme | `wsKey(workspaceId, key)` from Phase 1 | Already defined at app.js:184 — consistent with all future keys |
| Monaco model namespace isolation | Custom URI scheme | `makeWorkspaceUri(workspaceId, filePath)` from Phase 1 | Already defined at app.js:173 — models with different workspace IDs never collide |
| Per-workspace CC session filtering | Separate endpoint per workspace | Add `workspace_id` query param to `/api/cc/sessions` | Simpler — one endpoint, optional filter, backward compatible |

---

## Runtime State Inventory

This is not a rename/refactor phase. No runtime state inventory required.

---

## Common Pitfalls

### Pitfall 1: `_ideTabs` Alias Drift
**What goes wrong:** `switchWorkspace()` reassigns `_ideTabs = _wsTabState[newId].tabs` but some code holds a local reference captured before the switch.
**Why it happens:** Vanilla JS closures capture variable reference. If a function does `var tabs = _ideTabs` before a switch, it holds the old array.
**How to avoid:** Always read `_ideTabs` fresh inside functions — never save it to a local variable in closures that outlive a single call. All surface-update functions must be called after the alias assignment.
**Warning signs:** Editor tab bar renders tabs from the wrong workspace after a switch.

### Pitfall 2: Monaco Model URI Collision
**What goes wrong:** Two workspaces both open `src/main.py`. If `ideOpenFile()` still uses `"file:///" + path` (line 3802), both workspaces share the same Monaco model object.
**Why it happens:** Phase 1 defined `makeWorkspaceUri()` but did not migrate the `ideOpenFile()` call site — that migration is Phase 2's job.
**How to avoid:** In `ideOpenFile()`, change `var uri = monaco.Uri.parse("file:///" + path)` to `var uri = monaco.Uri.parse(makeWorkspaceUri(_activeWorkspaceId, path))`.
**Warning signs:** Editing a file in workspace A shows changes in workspace B's editor when both have the same filename open.

### Pitfall 3: Tree Cache Cross-Contamination
**What goes wrong:** Workspace A loads `src/` directory. User switches to workspace B. `ideRenderTree()` still shows workspace A's tree.
**Why it happens:** `_ideTreeCache` is currently keyed by path string only. No workspace scope.
**How to avoid:** Either clear `_ideTreeCache = {}` in `switchWorkspace()` before calling `ideLoadTree("")`, or use workspace-prefixed cache keys.
**Warning signs:** File explorer briefly shows wrong workspace's files after tab switch.

### Pitfall 4: Terminal fitAddon Timing
**What goes wrong:** After switching workspace tabs, newly visible terminals appear garbled or sized incorrectly.
**Why it happens:** xterm.js requires the terminal DOM element to have nonzero dimensions before `fitAddon.fit()` produces correct results. Calling fit while element is still `display:none` is a no-op.
**How to avoid:** Call `fitAddon.fit()` inside a `setTimeout(..., 50)` after setting `el.style.display = "block"`. This pattern is already used in `renderCode()` at line 3470.
**Warning signs:** Terminal appears blank or shows text with wrong line width after workspace switch.

### Pitfall 5: `cc_chat_ws` Uses Module-Level `workspace`, Not `_resolve_workspace()`
**What goes wrong:** All CC sessions in all workspaces get their subprocess cwd set to the env-var workspace, not the selected workspace.
**Why it happens:** `cc_chat_ws` (server.py line 2481) uses `cwd=str(workspace)` — the `workspace` variable is captured at `create_app()` scope. It never reads the WS query param.
**How to avoid:** Add `ws_workspace_id = websocket.query_params.get("workspace_id")` at line 2338 and call `workspace_path = _resolve_workspace(ws_workspace_id)`. Replace all `str(workspace)` inside `cc_chat_ws` with `str(workspace_path)`.
**Warning signs:** CC session runs in wrong directory regardless of which workspace tab is active.

### Pitfall 6: CC Sessions Filter — Missing `workspace_id` Field in Old Sessions
**What goes wrong:** After Phase 2, workspace_id filter on `/api/cc/sessions` returns no results for old sessions.
**Why it happens:** Sessions created before Phase 2 have no `workspace_id` field. A strict equality filter excludes them.
**How to avoid:** Filter logic: include sessions whose `workspace_id` matches the requested ID, OR sessions with no `workspace_id` field when the requested ID is the default workspace. Old sessions belong to the default workspace.
**Warning signs:** CC session sidebar shows empty history after Phase 2 deploy despite session files existing on disk.

### Pitfall 7: `ccGetStoredSessionId()` / `ccStoreSessionId()` Key Conflict
**What goes wrong:** Two workspace tabs open CC chat. The second workspace's CC session ID overwrites the first's, breaking resume on reload.
**Why it happens:** `cc_active_session` is a global sessionStorage key (app.js lines 4854, 4858). Phase 1 identified this for migration to `wsKey(workspaceId, "cc_active_session")`.
**How to avoid:** Update both `ccGetStoredSessionId()` (line 4854) and `ccStoreSessionId()` (line 4858) to use `wsKey(_activeWorkspaceId, "cc_active_session")`.
**Warning signs:** Resuming a CC session in workspace B restores workspace A's session.

### Pitfall 8: `termNew()` WS URL Lacks `workspace_id`
**What goes wrong:** New terminals in workspace B start with cwd set to workspace A's root or the env-var default.
**Why it happens:** `termNew()` at line 5848 builds the WS URL without `workspace_id`. Backend `terminal_ws` uses module-level `workspace` for cwd.
**How to avoid:** Append `&workspace_id=` + encodeURIComponent(_activeWorkspaceId) to the WS URL in both `termNew()` and `termNewClaude()`. Backend `terminal_ws` reads the param and calls `_resolve_workspace()`.
**Warning signs:** `pwd` in a new terminal shows wrong directory.

---

## Code Examples

Verified patterns from the existing codebase:

### Monaco setModel with view state (existing setModel call, Phase 2 adds restoreViewState)
```javascript
// Source: app.js:3851-3854 (existing file tab branch of ideActivateTab)
if (_monacoEditor) {
  _monacoEditor.setModel(tab.model);
  // Phase 2 adds immediately after setModel:
  if (tab.viewState) {
    _monacoEditor.restoreViewState(tab.viewState);
  }
}

// Phase 2 save before workspace switch (added to switchWorkspace()):
var currentTab = _ideTabs[_ideActiveTab];
if (currentTab && currentTab.type !== "claude" && currentTab.model) {
  currentTab.viewState = _monacoEditor.saveViewState();
}
```

### Terminal hide/show pattern (existing usage at app.js:5824)
```javascript
// Existing pattern in termNew() — hide all other terminals:
for (var i = 0; i < _termSessions.length; i++) {
  if (_termSessions[i].el) _termSessions[i].el.style.display = "none";
}
// Phase 2 workspace switch uses the same pattern keyed by workspace_id:
(_wsTermSessions[oldId] || []).forEach(function(s) {
  if (s.el) s.el.style.display = "none";
});
```

### wsKey usage (Phase 1 definition at app.js:184)
```javascript
// Active workspace stored globally (no workspace prefix needed):
localStorage.setItem("active_workspace_id", workspaceId);

// Per-workspace CC session key (Phase 2 migration):
sessionStorage.setItem(wsKey(_activeWorkspaceId, "cc_active_session"), sessionId);

// Per-workspace editor tab paths (Phase 2 addition):
localStorage.setItem(wsKey(_activeWorkspaceId, "editor_tabs"), JSON.stringify(tabPaths));
```

### `_resolve_workspace()` backend (Phase 1 output at server.py:1355)
```python
# Existing helper — already handles workspace_id -> Path resolution with fallback:
def _resolve_workspace(workspace_id: "str | None" = None) -> Path:
    if workspace_registry:
        ws = workspace_registry.resolve(workspace_id)
        if ws:
            return Path(ws.root_path)
        if workspace_id is not None:
            raise HTTPException(404, "Workspace not found")
    return workspace  # env-var fallback

# Phase 2 usage in cc_chat_ws (adds these two lines near line 2338):
ws_workspace_id = websocket.query_params.get("workspace_id")
workspace_path = _resolve_workspace(ws_workspace_id)
# Then replace str(workspace) -> str(workspace_path) in the handler
```

### stale-while-revalidate pattern (existing pattern in CC session resume at app.js:5076)
```javascript
// Existing: read from sessionStorage first, then reconnect WS for fresh data
var storedSession = ccGetStoredSessionId();
if (storedSession && _ccTabCounter === 1) {
  sessionId = storedSession;
  sessionResumed = true;
}

// Phase 2 workspace init follows same pattern:
// 1. Read cached workspace list from localStorage -> render immediately
// 2. Fetch /api/workspaces -> reconcile and update localStorage cache
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Single global `workspace` in all WS handlers | `_resolve_workspace(workspace_id)` per-request | Phase 1 (IDE HTTP only) | Phase 2 extends this to `cc_chat_ws` and `terminal_ws` |
| Flat `_ideTabs` / `_termSessions` globals | Workspace-keyed dicts with active workspace aliasing | Phase 2 | Zero call-site changes to existing functions |
| Single `cc_active_session` key | `wsKey(workspaceId, "cc_active_session")` | Phase 2 (planned in Phase 1) | Per-workspace CC session resume |
| `"file:///" + path` Monaco model URIs | `makeWorkspaceUri(workspaceId, path)` | Phase 2 (planned in Phase 1) | Cross-workspace filename collision prevention |

---

## Open Questions

1. **CC sessions directory — per-workspace or global?**
   - What we know: `_CC_SESSIONS_DIR` is set once at line 1811 as `workspace / ".agent42" / "cc-sessions"`. All workspaces currently share this directory.
   - What's unclear: Should Phase 2 move to per-workspace session directories, or keep all sessions in one directory but add `workspace_id` field for filtering?
   - Recommendation: Keep all sessions in one directory (no migration cost) and add `workspace_id` field + optional filter on `/api/cc/sessions`. Per-workspace directories are cleaner but require data migration. The filter approach is backward-compatible (old sessions treated as default workspace).

2. **`ideOpenCCChat()` session-on-first-tab logic (line 5080)**
   - What we know: `if (storedSession && _ccTabCounter === 1)` only resumes a session for the very first CC tab opened globally. With workspace scoping, each workspace needs its own `cc_active_session` key.
   - What's unclear: Should the workspace switch trigger a new CC tab, or should each workspace have a persistent CC tab?
   - Recommendation: Keep lazy creation (only open CC tab when user requests it via the dropdown). The condition stays, but session ID comes from `wsKey(_activeWorkspaceId, "cc_active_session")` instead of the bare key. The `_ccTabCounter === 1` guard may need to change to per-workspace tracking.

---

## Environment Availability

Step 2.6: SKIPPED (no new external dependencies — phase uses existing FastAPI, Monaco, xterm.js, all already available).

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.x + pytest-asyncio (asyncio_mode = "auto") |
| Config file | pyproject.toml |
| Quick run command | `python -m pytest tests/test_workspace_registry.py tests/test_ide_html.py -x -q` |
| Full suite command | `python -m pytest tests/ -x -q` |

### Phase Requirements to Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| FOUND-03 | Workspace tab bar HTML element present in app.js | unit (source scan) | `python -m pytest tests/test_ide_html.py -x -q` | Needs new test in existing file |
| FOUND-05 | `wsKey()` and `active_workspace_id` localStorage key defined in app.js | unit (source scan) | `python -m pytest tests/test_ide_html.py -x -q` | Needs new test |
| ISOL-01 | `/api/ide/tree?workspace_id=` returns scoped entries | integration (FastAPI TestClient) | `python -m pytest tests/test_workspace_registry.py -x -q` | Needs new test |
| ISOL-02 | `makeWorkspaceUri()` used in `ideOpenFile()` in app.js | unit (source scan) | `python -m pytest tests/test_ide_html.py -x -q` | Needs new test |
| ISOL-03 | `/api/cc/sessions?workspace_id=` filters by workspace_id | integration | New test file | Not exists — Wave 0 |
| ISOL-04 | `/ws/terminal?workspace_id=` wired to `_resolve_workspace()` | unit (source scan of server.py) | New test in test_workspace_registry.py | Not exists — Wave 0 |
| ISOL-05 | `switchWorkspace()` function present in app.js | unit (source scan) | `python -m pytest tests/test_ide_html.py -x -q` | Needs new test |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/test_workspace_registry.py tests/test_ide_html.py -x -q`
- **Per wave merge:** `python -m pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] New tests in `tests/test_ide_html.py` — covers FOUND-03 (workspace tab bar element), FOUND-05 (active_workspace_id key), ISOL-02 (makeWorkspaceUri usage), ISOL-05 (switchWorkspace function)
- [ ] `tests/test_workspace_surface.py` — covers ISOL-01 (ide/tree with workspace_id via TestClient), ISOL-03 (cc/sessions workspace filter), ISOL-04 (terminal ws workspace_id in server.py source)

---

## Sources

### Primary (HIGH confidence)
- `dashboard/frontend/dist/app.js` lines 160-200, 3458-3870, 4562-5492, 5810-5870 — existing IDE state globals, renderCode() template, Monaco tab management, CC chat session management, terminal session management — direct code inspection
- `dashboard/server.py` lines 1297-1500, 1539-1650, 2317-2360, 2460-2510, 2794-2830 — WorkspaceRegistry endpoints, terminal WS, cc_chat_ws, session save/load — direct code inspection
- `core/workspace_registry.py` — WorkspaceRegistry API, `_resolve_workspace()` — Phase 1 output (confirmed complete per ROADMAP.md)
- Monaco Editor API — `saveViewState()`, `restoreViewState()`, `setModel()` — confirmed present in existing ideActivateTab() code at app.js:3824, 3852

### Secondary (MEDIUM confidence)
- `tests/test_workspace_registry.py` — test patterns for WorkspaceRegistry integration tests — confirms TestClient-based API testing pattern used for server endpoints
- `tests/test_ide_html.py` — test pattern for app.js source scanning — confirms source-scan test approach for frontend validation

---

## Project Constraints (from CLAUDE.md)

| Directive | Impact on Phase 2 |
|-----------|-------------------|
| All I/O is async | `_resolve_workspace()` is sync (Path operations only) — acceptable. No new async file I/O added in Phase 2. |
| Never use blocking I/O | Terminal/CC WS subprocess cwd change is a sync Path string — no blocking I/O introduced. |
| Security: never accept raw paths from client | Confirmed: Phase 2 only accepts `workspace_id` query params, never raw paths. `_resolve_workspace()` validates. |
| pytest-asyncio asyncio_mode = "auto" | Use `asyncio.run()` in sync fixtures on Windows (known issue per STATE.md). |
| Test writing rules: every new module needs test coverage | New `test_workspace_surface.py` needed for server.py workspace_id threading (ISOL-03, ISOL-04). |
| GSD workflow enforcement | Phase 2 plans use `/gsd:execute-phase`. |
| Document fixes in CLAUDE.md pitfalls table | If non-obvious bugs discovered during implementation, add to CLAUDE.md pitfalls table (currently at #124). |

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new libraries; all referenced APIs confirmed present in existing code
- Architecture: HIGH — all patterns derived directly from existing codebase code at specific line numbers, not from documentation or assumptions
- Pitfalls: HIGH — each pitfall identified from specific existing line numbers where the problem originates
- Backend changes: HIGH — `_resolve_workspace()` and `_save_session()` APIs confirmed from Phase 1 output

**Research date:** 2026-03-24
**Valid until:** 2026-04-24 (stable codebase; research is invalidated only if server.py or app.js significantly changes)
