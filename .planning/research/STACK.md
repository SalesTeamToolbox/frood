# Stack Research

**Domain:** Multi-project workspace tabs for Agent42 IDE (additive feature)
**Researched:** 2026-03-23
**Confidence:** HIGH — all conclusions derived directly from the existing codebase and identified integration points; no speculative new-technology choices

---

## Context: No New Dependencies Required

Agent42's workspace page already has a fully-operational VS Code-style IDE built with:

- **Monaco Editor 0.52.2** (CDN-loaded via AMD loader, single `_monacoEditor` instance)
- **xterm.js** (self-hosted in `dist/xterm/`, loaded lazily via `termLoadXterm()`)
- **FastAPI** backend (`/api/ide/tree`, `/api/ide/file`, `/api/ide/search`, `/ws/terminal`, `/ws/cc-chat`)
- **Plain-object state** in `app.js` global `state`, with `localStorage` for persistence

Multi-project workspace tabs need to scope the file explorer, Monaco editor, xterm terminals, and CC subprocess cwd per workspace. Every mechanism required already exists. The work is composition and state management, not new technology.

---

## Recommended Stack

### Core Technologies (All Already In Use — No New Dependencies)

| Technology | Version | Purpose | Why Recommended |
| --- | --- | --- | --- |
| `localStorage` (browser stdlib) | N/A | Persist workspace configurations across reloads | Already used for auth token, CC session history (`cc_hist_*`), and first-task flag. Workspace config is small JSON (<2KB) — well within the 5–10MB localStorage limit. No IndexedDB needed. |
| `state.workspaces` plain JS object array | N/A | In-memory workspace tab state | The existing `state` object in `app.js` holds all UI state as plain objects. A `workspaces` array with `{ id, name, rootPath, editorTabs, activeEditorTab, treeCache, expandedDirs }` per entry follows the exact same pattern as `state.codeSessions`, `state.chatSessions`, etc. |
| `crypto.randomUUID()` (browser stdlib) | N/A | Workspace tab IDs | Already used for CC session IDs in `ideOpenCCChat()`. Generates stable, collision-proof IDs for per-workspace state keying. |
| FastAPI + `Path` stdlib | 0.115.0+ | Multi-root file tree endpoint | `/api/ide/tree` currently resolves paths relative to `AGENT42_WORKSPACE`. Adding an optional `?root=<registered_path>` query param (with server-side allowlist validation) scopes the tree to a registered workspace root without changing security model. |
| `asyncio` + existing PTY/subprocess | stdlib | Per-workspace terminal cwd | `termNew()` calls `/ws/terminal` with node and cmd params. Adding a `cwd` query param passed through to `PtyProcess.spawn(cwd=...)` and `subprocess.Popen(cwd=...)` is a one-line server change. |
| `/ws/cc-chat` workspace_path param | existing | Per-workspace CC subprocess cwd | `_cc_spawn_warm()` and the main CC run in `cc_chat_ws` already use `workspace_path` (hardcoded to global workspace). Exposing it as a WebSocket query param (validated against registered roots) scopes CC sessions per workspace. |
| `aiofiles` | 23.0.0+ | Persist workspace registry | Already in requirements.txt. Workspace registry (`list[{id, name, rootPath}]`) saved to `.agent42/workspaces.json` via `aiofiles.open()`. Matches existing persistence patterns for overrides, lessons, etc. |
| FastAPI REST | 0.115.0+ | Workspace CRUD API | New endpoints `/api/workspaces` (GET/POST), `/api/workspaces/{id}` (DELETE/PATCH) added to `server.py` following the same pattern as existing `/api/ide/*` routes. |

### Supporting Patterns (In-Codebase, No Library Needed)

| Pattern | Current Location | Reuse For |
| --- | --- | --- |
| Per-session state isolation | `state.chatSessions` / `state.codeSessions` arrays | Per-workspace editor tab list, tree cache, expanded dir set |
| `ccHistoryKey(sessionId)` keying | Lines 5334-5336 of `app.js` | `workspaceTreeKey(wsId)` for localStorage tree expansion state |
| Lazy script loading guard | `termLoadXterm()` / `_xtermLoaded` flag | No change needed — xterm is already loaded once globally |
| Monaco `_monacoEditor.dispose()` + `monaco.editor.create()` | Lines 3587-3598 of `app.js` | Swap Monaco content when switching workspace tabs (editor is already rebuilt on SPA re-render; the same mechanism applies) |
| Security: path-outside-workspace check | `ide_tree`, `ide_read_file`, `ide_write_file` in `server.py` | Add registered-roots allowlist check before resolving multi-root paths |

### Development Tools (Existing)

| Tool | Purpose | Notes |
| --- | --- | --- |
| pytest + pytest-asyncio | Test new `/api/workspaces` endpoints and path validation | Already configured. Add `tests/test_workspace_api.py`. |
| ruff | Linting and formatting for server.py additions | Already configured. Run `make format && make lint` after adding routes. |

---

## Installation

```bash
# No new dependencies required.
# All stack components are either browser stdlib, Python stdlib,
# or packages already in requirements.txt.
```

---

## Integration Points and How They Work

### 1. Frontend: Workspace State Shape

```javascript
// New addition to state object in app.js
workspaces: [],            // [{id, name, rootPath, color}]
activeWorkspaceId: "",     // which tab is active
// Per-workspace ephemeral state (not persisted):
_wsEditorTabs: {},         // wsId -> [{path, model, viewState}]
_wsActiveEditorTab: {},    // wsId -> index
_wsTreeCache: {},          // wsId -> {path: entries[]}
_wsExpandedDirs: {},       // wsId -> Set([...])
```

Workspace configs (`workspaces`, `activeWorkspaceId`) persist to localStorage under key `a42_workspaces`. Editor tab lists do NOT persist — they rebuild from the file tree on tab switch (consistent with how the current IDE rebuilds on page revisit).

### 2. Backend: Workspace Registry

New endpoints in `server.py`:

```text
GET  /api/workspaces          -> list[{id, name, rootPath}]
POST /api/workspaces          -> body: {name, rootPath} -> {id, name, rootPath}
DELETE /api/workspaces/{id}   -> {status: "ok"}
PATCH /api/workspaces/{id}    -> body: {name?, rootPath?} -> updated workspace
```

Registry stored at `AGENT42_WORKSPACE / ".agent42" / "workspaces.json"` — same `.agent42/` convention as `cc-sessions/`, `overrides.json`, etc.

### 3. Backend: Multi-Root File Tree

The existing `/api/ide/tree` endpoint anchors all paths relative to the global `workspace` variable (set once from `AGENT42_WORKSPACE`). For multi-workspace support, paths inside registered project workspaces need their own root anchor.

Two options — **Option A is recommended:**

**Option A (add `?root=<id>` param):** Caller passes workspace ID; server resolves registered root from registry and uses that as anchor. Security: root must be in the registered list (not an arbitrary path).

**Option B (accept absolute path param):** Too broad — any registered path could be guessed.

This keeps the path traversal protection model intact: `target.resolve()` must start with the registered workspace root rather than the global root.

### 4. Backend: Scoped Terminal cwd

`/ws/terminal` already accepts `node` and `cmd` query params. Add optional `cwd` param:

```python
cwd_param = websocket.query_params.get("cwd", "")
# Validate: cwd_param must resolve to a registered workspace root
effective_cwd = _resolve_registered_cwd(cwd_param) or workspace
pty_process = PtyProcess.spawn(pty_cmd, cwd=str(effective_cwd))
```

Frontend `termNew()` passes `&cwd=<encoded_workspace_root>` based on `state.activeWorkspaceId`.

### 5. Backend: Scoped CC Subprocess cwd

`/ws/cc-chat` uses `workspace` (global) for both the warm pool spawn and every real turn's subprocess cwd. Exposing a `workspace_root` query param (validated against registered paths) allows each CC session spawned from a workspace tab to start in that project's directory. The `--resume` flow works unchanged — CC session IDs are per-run, so different workspace tabs naturally get different CC sessions.

### 6. Monaco: Per-Workspace Models

Monaco already creates one global editor instance (`_monacoEditor`). When switching workspace tabs:

1. Save current tab's `viewState` via `_monacoEditor.saveViewState()`
2. Swap to the target workspace's active file model (or create new model)
3. Call `_monacoEditor.setModel(targetModel)` + `_monacoEditor.restoreViewState(saved)`

`monaco.editor.createModel()` is already called per-file in `ideOpenFile()`. The existing tab tracking in `_ideTabs` can be namespaced by workspace ID.

---

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
| --- | --- | --- |
| Per-workspace state in plain JS objects (same `state` pattern) | Separate SPA component framework (React, Vue) | Never for this project — no build system, single bundled `app.js`. Component framework would require adding a build pipeline, which is explicitly out of scope. |
| `localStorage` for workspace config | `IndexedDB` | Use IndexedDB only if workspace configs exceed tens of KB or need structured queries. Workspace config is a small flat list. |
| `aiofiles` JSON for workspace registry | SQLite workspace table | SQLite adds schema migration complexity for what is a 10-line JSON file. Existing pattern for small config lists (e.g., `github_accounts.json`) uses aiofiles + JSON. |
| Single Monaco instance, swap models | One Monaco instance per workspace | Multiple editor instances per page cause massive memory overhead (~80MB each). VS Code itself uses model swapping, not multiple instances. |
| Registered-roots allowlist for multi-root tree | Accept any absolute path from client | Client-supplied arbitrary paths are a path traversal risk. Registered roots validated on the server prevent this. |
| Lazy Monaco `viewState` save/restore per workspace | Full dispose+recreate on workspace switch | Dispose+recreate costs ~200ms per switch. `setModel()` + `restoreViewState()` is near-instant and is what VS Code multi-root workspaces do. |

---

## What NOT to Use

| Avoid | Why | Use Instead |
| --- | --- | --- |
| New frontend framework (React, Vue, Svelte) | Requires build tooling; the project explicitly has no build system (single `app.js`). This would be a project-wide migration, not a feature addition. | Plain JS state management already in place in `app.js` |
| Multiple Monaco editor instances | Each instance uses ~80MB RAM and causes layout conflicts. Monaco is designed for one instance per container. | `monaco.editor.setModel()` + per-workspace `ITextModel` objects |
| Multiple xterm.js Terminal instances with separate DOM containers per workspace | Xterm terminals are expensive to create (PTY subprocess per terminal). Existing pattern already manages N terminals in `_termSessions`. | Reuse existing `_termSessions` array, tag each session with a `workspaceId` field for filtering/display |
| `sessionStorage` for workspace config | Dies on tab close; user would lose workspace layout on every browser close. | `localStorage` — workspace config is persistent user preference |
| Arbitrary absolute path from client in `/api/ide/tree` | Path traversal vulnerability — client could supply `../../etc/` | Server-side registered roots allowlist: client sends workspace ID, server resolves path |
| Separate backend service for workspace management | This is a dashboard feature, not an independent service. Adds deployment complexity for no gain. | Add endpoints to existing `server.py` following the `/api/ide/*` pattern |

---

## Stack Patterns by Variant

**If a workspace points to an Agent42 app (inside `apps/` subdirectory):**

- `rootPath` is `AGENT42_WORKSPACE / "apps" / appname`
- Already inside the global workspace sandbox — no special allowlist entry needed
- File tree and terminal cwd both resolve correctly within existing security model

**If a workspace points to an external repo (outside `AGENT42_WORKSPACE`):**

- Must be explicitly registered in `workspaces.json` during workspace creation
- Server validates the path exists and is a directory at registration time
- Sandbox check at each file operation: `target.resolve().startswith(registered_root.resolve())`
- This is the only case that requires the registered-roots allowlist instead of the global workspace root

**If no workspaces are configured (fresh install or feature toggled off):**

- Workspace tab bar renders a single implicit default workspace rooted at `AGENT42_WORKSPACE`
- No behavioral change from current single-workspace mode
- Zero impact on existing deployments

---

## Version Compatibility

| Component | Version in Use | Notes |
| --- | --- | --- |
| Monaco Editor | 0.52.2 (CDN) | `monaco.editor.createModel()`, `editor.setModel()`, `editor.saveViewState()`, `editor.restoreViewState()` all stable since 0.20+. No version change needed. |
| xterm.js | Self-hosted (dist/xterm/) | `Terminal` constructor, `FitAddon` — both stable API. No per-workspace changes needed; tag sessions with `workspaceId` in existing session objects. |
| FastAPI | 0.115.0+ | `Query()` parameters for new `root`/`cwd` params on existing endpoints; new router for `/api/workspaces`. No version change needed. |
| pywinpty | 2.0.0+ (Windows) | `PtyProcess.spawn(cwd=str(path))` already used. Passing a different registered path is equivalent. |
| aiofiles | 23.0.0+ | Already in requirements.txt for `workspaces.json` persistence. |
| Python stdlib Path | 3.11+ | `Path.resolve()` for symlink-safe path containment check. |

---

## Sources

- Agent42 codebase — `dashboard/frontend/dist/app.js` (direct inspection of IDE state, terminal spawning, Monaco init, localStorage usage, CC chat session management) — HIGH confidence
- Agent42 codebase — `dashboard/server.py` lines 1296–1440 (IDE endpoints), 1441–1720 (terminal WS), 1721–2290 (CC chat WS including `workspace_path` parameter usage) — HIGH confidence
- `dashboard/frontend/dist/index.html` — Monaco 0.52.2, marked 17.0.4, highlight.js 11.11.1, DOMPurify 3.3.3 version confirmation — HIGH confidence
- Monaco Editor API docs — `ITextModel`, `editor.setModel()`, `editor.saveViewState()` / `restoreViewState()` confirmed stable since 0.20 — MEDIUM confidence (training data consistent with 0.52.x API surface; version-specific verification not done via Context7)
- PROJECT.md — v2.1 milestone requirements: workspace tab bar, scoped file explorer, scoped CC sessions, scoped terminals, workspace management, localStorage persistence — HIGH confidence

---

*Stack research for: Multi-project workspace tabs (v2.1 milestone on Agent42)*
*Researched: 2026-03-23*
