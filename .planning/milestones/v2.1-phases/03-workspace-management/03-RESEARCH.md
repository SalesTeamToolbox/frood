# Phase 3: Workspace Management - Research

**Researched:** 2026-03-24
**Domain:** Vanilla JS frontend DOM manipulation, modal patterns, inline editing, FastAPI backend (existing endpoints)
**Confidence:** HIGH

## Summary

Phase 3 is a pure UI/UX extension on top of fully-built backend infrastructure. The WorkspaceRegistry CRUD API (`POST`, `PATCH`, `DELETE /api/workspaces`) is complete, tested, and returning correct status codes. The frontend workspace state machine (`_workspaceList`, `_wsTabState`, `_wsTermSessions`, `switchWorkspace()`, `ideRenderWorkspaceTabs()`) is also complete from Phase 2.

The three requirements — add workspace, remove workspace with guards, and inline rename — are each discrete frontend features that read from and write to the existing backend API. No new Python code is required. The only backend touch is ensuring `GET /api/apps` is callable when `app_manager` is configured; that endpoint already exists at server.py:5382.

All three operations (add, remove, rename) must extend `ideRenderWorkspaceTabs()` which currently renders only plain `<button>` tabs. The plan must coordinate: (1) lifting the "hide when 1 workspace" rule from ideRenderWorkspaceTabs(), (2) adding a "+" button and per-tab close button to every tab render, and (3) implementing the inline rename input lifecycle inside the tab name span.

**Primary recommendation:** All three MGMT requirements can be delivered in one plan (03-01) because they all touch the same function (`ideRenderWorkspaceTabs`) and same state (`_workspaceList`). No backend work is needed.

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Add Workspace -- Button Placement**
- D-01: A "+" button is appended inside the `ide-workspace-tabs` container by `ideRenderWorkspaceTabs()`, right-justified after all workspace tabs
- D-02: The tab bar's current "hide when only 1 workspace" logic (line 3534) is lifted -- the bar is always visible when the "+" button is present

**Add Workspace -- Modal Layout**
- D-03: Single-panel modal using existing `showModal()`/`closeModal()` pattern -- path input always shown at top, Agent42 app dropdown below as optional shortcut
- D-04: Selecting an app from the dropdown auto-fills the path input with the app's directory path
- D-05: App dropdown populated via `GET /api/apps` fetch when modal opens; if `app_manager` is not configured, dropdown section is hidden entirely
- D-06: Modal footer has Cancel and Add buttons following the existing Create Task / Create App modal pattern

**Add Workspace -- Validation**
- D-07: No separate validation endpoint -- `POST /api/workspaces` returns 400 on invalid path, caught by `catch(err) => toast(err.message, "error")`
- D-08: Client-side duplicate check before POST -- scan `_workspaceList` for matching `root_path`; if found, show `toast("Workspace already open", "error")` without calling the API
- D-09: On successful creation, new workspace is appended to `_workspaceList`, tab bar re-renders, and `switchWorkspace(newId)` activates it immediately

**Remove Workspace -- Guards**
- D-10: Last-workspace protection is a frontend gate: if `_workspaceList.length <= 1`, the close button is disabled (greyed out or hidden entirely)
- D-11: Guard checks `tab.modified` on the workspace's editor tabs (from `_wsTabState[wsId].tabs`) AND `ccTabCount` from `_wsTabState[wsId]` for open CC sessions
- D-12: Confirmation dialog uses `confirm()` with message naming what will be lost: "This workspace has N unsaved file(s) and M CC session(s). Remove anyway?"
- D-13: If no unsaved files and no CC sessions, removal proceeds without confirmation

**Remove Workspace -- Post-Removal Cleanup**
- D-14: Terminal WebSocket connections for the removed workspace are closed immediately
- D-15: CC sessions are left running (WS dies naturally on page reload or explicit close)
- D-16: localStorage keys matching `ws_{id}_*` prefix are pruned at removal time; `cc_hist_{sessionId}` keys are excluded
- D-17: In-memory state (`_wsTabState[removedId]`, `_wsTermSessions[removedId]`, `_wsTermActiveIdx[removedId]`) is deleted
- D-18: Active workspace switches to adjacent tab (previous index - 1, else first remaining) before teardown

**Inline Rename**
- D-19: Rename trigger: clicking the label text of an already-active workspace tab enters rename mode
- D-20: Rename mode replaces the span with an `<input>`, pre-filled with current name, auto-focused and text-selected
- D-21: Enter commits: calls `PATCH /api/workspaces/{id}` with new name, updates `_workspaceList`, re-renders tab bar
- D-22: Escape discards: restores original name, removes input
- D-23: Blur commits (not discards) -- matches VS Code file explorer convention
- D-24: Validation: trim whitespace, reject empty string (restore original name), `maxlength="64"` on the input element

### Claude's Discretion
- Close button visual style on workspace tabs (X icon, positioning, hover state)
- "+" button styling (icon, size, hover effect)
- Modal input placeholder text and help copy
- Toast message wording for validation errors
- Animation/transition for tab addition/removal
- Whether the app dropdown shows app status (running/stopped) or just names

### Deferred Ideas (OUT OF SCOPE)
- Workspace-specific settings or preferences
- Drag-to-reorder workspace tabs
- Workspace color coding or icons
- Bulk workspace import from a config file
- Server-side guard preventing deletion of last workspace (currently frontend-only)
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| MGMT-01 | "Add workspace" button opens a modal where the user can enter a filesystem path (validated against the server) or choose an Agent42 internal app from a dropdown | `POST /api/workspaces` ready; `GET /api/apps` ready; `showModal()` pattern established; app dropdown conditional on app_manager availability |
| MGMT-02 | Clicking the close button on a workspace tab shows a confirmation guard if the workspace has unsaved files; the last workspace cannot be removed | `tab.modified` flag exists on editor tabs; `ccTabCount` exists on `_wsTabState[wsId]`; `confirm()` pattern used in `ideCloseTab()`; `termClose()` closes terminal WS+xterm |
| MGMT-03 | Clicking a workspace tab name switches it to an inline text input; pressing Enter saves the rename and updates the tab bar immediately | `PATCH /api/workspaces/{id}` endpoint ready; `ideRenderWorkspaceTabs()` is the only renderer; replace span with input and restore on Enter/Escape/blur |
</phase_requirements>

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Vanilla JS (existing) | ES6 | All frontend logic | Project uses no build toolchain -- all JS is hand-written in `app.js`. No framework. |
| FastAPI (existing) | 0.115+ | Backend endpoints | All three CRUD endpoints already exist and are tested |
| aiofiles (existing) | 23+ | Async persist in WorkspaceRegistry | Already used; no change needed |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `fetch()` (browser built-in) | -- | API calls from modal submit | Already the pattern used throughout `app.js` via the `api()` helper |
| `confirm()` (browser built-in) | -- | Unsaved-files guard dialog | Matches existing `ideCloseTab()` pattern exactly |
| `localStorage` (browser built-in) | -- | Pruning `ws_{id}_*` keys on removal | `wsKey()` helper at app.js:184 generates key names |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `confirm()` | Custom confirmation modal | `confirm()` matches the existing ideCloseTab pattern (D-12/D-13). A custom modal would be inconsistent. |
| Single `showModal()` call | Multi-step wizard | Single-panel (D-03) is simpler and consistent with Create Task modal |

**Installation:** No new dependencies. This phase is entirely additive JS + CSS.

---

## Architecture Patterns

### Recommended Project Structure

All changes land in two files:
```
dashboard/frontend/dist/
├── app.js           # All JS: ideRenderWorkspaceTabs(), showAddWorkspaceModal(),
│                    # submitAddWorkspace(), removeWorkspace(), enterWsRenameMode()
└── style.css        # Close button styles, "+" button styles, rename input styles
```

No Python backend changes required -- all three CRUD endpoints are complete.

### Pattern 1: Extending ideRenderWorkspaceTabs()

**What:** The function currently renders plain `<button>` tabs. It must be extended to:
1. Always show the tab bar (lift the `_workspaceList.length <= 1` hide guard -- D-02)
2. Render each tab with an inner `<span class="ide-ws-tab-name">` (for rename click target) and a close button element (for remove)
3. Append a "+" add button after all tabs

**When to use:** Every call site that triggers re-render already calls `ideRenderWorkspaceTabs()`. No new render triggers needed.

**Example -- tab element construction:**
```javascript
// Source: existing ideRenderWorkspaceTabs() at app.js:3527 -- extend this pattern
var tab = document.createElement("button");
tab.className = "ide-ws-tab" + (ws.id === _activeWorkspaceId ? " active" : "");
tab.setAttribute("data-ws-id", ws.id);
tab.onclick = (function(wsId) {
  return function() { switchWorkspace(wsId); };
})(ws.id);

// Name span -- separate click handler for rename (D-19)
var nameSpan = document.createElement("span");
nameSpan.className = "ide-ws-tab-name";
nameSpan.textContent = ws.name;  // textContent -- safe, no escaping needed
nameSpan.onclick = (function(wsId, wsName) {
  return function(e) {
    e.stopPropagation();  // Don't trigger switchWorkspace
    if (wsId === _activeWorkspaceId) enterWsRenameMode(wsId, wsName, nameSpan);
  };
})(ws.id, ws.name);
tab.appendChild(nameSpan);

// Close button -- disabled when last workspace (D-10)
var closeBtn = document.createElement("button");
closeBtn.className = "ide-ws-tab-close";
closeBtn.textContent = "\u00d7";  // Unicode multiplication sign (times) -- safe
closeBtn.disabled = _workspaceList.length <= 1;
closeBtn.onclick = (function(wsId) {
  return function(e) {
    e.stopPropagation();  // Don't trigger switchWorkspace
    removeWorkspace(wsId);
  };
})(ws.id);
tab.appendChild(closeBtn);

container.appendChild(tab);
```

### Pattern 2: Add Workspace Modal

**What:** `showAddWorkspaceModal()` calls `showModal(html)` with a path input and optional app dropdown. Submit calls `api()` (POST), then pushes to `_workspaceList` and calls `switchWorkspace()`.

**When to use:** Triggered by "+" button click in `ideRenderWorkspaceTabs()`.

**Example:**
```javascript
// Source: showCreateTaskModal() at app.js:1515 -- same modal shell pattern
function showAddWorkspaceModal() {
  showModal(
    '<div class="modal">' +
      '<div class="modal-header"><h3>Add Workspace</h3>' +
        '<button class="btn btn-icon btn-outline" onclick="closeModal()">\u00d7</button>' +
      '</div>' +
      '<div class="modal-body">' +
        '<div class="form-group">' +
          '<label for="aw-path">Folder path</label>' +
          '<input type="text" id="aw-path" placeholder="/home/user/projects/myapp">' +
          '<div class="help">Enter the absolute path to a project folder on the server.</div>' +
        '</div>' +
        '<div id="aw-apps-section" style="display:none">' +
          '<div class="form-group">' +
            '<label for="aw-app">Or choose an Agent42 app</label>' +
            '<select id="aw-app" onchange="onAddWsAppChange(this.value)">' +
              '<option value="">-- select an app --</option>' +
            '</select>' +
          '</div>' +
        '</div>' +
      '</div>' +
      '<div class="modal-footer">' +
        '<button class="btn btn-outline" onclick="closeModal()">Cancel</button>' +
        '<button class="btn btn-primary" onclick="submitAddWorkspace()">Add</button>' +
      '</div>' +
    '</div>'
  );
  document.getElementById("aw-path").focus();
  // Must call AFTER showModal so the DOM elements exist
  _populateWsAppDropdown();
}
```

**Note on modal HTML construction:** The modal shell uses static HTML strings with no user-derived content interpolated at construction time. All user-provided values (app names) that go into dropdown options must be set via `textContent` or the `esc()` helper, never by concatenating raw strings into the template.

### Pattern 3: Remove Workspace with Guards

**What:** `removeWorkspace(wsId)` implements guards in sequence:
1. Frontend last-workspace gate (D-10)
2. Unsaved-files/CC-session count check (D-11)
3. Conditional `confirm()` call (D-12/D-13)
4. Redirect active workspace if needed (D-18) -- BEFORE teardown
5. API DELETE call
6. Terminal cleanup (D-14)
7. localStorage pruning (D-16)
8. In-memory state cleanup (D-17)
9. Re-render tabs + persist cache

**Critical ordering:** Redirect active workspace BEFORE deleting state (D-18 before D-17), so `switchWorkspace()` can read the current state dict for the workspace being removed.

**Example -- terminal closure on removal:**
```javascript
// Source: termClose() at app.js:6164 -- DO NOT call termClose() directly here
// termClose() operates on _termSessions (the alias), not _wsTermSessions[wsId]
// Iterate and close the workspace's session objects directly:
var terms = _wsTermSessions[removedId] || [];
for (var i = 0; i < terms.length; i++) {
  var s = terms[i];
  if (s.ws) s.ws.close();
  if (s.term) s.term.dispose();
  if (s.el) s.el.remove();
}
```

**localStorage pruning (D-16):**
```javascript
// Source: wsKey() at app.js:184 -- key prefix is "ws_{id}_"
// Only prune ws_{id}_* keys; leave cc_hist_{sessionId} alone (globally unique UUIDs)
var prefix = "ws_" + removedId + "_";
var keysToRemove = [];
for (var i = 0; i < localStorage.length; i++) {
  var k = localStorage.key(i);
  if (k && k.startsWith(prefix)) keysToRemove.push(k);
}
keysToRemove.forEach(function(k) { localStorage.removeItem(k); });
```

### Pattern 4: Inline Rename

**What:** `enterWsRenameMode(wsId, currentName, nameSpan)` replaces the span with an input, wires Enter/Escape/blur handlers, and calls `api()` (PATCH) on commit.

**When to use:** Only triggered when clicking an already-active tab's name span (D-19).

**Example:**
```javascript
function enterWsRenameMode(wsId, currentName, nameSpan) {
  var input = document.createElement("input");
  input.type = "text";
  input.value = currentName;
  input.maxLength = 64;  // D-24
  input.className = "ide-ws-rename-input";

  var committed = false;
  function commit() {
    if (committed) return;
    committed = true;
    var newName = input.value.trim();
    if (!newName) {
      // D-24: restore original on empty string
      nameSpan.textContent = currentName;
      input.replaceWith(nameSpan);
      return;
    }
    // Optimistic update: update UI immediately, rollback on server error
    for (var i = 0; i < _workspaceList.length; i++) {
      if (_workspaceList[i].id === wsId) { _workspaceList[i].name = newName; break; }
    }
    nameSpan.textContent = newName;  // textContent -- safe for user input
    input.replaceWith(nameSpan);
    api("/workspaces/" + wsId, { method: "PATCH", body: JSON.stringify({ name: newName }) })
      .catch(function(err) {
        // Rollback on server failure
        for (var i = 0; i < _workspaceList.length; i++) {
          if (_workspaceList[i].id === wsId) { _workspaceList[i].name = currentName; break; }
        }
        nameSpan.textContent = currentName;
        toast("Rename failed", "error");
      });
  }

  input.addEventListener("keydown", function(e) {
    if (e.key === "Enter") { e.preventDefault(); commit(); }
    if (e.key === "Escape") {
      committed = true;
      nameSpan.textContent = currentName;
      input.replaceWith(nameSpan);
    }
  });
  input.addEventListener("blur", commit);  // D-23: blur commits, not discards

  nameSpan.replaceWith(input);
  input.focus();
  input.select();
}
```

### Anti-Patterns to Avoid

- **Using user-derived content in string concatenation for DOM/modal:** Always use `textContent` for user-provided strings (workspace names, app names). The existing codebase enforces this via the `esc()` helper and direct `textContent` assignment.
- **Calling `termClose(idx)` on `_wsTermSessions[removedId]`:** `termClose()` operates on `_termSessions` (the current alias array), not the workspace-keyed dict. For removal, close the sessions directly by iterating `_wsTermSessions[removedId]` and closing WS/xterm objects manually, then delete the dict entry.
- **Switching workspace before the close guard resolves:** The `confirm()` call is synchronous, but the API DELETE is async. Do not call `switchWorkspace()` before the user confirms -- the active workspace must not change if the user cancels.
- **Forgetting to update `workspaces_cache` in localStorage after add/remove:** `initWorkspaceTabs()` uses `localStorage.getItem("workspaces_cache")` for stale-while-revalidate. After mutating `_workspaceList`, always write back: `try { localStorage.setItem("workspaces_cache", JSON.stringify(_workspaceList)); } catch(e) {}`

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Path validation | Client-side path existence check | POST /api/workspaces returning 400 (D-07) | Server has filesystem access; client does not. WorkspaceRegistry.create() already validates with Path.resolve() + .exists() + .is_dir() |
| App list fetch | Inline fetch in modal HTML | `_populateWsAppDropdown()` helper called post-render | Modal HTML renders synchronously; fetch is async. Separate the render from the data load. |
| Confirmation dialog | Custom overlay modal | `confirm()` (D-12) | Matches existing ideCloseTab() pattern (app.js:4103). Custom modal would add code complexity for no UX gain. |
| Duplicate detection | Server round-trip for duplicate check | Client-side scan of `_workspaceList` (D-08) | `_workspaceList` is authoritative in-memory state. No round-trip needed. |

**Key insight:** All server-side infrastructure is complete. This phase is 100% frontend. The planner should not schedule any backend tasks.

---

## Common Pitfalls

### Pitfall 1: Tab close button triggering switchWorkspace
**What goes wrong:** The close button is nested inside the workspace tab `<button>`. Click events bubble up, so clicking close switches workspace AND triggers removal.
**Why it happens:** Event bubbling in nested buttons.
**How to avoid:** Call `e.stopPropagation()` in the close button's onclick handler before calling `removeWorkspace()`. Same pattern required for the name span's rename click handler.
**Warning signs:** Workspace switches to the tab being closed before the confirm() dialog appears.

### Pitfall 2: termClose() index mismatch during workspace removal
**What goes wrong:** Calling `termClose(i)` inside a forward-iteration loop splices `_termSessions` while iterating, causing index shift and skipped sessions or crashes.
**Why it happens:** `termClose()` at app.js:6164 calls `_termSessions.splice(idx, 1)`, which shifts indices.
**How to avoid:** Do NOT use `termClose()` for workspace removal. Instead iterate `_wsTermSessions[removedId]` directly and close `.ws` and `.term` objects without splicing `_termSessions`. Then delete the dict key. The terminal alias (`_termSessions`) for the removed workspace no longer matters since the workspace is gone.
**Warning signs:** TypeError on `_termSessions[i].ws` after the first iteration.

### Pitfall 3: Stale workspaces_cache after add/remove
**What goes wrong:** After adding or removing a workspace, the next page reload restores the stale cached list and the user sees the old set of workspaces until the fresh fetch completes.
**Why it happens:** `initWorkspaceTabs()` uses `localStorage.getItem("workspaces_cache")` for stale-while-revalidate and only updates it from the server response. Client-side mutations don't update the cache.
**How to avoid:** After every `_workspaceList` mutation (push on add, splice on remove), write: `try { localStorage.setItem("workspaces_cache", JSON.stringify(_workspaceList)); } catch(e) {}`
**Warning signs:** Ghost tabs appearing on reload, or a workspace that was just added not surviving a refresh.

### Pitfall 4: Inline rename restores stale name on failed PATCH
**What goes wrong:** Optimistic update puts the new name in the UI immediately. If the PATCH fails, the catch handler must restore BOTH `nameSpan.textContent` AND `_workspaceList[i].name`. If only the span is restored but not `_workspaceList`, the next `ideRenderWorkspaceTabs()` call will re-render with the new (wrong) name from `_workspaceList`.
**Why it happens:** Two sources of truth: the `_workspaceList` array and the DOM span.
**How to avoid:** In the catch handler, restore both: `_workspaceList[i].name = currentName` AND `nameSpan.textContent = currentName`.
**Warning signs:** Tab shows old name visually but re-renders with new name on next workspace switch.

### Pitfall 5: App dropdown fetch races the modal render
**What goes wrong:** The modal HTML is inserted synchronously by `showModal()`, but `fetch("/api/apps")` is async. If `_populateWsAppDropdown()` is called before `showModal()` completes, `getElementById("aw-app")` returns null and the populate silently fails.
**Why it happens:** `showModal()` appends to `document.body` synchronously, so the elements are available immediately AFTER the call returns. The order matters.
**How to avoid:** Always call `_populateWsAppDropdown()` on the line immediately after `showModal(...)` -- not before, not inside the HTML template string.
**Warning signs:** App dropdown is empty with no console errors.

### Pitfall 6: Close button disabled state not updated after add
**What goes wrong:** After adding a second workspace, the first workspace's close button remains disabled.
**Why it happens:** If `ideRenderWorkspaceTabs()` is called before `_workspaceList` is updated with the new workspace, it still sees `length <= 1` and disables the close button.
**How to avoid:** Always update `_workspaceList` (push new workspace) BEFORE calling `ideRenderWorkspaceTabs()`. The function rebuilds the entire container from scratch, so the button disabled state will be correct if the list is up to date.
**Warning signs:** Close button on first tab stays greyed out after adding a second workspace.

---

## Code Examples

Verified patterns from the existing codebase:

### Existing modal shell pattern (from showCreateTaskModal, app.js:1529)
```javascript
showModal(`
  <div class="modal">
    <div class="modal-header"><h3>Title Here</h3>
      <button class="btn btn-icon btn-outline" onclick="closeModal()">&times;</button>
    </div>
    <div class="modal-body">
      <div class="form-group">
        <label for="field-id">Label</label>
        <input type="text" id="field-id" placeholder="...">
        <div class="help">Help text here.</div>
      </div>
    </div>
    <div class="modal-footer">
      <button class="btn btn-outline" onclick="closeModal()">Cancel</button>
      <button class="btn btn-primary" onclick="submitFn()">Add</button>
    </div>
  </div>
`);
document.getElementById("field-id")?.focus();
```

### api() helper signature (app.js:224)
```javascript
// api() wraps fetch with auth headers; returns parsed JSON or throws
async function api(path, opts = {}) {
  const headers = { "Content-Type": "application/json" };
  if (state.token) headers["Authorization"] = `Bearer ${state.token}`;
  const res = await fetch(`${API}${path}`, { ...opts, headers });
  // throws on 401, returns res.json() on success
}
```

### Existing unsaved-files confirm pattern (app.js:4103)
```javascript
if (tab.modified && !confirm("Discard unsaved changes to " + tab.path + "?")) return;
```

### wsKey() for localStorage key naming (app.js:184)
```javascript
function wsKey(workspaceId, key) {
  return "ws_" + workspaceId + "_" + key;
}
// Pruning prefix: "ws_" + workspaceId + "_"
```

### WorkspaceRegistry.create() raises ValueError on bad path (workspace_registry.py:141)
```python
async def create(self, name: str, root_path: str) -> Workspace:
    resolved = Path(root_path).resolve()
    if not resolved.exists():
        raise ValueError(f"Path does not exist: {root_path}")
    if not resolved.is_dir():
        raise ValueError(f"Path is not a directory: {root_path}")
```

### GET /api/apps response structure (server.py:5382)
```python
@app.get("/api/apps")
async def list_apps(mode: str = "", _user: str = Depends(get_current_user)):
    apps = app_manager.list_apps()
    return [a.to_dict() for a in apps]
# Each app dict has id, name, and a path field -- verify exact field name before use
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Tab bar hidden when 1 workspace | Tab bar always visible (D-02) | Phase 3 | Lift `_workspaceList.length <= 1` hide guard in `ideRenderWorkspaceTabs()` |
| Plain `<button>` tab element | Composite tab with name span + close button | Phase 3 | Rebuild tab DOM construction in `ideRenderWorkspaceTabs()` |

---

## Open Questions

1. **App `root_path` field name in `app.to_dict()`**
   - What we know: `GET /api/apps` returns `[a.to_dict() for a in apps]`. The App dataclass structure was not inspected in this research.
   - What's unclear: The exact field name for the app's directory path (could be `root_path`, `path`, `directory`, `app_dir`).
   - Recommendation: Read the `App` dataclass or `AppManager` class before writing `onAddWsAppChange()`. The dropdown auto-fill reads `app.{field}` to populate the path input -- verify the field name before coding D-04.

2. **`app_manager` availability indicator from frontend**
   - What we know: D-05 says "if `app_manager` is not configured, dropdown section is hidden entirely." The indication is via a fetch to `GET /api/apps`.
   - What's unclear: Whether `GET /api/apps` returns 503 when `app_manager` is not configured, or always returns an empty array.
   - Recommendation: Handle both: hide the app section if the fetch fails (network error or 503) OR if the response is an empty array. This is the safe default.

---

## Environment Availability

Step 2.6: SKIPPED (no external dependencies -- this phase is frontend JS + CSS only; all backend endpoints are already deployed and tested).

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 7+ with pytest-asyncio |
| Config file | pyproject.toml (`asyncio_mode = "auto"`) |
| Quick run command | `python -m pytest tests/test_workspace_registry.py -x -q` |
| Full suite command | `python -m pytest tests/ -x -q` |

### Phase Requirements to Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| MGMT-01 | POST /api/workspaces creates workspace from valid path | integration | `python -m pytest tests/test_workspace_registry.py::TestWorkspaceEndpoints::test_create_workspace_valid_path -x` | Yes |
| MGMT-01 | POST /api/workspaces returns 400 on invalid path | integration | `python -m pytest tests/test_workspace_registry.py::TestWorkspaceEndpoints::test_create_workspace_rejects_bad_path -x` | Yes |
| MGMT-02 | DELETE /api/workspaces/{id} removes a workspace | integration | `python -m pytest tests/test_workspace_registry.py::TestWorkspaceEndpoints::test_delete_workspace -x` | Yes |
| MGMT-03 | PATCH /api/workspaces/{id} renames a workspace | integration | `python -m pytest tests/test_workspace_registry.py::TestWorkspaceEndpoints::test_update_workspace -x` | Yes |
| MGMT-01/02/03 | Frontend modal, close guard, inline rename (browser UX) | manual-only | n/a -- browser-only DOM interactions | n/a |

**Note on manual testing:** The frontend JS cannot be unit tested with pytest. The three user-facing behaviors (modal UX, close guard confirm(), inline rename input) require manual browser verification. Per `feedback_playwright_testing.md`, manual UAT items should be exercised via Playwright, not by asking the user.

### Sampling Rate
- **Per task commit:** `python -m pytest tests/test_workspace_registry.py -x -q`
- **Per wave merge:** `python -m pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
None -- existing test infrastructure covers all backend requirements for this phase. Frontend-only behaviors have no automated test coverage; that gap is pre-existing and out of scope for this phase.

---

## Sources

### Primary (HIGH confidence)
- `dashboard/frontend/dist/app.js` lines 3444-3623 -- workspace state vars, `initWorkspaceTabs()`, `ideRenderWorkspaceTabs()`, `switchWorkspace()`
- `dashboard/frontend/dist/app.js` lines 1497-1574 -- `showModal()`/`closeModal()`, `showCreateTaskModal()` modal shell pattern
- `dashboard/frontend/dist/app.js` lines 4090-4122 -- `ideCloseTab()` with `tab.modified && confirm()` guard pattern
- `dashboard/frontend/dist/app.js` lines 6164-6174 -- `termClose()` implementation
- `dashboard/frontend/dist/app.js` lines 180-199 -- `wsKey()` localStorage namespace function
- `dashboard/frontend/dist/app.js` lines 224-240 -- `api()` fetch wrapper
- `dashboard/frontend/dist/app.js` lines 1739-1744 -- `esc()` XSS-safe escaping function
- `dashboard/frontend/dist/style.css` lines 1820-1851 -- `.ide-workspace-tabs`, `.ide-ws-tab` CSS
- `dashboard/frontend/dist/style.css` lines 407-430 -- `.modal`, `.modal-header`, `.modal-body`, `.modal-footer` CSS
- `core/workspace_registry.py` -- full WorkspaceRegistry CRUD implementation
- `dashboard/server.py` lines 1297-1344 -- `/api/workspaces` CRUD endpoints
- `dashboard/server.py` lines 5382-5389 -- `GET /api/apps` endpoint
- `tests/test_workspace_registry.py` -- existing test coverage (36 tests, all passing as of 2026-03-24)

### Secondary (MEDIUM confidence)
- VS Code tab bar convention for "+" button placement and blur-commits rename -- observed industry convention, not from official docs

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- project uses vanilla JS with no build toolchain; all endpoints verified in source
- Architecture patterns: HIGH -- all patterns derived directly from existing app.js code with line references
- Pitfalls: HIGH -- pitfalls are derived from reading actual implementation details (splice behavior, event bubbling, async race conditions visible in existing codebase)

**Research date:** 2026-03-24
**Valid until:** 2026-04-24 (stable frontend/backend -- no external dependencies)
