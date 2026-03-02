# Feature Landscape: SambaNova Cloud API Integration

**Domain:** Free LLM provider integration — SambaNova Cloud inference API
**Researched:** 2026-03-01
**Research Mode:** Ecosystem / Features dimension

---

## CRITICAL ALERT: Model IDs in PROJECT.md Are Outdated

The PROJECT.md references "Llama 3.1 405B" and "Qwen 2.5 72B" as SambaNova's target models.
**Neither model appears in SambaNova's current supported-models documentation.**

SambaNova has migrated to newer model families. The integration must use the models actually
available today, not the ones from the PROJECT.md notes (which appear to be ~6 months stale).

See "Current Model Roster" section below for exact model IDs to use.

---

## API Connection Details

### Base URL and Authentication

| Property | Value | Confidence |
|----------|-------|------------|
| API base URL | `https://api.sambanova.ai/v1` | HIGH — confirmed via official SDK blog and docs |
| Auth method | Bearer token (API key) in `Authorization` header | HIGH — standard OpenAI client pattern |
| API key source | `cloud.sambanova.ai/apis` — "Create API Key" in dashboard | HIGH — confirmed via official UI |
| Env var convention | `SAMBANOVA_API_KEY` | HIGH — per LiteLLM integration docs |
| Client pattern | `AsyncOpenAI(base_url="https://api.sambanova.ai/v1", api_key=os.getenv("SAMBANOVA_API_KEY"))` | HIGH — confirmed via official SDK docs |
| Endpoint | `/v1/chat/completions` (standard OpenAI path) | HIGH |

### OpenAI Compatibility Level

SambaNova's API is explicitly designed as an OpenAI-compatible drop-in replacement.
The AsyncOpenAI client pattern used for all other Agent42 providers works without modification.

**Supported (confirmed HIGH confidence):**
- Chat completions (streaming and non-streaming)
- Async completions
- Function calling / tool use (`tools`, `tool_choice` parameters)
- Vision (multimodal — on Llama-4-Maverick model only)
- Embeddings (`E5-Mistral-7B-Instruct`)
- Audio transcription (`Whisper-Large-v3`)
- `top_k` parameter (SambaNova extension, not in OpenAI standard)

**NOT supported — will be silently ignored:**
- `logprobs` / `top_logprobs`
- `n` (multiple completions)
- `presence_penalty`
- `frequency_penalty`
- `logit_bias`
- `seed`
- Function calling `strict: true` (only `strict: false` works)

**Parameter difference:**
- OpenAI supports `temperature` 0–2; SambaNova supports 0–1 only. Values > 1 will likely be clamped or error.

---

## Current Model Roster

These are the models actually available as of March 2026, per official SambaNova docs.
(Sources: `docs.sambanova.ai/docs/en/models/sambacloud-models` and rate limits page)

### Production Models (stable, suitable for integration)

| Model ID (exact API value) | Context | Function Calling | Notes |
|---------------------------|---------|-----------------|-------|
| `Meta-Llama-3.3-70B-Instruct` | 128k | YES | Best free-tier general model; replaces Llama 3.1 70B |
| `Meta-Llama-3.1-8B-Instruct` | 16k | YES (unreliable for conv+tools) | High RPM; good for fast non-agentic tasks |
| `DeepSeek-V3.1` | 128k | YES | Strong coding; production-grade |
| `DeepSeek-V3-0324` | 128k | YES | Versioned DeepSeek V3; function calling confirmed |
| `DeepSeek-R1` | 128k | No (reasoning model) | Use for critic/analysis only, not tool use |
| `DeepSeek-R1-Distill-Llama-70B` | 128k | No (reasoning model) | Reasoning distillation; no function calling |

### Preview Models (experimental, NOT for production routing)

| Model ID (exact API value) | Context | Function Calling | Notes |
|---------------------------|---------|-----------------|-------|
| `Llama-4-Maverick-17B-128E-Instruct` | 128k | YES | Multimodal (up to 5 images, ≤20MB each); preview only |
| `gpt-oss-120b` | 128k | YES | Best function calling; set `reasoning_effort: "high"` |
| `Qwen3-235B-A22B-Instruct-2507` | 64k | NO (not listed) | Largest available; preview only; no function calling confirmed |
| `Qwen3-32B` | 8k | YES | Preview only; low RPM; small context |
| `Whisper-Large-v3` | N/A (audio) | N/A | Audio transcription only; 25MB max |
| `E5-Mistral-7B-Instruct` | 4k | N/A | Embeddings only |
| `Llama-3.3-Swallow-70B-Instruct-v0.4` | 16k | NO | Japanese-specialized; skip |

### Deprecated / Removed Models (DO NOT USE)

These were in PROJECT.md's notes but are no longer in current documentation:

| Model (from PROJECT.md) | Status | Replacement |
|------------------------|--------|------------|
| `Meta-Llama-3.1-405B-Instruct` | REMOVED — not in current docs; was deprecated mid-2025 | `Meta-Llama-3.3-70B-Instruct` (production), `gpt-oss-120b` (preview) |
| `Qwen2.5-72B-Instruct` | REMOVED — not in current docs | `Qwen3-235B-A22B-Instruct-2507` (preview, lower RPM) |

**Confidence:** MEDIUM — the official model list from `docs.sambanova.ai/docs/en/models/sambacloud-models`
does not include these models. No explicit deprecation notice was found for these specific IDs,
but their absence from the current docs strongly indicates they are gone. Verify at signup time.

---

## Free Tier vs Trial Credits: Critical Distinction

This is the most important thing to understand for Agent42 routing decisions.

### The Current Situation (as of February 2025 — Developer Tier launch)

SambaNova **replaced its free tier** with a Developer Tier (pay-as-you-go). The old
"free with no payment method" model is gone. What exists now:

| Aspect | Detail | Confidence |
|--------|--------|------------|
| Trial credits | $5 per new account | HIGH |
| Credit expiry | 90 days (3 months) from account creation | HIGH |
| Credit trigger | Credits used first; paid usage begins when $5 exhausted OR after 90 days | HIGH |
| Payment required? | Payment method must be added for continued use after credit exhaustion | HIGH |
| "Free tier" limits | A no-payment-method state still exists with 200K TPD cap | MEDIUM — docs show "Free Tier" limits alongside "Developer Tier" limits |

### What "Free Tier" Limits Actually Mean

The docs still show a "Free Tier" with 200K TPD and lower RPM limits. Based on community
discussion, this appears to be the state for accounts without a linked payment method.
The $5 credit is consumed first; once exhausted, if no payment method, the user is rate-limited
to "Free Tier" caps (very low RPM/RPD).

**For Agent42 routing:** SambaNova cannot be treated as a "zero cost" provider equivalent
to Cerebras or Groq free tiers. The $5 credit will be exhausted quickly in production use.
Users should add a payment method and manage spending via the spending tracker.

---

## Rate Limits

### Free Tier (no payment method linked, or credit exhausted without card)

| Model ID | RPM | RPD | TPD |
|----------|-----|-----|-----|
| `Meta-Llama-3.3-70B-Instruct` | 40 | 40 | 200,000 |
| `Meta-Llama-3.1-8B-Instruct` | 40 | 40 | 200,000 |
| `DeepSeek-R1` | 20 | 40 | 200,000 |
| `DeepSeek-R1-Distill-Llama-70B` | 40 | 40 | 200,000 |
| `DeepSeek-V3-0324` | 20 | 40 | 200,000 |
| `DeepSeek-V3.1` | 20 | 40 | 200,000 |
| `Qwen3-235B-A22B-Instruct-2507` | 20 | 20 | 200,000 |
| `Qwen3-32B` | 10 | 40 | 200,000 |
| `Llama-4-Maverick-17B-128E-Instruct` | 20 | 40 | 200,000 |
| `gpt-oss-120b` | 20 | 40 | 200,000 |

**Confidence:** HIGH — from official rate limits documentation page

**Key observation:** 40 RPD is extremely low. At 40 requests/day, a single active agentic task
(which may make 10-20 tool calls, each spawning an LLM call) will exhaust the daily limit in
2-4 tasks. Free tier SambaNova is suitable for experimentation, not production agentic workloads.

### Developer Tier (payment method linked, using credits or paid)

| Model ID | RPM | RPD |
|----------|-----|-----|
| `Meta-Llama-3.3-70B-Instruct` | 240 | 48,000 |
| `Meta-Llama-3.1-8B-Instruct` | 1,440 | 288,000 |
| `DeepSeek-V3-0324` | 60 | 12,000 |
| `DeepSeek-V3.1` | 60 | 12,000 |
| `DeepSeek-R1` | 60 | 12,000 |
| `DeepSeek-R1-Distill-Llama-70B` | 240 | 48,000 |
| `Qwen3-235B-A22B-Instruct-2507` | 30 | 6,000 |
| `Qwen3-32B` | 30 | 6,000 |
| `Llama-4-Maverick-17B-128E-Instruct` | 60 | 12,000 |
| `gpt-oss-120b` | 60 | 12,000 |

**Note:** No TPM (tokens per minute) limit documented — only TPD applies to free tier.
Developer tier has no published TPD cap (subject to spend limit).

**Confidence:** HIGH — from official rate limits documentation page

---

## Rate Limit Headers

Response headers for monitoring rate limit state (confirmed HIGH confidence):

| Header | Meaning |
|--------|---------|
| `x-ratelimit-limit-requests` | Max RPM |
| `x-ratelimit-remaining-requests` | Remaining requests this minute |
| `x-ratelimit-reset-requests` | Seconds until RPM window resets |
| `x-ratelimit-limit-requests-day` | Max RPD |
| `x-ratelimit-remaining-requests-day` | Remaining requests today |
| `x-ratelimit-reset-requests-day` | Seconds until RPD window resets |

**No `Retry-After` header documented** — use `x-ratelimit-reset-requests` to determine
backoff duration after a 429 response.

---

## Error Codes

| HTTP Code | Meaning | Agent42 Handling |
|-----------|---------|-----------------|
| 401 | Auth failure (bad/missing API key) | `_is_auth_error()` — skip retries, skip model |
| 429 | Rate limit exceeded (RPM or RPD) | Standard retry with backoff; check `x-ratelimit-reset-requests` |
| 503 / model unavailable | Model temporarily down | Add to `_failed_models`; fall back |
| Other 4xx/5xx | Request or server error | Standard retry behavior |

**Confidence:** MEDIUM — error code format confirmed (JSON with error code + message);
specific 401/429/503 behavior inferred from OpenAI compatibility pattern and community reports.

---

## Function Calling: Confirmed Support Details

Function calling is supported and confirmed via official docs. Format is OpenAI-compatible.

### Models That Support Function Calling

- `Meta-Llama-3.1-8B-Instruct` — works for zero-shot only; **unreliable** for conversation + tools
- `Meta-Llama-3.3-70B-Instruct` — **recommended** production function calling model
- `DeepSeek-V3-0324` — confirmed function calling support
- `DeepSeek-V3.1` — confirmed function calling support
- `Llama-4-Maverick-17B-128E-Instruct` — confirmed (preview)
- `Qwen3-32B` — confirmed (preview)
- `gpt-oss-120b` — confirmed; best quality with `reasoning_effort: "high"` (preview)

### Models That Do NOT Support Function Calling

- `DeepSeek-R1` — reasoning model; no tool use
- `DeepSeek-R1-Distill-Llama-70B` — reasoning model; no tool use
- `Qwen3-235B-A22B-Instruct-2507` — not listed in function calling docs
- `Whisper-Large-v3` — audio only
- `E5-Mistral-7B-Instruct` — embeddings only

### Tool Choice Options

Standard OpenAI options work:
- `tool_choice: "auto"` (default)
- `tool_choice: "required"`
- `tool_choice: {"type": "function", "function": {"name": "..."}}`

### Known Limitation

`strict: true` in tool definitions is NOT supported. Only `strict: false`.
This means the model may not always produce valid JSON for function arguments.
Agent42 should validate tool call outputs defensively.

**Confidence:** HIGH — confirmed via official function calling documentation page.

---

## Recommended Models for Agent42 Integration

Based on research findings, these are the models to register in `MODELS` dict:

### For FREE_ROUTING integration

| Role | Model ID | Rationale |
|------|----------|-----------|
| Primary (coding/agentic) | `Meta-Llama-3.3-70B-Instruct` | Production model, 128k context, function calling, 40 RPM (free) / 240 RPM (dev) |
| Critic | `DeepSeek-V3.1` | 128k context, function calling, different architecture from primary |
| Fast/lightweight | `Meta-Llama-3.1-8B-Instruct` | 40 RPM, good for simple tasks; 16k context limit |

### Do NOT use in production routing

| Model | Reason |
|-------|--------|
| `Qwen3-235B-A22B-Instruct-2507` | Preview only, 20 RPD free tier, no confirmed function calling |
| `gpt-oss-120b` | Preview only — "may be removed at short notice" |
| `Llama-4-Maverick-17B-128E-Instruct` | Preview only — "may be removed at short notice" |
| Any Llama 3.1 405B model | Not in current docs — likely deprecated |

---

## Table Stakes (Must Build)

Features required for a working SambaNova integration in Agent42.

| Feature | Why Required | Complexity | Notes |
|---------|-------------|-----------|-------|
| `ProviderType.SAMBANOVA` enum value | All providers need enum entry | Low | In `providers/registry.py` |
| `ProviderSpec` for SambaNova | Defines base URL, API key env var, client config | Low | `base_url="https://api.sambanova.ai/v1"`, `api_key_env="SAMBANOVA_API_KEY"` |
| `ModelSpec` entries for 3 production models | Route to correct models | Low | Llama 3.3 70B, Llama 3.1 8B, DeepSeek V3.1 |
| Temperature clamping to 0–1 | SambaNova rejects > 1; OpenAI allows up to 2 | Low | Guard in `_build_client()` or request params |
| `SAMBANOVA_API_KEY` in `.env.example` | User onboarding | Low | With comment explaining Developer Tier |
| Health check model | Verify key + connectivity | Low | Use `Meta-Llama-3.1-8B-Instruct` (highest RPM) |
| `_is_auth_error()` coverage | Skip retries on 401 | Low | Already exists in Agent42 codebase |
| Spending tracker entry | Track SambaNova token costs | Low | Free models = $0; dev tier has pricing |
| 429 + `x-ratelimit-reset-requests` backoff | Respect rate limits | Medium | Use header value for backoff duration |
| `strict: false` enforcement in tool definitions | Prevent API errors | Low | Strip `strict: true` before sending |

## Differentiators (Nice to Have)

| Feature | Value | Complexity | Notes |
|---------|-------|-----------|-------|
| DeepSeek-R1 as reasoning critic | High-quality analysis without tool use | Low | Register as separate model for critic-only roles |
| `reasoning_effort` param support | Exposes gpt-oss-120b quality mode | Low | SambaNova extension; pass through if set in ModelSpec |
| Embeddings via E5-Mistral | Provider-diverse embeddings | Medium | Only 4k context; limited utility |

## Anti-Features (Do NOT Build)

| Anti-Feature | Why Avoid | Instead |
|-------------|-----------|---------|
| Route preview models as production primaries | "May be removed at short notice" — causes Pitfall #56 pattern | Mark preview models with `is_preview=True` flag; exclude from primary routing |
| Treat SambaNova as cost-free equivalent to Cerebras | $5 credit expires in 90 days; after that, costs money | Document in `.env.example` that this is a paid tier with starter credits |
| Use Llama 3.1 8B for agentic tool calling | Unreliable for conversation + tools | Use 70B for any task requiring function calling |
| Set `temperature > 1.0` | SambaNova range is 0–1, not 0–2 like OpenAI | Clamp to 1.0 maximum |
| Register deprecated 405B/Qwen 2.5 72B model IDs | Will cause 404s; Pitfall #56 pattern | Use current IDs listed above |

---

## Feature Dependencies

```
SAMBANOVA_API_KEY in .env.example
    → ProviderSpec (base_url, api_key_env)
        → ProviderType.SAMBANOVA enum
            → ModelSpec for each model
                → FREE_ROUTING entries for SAMBANOVA models
                    → Health check for SAMBANOVA
                        → SpendingTracker pricing for SAMBANOVA
```

Temperature clamping → must be applied before any SambaNova request
`strict: false` enforcement → must be applied in tool schema construction

---

## MVP Recommendation

Prioritize (minimum viable SambaNova integration):
1. `ProviderSpec` + `ProviderType.SAMBANOVA` — foundation
2. `ModelSpec` for `Meta-Llama-3.3-70B-Instruct` — primary workhorse
3. `ModelSpec` for `Meta-Llama-3.1-8B-Instruct` — high-RPM health check model
4. Temperature clamping to 0–1
5. `strict: false` enforcement in tool definitions
6. `SAMBANOVA_API_KEY` in `.env.example` with Developer Tier documentation

Defer:
- DeepSeek-R1 as reasoning critic — useful but adds complexity; do in second pass
- Embeddings via E5-Mistral — low value (4k context); skip for now
- Preview model registration — too unstable for v1 integration

---

## Pricing (Developer Tier, for SpendingTracker)

Pricing from eesel.ai blog (MEDIUM confidence — verify against official pricing page):

| Model ID | Input ($/1M tokens) | Output ($/1M tokens) |
|----------|--------------------|--------------------|
| `DeepSeek-R1-0528` | $5.00 | $7.00 |
| `DeepSeek-V3.1` | $3.00 | $4.50 |
| `Meta-Llama-3.3-70B-Instruct` | $0.60 | $1.20 |
| `Meta-Llama-3.1-8B-Instruct` | $0.10 | $0.20 |
| `Qwen3-32B` | $0.40 | $0.80 |
| `gpt-oss-120b` | $0.22 | $0.59 |

**Note:** Verify against `cloud.sambanova.ai/plans` at implementation time. SpendingTracker
must use actual pricing; the $5 credit means early usage appears "free" but is consumed.

---

## Quality Gate Checklist

- [x] API base URL verified: `https://api.sambanova.ai/v1` (HIGH confidence, multiple sources)
- [x] Model IDs verified against current docs (not from training data — Llama 405B ABSENT)
- [x] Free tier vs trial credits clearly distinguished ($5 credit, 90 days, then paid)
- [x] Function calling support confirmed for Llama 3.3 70B, DeepSeek V3.1
- [x] Rate limits documented with confidence levels (HIGH — from official rate limits page)
- [x] Temperature parameter difference documented (0–1 not 0–2)
- [x] Rate limit headers documented
- [x] Unsupported OpenAI parameters listed

---

## Sources

| Source | Confidence | URL |
|--------|-----------|-----|
| SambaNova official supported models | HIGH | https://docs.sambanova.ai/docs/en/models/sambacloud-models |
| SambaNova rate limits (official docs) | HIGH | https://docs.sambanova.ai/docs/en/models/rate-limits |
| SambaNova function calling docs | HIGH | https://docs.sambanova.ai/docs/en/features/function-calling |
| SambaNova OpenAI compatibility guide | HIGH | https://docs.sambanova.ai/docs/en/features/openai-compatibility |
| SambaNova SDK blog (base URL, auth) | HIGH | https://sambanova.ai/blog/introducing-the-sambanova-sdk |
| Developer Tier announcement | HIGH | https://sambanova.ai/blog/sambanova-cloud-developer-tier-is-live |
| Function calling community article | MEDIUM | https://community.sambanova.ai/t/function-calling-and-json-mode-in-sambanova-cloud/540 |
| API rate limit community thread | MEDIUM | https://community.sambanova.ai/t/rate-limits/321 |
| SambaNova cloud API page (base URL, keys) | MEDIUM | https://cloud.sambanova.ai/apis |
| LiteLLM SambaNova integration | MEDIUM | https://docs.litellm.ai/docs/providers/sambanova |
| Pricing data (third-party) | MEDIUM | https://www.eesel.ai/blog/sambanova-cloud-pricing |
| Free tier deprecation thread | MEDIUM | https://community.sambanova.ai/t/is-free-tier-going-away/847 |
