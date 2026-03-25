# Project Research Summary

**Project:** Agent42 v2.1 — Multi-Project Workspace Tabs
**Domain:** Multi-project context isolation in an embedded web IDE (VS Code-style)
**Researched:** 2026-03-23
**Confidence:** HIGH

> Note: ARCHITECTURE.md researcher timed out. Architecture findings are fully covered by STACK.md
> (integration patterns, component boundaries, API design) and PITFALLS.md (data model design,
> component interaction failures). Coverage is functionally complete.

---

## Executive Summary

This milestone adds multi-project workspace tabs to the Agent42 IDE page — a second tier of tabs above the existing editor tab bar that scopes all IDE surfaces (file explorer, Monaco editor, CC sessions, terminals) to a project folder. The good news: every mechanism required already exists in the codebase. Monaco model swapping, PTY cwd parameters, CC session workspace_path routing, and localStorage persistence are all in place. The work is composition and state management, not new technology. No new dependencies are required.

The recommended approach is a two-phase core build. Phase 1 establishes the foundational data model: a server-side `WorkspaceRegistry` (authoritative source of truth), a workspace-ID-prefixed URI convention for Monaco models, a namespaced storage key schema for localStorage/sessionStorage, and `/api/workspaces` CRUD endpoints. This foundation must be locked before any UI is built — eight of the ten identified pitfalls stem from missing namespace isolation that is trivially cheap to design in from the start but expensive to retrofit after tab switching is wired. Phase 2 threads the registry into every IDE surface (file API, terminal WS, CC warm pool, Monaco model switching, editor tab snapshot/restore) and builds the workspace tab bar UI.

The primary risk is cross-workspace state contamination: Monaco URI collisions causing silent file corruption, CC sessions resuming in the wrong project directory, and localStorage history bleeding across workspace switches. These are not hypothetical — identical bugs are documented in Zed (issue #41240), Claude Code (issues #5386, #5387), and VS Code Copilot (feedback #275). All are prevented by the same root principle: every file reference, session ID, storage key, and API call must carry a workspace identifier, and the server must resolve workspace paths from a registered allowlist rather than accepting client-supplied paths directly.

---

## Key Findings

### Recommended Stack

The entire feature is buildable with existing dependencies. The stack is the existing Agent42 stack: FastAPI for new `/api/workspaces` endpoints, `aiofiles` + JSON for the `WorkspaceRegistry` persistence file (`.agent42/workspaces.json`), `crypto.randomUUID()` for workspace IDs, `localStorage` for client-side tab state, and plain JS object arrays (matching the existing `state.chatSessions` / `state.codeSessions` pattern) for in-memory workspace state.

See `.planning/research/STACK.md` for the full integration point analysis.

**Core technologies:**

- `localStorage` (browser stdlib): Workspace config persistence — stale-while-revalidate against server registry; small JSON (<2KB); same pattern as existing CC session history
- `state.workspaces` plain JS array: In-memory workspace tab state — matches `state.chatSessions` pattern exactly; no framework needed
- `crypto.randomUUID()` (browser stdlib): Stable workspace IDs — already used for CC session IDs in `ideOpenCCChat()`
- `aiofiles` (existing dep, 23.0.0+): Registry persistence at `.agent42/workspaces.json`
- FastAPI `Query()` params (existing, 0.115.0+): New `workspace_id` param on `/api/ide/tree`, `/api/ide/file`, `/api/ide/search`, `/ws/terminal`, `/ws/cc-chat`
- Monaco `setModel()` + `saveViewState()` / `restoreViewState()` (existing, Monaco 0.52.2): Per-workspace editor tab state — stable API since 0.20+; view state is lightweight

**What not to use:** Multiple Monaco editor instances (80MB RAM each; use model swapping), `sessionStorage` for workspace config (dies on tab close), arbitrary absolute paths from client in any API or WebSocket (path traversal risk), any new frontend framework (no build system exists in this project).

### Expected Features

See `.planning/research/FEATURES.md` for the full prioritization matrix and feature dependency graph.

**Must have (table stakes) — v2.1 launch:**

- Workspace tab bar above editor tab bar with active tab indicator
- Per-workspace file explorer (re-rooted to workspace `root_path` on tab switch)
- Per-workspace editor tabs (`_ideTabs` partitioned by `workspace_id`; Monaco view state saved/restored on switch)
- Per-workspace CC sessions (`--cwd` = workspace root; session list filtered per workspace; warm pool keyed by `(user, workspace_id)`)
- Per-workspace terminal sessions (PTY spawned with `cwd` = workspace root; terminals hidden/shown on switch)
- Workspace persistence across reloads (`localStorage` cache + server `/api/workspaces` as authoritative source)
- Add workspace modal (manual path input + `/api/apps` dropdown for Agent42 internal apps)
- Remove workspace (close button with unsaved-files guard; cannot remove last workspace)
- Default workspace seeded from `AGENT42_WORKSPACE` — zero behavior change for existing single-workspace users

**Should have (competitive advantage) — v2.1.x patches:**

- Server-side workspace persistence as authoritative source (enables cross-device sync; `/api/workspaces` already exists from Phase 1)
- Drag-to-reorder workspace tabs
- Quick keyboard switcher (Ctrl+` cycling through workspace tabs)
- Rename workspace (double-click tab label)
- CC session scoped to workspace cwd (differentiator: AI understands which project without manual prompting)
- GSD workstream indicator filtered per active workspace root

**Defer (v2.2+):**

- Per-workspace git status badge on tab (requires polling per workspace; complex at scale)
- Workspace-level agent/task count indicator
- Export/import workspace configuration

**Anti-features (do not build):**

- Global search across all workspaces — mixes results from unrelated projects
- Shared editor tabs across workspaces — destroys the context isolation guarantee
- Sync CC session across workspace switch — CC sessions are cwd-bound; cross-workspace sessions cause confabulation about wrong project
- Auto-discover all git repos — noisy, slow, and surprising

### Architecture Approach

The architecture is entirely additive to the existing single-workspace IDE. The central design decision is the `WorkspaceRegistry`: a server-side in-memory dict (loaded from `.agent42/workspaces.json` at startup, written via `aiofiles`) that maps workspace IDs to validated absolute paths. All API endpoints and WebSocket handlers accept `workspace_id` as a parameter and resolve the actual path from the registry — never from client-supplied path strings. The client never sends paths; it sends IDs. This single architectural principle prevents the entire security attack surface (path traversal, workspace spoofing) and the data integrity problems (Monaco URI collision, file API sandbox bypass).

**Major components:**

1. `WorkspaceRegistry` (new, `server.py` or `core/workspace_registry.py`): authoritative ID-to-path mapping; validates paths on registration; caches in memory; persists to `.agent42/workspaces.json`
2. `/api/workspaces` CRUD endpoints (new, `server.py`): GET/POST/DELETE/PATCH; thin layer over `WorkspaceRegistry`
3. Modified IDE API endpoints (`/api/ide/tree`, `/api/ide/file`, `/api/ide/search`): add `workspace_id` Query param; sandbox check against registry-resolved root instead of global `workspace` variable
4. Modified WebSocket handlers (`/ws/terminal`, `/ws/cc-chat`): accept `workspace_id` query param; terminal uses `registry.get_path(id)` as PTY cwd; CC warm pool keyed by `(user, workspace_id)` tuple
5. Frontend workspace state (`app.js`): `state.workspaces[]`, `state.activeWorkspaceId`, per-workspace `_wsEditorTabs`, `_wsTreeCache`, `_wsExpandedDirs` dicts; `localStorage` persistence under `a42_workspaces`
6. Workspace tab bar UI (new section in `app.js`): renders above editor tab bar; add/remove controls; active tab highlight; switches all IDE surfaces on click; workspace name = `basename(root_path)` with full path tooltip

### Critical Pitfalls

See `.planning/research/PITFALLS.md` for all 10 pitfalls with code line references and recovery strategies.

1. **Monaco URI collisions between workspaces** — Two workspaces containing `src/main.py` get the same model URI (`file:///src/main.py`); `monaco.editor.getModel(uri)` returns the first workspace's model; the second workspace silently edits the wrong file. Prevention: prefix all Monaco URIs with workspace ID (`file:///ws-<id>/relative/path`). Must be established in Phase 1 before any editor state is tracked — cannot be retrofitted.

2. **File API accepts client-supplied paths** — Passing `workspace_root` as a client query parameter to `/api/ide/tree` or `/api/ide/file` is a path traversal vulnerability. Prevention: client sends only `workspace_id`; server resolves path from `WorkspaceRegistry`; sandbox check validates against the resolved root, not the global `workspace` variable.

3. **CC warm pool keyed by user only** — `_cc_warm_pool[user]` (line 1737 of `server.py`) causes workspace A's warm CC session to be consumed when workspace B opens CC. Claude starts in the wrong project's cwd with the wrong git context. Prevention: key pool by `(user, workspace_id)` tuple.

4. **Global `_ideTabs` and `_termSessions` are shared singletons** — Workspace switch either leaves old workspace tabs visible (contamination) or clears all tabs (UX regression — user loses open files). Prevention: snapshot current workspace tab state to its localStorage slot on switch; restore on return; Monaco models stay in memory registry across switches.

5. **localStorage key collisions** — CC session history keys (`cc_hist_<sessionId>`) and active session pointer (`cc_active_session`) are workspace-agnostic; after a page reload, history from workspace A appears in workspace B's CC panel. Prevention: namespace all keys by workspace ID from day one (`cc_hist_<wsId>_<sessionId>`, `cc_active_session_<wsId>`). Key schema must be locked in Phase 1 before any storage code is written.

Additional documented pitfalls: CC sessions directory shared across workspaces (Pitfall 7), file search results returning workspace-ambiguous relative paths (Pitfall 8), workspace config stored in localStorage only without server validation (Pitfall 9), Monaco view state lost on workspace switch due to DOM re-render triggering editor dispose (Pitfall 10).

---

## Implications for Roadmap

The dependency graph is clear and unambiguous. All ten pitfalls map to one of two phases. The `WorkspaceRegistry` is the prerequisite for every other piece of work.

### Phase 1: Foundation — Workspace Data Model and Registry

**Rationale:** Eight of ten pitfalls require Phase 1 decisions. The Monaco URI convention, storage key schema, and server-side registry must all be locked before any UI is built. This phase produces no visible user-facing UI — it is infrastructure only. Building the tab switcher before this foundation is in place guarantees retrofitting pain.

**Delivers:**

- `WorkspaceRegistry` class: in-memory dict, `workspaces.json` persistence, `register()`, `get_path(id)`, `validate()`, `list()`, `delete()` methods; startup path validation
- `/api/workspaces` CRUD endpoints (GET/POST/DELETE/PATCH)
- Monaco URI namespacing convention: `file:///ws-<workspaceId>/<relative-path>` — applied to `ideOpenFile()` and all consumers before any tab state is built
- localStorage / sessionStorage key schema locked: `a42_workspaces`, `cc_hist_<wsId>_<sessionId>`, `cc_active_session_<wsId>` — established before any storage code is written
- `(workspace_id, relative_path)` as the canonical file reference pair across all APIs
- Frontend: `state.workspaces[]`, `state.activeWorkspaceId`, per-workspace state dicts; `localStorage` persistence under `a42_workspaces`
- Default workspace seeded from `AGENT42_WORKSPACE` so existing single-workspace behavior is unchanged

**Addresses features:** Workspace persistence, default workspace, add/remove workspace (backend only)

**Avoids pitfalls:** Pitfall 1 (Monaco URIs), Pitfall 4 (file API sandbox), Pitfall 5 (localStorage keys), Pitfall 8 (file path workspace-ambiguity), Pitfall 9 (server as authority)

**Research flag:** Well-understood. All patterns derived from direct codebase inspection. No additional research phase needed.

---

### Phase 2: Wiring — IDE Surface Scoping and Tab UI

**Rationale:** With the registry and data model in place, Phase 2 threads workspace context through every IDE surface and builds the tab switcher. Recommended execution order within the phase: backend API changes first (add `workspace_id` params to existing endpoints), then CC session scoping (warm pool key fix is a correctness issue, not polish), then terminal scoping, then frontend tab state snapshot/restore logic, then the tab bar UI last.

**Delivers:**

- Modified `/api/ide/tree`, `/api/ide/file`, `/api/ide/search`: `workspace_id` Query param; sandbox check against registry-resolved root
- Modified `/ws/terminal`: `workspace_id` query param; PTY spawns with `cwd = registry.get_path(workspace_id)`, not global `workspace`
- Modified `/ws/cc-chat`: `workspace_id` query param; warm pool keyed by `(user, workspace_id)` tuple; CC session directory per workspace root (`.agent42/cc-sessions/` inside each workspace's folder)
- CC session list endpoint filtered to active workspace; session picker shows only current workspace sessions
- Frontend tab state snapshot/restore: serialize `_ideTabs` + `_termSessions` to per-workspace localStorage slot on switch; restore on return; Monaco `viewState` saved/restored per model URI
- Workspace tab bar UI: horizontal strip above editor tab bar; active tab indicator; add/remove buttons; workspace name = `basename(root_path)` with full path in `title` tooltip

**Addresses features:** All P1 table-stakes features from FEATURES.md MVP list

**Avoids pitfalls:** Pitfall 2 (terminal cwd), Pitfall 3 (CC warm pool), Pitfall 6 (global IDE arrays), Pitfall 7 (CC session directory shared), Pitfall 10 (Monaco view state lost on DOM re-render)

**Verification checkpoints (from PITFALLS.md "Looks Done But Isn't" checklist):**

- `monaco.editor.getModels()` shows distinct URI-prefixed models for same-relative-path files in two workspaces
- New terminal `pwd` in workspace B shows workspace B root, not `AGENT42_WORKSPACE`
- CC session list shows only workspace B sessions when workspace B is active
- Path traversal test: `/api/ide/file?path=../../../etc/passwd&workspace_id=<valid>` returns 403
- Switch workspaces 3x; verify each retains its own open tabs, cursor positions, and terminal sessions

**Research flag:** One targeted pre-read before Phase 2 planning: inspect how `renderCode()` interacts with the Monaco singleton dispose/recreate cycle (lines 3587-3591 of `app.js`). If workspace tab switching triggers a full re-render, the `setModel()` + `restoreViewState()` approach needs adjustment. Not a full research phase — a 15-minute code trace.

---

### Phase 3: Polish — UX Enhancements and Full Server Persistence

**Rationale:** After core isolation is verified working, add features that improve experience. Server-side persistence is deferred here (not Phase 1) because the MVP is correct and functional with localStorage-only; server persistence adds cross-device sync which is quality-of-life, not correctness.

**Delivers:**

- Server-side workspace persistence as authoritative source (localStorage becomes stale-while-revalidate cache; `/api/workspaces` is fully authoritative)
- Drag-to-reorder workspace tabs (order persisted to server)
- Quick keyboard switcher (Ctrl+` cycles through workspace tabs)
- Rename workspace (double-click tab label to edit display name)
- Workspace deletion cleanup: invalidate CC sessions, sweep localStorage namespace, unregister from `WorkspaceRegistry`; inline error in tab when workspace folder is missing or inaccessible
- Workspace tab max count enforcement (8 workspaces max; workspace switcher modal for more)

**Research flag:** Standard patterns throughout. No research phase needed. Playwright UAT is the appropriate verification method for UX work.

---

### Phase Ordering Rationale

- Phase 1 before Phase 2: the registry and namespace schema are structural prerequisites; building tab UI on top of a broken data model means rebuilt UI, not just added functionality
- Backend API changes before frontend wiring in Phase 2: frontend cannot pass `workspace_id` to endpoints that don't accept it yet
- CC warm pool key fix in Phase 2 (not Phase 3): this is a correctness issue — consuming workspace A's warm session for workspace B is silent and wrong, not just inconvenient
- Server persistence in Phase 3 (not Phase 1): the registry API already exists from Phase 1; Phase 3 just makes the client treat it as authoritative rather than supplementary

### Research Flags

Phases with standard, well-documented patterns (skip `/gsd:research-phase`):

- **Phase 1:** All patterns derived from direct codebase inspection — aiofiles JSON, FastAPI Query params, localStorage schema, Monaco URI API
- **Phase 2 (most of it):** WebSocket query param routing, PTY cwd, CC session directory are documented and straightforward
- **Phase 3:** Drag-to-reorder (standard HTML5 drag-and-drop on flex tab bar), keyboard shortcuts, rename — all standard web patterns

Targeted pre-read recommended before Phase 2 planning (not a full research phase):

- **Phase 2 (Monaco re-render interaction):** Trace `renderCode()` call sites to understand whether workspace tab switching triggers full DOM re-render that would invoke the Monaco dispose/recreate guard at lines 3587-3591 of `app.js`. If so, design around it before implementing the tab switcher.
- **Phase 2 (CC sessions_dir threading):** Confirm `sessions_dir` parameter is used consistently through all `_save_session()` / `_load_session()` call sites in `cc_chat_ws` before planning CC scoping implementation.

---

## Confidence Assessment

| Area | Confidence | Notes |
| --- | --- | --- |
| Stack | HIGH | Direct codebase inspection (app.js, server.py, requirements.txt); no speculative choices; zero new dependencies |
| Features | HIGH | Derived from existing IDE capabilities and VS Code/JetBrains patterns; anti-features from real bug reports |
| Architecture | HIGH | ARCHITECTURE.md timed out; STACK.md and PITFALLS.md provide equivalent coverage with code line citations |
| Pitfalls | HIGH | 10 pitfalls with code line references; 5 backed by production bug reports from Zed, Claude Code, VS Code |

**Overall confidence:** HIGH

### Gaps to Address

- **Monaco DOM re-render interaction:** Whether workspace tab switching triggers `renderCode()` which disposes and recreates the Monaco editor (lines 3587-3591 of `app.js`) must be confirmed before Phase 2 planning. If it does, the `setModel()` + `restoreViewState()` approach needs a guard or alternative.

- **CC `sessions_dir` threading completeness:** The `_save_session()` and `_load_session()` functions accept an optional `sessions_dir` parameter, but it is unclear if all call sites within `cc_chat_ws` use it consistently. Verify this before finalizing the CC scoping design in Phase 2.

- **External repository paths (outside AGENT42_WORKSPACE):** Whether v2.1 MVP supports workspace roots outside `AGENT42_WORKSPACE` (requiring the registered-roots allowlist) or only internal `apps/` subdirectories (simpler, uses existing sandbox model) is a scoping decision to make in Phase 1 planning. Restricting to internal paths is a valid MVP simplification.

- **Windows PTY cwd behavior:** `PtyProcess.spawn(cwd=...)` is confirmed working on Windows (CLAUDE.md documents pywinpty usage), but behavior with non-`AGENT42_WORKSPACE` paths should be smoke-tested early in Phase 2 execution.

---

## Sources

### Primary (HIGH confidence)

- Agent42 codebase — `dashboard/frontend/dist/app.js` (direct inspection: `_ideTabs` line 3398, Monaco URI construction line 3761, `_termSessions` line 5720, `cc_hist_*` localStorage keys line 5335, `cc_active_session` sessionStorage line 4813, Monaco singleton init lines 3587-3598)
- Agent42 codebase — `dashboard/server.py` (direct inspection: workspace variable line 1301, file API sandbox check lines 1306-1409, terminal PTY spawn lines 1447-1690, CC sessions directory line 1727, warm pool dict line 1737, `_cc_spawn_warm()` workspace_path arg line 1747)
- Agent42 codebase — `requirements.txt`, `.planning/PROJECT.md` — version confirmation, v2.1 milestone requirements
- CLAUDE.md pitfall #120 (localStorage CC history design and session restore on reload)
- CLAUDE.md pitfall #122 (nested git root detection failure — parallel problem to workspace root confusion)
- CLAUDE.md pitfall #83 (duplicate API calls from workspace-scoped state)

### Secondary (MEDIUM confidence)

- [VS Code Multi-Root Workspaces official docs](https://code.visualstudio.com/docs/editing/workspaces/multi-root-workspaces) — multi-root vs. full context-switch tab model comparison; VS Code divergence noted
- [VS Code workspace concepts](https://code.visualstudio.com/docs/editing/workspaces/workspaces) — workspace config file design
- [JetBrains IDE Workspaces blog 2025](https://blog.jetbrains.com/idea/2025/03/ide-workspaces-development-challenges-and-plans/) — workspace as meta-container; per-project state isolation principle
- Monaco Editor API docs — `createModel`, `setModel`, `saveViewState`, `restoreViewState` stable since 0.20

### Tertiary (HIGH confidence — real bug reports, production evidence)

- [Zed AI cross-project history leak issue #41240](https://github.com/zed-industries/zed/issues/41240) — CC session IDs must be workspace-keyed; real production bug
- [Claude Code wrong project hooks issues #5386, #5387](https://github.com/anthropics/claude-code/issues/5386) — `--cwd` scoping prevents hook cross-contamination; real production bug
- [VS Code Copilot wrong project output feedback #275](https://github.com/microsoft/copilot-intellij-feedback/issues/275) — agent dispatch must default to active workspace; real production bug

---

*Research completed: 2026-03-23*
*Architecture researcher timed out — coverage sourced from STACK.md and PITFALLS.md (functionally complete)*
*Ready for roadmap: yes*
