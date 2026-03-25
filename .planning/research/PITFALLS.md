# Pitfalls Research

**Domain:** Multi-project workspace tabs in an existing single-workspace web IDE (Agent42 v2.1)
**Researched:** 2026-03-23
**Confidence:** HIGH for Agent42-specific integration risks (direct code inspection); MEDIUM for general multi-workspace IDE patterns (domain reasoning from known VS Code / Monaco patterns)

---

## Critical Pitfalls

Mistakes that cause data corruption, subprocess leakage, or silent state bleed between workspaces.

---

### Pitfall 1: Monaco URI Collisions Between Workspaces

**What goes wrong:**
Monaco uses `monaco.Uri.parse("file:///" + path)` to construct a globally unique model key. The current path is always relative to the single workspace root (e.g., `src/main.py`). When two workspace tabs are open and both contain a file at the same relative path (e.g., `agent42/src/main.py` and `meatheadgear/src/main.py`), both get the URI `file:///src/main.py`. `monaco.editor.getModel(uri)` returns the first model — whichever was opened first. The second workspace silently edits the wrong file. Saves propagate to the wrong path. The bug is invisible in the editor (the file appears to load correctly) but corrupts the second project's files on disk.

**Why it happens:**
The current code at line 3761 of `app.js` constructs the URI from the file path returned by `/api/ide/file`, which is a path relative to the single `workspace` root. When multi-workspace is added, developers typically just add a workspace selector to the tree and reuse the existing `ideOpenFile()` path without making the URI workspace-scoped. The collision only manifests when two workspaces share a relative path, which is common (`README.md`, `requirements.txt`, `.gitignore` appear in nearly every project root).

**How to avoid:**
Prefix Monaco URIs with the workspace ID: `"file:///ws-" + workspaceId + "/" + relativePath`. Each workspace must have a stable, unique ID (UUID or URL-safe name slug). The `ideOpenFile()` function must receive the workspace context, not just the path. When switching workspace tabs, the editor must call `setModel()` to the correct model for the new workspace context, not just re-open by path.

**Warning signs:**

- Saving a file in workspace B overwrites a file in workspace A
- `monaco.editor.getModels()` returns fewer models than expected (duplicates were silently ignored)
- File content from one project appears in the editor when the other project is active

**Phase to address:**
Phase 1 (workspace model and data layer) — URI namespacing must be established before any editor state is tracked. Cannot be retrofitted after tab switching is built.

---

### Pitfall 2: Terminal PTY Sessions Spawned With Global `workspace` Variable

**What goes wrong:**
The current terminal WebSocket handler (`/ws/terminal`) spawns all PTY processes with `cwd=str(workspace)`, where `workspace` is the single global `Path` resolved from `AGENT42_WORKSPACE` at server startup (line 1301 of `server.py`). When multi-workspace support is added and users open terminals in different workspace tabs, all terminals still spawn in the same global workspace directory regardless of which tab opened them. The user types `ls` and sees the wrong project's files. More critically, they may run `git commit` or `python manage.py migrate` in the wrong project directory without noticing.

**Why it happens:**
`workspace` is a module-level variable set once at server start inside `create_app()`. Every endpoint and WebSocket handler in that closure captures the same `workspace` reference. When a second workspace is added, the temptation is to add it as a query parameter to the WebSocket connection — but the module-level `workspace` variable is already used by dozens of code paths and changing them all is error-prone.

**How to avoid:**
The terminal WebSocket (`/ws/terminal`) must accept a `workspace_root` query parameter and resolve it server-side from the workspace configuration store (not from user-controlled path input directly). The server must maintain a `WorkspaceRegistry` that maps workspace IDs to resolved absolute paths. The terminal handler looks up the path by ID: `cwd = workspace_registry.get_path(workspace_id)`. User-supplied workspace_root strings must be validated against the registry — they cannot be arbitrary paths (this would be a path traversal vulnerability).

**Warning signs:**

- New terminals always open in `AGENT42_WORKSPACE` regardless of which workspace tab is active
- `pwd` in a new terminal shows the default workspace root, not the selected workspace
- Git operations in terminal affect the wrong repository

**Phase to address:**
Phase 1 (workspace model and data layer) — the `WorkspaceRegistry` must exist before any terminal spawning is changed. Phase 2 (terminal scoping) wires the registry into the WebSocket handler.

---

### Pitfall 3: CC Subprocess cwd Baked Into the Warm Pool Key

**What goes wrong:**
The CC warm pool is keyed by `user` only (`_cc_warm_pool[user]`). The warm process is spawned with `cwd=str(workspace_path)` passed to `_cc_spawn_warm()`. When multi-workspace is added, the warm pool must be keyed by `(user, workspace_id)`. If the key stays as just `user`, the warm session for workspace A will be consumed when workspace B opens its first CC session — Claude Code launches in the wrong directory. The `--resume` flag then resumes a session that was started in the wrong project tree, meaning Claude's context is contaminated with the other project's file paths and git state.

**Why it happens:**
`_cc_spawn_warm()` already accepts a `workspace_path` argument (line 1747), so the warm spawning code is workspace-aware. But the pool dict at line 1737 (`_cc_warm_pool: dict = {}`) only supports one entry per user. This is a silent semantic mismatch — the spawning code is correct but the storage key is wrong.

**How to avoid:**
Change `_cc_warm_pool` to key on `(user, workspace_id)` tuple. The warm pool expiry cleanup loop (line 1912) must iterate by tuple key. When a CC WebSocket connects with a `workspace_id` query parameter, it pops from `_cc_warm_pool.get((user, workspace_id))` not `_cc_warm_pool.get(user)`. Add the `workspace_id` to the WebSocket's `session_id` namespace as well so CC sessions from different workspaces never share `--resume` sessions.

**Warning signs:**

- Claude Code opens and immediately references files from the other workspace project
- `--resume` session shows a different project's context (wrong git root, wrong file paths)
- CC warm pool entry is consumed by a different workspace than expected

**Phase to address:**
Phase 2 (CC session scoping) — must be addressed before warm pool is retained across workspace switches.

---

### Pitfall 4: File API Paths Resolved Against Single Global `workspace`

**What goes wrong:**
All four IDE file endpoints (`/api/ide/tree`, `/api/ide/file` GET, `/api/ide/file` POST, `/api/ide/search`) resolve paths against the module-level `workspace` variable (lines 1306–1409 of `server.py`). The sandbox check (`not str(target).startswith(str(workspace.resolve()))`) ensures the path stays inside the single workspace. When multi-workspace is added, paths for workspace B will always fail this check (they are outside workspace A's directory). Developers who work around this by removing the sandbox check have created a path traversal vulnerability. Developers who add a `workspace_root` query parameter that the server uses directly (without validation against a registry) have also created a vulnerability.

**Why it happens:**
The four endpoints were written for a single workspace and the sandbox check is a direct string comparison against a known root. Adding a second workspace naively means either disabling the check or duplicating it with a user-supplied root path.

**How to avoid:**
The `WorkspaceRegistry` (from Pitfall 2 prevention) is the correct solution here too. Each endpoint accepts a `workspace_id` query parameter; the server resolves the workspace root from the registry; the sandbox check is performed against the resolved root. The registry lookup must not accept arbitrary paths from the client — only registered workspace IDs. The resolution pattern becomes: `root = registry.resolve(workspace_id)` then `target = (root / path).resolve()` then `assert str(target).startswith(str(root))`.

**Warning signs:**

- Files from workspace B return 403 when workspace B's path is not under `AGENT42_WORKSPACE`
- Developer removes sandbox check to "fix" 403 errors
- Client sends full absolute paths in `path` parameter to work around the root mismatch

**Phase to address:**
Phase 1 (workspace model and data layer) — WorkspaceRegistry is the prerequisite; Phase 2 (file API scoping) threads it through the four IDE endpoints.

---

### Pitfall 5: localStorage Keys Collide Across Workspaces

**What goes wrong:**
CC session history is stored with keys of the form `cc_hist_<sessionId>` (line 5335 of `app.js`). The `cc_active_session` key in `sessionStorage` (line 4813) tracks which CC session is active. Neither key includes a workspace identifier. When workspace A and workspace B each have their own CC sessions, and the user switches tabs, the `cc_active_session` value in sessionStorage is overwritten with the new workspace's session ID. On the next page reload, the history restoration logic (`ccRestoreHistory`) pulls from a `cc_hist_*` key that was last set by whichever workspace was active at reload time. Workspace A's chat history appears in workspace B's CC panel, or vice versa.

**Why it happens:**
The existing localStorage architecture (pitfall #120 in CLAUDE.md) was designed for a single workspace with multiple CC sessions. The session ID is workspace-agnostic — it is a UUID assigned by the server with no workspace metadata embedded. A page reload with `sessionStorage.cc_active_session = "abc"` will always restore session "abc" regardless of which workspace the user was in.

**How to avoid:**
Namespace all localStorage and sessionStorage keys with the active workspace ID. The `cc_active_session_<workspaceId>` pattern ensures each workspace tab has its own "last active CC session" pointer. Workspace configuration (list of workspaces, their names and roots) must be persisted in localStorage under a stable key like `agent42_workspaces` so the workspace tab bar can be rebuilt after reload without a round-trip. When a workspace is deleted, sweep localStorage for all keys prefixed with that workspace ID.

**Warning signs:**

- CC chat history from workspace A appears in workspace B after switching tabs
- Page reload restores the wrong workspace's CC session
- Adding a new workspace does not create isolated CC session state

**Phase to address:**
Phase 1 (workspace model and data layer) — key namespacing schema must be locked before any storage is implemented. Cannot be renamed later without breaking existing persisted data.

---

### Pitfall 6: `_ideTabs` Array and `_termSessions` Array Are Global Singletons

**What goes wrong:**
The editor tabs array (`_ideTabs`, line 3398 of `app.js`) and terminal sessions array (`_termSessions`, line 5720) are global JavaScript singletons. When the user switches workspace tabs, these arrays still contain the editor tabs and terminal sessions from the previous workspace. If the workspace switch just changes the file tree root but leaves `_ideTabs` intact, the tab bar shows files from the old workspace. If the workspace switch clears and re-fills these arrays, all open editor tabs from the previous workspace are closed (UX regression — user loses their open files). Neither behavior is correct.

**Why it happens:**
The single-workspace design assumes there is exactly one logical "workspace context" per page load. The global arrays are the entire editor state. There is no concept of "save this workspace's tab state and restore it later."

**How to avoid:**
Snapshot and restore tab/terminal state per workspace. When switching workspaces: (1) serialize the current workspace's `_ideTabs` and `_termSessions` state into the workspace's localStorage slot; (2) deserialize the new workspace's saved state; (3) re-open the Monaco models for the new workspace. Monaco models from the old workspace stay in the editor registry (they are not disposed) so they can be restored when the user switches back. The serialized state should contain paths and model content (not Monaco model objects, which are not serializable) — the models are recreated lazily when the tab becomes active again.

**Warning signs:**

- Switching workspace tabs clears all open editor tabs
- Files from workspace A remain open in the editor tab bar after switching to workspace B
- Terminal sessions don't reset when switching workspaces (wrong cwd)

**Phase to address:**
Phase 2 (frontend workspace switching) — workspace state snapshot/restore must be designed before the workspace tab switcher UI is built.

---

### Pitfall 7: CC Sessions Directory Lives Under the Single `workspace` Root

**What goes wrong:**
CC session files are stored at `workspace / ".agent42" / "cc-sessions"` (line 1727 of `server.py`). This is a fixed path relative to the global `workspace`. When multi-workspace is added, all workspace tabs share the same CC session directory. Session IDs are UUIDs so there is no collision between sessions — but if the user is in workspace B and resumes a CC session that was started in workspace A (because the session picker shows all sessions regardless of workspace), Claude Code resumes with workspace A's cwd and git context.

**Why it happens:**
The CC session store was designed as a shared per-server resource, not a per-workspace resource. Sessions are distinguished by UUID, not by workspace. The session picker in the UI (lines 2736–2750 of `server.py`) lists all sessions from the shared directory.

**How to avoid:**
Store CC sessions under each workspace's `.agent42/cc-sessions/` subdirectory, not under the global workspace root. The workspace-scoped session directory is passed to `_save_session()` and `_load_session()` (which already accept an optional `sessions_dir` parameter at lines 2215–2224). The session list endpoint must filter by workspace. When the user opens the session picker, they only see sessions from the current workspace. Cross-workspace resume is not a supported use case.

**Warning signs:**

- Session list shows sessions from all workspaces mixed together
- Resuming a session launches Claude Code in the wrong project directory
- Sessions from deleted workspaces still appear in the picker

**Phase to address:**
Phase 2 (CC session scoping) — must be aligned with the WorkspaceRegistry design from Phase 1.

---

### Pitfall 8: File Search Results Return Relative Paths That Are Workspace-Ambiguous

**What goes wrong:**
`/api/ide/search` returns matches with `"file"` set to a workspace-relative path (line 1430 of `server.py`). The frontend's `ccOpenDiffFromToolCard()` and `ideOpenFile()` functions consume these paths directly. When two workspaces are open and the user performs a search in workspace B while workspace A has a file open with the same relative path, clicking a search result silently opens the wrong file (the one already loaded from workspace A's model, due to Pitfall 1). The user edits workspace A's copy instead of workspace B's.

**Why it happens:**
Paths returned by the API are workspace-relative by design (they're stripped via `fpath.relative_to(workspace)`). The frontend has no way to know which workspace the path belongs to — it just calls `ideOpenFile(path)`. The ambiguity only manifests under multi-workspace.

**How to avoid:**
All API responses that return file paths must include a `workspace_id` field. The frontend `ideOpenFile()` must be updated to accept `(path, workspaceId)`. The search result click handler must pass both the path and workspace ID. The CC tool card diff handler must include workspace context. This is a systemic change to the file path data model — it cannot be patched one endpoint at a time.

**Warning signs:**

- Clicking search results in workspace B opens files from workspace A's Monaco model
- Diff viewer shows content from the wrong workspace
- CC tool card "Open File" links navigate to the wrong project's file

**Phase to address:**
Phase 1 (workspace model) — define the `(workspace_id, path)` pair as the canonical file reference before any API or frontend uses it; Phase 2 (API threading) propagates it through every endpoint.

---

### Pitfall 9: Workspace Configuration Persisted to localStorage Without Server Validation

**What goes wrong:**
The workspace tab bar's configuration (workspace name, root path, ID) is most naturally persisted in `localStorage` for instant reload. However, if the server's `WorkspaceRegistry` is the authoritative source (for security reasons — arbitrary paths must not be accepted from the client), then localStorage and server state can diverge. A workspace is added on machine A, then the user opens Agent42 on machine B — localStorage is empty, the workspace tabs bar is empty, but the workspaces exist on the server. Conversely, a workspace is removed from the server directly (its folder deleted), but localStorage still shows it as a tab — clicking it shows errors.

**Why it happens:**
localStorage is a client-only store with no synchronization mechanism. Single-workspace systems can use it freely because there is only one implicit workspace. Multi-workspace systems need a canonical source of truth, and the choice between client and server has UX trade-offs.

**How to avoid:**
Server is the authoritative workspace registry. On page load, the frontend fetches the workspace list from a new `/api/workspaces` endpoint and replaces the localStorage cache. localStorage is used only as a stale-while-revalidate performance optimization (to render the tab bar immediately before the API responds), not as a source of truth. The server validates that workspace root paths exist and are accessible before accepting them into the registry.

**Warning signs:**

- Workspace tabs bar shows workspaces that no longer exist on disk
- Opening Agent42 on a different machine shows no workspaces even though they were configured
- Workspace paths from localStorage are used directly in API calls without server-side validation

**Phase to address:**
Phase 1 (workspace model and data layer) — server-side registry is the design prerequisite for all other workspace work.

---

### Pitfall 10: The Single Monaco Editor Instance Loses Layout After Workspace Switches

**What goes wrong:**
`_monacoEditor` is a single editor instance. When the workspace tab switches, `_monacoEditor.setModel()` is called to show the new workspace's current file. But if the workspace tab switch triggers a DOM re-render (e.g., if `renderCode()` is called, which rebuilds the IDE layout from scratch), the Monaco container is destroyed and recreated. The current code at line 3587–3591 handles the "container was destroyed" case by disposing and recreating the editor. Each dispose/create cycle loses the cursor position, scroll position, folding state, and undo history for all previously open models. Users lose their editing context on every workspace switch.

**Why it happens:**
The single-editor pattern assumes the container DOM is stable (only one page). In a tabbed workspace, if the outer layout re-renders, the editor container's DOM node is replaced even though it looks the same. Monaco models survive DOM replacement (they're in a global registry) but the editor instance's per-model view state (cursor, scroll, folding) does not survive editor disposal.

**How to avoid:**
Save and restore Monaco view state on model switches. When switching from file A to file B (whether within one workspace or across workspaces), call `editorViewStateMap[modelUri] = editor.saveViewState()` before calling `setModel()`. After `setModel()`, call `editor.restoreViewState(editorViewStateMap[newModelUri])`. This map is keyed by the workspace-scoped URI (from Pitfall 1 prevention). View state is lightweight (cursor position, scroll offset, folding) and doesn't need to be persisted across page loads.

**Warning signs:**

- Cursor jumps to line 1 every time you switch workspace tabs
- Scroll position resets when switching workspace tabs
- Undo history is lost after switching to another workspace and returning

**Phase to address:**
Phase 2 (frontend workspace switching) — view state saving must be part of the tab-switching logic, not added as a polish step later.

---

## Technical Debt Patterns

Shortcuts that seem reasonable but create long-term problems.

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
| --- | --- | --- | --- |
| Using file path (not workspace_id + path) as the canonical file reference | No API changes needed initially | Silent file open collisions when two workspaces share a relative path (Pitfall 1, 8) | Never |
| Storing workspace config in localStorage only (no server registry) | Zero backend changes for workspace persistence | Diverges across machines; client can inject arbitrary paths (security risk); Pitfall 9 | Never |
| Passing `workspace_root` as a client-supplied query parameter to terminal WS | Simple to implement | Path traversal vulnerability — user can supply any path the server process can access | Never |
| Reusing the single global `workspace` variable by mutating it on workspace switch | No new data model required | All concurrent users (or concurrent tabs in same browser) share one global workspace — mutual corruption | Never |
| Clearing `_ideTabs` on workspace switch instead of saving/restoring state | Simpler state management | All open editor tabs are lost on every workspace switch — major UX regression | Only during initial prototype/demo |
| Single CC sessions directory for all workspaces | No migration needed | Session list is workspace-polluted; resume loads wrong project context (Pitfall 7) | Never for production |
| Skipping warm pool key change (keep `user`-only key) | No disruption to existing CC session logic | Wrong workspace warm session consumed; CC starts in wrong project directory (Pitfall 3) | Never |

---

## Integration Gotchas

Common mistakes when connecting to the existing Agent42 systems.

| Integration | Common Mistake | Correct Approach |
| --- | --- | --- |
| Monaco `editor.getModel(uri)` | URI is workspace-relative path (`file:///src/main.py`) | URI must include workspace ID prefix (`file:///ws-<id>/src/main.py`) |
| `/api/ide/tree`, `/api/ide/file`, `/api/ide/search` | Passing absolute `workspace_root` path from client | Pass `workspace_id`; server resolves root from `WorkspaceRegistry` |
| `/ws/terminal` PTY spawn | `cwd=str(workspace)` (module-level global) | `cwd=str(registry.get_path(workspace_id))` from query param |
| `/ws/cc` warm pool | `_cc_warm_pool[user]` dict key | `_cc_warm_pool[(user, workspace_id)]` tuple key |
| `_CC_SESSIONS_DIR` (shared) | All workspaces share `workspace / ".agent42" / "cc-sessions"` | Each workspace stores sessions under its own `.agent42/cc-sessions/` |
| `localStorage` CC history keys | `cc_hist_<sessionId>` (workspace-agnostic) | `cc_hist_<workspaceId>_<sessionId>` or workspace-scoped prefix |
| `sessionStorage` active CC session | `cc_active_session` (single value) | `cc_active_session_<workspaceId>` per workspace |
| `_ideTabs` / `_termSessions` global arrays | Shared across all workspace tabs | Snapshot on switch; restore on return; scoped to active workspace context |

---

## Performance Traps

Patterns that work at small scale but fail as workspace count grows.

| Trap | Symptoms | Prevention | When It Breaks |
| --- | --- | --- | --- |
| All Monaco models for all workspaces kept in memory simultaneously | Browser memory grows linearly with total open files across all workspaces | Dispose models for workspaces that have been inactive >30 min; recreate on next switch | At ~3 workspaces with ~20 files each open |
| File tree for all workspaces fetched on page load | Slow initial load, unnecessary API calls for inactive workspaces | Lazy-load file tree on workspace tab activation; cache with TTL | At ~5 workspaces |
| CC warm pool spawns one process per workspace on login | Startup takes 5–15 seconds; API rate-limit spikes | Only warm the default/active workspace; warm others lazily on first tab open | At ~3 workspaces |
| WorkspaceRegistry reads config from disk on every API request | File I/O on every `/api/ide/tree` call | Cache registry in memory; invalidate on write; startup load only | At any scale under concurrent requests |

---

## Security Mistakes

Domain-specific security issues beyond general web security.

| Mistake | Risk | Prevention |
| --- | --- | --- |
| Accepting raw `workspace_root` path from client in any API or WebSocket | Path traversal: attacker supplies `../../etc` as workspace root | Server-side `WorkspaceRegistry`; client only supplies `workspace_id`; server resolves and validates the path |
| Workspace config stored in localStorage and used directly in API calls | Client can modify localStorage to craft any path and send it | Server is authoritative; API accepts only registered workspace IDs |
| CC warm pool keyed by user only | User A's warm session (workspace A's cwd) consumed when user A opens workspace B | Key pool by `(user, workspace_id)` tuple |
| File path collision allowed to silently succeed | Reads/writes affect wrong workspace's files | Workspace-prefixed Monaco URIs + API workspace_id enforcement catches mismatches |
| Workspace deletion leaves dangling CC session files and localStorage keys | Stale sessions can be resumed (in a deleted/now-different directory) | On workspace deletion: invalidate CC sessions, clear localStorage namespace, unregister from WorkspaceRegistry |

---

## UX Pitfalls

Common user experience mistakes in multi-workspace IDE features.

| Pitfall | User Impact | Better Approach |
| --- | --- | --- |
| Workspace tab switch loses all open editor tabs | User must re-open every file after switching workspaces | Save/restore tab state per workspace (Pitfall 6 prevention) |
| No visual indicator of which workspace a terminal is scoped to | User runs git command in wrong project | Show workspace name in terminal tab label |
| CC session picker shows all sessions from all workspaces | User resumes wrong project's session | Filter session list to active workspace |
| Saving workspace config via a modal with no persistence feedback | User closes modal; wonders if it was saved | Show workspace name in tab immediately; persist to server before closing modal |
| No indication when a workspace folder is missing or inaccessible | File tree is empty; no error message | `WorkspaceRegistry.validate()` on load; show inline error in the tab if folder is gone |
| Workspace tabs without a max-count limit | More than ~6 workspaces makes the tab bar unusable | Enforce a max of 8 workspaces with a clear UX message; offer a workspace switcher modal for more |

---

## "Looks Done But Isn't" Checklist

Things that appear complete but are missing critical pieces.

- [ ] **Monaco URI scoping:** File opens successfully in workspace B — verify `monaco.editor.getModels()` shows distinct URIs for same-relative-path files in workspace A and workspace B
- [ ] **Terminal cwd:** New terminal in workspace B tab — verify `pwd` shows workspace B's root, not the default `AGENT42_WORKSPACE`
- [ ] **CC session scoping:** Open CC in workspace B — verify `claude` launches with `cwd` of workspace B's root; verify resume session list only shows workspace B sessions
- [ ] **File API sandbox:** Request `/api/ide/file?path=../../../etc/passwd&workspace_id=<valid_id>` — must return 403, not file content
- [ ] **localStorage isolation:** Open CC in workspace A (chat), switch to workspace B, reload page — verify workspace A's CC history does not appear in workspace B's panel
- [ ] **Workspace switch preserves editor state:** Switch from workspace A to B and back — verify cursor position in workspace A's open file is the same as before the switch
- [ ] **Warm pool isolation:** Trigger warm session for workspace A, then open CC in workspace B — verify workspace B spawns its own warm session (workspace A's is not consumed)
- [ ] **Workspace deletion cleanup:** Delete workspace B from the registry — verify workspace B's CC sessions, localStorage keys, and Monaco models are all cleaned up

---

## Recovery Strategies

When pitfalls occur despite prevention, how to recover.

| Pitfall | Recovery Cost | Recovery Steps |
| --- | --- | --- |
| Monaco URI collision corrupts files (Pitfall 1) | HIGH | Audit git history of affected files; restore from last clean commit; implement URI namespacing before re-enabling multi-workspace |
| Terminal spawns in wrong workspace (Pitfall 2) | LOW | Close terminal; add workspace_id to terminal WS params; reopen |
| CC warm pool consumed wrong workspace (Pitfall 3) | LOW | Clear `_cc_warm_pool`; restart Agent42; warm pool re-initializes on next CC open |
| File API accepts raw paths — path traversal exploited (Pitfall 4) | HIGH | Audit server logs for unauthorized reads; rotate credentials; implement WorkspaceRegistry immediately; redeploy |
| localStorage keys collide — history contamination (Pitfall 5) | LOW | Clear localStorage for agent42 keys; re-open workspaces; history is also server-persisted |
| Global `_ideTabs` cleared on every workspace switch (Pitfall 6) | LOW | Implement snapshot/restore; existing open tabs cannot be recovered but new behavior prevents recurrence |

---

## Pitfall-to-Phase Mapping

How roadmap phases should address these pitfalls.

| Pitfall | Prevention Phase | Verification |
| --- | --- | --- |
| Monaco URI collision (Pitfall 1) | Phase 1: Workspace data model — establish URI namespacing convention | `monaco.editor.getModels()` shows workspace-prefixed URIs; no collisions on same-relative-path files |
| Terminal cwd wrong (Pitfall 2) | Phase 1: WorkspaceRegistry + Phase 2: terminal scoping | New terminal `pwd` == workspace root; verified with two workspaces pointing to different dirs |
| CC warm pool wrong workspace (Pitfall 3) | Phase 2: CC session scoping | Warm pool dict keyed by tuple; confirmed in code review + test with 2 users and 2 workspaces |
| File API sandbox bypass (Pitfall 4) | Phase 1: WorkspaceRegistry + Phase 2: API scoping | Path traversal curl test returns 403; workspace_id-only API tested |
| localStorage key collisions (Pitfall 5) | Phase 1: Storage key schema | localStorage keys contain workspace_id; verified by inspecting browser devtools storage |
| Global IDE arrays not scoped (Pitfall 6) | Phase 2: Frontend workspace switching | Switch workspaces 3 times; verify each workspace retains its own open tabs and terminal sessions |
| CC session directory shared (Pitfall 7) | Phase 2: CC session scoping | Session list endpoint filtered by workspace; verified with two workspaces each having sessions |
| File path workspace-ambiguous (Pitfall 8) | Phase 1: Data model + Phase 2: API threading | All file API responses include `workspace_id`; frontend passes it to `ideOpenFile()` |
| Workspace config in localStorage only (Pitfall 9) | Phase 1: Server-side registry | Workspace list fetched from `/api/workspaces` on load; localStorage is cache only |
| Monaco view state lost on switch (Pitfall 10) | Phase 2: Frontend workspace switching | Switch workspace, return, verify cursor position preserved |

---

## Sources

- Direct code inspection: `dashboard/server.py` lines 1301–1430 (workspace variable, sandbox check, file APIs), lines 1447–1690 (terminal PTY spawn with `cwd=str(workspace)`), lines 1727–2450 (CC sessions directory, warm pool keyed by user, CC WebSocket handler) — HIGH confidence
- Direct code inspection: `dashboard/frontend/dist/app.js` lines 3396–3930 (`_monacoEditor` singleton, `_ideTabs` global array, Monaco URI construction at line 3761), lines 5720–5990 (`_termSessions` global array), lines 5332–5395 (`cc_hist_<sessionId>` localStorage keys), lines 4813–4817 (`cc_active_session` sessionStorage) — HIGH confidence
- CLAUDE.md pitfall #120: localStorage CC history design, session restore on reload — HIGH confidence (project history)
- CLAUDE.md pitfall #122: GSD nested repo root detection failure — MEDIUM confidence (parallel problem to workspace root confusion)
- CLAUDE.md pitfall #83: duplicate API calls from workspace-scoped state — HIGH confidence (project history showing state isolation bugs)
- VS Code architecture documentation: editor model registry, URI-based model identity — MEDIUM confidence (web search + known Monaco internals)
- Monaco Editor docs: `editor.createModel(content, language, uri)`, `editor.getModel(uri)`, `editor.saveViewState()`/`editor.restoreViewState()` — HIGH confidence (official Monaco API)

---

*Pitfalls research for: Multi-project workspace tabs (Agent42 v2.1)*
*Researched: 2026-03-23*
