# Phase 6: Routing + Config Finalization - Research

**Researched:** 2026-03-02
**Domain:** Python model routing, configuration management, provider-diverse fallback chains
**Confidence:** HIGH

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| ROUT-01 | Update FREE_ROUTING to use Cerebras as primary for speed-critical task types (coding, debugging, app_create) | `cerebras-gpt-oss-120b` (3000 tok/s) is registered and FREE. `FREE_ROUTING` dict in `agents/model_router.py` is a plain dict keyed by TaskType — simple replacement of the "primary" string for 3 task types |
| ROUT-02 | Use Codestral (Mistral free endpoint) as code critic for coding/debugging/refactoring | `mistral-codestral` key registered at `ProviderType.MISTRAL_CODESTRAL`. Replace "critic" field for 3 task types in `FREE_ROUTING` |
| ROUT-03 | Use Groq models as primary for research/content/strategy task types | `groq-llama-70b` (280 tok/s, 131K ctx) and `groq-gpt-oss-120b` (500 tok/s) are FREE. Replace "primary" for research/content/strategy in `FREE_ROUTING` |
| ROUT-04 | Update fallback chain with provider-diversity awareness — cycle through different providers before same provider again | `_find_healthy_free_model()` iterates MODELS dict in insertion order. Need a provider-diverse ordering so adjacent models come from different providers |
| ROUT-05 | Add SambaNova and Together AI models to fallback chain as CHEAP-tier options (after free models exhausted) | Both tiers registered. Need a separate `_find_cheap_model()` method or extend `_find_healthy_free_model()` to accept tier parameter |
| CONF-01 | Add `GEMINI_FREE_TIER` setting (bool, default true) — when false, exclude Gemini from FREE_ROUTING and fallback candidates | Pattern is clear from existing bool settings: field in `Settings` dataclass + `from_env()` call + `.env.example` entry |
| CONF-02 | Add `OPENROUTER_FREE_ONLY` setting (bool, default false) — when true, only route to models with `:free` suffix on OpenRouter | Same pattern. Router must check `settings.openrouter_free_only` before routing to non-`:free` OR models |
| CONF-03 | Add all new API key variables to Settings dataclass and `from_env()` — but all are already present | Confirmed: `cerebras_api_key`, `groq_api_key`, `mistral_api_key`, `codestral_api_key`, `sambanova_api_key`, `together_api_key` all exist in `core/config.py` as of Phase 1-5 work |
| CONF-04 | Update `.env.example` with new provider API keys and config flags with documentation | The `.env.example` already has all 6 provider keys (Phases 1-5). Needs only `GEMINI_FREE_TIER` and `OPENROUTER_FREE_ONLY` entries added |
| INFR-04 | Health checks in `model_catalog.py` cover new providers (minimal completion test per provider) | `health_check()` already iterates all FREE-tier models with API keys set. Cerebras/Groq/Codestral are FREE tier, so they are automatically included. SambaNova/Together are CHEAP — need explicit inclusion or tier filter change |
| TEST-04 | Unit tests for GEMINI_FREE_TIER and OPENROUTER_FREE_ONLY config flags | Test pattern: `patch.dict(os.environ, ...)` with `get_routing()` call and assertion on result |
| TEST-05 | Unit tests for updated fallback chain with provider diversity | Test pattern: mock `registry.free_models()` return and assert returned model comes from different provider than primary |
| TEST-06 | Integration test for routing with multiple providers configured | Test pattern: patch multiple env API keys, call `get_routing()` for several task types, assert correct provider selections |
</phase_requirements>

## Summary

Phase 6 is a pure logic/configuration phase — all providers (Cerebras, Groq, Codestral, SambaNova, Together AI) are already registered in the registry. The work is entirely in `agents/model_router.py`, `core/config.py`, and `.env.example`. No new modules are needed.

The `FREE_ROUTING` dict in `model_router.py` currently uses Gemini Flash as the primary for every task type. Phase 6 updates this to a task-type-aware multi-provider strategy: Cerebras for speed-critical code tasks, Groq for research/content, and Codestral as a code-aware critic. The fallback chain in `_find_healthy_free_model()` needs to be updated to prefer provider diversity (don't exhaust all Gemini models before trying Groq, etc.). Two new config flags (`GEMINI_FREE_TIER`, `OPENROUTER_FREE_ONLY`) need to be added to `Settings` and wired through the router.

The most critical insight from reading the existing code: `_find_healthy_free_model()` iterates `self.registry.free_models()`, which returns MODELS dict in insertion order. Insertion order in `registry.py` happens to group models by provider (all OR models, then Cerebras, then Groq, then Codestral). Provider diversity requires either reordering iteration or interleaving by provider. The cleanest approach is to group models by provider and round-robin.

**Primary recommendation:** Update `FREE_ROUTING` dict entries directly (simple string swaps), add provider-diverse round-robin to `_find_healthy_free_model()`, add two Settings fields with `from_env()` wiring, update `.env.example`, and expand health check coverage for CHEAP-tier providers (INFR-04).

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `agents/model_router.py` | existing | `FREE_ROUTING` dict, `ModelRouter` class, fallback chain | All routing logic lives here |
| `core/config.py` | existing | `Settings` frozen dataclass, `from_env()` | All env var parsing lives here |
| `providers/registry.py` | existing | `MODELS` dict, `ProviderType`, `ModelTier`, `ProviderRegistry` | Source of truth for registered models |
| `agents/model_catalog.py` | existing | `health_check()`, `is_model_healthy()` | Ping-based health checks |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `unittest.mock.patch` | stdlib | Patch `os.environ` and `settings` in tests | All config flag tests |
| `unittest.mock.MagicMock` | stdlib | Mock catalog and evaluator | Router integration tests |
| `pytest` | existing | Test runner | All test files |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Direct `FREE_ROUTING` dict mutation | Factory function that reads config | Factory adds complexity; dict is simpler and already used by every test |
| Round-robin provider diversity in `_find_healthy_free_model()` | Separate provider-diversity list in router init | Separate list is more maintainable but adds indirection; round-robin on-the-fly is fine for <20 free models |

## Architecture Patterns

### Recommended File Structure Changes
```
agents/
└── model_router.py    # Update FREE_ROUTING dict + _find_healthy_free_model() + GEMINI_FREE_TIER/OPENROUTER_FREE_ONLY logic

core/
└── config.py          # Add gemini_free_tier: bool + openrouter_free_only: bool to Settings

.env.example           # Add GEMINI_FREE_TIER and OPENROUTER_FREE_ONLY entries

tests/
├── test_model_router.py     # Add tests for config flags + fallback diversity
└── test_model_catalog.py    # Add test for CHEAP-tier health check inclusion (INFR-04)
```

### Pattern 1: FREE_ROUTING Dict Updates (ROUT-01, ROUT-02, ROUT-03)

**What:** Replace "primary" and "critic" string values in the `FREE_ROUTING` dict for specific task types.
**When to use:** Applying the task-type-specialized provider routing.

```python
# Source: agents/model_router.py (current pattern to follow)
FREE_ROUTING: dict[TaskType, dict] = {
    TaskType.CODING: {
        "primary": "cerebras-gpt-oss-120b",  # ROUT-01: Cerebras fastest (3000 tok/s)
        "critic": "mistral-codestral",        # ROUT-02: Codestral is code-aware critic
        "max_iterations": 8,
    },
    TaskType.DEBUGGING: {
        "primary": "cerebras-gpt-oss-120b",  # ROUT-01: Speed matters for iteration
        "critic": "mistral-codestral",        # ROUT-02: Code-aware critic
        "max_iterations": 10,
    },
    TaskType.RESEARCH: {
        "primary": "groq-llama-70b",          # ROUT-03: Groq for research
        "critic": "or-free-llama-70b",
        "max_iterations": 5,
    },
    TaskType.REFACTORING: {
        "primary": "gemini-2-flash",
        "critic": "mistral-codestral",        # ROUT-02: Code-aware critic for refactoring
        "max_iterations": 8,
    },
    TaskType.CONTENT: {
        "primary": "groq-llama-70b",          # ROUT-03: Groq for content
        "critic": "or-free-gemma-27b",
        "max_iterations": 6,
    },
    TaskType.STRATEGY: {
        "primary": "groq-gpt-oss-120b",       # ROUT-03: Groq for strategy
        "critic": "or-free-llama-70b",
        "max_iterations": 5,
    },
    TaskType.APP_CREATE: {
        "primary": "cerebras-gpt-oss-120b",  # ROUT-01: Cerebras for app creation speed
        "critic": "mistral-codestral",        # ROUT-02: Code-aware critic
        "max_iterations": 12,
    },
    # ... other task types keep gemini-2-flash as primary
}
```

**Key decision:** `APP_CREATE` is listed in ROUT-01's "speed-critical" set per the requirements description ("coding, debugging, app_create"). Codestral as critic for `REFACTORING` is covered by ROUT-02 ("coding/debugging/refactoring").

### Pattern 2: Provider-Diverse Fallback Chain (ROUT-04)

**What:** When `_find_healthy_free_model()` scans for a fallback, prefer models from different providers before repeating a provider.
**When to use:** Primary model unavailable or unhealthy.

```python
# Source: agents/model_router.py (proposed update)

def _find_healthy_free_model(self, exclude: set[str] | None = None) -> str | None:
    """Find a free model that is configured, healthy, and from a diverse provider."""
    exclude = exclude or set()

    # Group free models by provider, maintaining insertion order within each group
    from providers.registry import MODELS, ProviderType
    provider_groups: dict[ProviderType, list[str]] = {}
    for model in self.registry.free_models():
        key = model["key"]
        if key in exclude:
            continue
        try:
            spec = self.registry.get_model(key)
            provider_groups.setdefault(spec.provider, []).append(key)
        except ValueError:
            continue

    # Round-robin across providers: pick first healthy+configured model from each
    for _ in range(max(len(v) for v in provider_groups.values()) if provider_groups else 0):
        for provider, keys in list(provider_groups.items()):
            if not keys:
                continue
            key = keys.pop(0)
            if self._catalog and not self._catalog.is_model_healthy(key):
                continue
            try:
                spec = self.registry.get_model(key)
                provider_spec = PROVIDERS.get(spec.provider)
                api_key = os.getenv(provider_spec.api_key_env, "") if provider_spec else ""
                if api_key:
                    return key
            except ValueError:
                continue
    return None
```

**Simpler alternative** (acceptable if the round-robin approach causes test complexity): Sort the models list so models alternate providers, then iterate as before. The interleaved list approach is easier to test.

### Pattern 3: GEMINI_FREE_TIER Flag (CONF-01)

**What:** When `GEMINI_FREE_TIER=false`, exclude Gemini from FREE_ROUTING primary and from the fallback chain.
**Implementation location:** `get_routing()` pre-check AND `_find_healthy_free_model()`.

```python
# In get_routing(), after step 5 (hardcoded defaults):
from core.config import settings
if not settings.gemini_free_tier and routing.get("primary") == "gemini-2-flash":
    # Gemini excluded — find alternative
    replacement = self._find_healthy_free_model(
        exclude={"gemini-2-flash"}, skip_providers={ProviderType.GEMINI}
    )
    if replacement:
        routing["primary"] = replacement

# In _find_healthy_free_model():
if not settings.gemini_free_tier and spec.provider == ProviderType.GEMINI:
    continue  # Skip all Gemini models
```

**Alternative simpler approach:** Filter the model list at the start of `_find_healthy_free_model()` before the round-robin loop:

```python
# At top of _find_healthy_free_model():
from core.config import settings
from providers.registry import ProviderType
skip_providers = set()
if not settings.gemini_free_tier:
    skip_providers.add(ProviderType.GEMINI)
```

### Pattern 4: OPENROUTER_FREE_ONLY Flag (CONF-02)

**What:** When `OPENROUTER_FREE_ONLY=true`, only use OR models with `:free` suffix; skip non-`:free` OR models.

```python
# In get_routing() and _find_healthy_free_model():
from core.config import settings

# Check in _find_healthy_free_model():
if settings.openrouter_free_only and spec.provider == ProviderType.OPENROUTER:
    if not spec.model_id.endswith(":free"):
        continue  # Skip paid OR models

# Check in get_routing() for primary/critic:
if settings.openrouter_free_only:
    primary = routing.get("primary", "")
    if primary and primary in MODELS:
        spec = MODELS[primary]
        if spec.provider == ProviderType.OPENROUTER and not spec.model_id.endswith(":free"):
            # Swap to a free-suffix OR model
            routing["primary"] = self._find_healthy_free_model(
                exclude={primary}, require_or_free_suffix=True
            )
```

**Cleaner approach:** Add `openrouter_free_only` guard inside `_find_healthy_free_model()` as a filter, then call that from `get_routing()` when the current primary violates the constraint.

### Pattern 5: Settings Dataclass Extension (CONF-01, CONF-02, CONF-03)

**What:** Add two fields to the `Settings` frozen dataclass. Per CONF-03, all API key fields already exist. Only the two flag fields need adding.

```python
# In core/config.py Settings dataclass:
# Dynamic model routing — add after existing routing settings
gemini_free_tier: bool = True   # When false, exclude Gemini from free routing
openrouter_free_only: bool = False  # When true, only use :free suffix OR models

# In from_env():
gemini_free_tier=os.getenv("GEMINI_FREE_TIER", "true").lower() in ("true", "1", "yes"),
openrouter_free_only=os.getenv("OPENROUTER_FREE_ONLY", "false").lower() in ("true", "1", "yes"),
```

### Pattern 6: CHEAP-Tier Health Checks (INFR-04)

**What:** The current `health_check()` in `model_catalog.py` only pings FREE-tier models. SambaNova and Together AI are CHEAP-tier. Need to extend to cover them.

```python
# Current (model_catalog.py health_check()):
for key, spec in MODELS.items():
    if spec.tier != ModelTier.FREE:  # <-- excludes CHEAP
        continue
    ...

# Updated — include CHEAP tier:
for key, spec in MODELS.items():
    if spec.tier not in (ModelTier.FREE, ModelTier.CHEAP):
        continue
    provider_spec = PROVIDERS.get(spec.provider)
    if not provider_spec:
        continue
    env_key = os.getenv(provider_spec.api_key_env, "")
    if not env_key:
        continue  # Skip unconfigured providers — not an error
    models_to_check.append((key, spec.model_id, provider_spec.base_url, env_key))
```

**Note:** The "also check Gemini" special-case block below this loop remains unchanged — it handles the CHEAP-tier Gemini model that wasn't caught by the FREE tier filter.

### Pattern 7: ROUT-05 — CHEAP Fallback Chain

**What:** After free models are exhausted, try CHEAP-tier models (SambaNova, Together AI).
**Implementation:** Add a second fallback method or extend `_find_healthy_free_model()` with a tier parameter.

```python
def _find_healthy_model(
    self,
    tiers: tuple = (ModelTier.FREE,),
    exclude: set[str] | None = None,
    skip_providers: set | None = None,
) -> str | None:
    """Find a healthy model from the given tiers, with provider diversity."""
    exclude = exclude or set()
    skip_providers = skip_providers or set()

    for model in self.registry.models_by_tier_list(tiers):
        key = model["key"]
        if key in exclude:
            continue
        ...

# In get_routing() fallback of last resort:
if not replacement:
    replacement = self._find_healthy_model(
        tiers=(ModelTier.CHEAP,), exclude={primary}
    )
```

**Simpler alternative for ROUT-05:** Keep `_find_healthy_free_model()` as-is but add a separate `_find_healthy_cheap_model()` that checks CHEAP-tier models. Fewer changes to existing tested code.

### Anti-Patterns to Avoid

- **Hardcoding provider priority order as a list** — if a provider's key isn't configured, the fallback loop will skip it anyway. Don't add a separate "preferred providers" list that needs maintenance.
- **Mutating the `settings` object** to apply flag changes — `Settings` is a frozen dataclass. All checks must call `settings.gemini_free_tier` or `os.getenv(...)` at call time, not at import time.
- **Importing `settings` at module level in `model_router.py`** — `settings` is already imported at module level in other modules but `model_router.py` intentionally uses `from core.config import settings` inside methods to support test patching. Maintain this pattern.
- **Skipping the `is_admin_override` guard when applying config flags** — admin overrides beat all flags. If an admin explicitly sets `AGENT42_CODING_MODEL=gemini-2-flash`, it must work even when `GEMINI_FREE_TIER=false`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Health check infrastructure | Custom ping loop | Existing `model_catalog.health_check()` + `is_model_healthy()` | Already handles concurrency, timeouts, caching |
| Provider client management | Custom client pool | `ProviderRegistry.get_client()` | Already handles key rotation, caching |
| Model tier filtering | Custom model list | `registry.free_models()` + `registry.models_by_tier()` | Already implemented and tested |
| Boolean env var parsing | `os.getenv("X") == "true"` | `os.getenv("X", "true").lower() in ("true", "1", "yes")` | Existing pattern — handles "1", "yes", case-insensitive |

**Key insight:** This phase has almost zero infrastructure to build. Every underlying mechanism is already in place from Phases 1-5. The work is configuration wiring and routing logic adjustments.

## Common Pitfalls

### Pitfall 1: MODELS Dict Insertion Order Governs Fallback Priority

**What goes wrong:** `_find_healthy_free_model()` iterates `self.registry.free_models()` which returns models in MODELS dict insertion order. Currently all OR models appear first, then Cerebras, Groq, Codestral. If Gemini is excluded via `GEMINI_FREE_TIER=false` but Gemini was the routing primary, the fallback picks the first OR model — which may itself be unavailable on a bad day.
**Why it happens:** The MODELS dict in `registry.py` is defined in tier order (FREE first, by provider within tier). No deliberate interleaving by provider.
**How to avoid:** The provider-diversity round-robin in `_find_healthy_free_model()` (Pattern 2 above) solves this. Alternatively, reorder the MODELS dict so providers interleave — but that's fragile.
**Warning signs:** Tests that only mock one provider's API key passing, while integration tests with multiple keys show unexpected provider selection.

### Pitfall 2: `get_routing()` Validates Primary After Policy, Not After FREE_ROUTING Assignment

**What goes wrong:** The `GEMINI_FREE_TIER=false` check must happen AFTER the FREE_ROUTING dict is applied but BEFORE the API key validation block. If inserted in the wrong place, the validation block may re-select Gemini as the fallback.
**Why it happens:** The `get_routing()` method has a complex flow: admin override → dynamic → free defaults → policy → trial → context window → API key validation → critic validation. The config flag checks must be applied as part of the "API key validation" step (or just before it), not separately.
**How to avoid:** Apply `GEMINI_FREE_TIER` logic inside the existing primary model validation block. When Gemini is the primary and `gemini_free_tier=false`, treat it as "unavailable" and call `_find_healthy_free_model(skip_providers={ProviderType.GEMINI})`.
**Warning signs:** Test where `GEMINI_FREE_TIER=false` is set but routing still returns `gemini-2-flash`.

### Pitfall 3: Codestral Critic Fails If CODESTRAL_API_KEY Not Set

**What goes wrong:** Setting `mistral-codestral` as the critic for CODING/DEBUGGING/REFACTORING tasks causes the critic validation block to mark it unavailable if `CODESTRAL_API_KEY` is not set. The critic falls back to Gemini (if Gemini key is set) or is disabled. This is correct behavior but confusing in tests.
**Why it happens:** Critic validation in `get_routing()` checks the provider API key. `mistral-codestral` uses `ProviderType.MISTRAL_CODESTRAL` which requires `CODESTRAL_API_KEY`.
**How to avoid:** In tests that verify Codestral is selected as critic, mock `CODESTRAL_API_KEY` in the environment. In integration tests, verify the fallback-to-Gemini behavior when key is missing.
**Warning signs:** Test asserts `routing["critic"] == "mistral-codestral"` but gets `"gemini-2-flash"` instead.

### Pitfall 4: `OPENROUTER_FREE_ONLY` Does Not Apply to Already-`:free`-Suffix Models

**What goes wrong:** Implementing `OPENROUTER_FREE_ONLY` incorrectly blocks models that already have the `:free` suffix (e.g., `or-free-qwen-coder` → `qwen/qwen3-coder:free`). These should always be allowed.
**Why it happens:** Flag name implies "only free models" but the check should be "skip OR models WITHOUT `:free` suffix", not "skip all OR models".
**How to avoid:** Check `spec.model_id.endswith(":free")` — not `spec.model_id.startswith("or-free")` (the registry key prefix, which is different from the model_id).
**Warning signs:** `OPENROUTER_FREE_ONLY=true` breaks routing for all OpenRouter models, including explicitly-free ones.

### Pitfall 5: `settings` Import in Router Tests Must Be Patched at the Right Module

**What goes wrong:** Patching `core.config.settings` in router tests doesn't affect the router if the router does `from core.config import settings` at method call time — the patch must target `agents.model_router` if the name is imported there, or `core.config` if the router does `from core.config import settings` inside the method.
**Why it happens:** Looking at the existing test: `patch("core.config.settings", MagicMock(...))` is used. The router imports `from core.config import settings` inside methods. This patch works because the attribute is looked up on the module object at call time.
**How to avoid:** Follow existing test pattern exactly: `patch("core.config.settings", MagicMock(gemini_free_tier=False, ...))`. Do not use `patch.object(settings, "gemini_free_tier", False)` — frozen dataclass attributes cannot be set that way.
**Warning signs:** Config flag tests pass when run in isolation but fail when run with the full suite (module-level import already resolved).

### Pitfall 6: Health Check Covers NEW Providers Only When Their API Keys Are Set

**What goes wrong:** INFR-04 says "health checks cover new providers" but if `SAMBANOVA_API_KEY` is not set in the test environment, the health check correctly skips SambaNova. A test that asserts "SambaNova is checked" will fail in CI without the key.
**Why it happens:** The health check design intentionally skips unconfigured providers. INFR-04 is about infrastructure — verifying the health check WOULD cover new providers if keys are set.
**How to avoid:** Write INFR-04 test with `patch.dict(os.environ, {"SAMBANOVA_API_KEY": "test-key", "TOGETHER_API_KEY": "test-key"})` and assert those providers appear in `models_to_check`. Mock the actual HTTP call.
**Warning signs:** INFR-04 test passes locally (if keys are set) but fails in CI.

## Code Examples

Verified patterns from existing codebase:

### Adding a Bool Setting to the Settings Dataclass

```python
# Source: core/config.py — existing pattern for bool settings
# In Settings dataclass fields:
gemini_free_tier: bool = True
openrouter_free_only: bool = False

# In from_env():
gemini_free_tier=os.getenv("GEMINI_FREE_TIER", "true").lower() in ("true", "1", "yes"),
openrouter_free_only=os.getenv("OPENROUTER_FREE_ONLY", "false").lower() in ("true", "1", "yes"),
```

### Patching Settings in Router Tests

```python
# Source: tests/test_model_router.py — existing pattern
def _patch_policy(policy):
    return patch("core.config.settings", MagicMock(model_routing_policy=policy))

# New pattern for config flags (follow same approach):
def _patch_gemini_free_tier(enabled: bool):
    mock = MagicMock()
    mock.gemini_free_tier = enabled
    mock.openrouter_free_only = False
    mock.model_routing_policy = "balanced"
    return patch("core.config.settings", mock)
```

### Testing Provider API Key Presence in Routing

```python
# Source: tests/test_model_router.py — existing pattern
def test_free_only_uses_free_routing_defaults(self):
    router = ModelRouter()
    with patch.dict(
        os.environ,
        {"MODEL_ROUTING_POLICY": "free_only", "GEMINI_API_KEY": "test-key"},
        clear=False,
    ):
        with _patch_policy("free_only"):
            routing = router.get_routing(TaskType.CODING)
    assert routing["primary"] == FREE_ROUTING[TaskType.CODING]["primary"]

# New pattern for GEMINI_FREE_TIER test:
def test_gemini_excluded_when_free_tier_false(self):
    router = ModelRouter()
    with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key", "CEREBRAS_API_KEY": "test-key"}):
        with patch("core.config.settings", MagicMock(
            gemini_free_tier=False, openrouter_free_only=False,
            model_routing_policy="free_only"
        )):
            routing = router.get_routing(TaskType.RESEARCH)
    # Research task defaults to Groq, but if Groq key not set, should NOT fall back to Gemini
    assert "gemini" not in routing.get("primary", "").lower()
```

### Extending Health Check to Include CHEAP Tier

```python
# Source: agents/model_catalog.py health_check() — existing pattern (lines 446-454)
# Current:
for key, spec in MODELS.items():
    if spec.tier != ModelTier.FREE:
        continue
    ...

# Updated (INFR-04):
for key, spec in MODELS.items():
    if spec.tier not in (ModelTier.FREE, ModelTier.CHEAP):
        continue
    provider_spec = PROVIDERS.get(spec.provider)
    if not provider_spec:
        continue
    env_key = os.getenv(provider_spec.api_key_env, "")
    if not env_key:
        continue  # Skip unconfigured providers gracefully
    models_to_check.append((key, spec.model_id, provider_spec.base_url, env_key))
```

### .env.example Entries for New Config Flags

```bash
# Routing control flags (add to "── Dynamic Model Routing ──" section):
# Gemini free tier inclusion (default: true)
# When false, Gemini is excluded from FREE_ROUTING and fallback chain
# (reduces Google dependency when you have other free providers configured)
# GEMINI_FREE_TIER=true

# OpenRouter free-only mode (default: false)
# When true, only routes to OpenRouter models with :free suffix
# (never incurs OpenRouter paid charges, even with a funded account)
# OPENROUTER_FREE_ONLY=false
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| All task types route to Gemini Flash | Task-type-specialized routing (Cerebras for code, Groq for research) | Phase 6 (this phase) | Code tasks get 3000 tok/s instead of Gemini; research gets 131K context at 280 tok/s |
| Only OR free models as fallback | Provider-diverse fallback chain across 4 free providers | Phase 6 | Single provider outage no longer stops Agent42 |
| No billing-control flags | `GEMINI_FREE_TIER` + `OPENROUTER_FREE_ONLY` | Phase 6 | Users can opt out of Gemini (data privacy) or restrict OR to free-only |
| Health checks only for FREE-tier | Health checks for FREE + CHEAP tier | Phase 6 (INFR-04) | SambaNova and Together AI get proactive health monitoring |

**Deprecated/outdated:**
- The comment in `model_router.py` docstring saying "Uses Gemini free tier as the base LLM" — will be partially accurate after Phase 6 (Gemini remains a primary for some task types but not all).

## Open Questions

1. **Which Groq model for research vs. content vs. strategy?**
   - What we know: `groq-llama-70b` (llama-3.3-70b-versatile, 280 tok/s, 131K ctx, 1K RPM) and `groq-gpt-oss-120b` (openai/gpt-oss-120b, 500 tok/s, 131K ctx, 1K RPM) are both registered.
   - What's unclear: REQUIREMENTS.md says "use Groq models" without specifying which one for which task type.
   - Recommendation: Use `groq-llama-70b` as primary for research and content (more battle-tested for general tasks). Use `groq-gpt-oss-120b` for strategy (slightly faster, good for structured reasoning).

2. **Does ROUT-04 need full round-robin or just "no two adjacent from same provider"?**
   - What we know: The requirement says "cycle through different providers before retrying the same provider".
   - What's unclear: Whether this means strict alternation or best-effort diversity.
   - Recommendation: Implement full round-robin (group by provider, rotate through groups) — cleaner semantics, easier to test.

3. **ROUT-05: When exactly does CHEAP fallback activate?**
   - What we know: Requirements say "after free models exhausted". The current `_find_healthy_free_model()` returns `None` when no free model has a valid key.
   - What's unclear: Does CHEAP fallback happen in `get_routing()` itself or only in the agent dispatch layer?
   - Recommendation: Add CHEAP fallback in `get_routing()` — if `_find_healthy_free_model()` returns None, call `_find_healthy_cheap_model()`. Log clearly so users see it happening.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest with pytest-asyncio |
| Config file | pyproject.toml (`asyncio_mode = "auto"`) |
| Quick run command | `python -m pytest tests/test_model_router.py tests/test_model_catalog.py -x -q` |
| Full suite command | `python -m pytest tests/ -x -q` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| ROUT-01 | Cerebras is primary for coding/debugging/app_create in FREE_ROUTING | unit | `python -m pytest tests/test_model_router.py::TestFreeRoutingUpdates::test_cerebras_primary_for_coding -x` | ❌ Wave 0 |
| ROUT-02 | Codestral is critic for coding/debugging/refactoring in FREE_ROUTING | unit | `python -m pytest tests/test_model_router.py::TestFreeRoutingUpdates::test_codestral_critic_for_code_tasks -x` | ❌ Wave 0 |
| ROUT-03 | Groq is primary for research/content/strategy in FREE_ROUTING | unit | `python -m pytest tests/test_model_router.py::TestFreeRoutingUpdates::test_groq_primary_for_research -x` | ❌ Wave 0 |
| ROUT-04 | Fallback chain cycles across providers | unit | `python -m pytest tests/test_model_router.py::TestFallbackChainDiversity -x` | ❌ Wave 0 |
| ROUT-05 | CHEAP-tier fallback after free exhausted | unit | `python -m pytest tests/test_model_router.py::TestCheapTierFallback -x` | ❌ Wave 0 |
| CONF-01 | GEMINI_FREE_TIER=false excludes Gemini | unit | `python -m pytest tests/test_model_router.py::TestGeminiFreeTierFlag -x` | ❌ Wave 0 |
| CONF-02 | OPENROUTER_FREE_ONLY=true restricts to :free suffix | unit | `python -m pytest tests/test_model_router.py::TestOpenrouterFreeOnlyFlag -x` | ❌ Wave 0 |
| CONF-03 | API key fields exist in Settings | unit | `python -m pytest tests/test_config.py -x -q -k "api_key"` | ✅ (partial — verify cerebras, groq, etc. covered) |
| CONF-04 | .env.example has new flags documented | manual | Review .env.example for GEMINI_FREE_TIER and OPENROUTER_FREE_ONLY entries | ❌ Wave 0 |
| INFR-04 | Health check includes CHEAP-tier providers | unit | `python -m pytest tests/test_model_catalog.py::TestHealthCheck::test_cheap_tier_included -x` | ❌ Wave 0 |
| TEST-04 | Config flag unit tests | unit | `python -m pytest tests/test_model_router.py -x -q -k "free_tier or free_only"` | ❌ Wave 0 |
| TEST-05 | Fallback diversity unit tests | unit | `python -m pytest tests/test_model_router.py::TestFallbackChainDiversity -x` | ❌ Wave 0 |
| TEST-06 | Multi-provider integration test | integration | `python -m pytest tests/test_model_router.py::TestMultiProviderIntegration -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/test_model_router.py -x -q`
- **Per wave merge:** `python -m pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] Add `TestFreeRoutingUpdates` class to `tests/test_model_router.py` — covers ROUT-01, ROUT-02, ROUT-03
- [ ] Add `TestFallbackChainDiversity` class to `tests/test_model_router.py` — covers ROUT-04
- [ ] Add `TestCheapTierFallback` class to `tests/test_model_router.py` — covers ROUT-05
- [ ] Add `TestGeminiFreeTierFlag` class to `tests/test_model_router.py` — covers CONF-01, TEST-04
- [ ] Add `TestOpenrouterFreeOnlyFlag` class to `tests/test_model_router.py` — covers CONF-02, TEST-04
- [ ] Add `TestMultiProviderIntegration` class to `tests/test_model_router.py` — covers TEST-06
- [ ] Add `test_cheap_tier_included` to `tests/test_model_catalog.py::TestHealthCheck` — covers INFR-04
- [ ] No new test files needed — all new tests go into existing `test_model_router.py` and `test_model_catalog.py`

Existing test infrastructure: `tests/test_model_router.py` (17 tests passing), `tests/test_model_catalog.py` (existing), `tests/test_providers.py` (existing). Framework configured in `pyproject.toml`.

## Sources

### Primary (HIGH confidence)
- Direct source read: `agents/model_router.py` — `FREE_ROUTING` dict, `ModelRouter.get_routing()`, `_find_healthy_free_model()`, critic validation logic (lines 33-802)
- Direct source read: `core/config.py` — `Settings` dataclass fields (lines 40-280), `from_env()` pattern (lines 281-533)
- Direct source read: `providers/registry.py` — `MODELS` dict showing all registered models and tiers (lines 169-413), `SpendingTracker._BUILTIN_PRICES` (lines 422-455)
- Direct source read: `agents/model_catalog.py` — `health_check()` tier filter at line 446 (the `ModelTier.FREE` check that excludes CHEAP)
- Direct source read: `tests/test_model_router.py` — 17 existing tests, patching patterns, test class structure
- Direct source read: `.planning/REQUIREMENTS.md` — Phase 6 requirement definitions with task-type assignments
- Direct source read: `.planning/STATE.md` — Accumulated project decisions, Phase 5 completion state

### Secondary (MEDIUM confidence)
- Direct source read: `.env.example` — existing documentation style for API key entries and routing flags

### Tertiary (LOW confidence)
- None — all findings are from direct source examination.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all files read directly; no third-party libraries involved
- Architecture: HIGH — patterns extracted from existing working code; phase is pure logic changes
- Pitfalls: HIGH — extracted from actual code flow analysis and existing test patterns

**Research date:** 2026-03-02
**Valid until:** 2026-04-02 (stable — this is internal Python code with no external dependencies changing)
