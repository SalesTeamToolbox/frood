---
phase: 19-agent-config-dashboard
plan: 01
subsystem: ui
tags: [dashboard, settings, llm-routing, model-selection, vanilla-js, key-store]

# Dependency graph
requires:
  - phase: 18-agent-config-backend
    provides: "AgentRoutingStore, REST API endpoints (GET/PUT/DELETE /api/agent-routing/*), GET /api/available-models"
provides:
  - "LLM Routing tab in Settings page with global default routing controls"
  - "Shared routing helpers: routingSelect(), renderChainSummary(), saveRouting(), resetRouting(), loadRoutingModels(), loadRoutingConfig()"
  - "Updated Providers tab with 6-layer routing chain and L1/L2/Fallback terminology"
  - "StrongWall API Key field in Primary Providers section"
  - "STRONGWALL_API_KEY added to ADMIN_CONFIGURABLE_KEYS"
affects: [19-02-plan, 20-streaming-simulation]

# Tech tracking
tech-stack:
  added: []
  patterns: [routing-select-optgroup, chain-summary-badges, routing-dirty-state-tracking]

key-files:
  created: []
  modified:
    - dashboard/frontend/dist/app.js
    - core/key_store.py

key-decisions:
  - "Three dropdowns (Primary, Critic, Fallback) matching backend API fields, not four -- L2/Premium is a tier option within each dropdown via optgroup"
  - "STRONGWALL_API_KEY added to ADMIN_CONFIGURABLE_KEYS so settingSecret() renders as admin-editable"
  - "Chain summary uses styled badge spans with source-aware coloring (teal for profile override, gold for default, muted for system)"
  - "Empty string in routingEdits means clear override (send null to API), undefined means no change"

patterns-established:
  - "routingSelect(): Tier-grouped native <select> with optgroup headers, reusable for per-agent routing in Plan 02"
  - "renderChainSummary(): Resolution chain display with source badges, reusable for agent detail view"
  - "saveRouting(profileName): Profile-agnostic save function, works for both _default and agent profiles"

requirements-completed: [CONF-01]

# Metrics
duration: 5min
completed: 2026-03-07
---

# Phase 19 Plan 01: Agent Config Dashboard - Settings Summary

**LLM Routing tab in Settings page with tier-grouped model dropdowns, chain summary badges, save/reset controls, and updated Providers tab L1/L2/Fallback terminology**

## Performance

- **Duration:** 5 min
- **Started:** 2026-03-07T17:31:10Z
- **Completed:** 2026-03-07T17:36:46Z
- **Tasks:** 1 (+ 1 checkpoint auto-approved)
- **Files modified:** 2

## Accomplishments
- Settings page LLM Routing tab with three tier-grouped dropdowns (Primary, Critic, Fallback) for global default routing
- Shared routing infrastructure: routingSelect(), renderChainSummary(), saveRouting(), resetRouting() -- all reusable by Plan 02
- Providers tab info boxes updated: 6-layer priority chain with Profile Override step, L1/L2/Fallback terminology, clickable links to LLM Routing tab
- StrongWall API Key field added to Primary Providers section, STRONGWALL_API_KEY added to ADMIN_CONFIGURABLE_KEYS

## Task Commits

Each task was committed atomically:

1. **Task 1: Add shared routing state, loaders, helpers, and Settings LLM Routing tab** - `814f923` (feat)

## Files Created/Modified
- `dashboard/frontend/dist/app.js` - Added LLM Routing tab, shared routing helpers, updated Providers info boxes, StrongWall API key field
- `core/key_store.py` - Added STRONGWALL_API_KEY to ADMIN_CONFIGURABLE_KEYS frozenset

## Decisions Made
- Three dropdowns (Primary, Critic, Fallback) instead of four -- the L2/Premium concept is represented as a tier group within each dropdown's optgroup, matching the backend API's three override fields
- STRONGWALL_API_KEY added to ADMIN_CONFIGURABLE_KEYS so the settingSecret() helper renders it as an admin-editable field (was missing from Phase 16)
- Chain summary uses styled badge spans with source-aware coloring: teal for profile overrides, gold for _default, muted gray for system/FALLBACK_ROUTING
- routingEdits uses empty string to mean "clear override" (sends null to API), undefined means "no change" (field omitted from PUT body)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Added STRONGWALL_API_KEY to ADMIN_CONFIGURABLE_KEYS**
- **Found during:** Task 1 (checking server.py for StrongWall support)
- **Issue:** STRONGWALL_API_KEY was not in the ADMIN_CONFIGURABLE_KEYS frozenset in core/key_store.py, so settingSecret() would render it as read-only (set via env var only)
- **Fix:** Added STRONGWALL_API_KEY to the frozenset alongside other provider API keys
- **Files modified:** core/key_store.py
- **Verification:** 28/28 agent routing tests pass, 108/109 security tests pass (1 pre-existing failure)
- **Committed in:** 814f923 (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 missing critical functionality)
**Impact on plan:** Essential for StrongWall API key to be configurable from the dashboard UI. No scope creep.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- All shared routing helpers (routingSelect, renderChainSummary, saveRouting, resetRouting) are ready for Plan 02 to reuse in per-agent routing on the Agents page
- loadRoutingModels() and loadRoutingConfig() already load data for all profiles, not just _default
- State properties for agent routing edits (agentRoutingEdits, agentRoutingSaving) will need to be added in Plan 02

## Self-Check: PASSED

- All 2 modified files exist on disk
- Task commit 814f923 verified in git history
- 28/28 agent routing tests pass

---
*Phase: 19-agent-config-dashboard*
*Completed: 2026-03-07*
