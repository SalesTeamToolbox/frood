# Phase 50: Strip Harness Features - Research

**Researched:** 2026-04-07
**Domain:** FastAPI server route deletion, hand-written SPA editing, Python auth simplification
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01** Remove Mission Control — server.py tasks/projects routes, frontend renderMissionControl
- **D-02** Remove Workspace/IDE — Monaco editor, terminal, file browser, IDE chat; /api/ide/*, /ws/terminal, renderCode
- **D-03** Remove Agents page — /api/agents/*, renderAgents
- **D-04** Remove Teams page — renderTeams (no server routes)
- **D-05** Remove Approvals — /api/approvals, renderApprovals
- **D-06** Remove GitHub Integration — /api/github/*, /api/repos/*
- **D-07** Remove Chat — /api/chat/*, /ws/cc-chat, /api/cc/*, renderChat
- **D-08** Remove Device Gateway — /api/devices/*, auth.py device key validation
- **D-09** Remove GSD Workstreams UI — /api/gsd/*
- **D-10** Remove Status page — /api/status, renderStatus
- **D-11** Remove Agent Profiles — /api/profiles/*, /api/agent-routing/*
- **D-12** Remove Persona — /api/persona
- **D-13** Remove Rewards API — /api/rewards/*
- **D-14** Remove Projects — /api/projects/* (gated by project_manager)
- **D-15** Keep Auth — /api/login, /api/logout, /api/setup/*
- **D-16** Keep Memory — /api/memory/*
- **D-17** Keep Tools — /api/tools/*
- **D-18** Keep Skills — /api/skills/*
- **D-19** Keep Reports — /api/reports
- **D-20** Keep Effectiveness — /api/effectiveness/*, /api/learnings/*
- **D-21** Keep Provider Status — /api/providers/*
- **D-22** Keep LLM Chat Proxy — /llm/*
- **D-23** Keep Settings — /api/settings/*
- **D-24** Keep Agent Apps — /api/apps/*
- **D-25** Keep Health — /health, /api/health
- **D-26** Keep WebSocket infrastructure — broadcast mechanism, remove harness event handlers
- **D-27** app.js is hand-written 8,924 lines — surgically edit, no build system
- **D-28** Remove: renderMissionControl, renderStatus, renderApprovals, renderCode, renderAgents, renderTeams, renderChat
- **D-29** Update sidebar navigation (lines ~8786-8796) — only kept pages
- **D-30** Update page renderers object (lines ~8829-8843) — remove harness entries
- **D-31** Remove device API key validation from auth.py — keep JWT only
- **D-32** Simplify get_auth_context() to skip API key validation path
- **D-33** Bottom-to-top removal in server.py to avoid line number drift
- **D-34** Remove associated imports, helpers, and model classes that become orphaned
- **D-35** Activity Feed (_record_activity(), _activity_feed list) — remove entirely in this phase

### Claude's Discretion

- Exact order of route group removal within the bottom-to-top strategy
- Whether to leave stub 410 endpoints or remove routes entirely (preference: remove entirely)
- How to handle @standalone_guard decorator — can be removed from kept routes since all harness routes are gone

### Deferred Ideas (OUT OF SCOPE)

- Agent Apps rename — "Apps" → "Agent Apps" in UI/API is Phase 51 (BRAND-01)
- Activity Feed repurpose — Intelligence event log is Phase 51 (FEED-01 through FEED-03)
- Frood branding polish — Remaining "Agent42" text cleanup is Phase 51 (BRAND-03)
- Internal package rename — `agent42` → `frood` in Python is out of scope entirely
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| STRIP-01 | Remove Mission Control (Kanban board, tasks, projects) | renderMissionControl at L3556, renderProjectsBoard at L3573, renderProjectDetail at L3619, renderTasks at L1842, renderKanbanBoard at L1881, renderListView at L1944; server.py Projects block L5727-5890 |
| STRIP-02 | Remove Workspace/IDE (Monaco editor, terminal, file browser, Claude Code chat) | renderCode at L4185 (~3250 lines), renderCanvasPanel at L3267, renderReposPanel at L7445; server.py IDE L1429-1710, Workspaces L1376-1428, CC-chat L2065-3082, Terminal L1776-2064 |
| STRIP-03 | Remove Agents page (agent lifecycle CRUD, start/stop/delete) | renderAgents at L2383 (~400 lines); server.py Agents L4732-4943 |
| STRIP-04 | Remove Teams page (multi-agent team monitoring) | renderTeams at L2785, renderTeamRunDetail at L2832; no server routes |
| STRIP-05 | Remove Approvals page (human-in-the-loop task review) | renderApprovals at L2144; server.py Approvals L5049-5066 |
| STRIP-06 | Remove GitHub Integration (repo cloning, OAuth, account management) | renderReposPanel at L7445 (embedded in renderCode); server.py GitHub+Repos L5914-6193 |
| STRIP-07 | Remove Chat features (chat sessions, message streaming, conversation interface) | renderChat at L3410; server.py Chat+IDE Chat L3282-4112, CC Sessions L3082-3119 |
| STRIP-08 | Remove Device Gateway (multi-device management, device API keys) | server.py Devices L5067-5139; auth.py _validate_api_key(), _device_store, init_device_store(), API_KEY_PREFIX branch in get_auth_context(); /ws WebSocket device auth block |
| STRIP-09 | Remove GSD Workstreams UI (phase tracking in dashboard) | server.py GSD L1612-1708 |
| STRIP-10 | Remove Status page (platform capacity dashboard) | renderStatus at L3044; server.py /api/status L608-642 |
| STRIP-11 | Remove Agent Profiles (profile CRUD, routing overrides — already 410 Gone) | server.py Profiles+Routing+Persona L858-1073 |
| STRIP-12 | Remove Persona customization (chat system prompt — no chat = no persona) | included in STRIP-11 range; renderRoutingPanel at L8698, renderChainSummary at L8591 |
| CLEAN-01 | Remove dead server.py routes for stripped features | All route groups listed in STRIP-01 through STRIP-12; also remove orphaned Pydantic models and top-level stubs |
| CLEAN-02 | Remove dead frontend code for stripped pages/components | ~3,000+ lines from app.js; state variables, load* functions, harness API calls, sidebar entries, renderers map entries |
| CLEAN-03 | Remove unused Python modules (if any become orphaned) | device_auth import in auth.py; top-level imports in server.py (ApprovalGate, DeviceStore, Settings); inline imports inside removed routes |
| CLEAN-04 | Ensure all tests still pass after removal | ~9 test files to delete, ~5 to modify; baseline: 2,274 tests collected |
</phase_requirements>

---

## Summary

Phase 50 is a pure deletion phase with no new functionality. The work is removing approximately 1,600 lines from `dashboard/server.py`, 3,000+ lines from `dashboard/frontend/dist/app.js`, and 70 lines from `dashboard/auth.py`. The codebase has already undergone a v2.0 MCP pivot where many harness modules were stubbed out — they now return empty data or stub responses, making removal safe. No live data migration is required because all harness state (tasks, agents, projects, chat sessions) is either in-memory or already dead-code.

The main execution risk is test suite breakage. Fourteen test files directly test harness features. Nine should be deleted entirely; five need targeted edits to remove harness-specific test classes while keeping tests for shared infrastructure. The `standalone_guard` decorator and `standalone` parameter of `create_app()` can also be removed once all guarded routes are gone.

The frontend (`app.js`) is a hand-written 8,924-line SPA with no build system, so edits are surgical. The `state` object contains approximately 40 harness-related fields. The sidebar nav at L8786-8796, the page renderers map at L8829-8843, and load functions scattered through L694-1000 all require cleanup.

**Primary recommendation:** Bottom-to-top deletion in server.py, then frontend cleanup, then auth simplification, then test cleanup — one route group at a time, running `python -m pytest tests/ -x -q --tb=short` after each group.

---

## Architecture Patterns

### Recommended Deletion Order (server.py, bottom-to-top)

Follow D-33. Working bottom-to-top avoids line number drift after each delete.

```
1. GitHub + Repos        (L5914-6193)   ~280 lines
2. Projects              (L5727-5890)   ~163 lines  [inside `if project_manager:` block]
3. Devices               (L5067-5139)   ~73 lines
4. Approvals             (L5049-5066)   ~17 lines
5. Rewards               (L4944-5048)   ~105 lines
6. Agents                (L4732-4943)   ~212 lines
7. Chat + IDE Chat       (L3282-4112)   ~830 lines
8. CC Sessions           (L3082-3119)   ~37 lines
9. CC Chat WebSocket     (L2065-3082)   ~1017 lines
10. Terminal WebSocket   (L1776-2064)   ~289 lines
11. GSD Workstreams      (L1612-1708)   ~96 lines
12. IDE routes           (L1429-1710)   ~281 lines  [overlap with GSD — adjust]
13. Workspaces           (L1376-1428)   ~52 lines
14. Activity Feed        (L1075-1095)   ~20 lines   [_activity_feed, _record_activity]
15. Profiles+Routing+Persona (L858-1073) ~215 lines
16. Status               (L608-642)     ~34 lines
```

After route removal:
- Remove orphaned Pydantic model classes (TaskCreateRequest, InterventionRequest, etc.) from L187-290
- Remove orphaned enum stubs (TaskStatus, TaskType, infer_task_type) from L60-97
- Remove top-level imports: `from core.approval_gate import ApprovalGate`, `from core.device_auth import DeviceStore`, `from dashboard.auth import API_KEY_PREFIX`
- Clean `create_app()` signature: remove `approval_gate`, `device_store`, `channel_manager`, `repo_manager`, `project_manager`, `profile_loader`, `github_account_store`, `agent_manager`, `reward_system`, `workspace_registry`, `standalone` parameters
- Remove `standalone_guard` decorator definition and all its `@standalone_guard` usages (lines identified via grep)
- Remove `ws_manager.record_activity = _record_activity` at L6453
- Remove `_DASHBOARD_EDITABLE_SETTINGS` entries that only serve removed features: `PROJECT_MEMORY_ENABLED`, `AGENT_DEFAULT_PROFILE`, `RLM_*` entries

### WebSocket /ws Endpoint Simplification

The /ws endpoint (L5663) currently handles both JWT and device API key auth. After device gateway removal, simplify to JWT-only:

```python
# Remove the API_KEY_PREFIX branch entirely:
# if token.startswith(API_KEY_PREFIX):  <-- delete this block
#     if not device_store: ...
#     device = device_store.validate_api_key(token)
#     ...

# Keep only JWT validation:
try:
    payload = jose_jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    ...
    user = payload["sub"]
```

Also remove `device_id` and `device_name` variables and the `ws_manager.connect()` call can be simplified to `ws_manager.connect(ws, user=user)`.

### auth.py Simplification (D-31, D-32)

Remove from `auth.py`:
- `from core.device_auth import API_KEY_PREFIX, DeviceStore` import
- `_device_store: DeviceStore | None = None` global
- `init_device_store()` function
- `_validate_api_key()` function
- The `if token.startswith(API_KEY_PREFIX):` branch in `get_auth_context()`
- The same API key branch in `get_current_user_optional()`
- The API key check in `require_admin()`

`AuthContext` dataclass retains `user` and `auth_type` fields but `device_id` and `device_name` fields can be removed.

Export cleanup: `API_KEY_PREFIX` and `init_device_store` are imported by `server.py` and `agent42.py` — both need updating after auth.py change.

### Frontend app.js Deletion Map

**State object (L7-120):** Remove harness fields:
```
approvals, selectedTask, viewMode, activityFeed, activityOpen, filterPriority,
filterType, status, profiles, defaultProfile, selectedProfile, agentsViewMode,
personaCustom, personaDefault, routingModels, routingConfig, routingEdits,
routingSaving, agentRoutingEdits, agentRoutingSaving, selectedProfileRouting,
chatMessages, chatInput, chatSending, canvasOpen, canvasContent, canvasTitle,
canvasLang, chatSessions, currentSessionId, currentSessionMessages,
codeSessions, codeCurrentSessionId, codeCurrentMessages, codeSetupStep,
codeSending, codeCanvasOpen, panelTab, projects, selectedProject,
missionControlTab, projectViewMode, githubConnected, githubDeviceCode,
githubPolling, githubAccounts, githubAccountsLoading, githubAccountAdding,
repos, repoBranches, githubRepos, githubLoading, teamRuns, selectedTeamRun,
agents, rewardsStatus, standaloneMode
```

**Load functions to delete (L694-1000 range):**
- `loadTasks()` — already stub
- `loadRewardsStatus()`, `toggleRewardsSystem()`
- `loadRepos()`, `loadGithubAccounts()`, `loadRepoBranches()`
- `loadApprovals()`
- `loadStatus()`
- `loadApps()` calls `/api/apps` — KEEP (Agent Apps stays)
- `loadProfiles()`, `loadPersona()`
- `loadChannels()`

**Render functions to delete** (verified line numbers):
| Function | Start Line | Approx Size |
|----------|-----------|-------------|
| renderStats | 1821 | ~20 lines |
| renderTasks | 1842 | ~40 lines |
| renderKanbanBoard | 1881 | ~62 lines |
| renderListView | 1944 | ~42 lines |
| renderActivitySidebar | 1987 | ~25 lines |
| renderApprovals | 2144 | ~33 lines |
| renderAgents | 2383 | ~400 lines |
| renderTeams | 2785 | ~47 lines |
| renderTeamRunDetail | 2832 | ~178 lines |
| renderStatus | 3044 | ~158 lines |
| renderMarkdown | 3203 | ~63 lines |
| renderCanvasPanel | 3267 | ~142 lines |
| renderChat | 3410 | ~145 lines |
| renderMissionControl | 3556 | ~17 lines |
| renderProjectsBoard | 3573 | ~45 lines |
| renderProjectDetail | 3619 | ~565 lines |
| renderCode | 4185 | ~3259 lines |
| renderReposPanel | 7445 | ~239 lines |
| renderChainSummary | 8591 | ~106 lines |
| renderRoutingPanel | 8698 | ~47 lines |

**CAUTION — renderMarkdown:** Despite the name, `renderMarkdown` at L3203 is used by harness render functions. After those are deleted there are no callers. Verify before deleting that no kept functions (renderApps, renderTools, renderSkills, renderReports, renderSettings) call it.

**Sidebar (L8786-8796):** Replace with kept-pages-only links:
- Keep: apps (Sandboxed Apps), tools, skills, reports, settings
- Remove: tasks (Mission Control), status, approvals, workspace, agents, teams
- Note: sidebar still references `approvalBadge` at L8778 — this line must also go

**Renderers map (L8829-8843):** Remove: tasks, status, approvals, workspace, agents, teams, detail, projectDetail

**WebSocket message handlers (L580-640 area):** Remove handlers for `project_updated`, `chat_message`, `chat_message_update`, and the harness-specific task/agent events.

**Settings panel tabs (L7934):** Remove `repos`, `channels`, `rewards` tabs from the tabs array. Remove `!state.standaloneMode` conditionals (standaloneMode state field is also removed).

### agent42.py Cleanup

After server.py and auth.py changes, `agent42.py` needs corresponding updates:
- Remove `from core.device_auth import DeviceStore`
- Remove `from core.project_manager import ProjectManager`
- Remove `from core.repo_manager import RepositoryManager`
- Remove `from core.workspace_registry import WorkspaceRegistry`
- Remove `from dashboard.auth import init_device_store`
- Remove `self.device_store`, `init_device_store()` call in `__init__`
- Remove `self.repo_manager`, `self.project_manager`, `self.workspace_registry` in `__init__`
- Remove `await self.repo_manager.load()`, `await self.project_manager.load()`, `await self.workspace_registry.*` in `start()`
- Remove `github_account_store` creation (L295-298)
- Remove removed parameters from `create_app()` call (L299-316)
- Keep `self.agent_manager` — it is used by sidecar.py and tiered_routing_bridge.py
- Keep `self.reward_system` — it is used by sidecar.py and tiered_routing_bridge.py
- Keep `self.tier_recalc` — it depends on reward_system (REWARDS_ENABLED gate)

### Anti-Patterns to Avoid

- **Removing modules referenced outside dashboard:** `core/approval_gate.py` is used by `tools/ssh_tool.py` and `tools/tunnel_tool.py` — do NOT delete it. `core/reward_system.py` is used by `sidecar.py` and `tiered_routing_bridge.py` — do NOT delete it. `core/agent_manager.py` is used by `sidecar.py` and `tiered_routing_bridge.py` — do NOT delete it.
- **Top-down deletion in server.py:** Causes line number drift. Always work bottom-to-top.
- **Deleting DeviceStore core module:** `core/device_auth.py` remains; only the dashboard auth integration goes away.
- **Forgetting agent42.py:** The launcher passes harness parameters to `create_app()` — both files must be updated together or the app won't start.
- **renderMarkdown dependency:** Check kept render functions for `renderMarkdown` calls before deleting it.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Verifying no dangling references after deletion | Custom grep scripts | `python -m pytest tests/ -x -q` + ruff lint | Test suite catches import errors; ruff catches unused imports |
| Safely removing Python imports | Manual tracking | ruff `F401` (unused import) rule | Ruff will flag remaining unused imports after route removal |
| Line range identification before deletion | Memory | `grep -n "@app\."` + `wc -l` verification | Line numbers shift; always re-verify before each cut |

---

## Common Pitfalls

### Pitfall 1: Orphaned Pydantic Models
**What goes wrong:** Pydantic model classes (TaskCreateRequest, DeviceRegisterRequest, etc.) are defined near the top of `create_app()` before the routes that use them. Deleting routes leaves dangling model definitions that ruff flags as dead code and confuse future readers.
**Why it happens:** Route handlers and their request models are in different line ranges.
**How to avoid:** After each route group deletion, grep for model class names in remaining code. If no route references them, delete the class.
**Warning signs:** `F841` (local variable assigned but never used) in ruff output.

### Pitfall 2: Inline Import Cleanup
**What goes wrong:** Several harness routes use inline `from core.X import Y` patterns inside their route handler bodies. These imports are only reached at runtime, so they don't appear in top-level import analysis.
**Why it happens:** Graceful degradation pattern — imports are deferred to avoid startup failures.
**How to avoid:** When deleting a route handler, scan the entire function body for inline imports. Confirmed harness inline imports: `from core.agent_manager import` (L3552, L3866, L4734), `from core.agent_runtime import` (L4735), `from core.rewards_config import` (L4958, L4983), `from core.github_oauth import` (L5940, L5959, L5994), `from core.task_context import` (L4271), `from core.task_types import` (L4272).
**Warning signs:** ImportError at test time for a module you thought was removed.

### Pitfall 3: Test Files That Must Be Deleted vs Modified
**What goes wrong:** Leaving test files for deleted routes causes 404 assertion failures and import errors that fail the suite after removal.
**Why it happens:** Tests are tightly coupled to route existence.
**How to avoid:** Delete these test files entirely (they test only removed features):
- `tests/test_cc_bridge.py`
- `tests/test_cc_chat_ui.py`
- `tests/test_cc_layout.py`
- `tests/test_cc_pty.py`
- `tests/test_cc_tool_use.py`
- `tests/test_ide_html.py`
- `tests/test_ide_workspace.py`
- `tests/test_rewards_api.py`
- `tests/test_websocket_terminal.py`
- `tests/test_workspace_registry.py` — tests WorkspaceRegistry core module AND /api/workspaces endpoints; endpoint tests must go but core tests may stay if WorkspaceRegistry module is kept

Modify (remove harness test classes, keep others):
- `tests/test_device_auth.py` — TestDeviceRegistration, TestDeviceValidation, TestDeviceRevocation test `core/device_auth.py` (kept module). The `TestDeviceAPIKeyAuth` class and `TestDashboardAPIKeyEndpoints` class test the auth.py device path and /api/devices routes — delete those classes.
- `tests/test_standalone_mode.py` — all tests become invalid after standalone_guard is removed. Delete entire file or replace with a smoke test for the new stripped app.
- `tests/test_provider_ui.py` — `TestAgentsModels` class tests `/api/agents/models` (removed). Other tests (`TestProviderStatus`) test `/api/settings/provider-status` (kept). Delete `TestAgentsModels` class only.
- `tests/test_unified_agents.py` — tests /api/agents routes being removed. Delete entire file.
- `tests/test_github_accounts.py` — tests GitHub accounts core module and /api/github routes. Delete tests for /api/github routes; the core module itself may stay.
- `tests/test_github_oauth.py` — tests GitHub OAuth flow. If GitHubAccountStore module is kept (no decision to delete it), leave the test. If not, delete.

**Warning signs:** `ImportError: cannot import name 'X' from 'dashboard.server'` in test output.

### Pitfall 4: WebSocket Manager device_id Fields
**What goes wrong:** `WebSocketManager.WSConnection` dataclass has `device_id` and `device_name` fields, and `connected_device_ids()` method. These become dead code after Device Gateway removal.
**Why it happens:** WebSocket manager was built to support device identity.
**How to avoid:** After auth.py simplification, audit `websocket_manager.py` — `connected_device_ids()` is called from `server.py` Devices route (L5096, L5119), which is being deleted. The fields themselves are harmless but cleanup is part of CLEAN-01. Simplify `WSConnection` to drop `device_id` and `device_name`; remove `connected_device_ids()` method.

### Pitfall 5: _DASHBOARD_EDITABLE_SETTINGS Stale Entries
**What goes wrong:** Settings that only apply to removed features remain in the editable settings allowlist, allowing users to set them from the dashboard even though nothing reads them.
**Why it happens:** The allowlist was not pruned with each feature removal.
**How to avoid:** Remove from `_DASHBOARD_EDITABLE_SETTINGS`: `PROJECT_MEMORY_ENABLED`, `AGENT_DEFAULT_PROFILE`, `RLM_ENABLED`, `RLM_THRESHOLD_TOKENS`, `RLM_ENVIRONMENT`, `RLM_MAX_DEPTH`, `RLM_MAX_ITERATIONS`, `RLM_VERBOSE`, `RLM_COST_LIMIT`, `RLM_TIMEOUT_SECONDS`, `RLM_LOG_DIR`, `DEFAULT_REPO_PATH`, `TASKS_JSON_PATH`.
**Warning signs:** Settings page shows knobs for non-existent features.

### Pitfall 6: approvalBadge Reference Before Sidebar
**What goes wrong:** Line 8778 constructs `approvalBadge` using `state.approvals.length`. After sidebar cleanup that removes the approvals link, this line still executes and references the deleted state field.
**Why it happens:** Sidebar template is all one string; badge computation precedes the template.
**How to avoid:** Delete L8778 (`const approvalBadge = ...`) together with the sidebar approvals link.

---

## Runtime State Inventory

This is a deletion phase with no rename. No runtime state migration is required.

| Category | Items Found | Action Required |
|----------|-------------|-----------------|
| Stored data | None — tasks, agents, projects, chat sessions are in-memory stubs or already dead code since v2.0 pivot | None |
| Live service config | None — no external services depend on harness routes | None |
| OS-registered state | None | None |
| Secrets/env vars | `REWARDS_ENABLED` env var gates reward system in agent42.py — reward_system itself is kept (sidecar uses it), so env var stays | None |
| Build artifacts | None — app.js is hand-written, no build artifacts | None |

---

## Code Examples

### Correct Pattern: Verifying a Route Group is Gone

After each server.py deletion pass, run a quick sanity check:

```bash
# Verify route is gone
grep -n "api/agents" /c/Users/rickw/projects/agent42/dashboard/server.py
# Should return empty after Agents deletion

# Run tests immediately
python -m pytest tests/ -x -q --tb=short
```

### Correct Pattern: Removing a Sidebar Entry (app.js)

Before (L8786-8796):
```javascript
<a href="#" data-page="tasks" ...>&#127919; Mission Control</a>
<a href="#" data-page="status" ...>&#128200; Status</a>
<a href="#" data-page="approvals" ...>&#128274; Approvals ${approvalBadge}</a>
${state.standaloneMode ? "" : '<a href="#" data-page="workspace" ...>&#128187; Workspaces</a>'}
${state.standaloneMode ? "" : '<a href="#" data-page="apps" ...>&#128640; Sandboxed Apps</a>'}
<a href="#" data-page="agents" ...>&#129302; Agents</a>
<a href="#" data-page="teams" ...>&#129309; Teams</a>
<a href="#" data-page="tools" ...>&#128295; Tools</a>
<a href="#" data-page="skills" ...>&#9889; Skills</a>
<a href="#" data-page="reports" ...>&#128202; Reports</a>
<a href="#" data-page="settings" ...>&#9881; Settings</a>
```

After:
```javascript
<a href="#" data-page="apps" ...>&#128640; Sandboxed Apps</a>
<a href="#" data-page="tools" ...>&#128295; Tools</a>
<a href="#" data-page="skills" ...>&#9889; Skills</a>
<a href="#" data-page="reports" ...>&#128202; Reports</a>
<a href="#" data-page="settings" ...>&#9881; Settings</a>
```

Also update `state.page` default from `"tasks"` (L11) to `"apps"` — the new landing page.

### Correct Pattern: Renderers Map (app.js L8829-8843)

Before:
```javascript
const renderers = {
  tasks: renderMissionControl,
  status: renderStatus,
  approvals: renderApprovals,
  workspace: renderCode,
  tools: renderTools,
  skills: renderSkills,
  agents: renderAgents,
  teams: renderTeams,
  apps: renderApps,
  reports: renderReports,
  settings: renderSettings,
  detail: renderDetail,
  projectDetail: renderProjectDetail,
};
```

After:
```javascript
const renderers = {
  apps: renderApps,
  tools: renderTools,
  skills: renderSkills,
  reports: renderReports,
  settings: renderSettings,
};
```

### Correct Pattern: auth.py get_auth_context After Simplification

Before:
```python
def get_auth_context(credentials = Depends(security)) -> AuthContext:
    token = credentials.credentials
    if token.startswith(API_KEY_PREFIX):
        return _validate_api_key(token)
    return _validate_jwt(token)
```

After:
```python
def get_auth_context(credentials = Depends(security)) -> AuthContext:
    return _validate_jwt(credentials.credentials)
```

---

## Environment Availability

Step 2.6: Phase is code/config-only changes (no new external dependencies). The existing stack (Python 3.11, pytest, ruff, FastAPI) is already operational. No new installs required.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest (existing, configured via pyproject.toml) |
| Config file | pyproject.toml `[tool.pytest.ini_options]` |
| Quick run command | `python -m pytest tests/ -x -q --tb=short` |
| Full suite command | `python -m pytest tests/ -v` |
| Lint command | `make lint` (ruff) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | Status |
|--------|----------|-----------|-------------------|--------|
| STRIP-01 | No /api/tasks, /api/projects routes | negative (route gone) | `python -m pytest tests/test_auth_flow.py -x -q` (smoke: app starts) | Existing tests deleted |
| STRIP-02 | No /api/ide/*, /ws/terminal routes | negative | `grep -c "api/ide" dashboard/server.py` should be 0 | Manual verification |
| STRIP-03 | No /api/agents/* routes | negative | `grep -c "api/agents" dashboard/server.py` should be 0 | Manual verification |
| STRIP-04 | No renderTeams in app.js | negative | `grep -c "renderTeams" dashboard/frontend/dist/app.js` should be 0 | Manual verification |
| STRIP-05 | No /api/approvals route | negative | `grep -c "api/approvals" dashboard/server.py` should be 0 | Manual verification |
| STRIP-06 | No /api/github/*, /api/repos/* routes | negative | `grep -c "api/github" dashboard/server.py` should be 0 | Manual verification |
| STRIP-07 | No /api/chat/*, /ws/cc-chat | negative | `grep -c "cc-chat" dashboard/server.py` should be 0 | Manual verification |
| STRIP-08 | Device auth removed from auth.py | unit | `python -m pytest tests/test_device_auth.py::TestDeviceRegistration -x -q` (core DeviceStore kept) | Existing (partial) |
| STRIP-09 | No /api/gsd/* routes | negative | `grep -c "api/gsd" dashboard/server.py` should be 0 | Manual verification |
| STRIP-10 | No /api/status route | negative | `grep -c "api/status" dashboard/server.py` (health detail stays, status stub gone) | Manual verification |
| STRIP-11 | No /api/profiles/*, /api/agent-routing/* | negative | `grep -c "api/profiles" dashboard/server.py` should be 0 | Manual verification |
| STRIP-12 | No /api/persona | negative | `grep -c "api/persona" dashboard/server.py` should be 0 | Manual verification |
| CLEAN-01 | No dead routes in server.py | integration | `python -m pytest tests/test_auth_flow.py tests/test_llm_proxy.py tests/test_effectiveness.py -x -q` | Existing |
| CLEAN-02 | No dead render functions in app.js | source inspection | `grep -c "renderMissionControl\|renderChat\|renderAgents" dashboard/frontend/dist/app.js` should be 0 | Manual verification |
| CLEAN-03 | No unused imports | static analysis | `make lint` (ruff F401) | Existing |
| CLEAN-04 | Full test suite passes | integration | `python -m pytest tests/ -x -q --tb=short` | Existing — 2,274 tests baseline |

### Sampling Rate

- **Per route group deletion:** `python -m pytest tests/ -x -q --tb=short`
- **Per wave merge:** `python -m pytest tests/ -v` + `make lint`
- **Phase gate:** Full suite green + ruff clean before /gsd:verify-work

### Wave 0 Gaps

None — existing test infrastructure covers all phase requirements. No new test files needed. This phase deletes tests, not adds them.

---

## Open Questions

1. **renderMarkdown callers**
   - What we know: `renderMarkdown` is defined at L3203, 63 lines. It is called from harness render functions.
   - What's unclear: Whether any kept render functions (renderApps, renderReports, renderSettings) also call it.
   - Recommendation: `grep -n "renderMarkdown" dashboard/frontend/dist/app.js` before deleting it. If any kept function calls it, move the function body inline or keep it.

2. **test_github_accounts.py and test_github_oauth.py disposition**
   - What we know: These test `core/github_accounts.py` and `core/github_oauth.py` — modules used only by the GitHub routes being deleted.
   - What's unclear: Whether these core modules are referenced anywhere outside dashboard server.py (current grep found only server.py references).
   - Recommendation: If `core/github_accounts.py` and `core/github_oauth.py` have no other callers, delete the modules and their tests. Verify with `grep -rn "from core.github" --include="*.py"` excluding tests and server.py.

3. **test_cc_memory_sync.py partial dependency**
   - What we know: Most of test_cc_memory_sync.py tests Claude Code hooks (not harness routes). One class `TestDashboardCcSync` reimplements `_load_cc_sync_status` from server.py.
   - What's unclear: Whether `_load_cc_sync_status` is in the cc-chat removal range or in a kept section.
   - Recommendation: Verify `_load_cc_sync_status` location in server.py before deleting. If it's in the CC Chat block (L2065-3082), the test class goes. If it's in a kept block, preserve it.

4. **Settings panel tabs: channels**
   - What we know: The Settings page currently shows a "Channels" tab (gated `!state.standaloneMode`). The channels feature (`/api/channels`) is not in the explicit REMOVE list.
   - What's unclear: Whether Channels is a harness feature or intelligence layer feature.
   - Recommendation: `/api/channels` is referenced only in `loadChannels()` in app.js and not in the CONTEXT.md remove list. Treat as KEEP unless planner explicitly defers it. The `!state.standaloneMode` gate on the Channels tab is simply removed along with `standaloneMode` field.

---

## Project Constraints (from CLAUDE.md)

The following directives from `CLAUDE.md` apply to this phase:

- All I/O is async — use `aiofiles`, `httpx`, `asyncio`. Never blocking I/O in tools. (Not applicable to this phase — no new I/O code being added.)
- Frozen config — `Settings` dataclass in `core/config.py`. Do not add fields there for this phase. Removing `_DASHBOARD_EDITABLE_SETTINGS` entries is safe.
- Graceful degradation — Redis, Qdrant, MCP are optional. Preserved in kept routes.
- Sandbox always on — `sandbox.resolve_path()`. Not affected by this phase.
- New pitfalls — add to `.claude/reference/pitfalls-archive.md` when discovered.
- Test requirement — `python -m pytest tests/ -x -q` must pass. New modules need `tests/test_*.py` — this phase deletes tests, not adds them.
- GSD Workflow — use `/gsd:execute-phase` for this work.

---

## Sources

### Primary (HIGH confidence)

- Direct code inspection: `dashboard/server.py` (6,455 lines, verified) — route groups, line ranges, imports, model classes
- Direct code inspection: `dashboard/auth.py` (218 lines, verified) — device auth flow, JWT flow
- Direct code inspection: `dashboard/frontend/dist/app.js` (8,924 lines, verified) — render functions, state object, sidebar, renderers map
- Direct code inspection: `dashboard/websocket_manager.py` (101 lines, verified) — WSConnection fields, methods
- Direct code inspection: `agent42.py` (verified) — create_app() call site, imports, harness initialization
- Direct code inspection: `tests/` directory (2,274 tests, 96 test files) — affected test files identified

### Secondary (MEDIUM confidence)

- `.planning/workstreams/frood-dashboard/phases/50-strip-harness-features/50-CONTEXT.md` — all locked decisions, line ranges pre-verified by discussion phase

---

## Metadata

**Confidence breakdown:**
- What to remove: HIGH — decisions are locked in CONTEXT.md, verified against actual code
- Line ranges: HIGH — verified by direct grep and wc; planner should re-verify before cutting (files may have been edited)
- What to keep: HIGH — confirmed by checking all cross-module dependencies
- Test disposition: HIGH — confirmed by reading each test file
- Orphaned module identification: HIGH — verified by grep across full codebase

**Research date:** 2026-04-07
**Valid until:** 2026-05-07 (stable codebase — only changes if harness routes are modified before phase executes)
