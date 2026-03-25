# Feature Research: Multi-Project Workspace Tabs

**Domain:** Multi-project workspace tabs for an embedded web IDE (VS Code-style)
**Researched:** 2026-03-23
**Confidence:** HIGH

---

## Context: What Already Exists

The Agent42 Workspace page is a single-workspace VS Code-style IDE with:

- Monaco editor with per-file models, tab bar (`_ideTabs`), view state save/restore
- File explorer panel (ide-file-tree) rooted at a single workspace directory
- CC (Claude Code) chat tabs with `--resume` session support and per-session localStorage history
- Terminal tabs with PTY sessions
- Activity bar: Explorer, Search, Chat Panel buttons
- Diff editor, syntax highlighting, Ctrl+B explorer toggle

This milestone adds a **workspace switcher** — a second level of tabs above the existing editor tab bar. Each workspace tab scopes ALL IDE surfaces to a project folder.

---

## Feature Landscape

### Table Stakes (Users Expect These)

Features users assume exist when they hear "multi-project workspace tabs." Missing any of these makes the feature feel half-built.

| Feature | Why Expected | Complexity | Notes |
| ------- | ------------ | ---------- | ----- |
| Workspace tab bar | The entire milestone premise — tabs at top of workspace page to switch projects | LOW | Horizontal strip above editor tab bar; active tab highlighted; add/close buttons |
| Per-workspace file explorer | Each workspace tab shows only its own project folder tree | MEDIUM | File tree re-rooted to workspace `root_path` on tab switch; not shared across tabs |
| Per-workspace editor tabs | Open files from workspace A must not appear when switched to workspace B | MEDIUM | `_ideTabs` array must be partitioned per workspace; save/restore on switch |
| Per-workspace CC sessions | CC `--cwd` must match the active workspace root; switching tabs should not mix sessions from different projects | MEDIUM | Each workspace has its own CC tab collection; `--resume` uses workspace-scoped session IDs |
| Per-workspace terminal sessions | Terminal `cwd` must be set to project root; switching workspace tabs must not share terminal instances | MEDIUM | PTY sessions keyed per-workspace; switching hides/shows correct terminals |
| Workspace persistence across reloads | Workspaces configured today should still be there after page refresh or server restart | MEDIUM | Store workspace list + last-active tab in `localStorage` (client) and optionally `/api/workspaces` (server) |
| Add workspace action | Users must be able to add a new project folder to the workspace tab bar | LOW | Modal or inline input: pick path or browse; validates path is accessible |
| Remove workspace action | Users must be able to close/remove a workspace tab | LOW | Close button on tab (with confirmation if unsaved files exist); cannot remove last workspace |
| Workspace name display | Tab label should show project folder name (basename), not full path | LOW | Use `path.basename(root_path)` for display; full path in tooltip |
| Active workspace visual indicator | User must always know which workspace is active | LOW | Standard active tab styling — matches existing IDE tab pattern already in codebase |
| Agent42 internal apps as workspaces | `apps/` subdirectory items must be selectable as workspace targets | LOW | Populate "add workspace" picker from `/api/apps` in addition to manual path entry |

### Differentiators (Competitive Advantage)

Features that make Agent42 workspace tabs better than just "VS Code multi-root" — specifically in the AI agent context where CC sessions and agents are project-aware.

| Feature | Value Proposition | Complexity | Notes |
| ------- | ----------------- | ---------- | ----- |
| CC session scoped to workspace cwd | Claude Code launches with `--cwd` pointing to the workspace root — AI understands which project it's working in without manual prompting | LOW | Pass workspace `root_path` as `cwd` argument when spawning `claude` process; already threaded through PTY backend |
| GSD workstream indicator per workspace | Show active GSD phase/workstream state for the active workspace — not a global indicator | MEDIUM | Heartbeat already carries GSD state; filter by project root to show workspace-relevant phase |
| Agent dispatch scoped to workspace | When creating a task from the workspace page, default the workspace field to the active project | LOW | Pre-populate task creation modal with active workspace path; agents get correct cwd |
| Workspace-level MCP context | Per-workspace CLAUDE.md and `.planning/` directories auto-surface in the CC session — agents get project-specific context | LOW | `--cwd` already achieves this if CC is launched from the workspace root |
| Quick workspace switcher (keyboard shortcut) | Power users switch between projects without mouse; reduces context-switch friction | LOW | Ctrl+\` or similar hotkey cycles through workspace tabs; same pattern as VS Code window switching |
| Workspace status indicator | Show a small badge per workspace tab: git branch, dirty files count, or active agent count | HIGH | Requires polling per workspace for git status; do not block on this for MVP |
| Workspace drag-to-reorder | Users organize their tab order to match their mental model of priority | MEDIUM | HTML drag-and-drop on tab strip; save order to persistence layer |

### Anti-Features (Commonly Requested, Often Problematic)

| Feature | Why Requested | Why Problematic | Alternative |
| ------- | ------------- | --------------- | ----------- |
| Global search across all workspaces | "Search everything at once" | Mixes results from unrelated projects; adds result-grouping UI complexity; VS Code does this and it's confusing | Search scoped to active workspace only; user switches workspace to search the other project |
| Shared editor tabs across workspaces | "I want to compare files from two projects" | Destroys the isolation guarantee — users lose the context boundary that makes tabs valuable | Open diff editor within one workspace; or open the second workspace in a new browser tab |
| Sync CC session across workspace switch | "Keep my conversation going when I switch tabs" | CC sessions are cwd-bound; the same session in a different directory causes tool errors and confabulation about wrong project | New workspace = new CC session (or resume a prior session for that workspace); never port a session across workspaces |
| Auto-discover all git repos and add them as workspaces | "Add all my projects automatically" | Projects in deeply nested paths or unrelated repos create noise; startup scan is slow and surprising | Manual "Add Workspace" with optional `/api/apps` pre-population; let user decide what belongs |
| Per-workspace settings panels | "Set different editor preferences per project" | Dramatically increases UI surface area; only needed for polyglot shops | Use Monaco `modelOptions` for per-language settings; workspace-level settings are a v2+ concern |
| Workspace "projects" vs Agent42 "Projects" | "Use existing projects as workspaces" | Agent42 Projects are task-management entities (Kanban cards), not file-system roots; conflating them creates dual-meaning confusion | Keep separate; workspace tabs reference file system paths; Agent42 Projects remain task collections |

---

## Feature Dependencies

```text
Workspace Tab Bar (tab UI + add/remove)
    └──requires──> Workspace Config Store (client-side localStorage + optional server persist)
                       └──produces──> workspace list [{id, root_path, name}]
                           ├──feeds──> File Explorer (re-root on tab switch)
                           ├──feeds──> Editor Tab Partition (_ideTabs scoped per workspace_id)
                           │               └──requires──> Save/Restore active tab state on switch (already in Monaco viewState API)
                           ├──feeds──> CC Session Scoping (cwd = workspace root_path)
                           │               └──enhances──> GSD workstream indicator (filter by root_path)
                           └──feeds──> Terminal Session Scoping (cwd = workspace root_path)

Workspace Persistence
    └──requires──> Workspace Config Store
    └──optional──> /api/workspaces backend endpoint (for cross-device or multi-tab sync)

Agent42 Apps as Workspace Targets
    └──requires──> /api/apps (already exists)
    └──enhances──> Add Workspace picker (pre-populate with apps/ paths)
```

### Dependency Notes

- **File explorer re-root requires workspace root_path on tab switch:** The current file tree calls the server with a path argument. Switching workspace tabs simply changes the root path argument — no new API needed, only state management.
- **Editor tab partition requires workspace_id on each `_ideTabs` entry:** Add a `workspace_id` field to the existing tab object. On switch: hide current workspace tabs, show target workspace tabs. Monaco models persist in memory across the switch (no re-read needed).
- **CC session scoping is already architected:** The `claude` process already takes `--cwd`. The workspace tab just passes a different `root_path`. No backend changes needed if the frontend passes cwd when opening a new CC tab.
- **Terminal session scoping uses existing PTY pattern:** PTY backend accepts a `cwd` argument at session creation. Workspace tab stores its terminal session IDs; switching shows/hides the relevant xterm instances.
- **Workspace persistence can start client-only:** `localStorage` with key `agent42_workspaces` is sufficient for MVP. Server persistence (`/api/workspaces`) adds cross-device sync and is a v1.x addition.
- **GSD workstream indicator enhancement has no blocking dependency:** Existing heartbeat data already carries workstream state. The enhancement is a display filter — can be added independently of core workspace tab work.

---

## MVP Definition

### Launch With (v2.1 — initial release)

Minimum viable feature that delivers the core context-isolation benefit.

- [ ] Workspace tab bar rendered above editor tab bar in Workspace page
- [ ] Workspace config stored in `localStorage` as `[{id, root_path, name}]`; last-active workspace id stored separately
- [ ] Add workspace modal: manual path input + dropdown populated from `/api/apps`
- [ ] Remove workspace: close button on tab with "unsaved files" guard
- [ ] File explorer re-rooted to active workspace `root_path` on tab switch
- [ ] Editor tabs partitioned by `workspace_id` (add field to `_ideTabs` entries); save/restore Monaco view state on switch
- [ ] CC session tabs scoped per workspace: new CC tab spawned with `--cwd` = workspace `root_path`; existing sessions stored per-workspace and restored on switch
- [ ] Terminal sessions scoped per workspace: PTY spawned with `cwd` = workspace `root_path`; terminals hidden/shown on switch
- [ ] Workspace tab label = basename of `root_path`; full path in `title` attribute tooltip
- [ ] Default workspace seeded from existing `AGENT42_WORKSPACE` env var so current single-workspace users see no change

### Add After Validation (v2.1.x)

- [ ] Server-side workspace persistence (`/api/workspaces` GET/POST/DELETE) — enables cross-device sync and multi-browser-tab awareness
- [ ] Drag-to-reorder workspace tabs — saves order to persistence layer
- [ ] Quick workspace switcher keyboard shortcut (Ctrl+\` or similar)
- [ ] Rename workspace: double-click tab label to edit display name

### Future Consideration (v2.2+)

- [ ] Per-workspace git status badge on tab (branch name, dirty file count) — requires polling `/api/git/status?path=...` per workspace; complex with many workspaces
- [ ] Workspace-level agent/task count indicator — shows how many active agents are running in each workspace
- [ ] Workspace "favorite" / pinned ordering — persisted across sessions
- [ ] Export/import workspace configuration — useful for team setups or reproducing dev environments

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
| ------- | ---------- | ------------------- | -------- |
| Workspace tab bar + add/remove | HIGH | LOW | P1 |
| localStorage persistence | HIGH | LOW | P1 |
| File explorer re-root on switch | HIGH | LOW | P1 |
| Editor tab partition per workspace | HIGH | MEDIUM | P1 |
| CC session scoping (--cwd) | HIGH | LOW | P1 |
| Terminal session scoping | HIGH | MEDIUM | P1 |
| Apps as workspace targets | MEDIUM | LOW | P1 |
| Default workspace from env var | HIGH | LOW | P1 |
| Server-side workspace persistence | MEDIUM | MEDIUM | P2 |
| Drag-to-reorder tabs | LOW | MEDIUM | P2 |
| Quick keyboard switcher | MEDIUM | LOW | P2 |
| Rename workspace | LOW | LOW | P2 |
| Git status badge on tab | MEDIUM | HIGH | P3 |
| Agent/task count indicator | LOW | HIGH | P3 |

**Priority key:**

- P1: Must have for v2.1 launch
- P2: Should have, add in v2.1.x patch
- P3: Nice to have, v2.2+

---

## IDE Pattern Analysis

### VS Code Multi-Root Workspaces (HIGH confidence)

VS Code's pattern for multi-root workspaces: multiple folder roots shown as sibling entries in the single Explorer panel. File tabs include folder-name disambiguation in the tab label when collisions exist. Search operates globally but groups results by folder. Settings have three scopes: User, Workspace (global), and per-Folder. Terminals are not automatically scoped — any terminal can navigate anywhere. Workspace config lives in `.code-workspace` JSON file.

**Agent42 divergence:** VS Code renders all roots simultaneously in one Explorer. Agent42 should render only the active workspace root — tabs switch context entirely. This is closer to VS Code's "open new window" model than its multi-root model, but confined to a single browser tab. The tab-switch-entire-context approach matches how JetBrains workspaces and how Cursor users request multi-project support.

### JetBrains Workspaces (MEDIUM confidence)

IntelliJ IDEA's workspace feature (preview as of 2025) treats a workspace as a meta-container of independent projects. Each project keeps its own `.idea/` config. Workspace stores only folder structure and VCS roots — everything else stays on the project level. Key design principle: "workspace is responsible for storing the workspace folder structure; everything else remains on the project level." Projects can be loaded/unloaded within the workspace.

**Agent42 alignment:** Same principle: workspace tabs own only `{root_path, name, session_ids}`; all other state (open files, CC history, terminal content) lives per-tab, not globally.

### Known Cross-Project Contamination Bugs to Avoid (HIGH confidence)

Real-world issues found in VS Code and JetBrains multi-project workspaces:

1. AI conversation history leaking across projects (Zed issue #41240) — CC session IDs must be keyed by `workspace_id`, never shared
2. Wrong project hooks executing (Claude Code issues #5386, #5387) — CC `--cwd` scoping prevents this
3. Copilot output files placed in wrong project (Microsoft feedback #275) — agent dispatch must default to active workspace

---

## Sources

- [VS Code Multi-Root Workspaces official docs](https://code.visualstudio.com/docs/editing/workspaces/multi-root-workspaces) (HIGH confidence)
- [VS Code workspace concepts](https://code.visualstudio.com/docs/editing/workspaces/workspaces) (HIGH confidence)
- [JetBrains Workspaces in IntelliJ IDEA blog](https://blog.jetbrains.com/idea/2024/08/workspaces-in-intellij-idea/) (MEDIUM confidence)
- [JetBrains IDE Workspaces challenges and plans 2025](https://blog.jetbrains.com/idea/2025/03/ide-workspaces-development-challenges-and-plans/) (MEDIUM confidence)
- [Zed AI conversation history cross-project leak](https://github.com/zed-industries/zed/issues/41240) (HIGH confidence — real bug report)
- [Claude Code wrong project hooks in multi-project workspace](https://github.com/anthropics/claude-code/issues/5386) (HIGH confidence — real bug report)
- [Copilot output in wrong project in multi-project workspace](https://github.com/microsoft/copilot-intellij-feedback/issues/275) (HIGH confidence — real bug report)
- [Multi-project workspace feature request Cursor](https://forum.cursor.com/t/multi-project-workspace/92547) (MEDIUM confidence)
- [Monaco editor tab implementation (createModel/setModel/saveViewState/restoreViewState pattern)](https://github.com/microsoft/monaco-editor/issues/604) (HIGH confidence)
- Agent42 `app.js` — existing tab state implementation (`_ideTabs`, `ideRenderTabs`, ccTabs pattern) (HIGH confidence — direct code read)

---

*Feature research for: Agent42 v2.1 Multi-Project Workspace Tabs*
*Researched: 2026-03-23*
