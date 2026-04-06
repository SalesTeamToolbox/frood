# Phase 26: Tiered Routing Bridge - Research

**Researched:** 2026-03-29
**Domain:** Python dataclass bridge pattern, async tier lookup, static role mapping, per-token cost estimation
**Confidence:** HIGH — all key components are existing in-codebase; this phase wires them together

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Static dict constant in TieredRoutingBridge class maps Paperclip roles to Agent42 task categories: engineer→coding, researcher→research, writer→content, analyst→strategy. No runtime configuration needed.
- **D-02:** Unknown or missing roles fall back to `general` task category — never error on unrecognized roles.
- **D-03:** Base roles only — no prefix-tolerant matching (e.g., no stripping of 'senior_', 'lead_'). Paperclip's role field is a known enum.
- **D-04:** TieredRoutingBridge queries `RewardSystem.score(agent_id)` then `TierDeterminator.determine(score, obs_count)` to get the agent's tier (gold/silver/bronze/provisional).
- **D-05:** Tier upgrade uses existing `resolve_model(provider, task_category, tier)` from `core/agent_manager.py` — gold→reasoning, silver→general, bronze→fast. No new upgrade logic needed.
- **D-06:** Resolution order: (1) `AdapterConfig.preferredProvider` if set → use as provider; (2) otherwise → `synthetic` (L1 workhorse) as default; (3) fall back to `anthropic` if synthetic key is missing.
- **D-07:** If preferredProvider is set but doesn't support the tier-upgraded category, fall back to `general` category on that same provider — `resolve_model()` already does this fallback.
- **D-08:** Default provider is `synthetic` (StrongWall/L1 workhorse per PROJECT.md Core Value).
- **D-09:** Wire the plumbing now, populate with real values later — TieredRoutingBridge resolves model+provider and writes them into the usage dict. Token counts and costUsd stay 0 until AgentRuntime is wired in Phase 27+.
- **D-10:** Include a static pricing lookup table (model ID → per-token input/output costs) in the bridge. When real token counts flow from AgentRuntime, costUsd = input_tokens * input_price + output_tokens * output_price. Follows SpendingTracker pattern in server.py.
- **D-11:** New `TieredRoutingBridge` class in `core/tiered_routing_bridge.py` following the MemoryBridge pattern — dedicated class wrapping RewardSystem + resolve_model(), clean testable API.
- **D-12:** Bridge API: `resolve(role, agent_id, preferred_provider) → RoutingDecision(provider, model, tier, task_category, cost_estimate)`.
- **D-13:** Bridge is internal-only for this phase — called by SidecarOrchestrator.execute_async(), no HTTP endpoint. Plugin gets routing via `route_task` tool in Phase 28 (PLUG-04).
- **D-14:** SidecarOrchestrator already receives `reward_system` in constructor — pass it through to TieredRoutingBridge, or inject bridge directly (same pattern as memory_bridge injection).

### Claude's Discretion

- Exact field names for RoutingDecision dataclass
- Whether TieredRoutingBridge receives RewardSystem directly or accesses it through SidecarOrchestrator
- Pricing table values (per-model token costs)
- Logging format for routing decisions in sidecar structured JSON logs
- Whether to add a `POST /routing/resolve` endpoint later (deferred to Phase 28)

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope.
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| ROUTE-01 | TieredRoutingBridge maps Paperclip agent roles (engineer/researcher/writer/analyst) to Agent42 task categories | D-01/D-02/D-03: static dict in bridge class; TaskType enum in core/task_types.py defines valid category strings |
| ROUTE-02 | Routing bridge queries RewardSystem for agent tier and upgrades model selection accordingly | D-04/D-05: RewardSystem.score() + TierDeterminator.determine() + resolve_model() — all exist; bridge composes them |
| ROUTE-03 | AdapterConfig.preferredProvider overrides default provider selection when set | D-06/D-07: AdapterConfig.preferred_provider already parsed from payload; resolve_model() handles unknown categories via general fallback |
| ROUTE-04 | Routing bridge reports costUsd, usage tokens, model, and provider in callback response for Paperclip budget tracking | D-09/D-10: model+provider populated now; token counts and costUsd = 0 until AgentRuntime wired; static pricing table ready for Phase 27 |
</phase_requirements>

---

## Summary

Phase 26 is a composition phase, not an invention phase. All the individual pieces exist in the codebase — `resolve_model()`, `_TIER_CATEGORY_UPGRADE`, `RewardSystem.score()`, `TierDeterminator.determine()`, `AdapterConfig.preferred_provider`, `CallbackPayload.usage` — and this phase wires them into a single `TieredRoutingBridge` class that `SidecarOrchestrator.execute_async()` calls between memory recall (Step 1) and the execution stub (Step 2).

The MemoryBridge in `core/memory_bridge.py` is the direct architectural template: a `core/*.py` dedicated class, constructed in `create_sidecar_app()`, injected into `SidecarOrchestrator`. `TieredRoutingBridge` follows this exact pattern. The bridge wraps RewardSystem and resolve_model(), exposes a single `resolve()` method that returns a `RoutingDecision` dataclass, and writes `provider`, `model` fields into the `usage` dict that flows into `CallbackPayload`.

Cost reporting is a two-phase design (D-09/D-10): Phase 26 resolves model and provider into the usage dict and includes a static pricing table (model_id → (input_per_token, output_per_token)), but sets token counts and `costUsd` to 0 until AgentRuntime is wired in Phase 27+. The pricing table structure mirrors the server.py `_model_prices` dict pattern.

**Primary recommendation:** Follow MemoryBridge verbatim for class structure; compose RewardSystem + TierDeterminator + resolve_model() into a clean `resolve()` method; populate usage dict in execute_async() immediately after memory recall; write full test coverage for all four ROUTE-xx requirements.

---

## Standard Stack

### Core (already installed — no new packages needed)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib `dataclasses` | 3.14.3 | `RoutingDecision` dataclass | Used throughout codebase (AgentConfig, ScoreWeights, TierEntry) |
| `core.reward_system` | in-repo | RewardSystem.score(), TierDeterminator | Already exists, tested, rewards-disabled graceful degradation built in |
| `core.agent_manager` | in-repo | resolve_model(), _TIER_CATEGORY_UPGRADE, PROVIDER_MODELS | All routing logic already here — bridge wraps, does not replace |
| `core.sidecar_models` | in-repo | AdapterConfig, CallbackPayload, AdapterExecutionContext | Pydantic v2 models for all sidecar I/O |
| `core.task_types` | in-repo | TaskType enum — valid category strings | Canonical task category reference |

### No new dependencies

The `requirements.txt` does not need updating. This phase is pure Python composition of existing in-repo modules.

---

## Architecture Patterns

### MemoryBridge Pattern (direct template for TieredRoutingBridge)

The MemoryBridge class (`core/memory_bridge.py`) is the established pattern for Phase 25+ bridge classes:

```
core/tiered_routing_bridge.py   # New — mirrors core/memory_bridge.py
dashboard/sidecar.py             # Modified — construct TieredRoutingBridge, inject into orchestrator
core/sidecar_orchestrator.py     # Modified — add tiered_routing_bridge param, call resolve() between Step 1 and Step 2
```

**Construction site:** `create_sidecar_app()` in `dashboard/sidecar.py` constructs one `TieredRoutingBridge` instance and passes it to `SidecarOrchestrator`. One instance shared across all requests (same as `memory_bridge`).

**Injection site:** `SidecarOrchestrator.__init__()` gets a `tiered_routing_bridge` parameter alongside existing `memory_bridge`.

**Call site:** `execute_async()` between the memory recall block (Step 1) and the execution stub (Step 2), before building the `usage` dict.

### RoutingDecision Dataclass

Recommended field names (Claude's discretion):

```python
# Source: core/tiered_routing_bridge.py
from dataclasses import dataclass

@dataclass
class RoutingDecision:
    provider: str          # e.g. "synthetic", "anthropic"
    model: str             # resolved model ID
    tier: str              # "gold" / "silver" / "bronze" / "provisional" / ""
    task_category: str     # final effective category after tier upgrade
    base_category: str     # category from role mapping before upgrade
    cost_estimate: float   # 0.0 until AgentRuntime wired (Phase 27+)
```

`base_category` is separate from `task_category` to make the tier-upgrade effect observable in logs (success criterion 2 requires this to be observable).

### Role-to-Category Mapping

```python
# Source: core/tiered_routing_bridge.py — D-01, D-02, D-03
_ROLE_CATEGORY_MAP: dict[str, str] = {
    "engineer": "coding",
    "researcher": "research",
    "writer": "content",
    "analyst": "strategy",
}

def _role_to_category(self, role: str) -> str:
    return _ROLE_CATEGORY_MAP.get(role or "", "general")  # D-02: unknown -> general
```

Note: `strategy` maps to `analyst` but `PROVIDER_MODELS["synthetic"]` does not have a `strategy` key. `resolve_model()` falls back to `general` for unmapped categories on a provider — this is the intended D-07 behavior. Verify `strategy` is the intended mapping and that the general-fallback behavior is acceptable for the analyst role.

### Provider Selection Chain

```python
# D-06: Resolution order
def _resolve_provider(self, preferred_provider: str) -> str:
    if preferred_provider:
        return preferred_provider                # (1) explicit override
    if os.environ.get("SYNTHETIC_API_KEY"):
        return "synthetic"                       # (2) L1 workhorse default
    return "anthropic"                           # (3) fallback if key missing
```

Key insight: `resolve_model()` in `agent_manager.py` already handles the case where a provider doesn't have a specific category by falling back to `general`, and falls back to the `anthropic` provider dict if the requested provider is entirely unknown:

```python
# From core/agent_manager.py (verified)
def resolve_model(provider: str, task_category: str, tier: str = "") -> str:
    effective_category = _TIER_CATEGORY_UPGRADE.get(tier, task_category)
    models = PROVIDER_MODELS.get(provider, PROVIDER_MODELS.get("anthropic", {}))
    return models.get(effective_category, models.get("general", "claude-sonnet-4-6"))
```

The bridge does NOT need to duplicate this fallback logic — `resolve_model()` already handles it.

### Tier Lookup Sequence

```python
# D-04: score() is async; TierDeterminator.determine() is sync
async def resolve(self, role: str, agent_id: str, preferred_provider: str = "") -> RoutingDecision:
    # 1. Tier determination (gracefully degraded when rewards disabled)
    score = await self._reward_system.score(agent_id)  # returns 0.0 if disabled
    obs_count = self._get_observation_count(agent_id)  # see pitfall below
    tier = self._tier_determinator.determine(score, obs_count)

    # 2. Role → category
    base_category = _role_to_category(role)

    # 3. Provider selection
    provider = _resolve_provider(preferred_provider)

    # 4. resolve_model handles tier upgrade + category fallback
    model = resolve_model(provider, base_category, tier)

    # 5. Determine effective category for logging
    effective_category = _TIER_CATEGORY_UPGRADE.get(tier, base_category)

    return RoutingDecision(
        provider=provider,
        model=model,
        tier=tier,
        task_category=effective_category,
        base_category=base_category,
        cost_estimate=0.0,  # D-09: wired in Phase 27+
    )
```

### Usage Dict Population in execute_async()

```python
# In SidecarOrchestrator.execute_async() — between Step 1 and Step 2 stub
routing: RoutingDecision | None = None
if self.tiered_routing_bridge and ctx.agent_id:
    try:
        routing = await self.tiered_routing_bridge.resolve(
            role=ctx.context.get("agentRole", ""),
            agent_id=ctx.agent_id,
            preferred_provider=ctx.adapter_config.preferred_provider,
        )
        logger.info(
            "Routing run %s: agent=%s role=%s tier=%s provider=%s model=%s base_cat=%s cat=%s",
            run_id, ctx.agent_id,
            ctx.context.get("agentRole", ""),
            routing.tier, routing.provider, routing.model,
            routing.base_category, routing.task_category,
        )
    except Exception as exc:
        logger.warning("Routing resolution failed for run %s: %s — using defaults", run_id, exc)

# Build usage dict (D-09: model+provider populated; tokens = 0 until Phase 27+)
usage = {
    "inputTokens": 0,
    "outputTokens": 0,
    "costUsd": 0.0,
    "model": routing.model if routing else "",
    "provider": routing.provider if routing else "",
}
```

### Static Pricing Table Pattern (D-10)

The server.py `_StubTracker._model_prices` is currently empty (SpendingTracker was removed in v2.0). The bridge should include a static pricing table as a class constant for use when AgentRuntime wires real token counts:

```python
# Per-token costs: (input_per_token_usd, output_per_token_usd)
# Values based on published pricing as of 2026-03-29
_MODEL_PRICING: dict[str, tuple[float, float]] = {
    # Anthropic
    "claude-haiku-4-5-20251001":          (0.80 / 1_000_000,   4.00 / 1_000_000),
    "claude-sonnet-4-6-20260217":         (3.00 / 1_000_000,  15.00 / 1_000_000),
    "claude-opus-4-6-20260205":           (15.00 / 1_000_000, 75.00 / 1_000_000),
    # Synthetic (StrongWall — pricing TBD; use conservative fallback)
    "hf:zai-org/GLM-4.7-Flash":           (0.10 / 1_000_000,   0.30 / 1_000_000),
    "hf:zai-org/GLM-4.7":                 (0.50 / 1_000_000,   1.50 / 1_000_000),
    "hf:moonshotai/Kimi-K2-Thinking":     (2.00 / 1_000_000,   8.00 / 1_000_000),
    "hf:Qwen/Qwen3-Coder-480B-A35B-Instruct": (1.00 / 1_000_000, 3.00 / 1_000_000),
    "hf:Qwen/Qwen3.5-397B-A17B":          (1.00 / 1_000_000,   3.00 / 1_000_000),
    "hf:moonshotai/Kimi-K2.5":            (1.00 / 1_000_000,   3.00 / 1_000_000),
    "hf:deepseek-ai/DeepSeek-R1-0528":    (2.00 / 1_000_000,   8.00 / 1_000_000),
    "hf:meta-llama/Llama-3.3-70B-Instruct": (0.30 / 1_000_000, 0.80 / 1_000_000),
    "hf:MiniMaxAI/MiniMax-M2.5":          (0.50 / 1_000_000,   1.50 / 1_000_000),
    # OpenRouter
    "google/gemini-2.0-flash-001":        (0.10 / 1_000_000,   0.40 / 1_000_000),
    "anthropic/claude-sonnet-4-6":        (3.00 / 1_000_000,  15.00 / 1_000_000),
    "anthropic/claude-opus-4-6":          (15.00 / 1_000_000, 75.00 / 1_000_000),
}
_PRICING_FALLBACK: tuple[float, float] = (5.00 / 1_000_000, 15.00 / 1_000_000)  # conservative

def estimate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
    price = _MODEL_PRICING.get(model, _PRICING_FALLBACK)
    return round(input_tokens * price[0] + output_tokens * price[1], 8)
```

### Anti-Patterns to Avoid

- **Do not copy `_TIER_CATEGORY_UPGRADE` or `PROVIDER_MODELS` into the bridge.** Import and call `resolve_model()` directly — it owns that mapping.
- **Do not create a new AgentManager reference** to look up `effective_tier()`. The bridge uses `RewardSystem.score()` + `TierDeterminator.determine()` per D-04, not `AgentConfig.effective_tier()`. The `tier_override` path in AgentConfig is for dashboard agents, not sidecar agents with Paperclip-provided agent_ids.
- **Do not block execute_async() for slow tier lookups.** If `RewardSystem.score()` is slow (cold cache, EffectivenessStore query), it still runs in the async path — but the bridge call should be wrapped in a try/except like memory recall so it degrades gracefully.
- **Do not report Paperclip's budget to Agent42.** P3 in PITFALLS.md is explicit: Agent42 reports costs TO Paperclip, does not enforce its own limits in sidecar mode.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Tier → model category mapping | Custom dict | `_TIER_CATEGORY_UPGRADE` + `resolve_model()` in `core/agent_manager.py` | Already tested, handles gold→reasoning, silver→general, bronze→fast, empty→passthrough |
| Provider → model resolution with fallbacks | Custom lookup | `resolve_model(provider, category, tier)` | Already handles unknown provider (falls back to anthropic), unknown category (falls back to general), tier upgrade in one call |
| Agent performance score | Custom scoring | `RewardSystem.score(agent_id)` | Already computes composite score, caches it, no-ops when disabled |
| Tier determination | Custom threshold logic | `TierDeterminator.determine(score, obs_count)` | Already reads `RewardsConfig` thresholds, handles provisional for new agents |

**Key insight:** This phase is almost entirely composition. New code should be < 150 lines in `core/tiered_routing_bridge.py`, with most logic delegated to existing functions.

---

## Common Pitfalls

### Pitfall 1: observation_count for TierDeterminator

**What goes wrong:** `TierDeterminator.determine(score, obs_count)` needs the observation count to avoid prematurely assigning Bronze to a new agent. The RewardSystem doesn't directly expose obs_count — it only exposes `score()` and `get_cached_score()`.

**Why it happens:** The obs_count comes from `EffectivenessStore.get_agent_stats(agent_id)["task_volume"]`, which `RewardSystem.score()` queries internally but does not return to the caller.

**How to avoid:** Two options:
1. Call `effectiveness_store.get_agent_stats(agent_id)` directly in the bridge (requires passing `effectiveness_store` into TieredRoutingBridge).
2. Pass `obs_count=0` as a safe default — `TierDeterminator` returns "provisional" when count < `settings.rewards_min_observations` (default 10), which means the agent gets no upgrade. This is safe-by-default and prevents false Bronze assignments.

**Recommendation (Claude's discretion):** Use option 2 (pass `obs_count=0`) for simplicity. A new sidecar agent without observation history gets provisional tier (no upgrade). This matches the existing TierRecalcLoop behavior where new agents start provisional.

**Warning signs:** If all sidecar agents stay "provisional" permanently, the obs_count source needs to be wired from EffectivenessStore.

### Pitfall 2: `strategy` category not in PROVIDER_MODELS["synthetic"]

**What goes wrong:** The analyst→strategy mapping hits a category (`strategy`) not present in `PROVIDER_MODELS["synthetic"]`. The `resolve_model()` fallback applies, returning the `general` model. This is silent — no error, but the log shows `task_category=strategy` while the resolved model is the `general` one.

**Why it happens:** `PROVIDER_MODELS["synthetic"]` has specific keys (fast, general, reasoning, coding, content, research, monitoring, marketing, analysis, lightweight) but not `strategy`. `analyst→strategy` was chosen in D-01 for semantic clarity, but `strategy` has no dedicated model.

**How to avoid:** Accept the fallback behavior (D-07 explicitly covers this: "fall back to `general` category on that same provider"). Document in the code that `strategy` resolves via general-fallback on synthetic. The log line captures this for observability (success criterion 1).

**Warning signs:** If operators expect `analyst` to get a reasoning model, consider mapping analyst→reasoning directly. But this is a product decision, not a code bug.

### Pitfall 3: RewardSystem disabled when `REWARDS_ENABLED=false`

**What goes wrong:** `RewardSystem.score()` returns 0.0 when disabled. `TierDeterminator.determine(0.0, 0)` returns "provisional". The `_TIER_CATEGORY_UPGRADE` dict does not contain "provisional" — the original `task_category` is used unchanged. The routing decision silently skips the tier upgrade. This is correct behavior, but tests that assume a specific tier when rewards are disabled will fail.

**How to avoid:** Tests for ROUTE-02 must cover the `rewards_disabled` case explicitly: verify that when RewardSystem returns 0.0, the RoutingDecision.tier = "provisional" and task_category = base_category (no upgrade applied).

**Warning signs:** A test that mocks `reward_system.score()` to return 0.9 expecting gold upgrade but forgets to check `TierDeterminator` with `obs_count=0` will get "provisional" instead.

### Pitfall 4: `context.get("agentRole", "")` key name

**What goes wrong:** The Paperclip `AdapterExecutionContext.context` is a free-form dict. The key for the agent's role is not standardized in the payload spec — it may be `agentRole`, `role`, `agent_role`, or absent.

**How to avoid:** The CONTEXT.md references Paperclip's known enum roles (engineer/researcher/writer/analyst). Check the actual key name used in Phase 24's AdapterExecutionContext parsing. If the context dict key is not yet established, use `agentRole` as the default with a comment that it must be verified against the actual Paperclip payload shape in Phase 27 integration testing.

**Warning signs:** If every run gets role="" and falls back to "general", the key name is wrong.

### Pitfall 5: P3 (Duplicate Budget Tracking)

**What goes wrong:** The bridge includes a pricing table and can compute `costUsd`. If this value is also tracked locally by any Agent42 spending mechanism, costs will be double-counted from Paperclip's perspective.

**How to avoid:** Per PITFALLS.md P3: in sidecar mode, cost data is reported TO Paperclip in the callback payload — Agent42 does not enforce its own budget limits. The `costUsd` in the callback is Paperclip's source of truth; Agent42 must not also debit it locally.

---

## Code Examples

### Bridge Construction in create_sidecar_app()

```python
# Source: dashboard/sidecar.py — following MemoryBridge pattern (Phase 25)
from core.tiered_routing_bridge import TieredRoutingBridge
from core.reward_system import TierDeterminator

# Construct once, share between orchestrator requests
tiered_routing_bridge = TieredRoutingBridge(
    reward_system=reward_system,
    tier_determinator=TierDeterminator(),
)

orchestrator = SidecarOrchestrator(
    memory_store=memory_store,
    agent_manager=agent_manager,
    effectiveness_store=effectiveness_store,
    reward_system=reward_system,
    memory_bridge=memory_bridge,
    tiered_routing_bridge=tiered_routing_bridge,   # new param
)
```

### SidecarOrchestrator.__init__() signature change

```python
# Source: core/sidecar_orchestrator.py
def __init__(
    self,
    memory_store: Any = None,
    agent_manager: Any = None,
    effectiveness_store: Any = None,
    reward_system: Any = None,
    memory_bridge: Any = None,
    tiered_routing_bridge: Any = None,   # new — D-14
):
    ...
    self.tiered_routing_bridge = tiered_routing_bridge
```

### Graceful degradation pattern (mirrors memory recall pattern)

```python
# Source: core/sidecar_orchestrator.py execute_async()
routing: Any = None
if self.tiered_routing_bridge and ctx.agent_id:
    try:
        routing = await self.tiered_routing_bridge.resolve(
            role=ctx.context.get("agentRole", ""),
            agent_id=ctx.agent_id,
            preferred_provider=ctx.adapter_config.preferred_provider,
        )
    except Exception as exc:
        logger.warning(
            "Routing resolution failed for run %s: %s — using defaults",
            run_id, exc,
        )
```

### Test pattern (mirrors test_memory_bridge.py)

```python
# Source: tests/test_tiered_routing_bridge.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from core.tiered_routing_bridge import TieredRoutingBridge, RoutingDecision

@pytest.fixture
def mock_reward_system():
    rs = MagicMock()
    rs.is_enabled = True
    rs.score = AsyncMock(return_value=0.9)  # gold
    return rs

@pytest.fixture
def bridge(mock_reward_system):
    from core.reward_system import TierDeterminator
    return TieredRoutingBridge(
        reward_system=mock_reward_system,
        tier_determinator=TierDeterminator(),
    )

@pytest.mark.asyncio
async def test_engineer_role_routes_to_coding(bridge, mock_reward_system):
    # obs_count=0 → provisional (no upgrade) with default approach
    decision = await bridge.resolve(role="engineer", agent_id="agent-abc")
    assert decision.base_category == "coding"

@pytest.mark.asyncio
async def test_gold_tier_upgrades_to_reasoning(bridge, mock_reward_system):
    # Need obs_count >= min_observations for gold tier
    # If using obs_count=0 default: tier=provisional, no upgrade
    # Test documents behavior accurately
    pass
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Direct model string in AgentConfig | `resolve_model(provider, category, tier)` function | Rewards phase | All tier-based routing must go through resolve_model, never hardcode model strings |
| SpendingTracker class | Stub (removed v2.0) | v2.0 | No active spending enforcement in sidecar; pricing table must be in bridge |
| Task queue (removed v3.0) | AgentRuntime subprocess | v3.0 | Token counts come from AgentRuntime; Phase 26 uses 0 as placeholder |

---

## Open Questions

1. **observation_count source for TierDeterminator**
   - What we know: `TierDeterminator.determine(score, obs_count)` returns "provisional" when obs_count < settings.rewards_min_observations (default 10). Using obs_count=0 is safe-by-default.
   - What's unclear: Should the bridge query EffectivenessStore directly to get real obs_count, enabling genuine tier assignments for established sidecar agents?
   - Recommendation: Use obs_count=0 in Phase 26 (provisional for new agents). In Phase 27, when EffectivenessStore is more deeply integrated, wire real obs_count. Document the limitation in a TODO comment.

2. **`agentRole` key in AdapterExecutionContext.context dict**
   - What we know: The context field is a free-form `dict[str, Any]`. Paperclip's heartbeat payload structure is documented in FEATURES.md but does not specify role key name.
   - What's unclear: Is the key `agentRole`, `role`, `agent_role`, or something else? This must match what Paperclip sends.
   - Recommendation: Use `agentRole` as the key (camelCase matches Paperclip's JSON convention), add a comment that Phase 27 integration testing must verify this key name against a real Paperclip heartbeat payload.

3. **`analyst` → `strategy` category and general fallback**
   - What we know: `PROVIDER_MODELS["synthetic"]` has no `strategy` key. `resolve_model()` falls back to `general` silently. D-07 explicitly allows this.
   - What's unclear: Is this the intended UX? An analyst agent on synthetic gets the same model as a general task.
   - Recommendation: Accept the fallback for Phase 26. Document in code comment. Product decision if it needs fixing.

---

## Environment Availability

Step 2.6: SKIPPED (no external dependencies — this phase is pure Python composition of existing in-repo modules, no new services or CLIs required)

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.2 |
| Config file | `pytest.ini` or pyproject.toml (use existing) |
| Quick run command | `python -m pytest tests/test_tiered_routing_bridge.py -x -q` |
| Full suite command | `python -m pytest tests/ -x -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| ROUTE-01 | engineer→coding, researcher→research, writer→content, analyst→strategy, unknown→general | unit | `pytest tests/test_tiered_routing_bridge.py::TestRoleMapping -x` | ❌ Wave 0 |
| ROUTE-01 | Empty/None role falls back to general (D-02) | unit | `pytest tests/test_tiered_routing_bridge.py::test_unknown_role_falls_back_to_general -x` | ❌ Wave 0 |
| ROUTE-02 | Gold-tier agent resolves higher-capability model than bronze-tier for same task type | unit | `pytest tests/test_tiered_routing_bridge.py::TestTierUpgrade -x` | ❌ Wave 0 |
| ROUTE-02 | Rewards disabled → provisional tier → no upgrade applied | unit | `pytest tests/test_tiered_routing_bridge.py::test_rewards_disabled_uses_base_category -x` | ❌ Wave 0 |
| ROUTE-03 | preferredProvider override uses that provider in RoutingDecision | unit | `pytest tests/test_tiered_routing_bridge.py::test_preferred_provider_override -x` | ❌ Wave 0 |
| ROUTE-03 | No preferredProvider → defaults to synthetic (or anthropic if no key) | unit | `pytest tests/test_tiered_routing_bridge.py::test_default_provider_is_synthetic -x` | ❌ Wave 0 |
| ROUTE-04 | execute_async() usage dict contains model, provider after routing resolve | integration | `pytest tests/test_tiered_routing_bridge.py::TestOrchestratorIntegration -x` | ❌ Wave 0 |
| ROUTE-04 | costUsd=0, inputTokens=0, outputTokens=0 (stub values until Phase 27) | unit | `pytest tests/test_tiered_routing_bridge.py::test_usage_dict_stub_values -x` | ❌ Wave 0 |
| ROUTE-04 | Routing failure (exception) → usage dict has empty model/provider, run still completes | unit | `pytest tests/test_tiered_routing_bridge.py::test_routing_failure_degrades_gracefully -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/test_tiered_routing_bridge.py -x -q`
- **Per wave merge:** `python -m pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_tiered_routing_bridge.py` — covers all ROUTE-01 through ROUTE-04 requirements
- [ ] `core/tiered_routing_bridge.py` — the new bridge class itself

*(Existing test infrastructure (pytest, fixtures in test_memory_bridge.py) covers everything else)*

---

## Sources

### Primary (HIGH confidence)
- `core/agent_manager.py` — Direct read: `resolve_model()`, `_TIER_CATEGORY_UPGRADE`, `PROVIDER_MODELS` (verified 2026-03-29)
- `core/reward_system.py` — Direct read: `RewardSystem.score()`, `TierDeterminator.determine()`, `TierCache`, no-op when disabled (verified 2026-03-29)
- `core/memory_bridge.py` — Direct read: MemoryBridge class architecture pattern (verified 2026-03-29)
- `core/sidecar_orchestrator.py` — Direct read: execute_async() step sequence, existing reward_system param (verified 2026-03-29)
- `core/sidecar_models.py` — Direct read: AdapterConfig.preferred_provider field, CallbackPayload.usage dict (verified 2026-03-29)
- `dashboard/sidecar.py` — Direct read: create_sidecar_app() factory, MemoryBridge construction pattern (verified 2026-03-29)
- `core/task_types.py` — Direct read: TaskType enum values (verified 2026-03-29)
- `core/rewards_config.py` — Direct read: RewardsConfig thresholds (silver=0.65, gold=0.85) (verified 2026-03-29)
- `.planning/phases/26-tiered-routing-bridge/26-CONTEXT.md` — All locked decisions D-01 through D-14 (verified 2026-03-29)
- `.planning/research/PITFALLS.md` — P3 (duplicate budget tracking), P6 (standalone mode regression) (verified 2026-03-29)

### Secondary (MEDIUM confidence)
- `dashboard/server.py` lines 1117-1202 — SpendingTracker/pricing pattern reference; note that `SpendingTracker` was removed in v2.0 and replaced with a stub. Pricing lookup pattern (`_model_prices` tuple) is the reference implementation.
- `.planning/research/FEATURES.md` — Heartbeat response shape: `{costUsd, usage, model, provider}` required fields (verified 2026-03-29)

### Tertiary (LOW confidence)
- Synthetic (StrongWall) per-token pricing: Not publicly documented. Values in pricing table are estimates only. Mark as LOW confidence; update when actual pricing is available from StrongWall API docs.

---

## Project Constraints (from CLAUDE.md)

| Directive | Applies to Phase 26 |
|-----------|---------------------|
| All I/O is async — use `aiofiles`, `httpx`, `asyncio`. Never blocking I/O. | `TieredRoutingBridge.resolve()` must be `async def` (calls `RewardSystem.score()` which is async) |
| Frozen config — `Settings` dataclass in `core/config.py` | If any new config fields needed (none expected for this phase), add to `from_env()` |
| Graceful degradation — Redis, Qdrant, MCP are optional. Handle absence, never crash. | Bridge must handle `reward_system=None` without raising |
| Sandbox always on — validate paths via `sandbox.resolve_path()` | Not applicable to this phase (no file path operations) |
| New pitfalls — add to `.claude/reference/pitfalls-archive.md` when discovered | Add pitfall entries if new non-obvious issues emerge during implementation |
| Use `jcodemunch` before reading files | Followed: index was consulted via CLAUDE.md guidance |
| New modules need `tests/test_*.py` | `tests/test_tiered_routing_bridge.py` is required |
| Full standards: `.claude/reference/development-workflow.md` | Test file must follow conventions from that reference |

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — verified in-repo, no new dependencies
- Architecture: HIGH — MemoryBridge pattern is direct template; all API signatures verified in source
- Pitfalls: HIGH (pitfalls 1-4 verified from code inspection) / MEDIUM (pricing table values are estimates)

**Research date:** 2026-03-29
**Valid until:** 2026-04-28 (stable Python codebase; pricing table values may shift sooner if StrongWall publishes official pricing)
