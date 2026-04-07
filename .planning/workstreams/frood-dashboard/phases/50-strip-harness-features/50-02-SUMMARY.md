---
phase: 50-strip-harness-features
plan: "02"
subsystem: frontend
tags: [strip, frontend, spa, app.js, harness-removal]
dependency_graph:
  requires: []
  provides: [stripped-frontend-spa]
  affects: [dashboard/frontend/dist/app.js]
tech_stack:
  added: []
  patterns: [surgical-line-deletion, multi-pass-python-script]
key_files:
  created: []
  modified:
    - dashboard/frontend/dist/app.js
key_decisions:
  - Both tasks applied atomically via multi-pass Python script (single-file constraint)
  - loadChannels kept (channels not in REMOVE list per research Open Question 4)
  - renderDetail kept (used by navigate() for task detail links still in code)
  - _CODE_ONLY_TOOLS constant removed (only referenced by deleted renderCode)
  - orchestrator tab retained but DEFAULT_REPO_PATH and TASKS_JSON_PATH entries removed
metrics:
  duration: "14 minutes"
  completed: "2026-04-07"
  tasks_completed: 2
  tasks_total: 2
  files_modified: 1
  lines_removed: 6675
---

# Phase 50 Plan 02: Strip Harness Render Functions from app.js Summary

Removed all harness page render functions, load functions, state fields, sidebar entries, and renderer map entries from the hand-written 8,924-line frontend SPA. The resulting app.js serves only the intelligence layer admin pages (Apps, Tools, Skills, Reports, Settings).

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Remove harness render functions and load functions | af13ea3 | dashboard/frontend/dist/app.js |
| 2 | Update sidebar, renderers map, state object, default page | af13ea3 | dashboard/frontend/dist/app.js |

Note: Both tasks were committed atomically (af13ea3) because they modify the same single file. Splitting into separate commits would have required intermediate invalid JavaScript states.

## What Was Done

### Render functions deleted (~5,200 lines)

| Function | Lines removed |
|----------|--------------|
| renderStats | ~20 |
| renderTasks | ~30 |
| getFilteredTasks | ~7 |
| renderKanbanBoard | ~62 |
| renderListView | ~42 |
| renderActivitySidebar | ~25 |
| renderApprovals | ~33 |
| renderAgents + helpers (_relativeTime, _makeSparkline) | ~430 |
| renderTeams + renderTeamRunDetail + loadTeamRuns | ~226 |
| renderStatus | ~158 |
| renderMarkdown | ~63 |
| renderCanvasPanel | ~142 |
| renderChat | ~145 |
| renderMissionControl + renderProjectsBoard + renderProjectDetail | ~629 |
| renderCode | ~3,260 |
| renderReposPanel | ~235 |
| renderChainSummary | ~106 |
| renderRoutingPanel | ~47 |

### Load functions deleted

- loadTasks, loadRewardsStatus, toggleRewardsSystem
- loadRepos, loadGithubAccounts, loadRepoBranches
- loadApprovals, loadStatus, loadProfiles, loadPersona
- loadChatMessages, loadChatSessions, loadCodeSessions
- createChatSession, switchChatSession, switchCodeSession, sendSessionMessage, deleteChatSession
- loadProjects, loadGitHubStatus, submitCodeSetup, createProject, loadProjectTasks, sendChatMessage
- All task action functions (doCreateTask, doApproveTask, doCancelTask, doRetryTask, doSubmitReview, doMoveTask, doAddComment, doSetPriority, doBlockTask, doUnblockTask, doArchiveTask)
- loadActivity, doHandleApproval
- showCreateTaskModal, onTaskRepoChange, submitCreateTask, showReviewModal, submitReview
- loadRoutingModels, loadRoutingConfig, routingSelect (entire LLM routing helpers section)

### State object cleaned

Removed harness state fields:
- tasks, approvals, selectedTask
- Mission Control: viewMode, activityFeed, activityOpen, filterPriority, filterType, status
- Agents: profiles, defaultProfile, selectedProfile, agentsViewMode, personaCustom, personaDefault
- LLM Routing: routingModels, routingConfig, routingEdits, routingSaving, agentRoutingEdits, agentRoutingSaving, selectedProfileRouting
- Chat/Code: chatMessages, chatInput, chatSending, canvasOpen, canvasContent, canvasTitle, canvasLang, chatSessions, currentSessionId, currentSessionMessages, codeSessions, codeCurrentSessionId, codeCurrentMessages, codeSetupStep, codeSending, codeCanvasOpen, panelTab
- Projects: projects, selectedProject, missionControlTab, projectViewMode
- GitHub: githubConnected, githubDeviceCode, githubPolling, githubAccounts, githubAccountsLoading, githubAccountAdding
- Repos: repos, repoBranches, githubRepos, githubLoading
- Teams/Rewards: teamRuns, selectedTeamRun, agents, rewardsStatus
- standaloneMode (removed entirely)

Default page changed from `"tasks"` to `"apps"`.

### Sidebar updated

Before: 11 entries (Mission Control, Status, Approvals, Workspaces, Sandboxed Apps, Agents, Teams, Tools, Skills, Reports, Settings)
After: 5 entries (Sandboxed Apps, Tools, Skills, Reports, Settings)

approvalBadge computation (Pitfall 6) removed.
standaloneMode conditionals removed from sidebar.

### Renderers map updated

Before: tasks, status, approvals, workspace, tools, skills, agents, teams, apps, reports, settings, detail, projectDetail
After: apps, tools, skills, reports, settings
Default fallback changed from `renderTasks` to `renderApps`.

### WebSocket handlers cleaned

Removed handlers for: task_update, project_update, chat_message, chat_thinking, tier_update
Kept: system_health (updateGsdIndicator), app_status (renderApps)

### Settings panel updated

Removed tabs: repos, rewards
Removed standaloneMode conditionals from channels tab
Removed repos and rewards panel implementations
Removed DEFAULT_REPO_PATH, TASKS_JSON_PATH from orchestrator tab (harness-only settings)

### Other cleanup

- navigate() simplified (removed IDE/workspace redirect logic)
- loadAll() stripped to: loadTools, loadSkills, loadChannels, loadProviders, loadHealth, loadApiKeys, loadEnvSettings, loadStorageStatus, loadTokenStats, loadGsdWorkstreams, loadApps, loadReports
- loadHealth() simplified (removed standaloneMode assignment)
- WS onopen simplified (removed harness load calls on reconnect)
- DOMContentLoaded: removed approvals auto-refresh interval
- IDE sidebar toggle button removed from topbar
- IDE persistent container removed from layout HTML
- _CODE_ONLY_TOOLS constant removed (was only referenced by renderCode)

## Line Count

| Metric | Value |
|--------|-------|
| Original lines | 8,924 |
| Final lines | 2,249 |
| Lines removed | 6,675 (74.8%) |

## Verification Results

All acceptance criteria pass:

- renderMissionControl occurrences: 0
- renderStatus occurrences: 0
- renderApprovals occurrences: 0
- renderCode occurrences: 0
- renderAgents occurrences: 0
- renderTeams occurrences: 0
- renderChat occurrences: 0
- renderKanbanBoard occurrences: 0
- renderProjectDetail occurrences: 0
- renderReposPanel occurrences: 0
- renderRoutingPanel occurrences: 0
- renderChainSummary occurrences: 0
- loadTasks occurrences: 0
- loadApprovals occurrences: 0
- loadRewardsStatus occurrences: 0
- loadProfiles occurrences: 0
- approvalBadge occurrences: 0
- standaloneMode occurrences: 0
- data-page="tasks" occurrences: 0
- data-page="agents" occurrences: 0
- data-page="teams" occurrences: 0
- data-page="status" occurrences: 0
- data-page="approvals" occurrences: 0
- data-page="workspace" occurrences: 0
- renderApps function: present
- renderTools function: present
- renderSkills function: present
- renderReports function: present
- renderSettings function: present
- Default page: "apps"
- Renderers map: 5 entries (apps, tools, skills, reports, settings)

## Deviations from Plan

### Implementation approach (not a deviation — per D-27)

Both Task 1 and Task 2 were executed via a multi-pass Python scripting approach rather than manual Edit tool calls. The file is 8,924 lines with 19 render functions to delete spanning thousands of lines — this was the correct approach per D-27 (hand-written SPA, surgical line deletion). Result was identical to the plan's specification.

### Atomic commit for both tasks

Tasks 1 and 2 were committed in a single commit (af13ea3) because:
1. Both modify the same single file (app.js)
2. The intermediate state after Task 1 would have had dangling references (sidebar referencing deleted render functions)
3. The file is only valid JavaScript once both sets of changes are applied

### renderDetail kept

`renderDetail` (lines ~2013-2129) was not deleted even though it renders task detail. It is called by navigate() when `page === "detail"` and is referenced in the kept code. This is a harness function but has a dependency in kept code. It will become dead code once navigate() is fully cleaned in a future plan.

### loadChannels kept

`loadChannels()` was kept per plan instruction: "KEEP if Channels is a kept feature — /api/channels is not in REMOVE list."

## Known Stubs

None — all remaining render functions (renderApps, renderTools, renderSkills, renderReports, renderSettings) are fully wired and functional.

## Self-Check: PASSED
