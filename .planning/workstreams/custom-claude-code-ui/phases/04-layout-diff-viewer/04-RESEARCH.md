# Phase 4: Layout + Diff Viewer - Research

**Researched:** 2026-03-19
**Domain:** Vanilla JS IDE layout (flexbox panel split, drag-resize, localStorage) + Monaco diff editor API
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Side panel mode (LAYOUT-02)**
- Panel sits right of the editor area, splitting the `.ide-main` container horizontally
- Editor shrinks, CC panel appears to the right — VS Code convention
- Terminal panel stays full-width below (not affected by the split)
- Vertical drag handle between editor and CC panel for free resize (reuse terminal drag-handle pattern)
- Min width ~250px, max ~60% of editor area
- Panel width persisted to localStorage, restored on page load
- Default width: ~35% of editor area on first open

**Panel activation (LAYOUT-01, LAYOUT-02)**
- New CC icon in the activity bar (left rail) — click toggles the right panel
- Activity bar icon is the single entry point for panel mode
- CC tab from existing editor tab "+" button and terminal dropdown remain for tab mode
- Welcome screen button continues to open as tab

**Tab-to-panel switching (LAYOUT-03)**
- One mode at a time — CC is either in a tab OR in the panel, never both simultaneously
- Activity bar CC icon is the toggle:
  - CC in tab → click icon → session moves to panel (tab closes, WS connection preserved)
  - CC in panel → click icon → session moves to tab (panel closes)
  - No CC open → click icon → opens new session in panel
- Session state (WS connection, chat history, trust mode) transfers seamlessly between modes
- Multi-session tabs behavior: all CC tabs move to panel mode together (session tab strip renders in panel header)

**Diff viewer (LAYOUT-04)**
- Diff opens as a new editor tab using Monaco's `createDiffEditor()` (v0.52.2 already loaded)
- Side-by-side mode (original left, modified right) — Monaco default
- Tab title: `filename ↔ Changes`
- NOT auto-opened — triggered by user clicking "View Diff" button on Write/Edit tool cards
- Tool cards for Write/Edit operations get two action buttons: "View Diff" and "Open File"
- Diff data source: original content fetched via existing `GET /api/ide/file`, modified content from tool card's content block
- Diff tab is read-only (review only, not an editor)
- Uses existing `agent42-dark` Monaco theme

### Claude's Discretion
- Activity bar CC icon design (color, shape — match existing Explorer/Search icon style)
- Panel open/close animation (slide or instant)
- Drag handle visual styling (match terminal drag handle)
- "View Diff" button styling on tool cards
- Diff tab close behavior (auto-close when CC session ends, or persist)
- How to handle diff when original file doesn't exist (new file — show empty left pane)

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| LAYOUT-01 | CC interface opens as an editor tab in the main editor area | Already implemented by `ideOpenCCChat()` — this phase validates and ensures the tab path is the default entry point alongside panel mode |
| LAYOUT-02 | CC interface can also open as a dedicated resizable side panel (right) | New `#ide-cc-panel` container + vertical drag handle inside `.ide-main`; `initPanelDragHandle()` reusing `initDragHandle()` pattern; localStorage width persistence |
| LAYOUT-03 | User can switch between tab and panel modes | New `ideToggleCCPanel()` function; session DOM element moved between `#ide-cc-container` and `#ide-cc-panel` without closing WS; `ideCloseTab()` extended for panel-side tab closes |
| LAYOUT-04 | Diff viewer uses Monaco's built-in diff editor for proposed code changes | `monaco.editor.createDiffEditor()` confirmed at v0.52.2; `ideOpenDiffTab()` creates tab with `type: "diff"`; `ideActivateTab()` extended to show/dispose diff editors |
</phase_requirements>

---

## Summary

Phase 4 is a pure frontend change — no backend work required. All four requirements are implemented by editing `dashboard/frontend/dist/app.js` and `dashboard/frontend/dist/style.css` only. The codebase already has every reusable building block; this phase wires them together.

The layout split (LAYOUT-02) converts `.ide-main` from a single-column container into a two-column flex row when the CC panel is active. The existing terminal drag-handle pattern (`initDragHandle`, `_isDragging`, `mousedown/mousemove/mouseup`) is the direct template for the new vertical panel drag handle — the only change is axis (ew-resize instead of ns-resize) and the target element.

Tab-to-panel switching (LAYOUT-03) is the most complex task: it must move the CC session's DOM element without destroying it, preserve the live WS connection, and update the tab strip to reflect the mode change. The existing `ccMakeWsHandler` factory (Phase 3) ensures WS handler logic is already decoupled from the DOM container, making the move safe.

The Monaco diff editor (LAYOUT-04) is fully supported at v0.52.2. `monaco.editor.createDiffEditor()` accepts the same container div pattern as `monaco.editor.create()` and uses `diffEditor.setModel({original, modified})`. The existing `_ideTabs[]` array only needs a new `type: "diff"` entry with `diffEditor` and `diffOriginalModel`/`diffModifiedModel` stored on the tab object for proper disposal.

**Primary recommendation:** Implement in four waves: (1) CSS for panel container + drag handle, (2) panel open/close + activity bar icon, (3) tab↔panel mode transfer, (4) diff tab + tool card buttons.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Monaco Editor | v0.52.2 (already loaded via `/vs/loader.js`) | Diff editor | Already in production; `createDiffEditor` is first-class API |
| Vanilla JS | ES5 (project convention) | All IDE JS | No build toolchain; all app.js is plain ES5 var/function style |
| CSS Flexbox | Browser-native | Panel split layout | Entire IDE already flex-based; `.ide-main { display:flex; flex-direction:column }` |
| localStorage | Browser-native | Panel width persistence | Already the project's state persistence pattern for IDE settings |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `GET /api/ide/file` | Existing endpoint | Fetch original file content for diff | Diff viewer only — already used elsewhere in the IDE |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `createDiffEditor()` | Two `create()` editors side-by-side with manual diff | `createDiffEditor` has built-in diff computation, navigation, change highlighting — never hand-roll this |
| `localStorage` for panel width | `sessionStorage` | localStorage survives tab close — correct for panel width preference |

**Installation:** No new packages — Monaco and all needed libraries already loaded.

---

## Architecture Patterns

### Recommended Project Structure

No new files required. All changes are within:
```
dashboard/frontend/dist/
├── app.js        # All JS additions (functions + HTML template string changes)
└── style.css     # New CSS classes for panel + drag handle
```

### Pattern 1: The `.ide-main` Flex Layout Split

**What:** `.ide-main` changes from `flex-direction:column` (full-width editor stack) to `flex-direction:row` when panel opens. The CC panel div sits as a sibling to `#ide-editor-container` and `#ide-cc-container` inside `.ide-main`.

**Current structure:**
```
.ide-main (flex-direction:column)
  ├── #ide-tabs
  ├── #ide-editor-container  (flex:1)
  ├── #ide-cc-container      (display:none)
  └── #ide-welcome           (display:flex)
```

**Panel-open structure:**
```
.ide-main (flex-direction:row when panel open)
  ├── .ide-main-editor-area  (flex:1, flex-direction:column — wraps tabs + editor + cc-container + welcome)
  ├── .ide-panel-drag-handle (width:3px, cursor:ew-resize)
  └── #ide-cc-panel          (flex:none, width:<saved>px or 35%)
```

**Key insight:** The tabs bar (`#ide-tabs`) must stay with the editor, not span full width. This means the HTML template needs a wrapper div `.ide-main-editor-area` to contain tabs + editor containers, with the CC panel outside that wrapper.

**Alternative approach (simpler, avoids HTML template change):** Keep the current structure and position `#ide-cc-panel` as an absolutely positioned right-side overlay, adjusting `#ide-editor-container` right margin/padding dynamically. This is simpler but fights with Monaco's `automaticLayout: true`. **Recommended approach: add the `.ide-main-editor-area` wrapper** and do it properly.

### Pattern 2: Vertical Drag Handle (ew-resize)

**What:** Adapts the existing `initDragHandle()` (terminal ns-resize) for horizontal panel resize.

**Existing terminal pattern (`initDragHandle`):**
```javascript
// Source: app.js line 5421
handle.addEventListener("mousedown", function(e) {
  _isDragging = true;
  _dragStartY = e.clientY;  // <-- Y axis for ns-resize
  _dragStartHeight = wrapper.getBoundingClientRect().height;
  document.body.style.cursor = "ns-resize";
  ...
});
document.addEventListener("mousemove", function(e) {
  if (!_isDragging) return;
  var delta = _dragStartY - e.clientY;
  var newHeight = Math.max(80, Math.min(_dragStartHeight + delta, window.innerHeight * 0.8));
  wrapper.style.height = newHeight + "px";
  wrapper.style.flex = "none";
  termFitAll();
});
```

**New panel drag handle pattern:**
```javascript
// New variables (separate namespace from terminal drag)
var _isPanelDragging = false;
var _panelDragStartX = 0;
var _panelDragStartWidth = 0;

function initPanelDragHandle() {
  var handle = document.getElementById("ide-panel-drag-handle");
  if (!handle) return;
  handle.addEventListener("mousedown", function(e) {
    _isPanelDragging = true;
    _panelDragStartX = e.clientX;
    var panel = document.getElementById("ide-cc-panel");
    _panelDragStartWidth = panel ? panel.getBoundingClientRect().width : 400;
    document.body.style.cursor = "ew-resize";
    document.body.style.userSelect = "none";
    e.preventDefault();
  });
  document.addEventListener("mousemove", function(e) {
    if (!_isPanelDragging) return;
    var delta = _panelDragStartX - e.clientX;  // dragging left increases panel width
    var mainArea = document.querySelector(".ide-main-editor-area");
    var maxWidth = mainArea ? mainArea.getBoundingClientRect().width * 0.6 : 600;
    var newWidth = Math.max(250, Math.min(_panelDragStartWidth + delta, maxWidth));
    var panel = document.getElementById("ide-cc-panel");
    if (panel) { panel.style.width = newWidth + "px"; panel.style.flex = "none"; }
    // Monaco needs layout update when container resizes
    if (_monacoEditor) _monacoEditor.layout();
  });
  document.addEventListener("mouseup", function() {
    if (!_isPanelDragging) return;
    _isPanelDragging = false;
    document.body.style.cursor = "";
    document.body.style.userSelect = "";
    // Persist to localStorage
    var panel = document.getElementById("ide-cc-panel");
    if (panel) localStorage.setItem("cc_panel_width", panel.getBoundingClientRect().width);
  });
}
```

**Monaco layout refresh:** Whenever the panel drag changes editor container size, `_monacoEditor.layout()` must be called because Monaco's `automaticLayout: true` uses a ResizeObserver that may lag. This is a known Monaco gotcha.

### Pattern 3: Activity Bar CC Toggle (`ideToggleCCPanel`)

**What:** A new function that implements the three-state toggle logic from CONTEXT.md.

```javascript
var _ccPanelMode = false;  // true when CC UI is in panel (not tab)

function ideToggleCCPanel() {
  var ccTabs = _ideTabs.filter(function(t) { return t.type === "claude"; });

  if (_ccPanelMode) {
    // Panel → Tab: move all CC tabs back into #ide-cc-container, close panel
    ideMoveSessionsToTab();
    ideCloseCCPanel();
  } else if (ccTabs.length > 0) {
    // CC is in tab(s) → move to panel
    ideOpenCCPanel();
    ideMoveSessionsToPanel();
  } else {
    // No CC open → open new session in panel
    ideOpenCCPanel();
    ideOpenCCChatInPanel("local");
  }
}
```

**Session DOM transfer (tab → panel):**
- The `tab.el` (the `.ide-cc-chat` div) is already a standalone DOM element
- Move it: `panelContent.appendChild(tab.el)` — no WS close/reopen needed
- The WS connection is on `tab.ws` which is independent of DOM position
- Update `tab.chatPanel` flag and re-render tabs (tab entry removed from `#ide-tabs`)

### Pattern 4: Monaco Diff Editor Tab

**What:** Extends `_ideTabs[]` with a new `type: "diff"` entry. `ideActivateTab()` gets a new branch for diff tabs.

**Confirmed API (Context7 / official docs):**
```javascript
// Source: Context7 /microsoft/monaco-editor — createDiffEditor
var diffEditor = monaco.editor.createDiffEditor(container, {
  automaticLayout: true,
  renderSideBySide: true,   // side-by-side (default true)
  readOnly: true,           // modified pane read-only — NOTE: apply to each editor separately (see Pitfall 3)
  originalEditable: false,
  theme: "agent42-dark"     // inherited from global theme definition
});
diffEditor.setModel({
  original: originalModel,
  modified: modifiedModel
});
```

**Tab object shape for diff:**
```javascript
var tab = {
  type: "diff",
  path: filename + " ↔ Changes",
  chatPanel: false,
  diffEditor: diffEditor,       // monaco IStandaloneDiffEditor
  diffOriginalModel: origModel, // for dispose()
  diffModifiedModel: modModel,  // for dispose()
  el: container,                // the div the diff editor lives in
};
```

**`ideActivateTab()` extension for diff tabs:**
```javascript
} else if (tab.type === "diff") {
  if (_monacoEditor) _monacoEditor.setModel(null);
  if (container) container.style.display = "none";
  if (ccContainer) ccContainer.style.display = "none";
  if (welcome) welcome.style.display = "none";
  // Show the diff container div
  if (tab.el) {
    tab.el.style.display = "block";
    tab.diffEditor.layout();
  }
}
```

**`ideCloseTab()` extension for diff tabs:**
```javascript
} else if (tab.type === "diff") {
  if (tab.diffEditor) tab.diffEditor.dispose();
  if (tab.diffOriginalModel) tab.diffOriginalModel.dispose();
  if (tab.diffModifiedModel) tab.diffModifiedModel.dispose();
  if (tab.el) tab.el.remove();
}
```

### Pattern 5: `ideOpenDiffTab()` Function

```javascript
function ideOpenDiffTab(filename, originalContent, modifiedContent, language) {
  language = language || ideDetectLanguage(filename) || "plaintext";

  // Create a container div inside ide-editor-container's parent
  var editorArea = document.querySelector(".ide-main-editor-area") || document.getElementById("ide-editor-container").parentNode;
  var diffContainer = document.createElement("div");
  diffContainer.style.cssText = "flex:1;overflow:hidden;display:none";
  editorArea.appendChild(diffContainer);

  var origModel = monaco.editor.createModel(originalContent, language);
  var modModel = monaco.editor.createModel(modifiedContent, language);

  var diffEditor = monaco.editor.createDiffEditor(diffContainer, {
    automaticLayout: true,
    renderSideBySide: true,
    originalEditable: false,
    enableSplitViewResizing: true,
    theme: "agent42-dark"
  });
  diffEditor.setModel({ original: origModel, modified: modModel });

  var tab = {
    type: "diff",
    path: filename.split("/").pop() + " \u2194 Changes",
    chatPanel: false,
    diffEditor: diffEditor,
    diffOriginalModel: origModel,
    diffModifiedModel: modModel,
    el: diffContainer,
    modified: false,
  };
  _ideTabs.push(tab);
  _ideActiveTab = _ideTabs.length - 1;
  ideActivateTab();
}
```

### Anti-Patterns to Avoid

- **Closing and reopening WS for mode transfer:** The WS connection (`tab.ws`) is on the tab object, not the DOM. Never close it during a tab↔panel move — just reparent `tab.el`.
- **Using a single `_isDragging` flag for both drag handles:** The existing `_isDragging` is used by `initDragHandle()`. Use a separate `_isPanelDragging` variable with its own mousedown/mousemove/mouseup handlers attached to `document`.
- **Forgetting `_monacoEditor.layout()` after panel resize:** Monaco's `automaticLayout: true` uses a ResizeObserver that may not fire synchronously during drag. Call `_monacoEditor.layout()` in the panel mousemove handler.
- **Reusing `#ide-cc-container` for panel mode:** `#ide-cc-container` is inside `.ide-main-editor-area`. The new `#ide-cc-panel` must be a separate sibling element outside the editor area. Never try to "move" `#ide-cc-container` — create a new panel container in the HTML template.
- **Missing `diffEditor.dispose()` on tab close:** Monaco diff editors hold significant memory. Always dispose both the diff editor and both models in `ideCloseTab()`.
- **Setting `readOnly: true` on `createDiffEditor` options:** The `readOnly` option applies to the editor as a whole but doesn't guarantee both panes are read-only. Use `originalEditable: false` for the original pane; for read-only modified pane, use `diffEditor.getModifiedEditor().updateOptions({ readOnly: true })` after creation.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Side-by-side diff with syntax highlight | Two Monaco instances + manual diff algorithm | `monaco.editor.createDiffEditor()` | Built-in diff computation, line change navigation, inline/side-by-side toggle, all with syntax highlighting |
| Panel width persistence | Custom serialization | `localStorage.setItem("cc_panel_width", px)` | One line; browser-native; no library needed |
| Language detection for diff | Custom extension→language map | `ideDetectLanguage()` — already exists in app.js | Already maps .py, .js, .ts, .css, .json, etc. |
| Monaco layout refresh on panel resize | Polling resize observer | `_monacoEditor.layout()` direct call | Monaco's `automaticLayout` has ResizeObserver lag during active drag; direct call is instant |

**Key insight:** The entire phase avoids building anything from scratch. Every problem has an existing solution in the codebase or in Monaco's first-class API.

---

## Common Pitfalls

### Pitfall 1: `.ide-main` flex-direction change breaks tab bar width
**What goes wrong:** When `.ide-main` switches to `flex-direction: row` to accommodate the CC panel, `#ide-tabs` (which is a direct child) becomes a narrow column instead of spanning the editor width.
**Why it happens:** `#ide-tabs` is currently a sibling of `#ide-editor-container` inside `.ide-main`. Making `.ide-main` a row container puts the tabs bar alongside the editor, not above it.
**How to avoid:** Wrap `#ide-tabs`, `#ide-editor-container`, `#ide-cc-container`, and `#ide-welcome` in a new `.ide-main-editor-area` div (`flex:1; display:flex; flex-direction:column`). The CC panel and drag handle are siblings of `.ide-main-editor-area` inside `.ide-main`. This means a **HTML template string change** in the `renderCode()` function around line 3259.
**Warning signs:** Tab bar appears as a narrow strip on the left; Monaco editor doesn't fill the editor area.

### Pitfall 2: `_isDragging` flag collision between terminal and panel drag handles
**What goes wrong:** Both `initDragHandle()` (terminal resize) and the new panel drag handle use document-level mousemove/mouseup listeners. If they share `_isDragging`, dragging the terminal handle will also resize the CC panel.
**Why it happens:** ES5 globals are all in the same scope.
**How to avoid:** Use distinct variable names: `_isPanelDragging`, `_panelDragStartX`, `_panelDragStartWidth` — completely separate from the terminal's `_isDragging`, `_dragStartY`, `_dragStartHeight`.
**Warning signs:** Terminal drag also moves the CC panel; panel drag also resizes the terminal.

### Pitfall 3: Monaco diff editor `readOnly` option behavior
**What goes wrong:** Setting `readOnly: true` in `createDiffEditor()` options may not make both panes read-only in all Monaco versions.
**Why it happens:** `createDiffEditor()` options are passed to the wrapper; individual editor instances (original/modified) may need separate `updateOptions()`.
**How to avoid:** After creating the diff editor, explicitly call:
```javascript
diffEditor.getOriginalEditor().updateOptions({ readOnly: true });
diffEditor.getModifiedEditor().updateOptions({ readOnly: true });
```
Also set `originalEditable: false` in the constructor options.
**Warning signs:** User can type in the diff pane; changes are silently discarded.

### Pitfall 4: `ideActivateTab()` doesn't handle `type: "diff"` — wrong pane shown
**What goes wrong:** `ideActivateTab()` only handles `"claude"` and generic (file) tab types. A diff tab activates and shows `#ide-editor-container` with the Monaco file editor, not the diff container.
**Why it happens:** New tab type requires new branch in `ideActivateTab()`.
**How to avoid:** Add explicit `} else if (tab.type === "diff") {` branch that hides the editor container, shows `tab.el` (the diff container div), and calls `tab.diffEditor.layout()`.
**Warning signs:** Clicking a diff tab shows the last open file in Monaco, not the diff.

### Pitfall 5: Session DOM reparenting loses event listeners attached via `.onclick`
**What goes wrong:** Moving `tab.el` (the CC chat div) from `#ide-cc-container` to `#ide-cc-panel` via `appendChild()` in principle preserves event listeners attached via `addEventListener()`. However, if any buttons in the chat div were wired via `setAttribute("onclick", ...)` (which most are in this codebase), those listeners survive fine since they're inline handlers.
**Why it happens:** This is actually not a problem for this codebase — all CC chat handlers use `setAttribute("onclick", ...)` pattern.
**How to avoid:** No action needed — just verify DOM move works correctly. `appendChild()` on an existing child node moves it (no clone needed).
**Warning signs:** Buttons in the moved CC chat div stop responding (would indicate `addEventListener` was used).

### Pitfall 6: Diff tab container div placement
**What goes wrong:** The diff container div is appended to the wrong parent — e.g., inside `#ide-cc-container` — and gets hidden when the CC container is hidden.
**Why it happens:** `#ide-editor-container`, `#ide-cc-container`, `#ide-welcome` are siblings inside `.ide-main-editor-area`. The diff container should be another sibling at the same level.
**How to avoid:** Append `diffContainer` to `.ide-main-editor-area` (or its equivalent wrapper), not to any existing content container.
**Warning signs:** Diff tab appears blank; diff container is hidden when activating the diff tab.

### Pitfall 7: Panel width stored before layout stabilizes
**What goes wrong:** `localStorage.setItem("cc_panel_width", ...)` on `mouseup` reads the panel width before the browser has reflow-applied the CSS change, getting 0 or stale value.
**Why it happens:** `getBoundingClientRect()` reads computed layout, which is up-to-date. This is fine — `getBoundingClientRect()` forces synchronous reflow. Using `panel.style.width` instead would give the CSS string, not pixels.
**How to avoid:** Use `panel.getBoundingClientRect().width` in the `mouseup` handler.

---

## Code Examples

Verified patterns from official sources:

### Monaco diff editor (from Context7 /microsoft/monaco-editor)
```javascript
// Source: Context7 — createDiffEditor
var diffEditor = monaco.editor.createDiffEditor(container, {
  automaticLayout: true,
  renderSideBySide: true,   // side-by-side (true = default)
  originalEditable: false,
  enableSplitViewResizing: true
});
diffEditor.setModel({
  original: monaco.editor.createModel(originalText, language),
  modified: monaco.editor.createModel(modifiedText, language)
});
// After creation, make both panes read-only
diffEditor.getOriginalEditor().updateOptions({ readOnly: true });
diffEditor.getModifiedEditor().updateOptions({ readOnly: true });
// Cleanup
diffEditor.dispose(); origModel.dispose(); modModel.dispose();
```

### Existing drag handle pattern to adapt (app.js ~line 5421)
```javascript
// Source: app.js initDragHandle() — adapt for ew-resize
var _isDragging = false;      // reuse name ONLY for terminal; new handle uses _isPanelDragging
handle.addEventListener("mousedown", function(e) {
  _isDragging = true;
  _dragStartY = e.clientY;
  _dragStartHeight = wrapper.getBoundingClientRect().height;
  document.body.style.cursor = "ns-resize";
  document.body.style.userSelect = "none";
  e.preventDefault();
});
```

### Existing `ideShowPanel()` pattern to extend (app.js ~line 5218)
```javascript
// Source: app.js ideShowPanel() — existing activity bar toggle pattern
function ideShowPanel(panel, evt) {
  // Toggle: clicking active panel hides sidebar
  if (panel === _ideActivePanel && _ideSidebarVisible) {
    _ideSidebarVisible = false;
    sidebar.style.display = "none";
    return;
  }
  _ideSidebarVisible = true;
  _ideActivePanel = panel;
  // ... show/hide sidebar contents
}
// New CC icon adds a third entry to activity bar; ideToggleCCPanel() follows same toggle pattern
```

### DOM element move (no WS disruption)
```javascript
// Moving tab.el from #ide-cc-container to #ide-cc-panel
// appendChild on an existing node MOVES it (does not clone)
var panel = document.getElementById("ide-cc-panel");
panel.appendChild(tab.el);   // tab.ws remains open, no disruption
tab.inPanel = true;          // track current mode
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Manual diff computation + display | `monaco.editor.createDiffEditor()` | Monaco v0.20+ | Side-by-side diff with syntax highlighting, change navigation built-in |
| CSS absolute positioning for panels | CSS flexbox sibling layout | Industry standard since 2018 | Monaco `automaticLayout: true` works correctly with flex siblings |

**Deprecated/outdated:**
- `monaco.editor.createDiffEditor` `readOnly` constructor option: Not reliable for making both panes read-only; use `getOriginalEditor().updateOptions()` / `getModifiedEditor().updateOptions()` post-construction.

---

## Open Questions

1. **`ideDetectLanguage()` — does it exist?**
   - What we know: The app.js has language detection (e.g., status bar shows language). A `ideGetLanguage()` or similar may exist.
   - What's unclear: Exact function name. Grep for "function ideDetect" or "language.*split" in app.js before implementing.
   - Recommendation: Search for existing language detection function; if none, add a simple `ideDetectLanguage(filename)` that maps `.py → python`, `.js → javascript`, `.ts → typescript`, `.css → css`, `.json → json` — 10-line function.

2. **Diff tab "View Diff" button: Phase 3 tool cards — are Write/Edit cards already rendered?**
   - What we know: Phase 3 is complete; tool cards exist for all tools. TOOL-04 covers file read/write tools.
   - What's unclear: Whether the existing Write/Edit tool card rendering checks `ccToolType()` for file operations and has a place to add action buttons.
   - Recommendation: Read `ccCreateToolCard` and `ccToolType` in app.js before Plan 04-04. The "View Diff" button only needs to be added to cards where `ccToolType(name)` returns `"file"` and the tool is a write operation.

3. **Monaco theme inheritance: does `createDiffEditor` inherit `agent42-dark`?**
   - What we know: `monaco.editor.defineTheme("agent42-dark", ...)` is called once globally in `ideInitMonaco()`. Monaco themes are global registry.
   - What's unclear: Whether passing `theme: "agent42-dark"` to `createDiffEditor` options is sufficient, or if the theme must be set after the diff editor is constructed.
   - Recommendation: Pass `theme: "agent42-dark"` in constructor options — this should work since the theme is already registered when `ideInitMonaco()` runs before any diff editor is created. LOW risk; easy to verify.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.2 with pytest-asyncio |
| Config file | `pyproject.toml` — `[tool.pytest.ini_options]`, `asyncio_mode = "auto"` |
| Quick run command | `python -m pytest tests/test_cc_layout.py -x -q` |
| Full suite command | `python -m pytest tests/ -x -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| LAYOUT-01 | CC opens as editor tab (default path preserved) | source inspection | `python -m pytest tests/test_cc_layout.py::TestCCPanelLayout::test_cc_tab_default_path -x` | ❌ Wave 0 |
| LAYOUT-02 | Panel container, drag handle, activity bar CC icon present in HTML | source inspection | `python -m pytest tests/test_cc_layout.py::TestCCPanelLayout::test_panel_container_present -x` | ❌ Wave 0 |
| LAYOUT-02 | Panel width localStorage persistence in JS | source inspection | `python -m pytest tests/test_cc_layout.py::TestCCPanelLayout::test_panel_width_persistence -x` | ❌ Wave 0 |
| LAYOUT-03 | `ideToggleCCPanel` function defined in app.js | source inspection | `python -m pytest tests/test_cc_layout.py::TestCCPanelLayout::test_toggle_function_defined -x` | ❌ Wave 0 |
| LAYOUT-03 | Session transfer: panel-mode uses `_ccPanelMode` flag | source inspection | `python -m pytest tests/test_cc_layout.py::TestCCPanelLayout::test_panel_mode_flag -x` | ❌ Wave 0 |
| LAYOUT-04 | `ideOpenDiffTab` function defined in app.js | source inspection | `python -m pytest tests/test_cc_layout.py::TestDiffViewer::test_open_diff_tab_defined -x` | ❌ Wave 0 |
| LAYOUT-04 | `createDiffEditor` used in app.js | source inspection | `python -m pytest tests/test_cc_layout.py::TestDiffViewer::test_create_diff_editor_used -x` | ❌ Wave 0 |
| LAYOUT-04 | "View Diff" button in tool card for file tools | source inspection | `python -m pytest tests/test_cc_layout.py::TestDiffViewer::test_view_diff_button_on_file_tools -x` | ❌ Wave 0 |
| LAYOUT-04 | Diff tab uses `agent42-dark` theme | source inspection | `python -m pytest tests/test_cc_layout.py::TestDiffViewer::test_diff_uses_agent42_dark_theme -x` | ❌ Wave 0 |

**All tests use the established source-inspection pattern** (read `app.js` as text, assert substrings) matching `test_cc_chat_ui.py`, `test_cc_tool_use.py`, and `test_ide_html.py`. No browser automation required.

### Sampling Rate
- **Per task commit:** `python -m pytest tests/test_cc_layout.py -x -q`
- **Per wave merge:** `python -m pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_cc_layout.py` — covers LAYOUT-01 through LAYOUT-04 (new file, matches established Phase 2/3 pattern)

---

## Sources

### Primary (HIGH confidence)
- Context7 `/microsoft/monaco-editor` — `createDiffEditor`, `setModel`, `getOriginalEditor`, `getModifiedEditor`, `dispose`, `automaticLayout`, `renderSideBySide`, `originalEditable`, `enableSplitViewResizing` — all confirmed
- `dashboard/frontend/dist/app.js` lines 3225-3324 — existing HTML template structure, activity bar, `.ide-main` layout
- `dashboard/frontend/dist/app.js` lines 5421-5450 — `initDragHandle()` exact pattern for adaptation
- `dashboard/frontend/dist/app.js` lines 5218-5260 — `ideShowPanel()` activity bar toggle pattern
- `dashboard/frontend/dist/app.js` lines 3553-3590 — `ideActivateTab()` — needs extension for diff + panel modes
- `dashboard/frontend/dist/app.js` lines 3611-3639 — `ideCloseTab()` — needs extension for diff tab disposal
- `dashboard/frontend/dist/app.js` lines 4359-4560 — `ideOpenCCChat()` + tab object shape
- `dashboard/frontend/dist/style.css` lines 1711-1897 — IDE layout CSS, drag handle styles

### Secondary (MEDIUM confidence)
- Context7 `/microsoft/monaco-editor` — `getOriginalEditor().updateOptions({ readOnly: true })` for read-only diff panes (confirmed in API docs; exact behavior in v0.52.2 not directly tested)

### Tertiary (LOW confidence)
- `ideDetectLanguage` function name — not verified in app.js (needs grep before implementation)

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — Monaco `createDiffEditor` confirmed via Context7; all other tools are browser-native or already in use
- Architecture: HIGH — all patterns are adaptations of existing app.js code that was read directly
- Pitfalls: HIGH — derived from direct code inspection of the functions being extended; LOW risk items flagged
- Test infrastructure: HIGH — matches established source-inspection pattern from Phases 2 and 3

**Research date:** 2026-03-19
**Valid until:** 2026-04-19 (Monaco API stable; project code stable until next phase)
