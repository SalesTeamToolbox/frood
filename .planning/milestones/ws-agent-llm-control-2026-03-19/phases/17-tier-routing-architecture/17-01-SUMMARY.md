---
phase: 17-tier-routing-architecture
plan: 01
subsystem: routing
tags: [model-routing, l1-workhorse, l2-premium, strongwall, fallback-chain, tier-architecture]

# Dependency graph
requires:
  - phase: 16-strongwall-provider
    provides: StrongWall provider spec, health checker, model registration
provides:
  - FALLBACK_ROUTING dict (renamed from FREE_ROUTING) with backward-compatible alias
  - _resolve_l1_model() for L1 model resolution with env var and auto-detection
  - _is_l1_available() for provider + model health checks
  - _get_l1_routing() returning L1 routing dict with self-critique
  - L2 authorization mechanism (authorize_l2, revoke_l2, is_l2_authorized)
  - L2 last-resort fallback in resolution chain
  - L2 self-critique in L2_ROUTING (critic == primary for all task types)
affects: [18-agent-config-backend, 19-agent-config-dashboard, 17-02]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "L1-first routing: check L1 workhorse before falling to FALLBACK_ROUTING"
    - "L1 self-critique: same model as critic with different reviewer prompt"
    - "L2 self-critique: premium models review their own output"
    - "L2 authorization via runtime sets (task_types + task_ids)"
    - "L1 model resolution: os.getenv first, then settings, then auto-detect from STRONGWALL_API_KEY"

key-files:
  created: []
  modified:
    - agents/model_router.py
    - core/config.py
    - tests/test_tier_system.py

key-decisions:
  - "L1 resolves lazily at get_routing() time, not at startup (KeyStore may inject keys after Settings frozen)"
  - "L2 authorization uses runtime sets on ModelRouter, not config fields (clean for Phase 18/19 wiring)"
  - "L1 self-critique: same model, different prompt (agent execution loop applies reviewer system prompt)"
  - "FALLBACK_ROUTING alias kept permanently (zero runtime cost, no deprecation warning)"
  - "isinstance(val, str) guard on settings.l1_default_model protects against MagicMock in tests"

patterns-established:
  - "L1 model resolution: os.getenv('L1_MODEL') -> settings.l1_default_model -> auto-detect from STRONGWALL_API_KEY"
  - "Resolution chain: admin -> dynamic -> L1/FALLBACK -> policy -> Gemini Pro -> trial"
  - "L2 authorization: authorize_l2(task_type=...) / authorize_l2(task_id=...) for Phase 18/19"

requirements-completed: [TIER-01, TIER-02, TIER-03, TIER-04, TIER-05, ROUTE-01, ROUTE-02]

# Metrics
duration: 20min
completed: 2026-03-07
---

# Phase 17 Plan 01: Tier Routing Architecture Summary

**L1/L2 tier routing in model_router.py with StrongWall auto-detection, FALLBACK_ROUTING rename, L2 self-critique, and authorization mechanism**

## Performance

- **Duration:** 20 min
- **Started:** 2026-03-07T02:10:58Z
- **Completed:** 2026-03-07T02:31:46Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- Renamed FREE_ROUTING to FALLBACK_ROUTING with backward-compatible alias preserving all 55 existing model router tests
- Inserted L1 check as layer 3 in get_routing() resolution chain -- StrongWall becomes default primary when STRONGWALL_API_KEY is set
- Added L2 authorization mechanism (authorize_l2/revoke_l2/is_l2_authorized) ready for Phase 18/19 dashboard wiring
- Updated all 15 L2_ROUTING entries from critic=None to self-critique (critic == primary)
- Added L2 last-resort fallback between CHEAP-tier failure and absolute fallback

## Task Commits

Each task was committed atomically:

1. **Task 1: Rename FREE_ROUTING to FALLBACK_ROUTING and update L2_ROUTING critics** - `2a990b2` (refactor)
2. **Task 2: Add L1 routing methods, L2 authorization, and restructure get_routing()** - `093f0a4` (feat)

## Files Created/Modified
- `agents/model_router.py` - Renamed FREE_ROUTING to FALLBACK_ROUTING, added L1 routing methods (_resolve_l1_model, _is_l1_available, _get_l1_routing), L2 authorization, L2 last-resort fallback, restructured resolution chain
- `core/config.py` - Updated comments to reference FALLBACK_ROUTING instead of FREE_ROUTING
- `tests/test_tier_system.py` - Updated test_l2_routing_has_no_critic to test_l2_routing_self_critiques

## Decisions Made
- L1 resolves lazily at get_routing() time, not at startup -- KeyStore.inject_into_environ() may inject API keys after Settings frozen (per Pitfall 1 from RESEARCH.md)
- L2 authorization uses runtime sets on ModelRouter instance, not config fields -- clean surface for Phase 18/19 to wire dashboard UI
- L1 self-critique: same model, different reviewer prompt (the agent execution loop already builds separate reviewer system prompts)
- FALLBACK_ROUTING alias kept permanently with no deprecation warning (zero runtime cost)
- Added isinstance(val, str) guard on settings.l1_default_model to protect against MagicMock returning truthy non-string values in tests

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed MagicMock settings.l1_default_model in tests**
- **Found during:** Task 2 (L1 routing methods)
- **Issue:** _patch_policy() mocks settings with MagicMock, causing settings.l1_default_model to return a truthy MagicMock object. This made _resolve_l1_model() treat it as a valid model name, breaking test_free_only_uses_free_routing_defaults.
- **Fix:** Added isinstance(val, str) guard in _resolve_l1_model() to only use settings.l1_default_model if it's actually a string
- **Files modified:** agents/model_router.py
- **Verification:** All 55 model router tests pass
- **Committed in:** 093f0a4 (Task 2 commit)

**2. [Rule 1 - Bug] Updated test_l2_routing_has_no_critic assertion**
- **Found during:** Task 2 verification (full test suite)
- **Issue:** tests/test_tier_system.py::test_l2_routing_has_no_critic asserted critic=None for all L2 entries, which contradicts the intentional change to self-critique
- **Fix:** Renamed test to test_l2_routing_self_critiques, updated assertion to verify critic == primary
- **Files modified:** tests/test_tier_system.py
- **Verification:** All 27 tier system tests pass
- **Committed in:** 093f0a4 (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (2 Rule 1 bugs)
**Impact on plan:** Both auto-fixes necessary for correctness. No scope creep.

## Issues Encountered
- Pre-existing test failure in tests/test_security.py::TestFailSecureLogin::test_login_rejected_no_password (KeyError: 'detail') -- confirmed unrelated to our changes, exists on baseline commit. Not fixed (out of scope).

## User Setup Required
None - no external service configuration required. L1 routing activates automatically when STRONGWALL_API_KEY is set.

## Next Phase Readiness
- L1/L2 tier routing structure complete in model_router.py
- L2 authorization mechanism ready for Phase 18/19 dashboard wiring
- Plan 17-02 can proceed with fallback chain testing and backward compatibility verification
- All 2084 tests pass (excluding 1 pre-existing security test failure)

## Self-Check: PASSED

- All key files exist (agents/model_router.py, core/config.py, tests/test_tier_system.py, 17-01-SUMMARY.md)
- All commits verified (2a990b2, 093f0a4)
- All code artifacts present (FALLBACK_ROUTING, _resolve_l1_model, _is_l1_available, _get_l1_routing, authorize_l2, revoke_l2, is_l2_authorized)

---
*Phase: 17-tier-routing-architecture*
*Completed: 2026-03-07*
