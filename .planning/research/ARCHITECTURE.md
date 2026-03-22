# Architecture Research — Performance-Based Rewards System

**Domain:** Agent tier / rewards integration for AI agent platform
**Researched:** 2026-03-22
**Confidence:** HIGH — based on direct inspection of existing codebase

---

## Standard Architecture

### System Overview

```text
┌─────────────────────────────────────────────────────────────────────┐
│                        Dashboard Layer                              │
│  ┌──────────────────┐  ┌───────────────────┐  ┌──────────────────┐  │
│  │  Rewards Toggle  │  │  Tier Management  │  │  Metrics Display │  │
│  │  (enable/disable)│  │  + Admin Override  │  │  (per-agent)     │  │
│  └────────┬─────────┘  └────────┬──────────┘  └────────┬─────────┘  │
│           │                    │                       │             │
│           └────────────────────┼───────────────────────┘             │
│                                │ REST + WebSocket                    │
├────────────────────────────────┼────────────────────────────────────┤
│                       Service Layer                                 │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                    RewardSystem                               │   │
│  │  score_calculator()  tier_cache{}  apply_resource_limits()   │   │
│  └───────────┬──────────────────────────────────┬───────────────┘   │
│              │ reads                            │ writes            │
│  ┌───────────▼──────────┐          ┌────────────▼──────────────┐   │
│  │  EffectivenessStore  │          │      AgentManager         │   │
│  │  (SQLite read-only)  │          │  (tier field + limits)    │   │
│  └──────────────────────┘          └────────────┬──────────────┘   │
├────────────────────────────────────┬─────────────┘─────────────────┤
│                       Execution Layer                               │
│  ┌──────────────────┐  ┌───────────▼──────────┐  ┌──────────────┐  │
│  │   AgentRuntime   │  │    ToolRateLimiter    │  │  Model Router│  │
│  │  (spawns procs)  │  │  (per-agent limits)   │  │  (tier aware)│  │
│  └──────────────────┘  └──────────────────────┘  └──────────────┘  │
├─────────────────────────────────────────────────────────────────────┤
│                       Config Layer                                  │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  Settings (frozen dataclass, from_env())                      │   │
│  │  rewards_enabled | tier thresholds | tier resource limits     │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | Implementation Notes |
|---|---|---|
| `core/reward_system.py` (new) | Score calculation, tier determination, tier cache, resource limit specs | Central coordinator; reads EffectivenessStore, writes back to AgentManager via tier field |
| `memory/effectiveness.py` (existing) | Source of truth for task success, duration, invocation count per agent | Read-only from RewardSystem perspective; never modified by rewards logic |
| `core/agent_manager.py` (extend) | Stores current tier per agent in AgentConfig; enforces tier-driven limits at dispatch time | Add `reward_tier` field and `tier_override` field to AgentConfig; add `get_effective_limits()` method |
| `core/config.py` (extend) | Declares all rewards env vars as frozen Settings fields | Follow frozen dataclass pattern; add `rewards_enabled`, `tier_*_threshold`, `tier_*_max_*` fields |
| `core/rate_limiter.py` (extend) | Accepts per-agent limits from tier, not just global defaults | `ToolRateLimiter.check()` already accepts `agent_id`; extend to accept per-agent limit overrides at construction |
| `dashboard/server.py` (extend) | REST endpoints for rewards toggle, tier list, tier override, metrics | Follow existing pattern: `GET /api/rewards`, `POST /api/rewards/toggle`, `POST /api/agents/{id}/tier-override` |
| `dashboard/websocket_manager.py` (no change) | Broadcasts tier change events to connected dashboard clients | Existing `broadcast()` infrastructure is sufficient |
| `providers/` routing (extend) | Maps tier to allowed model pool | Higher tiers get access to L2 premium models |

---

## Recommended Project Structure

```text
core/
├── reward_system.py          # NEW — RewardSystem class (score calc + tier cache)
├── agent_manager.py          # EXTEND — add reward_tier, tier_override to AgentConfig
├── config.py                 # EXTEND — rewards_enabled + tier threshold/limit fields
├── rate_limiter.py           # EXTEND — per-agent limit overrides from tier
└── ...

memory/
└── effectiveness.py          # READ-ONLY from rewards perspective (no changes)

dashboard/
└── server.py                 # EXTEND — rewards REST endpoints + WS broadcast

tests/
├── test_reward_system.py     # NEW — unit tests (score calc, tier thresholds, caching)
└── test_rewards_integration.py  # NEW — integration tests (AgentManager + dashboard)
```

### Structure Rationale

- **`core/reward_system.py` as its own module:** RewardSystem has distinct lifecycle (cache TTL, score aggregation) that does not belong in AgentManager (which only manages configuration CRUD) or EffectivenessStore (which only records raw data). Keeping it separate avoids circular imports and makes it independently testable.
- **No new data store:** The constraint "must use existing effectiveness tracking data" means all score inputs come from `EffectivenessStore`. RewardSystem only holds an in-memory tier cache (dict keyed by agent_id), not its own database.
- **AgentConfig gets a `reward_tier` field:** Persisting the computed tier to disk (via AgentManager's existing JSON files) means tier survives restarts and is visible to any component that loads an AgentConfig — no live RewardSystem lookup needed at task dispatch time.

---

## Architectural Patterns

### Pattern 1: Cached Tier Computation (compute-on-schedule, serve-from-cache)

**What:** RewardSystem computes scores and tiers on a configurable schedule (e.g., every 15 minutes or on task completion), stores result in an in-memory `dict[agent_id, TierResult]`, and writes the tier back to AgentConfig. All hot-path reads (task dispatch, rate limit check) read from the cached AgentConfig field — never from the computation path.

**When to use:** Any time a derived value is expensive to compute and needed at high frequency. Score calculation requires a SQLite aggregation query; doing this per-request would add latency to every task dispatch.

**Trade-offs:** Cache can be stale by up to one recalculation interval. Acceptable because tier changes are expected to be slow-moving (many tasks needed to shift tier) and admin overrides bypass the cache entirely.

**Example:**

```python
@dataclass
class TierResult:
    agent_id: str
    tier: str          # "bronze" | "silver" | "gold"
    score: float       # composite 0.0-1.0
    computed_at: float # time.time()

class RewardSystem:
    _cache: dict[str, TierResult] = {}
    _cache_ttl: float = 900.0  # 15 minutes

    async def get_tier(self, agent_id: str) -> TierResult:
        cached = self._cache.get(agent_id)
        if cached and (time.time() - cached.computed_at) < self._cache_ttl:
            return cached
        result = await self._compute_tier(agent_id)
        self._cache[agent_id] = result
        return result
```

### Pattern 2: Tier Stored on AgentConfig (persistence via existing infrastructure)

**What:** The computed tier is written to `AgentConfig.reward_tier` via `AgentManager.update()`. This leverages the existing JSON persistence, load-on-startup, and REST API serialization — no new storage code required.

**When to use:** When a new attribute needs to be visible to all platform components (dashboard, runtime, rate limiter) without each of them taking a dependency on RewardSystem directly.

**Trade-offs:** Tier in AgentConfig may be one recalculation interval behind reality. Admin override (`tier_override` field) always wins over computed tier, so urgency overrides are instant.

**Example:**

```python
# In AgentConfig (extend existing dataclass)
reward_tier: str = "bronze"       # computed by RewardSystem, cached here
tier_override: str = ""           # admin-set; if non-empty, overrides reward_tier
performance_score: float = 0.0    # latest composite score (for display)

# Helper used by anything that needs the effective tier
def effective_tier(self) -> str:
    return self.tier_override if self.tier_override else self.reward_tier
```

### Pattern 3: Opt-In Guard (REWARDS_ENABLED=false default)

**What:** Every code path in RewardSystem and AgentManager that branches on tier checks first checks `settings.rewards_enabled`. When disabled, all agents behave identically to pre-rewards behavior — no tier limits, no score computation, no cache maintenance.

**When to use:** Any system-wide toggle where absence of the feature must have zero runtime cost.

**Trade-offs:** Adds one boolean branch per call site. Worth it because it guarantees zero impact on existing deployments that do not set `REWARDS_ENABLED=true`.

**Example:**

```python
# In AgentManager.get_effective_limits()
def get_effective_limits(self, agent_id: str) -> AgentLimits:
    if not settings.rewards_enabled:
        return AgentLimits.defaults()
    agent = self._agents.get(agent_id)
    if not agent:
        return AgentLimits.defaults()
    return TIER_LIMITS[agent.effective_tier()]
```

---

## Data Flow

### Flow 1: Score Computation and Tier Assignment

```text
Task completes
    ↓
EffectivenessStore.record(agent_id, success, duration_ms)   [existing, fire-and-forget]
    ↓
[async background, triggered by timer OR task completion event]
RewardSystem._compute_tier(agent_id)
    ↓
EffectivenessStore.get_aggregated_stats(agent_id)           [SQLite read]
    → success_rate, avg_duration_ms, total_invocations
    ↓
RewardSystem._calculate_score(stats) → float 0.0-1.0
    ↓
RewardSystem._determine_tier(score) → "bronze"|"silver"|"gold"
    ↓
AgentManager.update(agent_id, reward_tier=tier, performance_score=score)
    [writes to agent JSON on disk]
    ↓
WebSocketManager.broadcast({type: "tier_update", agent_id, tier, score})
    [real-time dashboard notification]
```

### Flow 2: Tier Enforcement at Task Dispatch

```text
New task arrives for agent_id
    ↓
AgentManager.get(agent_id) → AgentConfig
    ↓
AgentConfig.effective_tier()           [reads reward_tier or tier_override]
    ↓
AgentManager.get_effective_limits(agent_id) → AgentLimits
    → max_iterations, max_tokens, allowed_model_tier
    ↓
ToolRateLimiter initialized with per-agent limits from AgentLimits
    ↓
AgentRuntime._build_env() uses allowed model from tier-filtered PROVIDER_MODELS
    ↓
Agent subprocess launched with tier-appropriate resources
```

### Flow 3: Admin Tier Override

```text
Admin POSTs /api/agents/{id}/tier-override  {tier: "gold"}
    ↓
AgentManager.update(agent_id, tier_override="gold")
    [persisted immediately to JSON]
    ↓
WebSocketManager.broadcast({type: "tier_override", agent_id, tier: "gold"})
    ↓
Next task dispatch reads effective_tier() → "gold" (override wins)
    ↓
Admin POSTs tier-override with {tier: ""}  →  clears override, computed tier resumes
```

### Flow 4: Dashboard Metrics Display

```text
Dashboard connects via WebSocket
    ↓
ws.onopen → GET /api/agents  [list with reward_tier + performance_score on each]
    ↓
Dashboard renders tier badge per agent
    ↓
Periodic heartbeat broadcast includes tier-relevant fields
    ↓
RewardSystem fires tier_update event → WebSocketManager.broadcast()
    ↓
Dashboard updates tier badge in real time (no page reload)
```

---

## Suggested Build Order

Dependencies drive this order. Each phase can be independently tested before the next begins.

```text
Phase 1: Config Foundation
  core/config.py   ← rewards_enabled, tier thresholds, tier resource limits
  (no behavior yet — just Settings fields)
  Tests: verify Settings.from_env() loads all new fields, defaults correct

Phase 2: RewardSystem Core
  core/reward_system.py   ← score calculation, tier determination, tier cache
  (reads EffectivenessStore, returns TierResult — no writes yet)
  Tests: unit test score_calculator with synthetic stats, tier boundary conditions

Phase 3: AgentConfig Extension
  core/agent_manager.py   ← reward_tier, tier_override, performance_score on AgentConfig
                             effective_tier() helper, get_effective_limits() method
  (persist tier to disk; no enforcement yet)
  Tests: round-trip AgentConfig serialization with new fields

Phase 4: RewardSystem writes tier back
  core/reward_system.py   ← connect score computation to AgentManager.update()
                             add recalculation trigger (timer + on-task-complete)
  (tier now flows end-to-end from data to AgentConfig)
  Tests: integration test — record tasks, run recalculation, verify AgentConfig updated

Phase 5: Enforcement
  core/rate_limiter.py    ← per-agent limit overrides from AgentLimits
  core/agent_manager.py   ← get_effective_limits() returns tier-aware AgentLimits
  providers/ routing       ← tier-aware model selection (Gold → L2 premium allowed)
  Tests: verify Bronze agent cannot exceed Bronze limits, Gold agent gets premium model

Phase 6: Dashboard integration
  dashboard/server.py     ← GET /api/rewards, POST /api/rewards/toggle,
                             POST /api/agents/{id}/tier-override,
                             GET /api/agents/{id}/performance
  dashboard/websocket_manager.py  ← broadcast tier_update events
  Tests: dashboard endpoint tests, WebSocket broadcast coverage

Phase 7: Dashboard UI
  dashboard/static/       ← tier badges, performance metrics panel, toggle switch
  (visual only — all data flows already verified)
  Tests: manual / Playwright UAT
```

---

## Integration Points

### Internal Boundaries

| Boundary | Communication | Notes |
|---|---|---|
| RewardSystem → EffectivenessStore | Direct async call, read-only | RewardSystem takes EffectivenessStore as constructor arg; no circular dependency |
| RewardSystem → AgentManager | Direct call via `AgentManager.update()` | RewardSystem calls existing update() method; no new AgentManager API needed until Phase 3 |
| AgentManager → ToolRateLimiter | AgentLimits passed at construction | ToolRateLimiter already accepts per-tool limits; extend to accept per-agent level |
| AgentManager → AgentRuntime | AgentConfig passed to `_build_env()` | AgentRuntime reads `model` from AgentConfig; tier enforcement adds model filtering before handoff |
| dashboard/server → RewardSystem | Direct call on shared app instance | Follow existing pattern (agent_manager, project_manager passed to create_app()) |
| RewardSystem → WebSocketManager | `ws_manager.broadcast()` on tier change | RewardSystem takes ws_manager as optional constructor arg; skips broadcast if None |

### External Services

| Service | Integration Pattern | Notes |
|---|---|---|
| EffectivenessStore (SQLite) | Async read via `get_aggregated_stats()` | Already exists; no schema changes needed for basic aggregation. RewardSystem needs per-agent data — current API filters by tool_name/task_type, not agent_id. Needs a new `get_agent_stats(agent_id)` method or schema extension. |
| LLM Providers | Tier filters allowed model pool | Gold unlocks L2 premium (Gemini, OR paid); Bronze/Silver limited to free tier. Filter applied in AgentManager before AgentConfig.model is passed to AgentRuntime. |

---

## Scaling Considerations

| Scale | Architecture Adjustments |
|---|---|
| 1-10 agents | In-memory tier cache + per-agent JSON files is sufficient |
| 10-100 agents | Cache TTL may need shortening; recalculation job becomes more expensive; consider batch recalculation on a single timer rather than per-agent on task completion |
| 100+ agents | Consider moving tier computation off the main event loop to a thread pool executor; SQLite may become a bottleneck for aggregation queries across 100+ agents with high task volumes |

### Scaling Priorities

1. **First bottleneck:** SQLite aggregation scan over large `tool_invocations` table. Mitigation: add composite index `(task_id, ts)` to EffectivenessStore; or add an agent-level materialized stats table that is updated incrementally per task.
2. **Second bottleneck:** Cache invalidation contention when many tasks complete simultaneously triggering concurrent recalculations. Mitigation: debounce recalculation per agent (skip if recalculation already in flight for same agent_id).

---

## Anti-Patterns

### Anti-Pattern 1: Computing Tier on Every Hot-Path Request

**What people do:** Call `RewardSystem.compute_score(agent_id)` inside task dispatch, rate limit check, or model routing — every time.

**Why it's wrong:** SQLite aggregation is I/O and CPU intensive. Agent dispatch is already on the asyncio event loop critical path. Adding a blocking aggregation query per dispatch would stall all concurrent agents.

**Do this instead:** Compute on a background schedule (timer-based or post-task-completion). Store result on AgentConfig. Read AgentConfig.reward_tier at dispatch time — O(1) dict lookup.

### Anti-Pattern 2: RewardSystem Modifying EffectivenessStore Data

**What people do:** Write reward tier or score back into the effectiveness SQLite DB so it is "co-located" with the data that drove it.

**Why it's wrong:** EffectivenessStore is a raw event log (append-only design). Mixing derived state (tier) into the raw event store creates a single point of coupling and makes it harder to recompute tiers with different parameters later.

**Do this instead:** Tier is derived metadata. Store it on AgentConfig (already has JSON persistence + REST serialization). EffectivenessStore stays append-only.

### Anti-Pattern 3: Tier Logic Spread Across Multiple Modules

**What people do:** Put threshold comparisons in config.py, score calculation in agent_manager.py, and tier string constants scattered in dashboard/server.py.

**Why it's wrong:** Tier logic needs to change together (thresholds, score formula, resource limits). Spreading it makes the invariant impossible to verify and creates drift between components.

**Do this instead:** All tier logic lives in `core/reward_system.py`. Config only holds raw numeric env var values. AgentManager calls RewardSystem to get the tier label. Dashboard endpoints call AgentManager, not RewardSystem directly.

### Anti-Pattern 4: Hard-Coding Tier Names in AgentRuntime

**What people do:** Put `if agent.reward_tier == "gold": use_premium_model()` directly in AgentRuntime._build_env().

**Why it's wrong:** AgentRuntime should not need to understand tier semantics. Adding tier-conditional branches to _build_env() couples execution logic to reward business rules and makes future tier changes (adding "platinum") require touching execution code.

**Do this instead:** AgentManager.get_effective_limits() returns an `AgentLimits` dataclass with concrete values (allowed_model_tier, max_iterations, etc.). AgentRuntime reads those concrete values, never the tier string.

---

## Key Schema Changes

### AgentConfig additions (core/agent_manager.py)

```python
@dataclass
class AgentConfig:
    # ... existing fields ...

    # Rewards system (added in v1.4)
    reward_tier: str = "bronze"       # "bronze" | "silver" | "gold"
    tier_override: str = ""           # Admin override; empty = use computed tier
    performance_score: float = 0.0    # Latest composite score 0.0-1.0 (display)
    tier_computed_at: float = 0.0     # Timestamp of last tier computation

    def effective_tier(self) -> str:
        """Return tier_override if set, else reward_tier."""
        return self.tier_override if self.tier_override else self.reward_tier
```

### Settings additions (core/config.py)

```python
# Rewards system (v1.4)
rewards_enabled: bool = False                    # Opt-in, zero-impact default
rewards_recalc_interval: int = 900              # Seconds between tier recalculations
rewards_min_tasks_for_tier: int = 5             # Min task completions before tier applies
rewards_silver_threshold: float = 0.70          # Score >= this → Silver
rewards_gold_threshold: float = 0.90            # Score >= this → Gold
rewards_bronze_max_iterations: int = 10
rewards_silver_max_iterations: int = 20
rewards_gold_max_iterations: int = 50
rewards_bronze_model_tier: str = "free"         # Model access level
rewards_silver_model_tier: str = "free"
rewards_gold_model_tier: str = "premium"
```

### EffectivenessStore addition needed (memory/effectiveness.py)

```python
async def get_agent_stats(self, agent_id: str, since_ts: float = 0.0) -> dict:
    """Return aggregated stats for all tool calls tied to an agent.

    Requires task_id to carry agent_id prefix (e.g., '{agent_id}:{task_uuid}')
    OR a new agent_id column added to the tool_invocations table.
    """
```

Note: Current EffectivenessStore schema has `task_id` but not `agent_id` as a column. The rewards system needs per-agent aggregation. Two options:

1. Add `agent_id` column to `tool_invocations` table (schema migration required)
2. Use naming convention: `task_id = "{agent_id}:{uuid}"` and query with `task_id LIKE '{agent_id}:%'`

Option 1 is cleaner. Option 2 avoids a schema migration. Choose based on whether existing task_id values already carry agent context.

---

## Sources

- Direct inspection of `core/agent_manager.py` — AgentConfig dataclass, AgentManager CRUD, PROVIDER_MODELS
- Direct inspection of `memory/effectiveness.py` — EffectivenessStore schema, aggregation API
- Direct inspection of `core/config.py` — Settings frozen dataclass pattern, from_env() pattern, L1/L2 fields as precedent
- Direct inspection of `core/rate_limiter.py` — ToolRateLimiter, per-agent key pattern
- Direct inspection of `core/agent_runtime.py` — AgentRuntime._build_env(), model injection
- Direct inspection of `dashboard/server.py` — FastAPI endpoint patterns
- Direct inspection of `dashboard/websocket_manager.py` — broadcast infrastructure
- `.planning/PROJECT.md` — v1.4 milestone constraints and target features

---

*Architecture research for: Agent42 v1.4 Performance-Based Rewards System*
*Researched: 2026-03-22*
