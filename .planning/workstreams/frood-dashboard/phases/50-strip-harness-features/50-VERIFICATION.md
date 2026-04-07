---
phase: 50-strip-harness-features
verified: 2026-04-07T19:47:52Z
status: gaps_found
score: 3/5 must-haves verified
re_verification: false
gaps:
  - truth: "No harness render functions or dead harness call sites remain in app.js"
    status: failed
    reason: "Three undefined function references remain in app.js that cause JavaScript runtime errors: loadGsdWorkstreams() called in loadAll() (crashes entire data load on startup), updateGsdIndicator() called 4 times (crashes on WebSocket message and post-login), _CODE_ONLY_TOOLS.has() called inside renderTools() (crashes Tools page render). renderDetail() (task detail function) is also present but unreachable from the renderers map — dead code containing 10+ more references to deleted functions."
    artifacts:
      - path: "dashboard/frontend/dist/app.js"
        issue: "loadGsdWorkstreams called at line 2142 in loadAll() Promise.all — function definition was deleted. ReferenceError on startup blocks all intelligence layer data loads."
      - path: "dashboard/frontend/dist/app.js"
        issue: "_CODE_ONLY_TOOLS referenced at line 1124 inside active renderTools() function — constant was deleted. ReferenceError thrown every time Tools page is rendered."
      - path: "dashboard/frontend/dist/app.js"
        issue: "updateGsdIndicator called at lines 160, 306, 474, 2237 — function definition was deleted. ReferenceError on login, setup completion, WebSocket system_health message, and DOMContentLoaded."
      - path: "dashboard/frontend/dist/app.js"
        issue: "renderDetail() (lines 981-1097) is dead harness code kept by mistake per 50-02 SUMMARY. Not reachable from renderers map but contains calls to doApproveTask, showReviewModal, doCancelTask, doRetryTask, viewTeamRun, doSetPriority, doBlockTask, doUnblockTask, doArchiveTask — all deleted."
    missing:
      - "Remove loadGsdWorkstreams() call from loadAll() Promise.all at line 2142"
      - "Remove all 4 updateGsdIndicator() call sites (lines 160, 306, 474, 2237) OR define a no-op stub"
      - "Remove _CODE_ONLY_TOOLS.has() usage from renderTools() at line 1124 (replace with static 'general' category or delete the category column)"
      - "Delete the renderDetail() function block (lines 981-1097) and all associated dead helpers: submitComment, promptBlock, STATUS_FLAVOR constant"

  - truth: "REQUIREMENTS.md reflects completion of STRIP and CLEAN requirements for phase 50"
    status: partial
    reason: "CLEAN-02 ('Remove dead frontend code for stripped pages/components') is unchecked in REQUIREMENTS.md despite plan 50-02 claiming and executing it. This is a tracking artifact gap — the requirement text was never checked off even though the bulk of the work was done."
    artifacts:
      - path: ".planning/workstreams/frood-dashboard/REQUIREMENTS.md"
        issue: "CLEAN-02 marked [ ] (not done) at line 39 but plan 50-02 claims CLEAN-02 in its requirements frontmatter and executed the frontend strip."
    missing:
      - "Update REQUIREMENTS.md to mark CLEAN-02 as [x] done (the frontend code was stripped by plan 50-02)"
human_verification:
  - test: "Load the dashboard in a browser after fixing the JS errors"
    expected: "All 5 pages (Apps, Tools, Skills, Reports, Settings) load without JavaScript console errors. No harness pages are accessible."
    why_human: "Cannot run a browser in the verification environment to confirm runtime JS behavior."
---

# Phase 50: Strip Harness Features — Verification Report

**Phase Goal:** Remove all harness features from the dashboard, leaving only intelligence layer admin/observability
**Verified:** 2026-04-07T19:47:52Z
**Status:** gaps_found
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | No Mission Control, Workspace, Agents, Teams, Approvals, Chat, or Status pages exist | VERIFIED | grep returns 0 for all harness route patterns in server.py; all harness data-page attributes gone from app.js sidebar |
| 2 | No GitHub integration, Device Gateway, GSD Workstreams, Agent Profiles, or Persona features exist | VERIFIED | grep returns 0 for api/github, api/devices, api/gsd, api/profiles, api/persona in server.py; auth.py is JWT-only with no DeviceStore; agent42.py has no WorkspaceRegistry/ProjectManager/RepositoryManager imports |
| 3 | All dead server.py routes for stripped features return 404 or are removed | VERIFIED | Combined grep for 19 harness route patterns returns 0; all 52 intelligence layer route matches confirmed present; ruff lint clean |
| 4 | All dead frontend code for stripped pages is removed | FAILED | loadGsdWorkstreams(), updateGsdIndicator(), and _CODE_ONLY_TOOLS are undefined but called in active app.js code paths. loadGsdWorkstreams() in loadAll() Promise.all crashes startup. _CODE_ONLY_TOOLS in renderTools() crashes the Tools page. renderDetail() dead harness function still present. |
| 5 | Full test suite passes after removal | VERIFIED | 2025 passed, 10 skipped, 0 failed (222s run) |

**Score:** 3/5 truths verified (one partial: REQUIREMENTS.md tracking gap)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `dashboard/server.py` | Stripped server with only intelligence layer routes | VERIFIED | 2,496 lines (down from 6,455). All 19 harness route patterns grep to 0. All 52+ intelligence layer patterns present. Ruff clean. |
| `dashboard/frontend/dist/app.js` | Stripped frontend SPA with only intelligence layer pages | PARTIAL | 2,249 lines (down from 8,924). All harness render functions deleted. Sidebar/renderers correct. BUT: 3 deleted functions still called in active code paths (loadGsdWorkstreams, updateGsdIndicator, _CODE_ONLY_TOOLS). renderDetail dead code still present. |
| `dashboard/auth.py` | JWT-only authentication | VERIFIED | 175 lines. DeviceStore, API_KEY_PREFIX, _validate_api_key, init_device_store all gone. get_auth_context and _validate_jwt present and wired. |
| `dashboard/websocket_manager.py` | Simplified WebSocket manager without device fields | VERIFIED | 64 lines. device_id, device_name, connected_device_ids all gone. WSConnection and connect() present. |
| `agent42.py` | Launcher without harness initialization | VERIFIED | 402 lines. WorkspaceRegistry, ProjectManager, RepositoryManager, init_device_store, github_account_store all gone. create_app import succeeds. agent_manager and reward_system kept (used by sidecar). |
| `tests/` | Clean test suite with no harness feature tests | VERIFIED | 14 harness test files deleted. TestDeviceAPIKeyAuth, TestDashboardAPIKeyEndpoints, TestAgentsModels classes removed. 2025/0 pass/fail. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `dashboard/frontend/dist/app.js` | `dashboard/server.py` | fetch to /api/apps, /api/tools, /api/skills, /api/reports, /api/settings | WIRED | Kept render and load functions call correct intelligence layer endpoints |
| `agent42.py` | `dashboard/server.py` | create_app() call | WIRED | Import verified: `python -c "import agent42"` succeeds. Harness params removed from call. |
| `dashboard/auth.py` | `dashboard/server.py` | Depends(get_auth_context) injection | WIRED | get_auth_context present in auth.py, referenced in server.py kept routes |
| `dashboard/frontend/dist/app.js` | `dashboard/server.py` | loadGsdWorkstreams -> /api/gsd/* | BROKEN | loadGsdWorkstreams() called in loadAll() but function definition deleted. Calling undefined function throws ReferenceError synchronously inside Promise.all, causing loadAll() to reject and blocking all data load on startup. |
| `dashboard/frontend/dist/app.js` | (internal) | renderTools -> _CODE_ONLY_TOOLS.has() | BROKEN | _CODE_ONLY_TOOLS constant deleted but referenced in renderTools() line 1124. Throws ReferenceError every time Tools page renders. |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `app.js renderApps` | state.apps | loadApps() -> /api/apps | Yes (server.py apps routes present) | FLOWING |
| `app.js renderTools` | state.tools | loadTools() -> /api/tools | Yes (but renderTools throws ReferenceError on _CODE_ONLY_TOOLS before rendering) | BROKEN |
| `app.js renderSkills` | state.skills | loadSkills() -> /api/skills | Yes | FLOWING |
| `app.js renderReports` | state.reports | loadReports() -> /api/reports | Yes | FLOWING |
| `app.js loadAll()` | all state | Promise.all([...loadGsdWorkstreams()...]) | No — ReferenceError on loadGsdWorkstreams causes entire loadAll to reject | BROKEN |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| agent42 module imports cleanly | `python -c "import agent42"` | "import OK" | PASS |
| create_app() callable without harness params | `python -c "from dashboard.server import create_app"` | "create_app signature OK" | PASS |
| Full test suite passes | `python -m pytest tests/ -q` | 2025 passed, 10 skipped, 0 failed | PASS |
| All harness server routes gone | grep combined pattern returns 0 | 0 | PASS |
| All kept server routes present | grep combined pattern returns >0 | 52 matches | PASS |
| Ruff lint clean across all modified files | `ruff check ... --select F401,F841` | All checks passed | PASS |
| Tools page renders without error | Browser visit to /tools | Cannot verify — loadAll crashes before Tools data loads (ReferenceError on loadGsdWorkstreams) | FAIL (code analysis) |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| STRIP-01 | 50-01, 50-02 | Remove Mission Control | SATISFIED | /api/agents, /api/approvals routes gone; renderMissionControl, renderKanbanBoard gone; data-page="tasks" gone |
| STRIP-02 | 50-01, 50-02 | Remove Workspace/IDE | SATISFIED | /api/ide, /api/workspaces, ws/terminal routes gone; renderCode gone |
| STRIP-03 | 50-01, 50-02 | Remove Agents page | SATISFIED | /api/agents route gone; renderAgents gone; data-page="agents" gone |
| STRIP-04 | 50-01, 50-02 | Remove Teams page | SATISFIED | renderTeams, renderTeamRunDetail gone; data-page="teams" gone |
| STRIP-05 | 50-01, 50-02 | Remove Approvals page | SATISFIED | /api/approvals route gone; renderApprovals gone; data-page="approvals" gone |
| STRIP-06 | 50-01, 50-02 | Remove GitHub Integration | SATISFIED | /api/github, /api/repos routes gone; renderReposPanel gone |
| STRIP-07 | 50-01, 50-02 | Remove Chat features | SATISFIED | /api/chat, /api/cc, ws/cc-chat gone; renderChat gone |
| STRIP-08 | 50-01, 50-03 | Remove Device Gateway | SATISFIED | /api/devices gone; auth.py JWT-only; DeviceStore removed from agent42.py and websocket_manager.py |
| STRIP-09 | 50-01, 50-02 | Remove GSD Workstreams UI | PARTIAL | /api/gsd route gone from server.py. BUT: loadGsdWorkstreams() call and updateGsdIndicator() calls remain in app.js with no function definitions — dead harness call sites breaking startup. |
| STRIP-10 | 50-01, 50-02 | Remove Status page | SATISFIED | /api/status route gone; renderStatus gone; data-page="status" gone |
| STRIP-11 | 50-01, 50-02 | Remove Agent Profiles | SATISFIED | /api/profiles, /api/agent-routing routes gone; renderRoutingPanel, renderChainSummary gone |
| STRIP-12 | 50-01, 50-02 | Remove Persona customization | SATISFIED | /api/persona route gone |
| CLEAN-01 | 50-01 | Remove dead server.py routes | SATISFIED | All 19 harness route patterns grep to 0 in server.py |
| CLEAN-02 | 50-02 | Remove dead frontend code | PARTIAL | Bulk of harness render/load functions deleted. Three undefined function calls remain (loadGsdWorkstreams, updateGsdIndicator, _CODE_ONLY_TOOLS) in active code paths. renderDetail dead code block not removed. REQUIREMENTS.md still shows this as unchecked [ ]. |
| CLEAN-03 | 50-03 | Remove unused Python modules | SATISFIED | Harness imports removed from agent42.py, auth.py; ruff lint clean |
| CLEAN-04 | 50-04 | All tests pass after removal | SATISFIED | 2025 passed, 10 skipped, 0 failed |

**ORPHANED requirements check:** All 16 requirement IDs (STRIP-01 through STRIP-12, CLEAN-01 through CLEAN-04) are accounted for across plans 50-01 through 50-04. No orphaned requirements.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `app.js` | 2142 | `loadGsdWorkstreams()` called in loadAll() Promise.all — function deleted | BLOCKER | ReferenceError thrown synchronously inside Promise.all on every page load after login. loadAll() rejects, preventing all intelligence layer state from loading. Dashboard is non-functional. |
| `app.js` | 1124 | `_CODE_ONLY_TOOLS.has(t.name)` inside renderTools() — constant deleted | BLOCKER | ReferenceError thrown every time user visits the Tools page. Tools page is broken. |
| `app.js` | 160, 306, 474, 2237 | `updateGsdIndicator()` called 4 times — function deleted | BLOCKER | ReferenceError on DOMContentLoaded, post-setup completion, post-login, and WebSocket system_health messages. If uncaught, breaks page initialization flow. |
| `app.js` | 981-1097 | `renderDetail()` dead harness function — not in renderers map, but kept | WARNING | Not directly callable from navigation, but contains calls to 10+ deleted functions (doApproveTask, showReviewModal, etc.). Dead code increasing maintenance risk. STATUS_FLAVOR constant (lines 73-83) is only used by renderDetail. |
| `app.js` | 73-83 | `STATUS_FLAVOR` constant — only used by deleted/dead renderDetail | INFO | Dead constant. Minor. |

### Human Verification Required

#### 1. Dashboard Loads Correctly After JS Fix

**Test:** After fixing the three undefined function call sites (loadGsdWorkstreams, updateGsdIndicator, _CODE_ONLY_TOOLS), load the dashboard in a browser and navigate to each of the 5 pages.
**Expected:** Apps, Tools, Skills, Reports, and Settings pages all load without JavaScript console errors. No harness pages appear in the sidebar.
**Why human:** Cannot run a browser in the verification environment.

### Gaps Summary

**Root cause:** Plan 50-02's multi-pass Python script correctly deleted the function *definitions* for loadGsdWorkstreams, updateGsdIndicator, and _CODE_ONLY_TOOLS but missed the *call sites* for those functions in other parts of the file.

- `loadGsdWorkstreams()` was defined somewhere around the harness area but called in `loadAll()` in the main render section (line 2142). The deletion script removed the definition but not the call.
- `updateGsdIndicator()` was defined in the GSD workstreams section but called in 4 widely-spread locations: post-login callback (line 160), setup completion (line 306), WebSocket system_health handler (line 474), and DOMContentLoaded (line 2237).
- `_CODE_ONLY_TOOLS` was a Set constant used by both the deleted `renderCode()` and the kept `renderTools()` (line 1124). The SUMMARY incorrectly stated it was "only referenced by deleted renderCode."

**Impact severity:** The `loadGsdWorkstreams()` gap is the most critical — it causes `loadAll()` to throw a ReferenceError synchronously inside `Promise.all`, which rejects the entire promise. This means the dashboard loads with no data in any panel on startup. The intelligence layer is fully stripped at the server level (success criteria 1-3 are met) but the frontend is broken at runtime (success criteria 4 is not met).

**3 blockers, all in `dashboard/frontend/dist/app.js`:**
1. Remove `loadGsdWorkstreams()` from `loadAll()` call at line 2142
2. Remove or replace `_CODE_ONLY_TOOLS.has()` in `renderTools()` at line 1124
3. Remove or replace the 4 `updateGsdIndicator()` call sites (lines 160, 306, 474, 2237)

These are all small, targeted fixes in a single file.

---

_Verified: 2026-04-07T19:47:52Z_
_Verifier: Claude (gsd-verifier)_
