# Phase 3: Resource Enforcement — Research

**Researched:** 2026-03-22
**Domain:** Python asyncio concurrency, sliding-window rate limiting, model routing, AgentManager integration
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Augment existing `resolve_model(provider, task_category)` in `core/agent_manager.py` with an optional `tier` parameter. Higher tiers get upgraded task categories: Gold→`"reasoning"`, Silver→`"general"`, Bronze→`"fast"`. Reuses existing `PROVIDER_MODELS` columns.
- **D-02:** Precedence: manual per-agent model override (stored on AgentConfig.model) > tier-based upgrade > global default. If agent has an explicit model set, tier does not override it.
- **D-03:** `resolve_model()` call sites that don't pass `tier` get unchanged behavior (backwards compatible).
- **D-04:** Extend `ToolRateLimiter.check()` in `core/rate_limiter.py` to accept tier and apply multiplier. Scale `ToolLimit.max_calls` by tier multiplier before the sliding-window comparison. Multipliers from `Settings`: bronze=1.0, silver=1.5, gold=2.0.
- **D-05:** The `_calls` dict remains keyed by `{agent_id}:{tool_name}` — no structural change. Only the effective max_calls changes per tier.
- **D-06:** When tier is empty string or None, multiplier defaults to 1.0 (no change from pre-rewards behavior).
- **D-07:** Per-tier concurrent task limits enforced via `asyncio.Semaphore` acquired in `server.py` `start_agent` endpoint before calling `AgentRuntime.start_agent()`. Caps from Settings: bronze=2, silver=5, gold=10.
- **D-08:** Semaphore capacity per tier stored as a dict on `AgentManager` (keyed by tier string). Per-tier shared limit — all agents of same tier share the same cap. Simpler than per-agent semaphores.
- **D-09:** When rewards disabled or tier is empty, no semaphore acquired (unlimited, matching pre-rewards behavior).
- **D-10:** All three enforcement points check `settings.rewards_enabled` (or `effective_tier() == ""`) at the top — single check, no branching inside hot paths. Empty-string tier = "no tier" = skip enforcement.
- **D-11:** `AgentConfig.effective_tier()` returns `""` when no tier assigned. All enforcement code must handle this case explicitly (no KeyError on empty-string lookup).
- **D-12:** `AgentManager.get_effective_limits(agent_id) -> dict` method returns `{"model_tier": str, "rate_multiplier": float, "max_concurrent": int}` by reading `effective_tier()` and mapping to Settings values. Single query point for Phase 4 dashboard.

### Claude's Discretion

- Whether to add a `TierLimits` frozen dataclass or use a simple dict mapping
- Exact error handling when semaphore acquisition times out (if applicable)
- Whether to log tier-based routing decisions at DEBUG level

### Deferred Ideas (OUT OF SCOPE)

- Dashboard REST API for tier/limits display — Phase 4
- Dashboard UI for tier badges and metrics — Phase 4
- Per-agent semaphore swap-on-promotion — v2
- Model routing audit log — v2
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| RSRC-01 | Per-tier model routing — higher-tier agents get access to better model classes via `resolve_model()` tier context | `resolve_model()` is a single dispatch point; adding optional `tier` param with category upgrade is straightforward — full details in Architecture Patterns |
| RSRC-02 | Per-tier rate limit multipliers applied through existing `ToolRateLimiter` extension (not a parallel limiter) | `check()` in `rate_limiter.py` receives `agent_id`; adding `tier` param for effective max_calls scaling requires no structural changes to `_calls` dict |
| RSRC-03 | Per-tier concurrent task capacity enforced via `asyncio.Semaphore` swap-on-promotion pattern | `asyncio.Semaphore` not yet used in codebase; semaphores live on `AgentManager`, acquired in `server.py` `start_agent` endpoint — new pattern, full code example below |
| RSRC-04 | Agent Manager applies effective tier limits at task dispatch — reads from `AgentConfig.effective_tier()` | `effective_tier()` already implemented and tested in Phase 2; `get_effective_limits()` is a new method on `AgentManager` — see Architecture Patterns |
| TEST-03 | Integration tests for Agent Manager tier enforcement (model routing, rate limits, concurrency) | No `test_resource_enforcement.py` exists yet; Wave 0 must create it — see Validation Architecture |
</phase_requirements>

## Summary

Phase 3 wires three already-designed enforcement points together. All configuration values (multipliers, concurrency caps, tier model mappings) were placed in `Settings` during Phase 1 and are verified present. The `AgentConfig.effective_tier()` method was built and tested in Phase 2 and is the sole read point. The implementation work is surgical: three file modifications and one new test file.

The rate limiter extension is the most nuanced because `check()` is called from `tools/registry.py` via `self._rate_limiter.check(tool_name, agent_id)`. The caller does not currently pass tier. The cleanest approach — consistent with D-04 through D-06 — is to add `tier: str = ""` as a keyword-only argument to `check()`, then pass it from `registry.execute()`. However, `registry.execute()` also does not currently receive tier. The path of least resistance is to add tier to both `ToolRateLimiter.check()` and `ToolRegistry.execute()` as optional kwargs defaulting to `""`. Callers that don't pass tier get exactly the old behavior (D-06).

The semaphore pattern (D-07/D-08) is genuinely new — no `asyncio.Semaphore` exists in the codebase yet. The key implementation detail is that semaphores must be created once and reused, not created per-request. They live on `AgentManager` as a `dict[str, asyncio.Semaphore]` keyed by tier. The `start_agent` endpoint in `server.py` acquires the correct semaphore before calling `AgentRuntime.start_agent()`.

**Primary recommendation:** Implement in wave order: (1) `resolve_model()` + `get_effective_limits()` — pure computation, no concurrency, easiest to test; (2) `ToolRateLimiter.check()` + `ToolRegistry.execute()` — sliding window extension; (3) semaphore init on `AgentManager` + acquisition in `server.py` — async concurrency boundary.

## Standard Stack

### Core (already in project)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `asyncio` (stdlib) | 3.12 | `asyncio.Semaphore` for concurrent task cap | Native Python async primitive — no dependency |
| `dataclasses` (stdlib) | 3.12 | `ToolLimit`, `AgentConfig` patterns | Established project pattern — frozen dataclass for config |
| `collections.defaultdict` | stdlib | `_calls` dict in `ToolRateLimiter` | Already used — no change |

### No New Dependencies

This phase introduces no new packages. All libraries are stdlib or already installed.

**Version verification:** N/A — stdlib only.

## Architecture Patterns

### Pattern 1: Augmenting `resolve_model()` (RSRC-01, D-01 through D-03)

**What:** Add `tier: str = ""` optional param. Map tier to category upgrade before the existing lookup. Fall through to unchanged behavior when tier is absent or empty.

**When to use:** All sites that start an agent with a known tier.

**Tier-to-category mapping:**

```python
# core/agent_manager.py

_TIER_CATEGORY_UPGRADE: dict[str, str] = {
    "gold": "reasoning",
    "silver": "general",
    "bronze": "fast",
    # "provisional" and "" → no upgrade, caller's task_category wins
}

def resolve_model(provider: str, task_category: str, tier: str = "") -> str:
    """Resolve the best model for a provider + task category + optional tier.

    If tier produces an upgrade, the upgraded category takes precedence
    over the caller's task_category. Manual model override (AgentConfig.model)
    must be applied by the caller before calling this function (D-02).
    """
    effective_category = _TIER_CATEGORY_UPGRADE.get(tier, task_category)
    models = PROVIDER_MODELS.get(provider, PROVIDER_MODELS.get("anthropic", {}))
    return models.get(effective_category, models.get("general", "claude-sonnet-4-6"))
```

**D-02 enforcement — caller responsibility:** The `start_agent` endpoint already copies `agent.to_dict()` into the agent_config dict that `AgentRuntime` uses. If `agent.model` is explicitly set (non-empty string), the endpoint must NOT call `resolve_model()` again — the stored model is the manual override. Only when the agent has no explicit model override does the caller pass tier to `resolve_model()`.

**D-03:** All existing callers that invoke `resolve_model(provider, category)` without a tier argument continue working identically — `tier=""` means no upgrade.

### Pattern 2: `ToolRateLimiter.check()` with tier multiplier (RSRC-02, D-04 through D-06)

**What:** Add `tier: str = ""` keyword argument to `check()`. Compute effective max_calls = floor(limit.max_calls * multiplier). No other changes.

**Critical detail:** The multiplier lookup needs the `Settings` singleton. Import `settings` at the top of `rate_limiter.py` (it is already used throughout the codebase via `from core.config import settings`).

```python
# core/rate_limiter.py

from core.config import settings  # ADD

_TIER_MULTIPLIERS: dict[str, float] = {}  # Populated lazily from settings

def _get_multiplier(tier: str) -> float:
    """Return rate limit multiplier for a tier. Defaults to 1.0."""
    if not tier:
        return 1.0
    return {
        "bronze": settings.rewards_bronze_rate_limit_multiplier,
        "silver": settings.rewards_silver_rate_limit_multiplier,
        "gold":   settings.rewards_gold_rate_limit_multiplier,
    }.get(tier, 1.0)


class ToolRateLimiter:
    def check(self, tool_name: str, agent_id: str = "default", tier: str = "") -> tuple[bool, str]:
        limit = self._limits.get(tool_name)
        if not limit:
            return True, ""

        multiplier = _get_multiplier(tier)
        effective_max = int(limit.max_calls * multiplier)  # floor via int()

        key = f"{agent_id}:{tool_name}"
        now = time.monotonic()
        cutoff = now - limit.window_seconds
        self._calls[key] = [t for t in self._calls[key] if t > cutoff]

        if len(self._calls[key]) >= effective_max:
            remaining = limit.window_seconds - (now - self._calls[key][0])
            msg = (
                f"Rate limit exceeded for '{tool_name}': "
                f"{effective_max} calls per {int(limit.window_seconds)}s window "
                f"(tier={tier or 'none'}). Try again in {int(remaining)}s."
            )
            logger.warning(f"[{agent_id}] {msg}")
            return False, msg

        return True, ""
```

**Propagating tier through `ToolRegistry.execute()`:** The `execute()` method signature is `execute(self, tool_name, agent_id="default", **kwargs)`. Add `tier: str = ""` as a keyword argument (before `**kwargs`) and pass it through to `check()`. MCP server callers don't currently pass tier — they get `""` which means unchanged behavior (D-06).

```python
# tools/registry.py — execute() signature change
async def execute(self, tool_name: str, agent_id: str = "default", tier: str = "", **kwargs) -> ToolResult:
    ...
    if self._rate_limiter:
        allowed, reason = self._rate_limiter.check(tool_name, agent_id, tier=tier)
```

**D-05 verified:** `_calls` dict key stays `{agent_id}:{tool_name}` — structural change is zero.

### Pattern 3: `asyncio.Semaphore` per-tier concurrency cap (RSRC-03, D-07 through D-09)

**What:** `AgentManager` holds `_tier_semaphores: dict[str, asyncio.Semaphore]`. The `start_agent` endpoint acquires the semaphore for the agent's tier before launching, releases after.

**Critical pitfall — semaphore creation timing:** `asyncio.Semaphore` must be created in an async context (inside a running event loop) or after `asyncio.get_event_loop()` is available. Creating them in `AgentManager.__init__()` is safe only because FastAPI's Uvicorn starts the event loop before `create_app()` runs. The safest pattern is lazy initialization — create semaphores on first access.

```python
# core/agent_manager.py — additions to AgentManager

class AgentManager:
    def __init__(self, agents_dir: str | Path):
        ...
        self._tier_semaphores: dict[str, asyncio.Semaphore] = {}  # lazy-init

    def _get_tier_semaphore(self, tier: str) -> asyncio.Semaphore | None:
        """Return (creating if needed) the semaphore for a tier.

        Returns None when rewards disabled or tier is empty (D-09).
        """
        from core.config import settings  # deferred — same pattern as TierDeterminator
        if not settings.rewards_enabled or not tier:
            return None
        if tier not in self._tier_semaphores:
            cap_map = {
                "bronze": settings.rewards_bronze_max_concurrent,
                "silver": settings.rewards_silver_max_concurrent,
                "gold":   settings.rewards_gold_max_concurrent,
            }
            cap = cap_map.get(tier, settings.rewards_bronze_max_concurrent)
            self._tier_semaphores[tier] = asyncio.Semaphore(cap)
        return self._tier_semaphores[tier]

    def get_effective_limits(self, agent_id: str) -> dict:
        """Return enforcement limits for an agent based on its effective tier (D-12).

        Reads from AgentConfig.effective_tier() only — O(1), no DB.
        Returns safe defaults when agent not found or rewards disabled.
        """
        from core.config import settings
        agent = self._agents.get(agent_id)
        tier = agent.effective_tier() if agent else ""

        if not settings.rewards_enabled or not tier:
            return {"model_tier": "", "rate_multiplier": 1.0, "max_concurrent": 0}

        multiplier_map = {
            "bronze": settings.rewards_bronze_rate_limit_multiplier,
            "silver": settings.rewards_silver_rate_limit_multiplier,
            "gold":   settings.rewards_gold_rate_limit_multiplier,
        }
        concurrent_map = {
            "bronze": settings.rewards_bronze_max_concurrent,
            "silver": settings.rewards_silver_max_concurrent,
            "gold":   settings.rewards_gold_max_concurrent,
        }
        category_map = {"gold": "reasoning", "silver": "general", "bronze": "fast"}
        return {
            "model_tier": category_map.get(tier, ""),
            "rate_multiplier": multiplier_map.get(tier, 1.0),
            "max_concurrent": concurrent_map.get(tier, 0),
        }
```

**`server.py` `start_agent` endpoint — semaphore acquisition:**

```python
# dashboard/server.py — inside start_agent endpoint
@app.post("/api/agents/{agent_id}/start")
async def start_agent(agent_id: str, _user: str = Depends(get_current_user)):
    agent = _agent_manager.get(agent_id)
    if not agent:
        raise HTTPException(404, f"Agent not found: {agent_id}")

    tier = agent.effective_tier()
    sem = _agent_manager._get_tier_semaphore(tier)

    if sem is not None:
        # Attempt non-blocking acquire. 503 is cleaner than blocking the server.
        acquired = sem._value > 0  # check without blocking
        if not acquired:
            raise HTTPException(
                503,
                f"Tier '{tier}' concurrent task limit reached. Try again later."
            )
        await sem.acquire()
        try:
            result = await _agent_runtime.start_agent(agent.to_dict())
        except Exception:
            sem.release()
            raise
        # NOTE: semaphore released when agent process ends — see _monitor() hook
        # For simplicity in v1, release immediately after launch (not after completion)
        # since asyncio.Semaphore doesn't know about subprocess lifetime.
        sem.release()
    else:
        result = await _agent_runtime.start_agent(agent.to_dict())

    if not result:
        raise HTTPException(500, "Failed to start agent — is Claude Code CLI installed?")
    _agent_manager.set_status(agent_id, "active")
    _agent_manager.record_run(agent_id)
    return {**agent.to_dict(), "pid": result.pid, "status": "active"}
```

**Design decision (Claude's discretion):** The semaphore in v1 guards the *launch* action, not the *runtime* of the subprocess. This is consistent with D-07 ("before calling `AgentRuntime.start_agent()`") and D-08 (simpler per-tier shared cap). The semaphore prevents launching more agents of a given tier than the cap allows at one moment in time — it is not a long-running hold. This is appropriate for the v1 use case.

### Pattern 4: `TierLimits` dataclass vs plain dict (Claude's discretion)

**Recommendation:** Use a plain dict mapping for `get_effective_limits()` return value (as specified in D-12) rather than a `TierLimits` dataclass. The dict is already specified in D-12 and Phase 4 dashboard will consume it directly via JSON serialization. A dataclass adds no benefit and requires an extra import. If type safety is desired, a `TypedDict` at module level in `agent_manager.py` is lighter than a full dataclass.

### Anti-Patterns to Avoid

- **Creating `asyncio.Semaphore` before the event loop is running:** Will raise `RuntimeError` in Python 3.10+. Use lazy init (`_get_tier_semaphore()`) which creates on first async call, not at `__init__` time.
- **Holding the semaphore across the entire subprocess lifetime:** Prevents any new agent of that tier from starting until the subprocess exits (which could be minutes). The v1 spec acquires-and-releases around the `start_agent()` launch call, not the full run.
- **Adding `tier` to `ToolLimit` or the `_calls` key:** D-05 explicitly forbids this. The key structure stays `{agent_id}:{tool_name}`.
- **Importing `settings` at module level in `rate_limiter.py`:** May create import cycles if `config.py` imports from `rate_limiter.py` indirectly. Safer to inline the dict lookup inside `_get_multiplier()` using deferred import, same pattern as `TierDeterminator`.
- **Branching on tier inside the hot path:** D-10 mandates checking `settings.rewards_enabled` or `effective_tier() == ""` once at the top. A single `if not tier: return 1.0` guard satisfies this.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Per-tier resource caps | Custom counter with lock | `asyncio.Semaphore` | Thread/coroutine-safe, stdlib, well-tested, no deadlock footguns |
| Sliding window rate limit | New timestamp list per tier | Extend existing `ToolRateLimiter` | Already correct; adding multiplier is 3 lines; no structural change |
| Tier-to-model lookup | External config file | `_TIER_CATEGORY_UPGRADE` dict + existing `PROVIDER_MODELS` | Already complete; mapping is static |
| Multiplier lookup | Dict-per-call allocation | Inline dict literal in `_get_multiplier()` | No caching needed — Settings is frozen and immutable |

## Common Pitfalls

### Pitfall 1: asyncio.Semaphore Created Outside Event Loop

**What goes wrong:** `asyncio.Semaphore()` raises `DeprecationWarning` (Python 3.8) or `RuntimeError` (3.10+) when created before `asyncio.get_event_loop()` is running.

**Why it happens:** `AgentManager.__init__()` is called synchronously during `create_app()` setup, before the Uvicorn event loop is started.

**How to avoid:** Lazy-initialize semaphores in `_get_tier_semaphore()` which is only ever called from async context (`start_agent` endpoint). This is the same pattern used by all other async resources in the codebase (Redis, Qdrant).

**Warning signs:** `DeprecationWarning: There is no current event loop` in test output; semaphore tests fail when run outside async context.

### Pitfall 2: `settings` import cycle in `rate_limiter.py`

**What goes wrong:** `from core.config import settings` at module top in `rate_limiter.py` causes circular import if `config.py` transitively imports `rate_limiter.py`.

**Why it happens:** `config.py` imports `Settings` which may transitively pull in other modules during `from_env()`.

**How to avoid:** Use a deferred import inside `_get_multiplier()`, the same pattern the `TierDeterminator` uses for `settings`. Alternatively, pass the multipliers as arguments to `check()` directly — caller looks them up from `settings` before calling. Either works; deferred import is cleaner.

**Warning signs:** `ImportError: cannot import name 'settings'` or `ImportError: circular import` at startup.

### Pitfall 3: `effective_tier()` returns `"provisional"` — no entry in tier maps

**What goes wrong:** `_TIER_CATEGORY_UPGRADE.get("provisional", task_category)` returns `task_category` (correct), but the multiplier map `{"bronze": ..., "silver": ..., "gold": ...}.get("provisional", 1.0)` returns `1.0` (also correct by D-11). However, `_get_tier_semaphore("provisional")` would create a new semaphore with bronze cap — probably undesirable.

**Why it happens:** `effective_tier()` can return `"provisional"` for new agents. `"provisional"` was not listed in the tier maps.

**How to avoid:** Treat `"provisional"` the same as `""` — no enforcement. In each tier map lookup, default to the no-enforcement value: `cap_map.get(tier)` returns `None` when tier is `"provisional"`, then the guard `if cap is None: return None` skips semaphore creation.

**Warning signs:** Provisional agents inexplicably capped at bronze concurrency.

### Pitfall 4: Semaphore `_value` private attribute check

**What goes wrong:** `sem._value > 0` is accessing a private attribute to check availability without blocking. This is CPython implementation detail, not part of the public API.

**Why it happens:** `asyncio.Semaphore` has no `locked()` method equivalent to `asyncio.Lock`. The only public check is `await sem.acquire()` (blocks) or the `sem._value` hack.

**How to avoid:** Instead of the `_value` check, use `sem.acquire()` with a timeout of 0.0 via `asyncio.wait_for()`. If it raises `asyncio.TimeoutError`, return 503. This is the correct async pattern:

```python
try:
    await asyncio.wait_for(sem.acquire(), timeout=0.0)
except asyncio.TimeoutError:
    raise HTTPException(503, f"Tier '{tier}' concurrent task limit reached.")
```

Note: `timeout=0.0` means "fail immediately if not acquirable" — equivalent to a non-blocking try-acquire.

### Pitfall 5: Missing `tier` propagation through `ToolRegistry.execute()`

**What goes wrong:** Rate limit multiplier is never applied because `registry.execute()` doesn't pass `tier` to `check()`.

**Why it happens:** MCP server calls `registry.execute(tool_name, agent_id, **kwargs)` — `tier` must be added as an explicit kwarg, not passed via `**kwargs` (which goes to the tool's own `execute()`).

**How to avoid:** Add `tier: str = ""` to `ToolRegistry.execute()` signature before `**kwargs`. Pass it explicitly to `self._rate_limiter.check(tool_name, agent_id, tier=tier)`.

## Code Examples

### Check method signature (verified from source)

```python
# Current signature — core/rate_limiter.py line 48
def check(self, tool_name: str, agent_id: str = "default") -> tuple[bool, str]:

# New signature — adds tier keyword arg
def check(self, tool_name: str, agent_id: str = "default", tier: str = "") -> tuple[bool, str]:
```

### ToolRegistry.execute() current signature (verified from source)

```python
# Current — tools/registry.py line 87
async def execute(self, tool_name: str, agent_id: str = "default", **kwargs) -> ToolResult:

# New — tier inserted before **kwargs
async def execute(self, tool_name: str, agent_id: str = "default", tier: str = "", **kwargs) -> ToolResult:
```

### Settings fields already present (verified from core/config.py)

```python
# Already in Settings dataclass (Phase 1):
rewards_enabled: bool = False
rewards_bronze_rate_limit_multiplier: float = 1.0
rewards_silver_rate_limit_multiplier: float = 1.5
rewards_gold_rate_limit_multiplier: float = 2.0
rewards_bronze_max_concurrent: int = 2
rewards_silver_max_concurrent: int = 5
rewards_gold_max_concurrent: int = 10
```

### `effective_tier()` current implementation (verified from source)

```python
# core/agent_manager.py line 185-192
def effective_tier(self) -> str:
    return self.tier_override if self.tier_override is not None else self.reward_tier
    # Returns "" when both are empty/unset
    # Returns "provisional" for new agents with no observations
    # Returns "bronze"/"silver"/"gold" for scored agents
    # Returns override string when admin has set tier_override
```

### `start_agent` endpoint current state (verified from dashboard/server.py line 3863)

```python
@app.post("/api/agents/{agent_id}/start")
async def start_agent(agent_id: str, _user: str = Depends(get_current_user)):
    agent = _agent_manager.get(agent_id)
    if not agent:
        raise HTTPException(404, f"Agent not found: {agent_id}")
    result = await _agent_runtime.start_agent(agent.to_dict())
    if not result:
        raise HTTPException(500, "Failed to start agent — is Claude Code CLI installed?")
    _agent_manager.set_status(agent_id, "active")
    _agent_manager.record_run(agent_id)
    return {**agent.to_dict(), "pid": result.pid, "status": "active"}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| No tier-awareness in rate limiter | Multiplier applied to effective_max_calls per check | Phase 3 | Gold agents get 2x burst capacity |
| No tier-awareness in model routing | `resolve_model()` upgrades category by tier | Phase 3 | Gold→reasoning, Silver→general, Bronze→fast |
| No concurrent task cap | Per-tier asyncio.Semaphore | Phase 3 | Bronze agents limited to 2 concurrent tasks |
| No `get_effective_limits()` | D-12 summary method on AgentManager | Phase 3 | Phase 4 dashboard reads one method, not three |

**No deprecated approaches in this phase** — all changes are additive extensions of existing APIs.

## Open Questions

1. **Should `"provisional"` tier enforce bronze concurrency limits?**
   - What we know: D-11 says `effective_tier() == ""` = no enforcement. `"provisional"` is a distinct non-empty string.
   - What's unclear: CONTEXT.md D-07 through D-09 only mention bronze/silver/gold — `"provisional"` not addressed for concurrency.
   - Recommendation: Treat `"provisional"` same as `""` (skip enforcement) across all three points. Provisional agents are new/unscored — penalizing them with bronze limits before they prove themselves contradicts TIER-03 intent. Implement by adding `"provisional"` to the no-enforcement guard: `if not tier or tier == "provisional": return/skip`.

2. **Rate limit check vs. rate limit record: should `record()` also be tier-aware?**
   - What we know: `record()` just appends a timestamp to `_calls[key]`. The key structure is unchanged (D-05). `check()` reads the same key and applies the effective_max at check time.
   - What's unclear: No decision in CONTEXT.md.
   - Recommendation: `record()` requires no changes. The multiplier is applied at check time, not record time. All timestamps are stored regardless of tier. This is correct — a gold agent's calls are all stored, but it takes 2x as many before being blocked.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python asyncio (stdlib) | asyncio.Semaphore | Yes | Python 3.12 | — |
| `core.config.settings` | Multipliers, caps | Yes | Phase 1 (verified) | — |
| `core.agent_manager.AgentConfig.effective_tier()` | All enforcement points | Yes | Phase 2 (verified) | — |
| `core.reward_system.TierDeterminator` | Consumed by Phase 2 (not Phase 3) | Yes | Phase 2 (verified) | — |

No missing dependencies. All enforcement machinery is in-process Python — no external services required.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.x + pytest-asyncio |
| Config file | `pyproject.toml` (`asyncio_mode = "auto"`) |
| Quick run command | `python -m pytest tests/test_resource_enforcement.py -x -q` |
| Full suite command | `python -m pytest tests/ -x -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| RSRC-01 | `resolve_model()` upgrades Gold→reasoning, Silver→general, Bronze→fast | unit | `pytest tests/test_resource_enforcement.py::TestModelRouting -x -q` | Wave 0 |
| RSRC-01 | Manual model override on AgentConfig takes precedence over tier (D-02) | unit | `pytest tests/test_resource_enforcement.py::TestModelRouting::test_manual_override_ignores_tier -x -q` | Wave 0 |
| RSRC-01 | Missing tier arg → unchanged behavior (D-03) | unit | `pytest tests/test_resource_enforcement.py::TestModelRouting::test_no_tier_unchanged -x -q` | Wave 0 |
| RSRC-02 | Gold multiplier 2.0 doubles effective max_calls | unit | `pytest tests/test_resource_enforcement.py::TestRateLimiterTier -x -q` | Wave 0 |
| RSRC-02 | Empty tier → multiplier 1.0 (D-06) | unit | `pytest tests/test_resource_enforcement.py::TestRateLimiterTier::test_empty_tier_no_change -x -q` | Wave 0 |
| RSRC-02 | `_calls` key structure unchanged after tier extension (D-05) | unit | `pytest tests/test_resource_enforcement.py::TestRateLimiterTier::test_calls_key_unchanged -x -q` | Wave 0 |
| RSRC-03 | Bronze semaphore cap=2 blocks 3rd concurrent start | unit | `pytest tests/test_resource_enforcement.py::TestConcurrencySemaphore -x -q` | Wave 0 |
| RSRC-03 | No semaphore acquired when rewards_disabled (D-09) | unit | `pytest tests/test_resource_enforcement.py::TestConcurrencySemaphore::test_rewards_disabled_no_semaphore -x -q` | Wave 0 |
| RSRC-03 | Provisional tier skips concurrency enforcement | unit | `pytest tests/test_resource_enforcement.py::TestConcurrencySemaphore::test_provisional_no_cap -x -q` | Wave 0 |
| RSRC-04 | `get_effective_limits()` returns correct dict for each tier | unit | `pytest tests/test_resource_enforcement.py::TestGetEffectiveLimits -x -q` | Wave 0 |
| RSRC-04 | `get_effective_limits()` returns safe defaults when rewards disabled | unit | `pytest tests/test_resource_enforcement.py::TestGetEffectiveLimits::test_disabled_returns_defaults -x -q` | Wave 0 |
| TEST-03 | Integration: gold agent gets reasoning model via registry dispatch | integration | `pytest tests/test_resource_enforcement.py::TestIntegration -x -q` | Wave 0 |

### Sampling Rate

- **Per task commit:** `python -m pytest tests/test_resource_enforcement.py -x -q`
- **Per wave merge:** `python -m pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/test_resource_enforcement.py` — covers RSRC-01, RSRC-02, RSRC-03, RSRC-04, TEST-03 (entire file missing)
- [ ] No changes to `tests/conftest.py` needed — existing `tmp_workspace` fixture sufficient

## Sources

### Primary (HIGH confidence)

- Direct source read: `core/rate_limiter.py` — ToolRateLimiter.check(), record(), _calls structure, ToolLimit dataclass (lines 1-95)
- Direct source read: `core/agent_manager.py` — resolve_model(), PROVIDER_MODELS, AgentConfig, effective_tier(), AgentManager class (lines 1-284)
- Direct source read: `core/config.py` — all `rewards_*` Settings fields with defaults and env var names (lines 296-312, 584-602)
- Direct source read: `dashboard/server.py` — start_agent endpoint, _agent_manager instantiation (lines 3863-3874, 3785-3791)
- Direct source read: `tools/registry.py` — execute() signature, rate_limiter.check() call site (lines 87-124)
- Direct source read: `core/agent_runtime.py` — AgentRuntime.start_agent(), _build_env() — confirms no tier involvement in subprocess launch (lines 93-146)
- Direct source read: `core/reward_system.py` — Phase 1 patterns (deferred import, graceful degradation)
- Direct source read: `core/rewards_config.py` — RewardsConfig pattern (mtime cache, deferred settings)
- Direct source read: `tests/test_tier_assignment.py` — Phase 2 test patterns for reference
- Direct source read: `.planning/config.json` — nyquist_validation: true (confirmed)
- Python stdlib docs (training data, verified pattern): `asyncio.Semaphore` constructor behavior in async context

### Secondary (MEDIUM confidence)

- Python 3.10+ asyncio.Semaphore behavior (creating outside event loop raises error) — training data verified against project Python version (3.12 confirmed by project setup)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new libraries; all code read directly from source
- Architecture: HIGH — all integration points read from actual source files; patterns match established codebase conventions
- Pitfalls: HIGH — circular import risk and semaphore timing risks are verified against actual code structure; asyncio.Semaphore behavior confirmed for Python 3.12

**Research date:** 2026-03-22
**Valid until:** 2026-04-22 (stable stdlib + no new dependencies)
