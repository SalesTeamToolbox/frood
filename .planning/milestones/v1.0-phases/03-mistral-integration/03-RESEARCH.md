# Phase 3: Mistral Integration - Research

**Researched:** 2026-03-02
**Domain:** Provider registry extension — dual Mistral providers (Codestral + La Plateforme) following the Phase 1/2 pattern
**Confidence:** HIGH

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| MIST-01 | Register ProviderType.MISTRAL with ProviderSpec (base_url: `https://api.mistral.ai/v1`, api_key_env: `MISTRAL_API_KEY`) | Confirmed via Mistral OpenAI-compatible docs and community sources — `AsyncOpenAI(base_url="https://api.mistral.ai/v1", api_key=key)` is the standard pattern |
| MIST-02 | Register ProviderType.MISTRAL_CODESTRAL with ProviderSpec (base_url: `https://codestral.mistral.ai/v1`, api_key_env: `CODESTRAL_API_KEY`) | Separate endpoint confirmed in Mistral's official Codestral announcement; separate API key (`CODESTRAL_API_KEY`) confirmed by LiteLLM docs and community sources |
| MIST-03 | Register Codestral ModelSpec on MISTRAL_CODESTRAL provider — `codestral-latest` (32K context, 30 RPM free), classified as ModelTier.FREE | Model ID `codestral-latest` confirmed via Mistral docs. Context 32K per REQUIREMENTS.md (256K per some sources — see Open Questions). FREE tier correct for the `codestral.mistral.ai` dedicated endpoint |
| MIST-04 | Register La Plateforme ModelSpec entries on MISTRAL provider — `mistral-large-latest`, `mistral-small-latest`, classified as ModelTier.CHEAP (2 RPM free tier) | Both model IDs verified; CHEAP tier correct (credits-based, 2 RPM on experiment plan, per-token pricing confirmed) |
| MIST-05 | Add $0 pricing for Codestral free models, actual pricing for La Plateforme models in SpendingTracker | Codestral: $0 (free endpoint). La Plateforme: mistral-large-latest ~$2.00/$6.00 per M tokens, mistral-small-latest ~$0.20/$0.60 per M tokens (MEDIUM confidence — see sources) |
</phase_requirements>

---

## Summary

Phase 3 is the first multi-provider phase: Mistral exposes **two separate API endpoints** with **two separate API keys**, requiring two ProviderSpec registrations. The `codestral.mistral.ai` endpoint is Mistral's dedicated free code-specialist endpoint, while `api.mistral.ai` is La Plateforme (the general endpoint, credits-based). Both are OpenAI-compatible and work with the same `AsyncOpenAI(base_url=..., api_key=..., max_retries=0)` pattern used throughout `providers/registry.py`.

The ProviderType enum values `MISTRAL` and `MISTRAL_CODESTRAL` both already exist in the codebase (added in Phase 1 via INFR-01). Phase 3 only needs to add two ProviderSpec entries to `PROVIDERS`, two ModelSpec entries to `MODELS` (one for Codestral, two for La Plateforme), four `_BUILTIN_PRICES` entries (Codestral at $0, La Plateforme at actual pricing), and two API key fields in Settings. The pattern is identical to Phases 1 and 2 but applied twice.

The critical uniqueness of Phase 3: the two Mistral providers are **guarded against primary-slot assignment** by their tier classifications. Codestral (`ModelTier.FREE`) is classified free correctly because the `codestral.mistral.ai` endpoint is genuinely free. La Plateforme (`ModelTier.CHEAP`) correctly signals that mistral-large and mistral-small incur per-token costs — preventing them from silently entering FREE_ROUTING as primary models. This tier-based safeguard is the key architectural reason Mistral uses two ProviderType values rather than one.

**Primary recommendation:** Add two ProviderSpec entries (MISTRAL + MISTRAL_CODESTRAL) to PROVIDERS, three ModelSpec entries to MODELS, four `_BUILTIN_PRICES` entries to SpendingTracker, two API key fields to Settings, and document both keys in `.env.example`. Follow the exact Cerebras/Groq pattern for each. Write two test classes (TestMistralRegistration + TestMistralSpendingTracker) following the Phase 2 template.

---

## Standard Stack

### Core (already in project — no new dependencies)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `openai` (AsyncOpenAI) | already installed | HTTP client for both Mistral API endpoints | Both Mistral endpoints are OpenAI-compatible; no native Mistral SDK needed |
| `pytest` + `pytest-asyncio` | already installed | Test framework | Project standard — `asyncio_mode = "auto"` in pyproject.toml |

### No New Dependencies

Neither Mistral API endpoint requires the `mistralai` Python package. The project uses `AsyncOpenAI(base_url=..., api_key=..., max_retries=0)` for all providers. Both Mistral endpoints (La Plateforme and Codestral) expose an OpenAI-compatible `/v1/chat/completions` API.

**Installation:** No new packages needed for this phase.

---

## Architecture Patterns

### Recommended File Structure for Changes

```
providers/
└── registry.py          # 2x ProviderSpec, 3 ModelSpecs, 4 $0/$pricing entries
core/
└── config.py            # Add mistral_api_key + codestral_api_key fields to Settings
.env.example             # Document MISTRAL_API_KEY and CODESTRAL_API_KEY
tests/
└── test_providers.py    # Add TestMistralRegistration class (6 tests)
tests/
└── test_model_catalog.py  # Add TestMistralSpendingTracker class (5 tests)
```

### Pattern 1: Two ProviderSpec entries for the two Mistral endpoints (MIST-01, MIST-02)

**What:** Add to `PROVIDERS: dict[ProviderType, ProviderSpec]` in `providers/registry.py`
**When to use:** After the GROQ entry, in provider-type order. Add MISTRAL first, then MISTRAL_CODESTRAL.
**Example:**
```python
# Source: Mistral official docs + community verification (OpenAI-compatible)
ProviderType.MISTRAL: ProviderSpec(
    provider_type=ProviderType.MISTRAL,
    base_url="https://api.mistral.ai/v1",
    api_key_env="MISTRAL_API_KEY",
    display_name="Mistral La Plateforme",
    supports_function_calling=True,
    # No default_model — routing handles model selection
    # requires_model_prefix=False (default) — model IDs are bare strings
),
ProviderType.MISTRAL_CODESTRAL: ProviderSpec(
    provider_type=ProviderType.MISTRAL_CODESTRAL,
    base_url="https://codestral.mistral.ai/v1",
    api_key_env="CODESTRAL_API_KEY",
    display_name="Mistral Codestral (free)",
    supports_function_calling=True,
),
```

### Pattern 2: ModelSpec entries — one for Codestral, two for La Plateforme (MIST-03, MIST-04)

**What:** Add 3 entries to `MODELS: dict[str, ModelSpec]`. Codestral goes in FREE TIER section. La Plateforme models go in CHEAP TIER section.
**When to use:** Codestral immediately after Groq entries in FREE TIER. La Plateforme entries in CHEAP TIER after existing CHEAP models.
**Example:**
```python
# FREE TIER — Codestral (codestral.mistral.ai endpoint — genuinely free, 30 RPM)
# Source: REQUIREMENTS.md + Mistral docs (codestral-latest is the stable alias)
"mistral-codestral": ModelSpec(
    "codestral-latest",
    ProviderType.MISTRAL_CODESTRAL,
    max_tokens=8192,
    display_name="Codestral (Mistral free)",
    tier=ModelTier.FREE,
    max_context_tokens=32000,    # 32K per REQUIREMENTS.md spec (see Open Questions)
),

# CHEAP TIER — La Plateforme models (api.mistral.ai — credits-based, 2 RPM free experiment plan)
# Source: REQUIREMENTS.md + pricing research (MIST-04 classification)
"mistral-large": ModelSpec(
    "mistral-large-latest",
    ProviderType.MISTRAL,
    max_tokens=4096,
    display_name="Mistral Large (La Plateforme)",
    tier=ModelTier.CHEAP,
    max_context_tokens=128000,   # 128K context per verified sources
),
"mistral-small": ModelSpec(
    "mistral-small-latest",
    ProviderType.MISTRAL,
    max_tokens=4096,
    display_name="Mistral Small (La Plateforme)",
    tier=ModelTier.CHEAP,
    max_context_tokens=128000,   # 128K context per verified sources
),
```

### Pattern 3: SpendingTracker pricing entries (MIST-05)

**What:** Add 3 entries to `_BUILTIN_PRICES`. Codestral at $0, La Plateforme at actual per-token pricing.
**When to use:** After Groq entries in `_BUILTIN_PRICES`.
**Example:**
```python
# Codestral free endpoint — $0 (free for chat completions, dedicated endpoint)
# Source: Mistral official announcement + REQUIREMENTS.md MIST-05
"codestral-latest": (0.0, 0.0),

# Mistral La Plateforme — actual pricing (CHEAP tier, credits required)
# Source: Multiple pricing aggregators, MEDIUM confidence (see Sources section)
# Pricing as of March 2026: ~$2.00/M input, $6.00/M output for Large; $0.20/$0.60 for Small
# Note: mistral-large-latest may alias to mistral-large-2512 ($0.50/$1.50) or older versions ($2.00/$6.00)
# Use conservative estimates — the exact aliased version may change
"mistral-large-latest": (2.0e-6, 6.0e-6),    # ~$2.00/M in, $6.00/M out (conservative)
"mistral-small-latest": (0.20e-6, 0.60e-6),   # ~$0.20/M in, $0.60/M out
```

**IMPORTANT:** `_BUILTIN_PRICES` keys must match `ModelSpec.model_id` exactly. The keys above (`codestral-latest`, `mistral-large-latest`, `mistral-small-latest`) must exactly match the `model_id` strings used in the ModelSpec entries.

### Pattern 4: Settings dataclass fields (two new keys)

**What:** Add two fields to `Settings` in `core/config.py`, after `groq_api_key`.
**Example:**
```python
# core/config.py Settings dataclass — add after groq_api_key
mistral_api_key: str = ""
codestral_api_key: str = ""

# Settings.from_env() — add after groq_api_key line
mistral_api_key=os.getenv("MISTRAL_API_KEY", ""),
codestral_api_key=os.getenv("CODESTRAL_API_KEY", ""),
```

Note: `ProviderRegistry._build_client()` reads `os.getenv(spec.api_key_env, "")` directly — NOT `settings.mistral_api_key`. The Settings fields exist for introspection/reporting only. Same pattern as cerebras and groq keys from prior phases.

### Pattern 5: .env.example documentation (two new key blocks)

```bash
# Mistral La Plateforme — CHEAP tier (credits required, 2 RPM on free experiment plan)
# Get key: https://console.mistral.ai/ (experiment plan: free, no credit card required)
# MISTRAL_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Mistral Codestral — FREE code specialist endpoint (separate key from La Plateforme)
# Get key: https://console.mistral.ai/ (Codestral tab — separate from main API key)
# CODESTRAL_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

### Pattern 6: Test classes following Phase 2 template

**What:** Add `TestMistralRegistration` to `tests/test_providers.py` and `TestMistralSpendingTracker` to `tests/test_model_catalog.py`.
**When to use:** After the existing `TestGroqRegistration` / `TestGroqSpendingTracker` classes.

```python
# tests/test_providers.py — after TestGroqRegistration

class TestMistralRegistration:
    """Phase 3: Mistral dual-provider registration tests."""

    def test_mistral_provider_registered(self):
        """MIST-01: ProviderType.MISTRAL is in PROVIDERS with correct base_url and api_key_env."""
        spec = PROVIDERS[ProviderType.MISTRAL]
        assert spec.base_url == "https://api.mistral.ai/v1"
        assert spec.api_key_env == "MISTRAL_API_KEY"
        assert spec.display_name == "Mistral La Plateforme"

    def test_mistral_codestral_provider_registered(self):
        """MIST-02: ProviderType.MISTRAL_CODESTRAL is in PROVIDERS with correct base_url and api_key_env."""
        spec = PROVIDERS[ProviderType.MISTRAL_CODESTRAL]
        assert spec.base_url == "https://codestral.mistral.ai/v1"
        assert spec.api_key_env == "CODESTRAL_API_KEY"

    def test_codestral_model_registered(self):
        """MIST-03: codestral-latest is registered on MISTRAL_CODESTRAL provider as FREE."""
        spec = MODELS["mistral-codestral"]
        assert spec.model_id == "codestral-latest"
        assert spec.provider == ProviderType.MISTRAL_CODESTRAL
        assert spec.tier == ModelTier.FREE

    def test_la_plateforme_models_registered(self):
        """MIST-04: mistral-large and mistral-small are registered on MISTRAL provider as CHEAP."""
        for key, expected_id in [
            ("mistral-large", "mistral-large-latest"),
            ("mistral-small", "mistral-small-latest"),
        ]:
            spec = MODELS[key]
            assert spec.model_id == expected_id
            assert spec.provider == ProviderType.MISTRAL
            assert spec.tier == ModelTier.CHEAP

    def test_mistral_client_builds_with_key(self):
        """Client builds when MISTRAL_API_KEY is set."""
        registry = ProviderRegistry()
        with patch.dict(os.environ, {"MISTRAL_API_KEY": "test-key-1234"}):
            client = registry.get_client(ProviderType.MISTRAL)
            assert client is not None
            assert client.base_url == "https://api.mistral.ai/v1/"

    def test_codestral_client_builds_with_key(self):
        """Client builds when CODESTRAL_API_KEY is set."""
        registry = ProviderRegistry()
        with patch.dict(os.environ, {"CODESTRAL_API_KEY": "test-key-5678"}):
            client = registry.get_client(ProviderType.MISTRAL_CODESTRAL)
            assert client is not None
            assert client.base_url == "https://codestral.mistral.ai/v1/"

    def test_mistral_client_raises_without_key(self):
        """Client raises ValueError when MISTRAL_API_KEY is not set."""
        registry = ProviderRegistry()
        registry.invalidate_client(ProviderType.MISTRAL)
        with patch.dict(os.environ, {"MISTRAL_API_KEY": ""}, clear=False):
            with pytest.raises(ValueError, match="MISTRAL_API_KEY not set"):
                registry.get_client(ProviderType.MISTRAL)

    def test_codestral_client_raises_without_key(self):
        """Client raises ValueError when CODESTRAL_API_KEY is not set."""
        registry = ProviderRegistry()
        registry.invalidate_client(ProviderType.MISTRAL_CODESTRAL)
        with patch.dict(os.environ, {"CODESTRAL_API_KEY": ""}, clear=False):
            with pytest.raises(ValueError, match="CODESTRAL_API_KEY not set"):
                registry.get_client(ProviderType.MISTRAL_CODESTRAL)
```

```python
# tests/test_model_catalog.py — after TestGroqSpendingTracker

class TestMistralSpendingTracker:
    """Phase 3: Mistral models — $0 for Codestral, actual pricing for La Plateforme."""

    def test_codestral_builtin_prices_exist(self):
        """codestral-latest has explicit $0 entry in _BUILTIN_PRICES."""
        from providers.registry import SpendingTracker
        assert "codestral-latest" in SpendingTracker._BUILTIN_PRICES
        prompt_price, completion_price = SpendingTracker._BUILTIN_PRICES["codestral-latest"]
        assert prompt_price == 0.0
        assert completion_price == 0.0

    def test_mistral_large_builtin_prices_exist(self):
        """mistral-large-latest has a non-zero pricing entry in _BUILTIN_PRICES."""
        from providers.registry import SpendingTracker
        assert "mistral-large-latest" in SpendingTracker._BUILTIN_PRICES
        prompt_price, completion_price = SpendingTracker._BUILTIN_PRICES["mistral-large-latest"]
        assert prompt_price > 0.0
        assert completion_price > 0.0

    def test_mistral_small_builtin_prices_exist(self):
        """mistral-small-latest has a non-zero pricing entry in _BUILTIN_PRICES."""
        from providers.registry import SpendingTracker
        assert "mistral-small-latest" in SpendingTracker._BUILTIN_PRICES
        prompt_price, completion_price = SpendingTracker._BUILTIN_PRICES["mistral-small-latest"]
        assert prompt_price > 0.0
        assert completion_price > 0.0

    def test_codestral_zero_cost(self):
        """Codestral usage records $0 spend."""
        from providers.registry import SpendingTracker
        tracker = SpendingTracker()
        tracker.record_usage("mistral-codestral", 50000, 25000,
                             model_id="codestral-latest")
        assert tracker.daily_spend_usd == 0.0

    def test_mistral_large_incurs_cost(self):
        """mistral-large-latest usage records non-zero spend (not a free model)."""
        from providers.registry import SpendingTracker
        tracker = SpendingTracker()
        tracker.record_usage("mistral-large", 10000, 5000,
                             model_id="mistral-large-latest")
        assert tracker.daily_spend_usd > 0.0
```

### Anti-Patterns to Avoid

- **Do not use a single ProviderType for both Mistral endpoints:** The two endpoints have different base URLs and different API keys. Two ProviderSpec entries with two distinct ProviderType values is the correct architecture.
- **Do not add MISTRAL or MISTRAL_CODESTRAL to the ProviderType enum:** Both were already added in Phase 1 (INFR-01). Adding them again causes `ValueError: duplicate member in Enum`.
- **Do not put La Plateforme models (mistral-large, mistral-small) in FREE TIER:** These models require credits and are `ModelTier.CHEAP`. Only Codestral belongs in FREE TIER.
- **Do not add Mistral models to FREE_ROUTING in Phase 3:** Routing changes are Phase 6 (ROUT-02). Phase 3 only registers the providers; Phase 6 routes Codestral to critic slots.
- **Do not add the `mistralai` Python package as a dependency:** `AsyncOpenAI(base_url=..., api_key=...)` works with both Mistral endpoints via their OpenAI compatibility layer.
- **Do not update `test_all_providers_registered` expected set to include only "mistral":** After this phase, BOTH `"mistral"` and `"mistral_codestral"` must be in the expected set.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| HTTP client for Mistral La Plateforme | Custom httpx client | `AsyncOpenAI(base_url="https://api.mistral.ai/v1", ...)` | Mistral La Plateforme is OpenAI-compatible |
| HTTP client for Codestral | Custom httpx client | `AsyncOpenAI(base_url="https://codestral.mistral.ai/v1", ...)` | Codestral chat completions endpoint is OpenAI-compatible |
| Dual-provider routing logic | Custom if/elif for MISTRAL vs MISTRAL_CODESTRAL | `ProviderRegistry.get_client(spec.provider)` | Existing `_build_client()` already handles all ProviderType values uniformly |
| Free tier enforcement | RPM counter per provider | Provider-side enforcement | Codestral enforces 30 RPM server-side; Mistral enforces 2 RPM experiment tier server-side |
| Model ID validation | Runtime API call to list models | Static MODELS dict entries | Model IDs `codestral-latest`, `mistral-large-latest`, `mistral-small-latest` are verified stable aliases |
| Codestral cost tracking at $0 | Custom free-model detection | `_BUILTIN_PRICES` at `(0.0, 0.0)` | Same pattern as Cerebras and Groq from prior phases — model ID doesn't match `or-free-` or `:free` patterns |

**Key insight:** Phase 3 is 100% additive declarations in existing data structures — same architecture as Phases 1 and 2, applied to two providers instead of one.

---

## Common Pitfalls

### Pitfall 1: ProviderType.MISTRAL and MISTRAL_CODESTRAL already exist — do not add them again
**What goes wrong:** Phase 1 (INFR-01) added `MISTRAL = "mistral"` and `MISTRAL_CODESTRAL = "mistral_codestral"` to the `ProviderType` enum. Adding them again causes `ValueError: duplicate member in Enum`.
**Why it happens:** Phase 1 pre-populated all 6 future enum values. This is the same trap as Phase 2 (Pitfall 2 in Phase 2 research).
**How to avoid:** Verify that `ProviderType.MISTRAL` and `ProviderType.MISTRAL_CODESTRAL` already exist before writing. Only add the `ProviderSpec` entries to `PROVIDERS`.
**Warning signs:** `ValueError: duplicate member` on import; Python exits immediately on startup.

### Pitfall 2: Codestral free-tier pricing not in _BUILTIN_PRICES triggers conservative fallback
**What goes wrong:** `codestral-latest` does not match `or-free-` prefix or `:free` suffix. `SpendingTracker._get_price()` falls through to the conservative fallback ($5/$15 per million tokens). Even light Codestral usage hits the daily spend cap.
**Why it happens:** Same root cause as Cerebras (Phase 1) and Groq (Phase 2) — free-model detection was designed only for OpenRouter naming conventions.
**How to avoid:** Add `"codestral-latest": (0.0, 0.0)` to `_BUILTIN_PRICES` (MIST-05).
**Warning signs:** `SpendingLimitExceeded` triggered after a few Codestral calls; `daily_spend_usd` shows non-zero value for Codestral usage.

### Pitfall 3: La Plateforme models missing from _BUILTIN_PRICES also cause problems
**What goes wrong:** `mistral-large-latest` and `mistral-small-latest` don't match any free-model detection pattern. If they also have no entry in `_BUILTIN_PRICES`, they fall through to the conservative $5/$15 fallback, which wildly overestimates cost and could prematurely hit the daily cap.
**Why it happens:** Mistral La Plateforme is not a free provider — it's CHEAP tier. Without explicit `_BUILTIN_PRICES` entries at the real pricing, the fallback overestimates.
**How to avoid:** Add actual pricing entries for `mistral-large-latest` and `mistral-small-latest` to `_BUILTIN_PRICES` (MIST-05). Even an approximation beats the $5/$15 fallback.
**Warning signs:** `daily_spend_usd` spikes far above expected after a few La Plateforme calls; `SpendingLimitExceeded` triggered unexpectedly.

### Pitfall 4: test_all_providers_registered needs BOTH mistral values updated
**What goes wrong:** Adding MISTRAL to PROVIDERS without also adding MISTRAL_CODESTRAL (or vice versa) creates an incomplete test expected set. The `test_all_providers_registered` test only checks `issubset`, so it won't catch partial additions.
**Why it happens:** This is the first multi-provider phase — the pattern of "one provider per phase" doesn't apply here.
**How to avoid:** After Phase 3, `expected` must include both `"mistral"` and `"mistral_codestral"`. Update the expected set to include both.
**Warning signs:** Test passes despite one provider missing from PROVIDERS.

### Pitfall 5: Codestral FIM endpoint is NOT the same as chat completions
**What goes wrong:** Codestral's fill-in-the-middle (FIM) endpoint at `https://codestral.mistral.ai/v1/fim/completions` has a different request format. Using it for chat completions will cause API errors. Conversely, using the wrong endpoint format for chat breaks FIM.
**Why it happens:** Codestral is primarily marketed as a FIM tool (for IDE autocomplete) but also supports standard chat completions at `/v1/chat/completions`.
**How to avoid:** Agent42 uses OpenAI chat completions format (`/v1/chat/completions`). The `AsyncOpenAI(base_url="https://codestral.mistral.ai/v1", ...)` pattern routes to the correct chat endpoint automatically. Do NOT build a custom FIM client for Phase 3.
**Warning signs:** 422 or 404 errors from `codestral.mistral.ai` API calls; response format mismatch.

### Pitfall 6: mistral-large-latest pricing alias uncertainty
**What goes wrong:** The `mistral-large-latest` alias points to different underlying models depending on when you call it. Current evidence suggests it maps to either `mistral-large-2411` ($2.00/$6.00) or `mistral-large-2512` ($0.50/$1.50). Using the wrong pricing causes over- or under-reporting in SpendingTracker.
**Why it happens:** Mistral uses a `latest` alias that floats to the most recent version, but pricing varies significantly between versions.
**How to avoid:** Use the conservative (higher) estimate `$2.00/$6.00 per million tokens` for `mistral-large-latest` in `_BUILTIN_PRICES`. This protects against overspending on the daily cap. Overestimation is safer than underestimation for a spending cap.
**Warning signs:** SpendingTracker estimates don't match actual Mistral invoice; discrepancy growing over time.

### Pitfall 7: Two Settings fields needed, not one
**What goes wrong:** Adding only `mistral_api_key` to Settings without `codestral_api_key` means the Settings class doesn't represent the full provider configuration. Dashboard introspection will show only one Mistral key.
**Why it happens:** Phase 3 is the first phase requiring two new Settings fields. Prior phases each had one.
**How to avoid:** Add both `mistral_api_key: str = ""` and `codestral_api_key: str = ""` to Settings dataclass, plus both `os.getenv()` calls in `from_env()`.
**Warning signs:** Settings missing `codestral_api_key`; `hasattr(settings, 'codestral_api_key')` returns False.

---

## Code Examples

Verified patterns from official sources and codebase analysis:

### MIST-01 + MIST-02: Both ProviderSpec registrations
```python
# Source: Mistral official docs (OpenAI-compatible) + REQUIREMENTS.md
# Both go in PROVIDERS dict after ProviderType.GROQ entry

ProviderType.MISTRAL: ProviderSpec(
    provider_type=ProviderType.MISTRAL,
    base_url="https://api.mistral.ai/v1",
    api_key_env="MISTRAL_API_KEY",
    display_name="Mistral La Plateforme",
    supports_function_calling=True,
),
ProviderType.MISTRAL_CODESTRAL: ProviderSpec(
    provider_type=ProviderType.MISTRAL_CODESTRAL,
    base_url="https://codestral.mistral.ai/v1",
    api_key_env="CODESTRAL_API_KEY",
    display_name="Mistral Codestral (free)",
    supports_function_calling=True,
),
```

### MIST-03 + MIST-04: Three ModelSpec entries
```python
# Source: REQUIREMENTS.md + research-verified model IDs and context windows

# FREE TIER section — after Groq entries
# Codestral (codestral.mistral.ai — free endpoint, 30 RPM)
"mistral-codestral": ModelSpec(
    "codestral-latest",
    ProviderType.MISTRAL_CODESTRAL,
    max_tokens=8192,
    display_name="Codestral (Mistral free)",
    tier=ModelTier.FREE,
    max_context_tokens=32000,    # 32K per REQUIREMENTS.md
),

# CHEAP TIER section — after existing CHEAP models
# La Plateforme (api.mistral.ai — credits-based, 2 RPM experiment plan)
"mistral-large": ModelSpec(
    "mistral-large-latest",
    ProviderType.MISTRAL,
    max_tokens=4096,
    display_name="Mistral Large (La Plateforme)",
    tier=ModelTier.CHEAP,
    max_context_tokens=128000,
),
"mistral-small": ModelSpec(
    "mistral-small-latest",
    ProviderType.MISTRAL,
    max_tokens=4096,
    display_name="Mistral Small (La Plateforme)",
    tier=ModelTier.CHEAP,
    max_context_tokens=128000,
),
```

### MIST-05: Four _BUILTIN_PRICES entries
```python
# Source: REQUIREMENTS.md + pricing research (see Metadata for confidence levels)
# Keys must EXACTLY match ModelSpec.model_id values

# Codestral free endpoint — $0 (dedicated free API, 30 RPM)
"codestral-latest": (0.0, 0.0),

# Mistral La Plateforme — actual pricing (CHEAP tier, credits required)
# Conservative estimates (mistral-large-latest may alias to older $2/$6 or newer $0.50/$1.50 version)
# Using higher estimate to protect spending cap from underestimation
"mistral-large-latest": (2.0e-6, 6.0e-6),     # ~$2.00/M in, $6.00/M out
"mistral-small-latest": (0.20e-6, 0.60e-6),    # ~$0.20/M in, $0.60/M out
```

### Settings fields
```python
# core/config.py — add after groq_api_key in dataclass
mistral_api_key: str = ""
codestral_api_key: str = ""

# core/config.py — add after groq_api_key in from_env()
mistral_api_key=os.getenv("MISTRAL_API_KEY", ""),
codestral_api_key=os.getenv("CODESTRAL_API_KEY", ""),
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| OpenRouter + Cerebras + Groq as free providers | + Codestral as free code-specialist (Phase 3) | Phase 3 | Adds dedicated code-gen free model outside OpenRouter |
| Single ProviderSpec per provider | Two ProviderSpec entries for one vendor (Mistral) | Phase 3 (first) | Pattern for vendors with multiple endpoints/pricing tiers |
| Free model detection by naming only | Explicit `_BUILTIN_PRICES` for all providers | Phase 1 (pattern) | Extended to Codestral ($0) and La Plateforme (actual pricing) |
| `ProviderType` enum has 9 values (after Phase 2) | Still 13 (all 6 new values added in Phase 1) | Phase 1 (INFR-01) | Phase 3 only adds ProviderSpec entries — enum already complete |

**Deprecated/outdated:**
- Nothing is removed in Phase 3 — all changes are additive.

---

## Open Questions

1. **Codestral context window: 32K (REQUIREMENTS.md) vs. 256K (some sources)**
   - What we know: `REQUIREMENTS.md` specifies `32K context, 30 RPM free` for Codestral (MIST-03). The promptfoo docs for Mistral state `codestral-latest` has 256K context. The `codestral-latest` alias may have changed since the requirements were written (Codestral 25.08 was released August 2025, potentially with a larger context window).
   - What's unclear: Which context window spec is current for `codestral-latest` as of March 2026.
   - Recommendation: Honor REQUIREMENTS.md (`max_context_tokens=32000`) since it was researched at project start. The code uses this as a conservative routing hint — if the actual context is larger, the only downside is that Agent42 truncates context earlier than necessary. Planner can document this in a code comment for future update.

2. **mistral-large-latest pricing uncertainty (latest alias version)**
   - What we know: `mistral-large-latest` may alias to `mistral-large-2512` (~$0.50/$1.50 per M tokens) or `mistral-large-2411` ($2.00/$6.00 per M tokens). The alias floats.
   - What's unclear: Which version `mistral-large-latest` points to as of March 2026.
   - Recommendation: Use conservative `(2.0e-6, 6.0e-6)` in `_BUILTIN_PRICES`. Overestimating cost protects the spending cap from unexpected charges. The agent may never use La Plateforme models as primary (they're CHEAP tier), so SpendingTracker accuracy is lower priority than safety.

3. **Codestral rate limit: 30 RPM (REQUIREMENTS.md) — unverified with fresh API key**
   - What we know: PROJECT.md states "Codestral free endpoint (30 RPM, 2K RPD)". Multiple sources confirm Codestral's dedicated endpoint exists and is rate-limited.
   - What's unclear: Whether the 30 RPM figure is still current for new Codestral API keys in March 2026 (the original free beta may have ended). STATE.md notes this as a Phase 3 concern.
   - Recommendation: Implement per requirements (30 RPM comment in ModelSpec). `ModelSpec` has no RPM field — this is metadata only. No code change needed regardless of the actual current limit.

4. **Codestral function calling support on the dedicated endpoint**
   - What we know: `supports_function_calling=True` is set in the ProviderSpec above. Mistral's main API supports function calling; Codestral is primarily for code and may behave differently.
   - What's unclear: Whether the `codestral.mistral.ai` endpoint's chat completions path fully supports tool calls in the OpenAI format.
   - Recommendation: Set `supports_function_calling=True` (default). Phase 3 doesn't route Codestral to tool-using task types — that's Phase 6's routing decision. If Codestral doesn't support tools, it only matters when Phase 6 assigns it to code tasks that use tools. Adjust in Phase 6 if needed.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest + pytest-asyncio (auto mode) |
| Config file | `pyproject.toml` (`[tool.pytest.ini_options]`, `asyncio_mode = "auto"`) |
| Quick run command | `python -m pytest tests/test_providers.py tests/test_model_catalog.py -x -q` |
| Full suite command | `python -m pytest tests/ -x -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| MIST-01 | `ProviderType.MISTRAL` in `PROVIDERS` with correct base_url and api_key_env | unit | `pytest tests/test_providers.py::TestMistralRegistration::test_mistral_provider_registered -x` | ❌ Wave 0 |
| MIST-02 | `ProviderType.MISTRAL_CODESTRAL` in `PROVIDERS` with correct base_url and api_key_env | unit | `pytest tests/test_providers.py::TestMistralRegistration::test_mistral_codestral_provider_registered -x` | ❌ Wave 0 |
| MIST-03 | `mistral-codestral` model in MODELS with `model_id=codestral-latest`, MISTRAL_CODESTRAL provider, FREE tier | unit | `pytest tests/test_providers.py::TestMistralRegistration::test_codestral_model_registered -x` | ❌ Wave 0 |
| MIST-04 | `mistral-large` and `mistral-small` in MODELS with MISTRAL provider, CHEAP tier, correct model_ids | unit | `pytest tests/test_providers.py::TestMistralRegistration::test_la_plateforme_models_registered -x` | ❌ Wave 0 |
| MIST-05 | `SpendingTracker._BUILTIN_PRICES` has $0 for codestral-latest, non-zero for mistral-large/small | unit | `pytest tests/test_model_catalog.py -k "mistral" -x` | ❌ Wave 0 |

Additional tests to add (not directly mapped to MIST-XX but covering success criteria):
- `test_mistral_client_builds_with_key` — covers "MISTRAL provider available when MISTRAL_API_KEY set"
- `test_codestral_client_builds_with_key` — covers "MISTRAL_CODESTRAL provider available when CODESTRAL_API_KEY set"
- `test_mistral_client_raises_without_key` — covers "starts without error when MISTRAL_API_KEY absent" (graceful degradation)
- `test_codestral_client_raises_without_key` — covers "starts without error when CODESTRAL_API_KEY absent" (graceful degradation)

### Sampling Rate

- **Per task commit:** `python -m pytest tests/test_providers.py tests/test_model_catalog.py -x -q`
- **Per wave merge:** `python -m pytest tests/ -x -q`
- **Phase gate:** Full suite green (`python -m pytest tests/ -x -q`) before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/test_providers.py` — needs `TestMistralRegistration` class added (file exists, class does not)
- [ ] `tests/test_model_catalog.py` — needs `TestMistralSpendingTracker` class added (file exists, class does not)

Note: No framework install needed — pytest and pytest-asyncio already installed per `requirements-dev.txt`.

---

## Sources

### Primary (HIGH confidence)
- `C:/Users/rickw/projects/agent42/providers/registry.py` — Existing ProviderType enum confirms MISTRAL and MISTRAL_CODESTRAL already exist; SpendingTracker pattern for $0 pricing; _build_client() pattern for `AsyncOpenAI` usage
- `C:/Users/rickw/projects/agent42/tests/test_providers.py` — TestGroqRegistration and TestCerebrasRegistration test class patterns (direct template)
- `C:/Users/rickw/projects/agent42/tests/test_model_catalog.py` — TestGroqSpendingTracker pattern (direct template)
- `C:/Users/rickw/projects/agent42/.planning/REQUIREMENTS.md` — MIST-01 through MIST-05 exact specs
- `C:/Users/rickw/projects/agent42/.planning/phases/02-groq-integration/02-RESEARCH.md` — Phase 2 patterns to replicate
- `developer.puter.com` (via WebSearch) — Confirmed `AsyncOpenAI(base_url="https://api.mistral.ai/v1", api_key=...)` is the correct pattern for OpenAI-compatible access
- `docs.mistral.ai/capabilities/code_generation` — Confirmed `codestral-latest` as the model ID for chat completions
- Mistral Codestral announcement (`mistral.ai/news/codestral`) — Confirmed `codestral.mistral.ai` as the dedicated endpoint; confirmed `CODESTRAL_API_KEY` separate from main API key

### Secondary (MEDIUM confidence)
- Multiple web sources confirmed 2 RPM rate limit for Mistral La Plateforme free experiment plan (consistent with STATE.md note)
- `pricepertoken.com/pricing-page/provider/mistral-ai` — Pricing data for La Plateforme models: Large ~$2.00/$6.00, Small ~$0.20/$0.60 per M tokens (secondary source, pricing may float with `latest` alias)
- `docs.litellm.ai/docs/providers/codestral` — Confirmed `CODESTRAL_API_KEY` environment variable name; confirmed `codestral-latest` model ID

### Tertiary (LOW confidence)
- REQUIREMENTS.md `32K context` for Codestral — Some current sources list 256K for `codestral-latest`; implementation uses 32K per requirements spec
- Pricing figures for `mistral-large-latest` — The `latest` alias may point to `2411` ($2.00/$6.00) or `2512` ($0.50/$1.50); conservative high estimate used

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — OpenAI compatibility confirmed by multiple sources; no new dependencies; identical pattern to Phases 1 and 2
- Architecture: HIGH — Two-ProviderSpec pattern is the correct interpretation of MIST-01 + MIST-02; both ProviderType values already in enum
- Model IDs: HIGH — `codestral-latest`, `mistral-large-latest`, `mistral-small-latest` confirmed as stable aliases via official docs and community
- Pitfalls: HIGH — Enum duplication and _BUILTIN_PRICES key format pitfalls are direct extensions of verified Phase 1/2 pitfalls
- Pricing for La Plateforme: MEDIUM — Multiple aggregator sources agree on ~$2/$6 for Large and ~$0.20/$0.60 for Small, but `latest` alias version is unverified
- Codestral context window: MEDIUM — 32K used per requirements spec; some sources indicate larger (open question documented)
- Codestral rate limit: MEDIUM — 30 RPM per PROJECT.md; not independently verified for current (March 2026) accounts

**Research date:** 2026-03-02
**Valid until:** 2026-04-02 (Mistral moves fast; verify model IDs and pricing before implementation if delayed more than 2 weeks)
