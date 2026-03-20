---
phase: 18-agent-config-backend
plan: 01
subsystem: routing
tags: [model-routing, agent-profiles, rest-api, json-persistence, mtime-caching]

# Dependency graph
requires:
  - phase: 17-tier-routing-architecture
    provides: "FALLBACK_ROUTING dict, L1/L2 tier structure, get_routing() resolution chain"
provides:
  - "AgentRoutingStore with mtime-cached JSON persistence for per-profile routing overrides"
  - "ModelRouter.get_routing() profile_name parameter for profile-aware model resolution"
  - "Agent.run() passes task.profile to get_routing()"
  - "REST API endpoints: GET/PUT/DELETE /api/agent-routing/*, GET /api/available-models"
  - "_build_resolution_chain() for dashboard inheritance display"
  - "AgentRoutingRequest Pydantic model for PUT validation"
affects: [19-agent-config-dashboard, 20-streaming-simulation]

# Tech tracking
tech-stack:
  added: []
  patterns: [mtime-cached-json-store, atomic-write-replace, profile-inheritance-merge]

key-files:
  created:
    - agents/agent_routing_store.py
    - tests/test_agent_routing.py
  modified:
    - agents/model_router.py
    - agents/agent.py
    - dashboard/server.py

key-decisions:
  - "Profile override inserted as step 1b between admin override and dynamic routing"
  - "get_effective() merges profile + _default only, NOT FALLBACK_ROUTING -- caller falls through when no primary"
  - "has_config() guards profile path to prevent empty get_effective() from short-circuiting resolution"
  - "Critic auto-pairs with primary when unset (self-critique pattern from Phase 17)"
  - "data/agent_routing.json auto-created on first write (gitignored data/ directory)"
  - "GEMINI_PRO_FOR_COMPLEX step runs after profile override -- profile selections still subject to health/key validation"

patterns-established:
  - "AgentRoutingStore: mtime-cached lazy read with atomic os.replace() write"
  - "Resolution chain display: _build_resolution_chain() annotates field sources for dashboard UI"
  - "Profile-aware routing: profile_name parameter threaded from Agent.run() through get_routing()"

requirements-completed: [CONF-03, CONF-04, CONF-05]

# Metrics
duration: 18min
completed: 2026-03-07
---

# Phase 18 Plan 01: Agent Config Backend Summary

**Per-agent routing config store with mtime-cached JSON persistence, profile-aware model resolution in get_routing(), and REST API endpoints for CRUD + available-model enumeration**

## Performance

- **Duration:** 18 min
- **Started:** 2026-03-07T07:30:36Z
- **Completed:** 2026-03-07T07:48:15Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments
- AgentRoutingStore class with mtime-cached JSON persistence, atomic writes, and profile->_default inheritance merge
- ModelRouter.get_routing() now accepts profile_name and inserts profile resolution between admin override and dynamic routing
- Agent.run() wired to pass task.profile to get_routing() for profile-aware routing
- 5 REST API endpoints: list all, get single with resolution chain, set with validation, delete, available models by tier
- 28 tests covering store CRUD, effective resolution, router integration, resolution chain display, and API logic

## Task Commits

Each task was committed atomically:

1. **Task 1: AgentRoutingStore + ModelRouter + Agent wire-up**
   - `2066726` (test: failing tests for store and router integration)
   - `d7e07aa` (feat: implement AgentRoutingStore with profile-aware routing)
2. **Task 2: Dashboard API endpoints + available models**
   - `715f3e0` (test: failing tests for API endpoints and available models)
   - `bb2c933` (feat: add dashboard API endpoints for agent routing)

## Files Created/Modified
- `agents/agent_routing_store.py` - New: mtime-cached JSON store for per-profile routing overrides
- `agents/model_router.py` - Modified: profile_name parameter, step 1b profile resolution, agent_routing_store property
- `agents/agent.py` - Modified: pass task.profile to get_routing() in both L1 and L2 fallback paths
- `dashboard/server.py` - Modified: AgentRoutingRequest model, 5 API endpoints, _build_resolution_chain()
- `tests/test_agent_routing.py` - New: 28 tests across 5 test classes

## Decisions Made
- Profile override inserted as step 1b in resolution chain (between admin override and dynamic routing) -- allows admin env vars to always win while giving profiles priority over data-driven and L1 routing
- get_effective() only merges profile + _default, NOT FALLBACK_ROUTING -- when neither level provides a primary, the caller falls through to the existing dynamic/L1/FALLBACK chain, preserving backward compatibility
- has_config() guards the profile path to prevent empty get_effective() from short-circuiting the resolution chain when no overrides exist
- data/agent_routing.json is gitignored (in data/ directory) and auto-created on first write -- no need to seed the file
- Available models endpoint groups by l1/fallback/l2 tiers and filters out models from providers without configured API keys (CONF-05)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed dynamic variable scope in get_routing()**
- **Found during:** Task 1 (ModelRouter integration)
- **Issue:** After restructuring the if/elif/else block, the `dynamic` variable used in step 4 (policy routing check `if not is_admin_override and not dynamic:`) was not initialized when the profile path was taken
- **Fix:** Added `dynamic = None` initialization before the if/override block
- **Files modified:** agents/model_router.py
- **Verification:** All 58 existing model_router tests pass
- **Committed in:** d7e07aa (Task 1 commit)

**2. [Rule 1 - Bug] Fixed integration test environment for Gemini Pro upgrade**
- **Found during:** Task 1 (ModelRouter integration tests)
- **Issue:** Test set GEMINI_API_KEY for model validation, which triggered the Gemini Pro upgrade step (step 4b) that replaced the profile-selected gemini-2-flash with gemini-2-pro
- **Fix:** Added GEMINI_PRO_FOR_COMPLEX=false to affected tests to isolate profile override behavior
- **Files modified:** tests/test_agent_routing.py
- **Verification:** Profile override tests correctly verify the profile-selected model is returned

---

**Total deviations:** 2 auto-fixed (2 bugs)
**Impact on plan:** Both fixes necessary for correctness. No scope creep.

## Issues Encountered
- data/agent_routing.json cannot be committed because the data/ directory is gitignored -- this is by design (runtime data). The store auto-creates the file on first write.

## User Setup Required
None - no external service configuration required. The agent routing store auto-creates its data file.

## Next Phase Readiness
- All 5 API endpoints ready for Phase 19 dashboard UI consumption
- Resolution chain data structure ready for inheritance display (grayed-out inherited values)
- Available models endpoint provides grouped model lists for dropdown population
- _default key pattern enables Settings page global defaults via same API

## Self-Check: PASSED

- All 5 created/modified files exist on disk
- All 4 task commits verified in git history (2066726, d7e07aa, 715f3e0, bb2c933)
- 28/28 tests pass in test_agent_routing.py
- 58/58 existing model_router tests pass (no regressions)
- 27/27 existing tier_system tests pass (no regressions)

---
*Phase: 18-agent-config-backend*
*Completed: 2026-03-07*
