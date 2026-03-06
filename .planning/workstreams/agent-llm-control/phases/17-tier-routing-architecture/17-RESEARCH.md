# Phase 17: Tier Routing Architecture - Research

**Researched:** 2026-03-06
**Domain:** Model routing restructure (L1/L2 tier concepts in model_router.py)
**Confidence:** HIGH

## Summary

Phase 17 restructures `agents/model_router.py` around L1/L2 tier concepts. The current 5-layer resolution chain treats free models as the default and has no concept of a "workhorse" primary provider. The change introduces StrongWall as the default L1 primary for all task types when configured, demotes the current `FREE_ROUTING` dict to `FALLBACK_ROUTING`, and wires L2 premium models as last-resort escalation with an authorization mechanism.

The codebase is well-prepared for this change. The `l1_default_model` and `l1_critic_model` fields already exist in `core/config.py` (lines 260-261) but are **unused** by `model_router.py`. The `L2_ROUTING` dict and `get_l2_routing()` method already exist and are consumed by `agents/agent.py` (line 486). The `ProviderHealthChecker` already polls StrongWall health in production. The work is a routing logic restructure, not a new integration.

**Primary recommendation:** Restructure `get_routing()` to insert L1 check as layer 3 (replacing free defaults), rename `FREE_ROUTING` to `FALLBACK_ROUTING` with backward-compatible alias, update L2 critic fields from `None` to self-critique, and add `l2_authorized` mechanism. Update all 8 files that reference `FREE_ROUTING`.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- StrongWall serves as primary for ALL task types equally -- no exceptions or task-type specialization at L1 level
- When L1 is unavailable, fall back to task-type-aware FALLBACK_ROUTING table (Cerebras for coding, Groq for research, Gemini for general -- existing FREE_ROUTING entries)
- L1 reuses max_iterations from FALLBACK_ROUTING per task type (already tuned values: 12 for app_create, 8 for coding, etc.)
- ModelTier enum stays as-is (FREE/CHEAP/PAID) -- L1/L2 is a routing concept, not a cost tier. StrongWall remains ModelTier.CHEAP. No cascading changes to SpendingTracker, health checks, or catalog
- Replace layer 3 (free defaults) with L1 check: "If L1 model is configured + healthy, use L1. Else fall back to FALLBACK_ROUTING."
- New resolution chain: (1) Admin override, (2) Dynamic routing, (3) L1 check / FALLBACK_ROUTING, (4) Policy routing, (5) Trial injection
- Configurable L1 model via `L1_MODEL` env var -- defaults to `strongwall-kimi-k2.5` when STRONGWALL_API_KEY is set. Future-proof for additional StrongWall models or alternative L1 providers
- Rename `FREE_ROUTING` dict to `FALLBACK_ROUTING` -- clearer semantics as it's no longer the default, just the fallback table
- Gemini Pro upgrade logic (layer 4b) still runs after L1 -- if user has paid Gemini key and GEMINI_PRO_FOR_COMPLEX is not false, complex tasks upgrade to Gemini Pro even over L1
- Existing policy routing (balanced/performance/free_only modes) stays as-is alongside L2 -- separate concern about OpenRouter credit usage
- L2 activates as last-resort fallback when BOTH L1 AND free fallback providers are unavailable
- L2 also available via explicit user authorization: global allowlist by task type + per-task escalation through Approvals page
- Phase 17 builds routing logic only: an internal `l2_authorized` flag/mechanism that downstream phases (18/19) wire to the dashboard UI
- Existing _check_policy_routing() logic kept alongside L2 -- they are separate concerns
- L1 model is the default critic when L1 is active -- self-critique with dedicated reviewer system prompt and skills (same model, different role framing)
- When L1 is down and primary falls back to FALLBACK_ROUTING, critic also reverts to FALLBACK_ROUTING critics (Codestral for code, OR free for others) -- clean degradation
- L2 also self-critiques: premium model serves as both primary and critic (with separate reviewer prompting), replacing the current `critic: None` in L2_ROUTING
- Critic override configurable per-agent -- deferred to Phase 18/19 per-agent config

### Claude's Discretion
- Exact implementation of L1 health check integration with routing (reuse existing _catalog.is_model_healthy or StrongWall-specific health)
- How to structure the l2_authorized flag internally (config field, runtime state, or parameter)
- Whether L1_MODEL validation happens at startup or lazily on first get_routing() call
- Test restructuring approach for renamed FALLBACK_ROUTING and new L1 paths

### Deferred Ideas (OUT OF SCOPE)
- L2 authorization UI (global allowlist + per-task escalation button) -- Phase 19 (Agent Config Dashboard)
- Per-agent critic override configuration -- Phase 18/19
- Auto-escalation from L1 to L2 based on task complexity assessment -- future requirement ROUTE-05
- A/B testing between L1 and L2 models -- future requirement ROUTE-04
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| TIER-01 | Model routing supports L1 (workhorse) and L2 (premium) tier concepts | Resolution chain restructure in `get_routing()` with L1 check at layer 3; `get_l2_routing()` already exists |
| TIER-02 | StrongWall is the default L1 provider when API key is configured | `L1_MODEL` env var defaults to `strongwall-kimi-k2.5` when `STRONGWALL_API_KEY` is set; `l1_default_model` field already in Settings |
| TIER-03 | Gemini serves as default L2 provider | `L2_ROUTING` dict already has premium models; update defaults or add Gemini as L2 default |
| TIER-04 | OpenRouter paid models available as L2 when balance present and not locked to FREE | `get_l2_routing()` already checks API keys; add OR balance check for L2 availability |
| TIER-05 | Fallback chain operates as StrongWall -> Free providers -> L2 premium | L1 check -> `FALLBACK_ROUTING` -> L2 last-resort in `get_routing()` flow |
| ROUTE-01 | Routing chain updated to check agent-level overrides first (highest priority) | Admin override layer already position 1; agent-level overrides deferred to Phase 18/19 but routing logic prepared |
| ROUTE-02 | OR free models no longer default for critical tasks (coding, debugging, etc.) | L1 (StrongWall) becomes default for all task types; `FALLBACK_ROUTING` uses Cerebras/Groq for critical tasks (no OR free as primary) |
| ROUTE-03 | Existing free providers (Cerebras, Groq, Codestral) remain as fallback tier | `FALLBACK_ROUTING` (renamed from `FREE_ROUTING`) preserves all existing task-type mappings |
</phase_requirements>

## Standard Stack

### Core (No New Dependencies)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib | 3.11+ | enum, os, json, logging, dataclasses | Already used throughout; no new deps needed |

### Existing Modules (Modification Targets)
| Module | Location | Purpose | Changes Needed |
|--------|----------|---------|----------------|
| model_router.py | agents/model_router.py | Main routing logic | Restructure resolution chain, rename dict, add L1 check |
| config.py | core/config.py | Settings dataclass | Repurpose existing `l1_default_model` field, add L1_MODEL default logic |
| registry.py | providers/registry.py | Provider/model specs | No changes (StrongWall stays CHEAP tier) |
| model_catalog.py | agents/model_catalog.py | Health checks, catalog | Update `validate_primary_models` to use `FALLBACK_ROUTING` |
| agent.py | agents/agent.py | Agent execution | No changes (already uses `get_routing` / `get_l2_routing`) |

### Test Files (Update Required)
| File | References to Update |
|------|---------------------|
| tests/test_model_router.py | `FREE_ROUTING` import + 20+ references |
| tests/test_dynamic_routing.py | `FREE_ROUTING` import + 10+ references |
| tests/test_model_catalog.py | `FREE_ROUTING` import + 5 references |
| tests/test_openclaw_features.py | `FREE_ROUTING` import + 2 references |
| tests/test_project_interview.py | `FREE_ROUTING` import + 3 references |

## Architecture Patterns

### Current Resolution Chain (model_router.py:247)
```
1. Admin override (AGENT42_CODING_MODEL etc.)
2. Dynamic routing (outcome-driven JSON file)
3. [FREE_ROUTING defaults]              <-- REPLACED
4. Policy routing (balanced/performance)
4b. Gemini Pro upgrade (complex tasks)
5. Trial injection (small %)
```

### New Resolution Chain (Phase 17)
```
1. Admin override (AGENT42_CODING_MODEL etc.)     -- unchanged
2. Dynamic routing (outcome-driven JSON file)      -- unchanged
3. L1 check: if L1 configured + healthy -> L1     -- NEW
   ELSE: FALLBACK_ROUTING (renamed FREE_ROUTING)  -- renamed
4. Policy routing (balanced/performance)           -- unchanged
4b. Gemini Pro upgrade (complex tasks)             -- unchanged (runs over L1 too)
5. Trial injection (small %)                       -- unchanged
```

### L1 Health Check Integration

**Recommendation:** Use a two-tier check combining `ProviderHealthChecker` (provider-level, already polling StrongWall every 60s) and `ModelCatalog.is_model_healthy()` (model-level). The provider health checker is the primary gate since it runs continuously; the model catalog health check is secondary.

```python
def _is_l1_available(self, l1_model: str) -> bool:
    """Check if L1 model is configured and healthy."""
    # 1. Check provider-level health (ProviderHealthChecker polls every 60s)
    from providers.registry import provider_health_checker, MODELS
    spec = MODELS.get(l1_model)
    if spec:
        prov_status = provider_health_checker.get_status(spec.provider)
        if prov_status.get("status") == "unhealthy":
            return False

    # 2. Check model-level health (ModelCatalog — optimistic by default)
    if self._catalog and not self._catalog.is_model_healthy(l1_model):
        return False

    # 3. Check API key is set
    if spec:
        provider_spec = PROVIDERS.get(spec.provider)
        if provider_spec and not os.getenv(provider_spec.api_key_env, ""):
            return False

    return True
```

**Validation timing:** Lazy on first `get_routing()` call (not startup). Rationale: API keys may be injected after Settings initialization by `KeyStore.inject_into_environ()` (see config.py:690). Checking at startup would give false negatives.

### L1 Routing Logic

```python
def _get_l1_routing(self, task_type: TaskType) -> dict | None:
    """Return L1 routing if L1 model is configured and healthy."""
    l1_model = self._resolve_l1_model()
    if not l1_model:
        return None

    if not self._is_l1_available(l1_model):
        logger.info("L1 model %s unavailable, falling back to FALLBACK_ROUTING", l1_model)
        return None

    # Reuse max_iterations from FALLBACK_ROUTING (already tuned per task type)
    fallback = FALLBACK_ROUTING.get(task_type, FALLBACK_ROUTING[TaskType.CODING])

    return {
        "primary": l1_model,
        "critic": l1_model,  # L1 self-critique (same model, different prompt)
        "max_iterations": fallback.get("max_iterations", 8),
    }

def _resolve_l1_model(self) -> str:
    """Resolve the L1 model key from config or environment."""
    from core.config import settings

    # Explicit L1_MODEL env var takes priority
    l1_model = os.getenv("L1_MODEL", "") or settings.l1_default_model

    # Auto-detect: default to strongwall-kimi-k2.5 when StrongWall key is set
    if not l1_model and os.getenv("STRONGWALL_API_KEY", ""):
        l1_model = "strongwall-kimi-k2.5"

    return l1_model
```

### L2 Authorization Mechanism

**Recommendation:** Use a runtime-settable attribute on `ModelRouter` rather than a config field. This keeps Phase 17 clean (routing logic only) while giving Phase 18/19 a simple hook to wire the dashboard UI.

```python
class ModelRouter:
    def __init__(self, evaluator=None, routing_file="", catalog=None):
        # ... existing init ...
        self._l2_authorized_task_types: set[str] = set()  # Global allowlist
        self._l2_authorized_tasks: set[str] = set()       # Per-task IDs

    def authorize_l2(self, task_type: str | None = None, task_id: str | None = None):
        """Authorize L2 escalation for a task type or specific task."""
        if task_type:
            self._l2_authorized_task_types.add(task_type)
        if task_id:
            self._l2_authorized_tasks.add(task_id)

    def is_l2_authorized(self, task_type: TaskType, task_id: str = "") -> bool:
        """Check if L2 is authorized for this task type or task."""
        return (
            task_type.value in self._l2_authorized_task_types
            or task_id in self._l2_authorized_tasks
        )
```

**L2 as last-resort fallback:** When both L1 and all FALLBACK_ROUTING providers are unavailable (no API keys or all unhealthy), `get_routing()` should attempt L2 before returning an error routing. This is separate from explicit authorization.

### L2 Self-Critique Update

The `L2_ROUTING` dict currently has `"critic": None` for all task types. Per user decision, L2 should self-critique (same model, different reviewer prompt). Update all entries:

```python
L2_ROUTING: dict[TaskType, dict] = {
    TaskType.CODING: {
        "primary": "claude-sonnet",
        "critic": "claude-sonnet",      # Self-critique (was None)
        "max_iterations": 3,
    },
    # ... same pattern for all task types
}
```

### FALLBACK_ROUTING Rename with Backward Compatibility

```python
# Renamed: clearer semantics (no longer the default, just the fallback table)
FALLBACK_ROUTING: dict[TaskType, dict] = {
    # ... same entries as current FREE_ROUTING ...
}

# Backward-compatible alias for external consumers
FREE_ROUTING = FALLBACK_ROUTING
```

This approach means test files can be updated incrementally -- the alias prevents breakage during the transition. However, the test updates should be done in the same plan to keep things clean.

### Files Referencing FREE_ROUTING (Full Inventory)

| File | Line(s) | Type | Change |
|------|---------|------|--------|
| agents/model_router.py | 33, 226, 273, 417, 421, 631, 712, 747 | Definition + usage | Rename to FALLBACK_ROUTING |
| agents/model_catalog.py | 293, 299, 306 | Import + iteration | Update import to FALLBACK_ROUTING |
| core/config.py | 260, 270 | Comments only | Update comment text |
| tests/test_model_router.py | 9, 154-235+ | Import + assertions | Update import + all references |
| tests/test_dynamic_routing.py | 6, 14-177 | Import + assertions | Update import + all references |
| tests/test_model_catalog.py | 318-334 | Import + monkeypatch | Update import + references |
| tests/test_openclaw_features.py | 625, 649 | Import + assertion | Update import + reference |
| tests/test_project_interview.py | 582-589 | Import + assertions | Update import + references |

**Total: 8 files, ~50 references to rename.**

### Recommended Project Structure Changes

No new files needed. All changes are modifications to existing files:

```
agents/
  model_router.py        # Main restructure target
  model_catalog.py       # Update FREE_ROUTING import
core/
  config.py              # Update l1_default_model default logic + comments
tests/
  test_model_router.py   # Major update: rename refs + new L1/L2 tests
  test_dynamic_routing.py    # Rename refs
  test_model_catalog.py      # Rename refs
  test_openclaw_features.py  # Rename refs
  test_project_interview.py  # Rename refs
```

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Provider health check | Custom StrongWall health probe in router | `provider_health_checker.get_status(ProviderType.STRONGWALL)` | Already polls every 60s, Phase 16 built it |
| Model health check | Custom model health probe | `self._catalog.is_model_healthy(model_key)` | Already tracks per-model health with optimistic default |
| API key validation | Custom key checking logic | `os.getenv(provider_spec.api_key_env, "")` pattern | Already used throughout router, consistent with KeyStore injection |
| L2 routing resolution | New L2 routing from scratch | Extend existing `get_l2_routing()` | Already handles admin overrides, global defaults, per-type defaults, API key validation |

**Key insight:** The existing router already has all the building blocks (health checks, fallback chains, API key validation, L2 routing). Phase 17 is a restructure, not a greenfield build.

## Common Pitfalls

### Pitfall 1: Settings Frozen at Import vs os.getenv at Runtime
**What goes wrong:** Reading `settings.l1_default_model` gives empty string because Settings is frozen at import time, before `KeyStore.inject_into_environ()` runs.
**Why it happens:** The `Settings.from_env()` creates the frozen dataclass at module import. API keys from `.agent42/settings.json` (admin UI) are injected later.
**How to avoid:** Always use `os.getenv("L1_DEFAULT_MODEL", "")` for API-key-adjacent config in the routing path, consistent with how `_check_admin_override` works.
**Warning signs:** L1 model always shows as unconfigured despite API key being set via dashboard.

### Pitfall 2: Circular Import Between model_router and config
**What goes wrong:** Adding `from core.config import settings` at module level in model_router.py could create import cycles.
**Why it happens:** model_router already uses lazy imports (`from core.config import settings` inside methods, not at top level) to avoid this.
**How to avoid:** Keep the lazy import pattern. Use `from core.config import settings` inside `_resolve_l1_model()` and similar methods.
**Warning signs:** `ImportError` or `AttributeError` at import time.

### Pitfall 3: FREE_ROUTING Rename Breaking External Consumers
**What goes wrong:** Test files and model_catalog.py import `FREE_ROUTING` by name. A pure rename without alias breaks all 8 files.
**Why it happens:** Python dict rename is not a refactor the runtime can detect.
**How to avoid:** Add `FREE_ROUTING = FALLBACK_ROUTING` alias at module level. Update all imports in the same commit. The alias prevents partial breakage.
**Warning signs:** `ImportError: cannot import name 'FREE_ROUTING'` in tests.

### Pitfall 4: L1 Self-Critique Returning Same Model Key
**What goes wrong:** Setting `"critic": l1_model` where `l1_model = "strongwall-kimi-k2.5"` means the agent's critic loop uses the exact same model. Without a different system prompt, this is a rubber stamp.
**Why it happens:** The critic model key alone doesn't control prompting -- the agent execution loop builds a separate reviewer system prompt.
**How to avoid:** Verify that `agents/agent.py`'s critic path applies a distinct reviewer system prompt when `routing["critic"] == routing["primary"]`. This is already how the agent works (the critic prompt is role-framed differently from the primary).
**Warning signs:** Critic iterations always approve without substantive feedback.

### Pitfall 5: L2 Last-Resort Fallback Creating Infinite Loops
**What goes wrong:** If `get_routing()` falls through L1 and FALLBACK_ROUTING to L2, but L2 is also unavailable, the router could enter an error state or loop.
**Why it happens:** The current code has a "use fallback routing as last resort" path at lines 417-426. Adding L2 as an intermediate fallback needs careful ordering.
**How to avoid:** Keep the existing "return FALLBACK_ROUTING as absolute last resort" pattern at the bottom. L2 last-resort is an additional attempt, not a replacement for the existing safety net.
**Warning signs:** `get_routing()` returns `None` or raises an exception.

### Pitfall 6: GEMINI_PRO_FOR_COMPLEX Overriding L1
**What goes wrong:** Layer 4b (Gemini Pro upgrade) runs after L1 and replaces the L1 model with `gemini-2-pro` for complex tasks.
**Why it happens:** This is the designed behavior per user decision ("Gemini Pro upgrade logic still runs after L1"). But operators may be surprised that their L1 gets overridden.
**How to avoid:** Log clearly when Gemini Pro upgrade overrides L1. Document that `GEMINI_PRO_FOR_COMPLEX=false` disables this behavior.
**Warning signs:** StrongWall configured as L1 but agents use Gemini Pro for coding tasks.

## Code Examples

### Example 1: L1 Check Integration in get_routing()

```python
# Source: agents/model_router.py — restructured get_routing() layer 3
def get_routing(self, task_type: TaskType, context_window: str = "default") -> dict:
    # 1. Admin override — always wins
    override = self._check_admin_override(task_type)
    is_admin_override = override is not None
    if override:
        routing = override
    else:
        # 2. Dynamic routing
        dynamic = self._check_dynamic_routing(task_type)
        if dynamic:
            routing = dynamic.copy()
        else:
            # 3. L1 check: if L1 configured + healthy, use L1
            l1_routing = self._get_l1_routing(task_type)
            if l1_routing:
                routing = l1_routing
            else:
                # 3b. FALLBACK_ROUTING (renamed from FREE_ROUTING)
                routing = FALLBACK_ROUTING.get(
                    task_type, FALLBACK_ROUTING[TaskType.CODING]
                ).copy()

    # 4. Policy routing (unchanged)
    # 4b. Gemini Pro upgrade (unchanged — runs over L1 too)
    # 5. Trial injection (unchanged)
    # ... rest of existing logic ...
```

### Example 2: L2 Last-Resort Fallback

```python
# Source: agents/model_router.py — extended fallback chain in get_routing()
# After the existing primary model validation (lines 370-427):
if not primary_model or not self._is_model_available(primary_model):
    # Existing: try _find_healthy_free_model
    replacement = self._find_healthy_free_model(exclude={primary_model})
    if not replacement:
        # Existing: try _find_healthy_cheap_model
        replacement = self._find_healthy_cheap_model(exclude={primary_model})
    if not replacement:
        # NEW: L2 last-resort (when both L1 and free fallback unavailable)
        l2 = self.get_l2_routing(task_type)
        if l2:
            logger.warning("All L1/fallback models unavailable — using L2 last-resort")
            routing = l2
            replacement = l2.get("primary")
    if replacement:
        routing["primary"] = replacement
```

### Example 3: L1_MODEL Resolution with Auto-Detection

```python
# Source: agents/model_router.py — _resolve_l1_model()
def _resolve_l1_model(self) -> str:
    """Resolve the L1 model key from environment or auto-detection.

    Resolution order:
    1. L1_MODEL env var (explicit override)
    2. settings.l1_default_model (from .env)
    3. Auto-detect: strongwall-kimi-k2.5 when STRONGWALL_API_KEY is set
    4. Empty string (L1 not configured)
    """
    # Use os.getenv for runtime correctness (KeyStore may inject after settings frozen)
    l1_model = os.getenv("L1_MODEL", "")

    if not l1_model:
        from core.config import settings
        l1_model = settings.l1_default_model

    # Auto-detect: StrongWall as L1 when API key is configured
    if not l1_model and os.getenv("STRONGWALL_API_KEY", ""):
        l1_model = "strongwall-kimi-k2.5"

    return l1_model
```

### Example 4: L2 Self-Critique in L2_ROUTING

```python
# Source: agents/model_router.py — updated L2_ROUTING
L2_ROUTING: dict[TaskType, dict] = {
    TaskType.CODING: {
        "primary": "claude-sonnet",
        "critic": "claude-sonnet",  # Self-critique: same model, reviewer prompt
        "max_iterations": 3,
    },
    TaskType.DEBUGGING: {
        "primary": "claude-sonnet",
        "critic": "claude-sonnet",
        "max_iterations": 3,
    },
    # ... pattern continues for all task types
}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Free models as default | L1 workhorse as default | Phase 17 (now) | StrongWall primary for all tasks when configured |
| FREE_ROUTING dict name | FALLBACK_ROUTING dict name | Phase 17 (now) | Semantics: "fallback" not "default" |
| L2 critic: None | L2 self-critique | Phase 17 (now) | Premium models review their own output |
| No L1 concept in routing | L1 check at layer 3 | Phase 17 (now) | Explicit workhorse tier concept |

**Deprecated/outdated:**
- `FREE_ROUTING` name: Renamed to `FALLBACK_ROUTING` (alias kept for backward compat)
- `L2_ROUTING` critic=None pattern: Replaced with self-critique

## Open Questions

1. **L1_MODEL vs L1_DEFAULT_MODEL env var naming**
   - What we know: Settings field is `l1_default_model`, env var is `L1_DEFAULT_MODEL`. CONTEXT.md mentions `L1_MODEL` as the env var.
   - What's unclear: Should we add a separate `L1_MODEL` env var (checked first) or rename the existing `L1_DEFAULT_MODEL`?
   - Recommendation: Check `os.getenv("L1_MODEL")` first, fall back to `settings.l1_default_model` (which reads `L1_DEFAULT_MODEL`). This matches the user's mental model (simple `L1_MODEL`) while keeping backward compat with the existing field. No Settings field rename needed.

2. **FALLBACK_ROUTING critic degradation when L1 is down**
   - What we know: When L1 is active, critic = L1 model. When L1 is down, routing falls to FALLBACK_ROUTING which has its own critic assignments.
   - What's unclear: The critic validation logic (lines 432-460) may try to validate the L1 critic and replace it with gemini-2-flash, even when L1 is healthy.
   - Recommendation: The existing critic validation runs after routing is determined. When L1 is selected, the critic is set to L1 model. If the L1 model becomes unhealthy between routing and critic validation, the existing gemini-2-flash upgrade path handles it gracefully. No special handling needed.

3. **Backward compatibility alias scope**
   - What we know: `FREE_ROUTING = FALLBACK_ROUTING` alias keeps imports working.
   - What's unclear: Should the alias be permanent or deprecated with a warning?
   - Recommendation: Keep alias permanently (no deprecation warning). It's a module-level variable assignment with zero runtime cost. Removing it later would be a breaking change for no benefit.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest + pytest-asyncio (auto mode) |
| Config file | pyproject.toml |
| Quick run command | `python -m pytest tests/test_model_router.py -x -q` |
| Full suite command | `python -m pytest tests/ -x -q` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| TIER-01 | L1/L2 tier concepts in routing | unit | `python -m pytest tests/test_model_router.py::TestL1Routing -x` | Wave 0 |
| TIER-02 | StrongWall as default L1 when configured | unit | `python -m pytest tests/test_model_router.py::TestL1Routing::test_l1_defaults_to_strongwall -x` | Wave 0 |
| TIER-03 | Gemini as default L2 provider | unit | `python -m pytest tests/test_model_router.py::TestL2Routing -x` | Partial (existing get_l2_routing tests) |
| TIER-04 | OR paid models as L2 with balance | unit | `python -m pytest tests/test_model_router.py::TestL2Routing::test_or_paid_l2 -x` | Wave 0 |
| TIER-05 | Fallback chain StrongWall -> Free -> L2 | unit | `python -m pytest tests/test_model_router.py::TestFallbackChain -x` | Wave 0 |
| ROUTE-01 | Agent-level overrides first priority | unit | `python -m pytest tests/test_model_router.py::TestGetRoutingWithPolicy::test_admin_override_beats_policy -x` | Existing |
| ROUTE-02 | OR free not default for critical tasks | unit | `python -m pytest tests/test_model_router.py::TestL1Routing::test_coding_uses_l1_not_or_free -x` | Wave 0 |
| ROUTE-03 | Cerebras/Groq/Codestral remain as fallback | unit | `python -m pytest tests/test_model_router.py::TestFallbackRoutingEntries -x` | Existing (renamed class) |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/test_model_router.py tests/test_dynamic_routing.py -x -q`
- **Per wave merge:** `python -m pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_model_router.py::TestL1Routing` -- covers TIER-01, TIER-02, ROUTE-02
- [ ] `tests/test_model_router.py::TestL2RoutingUpdates` -- covers TIER-03, TIER-04
- [ ] `tests/test_model_router.py::TestFallbackChain` -- covers TIER-05
- [ ] All existing test classes need `FREE_ROUTING` -> `FALLBACK_ROUTING` rename
- [ ] Framework install: Not needed -- pytest already configured

## Sources

### Primary (HIGH confidence)
- Direct source code analysis of `agents/model_router.py` (933 lines) -- full resolution chain, FREE_ROUTING dict, L2_ROUTING dict, all helper methods
- Direct source code analysis of `core/config.py` (700 lines) -- existing `l1_default_model`, `l1_critic_model` fields, `L1_DEFAULT_MODEL` env var
- Direct source code analysis of `providers/registry.py` (970 lines) -- StrongWall provider spec, ModelTier enum, ProviderHealthChecker, SpendingTracker
- Direct source code analysis of `agents/agent.py` (lines 484-497) -- consumption of `get_routing()` and `get_l2_routing()`
- Direct source code analysis of `tests/test_model_router.py` (697 lines) -- existing test patterns, FREE_ROUTING references

### Secondary (MEDIUM confidence)
- `17-CONTEXT.md` -- user decisions and code context analysis from discussion phase
- `REQUIREMENTS.md` -- formal requirement definitions for TIER-01 through ROUTE-03

### Tertiary (LOW confidence)
- None -- all findings are from direct source code analysis

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - all code is internal, no new dependencies, direct source analysis
- Architecture: HIGH - resolution chain is well-documented in source, existing patterns clear
- Pitfalls: HIGH - identified from direct code analysis and known project patterns (see CLAUDE.md pitfalls)

**Research date:** 2026-03-06
**Valid until:** 2026-04-06 (stable internal refactor, no external dependency changes)
