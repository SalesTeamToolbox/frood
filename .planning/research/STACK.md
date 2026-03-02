# Technology Stack — Cerebras Provider Integration

**Project:** Agent42 Free LLM Provider Expansion (Cerebras)
**Researched:** 2026-03-01
**Research mode:** Ecosystem / Feasibility
**Overall confidence:** HIGH (all core facts verified against official Cerebras docs)

---

## Cerebras API — Verified Specifications

### 1. API Base URL and Authentication

| Field | Value |
|-------|-------|
| Base URL | `https://api.cerebras.ai/v1` |
| Auth method | Bearer token via `Authorization: Bearer <key>` header |
| Key env var convention | `CEREBRAS_API_KEY` |
| Key source | [cloud.cerebras.ai](https://cloud.cerebras.ai/) |

**Confirmed working with `AsyncOpenAI` client** (Agent42's existing pattern):

```python
from openai import AsyncOpenAI

client = AsyncOpenAI(
    base_url="https://api.cerebras.ai/v1",
    api_key=os.getenv("CEREBRAS_API_KEY"),
    max_retries=0,  # Agent42 manages retries in _complete_with_retry
)
```

No native Cerebras SDK required. The OpenAI Python SDK works as-is.

Source: [Cerebras OpenAI Compatibility](https://inference-docs.cerebras.ai/resources/openai)

---

### 2. OpenAI Compatibility Level

**Verdict: HIGH compatibility. Drop-in for chat completions, tool calling, and streaming.**

| Feature | Status | Notes |
|---------|--------|-------|
| Chat completions (`/v1/chat/completions`) | SUPPORTED | Full OpenAI-compatible format |
| Streaming (`stream=True`) | SUPPORTED | SSE streaming identical to OpenAI |
| Function/tool calling (`tools=`) | SUPPORTED | Parallel tool calls, `tool_choice="auto"`, strict mode |
| Structured outputs | SUPPORTED | Constrained decoding, `strict: true` in tool schema |
| Prompt caching | SUPPORTED | On `gpt-oss-120b`, `qwen-3-235b-a22b-instruct-2507`, `zai-glm-4.7` |
| Text completions (`/v1/completions`) | SUPPORTED | Available but limited |
| Embeddings | NOT OFFERED | No `/v1/embeddings` endpoint |
| Vision / multimodal | NOT SUPPORTED | Text input/output only on all models |
| `frequency_penalty` | NOT SUPPORTED | Returns 400 error if passed |
| `logit_bias` | NOT SUPPORTED | Returns 400 error if passed |
| `presence_penalty` | NOT SUPPORTED | Returns 400 error if passed |

**Critical difference from OpenAI:** The `gpt-oss-120b` model maps `system` role messages to a "developer-level instruction layer" — system messages have stronger weight than in OpenAI's implementation. Identical prompts may produce different outputs.

**Custom Cerebras parameters** (e.g., `disable_reasoning`, `clear_thinking` for `zai-glm-4.7`) must be passed via `extra_body` when using the OpenAI client:

```python
response = await client.chat.completions.create(
    model="zai-glm-4.7",
    messages=[...],
    extra_body={"disable_reasoning": True}
)
```

Source: [Cerebras OpenAI Compatibility](https://inference-docs.cerebras.ai/resources/openai), [Tool Calling](https://inference-docs.cerebras.ai/capabilities/tool-use)

---

### 3. Available Models — Exact Model IDs (Current as of 2026-03-01)

#### Production Models (stable)

| Agent42 Key | API Model ID | Parameters | Speed | Context (Free) | Context (Paid) | Max Output (Free) | Function Calling | Tier |
|-------------|--------------|-----------|-------|---------------|----------------|------------------|-----------------|------|
| `cerebras-gpt-oss-120b` | `gpt-oss-120b` | 120B (MoE, 5.1B active) | ~3,000 tok/s | 65k | 131k | 32k | YES | FREE |
| `cerebras-llama-8b` | `llama3.1-8b` | 8B | ~2,200 tok/s | 8k | 32k | 8k | YES | FREE |

#### Preview Models (stable enough for production use, may change)

| Agent42 Key | API Model ID | Parameters | Speed | Context (Free) | Context (Paid) | Max Output (Free) | Function Calling | Tier |
|-------------|--------------|-----------|-------|---------------|----------------|------------------|-----------------|------|
| `cerebras-qwen3-235b` | `qwen-3-235b-a22b-instruct-2507` | 235B (MoE) | ~1,400 tok/s | 65k | 131k | 32k | YES | FREE |
| `cerebras-zai-glm47` | `zai-glm-4.7` | 355B (MoE, ~32B active) | ~1,000 tok/s | 64k | 131k | 40k | YES | FREE |

#### Deprecated — DO NOT USE

| API Model ID | Deprecation Date | Replacement |
|--------------|-----------------|------------|
| `qwen-3-32b` | 2026-02-16 | `qwen-3-235b-a22b-instruct-2507` |
| `llama-3.3-70b` | 2026-02-16 | `gpt-oss-120b` |
| `llama3.3-70b` (alt ID) | 2026-02-16 | `gpt-oss-120b` |

**Recommended primary model for Agent42:** `gpt-oss-120b` — fastest (3,000 tok/s), 65k context on free tier, full tool calling, OpenAI-developed weights (best instruction following).

**Recommended for reasoning/complex tasks:** `zai-glm-4.7` — top open-source benchmark scores (beats Kimi K2), strong agentic tool use, built-in reasoning mode. Lower RPM (10 vs 30) limits it to critic/review roles.

Sources: [Models Overview](https://inference-docs.cerebras.ai/models/overview), [GPT-OSS-120B](https://inference-docs.cerebras.ai/models/openai-oss), [Qwen 3 235B](https://inference-docs.cerebras.ai/models/qwen-3-235b-2507), [Llama 3.1 8B](https://inference-docs.cerebras.ai/models/llama-31-8b), [ZAI GLM 4.7](https://inference-docs.cerebras.ai/models/zai-glm-47)

---

### 4. Free Tier Rate Limits

Cerebras uses **token-bucket algorithm** — capacity replenishes continuously, not on fixed intervals.

#### Per-Model Free Tier Limits

| API Model ID | RPM (free) | Input Tokens/min (free) | RPD (free) | TPD (free) |
|--------------|-----------|------------------------|-----------|-----------|
| `gpt-oss-120b` | 30 | 60,000 | 14,400 | 1,000,000 |
| `llama3.1-8b` | 30 | 60,000 | 14,400 | 1,000,000 |
| `qwen-3-235b-a22b-instruct-2507` | 30 | 60,000 | 14,400 | 1,000,000 |
| `zai-glm-4.7` | **10** | 60,000 | **100** | 1,000,000 |

**Key observations:**
- 1M tokens/day is shared across all requests to that model (not all models combined)
- `zai-glm-4.7` has a severely restricted RPD (100/day) due to high demand — use only for critic/review
- Context window is reduced on free tier: 65k (not 131k) for most models, 8k for Llama 3.1 8B
- High-demand note: Cerebras has temporarily reduced free-tier limits on `zai-glm-4.7` and `qwen-3-235b-a22b-instruct-2507`

Source: [Rate Limits](https://inference-docs.cerebras.ai/support/rate-limits)

---

### 5. Rate Limit Headers

All responses include these headers for client-side throttling:

| Header | Description |
|--------|-------------|
| `x-ratelimit-limit-requests-day` | Maximum requests allowed per day |
| `x-ratelimit-limit-tokens-minute` | Maximum input tokens per minute |
| `x-ratelimit-remaining-requests-day` | Remaining requests today |
| `x-ratelimit-remaining-tokens-minute` | Remaining input tokens this minute |
| `x-ratelimit-reset-requests-day` | When daily request limit resets (Unix timestamp) |
| `x-ratelimit-reset-tokens-minute` | When per-minute token limit resets (Unix timestamp) |

**Agent42 integration note:** Access via `response.headers` with `with_raw_response` wrapper, or read from `APIStatusError.response.headers` inside `except RateLimitError` blocks. The existing `_is_rate_limit_error()` check catches 429 status codes — no changes needed there.

Source: [Rate Limits](https://inference-docs.cerebras.ai/support/rate-limits)

---

### 6. Error Codes

| HTTP Code | Cerebras SDK Exception | Description | Agent42 Handling |
|-----------|----------------------|-------------|-----------------|
| 400 | `BadRequestError` | Invalid params (e.g., `frequency_penalty`) | Skip retry, log error |
| 401 | `AuthenticationError` | Missing/invalid API key | `_is_auth_error()` — skip retry |
| 402 | `PaymentRequired` | Billing issue (free tier exceeded?) | `_is_payment_error()` — skip retry |
| 403 | `PermissionDeniedError` | Insufficient permissions | Skip retry |
| 404 | `NotFoundError` | Model not found (deprecated model ID) | `_is_auth_error()` handles 404 already |
| 422 | `UnprocessableEntityError` | Validation failure | Skip retry |
| 429 | `RateLimitError` | Rate limit exceeded | `_is_rate_limit_error()` — exponential backoff + add to `_failed_models` |
| 500 | `InternalServerError` | Server error | Retry with backoff |
| 503 | `ServiceUnavailable` | Temporary outage | Retry with backoff |
| N/A | `APIConnectionError` | Network failure | Retry with backoff |
| N/A | `APITimeoutError` | Request timeout | Default 60s; retry twice |

**SDK retry behavior:** The native Cerebras SDK auto-retries 2x by default. Since Agent42 uses the OpenAI client with `max_retries=0`, Agent42's `_complete_with_retry` handles all retry logic — which is correct. Do not use native Cerebras SDK.

Source: [Error Codes](https://inference-docs.cerebras.ai/support/error)

---

### 7. SDK and Client Requirements

**Recommendation: Use existing `AsyncOpenAI` client — no new SDK needed.**

| Option | Package | Async Support | Verdict |
|--------|---------|--------------|---------|
| OpenAI Python SDK | `openai` (already installed) | YES (`AsyncOpenAI`) | USE THIS |
| Cerebras native SDK | `cerebras_cloud_sdk` | YES | Do not use — adds dependency, no benefit |

**Important Cerebras SDK caveats (if ever used):**
- TCP warming: SDK sends a warmup request to `/v1/tcp_warming` on construction — can cause unexpected network calls in tests
- Instance reuse: Repeatedly constructing the SDK instance degrades performance
- These caveats do NOT apply when using the OpenAI client

---

### 8. Known Limitations and Gotchas

| # | Limitation | Impact | Mitigation |
|---|-----------|--------|-----------|
| L1 | `frequency_penalty`, `logit_bias`, `presence_penalty` not supported — 400 error | Medium | Never pass these parameters to Cerebras models. Agent42's `complete_with_tools` doesn't currently send them — safe. |
| L2 | `zai-glm-4.7` RPD is only 100/day on free tier | High | Reserve `zai-glm-4.7` for critic role only; primary loops must use `gpt-oss-120b` |
| L3 | Free tier context window is 8k for `llama3.1-8b` (vs 32k paid) | Medium | Use `gpt-oss-120b` (65k free) for context-heavy tasks; `llama3.1-8b` only for lightweight tasks |
| L4 | No embeddings endpoint | Low | Agent42 already falls back to OpenAI for embeddings (pitfall #46) — no change needed |
| L5 | No vision/multimodal | Low | Document clearly; no workaround |
| L6 | `qwen-3-235b` only supports non-thinking mode (no `<think>` tags) | Low | Noted in model spec; don't rely on reasoning traces |
| L7 | `zai-glm-4.7` reasoning is ON by default — adds tokens to output | Medium | Pass `extra_body={"disable_reasoning": True}` for non-reasoning tasks to save tokens |
| L8 | `gpt-oss-120b` system role behavior differs from OpenAI | Low | System prompts will be more strictly obeyed — generally positive for agents |
| L9 | Preview models (`qwen-3-235b`, `zai-glm-4.7`) may change without notice | Medium | Pin model IDs; monitor Cerebras changelog; test after rate limit changes |
| L10 | Free tier 1M TPD is per-model, not per-account | Low | Diversify across models to maximize total daily capacity |

---

## Recommended Agent42 Provider Spec

```python
# providers/registry.py additions

class ProviderType(str, Enum):
    # ... existing entries ...
    CEREBRAS = "cerebras"

PROVIDERS[ProviderType.CEREBRAS] = ProviderSpec(
    provider_type=ProviderType.CEREBRAS,
    base_url="https://api.cerebras.ai/v1",
    api_key_env="CEREBRAS_API_KEY",
    display_name="Cerebras (World's Fastest Inference)",
    default_model="gpt-oss-120b",
    supports_function_calling=True,
)
```

## Recommended Agent42 Model Entries

```python
# providers/registry.py — FREE TIER section additions

# Cerebras direct — independent of OpenRouter, own API key
"cerebras-gpt-oss": ModelSpec(
    "gpt-oss-120b",
    ProviderType.CEREBRAS,
    max_tokens=8192,
    display_name="GPT-OSS 120B via Cerebras",
    tier=ModelTier.FREE,
    max_context_tokens=65536,   # 65k on free tier
),
"cerebras-qwen3-235b": ModelSpec(
    "qwen-3-235b-a22b-instruct-2507",
    ProviderType.CEREBRAS,
    max_tokens=8192,
    display_name="Qwen3 235B via Cerebras",
    tier=ModelTier.FREE,
    max_context_tokens=65536,   # 65k on free tier
),
"cerebras-llama-8b": ModelSpec(
    "llama3.1-8b",
    ProviderType.CEREBRAS,
    max_tokens=4096,
    display_name="Llama 3.1 8B via Cerebras",
    tier=ModelTier.FREE,
    max_context_tokens=8192,    # 8k on free tier
),
"cerebras-zai-glm47": ModelSpec(
    "zai-glm-4.7",
    ProviderType.CEREBRAS,
    max_tokens=8192,
    display_name="ZAI GLM 4.7 via Cerebras",
    tier=ModelTier.FREE,
    max_context_tokens=65536,   # 64k on free tier (rounded to power of 2)
),
```

## Recommended SpendingTracker Pricing Entries

All Cerebras free-tier models are $0. Add pricing for completeness (paid tier):

```python
# providers/registry.py — SpendingTracker._BUILTIN_PRICES additions
# Cerebras free tier = $0; these are paid tier prices (safety net if tier changes)
"gpt-oss-120b": (0.35e-6, 0.75e-6),       # $0.35/M input, $0.75/M output
"llama3.1-8b": (0.10e-6, 0.10e-6),        # $0.10/M both
"qwen-3-235b-a22b-instruct-2507": (0.60e-6, 1.20e-6),  # $0.60/M in, $1.20/M out
"zai-glm-4.7": (2.25e-6, 2.75e-6),        # $2.25/M in, $2.75/M out
```

The existing `_get_price()` free model detection does NOT cover Cerebras (it checks for `or-free-` prefix or `:free` suffix). Cerebras models will fall through to the conservative $5/$15 estimate. Add explicit $0 entries for free tier to prevent false cost tracking:

```python
# Add to _BUILTIN_PRICES with $0 for free tier models
# OR extend _get_price() to also check ProviderType.CEREBRAS
# Simplest: add a cerebras_free set and return (0.0, 0.0) for it
```

## FREE_ROUTING Recommendations

Based on rate limits and capabilities:

```python
# Primary (agent loops) — use gpt-oss-120b: fastest, 30 RPM, 65k context
# Critic — use cerebras-qwen3-235b or cerebras-zai-glm47 (but watch zai-glm47's 100 RPD)

FREE_ROUTING additions for each TaskType:
  primary:  "cerebras-gpt-oss"      # 3000 tok/s, best for iterative coding
  critic:   "cerebras-qwen3-235b"   # 1400 tok/s, 30 RPM, high quality
  # OR
  critic:   "cerebras-zai-glm47"    # ONLY if task count is low (100 RPD limit)
```

---

## Pricing Summary (for reference)

| Model | Tier | Input ($/M tok) | Output ($/M tok) |
|-------|------|-----------------|-----------------|
| `llama3.1-8b` | Free | $0 | $0 |
| `gpt-oss-120b` | Free | $0 | $0 |
| `qwen-3-235b-a22b-instruct-2507` | Free | $0 | $0 |
| `zai-glm-4.7` | Free | $0 | $0 |
| `llama3.1-8b` | Developer | $0.10 | $0.10 |
| `gpt-oss-120b` | Developer | $0.35 | $0.75 |
| `qwen-3-235b-a22b-instruct-2507` | Developer | $0.60 | $1.20 |
| `zai-glm-4.7` | Developer | $2.25 | $2.75 |

---

## Quality Gate Checklist

- [x] API base URL verified: `https://api.cerebras.ai/v1` — confirmed in official docs
- [x] Model IDs are current: verified against [models/overview](https://inference-docs.cerebras.ai/models/overview) and individual model pages (2026-03-01); deprecated IDs (`qwen-3-32b`, `llama-3.3-70b`) documented
- [x] Free tier limits documented: 1M TPD, 30 RPM (10 for zai-glm-4.7), 14,400 RPD (100 for zai-glm-4.7)
- [x] Function calling support confirmed: all 4 active models support `tools=`, `parallel_tool_calls`, strict mode
- [x] Error handling patterns documented: full HTTP status code table, SDK exception hierarchy, retry recommendations

---

## Sources

- [Cerebras OpenAI Compatibility](https://inference-docs.cerebras.ai/resources/openai) — HIGH confidence
- [Cerebras Rate Limits](https://inference-docs.cerebras.ai/support/rate-limits) — HIGH confidence
- [Cerebras Pricing](https://www.cerebras.ai/pricing) — HIGH confidence
- [Models Overview](https://inference-docs.cerebras.ai/models/overview) — HIGH confidence
- [GPT-OSS 120B model page](https://inference-docs.cerebras.ai/models/openai-oss) — HIGH confidence
- [Qwen 3 235B model page](https://inference-docs.cerebras.ai/models/qwen-3-235b-2507) — HIGH confidence
- [Llama 3.1 8B model page](https://inference-docs.cerebras.ai/models/llama-31-8b) — HIGH confidence
- [ZAI GLM 4.7 model page](https://inference-docs.cerebras.ai/models/zai-glm-47) — HIGH confidence
- [Tool Calling docs](https://inference-docs.cerebras.ai/capabilities/tool-use) — HIGH confidence
- [Error Codes](https://inference-docs.cerebras.ai/support/error) — HIGH confidence
- [Cerebras Python SDK README](https://github.com/Cerebras/cerebras-cloud-sdk-python/blob/main/README.md) — HIGH confidence
