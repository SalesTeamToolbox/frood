# Requirements: Agent42 Performance-Based Rewards System

**Defined:** 2026-03-22
**Core Value:** Agents that consistently deliver value get better tools to deliver more value — creating a self-reinforcing quality loop tied to measurable outcomes.

## v1 Requirements

Requirements for initial release. Each maps to roadmap phases.

### Configuration

- [x] **CONF-01**: System respects `REWARDS_ENABLED` flag (default `false`) — zero behavioral change when disabled
- [x] **CONF-02**: Tier thresholds configurable via environment variables (`REWARDS_SILVER_THRESHOLD`, `REWARDS_GOLD_THRESHOLD`)
- [x] **CONF-03**: Per-tier resource limits configurable via environment variables (model tier, rate limit multiplier, max concurrent tasks)
- [x] **CONF-04**: Score weights configurable via environment variables (`REWARDS_WEIGHT_SUCCESS`, `REWARDS_WEIGHT_VOLUME`, `REWARDS_WEIGHT_SPEED`)
- [x] **CONF-05**: Runtime toggle via mutable `RewardsConfig` file (separate from frozen `Settings`) takes effect without server restart

### Schema & Data

- [x] **DATA-01**: Effectiveness tracking includes `agent_id` for per-agent performance queries
- [x] **DATA-02**: `get_agent_stats(agent_id)` method on EffectivenessStore returns success_rate, task_volume, avg_speed per agent

### Scoring & Tiers

- [ ] **TIER-01**: Composite performance score calculated from existing effectiveness data (success_rate, volume, speed with configurable weights)
- [ ] **TIER-02**: Automatic tier assignment — Bronze/Silver/Gold based on composite score vs configurable thresholds
- [ ] **TIER-03**: Provisional tier assigned to new agents below minimum observation threshold (not penalized to Bronze)
- [ ] **TIER-04**: Tier cached in memory with TTL — never computed on the routing hot path
- [ ] **TIER-05**: Tier persisted to file for restart recovery — cache warmed from file on startup

### Resource Enforcement

- [ ] **RSRC-01**: Per-tier model routing — higher-tier agents get access to better model classes via `resolve_model()` tier context
- [ ] **RSRC-02**: Per-tier rate limit multipliers applied through existing `ToolRateLimiter` extension (not a parallel limiter)
- [ ] **RSRC-03**: Per-tier concurrent task capacity enforced via `asyncio.Semaphore` swap-on-promotion pattern
- [ ] **RSRC-04**: Agent Manager applies effective tier limits at task dispatch — reads from `AgentConfig.effective_tier()`

### Admin Controls

- [ ] **ADMN-01**: Admin can override any agent's tier via dashboard — override stored separately, not clobbered by recalculation
- [ ] **ADMN-02**: Admin can toggle rewards system on/off via dashboard without server restart
- [ ] **ADMN-03**: Background recalculation runs on schedule (default every 15 minutes) and skips overridden agents

### Dashboard

- [ ] **DASH-01**: Tier badge displayed on each agent card (Bronze/Silver/Gold/Provisional)
- [ ] **DASH-02**: Performance metrics panel per agent showing score, tier, task count, success rate
- [ ] **DASH-03**: Rewards system toggle switch with confirmation dialog in settings
- [ ] **DASH-04**: Admin tier override UI with optional expiry date
- [ ] **DASH-05**: Real-time tier updates via WebSocket `tier_update` events

### Testing

- [ ] **TEST-01**: Unit tests for score calculation logic (composite weights, edge cases, zero data)
- [ ] **TEST-02**: Unit tests for tier determination (threshold boundaries, provisional tier, override precedence)
- [ ] **TEST-03**: Integration tests for Agent Manager tier enforcement (model routing, rate limits, concurrency)
- [ ] **TEST-04**: Dashboard API tests including 401 auth verification for all rewards endpoints
- [x] **TEST-05**: Graceful degradation tests — rewards disabled produces identical behavior to pre-feature baseline

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Hysteresis & History

- **HYST-01**: Promotion requires N consecutive periods above threshold before upgrading tier
- **HYST-02**: Demotion has a configurable grace window before downgrading
- **HYST-03**: Tier change audit log — append-only with timestamp, old/new tier, reason (automated vs override)
- **HYST-04**: Score explanation endpoint returns dimension breakdown per agent

### Analytics

- **ANLT-01**: Score trend visualization showing weekly performance direction
- **ANLT-02**: Bulk recalculation admin endpoint for threshold changes
- **ANLT-03**: Fleet-level tier analytics across all agents

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
| ------- | ------ |
| Points/XP accumulation | Creates perverse incentives — volume over quality. Rolling success rate is recency-weighted and more accurate |
| Real-time tier recalculation per request | Violates "cached/fast" constraint. Scheduled recalculation with cache is the correct pattern |
| Cross-agent competitive leaderboard | Meaningless across different task types and complexities. Per-tier grouping only |
| Tier-gated tool access | Tool access is a security boundary, not a performance reward. Only resource limits vary by tier |
| Retroactive scoring from pre-rewards data | Pre-rewards data has no tier context. Score only from data after REWARDS_ENABLED=true |
| Custom tier names | Adds config/UI complexity with no behavioral benefit. Bronze/Silver/Gold is industry standard |
| Negative score for failures | Creates over-cautious agents avoiding complex tasks. Success rate already penalizes failures proportionally |
| Agent self-awareness of tier | Agents don't need to know their tier — prevents gaming behavior |
| Tier demotion notifications | Not needed for v1 single-user deployments |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
| ----------- | ----- | ------ |
| CONF-01 | Phase 1 | Complete |
| CONF-02 | Phase 1 | Complete |
| CONF-03 | Phase 1 | Complete |
| CONF-04 | Phase 1 | Complete |
| CONF-05 | Phase 1 | Complete |
| DATA-01 | Phase 1 | Complete |
| DATA-02 | Phase 1 | Complete |
| TIER-01 | Phase 1 | Pending |
| TIER-02 | Phase 2 | Pending |
| TIER-03 | Phase 2 | Pending |
| TIER-04 | Phase 1 | Pending |
| TIER-05 | Phase 1 | Pending |
| RSRC-01 | Phase 3 | Pending |
| RSRC-02 | Phase 3 | Pending |
| RSRC-03 | Phase 3 | Pending |
| RSRC-04 | Phase 3 | Pending |
| ADMN-01 | Phase 2 | Pending |
| ADMN-02 | Phase 4 | Pending |
| ADMN-03 | Phase 2 | Pending |
| DASH-01 | Phase 4 | Pending |
| DASH-02 | Phase 4 | Pending |
| DASH-03 | Phase 4 | Pending |
| DASH-04 | Phase 4 | Pending |
| DASH-05 | Phase 4 | Pending |
| TEST-01 | Phase 1 | Pending |
| TEST-02 | Phase 2 | Pending |
| TEST-03 | Phase 3 | Pending |
| TEST-04 | Phase 4 | Pending |
| TEST-05 | Phase 1 | Complete |

**Coverage:**

- v1 requirements: 29 total (note: original count of 27 was a counting error; actual count is 29)
- Mapped to phases: 29
- Unmapped: 0

---
*Requirements defined: 2026-03-22*
*Last updated: 2026-03-22 — traceability updated after roadmap creation (Phase 5 collapsed into Phase 4 for coarse granularity)*
