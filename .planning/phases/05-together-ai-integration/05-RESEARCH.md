# Phase 5: Together AI Integration - Research

**Researched:** 2026-03-02
**Domain:** Provider registry extension — ProviderSpec + ModelSpec registration, SpendingTracker credit pricing (no request transforms needed)
**Confidence:** HIGH

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| TOGR-01 | Register ProviderType.TOGETHER with ProviderSpec (base_url: `https://api.together.xyz/v1`, api_key_env: `TOGETHER_API_KEY`) | ProviderType.TOGETHER already in enum (Phase 1 INFR-01). Only ProviderSpec entry in PROVIDERS dict needed. Together AI exposes OpenAI-compatible endpoint. |
| TOGR-02 | Register ModelSpec entries — `together-deepseek-v3` (DeepSeek-V3-0324 weights, model_id: `deepseek-ai/DeepSeek-V3`), `together-llama-70b` (meta-llama/Llama-3.3-70B-Instruct-Turbo), classified as ModelTier.CHEAP | Both model IDs verified via official docs. CHEAP tier correct (credits-based). SpendingTracker pricing entries required for both. No request transforms needed (Together AI is spec-compliant). |
| TOGR-03 | Add credit-based pricing to SpendingTracker for Together AI models | Non-zero pricing entries in `_BUILTIN_PRICES` keyed by exact model_id strings. Together AI pricing: Llama 3.3 70B ~$0.88/M in+out, DeepSeek-V3 varies by source ($0.60-$1.25/M in). Use conservative estimates. |
</phase_requirements>

---

## Summary

Phase 5 is a **pure registration phase** — identical in structure to Phases 1-3 (Cerebras, Groq, Mistral La Plateforme) and the registration portion of Phase 4. Unlike Phase 4 (SambaNova), Together AI does not require any request transforms. The Together AI API is a standard OpenAI-compatible endpoint that accepts the full parameter set including `temperature > 1.0`, standard tool schemas with `strict: true`, and streaming.

The three requirements (TOGR-01, TOGR-02, TOGR-03) map directly to three code changes: one ProviderSpec entry in `PROVIDERS`, two ModelSpec entries in `MODELS` (CHEAP tier), and two pricing entries in `_BUILTIN_PRICES`. A Settings field (`together_api_key`) and `.env.example` documentation round out the implementation. Tests follow the established `TestTogetherRegistration` (6 tests) + `TestTogetherSpendingTracker` (5 tests) pattern.

The key nuance for Phase 5 is the **model ID format**: Together AI uses a namespaced `org/ModelName` format (e.g. `deepseek-ai/DeepSeek-V3`, `meta-llama/Llama-3.3-70B-Instruct-Turbo`). The REQUIREMENTS.md description references the underlying model weights (`DeepSeek-V3-0324`) but the actual Together AI API model_id is `deepseek-ai/DeepSeek-V3` — the endpoint that currently serves those weights. This is analogous to how SambaNova uses mixed-case model IDs that must match exactly.

**Primary recommendation:** Add one ProviderSpec to PROVIDERS, two ModelSpecs to MODELS (CHEAP tier, namespaced model IDs), two non-zero pricing entries to `_BUILTIN_PRICES`, one Settings field, one `.env.example` block, and two test classes following the established pattern from prior phases.

---

## Standard Stack

### Core (already in project — no new dependencies)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `openai` (AsyncOpenAI) | already installed | HTTP client for Together AI API | Together AI exposes OpenAI-compatible `/v1/chat/completions`; no native SDK needed |
| `pytest` + `pytest-asyncio` | already installed | Test framework | Project standard — `asyncio_mode = "auto"` in pyproject.toml |
| `unittest.mock` | stdlib | Mock environment for tests | Standard pattern across all existing provider tests |

**Installation:** No new packages needed for this phase.

---

## Architecture Patterns

### Recommended File Structure for Changes

```
providers/
└── registry.py          # 1x ProviderSpec, 2x ModelSpec, 2x pricing entries
core/
└── config.py            # Add together_api_key field to Settings
.env.example             # Document TOGETHER_API_KEY
tests/
└── test_providers.py    # Add TestTogetherRegistration class (6 tests)
tests/
└── test_model_catalog.py  # Add TestTogetherSpendingTracker class (5 tests)
```

### Pattern 1: ProviderSpec registration (TOGR-01)

**What:** Add one entry to `PROVIDERS` dict after the `SAMBANOVA` entry (before the closing brace `}`).
**When to use:** Single entry — Together AI has one API endpoint and one API key.

```python
# Source: REQUIREMENTS.md TOGR-01 + Together AI official docs (OpenAI-compatible)
ProviderType.TOGETHER: ProviderSpec(
    provider_type=ProviderType.TOGETHER,
    base_url="https://api.together.xyz/v1",
    api_key_env="TOGETHER_API_KEY",
    display_name="Together AI",
    supports_function_calling=True,
),
```

**CRITICAL:** `ProviderType.TOGETHER` already exists in the enum (added in Phase 1 INFR-01). Do NOT add it again. Only add the ProviderSpec to the PROVIDERS dict.

### Pattern 2: ModelSpec entries — two CHEAP models (TOGR-02)

**What:** Add 2 entries to `MODELS` in the CHEAP TIER section, after the SambaNova entries.

```python
# Together AI (credits-based, funded account required — OpenAI-compatible endpoint)
# NOTE: Together AI uses "org/ModelName" namespaced model IDs
# "deepseek-ai/DeepSeek-V3" serves DeepSeek-V3-0324 weights (updated March 2025)
"together-deepseek-v3": ModelSpec(
    "deepseek-ai/DeepSeek-V3",
    ProviderType.TOGETHER,
    max_tokens=4096,
    temperature=0.3,
    display_name="DeepSeek V3 (Together AI)",
    tier=ModelTier.CHEAP,
    max_context_tokens=128000,   # 128K context window
),
"together-llama-70b": ModelSpec(
    "meta-llama/Llama-3.3-70B-Instruct-Turbo",
    ProviderType.TOGETHER,
    max_tokens=4096,
    temperature=0.3,
    display_name="Llama 3.3 70B Turbo (Together AI)",
    tier=ModelTier.CHEAP,
    max_context_tokens=131000,   # 131K context window (Turbo model)
),
```

**CRITICAL NOTE on model IDs:** Together AI uses org-namespaced model IDs in `org/ModelName` format. The REQUIREMENTS.md description references `DeepSeek-V3-0324` (the underlying model weights) but the Together AI API model ID is `deepseek-ai/DeepSeek-V3` — this is the endpoint that serves those weights after Together AI updated it on March 24, 2025. The `_BUILTIN_PRICES` key must match the `ModelSpec.model_id` exactly.

### Pattern 3: SpendingTracker pricing entries (TOGR-03)

**What:** Add 2 entries to `_BUILTIN_PRICES`. Together AI is CHEAP (not free), so non-zero pricing prevents conservative fallback overestimation.

```python
# Together AI — credits-based (CHEAP tier), per-token pricing
# Source: https://www.together.ai/pricing (March 2026)
# Keys include "org/" prefix — must match ModelSpec.model_id exactly
"meta-llama/Llama-3.3-70B-Instruct-Turbo": (0.88e-6, 0.88e-6),   # $0.88/M in+out
"deepseek-ai/DeepSeek-V3": (0.60e-6, 1.70e-6),                    # $0.60/M in, $1.70/M out
```

**IMPORTANT:** Keys must include the `org/` prefix to exactly match `ModelSpec.model_id`. The `_get_price()` lookup is case-sensitive and prefix-aware. A mismatch triggers the conservative $5/$15 fallback.

### Pattern 4: Settings field (one new key)

```python
# core/config.py Settings dataclass — add after sambanova_api_key
together_api_key: str = ""

# Settings.from_env() — add after sambanova_api_key line
together_api_key=os.getenv("TOGETHER_API_KEY", ""),
```

### Pattern 5: .env.example documentation

```bash
# Together AI — CHEAP tier (credits required, funded account needed)
# Get key: https://api.together.xyz/settings/api-keys ($1 free credit at signup)
# TOGETHER_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

### Pattern 6: Test classes — registration + spending

Two test classes required, following the identical pattern established in Phases 1-4:

1. `TestTogetherRegistration` in `tests/test_providers.py` (6 tests)
2. `TestTogetherSpendingTracker` in `tests/test_model_catalog.py` (5 tests)

```python
# tests/test_providers.py — after TestSambanovaTransforms
class TestTogetherRegistration:
    """Phase 5: Together AI provider registration tests."""

    def test_together_provider_registered(self):
        """TOGR-01: ProviderType.TOGETHER in PROVIDERS with correct base_url and api_key_env."""
        spec = PROVIDERS[ProviderType.TOGETHER]
        assert spec.base_url == "https://api.together.xyz/v1"
        assert spec.api_key_env == "TOGETHER_API_KEY"
        assert spec.display_name == "Together AI"

    def test_together_models_registered(self):
        """TOGR-02: Both Together AI models registered with correct model_ids and CHEAP tier."""
        for key, expected_id in [
            ("together-deepseek-v3", "deepseek-ai/DeepSeek-V3"),
            ("together-llama-70b", "meta-llama/Llama-3.3-70B-Instruct-Turbo"),
        ]:
            spec = MODELS[key]
            assert spec.model_id == expected_id, f"{key} model_id mismatch"
            assert spec.provider == ProviderType.TOGETHER
            assert spec.tier == ModelTier.CHEAP, f"{key} should be CHEAP tier"

    def test_together_models_all_cheap_tier(self):
        """All Together AI models are CHEAP tier (credits required)."""
        together_models = [k for k, v in MODELS.items() if v.provider == ProviderType.TOGETHER]
        assert len(together_models) == 2
        for key in together_models:
            assert MODELS[key].tier == ModelTier.CHEAP, f"{key} should be CHEAP"

    def test_together_context_windows(self):
        """TOGR-02: Together AI models have appropriate context windows."""
        assert MODELS["together-deepseek-v3"].max_context_tokens == 128000
        assert MODELS["together-llama-70b"].max_context_tokens == 131000

    def test_together_client_builds_with_key(self):
        """Client builds when TOGETHER_API_KEY is set."""
        registry = ProviderRegistry()
        with patch.dict(os.environ, {"TOGETHER_API_KEY": "test-key-1234"}):
            client = registry.get_client(ProviderType.TOGETHER)
            assert client is not None
            assert client.base_url == "https://api.together.xyz/v1/"

    def test_together_client_raises_without_key(self):
        """INFR-05: Client raises ValueError when TOGETHER_API_KEY is not set."""
        registry = ProviderRegistry()
        registry.invalidate_client(ProviderType.TOGETHER)
        with patch.dict(os.environ, {"TOGETHER_API_KEY": ""}, clear=False):
            with pytest.raises(ValueError, match="TOGETHER_API_KEY not set"):
                registry.get_client(ProviderType.TOGETHER)
```

```python
# tests/test_model_catalog.py — after TestSambanovaSpendingTracker
class TestTogetherSpendingTracker:
    """Phase 5: Together AI models — CHEAP tier, non-zero pricing."""

    def test_together_llama_builtin_prices_exist(self):
        """meta-llama/Llama-3.3-70B-Instruct-Turbo has explicit pricing in _BUILTIN_PRICES."""
        from providers.registry import SpendingTracker
        assert "meta-llama/Llama-3.3-70B-Instruct-Turbo" in SpendingTracker._BUILTIN_PRICES
        prompt_price, completion_price = SpendingTracker._BUILTIN_PRICES["meta-llama/Llama-3.3-70B-Instruct-Turbo"]
        assert prompt_price > 0.0
        assert completion_price > 0.0

    def test_together_deepseek_builtin_prices_exist(self):
        """deepseek-ai/DeepSeek-V3 has explicit pricing in _BUILTIN_PRICES."""
        from providers.registry import SpendingTracker
        assert "deepseek-ai/DeepSeek-V3" in SpendingTracker._BUILTIN_PRICES
        prompt_price, completion_price = SpendingTracker._BUILTIN_PRICES["deepseek-ai/DeepSeek-V3"]
        assert prompt_price > 0.0
        assert completion_price > 0.0

    def test_together_llama_incurs_cost(self):
        """Together AI Llama usage records non-zero spend."""
        from providers.registry import SpendingTracker
        tracker = SpendingTracker()
        tracker.record_usage("together-llama-70b", 10000, 5000,
                             model_id="meta-llama/Llama-3.3-70B-Instruct-Turbo")
        assert tracker.daily_spend_usd > 0.0

    def test_together_deepseek_incurs_cost(self):
        """Together AI DeepSeek usage records non-zero spend."""
        from providers.registry import SpendingTracker
        tracker = SpendingTracker()
        tracker.record_usage("together-deepseek-v3", 10000, 5000,
                             model_id="deepseek-ai/DeepSeek-V3")
        assert tracker.daily_spend_usd > 0.0

    def test_together_not_free_model_detection(self):
        """Together AI model IDs don't match or-free- prefix or :free suffix — must have explicit pricing."""
        from providers.registry import SpendingTracker
        tracker = SpendingTracker()
        # Confirm _get_price resolves to explicit entry, not $0 free detection
        price = tracker._get_price("together-llama-70b", "meta-llama/Llama-3.3-70B-Instruct-Turbo")
        assert price is not None
        assert price[0] > 0.0  # Not free
```

### Anti-Patterns to Avoid

- **Do not add ProviderType.TOGETHER to the enum:** It was added in Phase 1 (INFR-01). Adding it again causes `ValueError: duplicate member in Enum`.
- **Do not use plain model weights name as model_id:** The REQUIREMENTS.md description says "DeepSeek-V3-0324" (the upstream model weights name) but the Together AI API model ID is `deepseek-ai/DeepSeek-V3`. Use the API model ID, not the HuggingFace weights name.
- **Do not omit the `org/` prefix in pricing keys:** The `_BUILTIN_PRICES` key must exactly match `ModelSpec.model_id` including the `deepseek-ai/` prefix. A key of `"DeepSeek-V3"` (without prefix) would miss the lookup and trigger the $5/$15 conservative fallback.
- **Do not add Together AI models to FREE_ROUTING:** Together AI is CHEAP tier (credits-based). Routing changes are Phase 6 (ROUT-05). Phase 5 only registers the provider.
- **Do not add request transforms:** Together AI is fully spec-compliant. Unlike SambaNova (Phase 4), Together AI accepts temperature > 1.0, strict: true in tools, and streaming tool calls without issues.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| HTTP client for Together AI | Custom httpx client | `AsyncOpenAI(base_url="https://api.together.xyz/v1", ...)` | Together AI exposes standard OpenAI-compatible endpoint |
| Request transforms | Temperature clamping, strict removal | Nothing — Together AI is spec-compliant | Unlike SambaNova, no known deviations from OpenAI spec |
| Model ID mapping layer | Custom lookup dict for weights-to-API names | Correct `model_id` in ModelSpec | Use `deepseek-ai/DeepSeek-V3` directly, document the weights alias in a comment |

**Key insight:** Phase 5 is simpler than Phase 4. Together AI is a clean OpenAI-compatible provider with no known API quirks. The registration pattern is identical to Phases 1-3.

---

## Common Pitfalls

### Pitfall 1: Using the weights name instead of the API model ID

**What goes wrong:** The REQUIREMENTS.md spec says `DeepSeek-V3-0324` (the model weights identifier from the original DeepSeek paper and HuggingFace). The Together AI API model ID is `deepseek-ai/DeepSeek-V3`. Using `DeepSeek-V3-0324` as the model_id will cause a 404 from the Together AI API.
**Why it happens:** REQUIREMENTS.md uses the canonical model name (weight checkpoint), while Together AI's API uses their own model ID format (`org/ModelName`).
**How to avoid:** Use `deepseek-ai/DeepSeek-V3` as the model_id in ModelSpec. Add a comment: `# Serves DeepSeek-V3-0324 weights (updated March 2025)` for documentation clarity.
**Warning signs:** API call returns 404 or "model not found" error.

### Pitfall 2: Omitting `org/` prefix in `_BUILTIN_PRICES` key

**What goes wrong:** If `_BUILTIN_PRICES["DeepSeek-V3"]` (without `deepseek-ai/` prefix) is used instead of `_BUILTIN_PRICES["deepseek-ai/DeepSeek-V3"]`, `_get_price()` won't find the entry. The fallback to $5/$15/M tokens triggers. Moderate Together AI usage (~15K tokens) would consume the daily spend cap instantly.
**Why it happens:** Easy to copy-paste the short model name without the namespace prefix. All previous providers in the codebase use non-namespaced model IDs.
**How to avoid:** `_BUILTIN_PRICES` key must be character-for-character identical to `ModelSpec.model_id`. Together AI model IDs include the namespace prefix.
**Warning signs:** `daily_spend_usd` spikes immediately after first Together AI API call; `SpendingLimitExceeded` triggered on first use.

### Pitfall 3: ProviderType.TOGETHER already exists — do not re-add

**What goes wrong:** Phase 1 (INFR-01) added `TOGETHER = "together"` to `ProviderType`. Adding it again causes `ValueError: duplicate member in Enum`.
**Why it happens:** Same trap as all prior phases — Phase 1 pre-populated all 6 future provider enum values.
**How to avoid:** Verify `ProviderType.TOGETHER` already exists in `providers/registry.py` before writing. Only add the ProviderSpec entry to `PROVIDERS`.
**Warning signs:** `ValueError: duplicate member` on import.

### Pitfall 4: `test_all_providers_registered` needs TOGETHER added to expected set

**What goes wrong:** Line 21 of `tests/test_providers.py` checks `expected.issubset(actual)`. If `"together"` is not added to `expected`, the test passes even before Phase 5 is implemented — masking missing coverage.
**Why it happens:** The `issubset` check doesn't fail when new providers are added to PROVIDERS; it only fails when expected providers are missing.
**How to avoid:** Update the `expected` set in `test_all_providers_registered` to include `"together"`.
**Warning signs:** Test suite green despite TOGETHER not in PROVIDERS; `"together"` missing from expected set.

### Pitfall 5: Using incorrect pricing from web search

**What goes wrong:** Web search returns inconsistent pricing for Together AI models ($0.20-$1.25/M for DeepSeek-V3 depending on source). Using an incorrect price doesn't cause a runtime failure — it just silently misestimates spend.
**Why it happens:** Together AI has updated pricing multiple times. Third-party comparison sites may show stale data.
**How to avoid:** Verify via `https://www.together.ai/pricing` at implementation time. Conservative estimates are acceptable — the agent rarely uses CHEAP tier models (not in FREE_ROUTING until Phase 6).
**Warning signs:** None at runtime. Daily spend cap may trigger earlier than expected if pricing is underestimated.

---

## Code Examples

Verified patterns from official Together AI documentation and prior phases:

### Complete ProviderSpec and ModelSpec additions

```python
# Source: providers/registry.py — add TOGETHER ProviderSpec after SAMBANOVA entry

# In PROVIDERS dict:
ProviderType.TOGETHER: ProviderSpec(
    provider_type=ProviderType.TOGETHER,
    base_url="https://api.together.xyz/v1",
    api_key_env="TOGETHER_API_KEY",
    display_name="Together AI",
    supports_function_calling=True,
),

# In MODELS dict (CHEAP TIER section, after SambaNova entries):
# Together AI (credits-based, funded account required — OpenAI-compatible endpoint)
# NOTE: Together AI uses "org/ModelName" namespaced model IDs
"together-deepseek-v3": ModelSpec(
    "deepseek-ai/DeepSeek-V3",    # Serves DeepSeek-V3-0324 weights (updated March 2025)
    ProviderType.TOGETHER,
    max_tokens=4096,
    temperature=0.3,
    display_name="DeepSeek V3 (Together AI)",
    tier=ModelTier.CHEAP,
    max_context_tokens=128000,
),
"together-llama-70b": ModelSpec(
    "meta-llama/Llama-3.3-70B-Instruct-Turbo",
    ProviderType.TOGETHER,
    max_tokens=4096,
    temperature=0.3,
    display_name="Llama 3.3 70B Turbo (Together AI)",
    tier=ModelTier.CHEAP,
    max_context_tokens=131000,
),

# In SpendingTracker._BUILTIN_PRICES (after SambaNova entries):
# Together AI — credits-based (CHEAP tier), per-token pricing
# Keys include org/ prefix — must match ModelSpec.model_id exactly
"meta-llama/Llama-3.3-70B-Instruct-Turbo": (0.88e-6, 0.88e-6),  # $0.88/M in+out
"deepseek-ai/DeepSeek-V3": (0.60e-6, 1.70e-6),                   # $0.60/M in, $1.70/M out
```

### Settings field pattern (core/config.py)

```python
# Settings dataclass — after sambanova_api_key
together_api_key: str = ""

# from_env() — after sambanova_api_key=os.getenv(...)
together_api_key=os.getenv("TOGETHER_API_KEY", ""),
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Registration-only phases (1-3) | Registration + transforms (Phase 4, SambaNova) | Phase 4 | Established pattern for provider-specific workarounds |
| Transform pattern (Phase 4) | Registration-only (Phase 5) | Phase 5 | Together AI is spec-compliant; no transforms needed |
| Lowercase/non-namespaced model IDs (all prior providers) | Namespaced `org/ModelName` model IDs | Phase 5 | First provider using org-namespaced format in model_id; pricing keys must include prefix |

**Note:** Phase 5 is structurally simpler than Phase 4 (no transforms), but introduces the first namespaced model IDs. The `_BUILTIN_PRICES` key format is a new pattern that differs from all prior phases.

---

## Open Questions

1. **Exact Together AI model ID for DeepSeek: `deepseek-ai/DeepSeek-V3` vs `deepseek-ai/DeepSeek-V3-0324`**
   - What we know: Official Together AI docs (https://docs.together.ai/docs/inference-models) show `deepseek-ai/DeepSeek-V3.1` as the current listing. The model page (together.ai/models/deepseek-v3) shows `deepseek-ai/DeepSeek-V3` in JavaScript code, described as serving "DeepSeek-V3-0324 weights updated March 24, 2025."
   - What's unclear: Whether the current API accepts `deepseek-ai/DeepSeek-V3` (base ID), `deepseek-ai/DeepSeek-V3-0324` (dated ID), or `deepseek-ai/DeepSeek-V3.1` (newer version).
   - Recommendation: Use `deepseek-ai/DeepSeek-V3` per the model page JavaScript code. This is the stable base ID. If Together AI has moved to `DeepSeek-V3.1` as the primary, update the model_id at implementation time. Add a comment documenting the weights alias.
   - Confidence: MEDIUM — requires verification against live API.

2. **Together AI pricing accuracy**
   - What we know: Official pricing page shows Llama 3.3 70B at $0.88/M in+out. DeepSeek-V3 pricing is less clear — documentation shows $0.60/M in/$1.70/M out via inference docs, while the pricing page showed $1.25/M.
   - What's unclear: Current exact pricing as of March 2026, especially for DeepSeek.
   - Recommendation: Use `$0.60/M in, $1.70/M out` for DeepSeek-V3 and `$0.88/M in+out` for Llama 70B. These are conservative enough to prevent surprise spend overruns. Verify at signup.
   - Confidence: MEDIUM — pricing subject to change.

3. **`test_all_providers_registered` expected set update**
   - What we know: Current line 21 of `tests/test_providers.py` has `expected = {"openai", "anthropic", "deepseek", "gemini", "openrouter", "vllm", "cerebras", "groq", "mistral", "mistral_codestral", "sambanova"}`. It does not include `"together"`.
   - Recommendation: Add `"together"` to the expected set when implementing Phase 5 tests. This is a required change to ensure the test actually validates TOGETHER presence.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest + pytest-asyncio (auto mode) |
| Config file | `pyproject.toml` (`[tool.pytest.ini_options]`, `asyncio_mode = "auto"`) |
| Quick run command | `python -m pytest tests/test_providers.py tests/test_model_catalog.py -x -q` |
| Full suite command | `python -m pytest tests/ -x -q` |

### Phase Requirements to Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| TOGR-01 | `ProviderType.TOGETHER` in `PROVIDERS` with correct base_url, api_key_env | unit | `pytest tests/test_providers.py::TestTogetherRegistration::test_together_provider_registered -x` | ❌ Wave 0 |
| TOGR-02 | Both Together AI models in `MODELS`, CHEAP tier, namespaced model_ids | unit | `pytest tests/test_providers.py::TestTogetherRegistration::test_together_models_registered -x` | ❌ Wave 0 |
| TOGR-03 | Non-zero pricing in `_BUILTIN_PRICES` for both Together AI model_ids (with org/ prefix) | unit | `pytest tests/test_model_catalog.py::TestTogetherSpendingTracker -x` | ❌ Wave 0 |

Additional tests:
- `test_together_client_builds_with_key` — covers INFR-05 graceful availability
- `test_together_client_raises_without_key` — covers INFR-05 graceful degradation
- `test_together_models_all_cheap_tier` — verifies no TOGETHER model is accidentally FREE tier
- `test_together_not_free_model_detection` — verifies org-namespaced IDs don't accidentally match free detection logic

### Sampling Rate

- **Per task commit:** `python -m pytest tests/test_providers.py tests/test_model_catalog.py -x -q`
- **Per wave merge:** `python -m pytest tests/ -x -q`
- **Phase gate:** Full suite green (`python -m pytest tests/ -x -q`) before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/test_providers.py` — needs `TestTogetherRegistration` class (6 tests) added after `TestSambanovaTransforms`; file exists, class does not
- [ ] `tests/test_model_catalog.py` — needs `TestTogetherSpendingTracker` class (5 tests) added after `TestSambanovaSpendingTracker`; file exists, class does not

Note: No framework install needed — pytest, pytest-asyncio, and unittest.mock already in place.

---

## Sources

### Primary (HIGH confidence)
- `C:/Users/rickw/projects/agent42/providers/registry.py` — `ProviderType.TOGETHER` already exists in enum; PROVIDERS dict shows insertion point after SAMBANOVA; SpendingTracker `_BUILTIN_PRICES` pattern established; `_build_client()` raises `ValueError` when API key not set (INFR-05 behavior confirmed)
- `C:/Users/rickw/projects/agent42/tests/test_providers.py` — `TestSambanovaRegistration` and `TestGroqRegistration` classes are direct templates for `TestTogetherRegistration`; `test_all_providers_registered` expected set at line 21 needs `"together"` added
- `C:/Users/rickw/projects/agent42/tests/test_model_catalog.py` — `TestSambanovaSpendingTracker` class is direct template for `TestTogetherSpendingTracker`
- `C:/Users/rickw/projects/agent42/.planning/REQUIREMENTS.md` — TOGR-01 through TOGR-03 exact specs; confirms CHEAP tier, model key names, and base_url
- `C:/Users/rickw/projects/agent42/.planning/STATE.md` — confirms CHEAP classification decision; notes "Llama 4 Scout serverless availability unverified — may need to fall back to DeepSeek-V3 as primary model" (Phase 5 concern logged)
- `C:/Users/rickw/projects/agent42/.planning/phases/04-sambanova-integration/04-RESEARCH.md` — Phase 4 research doc is the structural template for this document

### Secondary (MEDIUM confidence)
- [Together AI Inference Models Docs](https://docs.together.ai/docs/inference-models) — Confirmed `meta-llama/Llama-3.3-70B-Instruct-Turbo` and `deepseek-ai/DeepSeek-V3.1` as model IDs; context windows (131K Llama, 128K DeepSeek); pricing $0.88/M Llama, $0.60/$1.70/M DeepSeek
- [Together AI Pricing Page](https://www.together.ai/pricing) — Confirmed Llama 3.3 70B at $0.88/M in+out; DeepSeek-V3-0324 at $1.25/M (possible discrepancy vs docs page — use conservative docs value)
- [Together AI Models Page](https://www.together.ai/models/deepseek-v3) — Confirmed `deepseek-ai/DeepSeek-V3` as the JavaScript endpoint variable for the DeepSeek-V3-0324 model

### Tertiary (LOW confidence)
- Together AI pricing $0.60/M in, $1.70/M out for DeepSeek-V3 — two sources consulted show different values ($0.60 from docs, $1.25 from pricing page); using docs value as more likely to be updated; verify at implementation

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new dependencies; identical AsyncOpenAI pattern to all prior phases
- Registration pattern (TOGR-01): HIGH — ProviderSpec structure identical to all prior phases; base_url from REQUIREMENTS.md confirmed via docs
- Model IDs (TOGR-02): MEDIUM — `meta-llama/Llama-3.3-70B-Instruct-Turbo` HIGH confidence (confirmed in docs); `deepseek-ai/DeepSeek-V3` MEDIUM (JavaScript endpoint var; docs show DeepSeek-V3.1 as newer)
- Pricing (TOGR-03): MEDIUM — official pricing page consulted; some discrepancy between docs and pricing page for DeepSeek; use conservative values
- No transforms needed: HIGH — Together AI is OpenAI spec-compliant; no community reports of parameter rejection or streaming bugs
- Test pattern: HIGH — direct template from TestSambanovaRegistration and TestSambanovaSpendingTracker; org/ prefix key novelty is clearly documented
- Pitfalls: HIGH — key-mismatch pitfall (org/ prefix) and enum-duplicate pitfall are well-established from prior phases

**Research date:** 2026-03-02
**Valid until:** 2026-04-02 (Together AI may update model IDs as new versions release; verify DeepSeek model ID before implementation if delayed more than 2 weeks)
