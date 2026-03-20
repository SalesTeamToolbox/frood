---
phase: 17-tier-routing-architecture
plan: 02
subsystem: routing
tags: [model-routing, fallback-routing, l1-workhorse, l2-premium, tier-testing, backward-compat]

# Dependency graph
requires:
  - phase: 17-tier-routing-architecture
    plan: 01
    provides: FALLBACK_ROUTING dict, L1 routing methods, L2 authorization, L2_ROUTING self-critique
provides:
  - FALLBACK_ROUTING used consistently across all consumer files (no FREE_ROUTING references remain)
  - TestL1Routing test class covering L1 resolution, health checks, self-critique, ROUTE-02
  - TestL2RoutingUpdates test class covering L2 self-critique and defaults
  - TestFallbackChain test class covering L1-to-fallback degradation and backward compatibility
  - TestFallbackRoutingEntries (renamed from TestFreeRoutingUpdates)
affects: [18-agent-config-backend]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Consumer files import FALLBACK_ROUTING directly (not the FREE_ROUTING alias)"
    - "L1 test pattern: monkeypatch env vars + monkeypatch._is_l1_available for isolated testing"
    - "Fallback chain tests verify backward compat by clearing StrongWall/L1 env vars"

key-files:
  created: []
  modified:
    - agents/model_catalog.py
    - tests/test_model_router.py
    - tests/test_dynamic_routing.py
    - tests/test_model_catalog.py
    - tests/test_openclaw_features.py
    - tests/test_project_interview.py

key-decisions:
  - "CODESTRAL_API_KEY required in backward-compat test to prevent critic validation from nullifying the critic field"
  - "Added TestL2RoutingUpdates.test_l2_max_iterations_are_low to enforce review-pass constraint (max 5 iterations)"
  - "Added TestFallbackChain.test_l1_configured_uses_l1 beyond plan spec to verify the positive L1 path through get_routing()"

patterns-established:
  - "All consumer files use canonical FALLBACK_ROUTING name; FREE_ROUTING alias stays only in model_router.py"
  - "L1 routing tests mock _is_l1_available via monkeypatch.setattr for deterministic health results"

requirements-completed: [TIER-01, TIER-02, TIER-03, TIER-04, TIER-05, ROUTE-02, ROUTE-03]

# Metrics
duration: 8min
completed: 2026-03-07
---

# Phase 17 Plan 02: Tier Routing Architecture Summary

**FALLBACK_ROUTING rename across 6 consumer files with 14 new L1/L2/fallback chain tests covering resolution, self-critique, and backward compatibility**

## Performance

- **Duration:** 8 min
- **Started:** 2026-03-07T02:35:49Z
- **Completed:** 2026-03-07T02:44:24Z
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments
- Renamed all FREE_ROUTING references to FALLBACK_ROUTING across 6 consumer files (~50 references), leaving only the backward-compatible alias in model_router.py
- Added TestL1Routing class (7 tests) covering L1 model resolution, auto-detection, explicit override, health check, self-critique, max_iterations, and ROUTE-02
- Added TestL2RoutingUpdates class (4 tests) covering L2 self-critique for all entries, default models, and max_iterations bounds
- Added TestFallbackChain class (3 tests) covering L1-to-fallback degradation, backward compatibility, and L1-configured positive path
- Renamed TestFreeRoutingUpdates to TestFallbackRoutingEntries with updated docstring
- Total test count: 250 target-file tests pass (236 baseline + 14 new)

## Task Commits

Each task was committed atomically:

1. **Task 1: Rename FREE_ROUTING references in all consumer files** - `6c7e5aa` (refactor)
2. **Task 2: Add L1/L2/fallback chain test classes** - `de27479` (test)

## Files Created/Modified
- `agents/model_catalog.py` - Updated validate_primary_models() to import and use FALLBACK_ROUTING
- `tests/test_model_router.py` - Renamed class and all references to FALLBACK_ROUTING; added TestL1Routing, TestL2RoutingUpdates, TestFallbackChain classes
- `tests/test_dynamic_routing.py` - Changed all FREE_ROUTING imports/references to FALLBACK_ROUTING
- `tests/test_model_catalog.py` - Changed monkeypatch and import references to FALLBACK_ROUTING
- `tests/test_openclaw_features.py` - Changed import and assertion references to FALLBACK_ROUTING
- `tests/test_project_interview.py` - Changed import and assertion references to FALLBACK_ROUTING

## Decisions Made
- CODESTRAL_API_KEY must be set in backward-compat test because get_routing() validates critic availability; without it, critic is set to None, failing the assertion against FALLBACK_ROUTING defaults
- Added test_l2_max_iterations_are_low (not in plan) as a guard ensuring L2 stays low-iteration (review-and-refine pattern)
- Added test_l1_configured_uses_l1 (not in plan) to verify the positive L1 path through the full get_routing() chain

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed backward-compat test critic assertion**
- **Found during:** Task 2 (TestFallbackChain tests)
- **Issue:** test_backward_compat_no_strongwall failed because get_routing() validates critic API key availability and sets critic=None when CODESTRAL_API_KEY is missing
- **Fix:** Added monkeypatch.setenv("CODESTRAL_API_KEY", "test-key") to provide the critic's API key
- **Files modified:** tests/test_model_router.py
- **Verification:** All 14 new tests pass
- **Committed in:** de27479 (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 Rule 1 bug)
**Impact on plan:** Auto-fix necessary for test correctness. No scope creep.

## Issues Encountered
- Ruff linter auto-removes unused imports, requiring import and usage changes to be applied together rather than sequentially. Resolved by using replace_all for body references first, then adding the import.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Phase 17 (Tier Routing Architecture) is now complete: L1/L2 tier structure, resolution chain, and comprehensive test coverage
- Phase 18 (Agent Config Backend) can proceed with per-agent routing config storage and API endpoints
- L2 authorization mechanism (authorize_l2/revoke_l2/is_l2_authorized) is ready for Phase 18/19 dashboard wiring
- All 250 target-file tests pass; full suite compatibility confirmed

## Self-Check: PENDING

---
*Phase: 17-tier-routing-architecture*
*Completed: 2026-03-07*
