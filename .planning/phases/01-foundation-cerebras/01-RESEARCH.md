# Phase 1: Foundation + Cerebras - Research

**Researched:** 2026-03-01
**Domain:** Provider registry extension, SpendingTracker free-model detection, Cerebras API integration
**Confidence:** HIGH

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| CERE-01 | Register ProviderType.CEREBRAS with ProviderSpec (base_url: `https://api.cerebras.ai/v1`, api_key_env: `CEREBRAS_API_KEY`) | Confirmed via official Cerebras OpenAI-compatibility docs — AsyncOpenAI works with this base_url |
| CERE-02 | Register 4 ModelSpec entries — `cerebras-gpt-oss-120b`, `cerebras-qwen3-235b`, `cerebras-llama-8b`, `cerebras-zai-glm` | Model IDs, context windows, and speeds verified via Cerebras official docs |
| CERE-03 | All Cerebras models classified as ModelTier.FREE | Confirmed — Cerebras free tier covers all 4 models at $0 (1M tokens/day limit) |
| CERE-04 | Add $0 pricing entries to SpendingTracker `_BUILTIN_PRICES` for all Cerebras model IDs | This is the correct approach per existing pattern — keyed by `model_id` not `model_key` |
| INFR-01 | Add ProviderType enum values for CEREBRAS (and future: GROQ, MISTRAL, MISTRAL_CODESTRAL, SAMBANOVA, TOGETHER) | Existing `ProviderType(str, Enum)` pattern in registry.py supports this directly |
| INFR-02 | Extend SpendingTracker free-model detection beyond `or-free-` prefix / `:free` suffix | Current `_get_price` checks prefix/suffix only; fix is to add entries to `_BUILTIN_PRICES` at (0.0, 0.0) OR add a tier-aware lookup |
| INFR-05 | Graceful degradation — missing API keys for any new provider must not crash Agent42, just skip | `_build_client()` already raises `ValueError` on missing key; `get_client()` is only called at request time, so startup is safe |
| TEST-01 | Unit tests for each new ProviderSpec/ModelSpec registration | `tests/test_providers.py` exists with the exact class-based patterns to follow |
| TEST-02 | Unit tests for SpendingTracker pricing with new provider models | `tests/test_model_catalog.py::TestSpendingTrackerPricing` exists with the exact patterns to follow |
</phase_requirements>

---

## Summary

Phase 1 adds Cerebras as Agent42's first non-OpenRouter, non-Google free LLM provider. The implementation is primarily additive: new enum values, new dataclass instances, and extended pricing logic — no existing logic needs significant restructuring.

Cerebras exposes a fully OpenAI-compatible REST API at `https://api.cerebras.ai/v1`. The existing `AsyncOpenAI(base_url=..., api_key=...)` pattern used throughout `providers/registry.py` works without any SDK dependency. Four models are available on the free tier: `gpt-oss-120b` (fastest at ~3000 tok/s, 65K context), `qwen-3-235b-a22b-instruct-2507` (~1400 tok/s, 65K context on free), `llama3.1-8b` (fast, 8K context on free), and `zai-glm-4.7` (reasoning, 65K context but only 100 RPD on free).

The most important infrastructure fix in this phase is INFR-02: the `SpendingTracker._get_price()` method currently only recognizes free models by `or-free-` key prefix or `:free` model_id suffix. Cerebras model IDs (`gpt-oss-120b`, `llama3.1-8b`, etc.) have neither, so they would fall through to the conservative $5/$15 fallback and falsely trip the daily spend cap. The fix is to add these model IDs to `_BUILTIN_PRICES` at `(0.0, 0.0)` — this is the same resolution path used by all other known-price models and is already tested in `TestSpendingTrackerPricing`.

**Primary recommendation:** Add CEREBRAS to `ProviderType`, add `ProviderSpec` + 4 `ModelSpec` entries + 4 `_BUILTIN_PRICES` entries — all in `providers/registry.py`. Add `CEREBRAS_API_KEY` to `Settings` and `.env.example`. Add tests. No new dependencies required.

---

## Standard Stack

### Core (already in project)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `openai` (AsyncOpenAI) | already installed | HTTP client for Cerebras API | Cerebras is OpenAI-compatible; no new dep needed |
| `pytest` + `pytest-asyncio` | already installed | Test framework | Project standard — `asyncio_mode = "auto"` in pyproject.toml |

### No New Dependencies

Cerebras does not require the `cerebras-cloud-sdk` package. The project uses `AsyncOpenAI(base_url=..., api_key=...)` for all providers, and Cerebras explicitly supports this pattern via their OpenAI compatibility layer.

**Installation:** No new packages needed for this phase.

---

## Architecture Patterns

### Recommended File Structure for Changes

```
providers/
└── registry.py          # All changes: ProviderType enum, PROVIDERS dict, MODELS dict, _BUILTIN_PRICES
core/
└── config.py            # Add cerebras_api_key field to Settings
.env.example             # Document CEREBRAS_API_KEY
tests/
└── test_providers.py    # Add TestCerebrasRegistration class
tests/
└── test_model_catalog.py  # Add TestCerebrasSpendingTracker tests (or extend existing class)
```

### Pattern 1: Adding a ProviderType Enum Value

**What:** Extend `ProviderType(str, Enum)` in `providers/registry.py`
**When to use:** Every new provider gets exactly one enum value
**Example:**
```python
# Source: providers/registry.py (existing pattern)
class ProviderType(str, Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    DEEPSEEK = "deepseek"
    GEMINI = "gemini"
    OPENROUTER = "openrouter"
    VLLM = "vllm"
    CUSTOM = "custom"
    # NEW — Phase 1
    CEREBRAS = "cerebras"
    # NEW — Phase 2 (future placeholders, Phase 1 adds all 5 per INFR-01)
    GROQ = "groq"
    MISTRAL = "mistral"
    MISTRAL_CODESTRAL = "mistral_codestral"
    SAMBANOVA = "sambanova"
    TOGETHER = "together"
```

Note: INFR-01 says "Add ProviderType enum values for CEREBRAS, GROQ, MISTRAL, MISTRAL_CODESTRAL, SAMBANOVA, TOGETHER" — all 6 new values can be added in Phase 1 without the corresponding ProviderSpec/ModelSpec (which arrive in their respective phases). This is safe because `ProviderType` values only become active when a `ProviderSpec` is registered in `PROVIDERS`.

### Pattern 2: Adding a ProviderSpec to PROVIDERS dict

**What:** Add to the `PROVIDERS: dict[ProviderType, ProviderSpec]` dict
**When to use:** When a new provider is ready to accept requests
**Example:**
```python
# Source: providers/registry.py (existing pattern, applied to Cerebras)
ProviderType.CEREBRAS: ProviderSpec(
    provider_type=ProviderType.CEREBRAS,
    base_url="https://api.cerebras.ai/v1",
    api_key_env="CEREBRAS_API_KEY",
    display_name="Cerebras (Ultra-fast free inference)",
    supports_function_calling=True,
),
```

Note: `requires_model_prefix=False` is the default and correct for Cerebras — model IDs are bare strings like `gpt-oss-120b`, not `cerebras/gpt-oss-120b`.

### Pattern 3: Adding ModelSpec entries to MODELS dict

**What:** Add to the `MODELS: dict[str, ModelSpec]` dict
**When to use:** Each model gets a short human-readable key (the "model_key") and a `ModelSpec`
**Example:**
```python
# Source: providers/registry.py (existing pattern, applied to Cerebras)

# Phase 1 Cerebras models — all ModelTier.FREE
"cerebras-gpt-oss-120b": ModelSpec(
    model_id="gpt-oss-120b",
    provider=ProviderType.CEREBRAS,
    max_tokens=8192,
    display_name="Cerebras GPT-OSS 120B (3000 tok/s)",
    tier=ModelTier.FREE,
    max_context_tokens=65000,   # 65K on free tier
),
"cerebras-qwen3-235b": ModelSpec(
    model_id="qwen-3-235b-a22b-instruct-2507",
    provider=ProviderType.CEREBRAS,
    max_tokens=8192,
    display_name="Cerebras Qwen3 235B (1400 tok/s)",
    tier=ModelTier.FREE,
    max_context_tokens=65000,   # 65K on free tier (131K paid)
),
"cerebras-llama-8b": ModelSpec(
    model_id="llama3.1-8b",
    provider=ProviderType.CEREBRAS,
    max_tokens=4096,
    display_name="Cerebras Llama 3.1 8B (2200 tok/s)",
    tier=ModelTier.FREE,
    max_context_tokens=8000,    # 8K on free tier (32K paid)
),
"cerebras-zai-glm": ModelSpec(
    model_id="zai-glm-4.7",
    provider=ProviderType.CEREBRAS,
    max_tokens=4096,
    display_name="Cerebras ZAI GLM 4.7 Reasoning (1000 tok/s)",
    tier=ModelTier.FREE,
    max_context_tokens=65000,   # context is ample; limit is 100 RPD on free
),
```

**Important context window note:** The `max_context_tokens` in the REQUIREMENTS.md lists 65K for `gpt-oss-120b`, 65K for `qwen3-235b`, 128K for `llama-8b`, and 32K for `zai-glm`. The official Cerebras docs show `llama3.1-8b` has only 8K context on free tier (32K paid). The requirements spec may reflect paid-tier values. Set `max_context_tokens` based on free-tier verified limits to avoid errors.

### Pattern 4: SpendingTracker $0 pricing entries (INFR-02 + CERE-04)

**What:** Add entries to `_BUILTIN_PRICES` at `(0.0, 0.0)` for free Cerebras models
**When to use:** Any model whose free-tier pricing is $0 but whose model_id doesn't follow the `or-free-` or `:free` naming convention
**Example:**
```python
# Source: providers/registry.py SpendingTracker._BUILTIN_PRICES
_BUILTIN_PRICES: dict[str, tuple[float, float]] = {
    # Gemini 2.5 Flash — $0.15/M input, $0.60/M output
    "gemini-2.5-flash": (0.15e-6, 0.60e-6),
    # ... existing entries ...

    # Cerebras — free tier, $0 cost (1M tokens/day limit enforced by provider)
    "gpt-oss-120b": (0.0, 0.0),
    "qwen-3-235b-a22b-instruct-2507": (0.0, 0.0),
    "llama3.1-8b": (0.0, 0.0),
    "zai-glm-4.7": (0.0, 0.0),
}
```

**Why `_BUILTIN_PRICES` and not a prefix check:** The `_get_price` resolution order is: (1) catalog prices, (2) built-in prices, (3) prefix/suffix detection. Adding to `_BUILTIN_PRICES` is the most explicit and testable approach. It does not require changing `_get_price` logic — just the data. This also covers INFR-02 (extending free-model detection) as a side effect of CERE-04.

### Pattern 5: Settings dataclass field addition (INFR-05 support)

**What:** Add `cerebras_api_key: str = ""` to `Settings` in `core/config.py`
**When to use:** Every new provider API key needs a Settings field (per CLAUDE.md pitfall #1)
**Example:**
```python
# core/config.py Settings dataclass — add after existing provider keys
cerebras_api_key: str = ""

# Settings.from_env() — add:
cerebras_api_key=os.getenv("CEREBRAS_API_KEY", ""),
```

Note: The `ProviderRegistry._build_client()` reads `os.getenv(spec.api_key_env, "")` directly, NOT `settings.cerebras_api_key`. The Settings field is for introspection/reporting only (graceful degradation check). The env var is the canonical source for the actual key.

### Anti-Patterns to Avoid

- **Do not use `cerebras-cloud-sdk` package:** No new dependency is needed. `AsyncOpenAI(base_url="https://api.cerebras.ai/v1", api_key=key)` is the correct approach, verified by official Cerebras docs.
- **Do not pass `frequency_penalty`, `logit_bias`, or `presence_penalty` to Cerebras:** These return a 400 error. Agent42's `complete()` and `complete_with_tools()` do not currently pass these parameters, so no guard is needed in Phase 1 — but document this for future.
- **Do not assume `llama3.1-8b` has 128K context on free tier:** Official docs confirm 8K on free, 32K on paid. The requirements spec lists 128K which may reflect a different model version or paid tier. Use 8K for safety.
- **Do not register Cerebras in `FREE_ROUTING` in Phase 1:** Routing changes are Phase 6 (ROUT-01). Phase 1 only registers the provider so it *can* be used; Phase 6 makes it the *default*.
- **Do not add test for `test_all_providers_registered` without updating its expected set:** `tests/test_providers.py::TestProviderRegistry::test_all_providers_registered` has a hardcoded `expected` set. Update it when adding CEREBRAS to PROVIDERS.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| HTTP client for Cerebras | Custom requests.Session or httpx | `AsyncOpenAI(base_url=...)` | Cerebras is OpenAI-compatible; same client used for all providers |
| Free-tier rate limiting enforcement | Custom daily token counter | Provider-side enforcement | Cerebras enforces 1M tokens/day server-side; our SpendingTracker just tracks $0 spend |
| Model ID validation | Runtime API call to list models | Static MODELS dict entries | All 4 model IDs are stable production/preview models per official docs |

**Key insight:** This phase is 100% additive declarations in existing data structures. There is no novel algorithm to write — only new enum values, dataclass instances, and dict entries.

---

## Common Pitfalls

### Pitfall 1: Cerebras model IDs trip the conservative spend fallback
**What goes wrong:** Cerebras model IDs (`gpt-oss-120b`, `llama3.1-8b`, etc.) don't match the `or-free-` prefix or `:free` suffix patterns. `SpendingTracker._get_price()` falls through to the conservative fallback ($5/$15 per million tokens). After a few tasks, the daily spend cap triggers and blocks all requests.
**Why it happens:** The free-model detection in `_get_price()` was designed only for OpenRouter naming conventions.
**How to avoid:** Add all 4 Cerebras model IDs to `_BUILTIN_PRICES` at `(0.0, 0.0)` (CERE-04). This is required before any Cerebras model can safely be used.
**Warning signs:** `SpendingLimitExceeded` exception triggered after just 1-2 tasks; `daily_spend_usd` shows non-zero value for Cerebras calls.

### Pitfall 2: `_build_client()` raises ValueError on missing API key (not at startup)
**What goes wrong:** If `CEREBRAS_API_KEY` is not set, `_build_client()` raises `ValueError`. This is correct behavior — but it only fires when `get_client()` is called (at request time, not at startup). Agent42 starts successfully even without the key.
**Why it happens:** The graceful degradation requirement (INFR-05) is satisfied by the existing lazy-client pattern. No special handling is needed.
**How to avoid:** Ensure tests mock the env var when testing `get_client()` for CEREBRAS. Use `patch.dict(os.environ, {"CEREBRAS_API_KEY": "test-key"})`.
**Warning signs:** Test failures with `ValueError: CEREBRAS_API_KEY not set` — add the mock.

### Pitfall 3: `test_all_providers_registered` hardcoded set breaks after adding CEREBRAS
**What goes wrong:** `tests/test_providers.py` has `expected = {"openai", "anthropic", "deepseek", "gemini", "openrouter", "vllm"}`. Adding CEREBRAS to PROVIDERS without updating this test causes a false failure or false pass depending on assertion direction.
**Why it happens:** The test uses `issubset`, so CEREBRAS being added does not break it (CEREBRAS is not in `expected`). However, if the test is changed to equality, it breaks.
**How to avoid:** Add `"cerebras"` to the expected set when updating PROVIDERS. Also update `test_model_catalog_not_empty` assertion if model count changes significantly.
**Warning signs:** CI passes but expected set is stale — future tests that check exact membership will fail.

### Pitfall 4: Context window mismatch for `llama3.1-8b` on free tier
**What goes wrong:** Requirements say 128K context; official docs say 8K (free tier), 32K (paid). If we set `max_context_tokens=128000`, the model will return errors for large contexts on free tier.
**Why it happens:** The requirements spec may reference a different Llama variant or paid tier. The Cerebras docs are definitive.
**How to avoid:** Use 8K (or conservatively 8192) for `llama3.1-8b`. Document the discrepancy in comments.
**Warning signs:** `400 Bad Request` or context-length errors from Cerebras API when sending large prompts.

### Pitfall 5: Cerebras API rejects `frequency_penalty`, `logit_bias`, `presence_penalty`
**What goes wrong:** If these parameters are ever passed to a Cerebras model via `complete_with_tools()` kwargs expansion, Cerebras returns a 400 error.
**Why it happens:** Cerebras's OpenAI compatibility is not 100% — these three parameters are explicitly rejected.
**How to avoid:** Agent42's current `complete()` and `complete_with_tools()` do not pass these parameters, so no immediate fix is needed. Flag this in comments on the ProviderSpec for future developers.
**Warning signs:** `400 Bad Request` with message mentioning unsupported parameter.

---

## Code Examples

Verified patterns from official sources:

### CERE-01: ProviderSpec registration
```python
# Source: inference-docs.cerebras.ai/resources/openai — confirmed AsyncOpenAI-compatible
ProviderType.CEREBRAS: ProviderSpec(
    provider_type=ProviderType.CEREBRAS,
    base_url="https://api.cerebras.ai/v1",
    api_key_env="CEREBRAS_API_KEY",
    display_name="Cerebras (Ultra-fast free inference)",
    supports_function_calling=True,
    # Note: frequency_penalty, logit_bias, presence_penalty not supported
    # Note: requires_model_prefix=False (default) — model IDs are bare strings
),
```

### CERE-02: ModelSpec registrations
```python
# Source: inference-docs.cerebras.ai/models/overview + /support/rate-limits
# All verified model IDs, speeds, and free-tier context windows

"cerebras-gpt-oss-120b": ModelSpec(
    model_id="gpt-oss-120b",
    provider=ProviderType.CEREBRAS,
    max_tokens=8192,
    display_name="Cerebras GPT-OSS 120B (~3000 tok/s)",
    tier=ModelTier.FREE,
    max_context_tokens=65000,   # Free tier limit (131K paid)
),
"cerebras-qwen3-235b": ModelSpec(
    model_id="qwen-3-235b-a22b-instruct-2507",
    provider=ProviderType.CEREBRAS,
    max_tokens=8192,
    display_name="Cerebras Qwen3 235B (~1400 tok/s)",
    tier=ModelTier.FREE,
    max_context_tokens=65000,   # Free tier limit (131K paid)
),
"cerebras-llama-8b": ModelSpec(
    model_id="llama3.1-8b",
    provider=ProviderType.CEREBRAS,
    max_tokens=4096,
    display_name="Cerebras Llama 3.1 8B (~2200 tok/s)",
    tier=ModelTier.FREE,
    max_context_tokens=8000,    # Free tier only (32K paid); requirements say 128K — use official docs
),
"cerebras-zai-glm": ModelSpec(
    model_id="zai-glm-4.7",
    provider=ProviderType.CEREBRAS,
    max_tokens=4096,
    display_name="Cerebras ZAI GLM 4.7 Reasoning (~1000 tok/s)",
    tier=ModelTier.FREE,
    max_context_tokens=65000,   # 65K context; 100 RPD limit on free tier
),
```

### CERE-04 + INFR-02: SpendingTracker $0 pricing
```python
# Source: inference-docs.cerebras.ai/support/rate-limits — free tier confirmed $0
# This fixes INFR-02 as a side effect (no prefix/suffix match needed)

_BUILTIN_PRICES: dict[str, tuple[float, float]] = {
    "gemini-2.5-flash": (0.15e-6, 0.60e-6),
    "gemini-2.5-pro": (1.25e-6, 10.00e-6),
    "gpt-4o-mini": (0.15e-6, 0.60e-6),
    "gpt-4o": (2.50e-6, 10.00e-6),
    "deepseek-chat": (0.14e-6, 0.28e-6),
    # Cerebras free tier — $0 (1M tokens/day limit enforced server-side)
    "gpt-oss-120b": (0.0, 0.0),
    "qwen-3-235b-a22b-instruct-2507": (0.0, 0.0),
    "llama3.1-8b": (0.0, 0.0),
    "zai-glm-4.7": (0.0, 0.0),
}
```

### TEST-01: Provider registration test pattern
```python
# Source: tests/test_providers.py — existing class-based pattern to follow

class TestCerebrasRegistration:
    def test_cerebras_provider_registered(self):
        assert ProviderType.CEREBRAS in PROVIDERS
        spec = PROVIDERS[ProviderType.CEREBRAS]
        assert spec.base_url == "https://api.cerebras.ai/v1"
        assert spec.api_key_env == "CEREBRAS_API_KEY"

    def test_cerebras_models_registered(self):
        expected_keys = {
            "cerebras-gpt-oss-120b",
            "cerebras-qwen3-235b",
            "cerebras-llama-8b",
            "cerebras-zai-glm",
        }
        assert expected_keys.issubset(MODELS.keys())

    def test_cerebras_models_are_free_tier(self):
        for key in ["cerebras-gpt-oss-120b", "cerebras-qwen3-235b",
                    "cerebras-llama-8b", "cerebras-zai-glm"]:
            assert MODELS[key].tier == ModelTier.FREE, f"{key} should be FREE tier"
            assert MODELS[key].provider == ProviderType.CEREBRAS

    def test_cerebras_client_builds_with_key(self):
        registry = ProviderRegistry()
        with patch.dict(os.environ, {"CEREBRAS_API_KEY": "test-csk-key"}):
            client = registry.get_client(ProviderType.CEREBRAS)
            assert client is not None
            assert client.base_url == "https://api.cerebras.ai/v1/"  # trailing slash added by SDK

    def test_cerebras_client_fails_without_key(self):
        registry = ProviderRegistry()
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("CEREBRAS_API_KEY", None)
            with pytest.raises(ValueError, match="CEREBRAS_API_KEY"):
                registry.get_client(ProviderType.CEREBRAS)
```

### TEST-02: SpendingTracker $0 pricing test pattern
```python
# Source: tests/test_model_catalog.py::TestSpendingTrackerPricing — existing pattern

class TestCerebrasSpendingTracker:
    def test_cerebras_gpt_oss_zero_cost(self):
        tracker = SpendingTracker()
        tracker.record_usage("cerebras-gpt-oss-120b", 10000, 5000, model_id="gpt-oss-120b")
        assert tracker.daily_spend_usd == 0.0

    def test_cerebras_qwen3_zero_cost(self):
        tracker = SpendingTracker()
        tracker.record_usage("cerebras-qwen3-235b", 10000, 5000,
                             model_id="qwen-3-235b-a22b-instruct-2507")
        assert tracker.daily_spend_usd == 0.0

    def test_cerebras_llama_8b_zero_cost(self):
        tracker = SpendingTracker()
        tracker.record_usage("cerebras-llama-8b", 5000, 2000, model_id="llama3.1-8b")
        assert tracker.daily_spend_usd == 0.0

    def test_cerebras_zai_glm_zero_cost(self):
        tracker = SpendingTracker()
        tracker.record_usage("cerebras-zai-glm", 5000, 2000, model_id="zai-glm-4.7")
        assert tracker.daily_spend_usd == 0.0

    def test_cerebras_no_spend_cap_trip(self):
        """Cerebras usage must not trigger SpendingLimitExceeded at any sane cap."""
        tracker = SpendingTracker()
        # Simulate 50 tasks x 10K tokens each = 500K tokens
        for _ in range(50):
            tracker.record_usage("cerebras-gpt-oss-120b", 8000, 2000, model_id="gpt-oss-120b")
        assert tracker.daily_spend_usd == 0.0
        assert tracker.check_limit(1.0)   # $1 cap should never be hit
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Free model detection by naming convention (`or-free-`, `:free`) | Explicit `_BUILTIN_PRICES` entries at `(0.0, 0.0)` | Phase 1 (now) | Supports any free provider regardless of naming |
| OpenRouter as only free provider option | OpenRouter + Cerebras (Phase 1) + Groq (Phase 2) + ... | Phase 1-5 | Provider diversity; no single outage stops platform |
| `ProviderType` enum has 7 values | 13 values (7 existing + 6 new) | Phase 1 | Future phases can reference enum values immediately |

**Deprecated/outdated:**
- Nothing is removed in Phase 1 — all changes are additive.

---

## Open Questions

1. **Context window for `llama3.1-8b`**
   - What we know: Official Cerebras docs say 8K free / 32K paid. Requirements say 128K.
   - What's unclear: Whether 128K refers to a future model update, a paid-tier spec, or a documentation error.
   - Recommendation: Use `max_context_tokens=8000` in `ModelSpec` to match verified free-tier behavior. Add comment documenting the discrepancy. This is conservative and safe.

2. **`zai-glm-4.7` stability**
   - What we know: It's labeled "preview" in Cerebras docs. Preview models may be discontinued without notice.
   - What's unclear: When it will graduate to production or be discontinued.
   - Recommendation: Register it but add a code comment: `# Preview model — may be discontinued; monitor Cerebras changelog`. Do not use it in any critical routing path.

3. **INFR-01 scope: add all 6 enum values now or just CEREBRAS?**
   - What we know: INFR-01 explicitly lists all 6 (CEREBRAS, GROQ, MISTRAL, MISTRAL_CODESTRAL, SAMBANOVA, TOGETHER). Phase 1 is the only phase that touches the `ProviderType` enum before other phases need their values.
   - What's unclear: Whether the planner wants to add all 6 enum values in Phase 1 or stagger them.
   - Recommendation: Add all 6 enum values to `ProviderType` in Phase 1. Enum values are inert until a `ProviderSpec` is registered in `PROVIDERS`. This avoids revisiting the enum in each subsequent phase.

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
| CERE-01 | `ProviderType.CEREBRAS` in `PROVIDERS` with correct base_url and api_key_env | unit | `pytest tests/test_providers.py::TestCerebrasRegistration::test_cerebras_provider_registered -x` | ❌ Wave 0 |
| CERE-02 | All 4 Cerebras model keys in `MODELS` with correct model_id and specs | unit | `pytest tests/test_providers.py::TestCerebrasRegistration::test_cerebras_models_registered -x` | ❌ Wave 0 |
| CERE-03 | All 4 Cerebras models have `tier == ModelTier.FREE` | unit | `pytest tests/test_providers.py::TestCerebrasRegistration::test_cerebras_models_are_free_tier -x` | ❌ Wave 0 |
| CERE-04 | `SpendingTracker.record_usage()` produces $0 for all 4 Cerebras model IDs | unit | `pytest tests/test_model_catalog.py -k "cerebras" -x` | ❌ Wave 0 |
| INFR-01 | All 6 new `ProviderType` enum values exist | unit | `pytest tests/test_providers.py -k "enum" -x` | ❌ Wave 0 |
| INFR-02 | SpendingTracker returns (0.0, 0.0) for Cerebras model IDs (no prefix/suffix) | unit | `pytest tests/test_model_catalog.py -k "cerebras" -x` | ❌ Wave 0 (covered by CERE-04 tests) |
| INFR-05 | Agent42 starts without error when `CEREBRAS_API_KEY` is absent | unit (env mock) | `pytest tests/test_providers.py::TestCerebrasRegistration::test_cerebras_client_fails_without_key -x` | ❌ Wave 0 |
| TEST-01 | ProviderSpec and ModelSpec registration tests pass | unit | `pytest tests/test_providers.py -k "Cerebras" -x` | ❌ Wave 0 |
| TEST-02 | SpendingTracker $0 pricing tests pass for all Cerebras models | unit | `pytest tests/test_model_catalog.py -k "Cerebras" -x` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `python -m pytest tests/test_providers.py tests/test_model_catalog.py -x -q`
- **Per wave merge:** `python -m pytest tests/ -x -q`
- **Phase gate:** Full suite green (`python -m pytest tests/ -x -q`) before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/test_providers.py` — needs `TestCerebrasRegistration` class added (file exists, class does not)
- [ ] `tests/test_model_catalog.py` — needs `TestCerebrasSpendingTracker` class added (file exists, class does not)

Note: No framework install needed — pytest and pytest-asyncio already installed per `requirements-dev.txt`.

---

## Sources

### Primary (HIGH confidence)
- `inference-docs.cerebras.ai/resources/openai` — Confirmed `AsyncOpenAI` with `base_url="https://api.cerebras.ai/v1"` works; unsupported params listed
- `inference-docs.cerebras.ai/models/overview` — All 4 model IDs, speeds, and tiers verified
- `inference-docs.cerebras.ai/support/rate-limits` — Free tier limits per model verified (including 100 RPD for zai-glm-4.7)
- `inference-docs.cerebras.ai/models/openai-oss` — gpt-oss-120b: 65K context (free), ~3000 tok/s confirmed
- `inference-docs.cerebras.ai/models/llama-31-8b` — llama3.1-8b: 8K context (free), ~2200 tok/s confirmed
- `C:/Users/rickw/projects/agent42/providers/registry.py` — Current codebase patterns for ProviderType, ProviderSpec, ModelSpec, SpendingTracker
- `C:/Users/rickw/projects/agent42/tests/test_providers.py` — Existing test class patterns
- `C:/Users/rickw/projects/agent42/tests/test_model_catalog.py` — Existing SpendingTracker test patterns

### Secondary (MEDIUM confidence)
- `www.cerebras.ai/pricing` — Free tier described as "access to all models" with 1M tokens/day; pricing table for developer tier matches per-model doc pages

### Tertiary (LOW confidence)
- REQUIREMENTS.md context window for `llama3.1-8b` (128K) — conflicts with official docs (8K free). Unresolved — using official docs value.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — OpenAI compatibility confirmed by official docs; no new dependencies
- Architecture: HIGH — follows identical patterns to existing 7 providers in registry.py
- Pitfalls: HIGH — `_get_price` logic read directly from codebase; rate limits from official docs
- Context windows: MEDIUM — 3 of 4 models verified from docs; `llama3.1-8b` has discrepancy with requirements

**Research date:** 2026-03-01
**Valid until:** 2026-04-01 (Cerebras is a fast-moving company; verify model IDs and rate limits before implementation)
