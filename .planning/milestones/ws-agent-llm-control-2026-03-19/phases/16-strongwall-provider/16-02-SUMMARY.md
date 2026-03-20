---
phase: 16-strongwall-provider
plan: 02
subsystem: providers
tags: [strongwall, health-check, spending-tracker, flat-rate, dashboard, httpx]

# Dependency graph
requires:
  - phase: 16-01
    provides: ProviderType.STRONGWALL, ProviderSpec, ModelSpec, Settings.strongwall_monthly_cost
provides:
  - ProviderHealthChecker class with background polling for StrongWall /v1/models
  - SpendingTracker exemption for flat-rate providers (is_flat_rate, _FLAT_RATE_PROVIDERS)
  - SpendingTracker.get_flat_rate_daily() for dashboard cost reporting
  - Dashboard /api/models/health includes provider-level health status
  - Dashboard /api/reports includes flat-rate cost line item
  - provider_health_checker module-level singleton
affects: [17-tier-routing-architecture, 20-streaming-simulation]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Provider health check via /v1/models endpoint probe (no tokens consumed)"
    - "Flat-rate provider spending exemption via _FLAT_RATE_PROVIDERS set"
    - "Background polling loop started from agent42.py startup, cancelled on shutdown"

key-files:
  created: []
  modified:
    - providers/registry.py
    - dashboard/server.py
    - agent42.py
    - tests/test_providers.py

key-decisions:
  - "Health check uses /v1/models endpoint (GET, no tokens consumed) rather than completion requests"
  - "Thresholds: <3s healthy, 3-5s degraded, >5s/error unhealthy per 16-CONTEXT.md"
  - "Polling started in agent42.py alongside other background tasks (not in server.py startup event)"
  - "complete() and complete_with_tools() skip spending limit check for flat-rate providers"

patterns-established:
  - "Provider health polling: ProviderHealthChecker with configurable interval, singleton pattern"
  - "Flat-rate exemption: _FLAT_RATE_PROVIDERS set checked before spending limit enforcement"

requirements-completed: [PROV-04]

# Metrics
duration: 8min
completed: 2026-03-06
---

# Phase 16 Plan 02: StrongWall Health Check and Spending Integration Summary

**Provider-level health polling for StrongWall via /v1/models endpoint, flat-rate spending exemption bypassing daily cap, dashboard reporting with $16/mo cost line item**

## Performance

- **Duration:** 8 min
- **Started:** 2026-03-06T22:13:44Z
- **Completed:** 2026-03-06T22:21:46Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- ProviderHealthChecker class probes StrongWall /v1/models every 60s with 5s timeout, classifying as healthy/degraded/unhealthy
- SpendingTracker exempts flat-rate providers from MAX_DAILY_API_SPEND_USD cap in both complete() and complete_with_tools()
- Dashboard /api/models/health returns provider-level health alongside model-level health
- Dashboard /api/reports includes flat_rate cost line ($16/mo, $0.53/day) separate from per-token costs
- 8 new tests covering health check, spending exemption, flat-rate reporting, and graceful degradation

## Task Commits

Each task was committed atomically:

1. **Task 1 RED: Add failing tests for health checker and spending exemption** - `0dcbc73` (test)
2. **Task 1 GREEN: Implement ProviderHealthChecker and spending exemption** - `6f7acce` (feat)
3. **Task 2: Dashboard integration for health status and flat-rate cost** - `15d16bf` (feat)

_TDD task had RED + GREEN commits (no refactor needed)_

## Files Created/Modified
- `providers/registry.py` - Added ProviderHealthChecker class, _FLAT_RATE_PROVIDERS set, is_flat_rate(), get_flat_rate_daily(), spending limit exemption in complete()/complete_with_tools(), provider_health_checker singleton
- `dashboard/server.py` - Enhanced /api/models/health to include provider-level health, enhanced /api/reports costs to include flat_rate line item
- `agent42.py` - Start provider health polling on startup, stop on shutdown
- `tests/test_providers.py` - Added TestStrongWallHealth class (8 tests): health check no-key, healthy, unhealthy on error, unhealthy on HTTP error, flat-rate exempt, flat-rate daily cost, empty status, graceful degradation

## Decisions Made
- Health check uses GET /v1/models (no tokens consumed, pure reachability probe) rather than sending completion requests like ModelCatalog.health_check()
- Polling started in agent42.py (alongside heartbeat, cron, model catalog loops) rather than server.py startup event, since server.py has no lifespan handler
- Spending limit exemption implemented by checking _FLAT_RATE_PROVIDERS set before calling check_limit(), preserving the existing check_limit() API
- httpx imported at module level in registry.py (already a dependency) for the async HTTP client

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed test_health_checker_no_key_returns_none using async pattern**
- **Found during:** Task 1 (GREEN phase)
- **Issue:** Plan used `asyncio.get_event_loop().run_until_complete()` which fails on Python 3.14 (no default event loop in MainThread)
- **Fix:** Changed to `@pytest.mark.asyncio async def` pattern consistent with other async tests
- **Files modified:** tests/test_providers.py
- **Verification:** Test passes
- **Committed in:** 6f7acce

**2. [Rule 3 - Blocking] Health polling started in agent42.py instead of server.py startup event**
- **Found during:** Task 2
- **Issue:** Plan specified adding to `@app.on_event("startup")` but server.py has no startup/lifespan handler. All background tasks are started in agent42.py.
- **Fix:** Added `provider_health_checker.start_polling()` and `provider_health_checker.stop()` to agent42.py startup/shutdown methods alongside existing heartbeat/cron/catalog loops
- **Files modified:** agent42.py
- **Verification:** Code follows existing pattern for background task lifecycle
- **Committed in:** 15d16bf

---

**Total deviations:** 2 auto-fixed (1 bug fix, 1 blocking)
**Impact on plan:** Correct behavior preserved. Polling location change follows existing architecture pattern. No scope creep.

## Issues Encountered
- httpx AsyncClient mock required explicit `__aenter__`/`__aexit__` setup with `AsyncMock` instances, not `MagicMock` -- fixed by creating separate mock_client_instance as `AsyncMock`

## User Setup Required
None - StrongWall health check is automatic when STRONGWALL_API_KEY is configured. No additional setup needed.

## Next Phase Readiness
- Phase 16 complete: StrongWall registered, health monitored, spending exempted
- Phase 17 (tier routing architecture) has StrongWall available as L1 workhorse candidate
- Phase 20 (streaming simulation) has health check data available for routing decisions

## Self-Check: PASSED

All files exist. All 3 task commits verified (0dcbc73, 6f7acce, 15d16bf).

---
*Phase: 16-strongwall-provider*
*Completed: 2026-03-06*
