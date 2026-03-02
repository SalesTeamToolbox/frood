# Phase 2: Groq Integration - Research

**Researched:** 2026-03-02
**Domain:** Provider registry extension — Groq API integration following the Phase 1 Cerebras pattern
**Confidence:** HIGH

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| GROQ-01 | Register ProviderType.GROQ with ProviderSpec (base_url: `https://api.groq.com/openai/v1`, api_key_env: `GROQ_API_KEY`) | Confirmed via official Groq OpenAI-compatibility docs — `AsyncOpenAI(base_url="https://api.groq.com/openai/v1", api_key=key)` is the standard pattern |
| GROQ-02 | Register ModelSpec entries — `groq-llama-70b` (131K context, 280 tok/s), `groq-gpt-oss-120b` (131K context, 500 tok/s), `groq-llama-8b` (131K context, 560 tok/s) | All 3 model IDs, context windows, and speeds verified via Groq official docs. Model IDs: `llama-3.3-70b-versatile`, `openai/gpt-oss-120b`, `llama-3.1-8b-instant` |
| GROQ-03 | All Groq models classified as ModelTier.FREE | Groq offers a free plan (no credit card required) with all 3 models available. However, the developer paid tier charges per-token. ModelTier.FREE is the correct classification for the free-plan intent — see pricing note below. |
| GROQ-04 | Add $0 pricing entries to SpendingTracker for all Groq model IDs | Must add model_ids to `_BUILTIN_PRICES` at `(0.0, 0.0)` — same pattern as Cerebras. The Groq model IDs do NOT match `or-free-` or `:free` patterns, so explicit entries are required. |
</phase_requirements>

---

## Summary

Phase 2 adds Groq as Agent42's second non-OpenRouter, non-Google free LLM provider. This is a near-identical implementation to Phase 1 (Cerebras) — the same 4-step pattern applies: add ProviderSpec to PROVIDERS, add 3 ModelSpec entries to MODELS, add $0 pricing to `_BUILTIN_PRICES`, add `groq_api_key` to Settings. The ProviderType.GROQ enum value already exists from Phase 1 (INFR-01 added all 6 enum values), so Phase 2 starts one step ahead.

Groq exposes a fully OpenAI-compatible API at `https://api.groq.com/openai/v1`. The existing `AsyncOpenAI(base_url=..., api_key=..., max_retries=0)` pattern used throughout `providers/registry.py` works without any SDK dependency. Three models are specified: `llama-3.3-70b-versatile` (70B, 131K context, ~280 tok/s, 30 RPM free), `openai/gpt-oss-120b` (120B MoE, 131K context, ~500 tok/s, 30 RPM free), `llama-3.1-8b-instant` (8B, 131K context, ~560 tok/s, 30 RPM free).

**Pricing note (important distinction):** Groq's pricing page shows per-token costs for the developer tier ($0.15/$0.60 per million for gpt-oss-120b, $0.05/$0.08 for llama-8b). However, Groq also offers a free plan (no credit card required) with rate-limited access to the same models. The requirements spec classifies Groq as FREE (GROQ-03) and mandates $0 SpendingTracker entries (GROQ-04). This aligns with the "free plan" intent where Agent42 users may be on the free plan. `ModelTier.FREE` + `_BUILTIN_PRICES` at `(0.0, 0.0)` is the correct implementation. If a user is on the developer paid tier, they accept per-token charges directly with Groq — Agent42 simply does not double-account them.

**Primary recommendation:** Add GROQ ProviderSpec + 3 ModelSpec entries + 3 `_BUILTIN_PRICES` entries in `providers/registry.py`. Add `groq_api_key` to `Settings` in `core/config.py`. Update `.env.example`. Add registration and spending tests. Follow the Cerebras pattern exactly — this is a strict replication with different model IDs and base URL.

---

## Standard Stack

### Core (already in project — no new dependencies)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `openai` (AsyncOpenAI) | already installed | HTTP client for Groq API | Groq is OpenAI-compatible; no new SDK needed |
| `pytest` + `pytest-asyncio` | already installed | Test framework | Project standard — `asyncio_mode = "auto"` in pyproject.toml |

### No New Dependencies

Groq does not require the `groq` Python package. The project uses `AsyncOpenAI(base_url=..., api_key=..., max_retries=0)` for all providers, and Groq explicitly supports this via their OpenAI compatibility layer.

**Installation:** No new packages needed for this phase.

---

## Architecture Patterns

### Recommended File Structure for Changes

```
providers/
└── registry.py          # GROQ ProviderSpec, 3 Groq ModelSpecs, $0 pricing entries
core/
└── config.py            # Add groq_api_key field to Settings
.env.example             # Document GROQ_API_KEY
tests/
└── test_providers.py    # Add TestGroqRegistration class
tests/
└── test_model_catalog.py  # Add TestGroqSpendingTracker class (or tests within existing)
```

### Pattern 1: ProviderSpec for Groq (GROQ-01)

**What:** Add to `PROVIDERS: dict[ProviderType, ProviderSpec]` in `providers/registry.py`
**When to use:** Immediately after the Cerebras entry for logical grouping
**Example:**
```python
# Source: console.groq.com/docs/openai — confirmed AsyncOpenAI-compatible
ProviderType.GROQ: ProviderSpec(
    provider_type=ProviderType.GROQ,
    base_url="https://api.groq.com/openai/v1",
    api_key_env="GROQ_API_KEY",
    display_name="Groq",
    supports_function_calling=True,
    # Note: requires_model_prefix=False (default) — model IDs are bare strings
    # or "openai/model-name" prefix for gpt-oss-120b
),
```

Note: `default_model` is optional and should be left empty or omitted (no need to set a default since routing handles model selection). The `requires_model_prefix=False` default is correct — Groq uses bare model IDs or provider-prefixed IDs like `openai/gpt-oss-120b` which are passed verbatim to the API.

### Pattern 2: ModelSpec entries for Groq (GROQ-02)

**What:** Add 3 entries to `MODELS: dict[str, ModelSpec]` in the FREE TIER section
**When to use:** Immediately after the Cerebras model entries, before CHEAP tier
**Example:**
```python
# Source: console.groq.com/docs/models — all IDs, speeds, context windows verified
# All free-plan models (30 RPM, rate-limited, no credit card on free tier)

"groq-llama-70b": ModelSpec(
    model_id="llama-3.3-70b-versatile",
    provider=ProviderType.GROQ,
    max_tokens=8192,
    display_name="Llama 3.3 70B (Groq)",
    tier=ModelTier.FREE,
    max_context_tokens=131000,  # 131,072 per official docs
),
"groq-gpt-oss-120b": ModelSpec(
    model_id="openai/gpt-oss-120b",
    provider=ProviderType.GROQ,
    max_tokens=8192,
    display_name="GPT-OSS 120B (Groq)",
    tier=ModelTier.FREE,
    max_context_tokens=131000,  # 131,072 per official docs
),
"groq-llama-8b": ModelSpec(
    model_id="llama-3.1-8b-instant",
    provider=ProviderType.GROQ,
    max_tokens=4096,
    display_name="Llama 3.1 8B Instant (Groq)",
    tier=ModelTier.FREE,
    max_context_tokens=131000,  # 131,072 per official docs
),
```

### Pattern 3: SpendingTracker $0 pricing (GROQ-04)

**What:** Add 3 entries to `_BUILTIN_PRICES` at `(0.0, 0.0)` for the Groq model IDs
**When to use:** Immediately after Cerebras entries in `_BUILTIN_PRICES`
**Example:**
```python
# Source: Requirements spec + free-plan intent (no credit card)
# Keyed by model_id (the actual API string), not model_key

# Groq free plan — $0 for Agent42 tracking purposes (free plan, rate-limited)
"llama-3.3-70b-versatile": (0.0, 0.0),
"openai/gpt-oss-120b": (0.0, 0.0),
"llama-3.1-8b-instant": (0.0, 0.0),
```

**Critical:** The model IDs must match exactly what is in the `ModelSpec.model_id` fields above. `_BUILTIN_PRICES` is keyed by `model_id` (the string passed to the Groq API), not by the `model_key` used internally in Agent42.

### Pattern 4: Settings dataclass field addition

**What:** Add `groq_api_key: str = ""` to `Settings` in `core/config.py`
**When to use:** In the "API keys — providers" block, after `cerebras_api_key`
**Example:**
```python
# core/config.py Settings dataclass — add after cerebras_api_key
groq_api_key: str = ""

# Settings.from_env() — add after cerebras_api_key line:
groq_api_key=os.getenv("GROQ_API_KEY", ""),
```

Note: `ProviderRegistry._build_client()` reads `os.getenv(spec.api_key_env, "")` directly (NOT `settings.groq_api_key`). The Settings field exists for introspection/reporting only. This is the same pattern as `cerebras_api_key` added in Phase 1.

### Pattern 5: .env.example documentation

**What:** Add `GROQ_API_KEY` line to `.env.example` near the Cerebras entry
**When to use:** Immediately after the Cerebras block
**Example:**
```bash
# Groq — free inference (rate-limited on free plan, no credit card required)
# Sign up: https://console.groq.com/
# GROQ_API_KEY=gsk_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

### Anti-Patterns to Avoid

- **Do not add a `groq` Python package dependency:** `AsyncOpenAI(base_url="https://api.groq.com/openai/v1", api_key=key)` is the correct approach. The `groq` SDK is not needed.
- **Do not set `requires_model_prefix=True`:** Groq model IDs like `llama-3.3-70b-versatile` are bare strings. The `openai/gpt-oss-120b` prefix is part of the model ID itself (included in the ModelSpec.model_id), not a provider routing prefix.
- **Do not add Groq to FREE_ROUTING in Phase 2:** Routing changes are Phase 6 (ROUT-03). Phase 2 only registers the provider; Phase 6 routes traffic to it.
- **Do not update `test_all_providers_registered` expected set without adding "groq":** After adding GROQ to PROVIDERS, the test set must include `"groq"` or it will be stale.
- **Do not use `max_context_tokens=131072`:** Use `131000` for safety (same conservative rounding pattern used for Cerebras's 65K -> 65000).
- **Do not register ProviderType.GROQ in the enum:** It was already added in Phase 1 (INFR-01). Do NOT duplicate it.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| HTTP client for Groq | Custom requests.Session or httpx client | `AsyncOpenAI(base_url="https://api.groq.com/openai/v1", ...)` | Groq is OpenAI-compatible; same client used for all providers |
| Free-tier rate limiting enforcement | Custom RPM counter | Provider-side enforcement | Groq enforces 30 RPM / rate limits server-side on free plan |
| Model ID validation | Runtime API call to list models | Static MODELS dict entries | All 3 model IDs are verified production models per official docs |
| Per-token cost accounting for Groq | Custom pricing logic | `_BUILTIN_PRICES` at `(0.0, 0.0)` | Free plan intent; consistent with Cerebras pattern from Phase 1 |

**Key insight:** Phase 2 is 100% additive declarations in existing data structures — identical architecture to Phase 1 with different model IDs and base URL. There is no novel algorithm to write.

---

## Common Pitfalls

### Pitfall 1: Groq model IDs trip the conservative spend fallback
**What goes wrong:** Groq model IDs (`llama-3.3-70b-versatile`, `openai/gpt-oss-120b`, `llama-3.1-8b-instant`) don't match the `or-free-` prefix or `:free` suffix patterns. `SpendingTracker._get_price()` falls through to the conservative fallback ($5/$15 per million tokens). After a few tasks, the daily spend cap triggers and blocks all requests.
**Why it happens:** The same root cause as Cerebras in Phase 1 — free-model detection was designed only for OpenRouter naming conventions.
**How to avoid:** Add all 3 Groq model IDs to `_BUILTIN_PRICES` at `(0.0, 0.0)` (GROQ-04). This is required before any Groq model can safely be used.
**Warning signs:** `SpendingLimitExceeded` exception triggered after just 1-2 tasks; `daily_spend_usd` shows non-zero value for Groq calls.

### Pitfall 2: ProviderType.GROQ already exists — do not add it again
**What goes wrong:** Phase 1 (INFR-01) already added `GROQ = "groq"` to the `ProviderType` enum. Adding it again causes a Python `ValueError: duplicate member 'GROQ' in Enum`.
**Why it happens:** Phase 1 pre-populated all 6 future enum values per INFR-01.
**How to avoid:** Verify `ProviderType.GROQ` already exists in `providers/registry.py` before writing. Only add the `ProviderSpec` to `PROVIDERS` — not the enum value.
**Warning signs:** `ValueError: duplicate member` on import; `AttributeError: GROQ` if you accidentally reference a non-existent value.

### Pitfall 3: `openai/gpt-oss-120b` model ID includes the `openai/` prefix
**What goes wrong:** Passing just `gpt-oss-120b` as the model_id instead of `openai/gpt-oss-120b` to Groq's API results in a 404 or model-not-found error. The model is namespaced under the `openai` provider on Groq.
**Why it happens:** Groq hosts models from multiple providers using a `provider/model-name` namespace. For OpenAI OSS models on Groq, the full ID including the `openai/` prefix is required.
**How to avoid:** Use `model_id="openai/gpt-oss-120b"` in the ModelSpec. The `requires_model_prefix=False` flag in ProviderSpec is unrelated — it controls whether the ProviderSpec's own prefix is prepended, not whether the model_id itself contains slashes.
**Warning signs:** 404 errors from Groq API; "model not found" responses.

### Pitfall 4: `test_all_providers_registered` expected set needs updating
**What goes wrong:** `tests/test_providers.py::TestProviderRegistry::test_all_providers_registered` has `expected = {"openai", "anthropic", "deepseek", "gemini", "openrouter", "vllm", "cerebras"}`. Adding GROQ to PROVIDERS without updating this test results in a stale (though still-passing) expected set. Future tests that check exact membership will fail.
**Why it happens:** The test uses `issubset`, so adding a new provider doesn't break it — but the intent of the test is to verify all expected providers are registered.
**How to avoid:** Add `"groq"` to the expected set when adding GROQ to PROVIDERS.
**Warning signs:** Test passes but expected set doesn't include groq; future equality checks fail.

### Pitfall 5: `_BUILTIN_PRICES` key must match model_id exactly (including `openai/` prefix)
**What goes wrong:** Adding `"gpt-oss-120b": (0.0, 0.0)` instead of `"openai/gpt-oss-120b": (0.0, 0.0)` means the $0 price lookup fails. `_get_price` receives `model_id="openai/gpt-oss-120b"` (from ModelSpec.model_id) and doesn't find a match in `_BUILTIN_PRICES`. Falls through to conservative fallback.
**Why it happens:** The `_BUILTIN_PRICES` key must be the exact string sent to the API — which for this model includes the `openai/` namespace prefix.
**How to avoid:** Ensure the key in `_BUILTIN_PRICES` exactly matches the `model_id` field in the corresponding `ModelSpec`. Copy-paste from the ModelSpec to avoid typos.
**Warning signs:** `daily_spend_usd` is non-zero after Groq calls even though you added `_BUILTIN_PRICES`; `SpendingLimitExceeded` triggered unexpectedly.

### Pitfall 6: Free tier rate limits are 30 RPM, not 1K RPM
**What goes wrong:** The REQUIREMENTS.md spec says "1K RPM" in the Groq model descriptions. Official Groq docs show 30 RPM for free tier users.
**Why it happens:** The 1K RPM figure in requirements may refer to the developer (paid) tier rate limits, not the free tier. The free plan has 30 RPM, 12K TPM, 100K TPD for the 70B model.
**How to avoid:** ModelSpec does not have an RPM field — this is metadata-only in Phase 2. No implementation impact. Document the discrepancy in a code comment if throughput metadata is added in the future.
**Warning signs:** None — this doesn't affect the implementation, only documentation accuracy.

---

## Code Examples

Verified patterns from official sources:

### GROQ-01: ProviderSpec registration
```python
# Source: console.groq.com/docs/openai — confirmed AsyncOpenAI-compatible
ProviderType.GROQ: ProviderSpec(
    provider_type=ProviderType.GROQ,
    base_url="https://api.groq.com/openai/v1",
    api_key_env="GROQ_API_KEY",
    display_name="Groq",
    supports_function_calling=True,
    # Note: requires_model_prefix=False (default) — model IDs are passed verbatim
),
```

### GROQ-02: ModelSpec registrations
```python
# Source: console.groq.com/docs/models — verified IDs, speeds, context windows (March 2026)
# All 3 models on Groq free plan (no credit card required, 30 RPM limit)

"groq-llama-70b": ModelSpec(
    model_id="llama-3.3-70b-versatile",
    provider=ProviderType.GROQ,
    max_tokens=8192,
    display_name="Llama 3.3 70B (Groq)",
    tier=ModelTier.FREE,
    max_context_tokens=131000,   # 131,072 per official docs
    # Free plan: 30 RPM, 12K TPM, 100K TPD
),
"groq-gpt-oss-120b": ModelSpec(
    model_id="openai/gpt-oss-120b",    # IMPORTANT: includes "openai/" namespace prefix
    provider=ProviderType.GROQ,
    max_tokens=8192,
    display_name="GPT-OSS 120B (Groq)",
    tier=ModelTier.FREE,
    max_context_tokens=131000,   # 131,072 per official docs
    # Free plan: 30 RPM, 8K TPM, 200K TPD
),
"groq-llama-8b": ModelSpec(
    model_id="llama-3.1-8b-instant",
    provider=ProviderType.GROQ,
    max_tokens=4096,
    display_name="Llama 3.1 8B Instant (Groq)",
    tier=ModelTier.FREE,
    max_context_tokens=131000,   # 131,072 per official docs
    # Free plan: 30 RPM, 6K TPM, 500K TPD
),
```

### GROQ-04: SpendingTracker $0 pricing
```python
# Source: requirements spec + free-plan intent
# Keys must EXACTLY match ModelSpec.model_id values (including namespaces)

# Groq free plan — $0 for Agent42 tracking (free plan, rate-limited by Groq)
"llama-3.3-70b-versatile": (0.0, 0.0),
"openai/gpt-oss-120b": (0.0, 0.0),     # IMPORTANT: "openai/" prefix required
"llama-3.1-8b-instant": (0.0, 0.0),
```

### TEST-01: Provider registration tests (Groq)
```python
# Source: tests/test_providers.py::TestCerebrasRegistration — follow this pattern exactly

class TestGroqRegistration:
    """Phase 2: Groq provider registration tests."""

    def test_groq_provider_registered(self):
        """Groq ProviderSpec is in PROVIDERS with correct base_url and api_key_env."""
        spec = PROVIDERS[ProviderType.GROQ]
        assert spec.base_url == "https://api.groq.com/openai/v1"
        assert spec.api_key_env == "GROQ_API_KEY"
        assert spec.display_name == "Groq"

    def test_groq_models_registered(self):
        """All 3 Groq models are registered with correct model_ids."""
        expected = {
            "groq-llama-70b": "llama-3.3-70b-versatile",
            "groq-gpt-oss-120b": "openai/gpt-oss-120b",
            "groq-llama-8b": "llama-3.1-8b-instant",
        }
        for model_key, expected_id in expected.items():
            spec = MODELS[model_key]
            assert spec.model_id == expected_id, f"{model_key} model_id mismatch"
            assert spec.provider == ProviderType.GROQ

    def test_groq_models_all_free_tier(self):
        """All Groq models are classified as FREE tier."""
        from providers.registry import ModelTier
        groq_models = [k for k, v in MODELS.items() if v.provider == ProviderType.GROQ]
        assert len(groq_models) == 3
        for key in groq_models:
            assert MODELS[key].tier == ModelTier.FREE, f"{key} is not FREE tier"

    def test_groq_context_windows(self):
        """All Groq models have the expected 131K context window."""
        for key in ["groq-llama-70b", "groq-gpt-oss-120b", "groq-llama-8b"]:
            assert MODELS[key].max_context_tokens == 131000

    def test_groq_client_builds_with_key(self):
        """Client builds successfully when GROQ_API_KEY is set."""
        registry = ProviderRegistry()
        with patch.dict(os.environ, {"GROQ_API_KEY": "gsk-test-key-1234"}):
            client = registry.get_client(ProviderType.GROQ)
            assert client is not None
            assert client.base_url == "https://api.groq.com/openai/v1/"

    def test_groq_client_raises_without_key(self):
        """Client raises ValueError when GROQ_API_KEY is not set."""
        registry = ProviderRegistry()
        registry.invalidate_client(ProviderType.GROQ)
        with patch.dict(os.environ, {"GROQ_API_KEY": ""}, clear=False):
            with pytest.raises(ValueError, match="GROQ_API_KEY not set"):
                registry.get_client(ProviderType.GROQ)
```

### TEST-02: SpendingTracker $0 pricing tests (Groq)
```python
# Source: tests/test_model_catalog.py::TestCerebrasSpendingTracker — follow this pattern

class TestGroqSpendingTracker:
    """Phase 2: Groq $0 pricing tests."""

    def test_groq_llama_70b_zero_cost(self):
        tracker = SpendingTracker()
        tracker.record_usage("groq-llama-70b", 10000, 5000,
                             model_id="llama-3.3-70b-versatile")
        assert tracker.daily_spend_usd == 0.0

    def test_groq_gpt_oss_120b_zero_cost(self):
        tracker = SpendingTracker()
        tracker.record_usage("groq-gpt-oss-120b", 10000, 5000,
                             model_id="openai/gpt-oss-120b")
        assert tracker.daily_spend_usd == 0.0

    def test_groq_llama_8b_zero_cost(self):
        tracker = SpendingTracker()
        tracker.record_usage("groq-llama-8b", 5000, 2000,
                             model_id="llama-3.1-8b-instant")
        assert tracker.daily_spend_usd == 0.0

    def test_groq_no_spend_cap_trip(self):
        """Groq usage must not trigger SpendingLimitExceeded at any sane cap."""
        tracker = SpendingTracker()
        # Simulate 50 tasks x 10K tokens each
        for _ in range(50):
            tracker.record_usage("groq-llama-70b", 8000, 2000,
                                 model_id="llama-3.3-70b-versatile")
        assert tracker.daily_spend_usd == 0.0
        assert tracker.check_limit(1.0)   # $1 cap should never be hit
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| OpenRouter as only free provider | OpenRouter + Cerebras (Phase 1) + Groq (Phase 2) | Phase 2 | Provider diversity; Groq adds 131K context free models |
| Free model detection by naming convention | Explicit `_BUILTIN_PRICES` at `(0.0, 0.0)` | Phase 1 | Supports any free provider regardless of naming |
| `ProviderType` enum has 7 values | 13 values (7 existing + 6 added in Phase 1) | Phase 1 (INFR-01) | Phase 2 only needs to add ProviderSpec to PROVIDERS |

**Deprecated/outdated:**
- Nothing is removed in Phase 2 — all changes are additive.

---

## Open Questions

1. **Groq free tier pricing vs. developer tier pricing**
   - What we know: Groq has a free plan (no credit card required, rate-limited) and a developer paid plan (per-token, higher limits). The requirements spec mandates ModelTier.FREE and $0 SpendingTracker entries.
   - What's unclear: Whether Agent42 users on the developer tier expect cost tracking for Groq calls. If so, the `_BUILTIN_PRICES` $0 approach would under-report costs.
   - Recommendation: Implement $0 as required (GROQ-04). If a user is on developer tier, Groq charges them directly — Agent42 does not need to double-account. This is the same logic applied to Cerebras. Add a comment in the code documenting this decision.

2. **Free tier RPM discrepancy with requirements**
   - What we know: Requirements say "1K RPM". Official Groq docs say 30 RPM for free tier (1K RPD for some models — "RPD" not "RPM").
   - What's unclear: Whether requirements spec meant 1K RPD (requests per day) or whether it referred to a developer tier limit.
   - Recommendation: This is metadata-only — `ModelSpec` has no RPM field, so this doesn't affect implementation. Document the verified rate limits in code comments (30 RPM, 12K TPM, 100K TPD for the 70B) and move on. No code change needed.

3. **`openai/gpt-oss-120b` — namespace prefix requirement**
   - What we know: Confirmed via Groq docs that the model ID on Groq is `openai/gpt-oss-120b` (with the `openai/` prefix). This is different from Cerebras where the same base model is called `gpt-oss-120b` (no prefix).
   - What's unclear: Whether Groq will add an alias without the prefix in the future.
   - Recommendation: Use `model_id="openai/gpt-oss-120b"` exactly as documented. If Groq adds an alias, update the ModelSpec accordingly. Do not try to "normalize" the ID — pass it verbatim to the API.

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
| GROQ-01 | `ProviderType.GROQ` in `PROVIDERS` with correct base_url and api_key_env | unit | `pytest tests/test_providers.py::TestGroqRegistration::test_groq_provider_registered -x` | ❌ Wave 0 |
| GROQ-02 | All 3 Groq model keys in `MODELS` with correct model_id and specs | unit | `pytest tests/test_providers.py::TestGroqRegistration::test_groq_models_registered -x` | ❌ Wave 0 |
| GROQ-03 | All 3 Groq models have `tier == ModelTier.FREE` | unit | `pytest tests/test_providers.py::TestGroqRegistration::test_groq_models_all_free_tier -x` | ❌ Wave 0 |
| GROQ-04 | `SpendingTracker.record_usage()` produces $0 for all 3 Groq model IDs | unit | `pytest tests/test_model_catalog.py -k "groq" -x` | ❌ Wave 0 |

Additional tests to add (not directly mapped to GROQ-XX but covering success criteria):
- `test_groq_client_builds_with_key` — covers "Agent42 starts without error when GROQ_API_KEY is set"
- `test_groq_client_raises_without_key` — covers "Agent42 starts without error when GROQ_API_KEY is absent"
- `test_groq_context_windows` — covers "Three Groq ModelSpec entries exist with correct context windows"
- `test_groq_no_spend_cap_trip` — covers "A task routed to a Groq model incurs $0 in SpendingTracker"

### Sampling Rate

- **Per task commit:** `python -m pytest tests/test_providers.py tests/test_model_catalog.py -x -q`
- **Per wave merge:** `python -m pytest tests/ -x -q`
- **Phase gate:** Full suite green (`python -m pytest tests/ -x -q`) before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/test_providers.py` — needs `TestGroqRegistration` class added (file exists, class does not)
- [ ] `tests/test_model_catalog.py` — needs `TestGroqSpendingTracker` class added (file exists, class does not)

Note: No framework install needed — pytest and pytest-asyncio already installed per `requirements-dev.txt`.

---

## Sources

### Primary (HIGH confidence)
- `console.groq.com/docs/openai` — Confirmed `AsyncOpenAI` with `base_url="https://api.groq.com/openai/v1"` works
- `console.groq.com/docs/models` — All 3 model IDs, speeds, and context windows verified
- `console.groq.com/docs/model/llama-3.3-70b-versatile` — Model ID `llama-3.3-70b-versatile`, 131,072 context, ~280 tok/s
- `console.groq.com/docs/model/llama-3.1-8b-instant` — Model ID `llama-3.1-8b-instant`, 131,072 context, ~560 tok/s
- `console.groq.com/docs/model/openai/gpt-oss-120b` — Model ID `openai/gpt-oss-120b`, 131,072 context, ~500 tok/s, $0.15/$0.60 per M tokens (developer tier)
- `console.groq.com/docs/rate-limits` — Free tier rate limits: 30 RPM, 12K TPM, 100K TPD (llama-70b); 8K TPM, 200K TPD (gpt-oss-120b); 6K TPM, 500K TPD (llama-8b)
- `C:/Users/rickw/projects/agent42/providers/registry.py` — Current codebase patterns for ProviderType, ProviderSpec, ModelSpec, SpendingTracker (Phase 1 Cerebras as template)
- `C:/Users/rickw/projects/agent42/tests/test_providers.py` — Existing TestCerebrasRegistration pattern to follow
- `C:/Users/rickw/projects/agent42/core/config.py` — Existing Settings pattern for `cerebras_api_key` to follow

### Secondary (MEDIUM confidence)
- `community.groq.com/t/is-there-a-free-tier-and-what-are-its-limits/790` — Groq free plan confirmed: no credit card required, capped by rate limits
- `groq.com/blog/day-zero-support-for-openai-open-models` — Groq hosts OpenAI OSS models including gpt-oss-120b

### Tertiary (LOW confidence)
- REQUIREMENTS.md "1K RPM" for Groq models — Conflicts with official docs (30 RPM free tier). Likely refers to developer tier or RPD. No implementation impact.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — OpenAI compatibility confirmed by official docs; no new dependencies
- Architecture: HIGH — identical pattern to Phase 1 Cerebras; tested approach
- Model IDs: HIGH — all 3 model IDs verified via official Groq docs pages
- Pitfalls: HIGH — `_BUILTIN_PRICES` key format read directly from codebase; `openai/` prefix pitfall verified via docs
- Rate limits: MEDIUM — 30 RPM (free tier) verified; "1K RPM" in requirements is LOW confidence (contradicted by official docs)

**Research date:** 2026-03-02
**Valid until:** 2026-04-02 (Groq is a fast-moving company; verify model IDs and rate limits before implementation if delayed)
