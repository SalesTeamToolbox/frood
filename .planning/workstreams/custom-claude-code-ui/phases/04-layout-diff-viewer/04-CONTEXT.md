# Phase 4: Layout + Diff Viewer - Context

**Gathered:** 2026-03-19
**Status:** Ready for planning

<domain>
## Phase Boundary

Users can position the CC chat interface as either an editor tab (existing) or a resizable right-side panel, switch between modes without losing session state, and view code diffs proposed by CC in Monaco's side-by-side diff editor. This phase completes the UI arrangement layer.

Out of scope: @-mention file references (v2 INPUT-05), conversation fork/rewind (v2 ADV-01), cost tracking (v2 ADV-02), remote CC sessions (v2 ADV-03).

</domain>

<decisions>
## Implementation Decisions

### Side panel mode (LAYOUT-02)
- Panel sits right of the editor area, splitting the `.ide-main` container horizontally
- Editor shrinks, CC panel appears to the right — VS Code convention
- Terminal panel stays full-width below (not affected by the split)
- Vertical drag handle between editor and CC panel for free resize (reuse terminal drag-handle pattern)
- Min width ~250px, max ~60% of editor area
- Panel width persisted to localStorage, restored on page load
- Default width: ~35% of editor area on first open

### Panel activation (LAYOUT-01, LAYOUT-02)
- New CC icon in the activity bar (left rail) — click toggles the right panel
- Activity bar icon is the single entry point for panel mode
- CC tab from existing editor tab "+" button and terminal dropdown remain for tab mode
- Welcome screen button continues to open as tab

### Tab-to-panel switching (LAYOUT-03)
- One mode at a time — CC is either in a tab OR in the panel, never both simultaneously
- Activity bar CC icon is the toggle:
  - CC in tab → click icon → session moves to panel (tab closes, WS connection preserved)
  - CC in panel → click icon → session moves to tab (panel closes)
  - No CC open → click icon → opens new session in panel
- Session state (WS connection, chat history, trust mode) transfers seamlessly between modes
- Multi-session tabs behavior: all CC tabs move to panel mode together (session tab strip renders in panel header)

### Diff viewer (LAYOUT-04)
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

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements
- `.planning/workstreams/custom-claude-code-ui/REQUIREMENTS.md` §Layout — LAYOUT-01 through LAYOUT-04 acceptance criteria
- `.planning/workstreams/custom-claude-code-ui/ROADMAP.md` §Phase 4 — success criteria and phase dependencies

### Existing IDE layout (must-read before implementing)
- `dashboard/frontend/dist/app.js` lines ~3240-3323 — IDE page HTML structure (activity bar, sidebar, editor, terminal)
- `dashboard/frontend/dist/app.js` `ideActivateTab()` ~line 3553 — tab switching logic (editor vs CC container toggle)
- `dashboard/frontend/dist/app.js` `ideOpenCCChat()` ~line 4359 — current CC tab creation, WS handler setup
- `dashboard/frontend/dist/app.js` `ideInitMonaco()` ~line 3360 — Monaco editor initialization, `agent42-dark` theme
- `dashboard/frontend/dist/app.js` `initDragHandle()` ~line 5421 — terminal resize drag pattern (reuse for panel resize)
- `dashboard/frontend/dist/app.js` `ideShowPanel()` ~line 5218 — activity bar panel switching pattern
- `dashboard/frontend/dist/style.css` lines ~1711-1890 — IDE layout CSS classes

### Prior phase context
- `.planning/workstreams/custom-claude-code-ui/phases/01-backend-ws-bridge/01-CONTEXT.md` — WS message schema, session storage
- `.planning/workstreams/custom-claude-code-ui/phases/03-tool-use-and-sessions/03-CONTEXT.md` — Tool cards, session tabs, WS handler factory (`ccMakeWsHandler`)

### Monaco diff editor
- Monaco Editor v0.52.2 API — `monaco.editor.createDiffEditor()` for side-by-side diff. Researcher should verify API for current CDN version.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `initDragHandle()`: Terminal panel drag-resize logic — reuse pattern for CC panel vertical drag handle
- `ideShowPanel()` / `_ideActivePanel`: Activity bar panel toggle pattern — extend for CC panel
- `ccMakeWsHandler()`: WS handler factory from Phase 3 — reuse when moving session between tab/panel
- `ideActivateTab()`: Tab switching that toggles Monaco editor vs CC container visibility
- `_ideTabs[]` array: Tab management — extend with diff tab type
- `GET /api/ide/file`: File content endpoint — use for fetching original file content for diff
- Monaco `agent42-dark` theme: Already defined, will apply to diff editor automatically

### Established Patterns
- Activity bar icons toggle sidebar panels (`ideShowPanel`); extend this for right-side CC panel
- All IDE containers use `display:none` toggling for show/hide
- Editor and CC container are siblings inside `.ide-main` with `flex:1`
- Drag handle uses mousedown/mousemove/mouseup with min/max constraints
- localStorage used for IDE state (e.g., sidebar visibility could be extended to panel width)

### Integration Points
- New `#ide-cc-panel` container as sibling of `#ide-editor-container` inside `.ide-main` (right side)
- New vertical `.ide-panel-drag-handle` between editor and CC panel
- Activity bar gets new CC icon button (after Search icon)
- `ideActivateTab()` needs update: when CC tab activated in panel mode, show panel instead of editor container
- Tool card rendering (Phase 3) needs "View Diff" button added to Write/Edit tool cards
- New `ideOpenDiffTab()` function creates diff editor tabs with `monaco.editor.createDiffEditor()`

</code_context>

<specifics>
## Specific Ideas

- Panel positioning follows VS Code's Copilot Chat panel pattern — right of editor, above terminal
- Activity bar icon as single toggle for panel mode — clean, discoverable
- Session moves between modes seamlessly — user shouldn't notice any interruption
- "View Diff" is user-initiated, not auto-opened — avoids disruption during multi-edit sessions
- Diff tab feels like VS Code's "Open Changes" — familiar to developers

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 04-layout-diff-viewer*
*Context gathered: 2026-03-19*
