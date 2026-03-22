# Phase 3: Resource Enforcement - Context

**Gathered:** 2026-03-22 (assumptions mode)
**Status:** Ready for planning

<domain>
## Phase Boundary

Tier labels produce real resource differences — higher-tier agents access better model classes, benefit from higher rate limit multipliers, and can run more concurrent tasks — while all enforcement reads from a single O(1) AgentConfig field and never touches the database on the routing hot path. No dashboard changes, no new API endpoints.

</domain>

<decisions>
## Implementation Decisions

### Model Routing
- **D-01:** Augment existing `resolve_model(provider, task_category)` in `core/agent_manager.py` with an optional `tier` parameter. Higher tiers get upgraded task categories: Gold→`"reasoning"`, Silver→`"general"`, Bronze→`"fast"`. Reuses existing `PROVIDER_MODELS` columns.
- **D-02:** Precedence: manual per-agent model override (stored on AgentConfig.model) > tier-based upgrade > global default. If agent has an explicit model set, tier does not override it.
- **D-03:** `resolve_model()` call sites that don't pass `tier` get unchanged behavior (backwards compatible).

### Rate Limit Enforcement
- **D-04:** Extend `ToolRateLimiter.check()` in `core/rate_limiter.py` to accept tier and apply multiplier. Scale `ToolLimit.max_calls` by tier multiplier before the sliding-window comparison. Multipliers from `Settings`: bronze=1.0, silver=1.5, gold=2.0.
- **D-05:** The `_calls` dict remains keyed by `{agent_id}:{tool_name}` — no structural change. Only the effective max_calls changes per tier.
- **D-06:** When tier is empty string or None, multiplier defaults to 1.0 (no change from pre-rewards behavior).

### Concurrent Task Enforcement
- **D-07:** Per-tier concurrent task limits enforced via `asyncio.Semaphore` acquired in `server.py` `start_agent` endpoint before calling `AgentRuntime.start_agent()`. Caps from Settings: bronze=2, silver=5, gold=10.
- **D-08:** Semaphore capacity per tier stored as a dict on `AgentManager` (keyed by tier string). Per-tier shared limit — all agents of same tier share the same cap. Simpler than per-agent semaphores.
- **D-09:** When rewards disabled or tier is empty, no semaphore acquired (unlimited, matching pre-rewards behavior).

### Rewards-Disabled Fallback
- **D-10:** All three enforcement points check `settings.rewards_enabled` (or `effective_tier() == ""`) at the top — single check, no branching inside hot paths. Empty-string tier = "no tier" = skip enforcement.
- **D-11:** `AgentConfig.effective_tier()` returns `""` when no tier assigned. All enforcement code must handle this case explicitly (no KeyError on empty-string lookup).

### AgentManager Integration
- **D-12:** `AgentManager.get_effective_limits(agent_id) -> dict` method returns `{"model_tier": str, "rate_multiplier": float, "max_concurrent": int}` by reading `effective_tier()` and mapping to Settings values. This is the single query point for Phase 4 dashboard as well.

### Claude's Discretion
- Whether to add a `TierLimits` frozen dataclass or use a simple dict mapping
- Exact error handling when semaphore acquisition times out (if applicable)
- Whether to log tier-based routing decisions at DEBUG level

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Rate limiter
- `core/rate_limiter.py` — ToolRateLimiter class, check() method, _calls dict, ToolLimit dataclass

### Model routing
- `core/agent_manager.py` — resolve_model() function, PROVIDER_MODELS dict, AgentConfig with effective_tier()

### Agent execution dispatch
- `dashboard/server.py` — start_agent endpoint (line ~3863), where agents are launched
- `core/agent_runtime.py` — AgentRuntime.start_agent(), _build_env()

### Config values
- `core/config.py` — Settings with reward_tier_*_rate_multiplier, reward_tier_*_max_concurrent fields

### Phase 1+2 output
- `core/reward_system.py` — RewardSystem, TierDeterminator, TierRecalcLoop
- `tests/test_tier_assignment.py` — Phase 2 tests (21 tests)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `ToolRateLimiter.check(tool_name, agent_id)` — already has agent_id, sliding window with time.monotonic()
- `resolve_model(provider, task_category)` — single dispatch point for model selection
- `AgentConfig.effective_tier()` — O(1) tier read, returns override or computed tier
- `Settings` per-tier fields — multipliers and caps already defined in Phase 1

### Established Patterns
- `ToolLimit` dataclass for rate limit configuration
- `PROVIDER_MODELS` dict with `"fast"`, `"general"`, `"reasoning"` columns
- `asyncio.Semaphore` not yet used in codebase — new pattern for concurrency
- `settings.rewards_enabled` as gate — established in Phase 1

### Integration Points
- `core/rate_limiter.py` check() — add tier multiplier parameter
- `core/agent_manager.py` resolve_model() — add tier parameter
- `dashboard/server.py` start_agent — add semaphore acquisition
- `core/agent_manager.py` — add get_effective_limits() method

</code_context>

<specifics>
## Specific Ideas

No specific requirements — implementation follows directly from Phase 1+2 decisions and existing codebase patterns.

</specifics>

<deferred>
## Deferred Ideas

- Dashboard REST API for tier/limits display — Phase 4
- Dashboard UI for tier badges and metrics — Phase 4
- Per-agent semaphore swap-on-promotion — v2 (per-tier shared is simpler for v1)
- Model routing audit log — v2

### Reviewed Todos (not folded)
None — no matching todos found.

</deferred>

---

*Phase: 03-resource-enforcement*
*Context gathered: 2026-03-22*
