---
phase: 50-strip-harness-features
plan: "01"
subsystem: dashboard/server.py
tags: [deletion, harness-removal, server, routes]
dependency_graph:
  requires: []
  provides: [stripped-server-routes]
  affects: [dashboard/server.py, tests/test_auth_flow.py, tests/test_llm_proxy.py]
tech_stack:
  added: []
  patterns: [bottom-to-top deletion, surgical Python script removal]
key_files:
  created: []
  modified:
    - dashboard/server.py
    - tests/test_auth_flow.py
    - tests/test_llm_proxy.py
decisions:
  - Removed _PERSONA_FILE, _load_persona, _save_persona since all persona consumers were removed
  - Removed _build_resolution_chain since all routing consumers were removed
  - Kept _build_reports() project_list block stub (empty list) rather than removing whole function
  - Fixed pre-existing F841 (max_tokens, temperature unused vars) in LLM proxy since ruff gate required 0 errors
  - Used Python script approach for bulk deletions to avoid line-number drift during editing
metrics:
  duration_minutes: 90
  completed: "2026-04-07"
  tasks_completed: 2
  tasks_total: 2
  files_modified: 3
---

# Phase 50 Plan 01: Strip Harness Routes from server.py — Summary

Removed 3,943 lines from dashboard/server.py — all 16 harness route groups plus orphaned infrastructure — leaving only the intelligence layer admin routes.

## What Was Done

### Task 1: Remove all harness route groups (bottom-to-top)

Deleted these route groups using a Python script (bottom-to-top to avoid line-number drift):

1. GitHub + Repos (`/api/github/*`, `/api/repos/*`) — D-06
2. Project Memory (`/api/projects/{id}/memory`) — D-14
3. Projects (`/api/projects/*`) — D-14
4. Devices (`/api/devices/*`) — D-08
5. Approvals (`/api/approvals`) — D-05
6. Rewards (`/api/rewards/*`) — D-13
7. Agents (`/api/agents/*`) — D-03
8. Chat Sessions + IDE Chat routes (`/api/chat/*`, `/api/ide/chat*`) — D-07
9. CC Sessions (`/api/cc/*`) — D-07
10. CC Chat WebSocket (`/ws/cc-chat`) — D-07
11. Terminal WebSocket (`/ws/terminal`) — D-02
12. GSD Workstreams + IDE Lint (`/api/gsd/*`, `/api/ide/lint`) — D-09, D-02
13. IDE routes (`/api/ide/*`) — D-02
14. Workspaces (`/api/workspaces/*`) — D-02
15. Activity Feed (`/api/activity`, `_record_activity`, `_activity_feed`) — D-35
16. Profiles + Routing + Persona (`/api/profiles/*`, `/api/agent-routing/*`, `/api/persona`) — D-11, D-12
17. Status (`/api/status`) — D-10
18. Remote Node Status (`/api/remote/status`) — D-02 (tied to IDE/terminal)
19. Channels (`/api/channels`) — channel_manager removed from create_app

**Post-deletion fix:** Added `import os as _os` before Memory Search section to replace the import that was in the removed IDE section (LLM proxy uses `_os`).

### Task 2: Clean orphaned models, imports, create_app params, standalone_guard

**Removed Pydantic models:** TaskCreateRequest, InterventionRequest, UserInputResponse, TaskMoveRequest, TaskCommentRequest, TaskAssignRequest, TaskPriorityRequest, TaskBlockRequest, ApprovalAction, ReviewFeedback, DeviceRegisterRequest, ProfileCreateRequest, ProfileUpdateRequest, PersonaUpdateRequest, AgentRoutingRequest

**Removed enum stubs:** TaskStatus, TaskType, infer_task_type(), GENERAL_ASSISTANT_PROMPT

**Removed top-level imports:** `from core.approval_gate import ApprovalGate`, `from core.device_auth import DeviceStore`, `API_KEY_PREFIX` from auth import

**Cleaned create_app() signature:** Removed approval_gate, device_store, channel_manager, repo_manager, project_manager, profile_loader, github_account_store, agent_manager, reward_system, workspace_registry, standalone parameters. Kept: ws_manager, tool_registry, skill_loader, heartbeat, key_store, app_manager, memory_store, effectiveness_store.

**Removed standalone_guard:** Decorator definition + 11 usages on kept App routes

**Removed helpers:** `_load_persona`, `_save_persona`, `_PERSONA_FILE`, `_build_resolution_chain`

**Cleaned _DASHBOARD_EDITABLE_SETTINGS:** Removed PROJECT_MEMORY_ENABLED, AGENT_DEFAULT_PROFILE, RLM_ENABLED/THRESHOLD_TOKENS/ENVIRONMENT/MAX_DEPTH/MAX_ITERATIONS/VERBOSE/COST_LIMIT/TIMEOUT_SECONDS/LOG_DIR, DEFAULT_REPO_PATH, TASKS_JSON_PATH

**Updated module docstring** to reflect intelligence layer admin panel identity.

## Verification Results

| Check | Result |
|-------|--------|
| All harness route patterns | 0 matches each |
| standalone_guard | 0 |
| ruff F401/F841 | All checks passed |
| Line reduction | 6439 → 2496 (3943 lines removed) |
| test_auth_flow (except status test) | PASS |
| test_llm_proxy | PASS (5/5) |
| test_effectiveness | PASS (28/28) |

**Known test failure:** `test_protected_endpoint_requires_auth` in test_auth_flow.py tests `/api/status` which was intentionally removed. Returns 404 instead of 401. This test will be removed in Plan 50-04.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Missing `import os as _os` after IDE section removal**
- **Found during:** Task 1 post-removal testing
- **Issue:** LLM proxy section uses `_os.environ.get()` but the `import os as _os` was inside the removed IDE section
- **Fix:** Added `import os as _os` before Memory Search section
- **Files modified:** dashboard/server.py
- **Commit:** 35f97f7

**2. [Rule 1 - Bug] Test fixtures passing removed create_app() parameters**
- **Found during:** Task 2 smoke test
- **Issue:** test_auth_flow.py and test_llm_proxy.py fixtures passed `device_store`, `channel_manager`, `project_manager`, etc. to create_app() after those params were removed
- **Fix:** Updated both test fixtures to only pass kept parameters
- **Files modified:** tests/test_auth_flow.py, tests/test_llm_proxy.py
- **Commit:** 69e4897

**3. [Rule 3 - Pre-existing] Fixed F841 unused variable warnings in LLM proxy**
- **Found during:** Task 2 ruff check
- **Issue:** `max_tokens` and `temperature` variables assigned but unused in two LLM proxy handlers. Pre-existed but blocked ruff gate requirement.
- **Fix:** Removed both unused variable assignments
- **Files modified:** dashboard/server.py
- **Commit:** 69e4897

### Implementation note
Used a Python script approach (reading all lines, defining keep-ranges, writing new file) rather than sequential Edit calls. This avoided the line-number drift problem that occurs when making many sequential deletions to a 6400-line file.

## Known Stubs

None — no stub data flowing to UI rendering was introduced by this plan. The `_build_reports()` function retains `project_list = []` (always empty now) but this is correct behavior since projects were removed.

## Commits

| Hash | Description |
|------|-------------|
| 35f97f7 | feat(50-01): remove all 16 harness route groups from server.py |
| 69e4897 | feat(50-01): clean orphaned models, imports, create_app params, standalone_guard |
