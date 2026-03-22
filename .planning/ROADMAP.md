# Roadmap: Agent42 Performance-Based Rewards System

## Overview

This roadmap delivers a Bronze/Silver/Gold performance tier system for Agent42 agents. High-performing agents earn access to better models and higher resource limits, creating a self-reinforcing quality loop. The feature is fully additive — `REWARDS_ENABLED=false` by default, zero behavioral change for existing deployments — and is built in four phases ordered by strict data dependencies: foundation must exist before scoring, scoring before enforcement, and enforcement before dashboard visibility.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Foundation** - Config, schema, scoring core, and tier cache with restart recovery
- [ ] **Phase 2: Tier Assignment** - Tier determination logic, provisional handling, admin overrides, and background recalculation
- [ ] **Phase 3: Resource Enforcement** - Wire tier into model routing, rate limits, and concurrent task capacity
- [ ] **Phase 4: Dashboard** - REST API, UI badges, metrics panel, admin controls, and real-time tier events

## Phase Details

### Phase 1: Foundation
**Goal**: The rewards system has a complete data foundation — config gate, schema with agent_id, composite scoring, in-memory TTL cache, and restart recovery — such that tier computation is possible but all new behavior is gated behind REWARDS_ENABLED=false
**Depends on**: Nothing (first phase)
**Requirements**: CONF-01, CONF-02, CONF-03, CONF-04, CONF-05, DATA-01, DATA-02, TIER-01, TIER-04, TIER-05, TEST-01, TEST-05
**Success Criteria** (what must be TRUE):
  1. Agent42 starts and operates identically to pre-rewards baseline when REWARDS_ENABLED is unset or false
  2. Effectiveness tracking records which agent performed each task — per-agent performance stats are queryable
  3. A composite performance score (weighted success rate, volume, speed) can be computed for any agent with recorded data
  4. Computed tiers are cached in memory with TTL and persisted to file — a server restart does not lose tier assignments
  5. A mutable RewardsConfig file controls thresholds and runtime toggle without a server restart
**Plans**: TBD

Plans:
- [ ] 01-01: Config, schema migration, and RewardsConfig
- [ ] 01-02: Score calculation, tier cache, and file persistence

### Phase 2: Tier Assignment
**Goal**: The system automatically assigns Bronze/Silver/Gold tiers to agents based on their performance scores, new agents get a Provisional tier instead of being penalized to Bronze, admin overrides are stored separately and never clobbered by recalculation, and a background task keeps tiers current every 15 minutes
**Depends on**: Phase 1
**Requirements**: TIER-02, TIER-03, ADMN-01, ADMN-03, TEST-02
**Success Criteria** (what must be TRUE):
  1. An agent with sufficient performance data is automatically assigned Bronze, Silver, or Gold based on configurable thresholds
  2. A new agent with fewer than the minimum observations receives Provisional tier, not Bronze
  3. An admin-set tier override persists through background recalculation cycles — the override is never silently replaced
  4. The background recalculation job runs on schedule and updates all non-overridden agents
**Plans**: TBD

Plans:
- [ ] 02-01: TierDeterminator, provisional logic, AgentConfig fields, and recalculation loop
- [ ] 02-02: Admin override model and override tests

### Phase 3: Resource Enforcement
**Goal**: Tier labels produce real resource differences — higher-tier agents access better model classes, benefit from higher rate limit multipliers, and can run more concurrent tasks — while all enforcement reads from a single O(1) AgentConfig field and never touches the database on the routing hot path
**Depends on**: Phase 2
**Requirements**: RSRC-01, RSRC-02, RSRC-03, RSRC-04, TEST-03
**Success Criteria** (what must be TRUE):
  1. A Gold-tier agent dispatches to a higher model class than a Bronze-tier agent under identical conditions
  2. Rate limit multipliers differ by tier — a Gold agent can make more tool calls per window than a Bronze agent
  3. Concurrent task capacity is enforced per tier via semaphore — a Bronze agent cannot exceed its cap regardless of queue depth
  4. Disabling rewards (REWARDS_ENABLED=false) produces routing and rate-limit behavior identical to the pre-rewards baseline
**Plans**: TBD

Plans:
- [ ] 03-01: TierLimits, AgentManager integration, model routing tier-awareness, and ToolRateLimiter extension

### Phase 4: Dashboard
**Goal**: Operators can see every agent's tier and performance metrics at a glance, toggle the rewards system on/off without a restart, override any agent's tier via UI, and watch tier changes propagate in real time via WebSocket — with all API endpoints protected by authentication
**Depends on**: Phase 3
**Requirements**: ADMN-02, DASH-01, DASH-02, DASH-03, DASH-04, DASH-05, TEST-04
**Success Criteria** (what must be TRUE):
  1. Every agent card displays a tier badge (Bronze/Silver/Gold/Provisional) that reflects the current computed or overridden tier
  2. Clicking an agent shows a performance metrics panel with score, tier, task count, and success rate
  3. The settings page has a rewards toggle with a confirmation dialog — toggling takes effect without a server restart
  4. An admin can override any agent's tier via UI, optionally setting an expiry date, and the override is visible and persistent
  5. Tier changes broadcast a WebSocket tier_update event — the dashboard badge updates in real time without a page refresh
  6. All rewards API endpoints return 401 for unauthenticated requests
**Plans**: TBD

Plans:
- [ ] 04-01: Rewards REST API with router-level auth and 401 tests
- [ ] 04-02: Dashboard UI — tier badges, metrics panel, toggle, override UI, and WebSocket events

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Foundation | 0/2 | Not started | - |
| 2. Tier Assignment | 0/2 | Not started | - |
| 3. Resource Enforcement | 0/1 | Not started | - |
| 4. Dashboard | 0/2 | Not started | - |
