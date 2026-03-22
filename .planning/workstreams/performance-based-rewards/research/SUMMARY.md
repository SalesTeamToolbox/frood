# Project Research Summary

**Project:** Agent42 v1.4 — Performance-Based Rewards System
**Domain:** Performance-based tier/rewards system for an AI agent platform
**Researched:** 2026-03-22
**Confidence:** HIGH

## Executive Summary

Agent42 v1.4 adds a Bronze/Silver/Gold rewards tier system that creates a self-reinforcing quality loop: high-performing agents earn access to better models and higher resource limits, which in turn enables them to perform even better. Research confirms this is a well-understood pattern in API platform tier systems (Azure OpenAI, Google Gemini) and gamification frameworks, and the recommended approach treats tier as a **computed projection of existing performance data** rather than an independent stored state. The feature must be entirely additive — `REWARDS_ENABLED=false` by default, zero behavioral change for existing deployments, and all implementation layered on top of the existing `EffectivenessStore`, `AgentManager`, `ToolRateLimiter`, and frozen-dataclass `Settings` infrastructure already in place.

The critical architectural constraint is that tier lookups must never touch the database on the routing hot path. Tier is computed on a background schedule (every 15 minutes), cached in memory, persisted to a JSON file for restart recovery, and stored on `AgentConfig` for O(1) reads at dispatch time. The composite performance score derives from the existing `EffectivenessStore` data (success rate 60%, task volume 25%, speed 15%) — no new ML libraries, no new databases, and no new async frameworks are required. The entire implementation can be delivered with Python stdlib (`IntEnum`, `dataclasses`, `asyncio.Semaphore`) plus dependencies already in `requirements.txt`.

The highest-priority risks are: (1) the existing `EffectivenessStore` schema has no `agent_id` column, meaning per-agent performance data cannot currently be queried — this schema gap must be resolved before any scoring logic is built; (2) the frozen-dataclass `Settings` pattern cannot support a runtime toggle without a separate mutable `RewardsConfig` file; and (3) cold-start agents will be permanently stuck at Bronze if a provisional-tier mechanism is not implemented from the start. These are Phase 1 decisions that cannot be deferred.

## Key Findings

### Recommended Stack

The rewards system requires no new runtime dependencies. All recommendations use Python 3.11+ stdlib or packages already in `requirements.txt`. The feature fits directly into Agent42's existing async, frozen-dataclass, plugin-oriented architecture.

**Core technologies:**

- `enum.IntEnum` (stdlib): `RewardTier` enum — supports `>=` comparisons (unlike plain `Enum`), zero cost
- `dataclasses` (stdlib): `TierConfig`, `TierLimits`, `TierResult` frozen dataclasses — matches project pattern throughout `core/config.py` and `core/rate_limiter.py`
- `asyncio.Semaphore` (stdlib): per-tier concurrent task caps — cannot be resized after creation; swap on promotion, drain before demotion
- `aiosqlite` (existing dep): `tier_history` and `agent_performance` table — already in `requirements.txt` for effectiveness tracking
- `time.monotonic()` (stdlib): TTL-based cache invalidation — already used in `rate_limiter.py`
- FastAPI + WebSocket (existing): REST endpoints and push events — no new framework needed

Optional: `cachetools>=7.0.5` for `TTLCache` if the hand-rolled TTL dict grows unwieldy (check `pip show cachetools` first — likely already a transitive dependency). Do NOT use `asyncache 0.3.1` — unmaintained since November 2022, incompatible with cachetools 7.x.

### Expected Features

**Must have (table stakes) — v1.4:**

- `REWARDS_ENABLED` flag in `Settings` (default `false`) with graceful degradation — required per PROJECT.md constraints
- `PerformanceScoreCalculator` reading from `EffectivenessStore` — composite weighted score (success_rate 60%, volume 25%, speed 15%)
- `TierDeterminator` mapping score to Bronze/Silver/Gold with configurable thresholds (`REWARDS_SILVER_THRESHOLD=0.65`, `REWARDS_GOLD_THRESHOLD=0.85`)
- `ResourceAllocator` — per-tier model routing class, rate limit multiplier, max concurrent tasks
- `AgentManager` integration — apply resource limits from allocator at task dispatch
- Model routing integration — `resolve_model()` accepts tier context and selects appropriate model class
- Admin tier override API — `PATCH /api/agents/{id}/reward-tier`; override stored separately from computed tier and never clobbered by recalculation
- Dashboard tier badge and performance metrics panel per agent
- Scheduled recalculation (every 15 min) + in-memory cache + JSON file persistence for restart recovery
- Provisional tier for new agents (default Silver, not Bronze) until `min_observations` threshold is met

**Should have — v1.4.x patch:**

- Hysteresis / cooldown — require N sustained periods above threshold for promotion; configurable `REWARDS_PROMOTION_COOLDOWN_DAYS`
- Tier change audit log — append-only, timestamp + old/new tier + reason (automated vs override)
- Score explanation endpoint — `GET /api/agents/{id}/reward-score` returns dimension breakdown
- Bulk recalculation admin endpoint — `POST /api/admin/rewards/recalculate-all`

**Defer (v2+):**

- Score trend visualization — needs at least 4 weeks of historical data before charts are meaningful
- Per-task-type tier specialization — adds significant complexity; value unclear until base system is in production use
- Email/webhook notifications on tier change — useful for fleet operators, not needed for single-user deployments
- Fleet-level tier analytics — requires steady-state history first

**Anti-features to avoid:**

- Points/XP accumulation — creates perverse incentives (volume over quality)
- Real-time tier recalculation on every request — violates PROJECT.md "cached/fast" constraint
- Cross-agent competitive leaderboard — meaningless across different task types and complexities
- Tier-gated tool access — tool access is a security boundary, not a performance reward; mixing the two is dangerous

### Architecture Approach

The rewards system is a new `core/reward_system.py` module that reads from `EffectivenessStore` (read-only), writes computed tiers back to `AgentConfig` via `AgentManager.update()`, and broadcasts tier change events over the existing WebSocket infrastructure. The key pattern is: tier is computed on a background schedule, cached in memory (TTL), persisted to `.agent42/tier_assignments.json`, and stored on `AgentConfig` for O(1) hot-path reads. All existing components (`AgentRuntime`, `ToolRateLimiter`, model routing) read from `AgentConfig.effective_tier()` and an `AgentLimits` dataclass — they never call `RewardSystem` directly.

A separate mutable `RewardsConfig` file (not in frozen `Settings`) handles the runtime toggle and threshold overrides that must take effect without a server restart.

**Major components:**

1. `core/reward_system.py` (NEW) — score calculation, tier determination, in-memory cache, file persistence, background recalculation loop
2. `core/agent_manager.py` (EXTEND) — `reward_tier`, `tier_override`, `performance_score`, `tier_computed_at` fields on `AgentConfig`; `effective_tier()` helper; `get_effective_limits()` method
3. `core/config.py` (EXTEND) — `rewards_enabled` startup gate + all threshold/limit env vars as frozen Settings fields; separate mutable `RewardsConfig` for runtime toggle
4. `memory/effectiveness.py` (EXTEND) — add `agent_id` column to `tool_invocations` table OR create separate `agent_performance` table; add `get_agent_stats(agent_id)` method
5. `core/rate_limiter.py` (EXTEND) — extend existing `ToolRateLimiter` with per-agent tier limit overrides, NOT a parallel rate limiter
6. `dashboard/server.py` (EXTEND) — rewards REST endpoints with router-level `require_auth` dependency

### Critical Pitfalls

1. **Tier lookup on the routing hot path** — `get_tier(agent_id)` inside model routing or task dispatch will hit SQLite on every agent iteration, stalling all concurrent agents. Cache tier in memory with TTL; routing code reads `AgentConfig.reward_tier` (O(1) dict lookup), never queries the DB directly.

2. **No `agent_id` in `EffectivenessStore` schema** — the `tool_invocations` table has no `agent_id` column; all effectiveness data is indexed by `(tool_name, task_type, task_id)`. Per-agent scoring is impossible without either a schema migration (add `agent_id` column, default existing rows to `""`) or a separate `agent_performance` table. Must be resolved in Phase 1 before any scoring logic is built.

3. **Frozen dataclass `Settings` cannot support runtime toggle** — `Settings` is frozen at import time. Use `Settings.rewards_enabled` as a startup gate only; a separate mutable `RewardsConfig` (file-backed, non-frozen) handles runtime on/off state and threshold overrides.

4. **Admin override silently clobbered by recalculation** — the background recalculation job will overwrite admin-set tier overrides unless it explicitly checks for active overrides. Store overrides in a separate dict; recalculation skips overridden agents; overrides have a visible timestamp and optional expiry.

5. **Cold-start penalty traps new agents at Bronze** — agents below `min_observations` threshold should receive a "Provisional" status mapping to the configured neutral tier (recommended: Silver), not Bronze. Bronze's resource restrictions create a negative feedback loop that prevents new agents from accumulating the data needed to promote.

6. **Parallel rate limiter conflicts** — adding a new tier-based concurrent task limiter alongside the existing `ToolRateLimiter` creates two independent enforcement points that can conflict under concurrent dispatch. Extend the existing architecture; do not build a parallel one.

7. **Missing auth on new dashboard endpoints** — apply `require_auth` at the router level (`APIRouter(dependencies=[Depends(require_auth)])`), not per-endpoint. An unauthenticated attacker could promote agents to Gold or disable the rewards system entirely.

8. **Tier state lost on restart** — the in-memory tier cache is empty after every restart. Persist computed tiers to `.agent42/tier_assignments.json` after each recalculation; warm the cache from this file on startup.

## Implications for Roadmap

Research strongly suggests a 6-phase build order driven by data dependencies: schema must exist before scoring, scoring must work before enforcement, enforcement must work before dashboard visualization. Each phase is independently testable before the next begins.

### Phase 1: Foundation — Config, Schema, and Tier Cache

**Rationale:** Three hard blockers must be resolved before any other work is possible: the `EffectivenessStore` lacks an `agent_id` column (Pitfall 2), the frozen `Settings` pattern is incompatible with a runtime toggle (Pitfall 3), and the tier cache persistence model must be established before any routing integration (Pitfall 10). These are architectural decisions that cannot be made after the feature is partially built.

**Delivers:** `rewards_enabled` gate in `Settings`; mutable `RewardsConfig` file-backed runtime config; `agent_id` in effectiveness schema; `RewardSystem` class with score calculation, tier determination, in-memory TTL cache, and JSON file persistence; `get_agent_stats(agent_id)` on `EffectivenessStore`

**Addresses features:** REWARDS_ENABLED flag, graceful degradation, tier cache, scoring foundation

**Avoids pitfalls:** Pitfall 1 (hot path), Pitfall 2 (schema gap), Pitfall 3 (frozen dataclass), Pitfall 7 (volume vs quality — task type weights in formula from day 1), Pitfall 10 (restart recovery)

**Research flag:** Well-understood — all patterns derived directly from codebase inspection. No additional research needed.

### Phase 2: Tier Assignment Logic

**Rationale:** With the schema and cache in place, tier determination logic can be built and tested in isolation before any dispatch integration. Provisional tier handling (Pitfall 5) and admin override semantics (Pitfall 4) must be designed at this stage because the recalculation loop is built here.

**Delivers:** `TierDeterminator` with configurable thresholds; provisional tier for new agents; admin override data model (`tier_overrides` dict keyed by agent_id with timestamps and optional expiry); recalculation loop that skips overridden agents; background scheduled recalculation task; `AgentConfig` new fields (`reward_tier`, `tier_override`, `performance_score`, `tier_computed_at`); `effective_tier()` helper

**Addresses features:** Automatic tier assignment, admin override, minimum data threshold, provisional tier

**Avoids pitfalls:** Pitfall 4 (override clobbered by recalculation), Pitfall 5 (cold-start Bronze penalty)

**Research flag:** Well-understood — standard pattern. No additional research needed.

### Phase 3: Resource Enforcement

**Rationale:** Tier labels are meaningless without resource differentiation. This phase wires the computed tier into actual enforcement: concurrent task limits, model routing, and rate limit multipliers. Must audit all existing rate limiting surfaces before adding tier limits (Pitfall 6), and must establish explicit precedence rules before model routing integration (Pitfall 9).

**Delivers:** `TierLimits` frozen dataclass per tier; `AgentManager.get_effective_limits()` returning `AgentLimits`; `ToolRateLimiter` extended with per-agent tier overrides (not a parallel limiter); model routing tier-awareness in `resolve_model()` with explicit precedence (manual override > tier > global default); `allow_tier_routing_override` field on `AgentConfig`

**Addresses features:** Resource differentiation per tier, model routing integration, AgentManager integration

**Avoids pitfalls:** Pitfall 6 (parallel rate limiter conflict), Pitfall 9 (model routing precedence silently overrides per-agent config)

**Research flag:** Targeted pre-read of `core/rate_limiter.py` interface recommended before writing the `ToolRateLimiter` extension — not a full research-phase, just a 15-minute code review.

### Phase 4: Dashboard REST API

**Rationale:** Once enforcement works end-to-end, the dashboard API can expose the full rewards feature. New endpoints must use router-level auth (Pitfall 8), not per-endpoint decorators.

**Delivers:** `GET /api/rewards` (status, enabled state, config); `POST /api/rewards/toggle`; `GET /api/agents/{id}/performance`; `PATCH /api/agents/{id}/reward-tier` (override); `POST /api/admin/rewards/recalculate-all`; all endpoints under `APIRouter(dependencies=[Depends(require_auth)])`; automated 401 tests for every endpoint

**Addresses features:** Admin tier override API, performance metrics endpoint, bulk recalculation

**Avoids pitfalls:** Pitfall 8 (missing auth on rewards endpoints)

**Research flag:** Standard FastAPI patterns — no research needed. Auth pattern already established in `server.py`.

### Phase 5: Dashboard UI

**Rationale:** Visual layer added last, after all data flows are verified and tested. Purely additive — no behavioral changes.

**Delivers:** Tier badge on agent cards (Bronze/Silver/Gold/Provisional); performance metrics panel per agent (score, tier, task count, success rate); rewards toggle switch with confirmation dialog; admin override UI with expiry date; real-time tier update via WebSocket `tier_update` events

**Addresses features:** Tier visibility in dashboard, admin override UI, dashboard metrics panel

**Avoids pitfalls:** UX pitfalls (raw score without context, no explanation, override without expiry, no tier change history visible)

**Research flag:** No research needed — Playwright UAT is the appropriate verification method per project conventions.

### Phase 6: Hysteresis and Audit Trail

**Rationale:** Hysteresis and audit logging are v1.4.x "should have" features. Implementing them after Phase 5 means the base system is already validated in production and the history data needed for hysteresis computation is accumulating.

**Delivers:** `tier_score_history` field on `AgentConfig` (last 4 periods); promotion requires N consecutive periods above threshold; demotion has a grace window; append-only tier change audit log (timestamp, old tier, new tier, reason); score explanation endpoint `GET /api/agents/{id}/reward-score`; audit log visible in dashboard

**Addresses features:** Hysteresis/cooldown, tier change audit log, score explanation breakdown

**Research flag:** Well-documented pattern — standard hysteresis design from enterprise integration patterns and game matchmaking literature.

### Phase Ordering Rationale

- Phases 1-2 are blocked by data dependencies: schema must exist before scoring, scoring before assignment logic
- Phase 3 is blocked by Phase 2: enforcement requires knowing the agent's computed tier
- Phase 4 is blocked by Phase 3: API endpoints surface enforcement state that must work before it's exposed
- Phase 5 is blocked by Phase 4: UI has no backend to call without the API
- Phase 6 is independent of Phases 4-5 and could be parallelized if needed, but is deferred to after production validation so real data informs hysteresis thresholds

The 10 critical pitfalls from PITFALLS.md map cleanly onto Phases 1-3. All critical pitfalls are resolved before the dashboard is even started, ensuring the core correctness of tier computation and enforcement is verifiable in isolation.

### Research Flags

Phases with standard, well-documented patterns (skip `/gsd:research-phase`):

- **Phase 1:** All patterns derived directly from existing codebase inspection — frozen dataclass, TTL cache, aiosqlite schema migration
- **Phase 2:** Standard tier determination pattern — thresholds, provisional handling, admin override
- **Phase 4:** Standard FastAPI router auth pattern, already established in `server.py`
- **Phase 5:** No research needed; Playwright UAT for verification
- **Phase 6:** Standard hysteresis pattern from well-documented domain literature

Phases that may benefit from targeted review (not full research-phase):

- **Phase 3:** Review `core/rate_limiter.py` interface in detail before writing `ToolRateLimiter` extension — targeted pre-read to avoid Pitfall 6, not a research phase

## Confidence Assessment

| Area | Confidence | Notes |
| ---- | ---------- | ----- |
| Stack | HIGH | All recommendations from direct codebase inspection + verified PyPI versions; no speculative deps; no new packages required |
| Features | HIGH | Derived from existing EffectivenessStore data model and PROJECT.md constraints; feature boundaries are clear; anti-features well-justified |
| Architecture | HIGH | Based on direct inspection of `core/agent_manager.py`, `memory/effectiveness.py`, `core/config.py`, `core/rate_limiter.py`, `core/agent_runtime.py`, `dashboard/server.py` |
| Pitfalls | HIGH (codebase-specific) / MEDIUM (scoring formula weights) | Integration pitfalls derived from direct code inspection; composite score weights (60/25/15) need production validation |

**Overall confidence:** HIGH

### Gaps to Address

- **Composite score weights (60/25/15 split):** Research-informed starting point; must be calibrated against real agent data after 2-4 weeks of production operation. Use configurable env vars (`REWARDS_WEIGHT_SUCCESS`, `REWARDS_WEIGHT_VOLUME`, `REWARDS_WEIGHT_SPEED`) from day one so weights can be adjusted without code changes.

- **`agent_id` schema approach (migration vs separate table):** Research identified two options — adding `agent_id` to `tool_invocations` (schema migration, cleaner long-term) or creating a separate `agent_performance` table (avoids migration, cleaner separation). The right choice depends on whether existing `task_id` values already carry agent context. Inspect a sample of live `task_id` values in the production `tool_invocations` table before committing to either approach.

- **Provisional tier default (Silver vs Bronze):** Research recommends Silver as the cold-start default, but the right value depends on how Bronze resource limits affect early agent performance in practice. If Bronze limits are not materially worse than Silver for simple tasks, Bronze provisional may be acceptable. Validate this assumption against the production model routing configuration before Phase 2 implementation is finalized.

- **Task complexity weight mapping:** Research identified the risk that monitoring agents (high volume, high success rate) will outrank coding agents (lower volume, higher complexity). A `task_complexity_weight` per task type is recommended but specific values must be defined before Phase 1 implementation — they cannot be retrofitted without re-scoring all historical data.

## Sources

### Primary (HIGH confidence)

- Agent42 codebase — `core/agent_manager.py`, `core/config.py`, `core/rate_limiter.py`, `core/agent_runtime.py`, `memory/effectiveness.py`, `dashboard/server.py`, `dashboard/websocket_manager.py` — direct codebase inspection
- Python 3.11 stdlib docs — `enum.IntEnum`, `asyncio.Semaphore`, `dataclasses` — confirmed behavior
- `cachetools 7.0.5` on PyPI — version and API verified 2026-03-22
- `asyncache 0.3.1` on PyPI — confirmed unmaintained (November 2022), incompatible with cachetools 7.x
- `cachetools-async 0.0.5` on PyPI — confirmed active (June 2025)
- `.planning/PROJECT.md` — v1.4 milestone constraints and opt-in requirements

### Secondary (MEDIUM confidence)

- Azure OpenAI, Google Gemini, OpenAI API tier documentation — tier threshold patterns and resource allocation multiplier approach
- Galileo AI agent metrics guide — multi-dimension scoring rationale
- Anthropic agent evaluation guide — scoring formula principles
- Xtremepush gamification mechanics — tier hysteresis and cooldown patterns
- Enterprise Integration Patterns — hysteresis design documentation

### Tertiary (LOW confidence / needs production validation)

- Composite score weights (60/25/15) — research-informed starting point; must be calibrated against real Agent42 agent data in production
- Task complexity weight mapping per task type — domain reasoning; specific values TBD before Phase 1

---
*Research completed: 2026-03-22*
*Ready for roadmap: yes*
