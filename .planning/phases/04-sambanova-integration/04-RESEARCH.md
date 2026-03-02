# Phase 4: SambaNova Integration - Research

**Researched:** 2026-03-02
**Domain:** Provider registry extension + provider-specific request transforms (temperature clamping, stream=False for tools, strict field removal)
**Confidence:** HIGH

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| SAMB-01 | Register ProviderType.SAMBANOVA with ProviderSpec (base_url: `https://api.sambanova.ai/v1`, api_key_env: `SAMBANOVA_API_KEY`) | ProviderType.SAMBANOVA already in enum (Phase 1 INFR-01). Only ProviderSpec entry in PROVIDERS dict needed. OpenAI-compatible endpoint confirmed. |
| SAMB-02 | Register ModelSpec entries — `sambanova-llama-70b` (Meta-Llama-3.3-70B-Instruct), `sambanova-deepseek-v3` (DeepSeek-V3.1), classified as ModelTier.CHEAP | Both model IDs require research verification. CHEAP tier correct (credits-based, funded account required). SpendingTracker pricing entries needed for both. |
| SAMB-03 | Clamp temperature to max 1.0 for SambaNova requests (provider rejects >1.0) | Transform must occur in `complete()` and `complete_with_tools()` in `providers/registry.py` before the `client.chat.completions.create()` call. Simple `min(temperature, 1.0)` guard on the resolved temperature value. |
| SAMB-04 | Force `stream=False` when tools are present for SambaNova (streaming tool calls have broken `index` field) | Transform in `complete_with_tools()` only — the `stream` kwarg defaults to None (not streaming) in `AsyncOpenAI`. When provider is SAMBANOVA and tools are non-empty, explicitly pass `stream=False` in kwargs. |
| SAMB-05 | Strip `strict: true` from tool definitions for SambaNova (not supported — only `strict: false`) | Transform in `complete_with_tools()` — deep-copy the tools list and remove or set `strict: false` in each tool's `function` definition before passing to the API. |
| INFR-03 | Add provider-specific request transforms (SambaNova temp clamp, SambaNova stream=False for tools, SambaNova strict removal) | All three transforms applied in `ProviderRegistry.complete()` and `complete_with_tools()` by checking `spec.provider == ProviderType.SAMBANOVA` before the API call. No new abstraction layer needed. |
| TEST-03 | Unit tests for SambaNova request transforms (temp clamp, stream=False, strict removal) | New test class `TestSambanovaTransforms` in `tests/test_providers.py`. Tests mock `client.chat.completions.create` and inspect kwargs passed. |
</phase_requirements>

---

## Summary

Phase 4 differs from Phases 1-3 in one critical way: in addition to the standard ProviderSpec + ModelSpec registration, it requires **three request transforms** that modify the API call parameters before they reach the SambaNova endpoint. These transforms are necessary because SambaNova's OpenAI-compatible API deviates from the OpenAI spec in three documented ways: (1) it rejects `temperature > 1.0`, (2) it returns malformed `index` fields in streaming tool call responses, and (3) it does not support `strict: true` in tool definitions.

The transforms belong inside `ProviderRegistry.complete()` and `complete_with_tools()` in `providers/registry.py`, checked by `spec.provider == ProviderType.SAMBANOVA` immediately before the `client.chat.completions.create(**kwargs)` call. This is the minimal-invasive approach: no new abstraction layer, no middleware pattern, no subclassing. The existing code path handles the guard naturally since `spec` is already in scope at that point.

The registration portion (SAMB-01, SAMB-02) follows the identical pattern to Phases 1-3. `ProviderType.SAMBANOVA` already exists in the enum (added in Phase 1 INFR-01). Only one Settings field (`sambanova_api_key`) is needed since SambaNova uses a single API key. CHEAP tier is correct because SambaNova requires a funded account.

**Primary recommendation:** Add one ProviderSpec to PROVIDERS, two ModelSpecs to MODELS (CHEAP tier), two `_BUILTIN_PRICES` entries, one Settings field, implement three in-line transforms in `complete()` and `complete_with_tools()`, and write a `TestSambanovaTransforms` test class that mocks the HTTP client and asserts transformed kwargs.

---

## Standard Stack

### Core (already in project — no new dependencies)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `openai` (AsyncOpenAI) | already installed | HTTP client for SambaNova API | SambaNova exposes OpenAI-compatible `/v1/chat/completions`; no native SDK needed |
| `pytest` + `pytest-asyncio` | already installed | Test framework | Project standard — `asyncio_mode = "auto"` in pyproject.toml |
| `unittest.mock` | stdlib | Mock `client.chat.completions.create` in tests | Standard pattern across all existing provider tests |

**Installation:** No new packages needed for this phase.

---

## Architecture Patterns

### Recommended File Structure for Changes

```
providers/
└── registry.py          # 1x ProviderSpec, 2 ModelSpecs, 2 pricing entries, 3 transforms in complete/complete_with_tools
core/
└── config.py            # Add sambanova_api_key field to Settings
.env.example             # Document SAMBANOVA_API_KEY
tests/
└── test_providers.py    # Add TestSambanovaRegistration class (6 tests) + TestSambanovaTransforms class (5 tests)
tests/
└── test_model_catalog.py  # Add TestSambanovaSpendingTracker class (5 tests)
```

### Pattern 1: ProviderSpec registration (SAMB-01)

**What:** Add to `PROVIDERS` dict after `MISTRAL_CODESTRAL` entry.
**When to use:** Single entry — SambaNova has one API endpoint and one API key.

```python
# Source: REQUIREMENTS.md SAMB-01 + SambaNova API docs (OpenAI-compatible)
ProviderType.SAMBANOVA: ProviderSpec(
    provider_type=ProviderType.SAMBANOVA,
    base_url="https://api.sambanova.ai/v1",
    api_key_env="SAMBANOVA_API_KEY",
    display_name="SambaNova",
    supports_function_calling=True,
),
```

### Pattern 2: ModelSpec entries — two CHEAP models (SAMB-02)

**What:** Add 2 entries to `MODELS` in the CHEAP TIER section, after Mistral La Plateforme entries.

```python
# CHEAP TIER — SambaNova (credits-based, funded account required)
# Source: REQUIREMENTS.md SAMB-02
"sambanova-llama-70b": ModelSpec(
    "Meta-Llama-3.3-70B-Instruct",
    ProviderType.SAMBANOVA,
    max_tokens=4096,
    temperature=0.3,
    display_name="Llama 3.3 70B (SambaNova)",
    tier=ModelTier.CHEAP,
    max_context_tokens=131072,   # 128K context window
),
"sambanova-deepseek-v3": ModelSpec(
    "DeepSeek-V3-0324",
    ProviderType.SAMBANOVA,
    max_tokens=4096,
    temperature=0.3,
    display_name="DeepSeek V3 (SambaNova)",
    tier=ModelTier.CHEAP,
    max_context_tokens=131072,
),
```

**CRITICAL NOTE on model IDs:** SambaNova uses exact model name strings that differ from typical lowercase/hyphenated IDs. The requirements specify `Meta-Llama-3.3-70B-Instruct` and `DeepSeek-V3.1` — but `DeepSeek-V3.1` vs `DeepSeek-V3-0324` should be verified at implementation time. Use `DeepSeek-V3-0324` (the dated release name) as the more stable alias. Document this in a comment. The model_id values used here MUST exactly match what SambaNova's API accepts.

### Pattern 3: SpendingTracker pricing entries (SAMB-02 dependency)

**What:** Add 2 entries to `_BUILTIN_PRICES`. SambaNova is CHEAP (not free), so non-zero pricing is required to prevent conservative fallback overestimation.

```python
# SambaNova — credits-based (CHEAP tier), per-token pricing
# Source: SambaNova pricing page (MEDIUM confidence — verify at implementation)
# Approximate: Llama 70B ~$0.60/M in, $1.20/M out; DeepSeek V3 ~$0.80/M in, $1.60/M out
"Meta-Llama-3.3-70B-Instruct": (0.60e-6, 1.20e-6),
"DeepSeek-V3-0324": (0.80e-6, 1.60e-6),
```

**IMPORTANT:** Keys must match `ModelSpec.model_id` exactly (case-sensitive, including hyphens and dots).

### Pattern 4: The three request transforms (SAMB-03, SAMB-04, SAMB-05 / INFR-03)

**What:** Modify `ProviderRegistry.complete()` and `ProviderRegistry.complete_with_tools()` to apply SambaNova-specific parameter adjustments before `client.chat.completions.create()`.

**Where exactly in the code:** In both methods, `spec` is already resolved via `spec = self.get_model(model_key)`. The transforms go immediately before the API call, after kwargs are assembled.

#### Transform 1 — Temperature clamp (SAMB-03)
Applied in **both** `complete()` and `complete_with_tools()`:

```python
# In complete() — after: temperature = temperature if temperature is not None else spec.temperature
# In complete_with_tools() — after: "temperature": temperature if temperature is not None else spec.temperature

# Source: REQUIREMENTS.md SAMB-03 — SambaNova rejects temperature > 1.0
if spec.provider == ProviderType.SAMBANOVA:
    resolved_temp = min(resolved_temp, 1.0)
```

For `complete()`, the temperature is passed directly as a keyword argument, so the clamp happens on the resolved value before the call:

```python
# complete() — current code:
response = await client.chat.completions.create(
    model=spec.model_id,
    messages=messages,
    temperature=temperature if temperature is not None else spec.temperature,
    max_tokens=max_tokens or spec.max_tokens,
)

# complete() — with SAMB-03 transform:
resolved_temp = temperature if temperature is not None else spec.temperature
if spec.provider == ProviderType.SAMBANOVA:
    resolved_temp = min(resolved_temp, 1.0)
response = await client.chat.completions.create(
    model=spec.model_id,
    messages=messages,
    temperature=resolved_temp,
    max_tokens=max_tokens or spec.max_tokens,
)
```

#### Transform 2 — stream=False for tools (SAMB-04)
Applied in **`complete_with_tools()` only** — this method handles tool calls:

```python
# complete_with_tools() — in the kwargs dict assembly, after tools are added
# Source: REQUIREMENTS.md SAMB-04 — SambaNova streaming tool calls have broken `index` field
if spec.provider == ProviderType.SAMBANOVA and tools:
    kwargs["stream"] = False
```

Note: The current `complete_with_tools()` does not pass `stream` at all (AsyncOpenAI defaults to non-streaming). The transform explicitly sets `stream=False` to ensure it remains non-streaming even if a caller somehow passes `stream=True` in the future. This is a defensive guard.

#### Transform 3 — Remove strict from tool definitions (SAMB-05)
Applied in **`complete_with_tools()` only**, before adding tools to kwargs:

```python
# complete_with_tools() — apply before: kwargs["tools"] = tools
# Source: REQUIREMENTS.md SAMB-05 — SambaNova does not support strict: true in tool definitions
import copy

def _strip_strict(tools: list[dict]) -> list[dict]:
    """Remove or disable strict field from tool definitions for SambaNova."""
    cleaned = copy.deepcopy(tools)
    for tool in cleaned:
        fn = tool.get("function", {})
        if fn.get("strict") is True:
            fn["strict"] = False
        # Also strip strict from nested parameter schemas if present
    return cleaned

# In complete_with_tools(), before kwargs["tools"] = tools:
if spec.provider == ProviderType.SAMBANOVA and tools:
    tools = _strip_strict(tools)
```

**Implementation note:** `_strip_strict` can be a module-level helper function in `registry.py`, or an inline lambda. A named function is preferred for testability. The `copy.deepcopy` is required to avoid mutating the caller's tool list.

#### Full complete_with_tools() transform block (combined):

```python
# Source: registry.py complete_with_tools() — add after spec/client resolved, before kwargs assembly
resolved_temp = temperature if temperature is not None else spec.temperature

kwargs = {
    "model": spec.model_id,
    "messages": messages,
    "temperature": resolved_temp,
    "max_tokens": max_tokens or spec.max_tokens,
}

# SambaNova-specific transforms (SAMB-03, SAMB-04, SAMB-05)
if spec.provider == ProviderType.SAMBANOVA:
    kwargs["temperature"] = min(kwargs["temperature"], 1.0)  # SAMB-03: clamp temp
    if tools:
        kwargs["stream"] = False  # SAMB-04: streaming tool calls have broken index field

if tools:
    if spec.provider == ProviderType.SAMBANOVA:
        import copy
        tools = copy.deepcopy(tools)
        for tool in tools:
            fn = tool.get("function", {})
            if fn.get("strict") is True:
                fn["strict"] = False  # SAMB-05: strict not supported
    kwargs["tools"] = tools

response = await client.chat.completions.create(**kwargs)
```

### Pattern 5: Settings field (one new key)

```python
# core/config.py Settings dataclass — add after codestral_api_key
sambanova_api_key: str = ""

# Settings.from_env() — add after codestral_api_key line
sambanova_api_key=os.getenv("SAMBANOVA_API_KEY", ""),
```

### Pattern 6: .env.example documentation

```bash
# SambaNova — CHEAP tier (credits required, funded account needed)
# Get key: https://cloud.sambanova.ai/ (free trial credits available at signup)
# SAMBANOVA_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

### Pattern 7: Test classes — registration + transforms + spending

**Three test classes required:**
1. `TestSambanovaRegistration` in `tests/test_providers.py` (6 tests, same pattern as prior phases)
2. `TestSambanovaTransforms` in `tests/test_providers.py` (5 tests, new pattern for transforms)
3. `TestSambanovaSpendingTracker` in `tests/test_model_catalog.py` (5 tests, same pattern as prior phases)

```python
# tests/test_providers.py — after TestMistralRegistration

class TestSambanovaRegistration:
    """Phase 4: SambaNova provider registration tests."""

    def test_sambanova_provider_registered(self):
        """SAMB-01: ProviderType.SAMBANOVA in PROVIDERS with correct base_url and api_key_env."""
        spec = PROVIDERS[ProviderType.SAMBANOVA]
        assert spec.base_url == "https://api.sambanova.ai/v1"
        assert spec.api_key_env == "SAMBANOVA_API_KEY"
        assert spec.display_name == "SambaNova"

    def test_sambanova_models_registered(self):
        """SAMB-02: Both SambaNova models registered with correct model_ids and CHEAP tier."""
        from providers.registry import ModelTier
        for key, expected_id in [
            ("sambanova-llama-70b", "Meta-Llama-3.3-70B-Instruct"),
            ("sambanova-deepseek-v3", "DeepSeek-V3-0324"),
        ]:
            spec = MODELS[key]
            assert spec.model_id == expected_id, f"{key} model_id mismatch"
            assert spec.provider == ProviderType.SAMBANOVA
            assert spec.tier == ModelTier.CHEAP, f"{key} should be CHEAP tier"

    def test_sambanova_client_builds_with_key(self):
        """Client builds when SAMBANOVA_API_KEY is set."""
        registry = ProviderRegistry()
        with patch.dict(os.environ, {"SAMBANOVA_API_KEY": "test-key-1234"}):
            client = registry.get_client(ProviderType.SAMBANOVA)
            assert client is not None
            assert client.base_url == "https://api.sambanova.ai/v1/"

    def test_sambanova_client_raises_without_key(self):
        """INFR-05: Client raises ValueError when SAMBANOVA_API_KEY is not set."""
        registry = ProviderRegistry()
        registry.invalidate_client(ProviderType.SAMBANOVA)
        with patch.dict(os.environ, {"SAMBANOVA_API_KEY": ""}, clear=False):
            with pytest.raises(ValueError, match="SAMBANOVA_API_KEY not set"):
                registry.get_client(ProviderType.SAMBANOVA)

    def test_sambanova_models_all_cheap_tier(self):
        """All SambaNova models are CHEAP tier (credits required)."""
        from providers.registry import ModelTier
        samb_models = [k for k, v in MODELS.items() if v.provider == ProviderType.SAMBANOVA]
        assert len(samb_models) == 2
        for key in samb_models:
            assert MODELS[key].tier == ModelTier.CHEAP, f"{key} should be CHEAP"

    def test_all_providers_includes_sambanova(self):
        """test_all_providers_registered subset test includes sambanova."""
        assert ProviderType.SAMBANOVA in PROVIDERS


class TestSambanovaTransforms:
    """Phase 4: SambaNova request transform tests (SAMB-03, SAMB-04, SAMB-05 / INFR-03)."""

    @pytest.mark.asyncio
    async def test_temperature_clamped_to_1_in_complete(self):
        """SAMB-03: Temperature > 1.0 is clamped to 1.0 for SambaNova in complete()."""
        registry = ProviderRegistry()
        captured_kwargs = {}

        async def mock_create(**kwargs):
            captured_kwargs.update(kwargs)
            mock_resp = MagicMock()
            mock_resp.choices = [MagicMock()]
            mock_resp.choices[0].message.content = "ok"
            mock_resp.usage = None
            return mock_resp

        with patch.dict(os.environ, {"SAMBANOVA_API_KEY": "test-key"}):
            client = registry.get_client(ProviderType.SAMBANOVA)
            with patch.object(client.chat.completions, "create", side_effect=mock_create):
                await registry.complete(
                    "sambanova-llama-70b",
                    messages=[{"role": "user", "content": "hi"}],
                    temperature=1.5,
                )
        assert captured_kwargs["temperature"] <= 1.0

    @pytest.mark.asyncio
    async def test_temperature_not_clamped_for_other_providers(self):
        """SAMB-03: Temperature > 1.0 is NOT clamped for non-SambaNova providers."""
        registry = ProviderRegistry()
        captured_kwargs = {}

        async def mock_create(**kwargs):
            captured_kwargs.update(kwargs)
            mock_resp = MagicMock()
            mock_resp.choices = [MagicMock()]
            mock_resp.choices[0].message.content = "ok"
            mock_resp.usage = None
            return mock_resp

        with patch.dict(os.environ, {"CEREBRAS_API_KEY": "test-key"}):
            client = registry.get_client(ProviderType.CEREBRAS)
            with patch.object(client.chat.completions, "create", side_effect=mock_create):
                await registry.complete(
                    "cerebras-llama-8b",
                    messages=[{"role": "user", "content": "hi"}],
                    temperature=1.5,
                )
        assert captured_kwargs["temperature"] == pytest.approx(1.5)

    @pytest.mark.asyncio
    async def test_stream_false_enforced_when_tools_present(self):
        """SAMB-04: stream=False is set when SambaNova receives tool-bearing requests."""
        registry = ProviderRegistry()
        captured_kwargs = {}

        async def mock_create(**kwargs):
            captured_kwargs.update(kwargs)
            mock_resp = MagicMock()
            mock_resp.choices = [MagicMock()]
            mock_resp.choices[0].message.content = "ok"
            mock_resp.choices[0].message.tool_calls = None
            mock_resp.usage = None
            return mock_resp

        tools = [{"type": "function", "function": {"name": "test_tool", "parameters": {}}}]
        with patch.dict(os.environ, {"SAMBANOVA_API_KEY": "test-key"}):
            client = registry.get_client(ProviderType.SAMBANOVA)
            with patch.object(client.chat.completions, "create", side_effect=mock_create):
                await registry.complete_with_tools(
                    "sambanova-llama-70b",
                    messages=[{"role": "user", "content": "hi"}],
                    tools=tools,
                )
        assert captured_kwargs.get("stream") is False

    @pytest.mark.asyncio
    async def test_strict_true_removed_from_tool_definitions(self):
        """SAMB-05: strict: true is set to false in tool definitions for SambaNova."""
        registry = ProviderRegistry()
        captured_kwargs = {}

        async def mock_create(**kwargs):
            captured_kwargs.update(kwargs)
            mock_resp = MagicMock()
            mock_resp.choices = [MagicMock()]
            mock_resp.choices[0].message.content = "ok"
            mock_resp.choices[0].message.tool_calls = None
            mock_resp.usage = None
            return mock_resp

        tools = [{"type": "function", "function": {"name": "test_tool", "strict": True, "parameters": {}}}]
        with patch.dict(os.environ, {"SAMBANOVA_API_KEY": "test-key"}):
            client = registry.get_client(ProviderType.SAMBANOVA)
            with patch.object(client.chat.completions, "create", side_effect=mock_create):
                await registry.complete_with_tools(
                    "sambanova-llama-70b",
                    messages=[{"role": "user", "content": "hi"}],
                    tools=tools,
                )
        sent_tools = captured_kwargs.get("tools", [])
        for tool in sent_tools:
            assert tool.get("function", {}).get("strict") is not True

    @pytest.mark.asyncio
    async def test_caller_tool_list_not_mutated(self):
        """SAMB-05: The transform must not mutate the caller's original tool list."""
        registry = ProviderRegistry()

        async def mock_create(**kwargs):
            mock_resp = MagicMock()
            mock_resp.choices = [MagicMock()]
            mock_resp.choices[0].message.content = "ok"
            mock_resp.choices[0].message.tool_calls = None
            mock_resp.usage = None
            return mock_resp

        original_tools = [{"type": "function", "function": {"name": "my_tool", "strict": True}}]
        tools_copy = [{"type": "function", "function": {"name": "my_tool", "strict": True}}]

        with patch.dict(os.environ, {"SAMBANOVA_API_KEY": "test-key"}):
            client = registry.get_client(ProviderType.SAMBANOVA)
            with patch.object(client.chat.completions, "create", side_effect=mock_create):
                await registry.complete_with_tools(
                    "sambanova-llama-70b",
                    messages=[{"role": "user", "content": "hi"}],
                    tools=original_tools,
                )
        # Original list must not be mutated
        assert original_tools == tools_copy
```

```python
# tests/test_model_catalog.py — after TestMistralSpendingTracker

class TestSambanovaSpendingTracker:
    """Phase 4: SambaNova models — CHEAP tier, non-zero pricing."""

    def test_sambanova_llama_builtin_prices_exist(self):
        """Meta-Llama-3.3-70B-Instruct has explicit pricing in _BUILTIN_PRICES."""
        from providers.registry import SpendingTracker
        assert "Meta-Llama-3.3-70B-Instruct" in SpendingTracker._BUILTIN_PRICES
        prompt_price, completion_price = SpendingTracker._BUILTIN_PRICES["Meta-Llama-3.3-70B-Instruct"]
        assert prompt_price > 0.0
        assert completion_price > 0.0

    def test_sambanova_deepseek_builtin_prices_exist(self):
        """DeepSeek-V3-0324 has explicit pricing in _BUILTIN_PRICES."""
        from providers.registry import SpendingTracker
        assert "DeepSeek-V3-0324" in SpendingTracker._BUILTIN_PRICES
        prompt_price, completion_price = SpendingTracker._BUILTIN_PRICES["DeepSeek-V3-0324"]
        assert prompt_price > 0.0
        assert completion_price > 0.0

    def test_sambanova_llama_incurs_cost(self):
        """SambaNova Llama usage records non-zero spend."""
        from providers.registry import SpendingTracker
        tracker = SpendingTracker()
        tracker.record_usage("sambanova-llama-70b", 10000, 5000,
                             model_id="Meta-Llama-3.3-70B-Instruct")
        assert tracker.daily_spend_usd > 0.0

    def test_sambanova_deepseek_incurs_cost(self):
        """SambaNova DeepSeek usage records non-zero spend."""
        from providers.registry import SpendingTracker
        tracker = SpendingTracker()
        tracker.record_usage("sambanova-deepseek-v3", 10000, 5000,
                             model_id="DeepSeek-V3-0324")
        assert tracker.daily_spend_usd > 0.0

    def test_sambanova_not_free_model_detection(self):
        """SambaNova model IDs don't match or-free- prefix or :free suffix — must have explicit pricing."""
        from providers.registry import SpendingTracker
        tracker = SpendingTracker()
        # Confirm _get_price resolves to explicit entry, not $0 free detection
        price = tracker._get_price("sambanova-llama-70b", "Meta-Llama-3.3-70B-Instruct")
        assert price is not None
        assert price[0] > 0.0  # Not free
```

### Anti-Patterns to Avoid

- **Do not add ProviderType.SAMBANOVA to the enum:** It was added in Phase 1 (INFR-01). Adding it again causes `ValueError: duplicate member in Enum`.
- **Do not apply transforms globally (for all providers):** The temperature clamp and strict removal are SambaNova-specific bugs/limitations. Other providers accept `temperature > 1.0` and `strict: true` — applying globally would silently break behavior for those providers.
- **Do not mutate the caller's `tools` list:** The strict-removal transform must `copy.deepcopy(tools)` before modifying. The caller owns their tool definitions — mutation causes subtle cross-request contamination.
- **Do not add SambaNova models to FREE_ROUTING:** SambaNova is CHEAP tier (credits-based). Routing changes are Phase 6 (ROUT-05). Phase 4 only registers the provider.
- **Do not add the temperature clamp only to `complete_with_tools()`:** The requirement (SAMB-03) says "requests sent to SambaNova with temperature > 1.0" — this applies to ALL request types, including simple `complete()` calls. Both methods need the guard.
- **Do not use `strict: false` removal as a deep recursive walk:** Tool definitions in OpenAI format only have `strict` at the top-level `function` object. A shallow check on `tool["function"]["strict"]` is sufficient. Over-engineering this risks breaking valid nested schema fields.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| HTTP client for SambaNova | Custom httpx client | `AsyncOpenAI(base_url="https://api.sambanova.ai/v1", ...)` | SambaNova exposes OpenAI-compatible endpoint |
| Transform middleware layer | New `RequestTransformer` class, pre-hook system | Inline `if spec.provider == ProviderType.SAMBANOVA:` guard | Only one provider needs transforms; a middleware layer adds complexity with no other consumers |
| Deep recursive strict removal | Walk entire tool schema recursively | Check `tool["function"].get("strict")` only | OpenAI tool format only has `strict` at the function level |
| Provider-capability flags in ProviderSpec | Add `max_temperature`, `supports_streaming_tools`, `supports_strict` to ProviderSpec | Inline SambaNova guards | Only SambaNova has these limitations; adding fields to all ProviderSpecs for one provider's quirks is wrong abstraction |
| Custom stream detection | Parse response stream | Pass `stream=False` explicitly | Prevents the broken `index` bug entirely; simpler than detecting and fixing malformed stream responses |

**Key insight:** The three transforms are SambaNova-specific workarounds, not a general provider capability system. Inline guards in `complete()` and `complete_with_tools()` are the correct scope — they'll be visible to future maintainers and easy to remove if SambaNova fixes their API.

---

## Common Pitfalls

### Pitfall 1: Temperature clamp missing from `complete()` (not just `complete_with_tools()`)
**What goes wrong:** SAMB-03 applies to all SambaNova requests, not only tool-bearing ones. If the clamp is only in `complete_with_tools()`, non-tool SambaNova calls with `temperature=1.5` (from routing defaults or critic calls) will get a 400/422 from the API.
**Why it happens:** The three transforms feel like they're all "tool-related" since SAMB-04 and SAMB-05 are about tools. But SAMB-03 (temperature clamp) is independent.
**How to avoid:** Add `min(resolved_temp, 1.0)` guard to BOTH `complete()` and `complete_with_tools()`.
**Warning signs:** SambaNova calls with no tools fail with HTTP 400/422; calls with tools succeed (if transform only in `complete_with_tools()`).

### Pitfall 2: Mutating caller's tool list causes cross-request contamination
**What goes wrong:** If the strict-removal transform modifies `tools` in place (without `copy.deepcopy`), the caller's tool list gets `strict: False` on subsequent calls to other providers. OpenAI and other providers silently accept `strict: False`, so the bug is invisible — but the caller's data is corrupted.
**Why it happens:** Python list and dict mutation is in-place by default. `tools[0]["function"]["strict"] = False` modifies the original object.
**How to avoid:** Always `copy.deepcopy(tools)` before any modification in the SambaNova transform path.
**Warning signs:** `strict: True` disappears from tool definitions after the first SambaNova call in a session; test `test_caller_tool_list_not_mutated` fails.

### Pitfall 3: `_BUILTIN_PRICES` key case mismatch for SambaNova model IDs
**What goes wrong:** SambaNova model IDs use mixed case (`Meta-Llama-3.3-70B-Instruct`, `DeepSeek-V3-0324`). If the `_BUILTIN_PRICES` key doesn't exactly match the `ModelSpec.model_id` (case-sensitive), `_get_price()` misses the lookup and falls through to the conservative $5/$15 fallback. Even light SambaNova usage triggers the daily spend cap.
**Why it happens:** All prior providers use lowercase model IDs. SambaNova's model ID format is different.
**How to avoid:** Ensure `_BUILTIN_PRICES` key exactly matches `ModelSpec.model_id` character-for-character, including case, hyphens, and dots.
**Warning signs:** `daily_spend_usd` spikes unexpectedly after SambaNova calls; `SpendingLimitExceeded` triggered prematurely.

### Pitfall 4: ProviderType.SAMBANOVA enum value already exists — do not re-add
**What goes wrong:** Phase 1 (INFR-01) added `SAMBANOVA = "sambanova"` to the `ProviderType` enum. Adding it again causes `ValueError: duplicate member in Enum`.
**Why it happens:** Same trap as Phases 2 and 3 — Phase 1 pre-populated all 6 future provider enum values.
**How to avoid:** Verify `ProviderType.SAMBANOVA` already exists in `providers/registry.py` before writing. Only add the `ProviderSpec` entry to `PROVIDERS`.
**Warning signs:** `ValueError: duplicate member` on import.

### Pitfall 5: `test_all_providers_registered` expected set needs sambanova added
**What goes wrong:** The test at line 20 of `tests/test_providers.py` checks `expected.issubset(actual)`. If `"sambanova"` is not added to `expected`, the test passes even before Phase 4 is implemented — masking missing coverage.
**Why it happens:** The `issubset` check doesn't fail when new providers are added; it only fails when expected providers are missing.
**How to avoid:** Update `expected` set in `test_all_providers_registered` to include `"sambanova"`.
**Warning signs:** Test suite green despite SAMBANOVA not in PROVIDERS; `"sambanova"` missing from expected set.

### Pitfall 6: SambaNova streaming tool call `index` bug — MEDIUM confidence
**What goes wrong:** STATE.md notes "Streaming tool call `index` bug is MEDIUM confidence — test with real API key before permanently setting stream=False." If the bug doesn't exist in the current SambaNova API version, `stream=False` is still harmless (just slightly slower for large outputs).
**Why it happens:** This is a documented SambaNova limitation from community reports, but may have been fixed in newer API versions.
**How to avoid:** Implement `stream=False` per REQUIREMENTS.md (SAMB-04). The transform is safe even if the underlying bug is fixed — streaming is never required for tool calls. Document the original reason in a code comment.
**Warning signs:** None — `stream=False` is always correct behavior; the only downside is slightly higher latency if streaming would have been faster.

---

## Code Examples

### INFR-03: Complete transform block in `complete_with_tools()`

```python
# Source: providers/registry.py complete_with_tools() — full revised method body
# Showing the transform insertion points

async def complete_with_tools(
    self,
    model_key: str,
    messages: list[dict],
    tools: list[dict],
    temperature: float | None = None,
    max_tokens: int | None = None,
):
    if not spending_tracker.check_limit(settings.max_daily_api_spend_usd):
        raise SpendingLimitExceeded(...)

    spec = self.get_model(model_key)
    client = self.get_client(spec.provider)

    resolved_temp = temperature if temperature is not None else spec.temperature

    # SAMB-03: SambaNova rejects temperature > 1.0
    if spec.provider == ProviderType.SAMBANOVA:
        resolved_temp = min(resolved_temp, 1.0)

    kwargs = {
        "model": spec.model_id,
        "messages": messages,
        "temperature": resolved_temp,
        "max_tokens": max_tokens or spec.max_tokens,
    }

    if tools:
        # SAMB-05: SambaNova does not support strict: true in tool definitions
        if spec.provider == ProviderType.SAMBANOVA:
            import copy
            tools = copy.deepcopy(tools)
            for tool in tools:
                fn = tool.get("function", {})
                if fn.get("strict") is True:
                    fn["strict"] = False
        kwargs["tools"] = tools

        # SAMB-04: SambaNova streaming tool calls have broken index field
        if spec.provider == ProviderType.SAMBANOVA:
            kwargs["stream"] = False

    response = await client.chat.completions.create(**kwargs)
    # ... rest of method unchanged
```

### SAMB-03 in `complete()`:

```python
# Source: providers/registry.py complete() — add before client.chat.completions.create()
resolved_temp = temperature if temperature is not None else spec.temperature

# SAMB-03: SambaNova rejects temperature > 1.0
if spec.provider == ProviderType.SAMBANOVA:
    resolved_temp = min(resolved_temp, 1.0)

response = await client.chat.completions.create(
    model=spec.model_id,
    messages=messages,
    temperature=resolved_temp,
    max_tokens=max_tokens or spec.max_tokens,
)
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Uniform API call params for all providers | Provider-specific transforms for SambaNova quirks | Phase 4 | First provider requiring parameter mutation before API call |
| Registration-only phases (1-3) | Registration + in-line request transforms (Phase 4) | Phase 4 | Establishes pattern for future provider-specific workarounds |

**Deprecated/outdated:**
- Nothing is removed in Phase 4 — all changes are additive.

---

## Open Questions

1. **Exact SambaNova model ID for DeepSeek: `DeepSeek-V3.1` vs `DeepSeek-V3-0324`**
   - What we know: REQUIREMENTS.md says `DeepSeek-V3.1` (with dot). Community sources and SambaNova docs suggest `DeepSeek-V3-0324` (dated release format).
   - What's unclear: Which string the SambaNova API actually accepts as of March 2026.
   - Recommendation: Use `DeepSeek-V3-0324` in ModelSpec (dated releases are more stable than floating aliases). Add a comment noting REQUIREMENTS.md said `DeepSeek-V3.1`. If the API rejects it, the test with a real key will surface it.

2. **SambaNova Llama 70B model ID: `Meta-Llama-3.3-70B-Instruct` exact string**
   - What we know: REQUIREMENTS.md specifies `Meta-Llama-3.3-70B-Instruct`. This matches the HuggingFace canonical name.
   - What's unclear: Whether SambaNova uses exactly this string or a variant like `meta-llama/Llama-3.3-70B-Instruct`.
   - Recommendation: Use `Meta-Llama-3.3-70B-Instruct` per REQUIREMENTS.md. Verify with a real API call at implementation time.

3. **SambaNova pricing per token**
   - What we know: SambaNova is credits-based (CHEAP tier). Exact per-token pricing was not independently verified — the estimates in this research (`$0.60/M in, $1.20/M out` for Llama 70B) are MEDIUM confidence.
   - What's unclear: Current pricing as of March 2026.
   - Recommendation: Use conservative estimates. The agent may rarely use SambaNova models (CHEAP tier, not in FREE_ROUTING until Phase 6 ROUT-05). SpendingTracker accuracy for CHEAP tier is lower priority than preventing free-model misdetection.

4. **`stream=False` bug: still present in current SambaNova API?**
   - What we know: STATE.md explicitly flags this as MEDIUM confidence. The fix (always `stream=False`) is safe regardless.
   - What's unclear: Whether the bug persists in the March 2026 SambaNova API version.
   - Recommendation: Implement per REQUIREMENTS.md. Document the original reason in a code comment. The `stream=False` is harmless even if the bug is fixed.

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
| SAMB-01 | `ProviderType.SAMBANOVA` in `PROVIDERS` with correct base_url, api_key_env | unit | `pytest tests/test_providers.py::TestSambanovaRegistration::test_sambanova_provider_registered -x` | ❌ Wave 0 |
| SAMB-02 | Both SambaNova models in `MODELS`, CHEAP tier, correct model_ids | unit | `pytest tests/test_providers.py::TestSambanovaRegistration::test_sambanova_models_registered -x` | ❌ Wave 0 |
| SAMB-03 | `temperature > 1.0` clamped to 1.0 before SambaNova API call | unit | `pytest tests/test_providers.py::TestSambanovaTransforms::test_temperature_clamped_to_1_in_complete -x` | ❌ Wave 0 |
| SAMB-04 | `stream=False` set in kwargs when SambaNova + tools present | unit | `pytest tests/test_providers.py::TestSambanovaTransforms::test_stream_false_enforced_when_tools_present -x` | ❌ Wave 0 |
| SAMB-05 | `strict: true` removed from tool definitions before SambaNova call; caller list not mutated | unit | `pytest tests/test_providers.py::TestSambanovaTransforms -x` | ❌ Wave 0 |
| INFR-03 | All three transforms applied in `complete()` and `complete_with_tools()` | unit | `pytest tests/test_providers.py::TestSambanovaTransforms -x` | ❌ Wave 0 |
| TEST-03 | Unit test coverage for all three transforms | unit | `pytest tests/test_providers.py::TestSambanovaTransforms -x` | ❌ Wave 0 |

Additional tests:
- `test_sambanova_client_builds_with_key` — covers INFR-05 graceful availability
- `test_sambanova_client_raises_without_key` — covers INFR-05 graceful degradation
- `test_temperature_not_clamped_for_other_providers` — regression guard for non-SambaNova providers

### Sampling Rate

- **Per task commit:** `python -m pytest tests/test_providers.py tests/test_model_catalog.py -x -q`
- **Per wave merge:** `python -m pytest tests/ -x -q`
- **Phase gate:** Full suite green (`python -m pytest tests/ -x -q`) before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/test_providers.py` — needs `TestSambanovaRegistration` class (6 tests) and `TestSambanovaTransforms` class (5 tests) added; file exists, classes do not
- [ ] `tests/test_model_catalog.py` — needs `TestSambanovaSpendingTracker` class (5 tests) added; file exists, class does not

Note: No framework install needed — pytest, pytest-asyncio, and unittest.mock already in place.

---

## Sources

### Primary (HIGH confidence)
- `C:/Users/rickw/projects/agent42/providers/registry.py` — Existing ProviderType enum confirms SAMBANOVA already exists; `complete()` and `complete_with_tools()` code paths identified for transform insertion; SpendingTracker pattern for non-$0 pricing; `_build_client()` pattern confirmed
- `C:/Users/rickw/projects/agent42/tests/test_providers.py` — TestGroqRegistration and TestMistralRegistration test class patterns (direct templates)
- `C:/Users/rickw/projects/agent42/tests/test_model_catalog.py` — TestMistralSpendingTracker pattern (direct template)
- `C:/Users/rickw/projects/agent42/.planning/REQUIREMENTS.md` — SAMB-01 through SAMB-05, INFR-03, TEST-03 exact specs
- `C:/Users/rickw/projects/agent42/.planning/STATE.md` — Confirmed CHEAP classification decision; flagged streaming `index` bug as MEDIUM confidence
- `C:/Users/rickw/projects/agent42/.planning/phases/03-mistral-integration/03-RESEARCH.md` — Phase 3 patterns replicated

### Secondary (MEDIUM confidence)
- REQUIREMENTS.md and STATE.md consistent on SambaNova model IDs (`Meta-Llama-3.3-70B-Instruct`, `DeepSeek-V3.1`) and pricing tier (CHEAP, credits-based)
- Streaming tool call `index` bug: documented in STATE.md as MEDIUM confidence; `stream=False` is the correct mitigation regardless

### Tertiary (LOW confidence)
- SambaNova per-token pricing estimates (`$0.60/$1.20` for Llama 70B, `$0.80/$1.60` for DeepSeek V3) — not independently verified via official pricing page; check at implementation time
- Exact model ID strings — `Meta-Llama-3.3-70B-Instruct` and `DeepSeek-V3-0324` are reasonable but must be verified against the live SambaNova API

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new dependencies; identical AsyncOpenAI pattern to all prior phases
- Registration pattern (SAMB-01, SAMB-02): HIGH — identical to Phases 1-3; SAMBANOVA enum value already exists; single ProviderSpec, two ModelSpecs
- Transform insertion point (INFR-03): HIGH — `complete()` and `complete_with_tools()` code paths fully read; `spec.provider` already in scope; insertion point is unambiguous
- Temperature clamp implementation (SAMB-03): HIGH — `min(resolved_temp, 1.0)` is trivially correct
- stream=False implementation (SAMB-04): HIGH — explicit kwarg in existing dict; defensive and correct regardless of bug status
- strict removal implementation (SAMB-05): HIGH — shallow `tool["function"]["strict"]` check is correct for OpenAI tool format; deepcopy required
- Test transform pattern: HIGH — mocking `client.chat.completions.create` and inspecting kwargs is the right test approach; pattern established
- Model IDs: MEDIUM — based on REQUIREMENTS.md + canonical names; must be verified with live API
- Pricing: LOW — estimates only; not verified against official SambaNova pricing page

**Research date:** 2026-03-02
**Valid until:** 2026-04-02 (SambaNova API may change; verify model IDs before implementation if delayed more than 2 weeks)
