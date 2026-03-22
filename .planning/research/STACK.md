# Stack Research

**Domain:** Performance-based tier/rewards system for Python async agent platform
**Researched:** 2026-03-22
**Confidence:** HIGH — recommendations derived from existing Agent42 codebase patterns, stdlib capabilities, and verified library versions

---

## Context: This Is an Additive Feature, Not a New Stack

Agent42 already runs Python 3.11+, FastAPI, aiosqlite, asyncio throughout. The rewards system
must fit inside the existing stack without new runtime dependencies where possible. The
recommendations below are split into: **stdlib only** (preferred), **existing deps** (already
in requirements.txt), and **new optional deps** (add only if the stdlib approach is insufficient).

---

## Recommended Stack

### Core Technologies (Stdlib — No New Dependencies)

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| `enum.IntEnum` (stdlib) | Python 3.11+ | `RewardTier` enum (BRONZE/SILVER/GOLD) | Standard, hashable, sortable — IntEnum supports `tier >= SILVER` comparisons which plain Enum does not. Zero deps. Project already uses dataclasses + enum throughout. |
| `dataclasses` (stdlib) | Python 3.11+ | `TierConfig`, `TierLimits`, `AgentTierState` frozen dataclasses | Matches the frozen-dataclass pattern used throughout `core/config.py` and `core/rate_limiter.py`. Immutable tier config objects prevent accidental mutation in concurrent code. |
| `asyncio.Semaphore` (stdlib) | Python 3.11+ | Per-tier concurrent task caps | Agent Manager already manages agent lifecycle. Semaphores keyed per-agent give each tier its concurrent task ceiling. Cannot resize after creation — swap on promotion (see Pattern 3 below). |
| `asyncio.Lock` (stdlib) | Python 3.11+ | Tier state mutation guard | Tier promotions are rare but must be atomic. A per-agent lock prevents race between a score recompute and an in-flight task dispatch. |
| `time.monotonic()` (stdlib) | Python 3.11+ | Cache expiry timestamps | Already used in `rate_limiter.py`. Use for TTL-based tier cache invalidation without importing cachetools. |
| `aiosqlite` (existing dep) | >=0.20.0 | Tier history log | Already in requirements.txt for effectiveness tracking. Add a `tier_history` table alongside existing effectiveness tables. Append-only rows (agent_id, tier, score, timestamp) give full audit trail at zero extra cost. |

### Supporting Libraries (Existing Dependencies — Already Installed)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `aiofiles` (existing) | >=23.0.0 | Persist tier overrides to `.agent42/rewards/overrides.json` | Admin override JSONL for human-readable backup alongside the SQLite audit log. Matches existing file-persistence patterns. |
| FastAPI (existing) | >=0.115.0 | REST endpoints for tier management dashboard | `/api/rewards/tiers`, `/api/rewards/agents/{id}/override`, `/api/rewards/status`. No new framework needed. |
| WebSocket (existing) | >=12.0 | Push tier-change events to dashboard | When an agent promotes from Bronze to Silver, push a `tier_changed` event over the existing WS bus. Dashboard already subscribes to agent status events. |

### New Optional Dependency (Add Only If TTL Cache Complexity Warrants It)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `cachetools` | 7.0.5 (2026-03-09) | `TTLCache` for computed tier scores | Only add if the hand-rolled TTL dict approach grows messy. `TTLCache(maxsize=512, ttl=300)` keyed by `agent_id` is cleaner than dict + timestamp bookkeeping at scale. Likely already installed as a transitive dep — run `pip show cachetools` before adding. |

**Do NOT add `asyncache` 0.3.1** — unmaintained since November 2022, incompatible with
cachetools 7.x (requires <=5.x). If async-safe caching is needed, use `cachetools-async`
0.0.5 (released June 2025, actively maintained) or a simple `asyncio.Lock`-guarded dict.

### Development Tools (Existing)

| Tool | Purpose | Notes |
|------|---------|-------|
| pytest + pytest-asyncio | Unit and async integration tests for tier logic | Already configured with `asyncio_mode = "auto"`. Test tier transitions, score calculations, semaphore enforcement. |
| ruff | Linting and formatting | Already configured. Run `make format && make lint` after adding new modules. |

---

## Installation

```bash
# No new core dependencies required.
# All recommendations use stdlib or packages already in requirements.txt.

# Optional — only if TTLCache is added:
# First check if it is already a transitive dep:
pip show cachetools
# If not present:
pip install "cachetools>=7.0.5"
```

---

## Architectural Patterns for This Feature

### Pattern 1: Tier as a Computed Projection, Not Stored State

**What:** Tier is computed on-demand from effectiveness scores, then cached with a TTL
(5–15 minutes). The canonical data source remains the existing effectiveness store.

**Why:** Avoids a separate "tier store" that can drift from the effectiveness data. The
tier is a view over performance data, not an independent fact. This also means the
rewards engine does not need its own database — it reads from what already exists.

```python
# core/rewards_engine.py
import time
from dataclasses import dataclass
from enum import IntEnum

class RewardTier(IntEnum):
    BRONZE = 1
    SILVER = 2
    GOLD   = 3

@dataclass(frozen=True)
class TierConfig:
    silver_threshold: float = 0.70  # success_rate floor for Silver
    gold_threshold: float   = 0.85  # success_rate floor for Gold
    min_tasks: int          = 10    # minimum completed tasks to qualify for Silver+
    cache_ttl_seconds: int  = 300   # how long before tier is recomputed

# In-memory cache: {agent_id: (tier, computed_at)}
_tier_cache: dict[str, tuple[RewardTier, float]] = {}

async def get_agent_tier(agent_id: str, store, config: TierConfig) -> RewardTier:
    now = time.monotonic()
    cached = _tier_cache.get(agent_id)
    if cached and (now - cached[1]) < config.cache_ttl_seconds:
        return cached[0]
    score = await store.get_agent_score(agent_id)
    tier = _compute_tier(score, config)
    _tier_cache[agent_id] = (tier, now)
    return tier
```

### Pattern 2: Frozen Dataclass Tier Limits

**What:** Each tier has an associated `TierLimits` frozen dataclass specifying resource
ceilings — max concurrent tasks, model access level, API rate multiplier.

**Why:** Matches the `frozen=True` pattern used throughout Agent42 config and rate
limiter. Immutable, hashable, passable without defensive copying. Tier limit lookups
are O(1) dict reads.

```python
@dataclass(frozen=True)
class TierLimits:
    max_concurrent_tasks: int
    rate_limit_multiplier: float  # Applied to ToolRateLimiter defaults
    model_tier: str               # fast, general, or reasoning

TIER_LIMITS: dict[RewardTier, TierLimits] = {
    RewardTier.BRONZE: TierLimits(max_concurrent_tasks=2, rate_limit_multiplier=1.0, model_tier="fast"),
    RewardTier.SILVER: TierLimits(max_concurrent_tasks=4, rate_limit_multiplier=2.0, model_tier="general"),
    RewardTier.GOLD:   TierLimits(max_concurrent_tasks=8, rate_limit_multiplier=3.0, model_tier="reasoning"),
}
```

### Pattern 3: Semaphore-per-Agent with Swap-on-Promotion

**What:** Each agent holds a semaphore reference sized to its tier's `max_concurrent_tasks`.
On tier change, the semaphore is replaced with a new one. The swap is guarded by an
`asyncio.Lock` per agent.

**Why:** `asyncio.Semaphore` cannot be resized after creation. This is the standard
Python pattern for dynamic concurrency limits.

**Critical rule:** On promotion (Bronze to Silver), swap immediately — more capacity
is always safe. On demotion (Gold to Bronze), drain in-flight tasks first (wait until
no tasks hold the semaphore before replacing it) to avoid tasks running at higher
concurrency than the new tier allows.

### Pattern 4: Opt-In via Settings, Graceful Degradation When Disabled

**What:** Add `rewards_enabled: bool = False` to `Settings` (frozen dataclass in
`core/config.py`). When False, `get_agent_tier()` returns `RewardTier.BRONZE`
immediately, and `TierLimits` returns Bronze defaults. Zero behavioral change for
existing deployments.

**Why:** The PROJECT.md constraint is explicit: `REWARDS_ENABLED=false` default.
Follows the exact same pattern as `tool_rate_limiting_enabled`, `qdrant_enabled`,
`l2_enabled`, etc. throughout the existing settings file.

### Pattern 5: Composite Score as Weighted Sum (No ML Library Needed)

**What:** Performance score is a weighted average of 2–4 floats from the effectiveness
store. Weights are configurable via Settings.

**Why:** The data coming from the effectiveness store (success_rate, quality_score, etc.)
are already normalized 0–1 floats. A weighted sum requires no external library — scikit-learn
would be extreme overkill for `score = 0.6 * success_rate + 0.4 * quality_score`.

```python
def compute_performance_score(
    success_rate: float,
    quality_score: float,
    weight_success: float = 0.6,
    weight_quality: float = 0.4,
) -> float:
    return (weight_success * success_rate) + (weight_quality * quality_score)
```

---

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| `IntEnum` for tiers | String literals "bronze"/"silver"/"gold" | Never for internal code — strings lose comparability. Strings acceptable only at the API/JSON serialization boundary. |
| In-memory TTL dict | `cachetools.TTLCache` | Use `cachetools` only if tier cache needs LRU eviction (thousands of agents). For tens to hundreds of agents, a plain dict with monotonic timestamps is simpler with zero deps. |
| Append to aiosqlite `tier_history` | Separate JSONL audit file | JSONL is fine for human inspection; SQLite is better if you need to query "all agents that were Gold last week". Since aiosqlite is already a dep, prefer it. |
| `asyncio.Semaphore` per-agent | Token bucket rate limiter library (e.g., `aiometer`) | Use a library only if you need continuous rate (requests-per-second) rather than concurrency (in-flight task count). Tier system needs concurrency caps, not rate caps. |
| Pure Python weighted average | scikit-learn metrics | scikit-learn is a 300 MB ML library for a 2-float weighted sum. Never appropriate here. |
| FastAPI endpoints on existing server | Separate microservice | Never. This is an additive feature on Agent42, not a separate service. |

---

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| `asyncache` 0.3.1 | Unmaintained since November 2022; requires cachetools <=5.x, incompatible with cachetools 7.x | `cachetools-async` 0.0.5 (June 2025) or a Lock-guarded dict |
| Redis Streams or Kafka for tier-change events | Enormous operational overhead for an in-process state change; Redis is optional in Agent42 | `asyncio.Queue` or direct WebSocket push via existing heartbeat/WS infrastructure |
| Celery or task queue for score recomputation | Brings sync worker overhead and hard Redis dependency; Agent42 is async-native | `asyncio.create_task()` scheduled background recompute in the existing event loop |
| scikit-learn | 300 MB dependency for a weighted average of floats | Pure Python arithmetic |
| Separate database for tier state | Tier is a derived view of effectiveness data; a separate DB creates drift risk | Compute from existing effectiveness store; cache in-memory; audit log in the existing aiosqlite DB |

---

## Stack Patterns by Variant

**If `REWARDS_ENABLED=false` (default):**

- `get_agent_tier()` returns `RewardTier.BRONZE` immediately, no DB queries, no cache writes
- All `TierLimits` return Bronze defaults — existing behavior is unchanged

**If `REWARDS_ENABLED=true`, Redis unavailable:**

- Use in-memory TTL dict for tier cache (already the primary approach)
- No degradation — Redis is not required for this feature

**If agent has fewer than `min_tasks` completions:**

- Return `RewardTier.BRONZE` regardless of score
- Surface a reason string: "Needs N more task completions to qualify for Silver"

**If admin override is set for an agent:**

- Store override in `.agent42/rewards/overrides.json` (keyed by agent_id), persisted via `aiofiles`
- `get_agent_tier()` checks overrides first, bypasses score computation entirely
- Dashboard displays "Admin Override: Gold" with a clear visual indicator

---

## Version Compatibility

| Package | Compatible With | Notes |
|---------|-----------------|-------|
| `cachetools>=7.0.5` | Python 3.10+ | Safe with existing stack (Python 3.11+). If added, do NOT also add `asyncache` (incompatible with 7.x). |
| `aiosqlite>=0.20.0` | Python 3.11+ | Already in requirements.txt. Use `async with aiosqlite.connect()` pattern consistent with existing usage. |
| `asyncio.Semaphore` | Python 3.11+ stdlib | Cannot be resized — design semaphore lifecycle carefully (see Pattern 3). |
| `enum.IntEnum` | Python 3.11+ stdlib | Supports `>=` and `<` comparisons directly, which plain `enum.Enum` does not. |

---

## Sources

- Agent42 codebase — `core/rate_limiter.py` (sliding-window per-agent pattern), `core/config.py` (frozen dataclass settings pattern), `core/agent_manager.py` (AgentConfig dataclass), `requirements.txt` (existing deps) — HIGH confidence
- [cachetools 7.0.5 on PyPI](https://pypi.org/project/cachetools/) — latest version verified 2026-03-22 — HIGH confidence
- [asyncache 0.3.1 on PyPI](https://pypi.org/project/asyncache/) — confirmed unmaintained (last release November 2022), incompatible with cachetools 7.x — HIGH confidence
- [cachetools-async 0.0.5 on PyPI](https://pypi.org/project/cachetools-async/) — confirmed active (released June 2025) — HIGH confidence
- [Python asyncio.Semaphore docs](https://docs.python.org/3/library/asyncio-sync.html) — fixed-at-creation limit confirmed — HIGH confidence
- [Python enum.IntEnum docs](https://docs.python.org/3/library/enum.html) — IntEnum for tier comparison operators — HIGH confidence
- [cachetools TTLCache docs](https://cachetools.readthedocs.io/en/stable/) — TTL eviction semantics — HIGH confidence
- [asyncio semaphore concurrency pattern](https://rednafi.com/python/limit-concurrency-with-semaphore/) — separate semaphore per scope, cannot resize — MEDIUM confidence (WebSearch, consistent with official docs)

---

*Stack research for: Performance-based rewards/tier system on Agent42 (v1.4 milestone)*
*Researched: 2026-03-22*
