# Technology Stack — Rewards/Tier System

GSD research output for the agent rewards tier feature. Reference this when implementing
or modifying the rewards engine (`core/rewards_engine.py`).

## Context: This Is an Additive Feature, Not a New Stack
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
### Development Tools (Existing)
| Tool | Purpose | Notes |
|------|---------|-------|
| pytest + pytest-asyncio | Unit and async integration tests for tier logic | Already configured with `asyncio_mode = "auto"`. Test tier transitions, score calculations, semaphore enforcement. |
| ruff | Linting and formatting | Already configured. Run `make format && make lint` after adding new modules. |
## Installation
# No new core dependencies required.
# All recommendations use stdlib or packages already in requirements.txt.
# Optional — only if TTLCache is added:
# First check if it is already a transitive dep:
# If not present:
## Architectural Patterns for This Feature
### Pattern 1: Tier as a Computed Projection, Not Stored State
# core/rewards_engine.py
# In-memory cache: {agent_id: (tier, computed_at)}
### Pattern 2: Frozen Dataclass Tier Limits
### Pattern 3: Semaphore-per-Agent with Swap-on-Promotion
### Pattern 4: Opt-In via Settings, Graceful Degradation When Disabled
### Pattern 5: Composite Score as Weighted Sum (No ML Library Needed)
## Alternatives Considered
| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| `IntEnum` for tiers | String literals "bronze"/"silver"/"gold" | Never for internal code — strings lose comparability. Strings acceptable only at the API/JSON serialization boundary. |
| In-memory TTL dict | `cachetools.TTLCache` | Use `cachetools` only if tier cache needs LRU eviction (thousands of agents). For tens to hundreds of agents, a plain dict with monotonic timestamps is simpler with zero deps. |
| Append to aiosqlite `tier_history` | Separate JSONL audit file | JSONL is fine for human inspection; SQLite is better if you need to query "all agents that were Gold last week". Since aiosqlite is already a dep, prefer it. |
| `asyncio.Semaphore` per-agent | Token bucket rate limiter library (e.g., `aiometer`) | Use a library only if you need continuous rate (requests-per-second) rather than concurrency (in-flight task count). Tier system needs concurrency caps, not rate caps. |
| Pure Python weighted average | scikit-learn metrics | scikit-learn is a 300 MB ML library for a 2-float weighted sum. Never appropriate here. |
| FastAPI endpoints on existing server | Separate microservice | Never. This is an additive feature on Agent42, not a separate service. |
## What NOT to Use
| Avoid | Why | Use Instead |
|-------|-----|-------------|
| `asyncache` 0.3.1 | Unmaintained since November 2022; requires cachetools <=5.x, incompatible with cachetools 7.x | `cachetools-async` 0.0.5 (June 2025) or a Lock-guarded dict |
| Redis Streams or Kafka for tier-change events | Enormous operational overhead for an in-process state change; Redis is optional in Agent42 | `asyncio.Queue` or direct WebSocket push via existing heartbeat/WS infrastructure |
| Celery or task queue for score recomputation | Brings sync worker overhead and hard Redis dependency; Agent42 is async-native | `asyncio.create_task()` scheduled background recompute in the existing event loop |
| scikit-learn | 300 MB dependency for a weighted average of floats | Pure Python arithmetic |
| Separate database for tier state | Tier is a derived view of effectiveness data; a separate DB creates drift risk | Compute from existing effectiveness store; cache in-memory; audit log in the existing aiosqlite DB |
## Stack Patterns by Variant
- `get_agent_tier()` returns `RewardTier.BRONZE` immediately, no DB queries, no cache writes
- All `TierLimits` return Bronze defaults — existing behavior is unchanged
- Use in-memory TTL dict for tier cache (already the primary approach)
- No degradation — Redis is not required for this feature
- Return `RewardTier.BRONZE` regardless of score
- Surface a reason string: "Needs N more task completions to qualify for Silver"
- Store override in `.agent42/rewards/overrides.json` (keyed by agent_id), persisted via `aiofiles`
- `get_agent_tier()` checks overrides first, bypasses score computation entirely
- Dashboard displays "Admin Override: Gold" with a clear visual indicator
## Version Compatibility
| Package | Compatible With | Notes |
|---------|-----------------|-------|
| `cachetools>=7.0.5` | Python 3.10+ | Safe with existing stack (Python 3.11+). If added, do NOT also add `asyncache` (incompatible with 7.x). |
| `aiosqlite>=0.20.0` | Python 3.11+ | Already in requirements.txt. Use `async with aiosqlite.connect()` pattern consistent with existing usage. |
| `asyncio.Semaphore` | Python 3.11+ stdlib | Cannot be resized — design semaphore lifecycle carefully (see Pattern 3). |
| `enum.IntEnum` | Python 3.11+ stdlib | Supports `>=` and `<` comparisons directly, which plain `enum.Enum` does not. |
## Sources
- Agent42 codebase — `core/rate_limiter.py` (sliding-window per-agent pattern), `core/config.py` (frozen dataclass settings pattern), `core/agent_manager.py` (AgentConfig dataclass), `requirements.txt` (existing deps) — HIGH confidence
- [cachetools 7.0.5 on PyPI](https://pypi.org/project/cachetools/) — latest version verified 2026-03-22 — HIGH confidence
- [asyncache 0.3.1 on PyPI](https://pypi.org/project/asyncache/) — confirmed unmaintained (last release November 2022), incompatible with cachetools 7.x — HIGH confidence
- [cachetools-async 0.0.5 on PyPI](https://pypi.org/project/cachetools-async/) — confirmed active (released June 2025) — HIGH confidence
- [Python asyncio.Semaphore docs](https://docs.python.org/3/library/asyncio-sync.html) — fixed-at-creation limit confirmed — HIGH confidence
- [Python enum.IntEnum docs](https://docs.python.org/3/library/enum.html) — IntEnum for tier comparison operators — HIGH confidence
- [cachetools TTLCache docs](https://cachetools.readthedocs.io/en/stable/) — TTL eviction semantics — HIGH confidence
- [asyncio semaphore concurrency pattern](https://rednafi.com/python/limit_concurrency_with_semaphore/) — separate semaphore per scope, cannot resize — MEDIUM confidence (WebSearch, consistent with official docs)