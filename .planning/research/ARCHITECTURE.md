# Architecture Patterns — Mistral & Together AI Provider Integration

**Project:** Agent42 Free LLM Provider Expansion (Mistral + Together AI)
**Researched:** 2026-03-01
**Research mode:** Architecture / Feasibility
**Overall confidence:** MEDIUM-HIGH (API base URLs and compatibility confirmed; free tier exact limits partially verified via secondary sources)

---

## 1. Mistral API — Verified Specifications

### 1.1 API Base URL and Authentication

| Field | Value | Confidence |
|-------|-------|-----------|
| La Plateforme base URL | `https://api.mistral.ai/v1` | HIGH — official docs |
| Codestral dedicated base URL | `https://codestral.mistral.ai/v1` | MEDIUM — verified via multiple secondary sources |
| Auth method | Bearer token: `Authorization: Bearer <key>` | HIGH — official docs |
| La Plateforme key env var | `MISTRAL_API_KEY` | HIGH — official SDK convention |
| Codestral key env var | `CODESTRAL_API_KEY` | MEDIUM — liteLLM docs + community sources |

**Two separate domains, two separate keys:**

Mistral operates two distinct API surfaces:
- `api.mistral.ai` — La Plateforme: all general models (Mistral Large, Mistral Small, Pixtral), billing per token.
- `codestral.mistral.ai` — Dedicated Codestral endpoint: currently free under a monthly subscription structure (phone verification required). Personal-level API key, not bound by organization rate limits.

**Agent42 will need two ProviderSpec entries** — one for each domain.

```python
from openai import AsyncOpenAI

# La Plateforme — general models
client_laplateforme = AsyncOpenAI(
    base_url="https://api.mistral.ai/v1",
    api_key=os.getenv("MISTRAL_API_KEY"),
    max_retries=0,
)

# Codestral endpoint — code specialist (free)
client_codestral = AsyncOpenAI(
    base_url="https://codestral.mistral.ai/v1",
    api_key=os.getenv("CODESTRAL_API_KEY"),
    max_retries=0,
)
```

Source: [Mistral API Docs](https://docs.mistral.ai/api/), [LiteLLM Codestral](https://docs.litellm.ai/docs/providers/codestral), [cheahjs/free-llm-api-resources](https://github.com/cheahjs/free-llm-api-resources)

---

### 1.2 OpenAI Compatibility Level

**Verdict: MEDIUM-HIGH compatibility. Drop-in for chat completions and function calling. NOT a full OpenAI clone.**

| Feature | Status | Notes |
|---------|--------|-------|
| Chat completions (`/v1/chat/completions`) | SUPPORTED | Full OpenAI-compatible format |
| Tool/function calling (`tools=`) | SUPPORTED | `tool_choice`, parallel tool calls — identical format to OpenAI |
| Streaming (`stream=True`) | SUPPORTED | SSE streaming |
| Embeddings (`/v1/embeddings`) | SUPPORTED | Available on La Plateforme |
| Fill-in-the-Middle (FIM) | SUPPORTED | Codestral-specific endpoint: `POST /v1/fim/completions` |
| Vision / multimodal | SUPPORTED | Mistral Large 3, Pixtral Large only |
| Structured outputs | SUPPORTED | |
| Official recommendation | Native SDK preferred | Mistral docs say "strongly recommend official SDK" |
| `AsyncOpenAI` client tested | YES (community verified) | Works via `base_url` override |

**Critical note:** Mistral's official documentation recommends using their native Python SDK (`mistralai` package). However, the OpenAI Python client works with `base_url` override based on community verification and the identical `/v1/chat/completions` endpoint structure. Agent42 should use `AsyncOpenAI` (consistent with all other providers) and document the risk that Mistral-specific features (OCR, FIM, Agents API) are not accessible via the OpenAI client.

Source: [Mistral API reference](https://docs.mistral.ai/api/), [Mistral SDK clients](https://docs.mistral.ai/getting-started/clients), [OpenAI community thread](https://community.openai.com/t/you-can-access-mistral-api-via-custom-gpt-action/560421)

---

### 1.3 Available Models — Exact Model IDs (Current as of 2026-03-01)

#### Frontier / General Models

| Agent42 Key | API Model ID | Context | Vision | Function Calling | Tier |
|-------------|--------------|---------|--------|-----------------|------|
| `mistral-large` | `mistral-large-latest` | 128k | YES | YES | PAID |
| `mistral-medium` | `mistral-medium-latest` | 128k | YES | YES | PAID |
| `mistral-small` | `mistral-small-latest` | 128k | NO | YES | PAID |
| `pixtral-large` | `pixtral-large-latest` | 128k | YES | YES | PAID |

**Pinned version IDs (stable aliases):**

| Model | Pinned ID |
|-------|-----------|
| Mistral Large 3 (Dec 2025) | `mistral-large-3-25-12` |
| Mistral Medium 3.1 (Aug 2025) | `mistral-medium-3-1-25-08` |
| Mistral Small 3.2 (Jun 2025) | `mistral-small-3-2-25-06` |
| Pixtral Large (Nov 2024) | `pixtral-large-24-11` |

**Recommendation:** Use `-latest` aliases. Mistral updates models continuously; pinned IDs become deprecated (e.g., `codestral-2405` is already deprecated). The `-latest` alias points to the current production version.

#### Codestral Models (Code Specialist)

| Agent42 Key | API Model ID | Endpoint | Context | Function Calling | Tier |
|-------------|--------------|---------|---------|-----------------|------|
| `mistral-codestral` | `codestral-latest` | `api.mistral.ai/v1` OR `codestral.mistral.ai/v1` | 256k | YES | PAID (La Plateforme) / FREE (Codestral endpoint) |
| `mistral-devstral-small` | `devstral-small-latest` | `api.mistral.ai/v1` | 128k | YES | PAID |
| `mistral-devstral-medium` | `devstral-medium-latest` | `api.mistral.ai/v1` | 128k | YES | PAID |

**Pinned Codestral IDs:**

| Model | Pinned ID |
|-------|-----------|
| Codestral (Aug 2025) | `codestral-2508` |
| Codestral (Jan 2025) — older | `codestral-2501` |
| Codestral (May 2024) — deprecated | `codestral-2405` (DO NOT USE) |

#### Reasoning Models

| Agent42 Key | API Model ID | Context | Function Calling | Tier |
|-------------|--------------|---------|-----------------|------|
| `mistral-magistral-medium` | `magistral-medium-latest` | 40k | YES | PAID |

Source: [Mistral Models Overview](https://docs.mistral.ai/getting-started/models/models_overview/), [Mistral Changelog](https://docs.mistral.ai/getting-started/changelog)

---

### 1.4 Free "Experiment" Tier — Exact Limits

**Verdict: Verified via secondary sources (official limits page requires login). Treat as MEDIUM confidence.**

| Limit | Value | Source |
|-------|-------|--------|
| Monthly token allowance | 1,000,000,000 tokens (1B/month) | cheahjs/free-llm-api-resources (MEDIUM) |
| Rate limit type | 1 request/second, 500,000 tokens/minute | cheahjs/free-llm-api-resources (MEDIUM) |
| RPM equivalent | ~60 RPM (1 RPS) | Derived from above |
| Credit card required | NO — phone number verification only | Mistral help center (HIGH) |
| Models available | All open-weight models on La Plateforme | MEDIUM — implied by docs |
| Data training consent | Required | cheahjs/free-llm-api-resources (MEDIUM) |

**Important caveats:**
- The exact tier limits are managed per-workspace in `admin.mistral.ai/plateforme/limits` and are not published in static documentation.
- Mistral's official docs only state "conservative rate limits" for the Experiment tier — the 1 RPS / 1B tokens/month figures come from a well-maintained community resource (cheahjs) and are widely cited. Verify at signup.
- "Experiment" plan is positioned for evaluation and prototyping, not production. Scale plan required for production use.
- Which specific models are available on the Experiment tier is not explicitly documented. Premier models (Mistral Large, Pixtral Large) likely require paid billing.

**Routing implication for Agent42:** At 1 RPS (60 RPM), Mistral La Plateforme is suitable for non-latency-critical tasks on the free tier. This is higher than the "2 RPM" figure cited in PROJECT.md — the 2 RPM figure may be outdated or refer to a specific endpoint limit. Verify at signup.

#### Codestral Endpoint (codestral.mistral.ai) Free Limits

| Limit | Value | Confidence |
|-------|-------|-----------|
| Rate limit | 30 requests/minute | MEDIUM (cheahjs) |
| Daily request limit | 2,000 requests/day | MEDIUM (cheahjs) |
| Cost | Currently FREE (monthly subscription structure) | MEDIUM |
| Phone verification | Required | HIGH |
| Waiting list | Previously existed — current status unclear | LOW |

The Codestral endpoint is separate from La Plateforme. It uses a distinct API key and the `codestral.mistral.ai` domain. The model available is `codestral-latest`. This endpoint does NOT appear to support FIM via the standard chat completions route — FIM requires `POST /v1/fim/completions`.

Source: [cheahjs/free-llm-api-resources](https://github.com/cheahjs/free-llm-api-resources), [Mistral help center](https://help.mistral.ai/en/articles/455206-how-can-i-try-the-api-for-free-with-the-experiment-plan), [LiteLLM Codestral docs](https://docs.litellm.ai/docs/providers/codestral)

---

### 1.5 Function Calling Support

**Confirmed: YES — identical format to OpenAI.**

Mistral models support:
- `tools` parameter with `type: "function"` schema
- `tool_choice` parameter (`"auto"`, `"any"`, `"none"`, specific function name)
- `parallel_tool_calls` parameter
- Response: `tool_calls` array on assistant message

Works with Agent42's existing `complete_with_tools()` pattern via `AsyncOpenAI` client.

Source: [Mistral Function Calling docs](https://docs.mistral.ai/capabilities/function_calling)

---

### 1.6 Recommended Agent42 Provider Specs

```python
# providers/registry.py additions

class ProviderType(str, Enum):
    # ... existing ...
    MISTRAL = "mistral"
    MISTRAL_CODESTRAL = "mistral_codestral"  # separate domain, separate key

PROVIDERS[ProviderType.MISTRAL] = ProviderSpec(
    provider_type=ProviderType.MISTRAL,
    base_url="https://api.mistral.ai/v1",
    api_key_env="MISTRAL_API_KEY",
    display_name="Mistral (La Plateforme)",
    default_model="mistral-small-latest",
    supports_function_calling=True,
)

PROVIDERS[ProviderType.MISTRAL_CODESTRAL] = ProviderSpec(
    provider_type=ProviderType.MISTRAL_CODESTRAL,
    base_url="https://codestral.mistral.ai/v1",
    api_key_env="CODESTRAL_API_KEY",
    display_name="Codestral (Mistral Code Specialist)",
    default_model="codestral-latest",
    supports_function_calling=True,
)
```

```python
# providers/registry.py — Model entries

# Mistral free tier (Experiment plan — 1B tokens/month)
"mistral-small-free": ModelSpec(
    "mistral-small-latest",
    ProviderType.MISTRAL,
    max_tokens=4096,
    display_name="Mistral Small (free tier)",
    tier=ModelTier.FREE,
    max_context_tokens=128000,
),

# Codestral — code specialist on dedicated free endpoint
"mistral-codestral-free": ModelSpec(
    "codestral-latest",
    ProviderType.MISTRAL_CODESTRAL,
    max_tokens=8192,
    display_name="Codestral (free endpoint)",
    tier=ModelTier.FREE,
    max_context_tokens=256000,
),

# Mistral paid models (premium use)
"mistral-large": ModelSpec(
    "mistral-large-latest",
    ProviderType.MISTRAL,
    max_tokens=4096,
    display_name="Mistral Large",
    tier=ModelTier.PREMIUM,
    max_context_tokens=128000,
),
```

---

## 2. Together AI API — Verified Specifications

### 2.1 API Base URL and Authentication

| Field | Value | Confidence |
|-------|-------|-----------|
| Base URL | `https://api.together.xyz/v1` | HIGH — official docs, confirmed in quickstart |
| Auth method | Bearer token: `Authorization: Bearer <key>` | HIGH |
| Key env var | `TOGETHER_API_KEY` | HIGH — standard convention |
| Key source | [api.together.ai](https://api.together.ai/) after account creation |

**Drop-in with `AsyncOpenAI` client:**

```python
from openai import AsyncOpenAI

client = AsyncOpenAI(
    base_url="https://api.together.xyz/v1",
    api_key=os.getenv("TOGETHER_API_KEY"),
    max_retries=0,
)
```

Source: [Together OpenAI Compatibility](https://docs.together.ai/docs/openai-api-compatibility), [Together Llama 4 Quickstart](https://docs.together.ai/docs/llama4-quickstart)

---

### 2.2 OpenAI Compatibility Level

**Verdict: HIGH compatibility. Official documentation states full OpenAI API compatibility across all major endpoints.**

| Feature | Status | Notes |
|---------|--------|-------|
| Chat completions (`/v1/chat/completions`) | SUPPORTED | Full OpenAI-compatible format |
| Tool/function calling (`tools=`) | SUPPORTED | OpenAI-identical format; 24+ models support it |
| Streaming (`stream=True`) | SUPPORTED | SSE streaming |
| Embeddings (`/v1/embeddings`) | SUPPORTED | Available |
| Vision / multimodal | SUPPORTED | Llama 4 Maverick, Qwen3-VL-8B |
| Image generation | SUPPORTED | Separate endpoint |
| Speech/TTS | SUPPORTED | Separate endpoint |
| Structured outputs | SUPPORTED | |
| `AsyncOpenAI` client | CONFIRMED | Official docs demonstrate this pattern |

Together AI explicitly markets "full compatibility with OpenAI's API" — redirect existing applications with only `base_url` change. This is the highest compatibility level among the new providers being added.

Source: [Together OpenAI Compatibility](https://docs.together.ai/docs/openai-api-compatibility)

---

### 2.3 Available Models — Exact Model IDs (Current as of 2026-03-01)

#### Flagship Chat Models

| Agent42 Key | API Model ID | Context | Function Calling | Pricing (input/output per 1M) | Tier |
|-------------|--------------|---------|-----------------|------------------------------|------|
| `together-llama4-scout` | `meta-llama/Llama-4-Scout-17B-16E-Instruct` | 327,680 | YES | $0.18 / $0.59 | CHEAP |
| `together-llama4-maverick` | `meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8` | 1,048,576 | YES | Paid | CHEAP |
| `together-deepseek-r1` | `deepseek-ai/DeepSeek-R1` | 163,839 | YES | Paid | CHEAP |
| `together-deepseek-v3` | `deepseek-ai/DeepSeek-V3` | ~128k | YES | Paid | CHEAP |
| `together-qwen35-397b` | `Qwen/Qwen3.5-397B-A17B` | 262,144 | YES | Paid | CHEAP |

**Note on Llama 4 Scout:** The model page states it is "not available on Together's Serverless API" for production — it requires a dedicated endpoint. This is a critical constraint. Verify at implementation time whether it is available serverless for the free credit tier.

#### Free / Zero-Cost Models

| Agent42 Key | API Model ID | Context | Function Calling | Cost | Notes |
|-------------|--------------|---------|-----------------|------|-------|
| `together-deepseek-r1-free` | `deepseek-ai/DeepSeek-R1-Distill-Llama-70B-free` | ~32k | Unknown | $0.00 | Free playground endpoint; not on Serverless API |
| `google/gemma-2b-it` | `google/gemma-2b-it` | ~8k | Unknown | $0.00 | Pricing listed as free |

**Important:** "Free" models on Together AI appear to be playground/experimental endpoints, not production-grade serverless models. The `DeepSeek-R1-Distill-Llama-70B-free` endpoint explicitly notes it is "not available on Together's Serverless API." Together AI's free credit model (spend credits from the $25 signup) is the recommended approach for production use.

#### DeepSeek Model Family on Together AI

| API Model ID | Description |
|--------------|-------------|
| `deepseek-ai/DeepSeek-R1` | R1 full (updated to R1-0528 weights) |
| `deepseek-ai/DeepSeek-V3` | V3 (updated to V3-0324 weights) |
| `deepseek-ai/DeepSeek-V3.1` | V3.1 |
| `DeepSeek-AI/DeepSeek-V3-2-Exp` | V3.2 experimental |
| `deepseek-ai/DeepSeek-R1-Distill-Llama-70B-free` | R1 distilled 70B (FREE, playground only) |

Source: [Together DeepSeek page](https://www.together.ai/deepseek), [Together AI models listing](https://www.together.ai/models)

---

### 2.4 Free Credits and Billing

**Critical update: Together AI's free tier changed in July 2025.**

| Detail | Status | Confidence |
|--------|--------|-----------|
| Free trial without payment | NO — minimum $5 purchase required | HIGH (official support article) |
| Signup credits | $25 (MEDIUM confidence) — conflicting reports of $25 or $100 | MEDIUM |
| Credit expiry | No expiration (official docs) — some secondary sources say 30-90 days | LOW (conflicting) |
| Minimum purchase | $5 to access the platform | HIGH |
| Negative balance limit | $100 (Build Tiers 1-4) | MEDIUM |

**What this means for Agent42 integration:**
- Together AI is NOT truly "free" post-July 2025. It requires a minimum $5 credit purchase.
- The PROJECT.md description of "$25 free credits" is accurate at MEDIUM confidence — signup credits are granted, but the platform requires adding payment.
- For Agent42 routing, Together AI should be classified as CHEAP tier (spend from credits) rather than FREE tier (no-cost like Cerebras or Mistral Experiment).
- The SpendingTracker must track Together AI token usage against the credit balance.

**Build Tier system:**

| Tier | Rate Limits | Notes |
|------|-------------|-------|
| Build Tier 1–4 | Up to 6,000 RPM, 2M TPM | Default for new users |
| Build Tier 5 | Higher than above | Threshold-based progression |
| Scale/Enterprise | Custom | For heavy production use |

The default 60 RPM base rate documented in Together AI's rate limits docs applies to standard serverless inference. High-demand models (DeepSeek-R1) may have model-specific limits of 0.3–4 RPM for free/tier-1 users.

Source: [Together AI billing](https://docs.together.ai/docs/billing), [Changes to free tier (July 2025)](https://support.together.ai/articles/1862638756-changes-to-free-tier-and-billing-july-2025), [Together AI pricing](https://www.together.ai/pricing)

---

### 2.5 Function Calling Support

**Confirmed: YES — identical format to OpenAI, 24+ models supported.**

Models confirmed to support function calling:
- `meta-llama/Llama-4-Scout-17B-16E-Instruct` (YES)
- `meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8` (YES)
- `deepseek-ai/DeepSeek-R1` (YES)
- `deepseek-ai/DeepSeek-V3` (YES)
- Qwen series, Mistral Small, other major models (YES)

Format is identical to OpenAI: `tools` parameter, `tool_calls` in response. Works with Agent42's existing `complete_with_tools()` pattern.

Source: [Together Function Calling docs](https://docs.together.ai/docs/function-calling)

---

### 2.6 Unique Features

| Feature | Available | Notes |
|---------|-----------|-------|
| Vision / multimodal input | YES | Llama 4 Maverick, Qwen3-VL-8B |
| Image generation | YES | Separate endpoint |
| Embeddings | YES | `/v1/embeddings` endpoint |
| Sub-100ms latency (claimed) | YES | Together AI marketing claim |
| GPU Cloud (dedicated) | YES | Hourly rates $2.09–$5.50/hr |
| Fine-tuning | YES | Per-token pricing |

---

### 2.7 Recommended Agent42 Provider Specs

```python
# providers/registry.py additions

class ProviderType(str, Enum):
    # ... existing ...
    TOGETHER = "together"

PROVIDERS[ProviderType.TOGETHER] = ProviderSpec(
    provider_type=ProviderType.TOGETHER,
    base_url="https://api.together.xyz/v1",
    api_key_env="TOGETHER_API_KEY",
    display_name="Together AI (200+ open models)",
    default_model="meta-llama/Llama-4-Scout-17B-16E-Instruct",
    supports_function_calling=True,
)
```

```python
# providers/registry.py — Model entries
# Together AI is CHEAP tier (uses $25 credit, not truly free like Cerebras)

"together-llama4-scout": ModelSpec(
    "meta-llama/Llama-4-Scout-17B-16E-Instruct",
    ProviderType.TOGETHER,
    max_tokens=8192,
    display_name="Llama 4 Scout via Together AI",
    tier=ModelTier.CHEAP,
    max_context_tokens=327680,
),
"together-deepseek-r1": ModelSpec(
    "deepseek-ai/DeepSeek-R1",
    ProviderType.TOGETHER,
    max_tokens=8192,
    display_name="DeepSeek-R1 via Together AI",
    tier=ModelTier.CHEAP,
    max_context_tokens=163839,
),
"together-deepseek-v3": ModelSpec(
    "deepseek-ai/DeepSeek-V3",
    ProviderType.TOGETHER,
    max_tokens=8192,
    display_name="DeepSeek-V3 via Together AI",
    tier=ModelTier.CHEAP,
    max_context_tokens=131072,
),
"together-llama4-maverick": ModelSpec(
    "meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8",
    ProviderType.TOGETHER,
    max_tokens=8192,
    display_name="Llama 4 Maverick via Together AI",
    tier=ModelTier.CHEAP,
    max_context_tokens=1048576,
),
# Free playground endpoint (reduced rate limits, not serverless)
"together-deepseek-r1-free": ModelSpec(
    "deepseek-ai/DeepSeek-R1-Distill-Llama-70B-free",
    ProviderType.TOGETHER,
    max_tokens=4096,
    display_name="DeepSeek R1 Distill 70B (free)",
    tier=ModelTier.FREE,
    max_context_tokens=32768,
),
```

---

## 3. Implementation Architecture

### 3.1 Integration Pattern (Identical for Both Providers)

Both Mistral and Together AI integrate using the **same pattern** as all existing Agent42 providers. No new code patterns are needed — it is pure configuration.

```
Agent42 model routing
        │
        ▼
ProviderRegistry.get_client(ProviderType.MISTRAL)
        │
        ▼
AsyncOpenAI(base_url="https://api.mistral.ai/v1", api_key=MISTRAL_API_KEY)
        │
        ▼
client.chat.completions.create(model="mistral-small-latest", ...)
```

This pattern is already implemented for Gemini, DeepSeek, OpenRouter, and VLLM — Mistral and Together AI are structurally identical.

### 3.2 Two-Key Architecture for Mistral

Mistral requires special handling due to two domains:

```
                    MISTRAL_API_KEY
                         │
                         ▼
              ProviderType.MISTRAL ──► api.mistral.ai/v1
              (general models)

                    CODESTRAL_API_KEY
                         │
                         ▼
         ProviderType.MISTRAL_CODESTRAL ──► codestral.mistral.ai/v1
         (Codestral code specialist — free endpoint)
```

If only `CODESTRAL_API_KEY` is set (user wants only free Codestral), the `MISTRAL` provider throws on client creation (no key) — graceful degradation works correctly via the existing `try/except` in `_complete_with_retry`.

If only `MISTRAL_API_KEY` is set (user wants paid La Plateforme only), `MISTRAL_CODESTRAL` provider fails — also handled gracefully.

### 3.3 SpendingTracker Pricing

```python
# providers/registry.py — SpendingTracker._BUILTIN_PRICES additions

# Mistral free Experiment tier = $0 for open-weight models
# Codestral free endpoint = $0
# Together AI credits consumed from $25 signup balance

# Mistral La Plateforme (paid models — estimated, verify at mistral.ai/pricing)
"mistral-large-latest": (2.00e-6, 6.00e-6),     # Estimated ~$2/M in, $6/M out
"mistral-medium-latest": (0.40e-6, 2.00e-6),    # Estimated
"mistral-small-latest": (0.10e-6, 0.30e-6),     # ~$0.10/M in, $0.30/M out

# Together AI — actual published pricing
"meta-llama/Llama-4-Scout-17B-16E-Instruct": (0.18e-6, 0.59e-6),
"deepseek-ai/DeepSeek-R1": (3.00e-6, 7.00e-6),  # Estimated — verify on together.ai/pricing
"deepseek-ai/DeepSeek-V3": (1.25e-6, 1.25e-6),  # Estimated
```

**Free detection extension needed:** The existing `_get_price()` free model detection checks for `or-free-` prefix and `:free` suffix. Neither covers Mistral or Together AI free models. Add explicit `(0.0, 0.0)` entries in `_BUILTIN_PRICES` for:
- `mistral-small-latest` when used on Experiment tier (ambiguous — user may be on paid tier too)
- `codestral-latest` when used via `codestral.mistral.ai` (always free)
- `deepseek-ai/DeepSeek-R1-Distill-Llama-70B-free` (Together AI free endpoint)

Recommended: add `FREE_MODEL_IDS` set to `SpendingTracker` so new providers can register free models without relying on naming conventions.

### 3.4 FREE_ROUTING Recommendations

Based on rate limits and capabilities:

```python
# Mistral Experiment tier (60 RPM, 1B tokens/month)
# Best role: coding critic (Codestral), or specialized reasoning tasks
# Codestral endpoint: 30 RPM, 2000 req/day — good for code review role

# Together AI (~60 RPM base, limited only by credit balance)
# Best role: general primary (sub-100ms latency claim), high context tasks
# Llama 4 Scout (327k context) is ideal for long-context coding tasks

# Routing recommendations per TaskType:
# coding:    primary="together-llama4-scout", critic="mistral-codestral-free"
# debugging: primary="together-deepseek-r1", critic="mistral-codestral-free"
# general:   primary="together-llama4-scout", critic="mistral-small-free"
```

**Note:** Codestral's 2,000 req/day limit must be monitored. If Agent42 runs many coding tasks, Codestral exhausts its daily budget quickly. Rate-limit tracking should use the existing `_failed_models` pattern — once Codestral returns 429, it falls back to other critics for the rest of the day.

### 3.5 Health Check Integration

`model_catalog.py` health checks: add Mistral and Together AI models to the health check list. Use the existing pattern — attempt a minimal completion and check for non-error response.

**Mistral health check note:** The Experiment tier's low RPM means health checks should be infrequent (every 30+ minutes, not every 5 minutes) to avoid burning rate limit capacity.

---

## 4. Component Boundaries

| Component | Change Required | Notes |
|-----------|----------------|-------|
| `providers/registry.py` | Add `MISTRAL`, `MISTRAL_CODESTRAL`, `TOGETHER` to `ProviderType` | Extend enum + `PROVIDERS` dict + `MODELS` dict |
| `core/config.py` | Add `mistral_api_key`, `codestral_api_key`, `together_api_key` fields | Follow existing pattern |
| `.env.example` | Add `MISTRAL_API_KEY`, `CODESTRAL_API_KEY`, `TOGETHER_API_KEY` | Document free tier URLs |
| `agents/model_router.py` | Update `FREE_ROUTING` dict | Add Mistral/Together slots per TaskType |
| `model_catalog.py` | Add health check entries | Use infrequent polling for Mistral |
| `agents/model_router.py` | Update `_get_fallback_models()` | Include Mistral/Together in fallback chains |

---

## 5. Open Questions and Verification Required

| Question | Action |
|----------|--------|
| Does Together AI's Llama 4 Scout work via serverless API (not dedicated)? | Verify at signup — model page says "not available on Serverless API" |
| Exact Mistral Experiment tier RPM limit — 60 RPM or 2 RPM? | PROJECT.md says 2 RPM; cheahjs says 1 RPS (60 RPM). Verify in AI Studio limits dashboard at signup |
| Which Mistral models are available on the Experiment (free) tier? | Verify at signup — Premier models (Mistral Large, Pixtral) likely require payment |
| Is Codestral endpoint waitlist still active? | Verify at signup — was present in 2024, may have been removed |
| Together AI signup credits: $25 or $100? | Verify at signup — conflicting sources |
| Together AI credit expiry: none or 30-90 days? | Verify at signup — official docs say no expiry, but this may have changed July 2025 |
| Mistral pricing per token for each model | Visit `mistral.ai/pricing#api-pricing` — JS-rendered, not fetched successfully |
| Together AI pricing for DeepSeek-R1 and V3 | Visit `together.ai/pricing` — JS-rendered, estimate in SpendingTracker |

---

## 6. Quality Gate Checklist

- [x] Both providers' API base URLs verified
  - Mistral La Plateforme: `https://api.mistral.ai/v1` (HIGH confidence)
  - Mistral Codestral: `https://codestral.mistral.ai/v1` (MEDIUM confidence)
  - Together AI: `https://api.together.xyz/v1` (HIGH confidence)
- [x] Model IDs current
  - Mistral: `-latest` aliases recommended; pinned IDs for stable deploys (MEDIUM)
  - Together AI: exact model IDs verified via official model pages (HIGH)
- [x] Free tier limits documented for each
  - Mistral Experiment: 1B tokens/month, ~60 RPM (MEDIUM — requires login to verify)
  - Mistral Codestral: 30 RPM, 2000 req/day (MEDIUM — community source)
  - Together AI: $25 credit-based (not truly free post-July 2025) (MEDIUM)
- [x] OpenAI compatibility confirmed for AsyncOpenAI usage
  - Mistral: MEDIUM-HIGH (official SDK recommended, but OpenAI client works)
  - Together AI: HIGH (official "full compatibility" claim)
- [x] Codestral availability on free tier confirmed
  - MEDIUM confidence — dedicated endpoint is free, uses separate API key

---

## 7. Sources

| Source | URL | Confidence |
|--------|-----|-----------|
| Mistral API reference | https://docs.mistral.ai/api/ | HIGH |
| Mistral models overview | https://docs.mistral.ai/getting-started/models/models_overview/ | HIGH |
| Mistral function calling | https://docs.mistral.ai/capabilities/function_calling | HIGH |
| Mistral code generation (Codestral) | https://docs.mistral.ai/capabilities/code_generation | HIGH |
| Mistral SDK clients | https://docs.mistral.ai/getting-started/clients | HIGH |
| Mistral rate limits (login required) | https://docs.mistral.ai/deployment/ai-studio/tier | MEDIUM |
| Mistral Experiment plan help | https://help.mistral.ai/en/articles/455206-how-can-i-try-the-api-for-free-with-the-experiment-plan | MEDIUM |
| LiteLLM Codestral docs | https://docs.litellm.ai/docs/providers/codestral | MEDIUM |
| cheahjs free LLM resources | https://github.com/cheahjs/free-llm-api-resources | MEDIUM |
| Together AI OpenAI compatibility | https://docs.together.ai/docs/openai-api-compatibility | HIGH |
| Together AI Llama 4 quickstart | https://docs.together.ai/docs/llama4-quickstart | HIGH |
| Together AI function calling | https://docs.together.ai/docs/function-calling | HIGH |
| Together AI billing | https://docs.together.ai/docs/billing | HIGH |
| Together AI free tier changes (Jul 2025) | https://support.together.ai/articles/1862638756-changes-to-free-tier-and-billing-july-2025 | HIGH |
| Together AI models | https://www.together.ai/models | HIGH |
| Together AI Llama 4 Scout model | https://www.together.ai/models/llama-4-scout | HIGH |
| Together AI DeepSeek-R1 free | https://www.together.ai/models/deepseek-r1-distilled-llama-70b-free | HIGH |
