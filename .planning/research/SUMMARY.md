# Project Research Summary

**Project:** Agent42 Free LLM Provider Expansion (Cerebras, SambaNova, Mistral, Together AI)
**Domain:** Multi-provider free/cheap LLM inference integration into an existing OpenAI-compatible agent platform
**Researched:** 2026-03-01
**Confidence:** HIGH (Cerebras, core architecture), MEDIUM-HIGH (Mistral, Together AI), MEDIUM (SambaNova free-tier caveats)

---

## Executive Summary

This project adds four new LLM inference providers to Agent42's existing routing system: Cerebras (genuinely free, fastest inference at ~3,000 tok/s), SambaNova (credits-based, not permanently free), Mistral (free Experiment tier with a severe 2 RPM ceiling plus a separate free Codestral code endpoint), and Together AI (requires minimum $5 funded account as of July 2025). All four providers use an OpenAI-compatible API that works with Agent42's existing `AsyncOpenAI(base_url=..., api_key=...)` client pattern — no new SDKs or client code is needed. The integration is primarily a data configuration exercise: add `ProviderType` enum values, `ProviderSpec` entries, `ModelSpec` records, `FREE_ROUTING` assignments, and `.env.example` documentation.

The recommended approach is to treat providers by their sustainable throughput tier rather than their advertised "free" label. Cerebras is the only genuinely zero-cost, high-throughput provider (30 RPM, 1M TPD, $0) and should be the primary addition to `FREE_ROUTING`. Mistral's Codestral endpoint is a strong free code-review critic (30 RPM, 2,000 req/day) but must never occupy a primary slot due to its 2 RPM general-tier cap. SambaNova and Together AI are "credits-based" providers that require funded accounts; they should be classified as `ModelTier.CHEAP` in routing, not `ModelTier.FREE`, and documented accordingly. The PROJECT.md descriptions of both as "free" are outdated and will mislead users if not corrected before shipping.

The critical pre-shipment risk is `SpendingTracker` misclassification: Agent42's free-model detection relies on `or-free-` prefix or `:free` suffix naming conventions that none of these four providers follow. Without explicit `(0.0, 0.0)` pricing entries in `_BUILTIN_PRICES`, every call to a Cerebras or Mistral free model will be logged at the conservative $5/$15 per-million-token fallback rate, potentially triggering the daily spend cap mid-day and blocking all agent tasks. This fix is required on Day 1 of each provider's integration, not as a follow-up.

---

## Key Findings

### Recommended Stack

All four providers drop into Agent42's existing provider architecture without new dependencies. The pattern is identical to the existing Gemini, DeepSeek, and OpenRouter integrations: a `ProviderSpec` with `base_url` and `api_key_env`, `ModelSpec` entries with `tier=ModelTier.FREE` or `ModelTier.CHEAP`, and additions to `FREE_ROUTING` and `_get_fallback_models()`. For complete details see `.planning/research/STACK.md`.

**Core provider specifications:**
- **Cerebras** — `https://api.cerebras.ai/v1`, key: `CEREBRAS_API_KEY`. Primary model: `gpt-oss-120b` (3,000 tok/s, 65k context free, 30 RPM). Full tool calling. Zero cost on free tier. Best primary/fallback model of the four.
- **SambaNova** — `https://api.sambanova.ai/v1`, key: `SAMBANOVA_API_KEY`. Primary model: `Meta-Llama-3.3-70B-Instruct` (128k context, 40 RPM paid). $5 trial credits expire in 30 days; not a permanently free provider.
- **Mistral (La Plateforme)** — `https://api.mistral.ai/v1`, key: `MISTRAL_API_KEY`. Model: `mistral-small-latest` (128k context). 2 RPM on free Experiment tier — critic-only role only.
- **Mistral (Codestral)** — `https://codestral.mistral.ai/v1`, key: `CODESTRAL_API_KEY`. Model: `codestral-latest` (256k context, 30 RPM, 2,000 req/day). Free code specialist endpoint. Strong fit as coding task critic.
- **Together AI** — `https://api.together.xyz/v1`, key: `TOGETHER_API_KEY`. Primary model: `meta-llama/Llama-4-Scout-17B-16E-Instruct` (327k context, tool calling). Credits-required ($5 minimum); ~$0.18/M input tokens.

No new Python packages are required. The `openai` package (already installed) handles all four providers via `base_url` override with `max_retries=0`.

### Expected Features

The FEATURES.md file covers SambaNova in depth and serves as the table stakes reference for the integration pattern. For complete details see `.planning/research/FEATURES.md`.

**Must have (table stakes) — required for each provider to be functional:**
- `ProviderType` enum value, `ProviderSpec`, and `ModelSpec` entries for each provider
- `(0.0, 0.0)` pricing entries in `SpendingTracker._BUILTIN_PRICES` for all free-tier models — prevents false spend-cap trips
- `.env.example` entries with accurate free-vs-credits documentation
- `SAMBANOVA_API_KEY` + `TOGETHER_API_KEY` documented as "credits-based, not free"
- Temperature clamping to 0–1 for SambaNova (rejects values > 1 unlike OpenAI's 0–2 range)
- `strict: false` enforcement in tool definitions for SambaNova (does not support `strict: true`)
- `stream=False` for SambaNova tool-calling requests (streaming tool calls missing required `index` field)
- Mistral Codestral as separate `ProviderType.MISTRAL_CODESTRAL` with independent key and base URL
- Health checks that include a tool-call probe (not just a ping) for tool-capable providers

**Should have (improves routing quality):**
- `supports_streaming_tools: bool` flag on `ProviderSpec` — SambaNova must be `False`
- `unsupported_params: frozenset[str]` on `ProviderSpec` — documents Cerebras/SambaNova rejection of `frequency_penalty`, `presence_penalty`
- `tool_choice_required_value: str` on `ProviderSpec` — Mistral uses `"any"` not `"required"`
- DeepSeek-R1 via SambaNova registered as a critic-only (no tools) model for high-quality reasoning passes
- `GEMINI_FREE_TIER` config flag with startup warning to prevent silent billing on Cloud-enabled Google projects
- `FREE_MODEL_IDS` set on `SpendingTracker` to replace naming-convention-based free detection with tier-based detection
- Weighted provider selection in rotation that accounts for sustainable RPM differences

**Defer (v2+):**
- `OPENROUTER_FREE_ONLY` flag enforcement at registration time (valid but low urgency)
- Embeddings via SambaNova's E5-Mistral (4k context limit makes it low value)
- Together AI image generation and TTS endpoints
- Preview model registration for SambaNova (`gpt-oss-120b` preview, `Llama-4-Maverick`, `Qwen3-235B`) — too unstable for production routing
- Circuit-breaker pattern aggregated across tasks (per-task `_failed_models` is sufficient for v1)

### Architecture Approach

All four integrations follow an identical pattern — pure configuration additions to `providers/registry.py`, with minimal changes to `core/config.py`, `agents/model_router.py`, and `.env.example`. Mistral requires two `ProviderType` entries (one per domain) as the sole structural variation. For complete details see `.planning/research/ARCHITECTURE.md`.

**Major components and their changes:**
1. `providers/registry.py` — Add `ProviderType` enum values, `ProviderSpec` dicts, `ModelSpec` records, `_BUILTIN_PRICES` free-model entries. Heaviest file touched.
2. `core/config.py` — Add `cerebras_api_key`, `sambanova_api_key`, `mistral_api_key`, `codestral_api_key`, `together_api_key`, `gemini_free_tier` fields following the existing frozen dataclass pattern.
3. `agents/model_router.py` — Update `FREE_ROUTING` dict (new primary/critic slots per TaskType) and `_get_fallback_models()` (include Cerebras in fallback chain; Codestral in coding-task critics).
4. `model_catalog.py` — Add new providers to health check list; use infrequent polling (30+ min) for Mistral to avoid burning its 2 RPM allowance.
5. `.env.example` — Add 5 new API key entries with accurate documentation of free-vs-credits tiers.

### Critical Pitfalls

Full pitfall catalog with 20 entries in `.planning/research/PITFALLS.md`. The five most likely to cause production incidents:

1. **SpendingTracker false expensive billing** — Every new provider's free models will hit the $5/$15 fallback rate without explicit `(0.0, 0.0)` `_BUILTIN_PRICES` entries, potentially triggering the daily spend cap. Fix: add explicit zero-pricing entries for every free-tier model ID before any task runs on the new provider.

2. **SambaNova streaming tool calls missing `index` field** — SambaNova's streaming implementation omits the `index` field required by OpenAI spec, causing `KeyError` in Agent42's tool call parser. Fix: set `stream=False` whenever `tools` are present and provider is `ProviderType.SAMBANOVA`.

3. **Mistral 2 RPM free tier causes 429 storm under concurrent load** — More than one concurrent agent immediately saturates Mistral La Plateforme's free tier. Fix: never assign Mistral Small to a primary slot in `FREE_ROUTING`. Codestral endpoint (30 RPM) as code critic only — one call per task, not per iteration.

4. **SambaNova and Together AI free-tier documentation is outdated** — PROJECT.md describes both as free providers. SambaNova now offers $5/30-day trial credits; Together AI requires a minimum $5 purchase as of July 2025. Fix: update `.env.example` and user-facing docs to classify both as credits-based before shipping.

5. **Cerebras free-tier context window is 65K not 131K** — Routing large-context tasks to Cerebras free tier with a `ModelSpec` configured for 131K causes 422 errors. Fix: set `max_context_tokens=65000` for all Cerebras free-tier `ModelSpec` entries.

---

## Implications for Roadmap

Based on combined research findings, the following phase structure is recommended. The ordering logic: fix foundational plumbing (pricing, config) first, add the highest-value genuinely-free provider second, then layer in the credits-based and structurally-complex providers, and finish with routing optimization once all providers are active.

### Phase 1: Foundation and Cerebras Integration

**Rationale:** Cerebras is the only provider in this set that is genuinely free (not credits-based), has the highest throughput (3,000 tok/s, 30 RPM), and has the fewest integration gotchas. It is the highest ROI starting point. The SpendingTracker fix must land in Phase 1 or every subsequent phase will corrupt daily spend tracking.

**Delivers:** Cerebras as primary/fallback model in `FREE_ROUTING`; accurate $0 cost tracking for free-tier models; `CEREBRAS_API_KEY` in `.env.example`; `GEMINI_FREE_TIER` config flag with startup warning.

**Addresses features:** `ProviderType.CEREBRAS`, 4 `ModelSpec` entries (`gpt-oss-120b` as primary, `qwen3-235b` as critic, `llama-8b` as lightweight, `zai-glm-4.7` reserved for low-volume critic at 100 RPD limit), `(0.0, 0.0)` pricing entries in `_BUILTIN_PRICES`.

**Avoids:** Pitfall #1 (SpendingTracker misreporting — required for all subsequent phases), Pitfall #5 (`max_tokens` vs `max_completion_tokens` — test explicitly), Pitfall #8 (set `max_context_tokens=65000` not 131K).

### Phase 2: Mistral Integration (Codestral + La Plateforme)

**Rationale:** Mistral offers a genuinely free code-specialist endpoint (Codestral, 30 RPM) that is a strong fit as a coding-task critic. The two-key architecture (separate domain and key for Codestral vs La Plateforme) is the main complexity. La Plateforme (2 RPM) must be registered but explicitly excluded from primary slots.

**Delivers:** `ProviderType.MISTRAL` and `ProviderType.MISTRAL_CODESTRAL`; `codestral-latest` as code-review critic for `CODING`, `DEBUGGING`, `APP_CREATE` task types; `mistral-small-latest` registered as restricted critic only; health checks at 30+ minute intervals.

**Addresses features:** Two-key architecture, `MISTRAL_API_KEY` + `CODESTRAL_API_KEY` in `.env.example`, `tool_choice="any"` normalization for Mistral endpoints.

**Avoids:** Pitfall #6 (never assign Mistral to primary), Pitfall #12 (weighted rotation respects 2 RPM cap), Pitfall #17 (`tool_choice` normalization), Pitfall #14 (use `-latest` model aliases, not pinned version strings).

### Phase 3: SambaNova Integration (Credits-Based)

**Rationale:** SambaNova provides strong DeepSeek models (V3.1, R1) with 128k context and competitive RPM on the Developer Tier. However, its $5/30-day trial credit model, non-streaming tool calls, and function-calling limitations for specific models require more defensive coding than Cerebras or Mistral. Phase 3 placement gives time to validate Phase 1/2 routing patterns before adding SambaNova's complexity.

**Delivers:** `ProviderType.SAMBANOVA`; `Meta-Llama-3.3-70B-Instruct` (primary, tool-capable), `Meta-Llama-3.1-8B-Instruct` (health check probe model, lightweight), `DeepSeek-V3.1` (critic); `stream=False` guard for SambaNova + tools; documentation correcting the "free" claim; 402 credit-exhaustion handling verified.

**Addresses features:** Credits-tier classification, temperature clamping (0–1), `strict: false` enforcement, `supports_streaming_tools=False` on `ProviderSpec`.

**Avoids:** Pitfall #2 (document credits-not-free), Pitfall #4 (disable streaming for tool calls), Pitfall #10 (do not register deprecated 405B model — use 70B for tool calling), Pitfall #18 (health check uses completion probe, not auth-only ping).

### Phase 4: Together AI Integration (Credits-Based)

**Rationale:** Together AI has the highest OpenAI compatibility of the four providers and offers massive context windows (Llama 4 Scout: 327k tokens) at very low per-token cost. The main complexity is billing clarity ($5 minimum) and Together's dynamic rate limits (read headers, do not use static backoff values). Place last because it requires funded account verification and the dynamic rate limit handling adds non-trivial work.

**Delivers:** `ProviderType.TOGETHER`; `Llama-4-Scout-17B` (cheap-tier primary, 327k context — pending serverless availability verification), `DeepSeek-R1` and `DeepSeek-V3` as cheap-tier alternatives; corrected documentation; dynamic rate limit header parsing.

**Addresses features:** Credits-tier classification, `TOGETHER_API_KEY` in `.env.example` with "requires funded account" note, dynamic `x-ratelimit-remaining` header reading.

**Avoids:** Pitfall #3 (correct docs — not $25 free), Pitfall #13 (dynamic rate limits — read headers not static values), Pitfall #14 (verify Llama 4 Scout model ID is available serverless at signup before making it primary).

### Phase 5: Routing Optimization

**Rationale:** Once all four providers are registered, `FREE_ROUTING` needs optimization passes: weighted rotation by RPM, cross-provider fallback ordering, `_get_fallback_models()` chain tuning, and health check improvements (tool-call probes, not just pings). This is also where `FREE_MODEL_IDS` set refactoring on `SpendingTracker` pays off if per-model `(0.0, 0.0)` entries from Phases 1-4 accumulate to an unwieldy list.

**Delivers:** Weighted provider selection respecting RPM tiers; tool-call-inclusive health checks for all tool-capable providers; `OPENROUTER_FREE_ONLY` flag enforcement at registration + routing time; optional `FREE_MODEL_IDS` set refactor on `SpendingTracker`.

**Addresses features:** Pitfalls #11 (health check false positives), #12 (rotation ignores RPM differences), #20 (`OPENROUTER_FREE_ONLY` flag bypass).

### Phase Ordering Rationale

- Phases 1 and 2 deliver genuinely free capacity (Cerebras + Codestral) with no credit-expiry risk, providing immediate value with minimal operational complexity.
- The SpendingTracker fix is a hard dependency for all phases — it must land in Phase 1.
- SambaNova (Phase 3) before Together AI (Phase 4) because SambaNova has more integration gotchas (streaming tool calls, parameter restrictions) that exercise the `ProviderSpec` extension points added in Phases 1-2.
- Phase 5 (optimization) depends on all providers being registered to accurately characterize real-world RPM behavior and fallback ordering under actual production load.

### Research Flags

Phases likely needing deeper research or verification during implementation:

- **Phase 3 (SambaNova):** The streaming tool call `index` field bug is MEDIUM confidence (community report, not official docs). Recommend testing with an actual API key before permanently setting `stream=False` — the bug may be fixed or behave differently. A quick 30-minute test at implementation time resolves this.
- **Phase 4 (Together AI):** Whether Llama 4 Scout is available on the serverless API (not dedicated endpoint only) is unverified. The official model page says "not available on Together's Serverless API." Must verify at signup before committing it as the primary model. Fallback recommendation: use `deepseek-ai/DeepSeek-V3` as primary if Scout is restricted.
- **Phase 4 (Together AI):** Signup credit amount and expiry policy are MEDIUM confidence with conflicting sources. Verify at signup and update `.env.example` accordingly.

Phases with standard patterns (no additional research needed):

- **Phase 1 (Cerebras):** All facts are HIGH confidence from official docs. Integration pattern is identical to existing providers. No unknowns.
- **Phase 2 (Mistral Codestral):** Base URL, model IDs, tool calling format all HIGH confidence. The 2 RPM mitigation (critic-only) is clear and straightforward.
- **Phase 5 (Routing Optimization):** Agent42 already has weighted routing infrastructure from prior work. This is configuration refinement, not new architecture.

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All four API base URLs and `AsyncOpenAI` compatibility verified against official docs or official SDK examples. No new packages required. Model IDs current as of 2026-03-01. |
| Features | HIGH (Cerebras/Mistral), MEDIUM (SambaNova/Together AI) | Cerebras and Mistral feature sets fully verified from official docs. SambaNova streaming tool call bug is community-sourced (MEDIUM). Together AI serverless Llama 4 Scout availability is unverified (LOW). |
| Architecture | HIGH | Integration pattern is a strict extension of the existing `ProviderSpec`/`ModelSpec` registry. No novel patterns required. Two-key Mistral architecture is the sole structural variation. |
| Pitfalls | HIGH (15 of 20), MEDIUM (5) | SpendingTracker issue, Mistral RPM limit, Cerebras context window, SambaNova credits exhaustion — all verified against official sources. SambaNova streaming tool call `index` bug, Mistral Experiment exact RPM, Together AI signup credits are MEDIUM confidence from community sources. |

**Overall confidence:** HIGH for integration decisions; MEDIUM for operational details that require signup verification at implementation time.

### Gaps to Address

- **Mistral Experiment tier actual RPM limit:** PROJECT.md says 2 RPM; community sources cite 1 RPS (~60 RPM). The discrepancy is large enough to affect routing decisions. Verify against `admin.mistral.ai/plateforme/limits` at signup. If actually 60 RPM, Mistral La Plateforme could serve as a light primary rather than critic-only.
- **Together AI Llama 4 Scout serverless availability:** Must confirm at signup whether `meta-llama/Llama-4-Scout-17B-16E-Instruct` is accessible without a dedicated endpoint. If not, use `deepseek-ai/DeepSeek-V3` as the recommended Together primary in `FREE_ROUTING`.
- **SambaNova streaming tool call bug current status:** Reported July 2025. By implementation time it may be fixed. Test with actual API key before permanently setting `stream=False` for all SambaNova tool calls.
- **Mistral Experiment model availability:** Official docs do not specify which models are available on the free tier. `mistral-small-latest` is the assumed free model; verify at signup that it is accessible without paid billing.
- **SambaNova current model list:** Verify `Meta-Llama-3.3-70B-Instruct` is still available at signup — SambaNova's model list has evolved rapidly. Do not assume Llama 3.1 405B is available (it appears deprecated per current docs).

---

## Sources

### Primary (HIGH confidence)
- [Cerebras OpenAI Compatibility](https://inference-docs.cerebras.ai/resources/openai) — API pattern, supported params
- [Cerebras Rate Limits](https://inference-docs.cerebras.ai/support/rate-limits) — TPM/TPD/RPM limits per model
- [Cerebras Models Overview](https://inference-docs.cerebras.ai/models/overview) — current model IDs, free-tier context windows
- [Cerebras Tool Calling](https://inference-docs.cerebras.ai/capabilities/tool-use) — function calling support verification
- [SambaNova Supported Models](https://docs.sambanova.ai/docs/en/models/sambacloud-models) — current model roster
- [SambaNova Rate Limits](https://docs.sambanova.ai/docs/en/models/rate-limits) — free vs developer tier limits
- [SambaNova Function Calling](https://docs.sambanova.ai/docs/en/features/function-calling) — supported models, `strict: false` requirement
- [SambaNova Developer Tier announcement](https://sambanova.ai/blog/sambanova-cloud-developer-tier-is-live) — credits-based model change
- [Mistral API reference](https://docs.mistral.ai/api/) — base URL, auth, unsupported params
- [Mistral Models Overview](https://docs.mistral.ai/getting-started/models/models_overview/) — model IDs and aliases
- [Mistral Function Calling](https://docs.mistral.ai/capabilities/function_calling) — `tool_choice="any"` requirement
- [Mistral Experiment Plan help](https://help.mistral.ai/en/articles/455206-how-can-i-try-the-api-for-free-with-the-experiment-plan) — free tier confirmed
- [Together AI OpenAI Compatibility](https://docs.together.ai/docs/openai-api-compatibility) — drop-in usage confirmed
- [Together AI Billing](https://docs.together.ai/docs/billing) — credit requirements documented
- [Together AI Free Tier Changes (Jul 2025)](https://support.together.ai/articles/1862638756-changes-to-free-tier-and-billing-july-2025) — $5 minimum purchase confirmed
- [Together AI Function Calling](https://docs.together.ai/docs/function-calling) — supported models
- Agent42 `providers/registry.py` lines 280-296 — SpendingTracker free-detection logic (direct code inspection)

### Secondary (MEDIUM confidence)
- [cheahjs/free-llm-api-resources](https://github.com/cheahjs/free-llm-api-resources) — Mistral Experiment tier RPM, Codestral limits
- [SambaNova community thread on free tier](https://community.sambanova.ai/t/is-free-tier-going-away/847) — credits-only clarification (official moderator response)
- [SambaNova OpenAI SDK compatibility thread](https://community.sambanova.ai/t/openai-sdk-compatibility-using-vercel-ai-sdk-with-openai-compatible-provider/1266) — streaming tool call `index` bug report
- [LiteLLM Codestral docs](https://docs.litellm.ai/docs/providers/codestral) — Codestral base URL corroboration
- [Together AI rate limits docs](https://docs.together.ai/docs/rate-limits) — dynamic rate limit behavior documented
- [Portkey failover routing strategies](https://portkey.ai/blog/failover-routing-strategies-for-llms-in-production/) — rotation design patterns

### Tertiary (LOW confidence)
- Together AI signup credit amount ($25 or $100 or $0) — conflicting sources; verify at signup
- Together AI credit expiry policy — official docs say no expiry; may have changed with July 2025 billing changes

---

*Research completed: 2026-03-01*
*Ready for roadmap: yes*
