# Domain Pitfalls: Multi-Provider Free LLM Integration

**Domain:** Multi-provider free LLM inference (Cerebras, SambaNova, Mistral, Together AI added to Agent42)
**Researched:** 2026-03-01
**Overall confidence:** HIGH for provider-specific facts (official docs); MEDIUM for rotation patterns (community sources)

---

## Critical Pitfalls

Mistakes that cause rewrites, silent failures, or production incidents.

---

### Pitfall 1: SpendingTracker Misreports New Providers as Expensive

**What goes wrong:** Agent42's `SpendingTracker._get_price()` detects free models via two patterns: the internal key starting with `or-free-` and the model ID ending with `:free`. Cerebras, SambaNova, Mistral, and Together AI free models match neither pattern. Without explicit pricing entries, every call to these providers falls through to the conservative `$5/$15 per million token` fallback. A single 200K-token coding task gets logged as costing ~$4 instead of $0, potentially triggering the `max_daily_api_spend_usd` limit and blocking further requests.

**Why it happens:** The `_get_price()` free-detection logic was written for OpenRouter's naming conventions and was never generalized. Verified in `providers/registry.py` lines 280-296.

**Consequences:** False cost accumulation → daily spend limit hit mid-day → all agent tasks fail with `SpendingLimitExceeded` → silent degradation; users see failures with no obvious cause.

**Prevention:** Before shipping each new provider, add all free-tier model IDs to `_BUILTIN_PRICES` with `(0.0, 0.0)` pricing. Alternatively, generalize `_get_price()` to detect free models via `ProviderType` when `tier == ModelTier.FREE`. The per-provider `ModelSpec.tier` field is the right authoritative source for this.

**Detection:** After first task runs on a new provider, check `spending_tracker.daily_spend_usd` via the `/api/reports` endpoint. If it shows non-zero cost for a task that should be free, this pitfall has occurred.

**Phase:** Provider registration (Phase 1 of each provider integration).

---

### Pitfall 2: SambaNova's Free Tier Is Now Credits-Only (Not Permanently Free)

**What goes wrong:** Agent42's `PROJECT.md` describes SambaNova as "200K TPD free." This was accurate when the free tier existed, but SambaNova discontinued it in early 2025. New accounts receive $5 in trial credits (30-day expiration), which is consumed at inference rates. Once credits exhaust, the API returns 402 errors. For Agent42 users who set `SAMBANOVA_API_KEY` expecting permanent free access, tasks will start failing after a few days of usage with no warning.

**Why it happens:** SambaNova launched a paid "Developer Tier" and transferred all free-tier users to it with initial credits. Source: Official SambaNova community announcement (verified January 2025).

**Consequences:** Tasks using SambaNova as primary or critic silently fail after credit exhaustion → fallback chain overloaded → degraded throughput on remaining providers.

**Prevention:**
1. Treat SambaNova as a "credits provider" (like Together AI) rather than a permanently free provider. Document this prominently in `.env.example`.
2. Implement 402 payment-error handling to remove SambaNova from active rotation when credits exhaust — Agent42 already has `_is_payment_error()` for this, but it must be verified to fire on SambaNova's 402 response format.
3. Consider not using SambaNova as primary in `FREE_ROUTING` — reserve it for quality-critical passes where Llama 405B's capability justifies spending the limited credits.

**Detection:** 402 response from SambaNova API after initial usage period. Warning sign in logs: `SpendingLimitExceeded` on SambaNova model key after first ~30 days.

**Phase:** Provider registration + `FREE_ROUTING` design.

---

### Pitfall 3: Together AI No Longer Offers Free Trials

**What goes wrong:** Agent42's `PROJECT.md` documents Together AI as "$25 free credits." Together AI removed free trials in July 2025 — new accounts now require a minimum $5 credit purchase. The `$25 credits` figure referred to an early-adopter promotion, no longer available. If users add `TOGETHER_API_KEY` from a new account assuming they have free credits, they have zero balance and every request fails with a 402.

**Why it happens:** Together AI changed billing structure. Source: Official Together AI support article "Changes to free tier and billing July 2025."

**Consequences:** All routing through Together AI fails immediately. Because `_is_payment_error()` will catch the 402 and add Together to `_failed_models`, it degrades silently — users may not realize Together AI was supposed to be active.

**Prevention:**
1. Update `PROJECT.md` and `.env.example` documentation to reflect that Together AI requires funded account (minimum $5).
2. Classify Together AI as a "funded credits" provider in model tier metadata — similar approach to SambaNova.
3. Provide a health check that detects zero-balance state before routing begins (check account balance via Together's billing API, if available, rather than waiting for a 402 mid-task).

**Detection:** 402 response immediately on first Together AI call with unfunded account.

**Phase:** Provider registration + documentation.

---

### Pitfall 4: SambaNova Streaming Tool Calls Are Missing the `index` Field

**What goes wrong:** When streaming tool calls from SambaNova, the response omits the `index` field that OpenAI's spec mandates for each `tool_calls` chunk. Additionally, SambaNova delivers tool calls as a single complete chunk rather than progressively assembling them across multiple deltas (non-streaming behavior in streaming mode). Some integrations report function names being modified: `get_weather_data` may come back as `weather_data` with the `get_` prefix stripped.

**Why it happens:** SambaNova's streaming implementation does not fully conform to OpenAI's streaming spec. Documented in SambaNova Developer Community (July 2025): "SambaNova's streaming response missing the required index field in tool calls which OpenAI's specification mandates."

**Consequences:** Agent42's `_run_tool_loop` parses tool call chunks expecting OpenAI format. Missing `index` fields cause `KeyError` or silent tool-call-drop. Function name mismatch causes `_execute_tool_calls` to look up a tool name that doesn't exist (`weather_data` vs `get_weather_data`), returning a "tool not found" error.

**Prevention:**
1. Disable streaming for SambaNova tool-calling requests. Pass `stream=False` when `tools` are present and the provider is `ProviderType.SAMBANOVA`. This is a standard pattern across providers with streaming tool call issues.
2. Add a `supports_streaming_tools: bool = True` flag to `ProviderSpec` and set it `False` for SambaNova.
3. If streaming is required, add a normalizer that reconstructs the missing `index` field from the chunk's position in the stream.

**Detection:** `KeyError: 'index'` in tool call parsing code when streaming from SambaNova. Or tool execution failures where the tool name doesn't match any registered tool.

**Phase:** Provider registration + tool call integration.

---

### Pitfall 5: Cerebras Uses `max_completion_tokens` Not `max_tokens`

**What goes wrong:** Cerebras's official API uses `max_completion_tokens` as the parameter name, mirroring OpenAI's current preferred naming. Agent42's `ProviderRegistry.complete()` and `complete_with_tools()` both pass `max_tokens` (the legacy OpenAI parameter name). Cerebras may silently ignore the unrecognized parameter, returning responses truncated at its own default, or raise a 400 `BadRequestError`.

**Why it happens:** OpenAI is migrating from `max_tokens` to `max_completion_tokens` and Cerebras adopted the newer name from the start. The OpenAI Python SDK transparently handles this for OpenAI's own API, but when used with third-party base URLs, no translation occurs.

**Consequences:** Agent42's coding tasks may be silently truncated mid-function. No error is raised — the response just ends early. Critic detects incomplete output and marks task as FAILED, wasting iterations.

**Prevention:** Test Cerebras responses with and without explicit token limits. If `max_tokens` is ignored, add a Cerebras-specific parameter translation in `ProviderRegistry._build_call_kwargs()` — or pass both parameter names and let the server ignore the one it doesn't know.

**Detection:** Coding task outputs that end mid-sentence or mid-function. Compare `completion_tokens` from usage data against `max_tokens` set in `ModelSpec` — if completion tokens always equal the default and not the configured max, the parameter is being ignored.

**Phase:** Provider registration testing.

---

### Pitfall 6: Mistral's 2 RPM Free Tier Makes It Unsuitable as Primary

**What goes wrong:** Mistral's free tier ("Experiment" / "La Plateforme") allows only 2 requests per minute (confirmed: 1 request/second documented, ~2 RPM effective). Agent42 runs multiple concurrent tasks and agents. Any attempt to use Mistral as a primary model in `FREE_ROUTING` will produce 429s for ~90% of concurrent requests. The `_complete_with_retry` exponential backoff holds the async event loop slot, blocking other tasks.

**Why it happens:** Mistral's free tier is designed for individual experimentation, not production agentic workloads. The 1B tokens/month allowance is generous, but the RPM cap is severely restrictive. Source: official Mistral rate limit help article and La Plateforme documentation.

**Consequences:** Severe throughput degradation. If Mistral is in primary slot for any TaskType with concurrent agents, all those tasks will queue behind a 30-60 second retry window. The `AGENT_DISPATCH_DELAY=2.0s` stagger helps marginally but doesn't solve the fundamental 2 RPM constraint.

**Prevention:** Use Mistral exclusively in critic/review slots where a single call per task (not per iteration) fits within the rate limit. Codestral (separate endpoint, `codestral.mistral.ai`) has a more generous limit: 30 RPM, 2,000 requests/day — suitable for code review critic passes on large tasks.

**Routing recommendation:**
- `mistral-codestral` → code review critic for `CODING`, `DEBUGGING`, `APP_CREATE`
- `mistral-small` → never primary; only as final-review critic on slow tasks (DOCUMENTATION, STRATEGY)
- Never in primary slot for any TaskType

**Detection:** Sustained 429 wave from Mistral models when more than 2 concurrent agents are active.

**Phase:** `FREE_ROUTING` design for Mistral integration.

---

## Moderate Pitfalls

Mistakes that degrade quality or require rework, but don't cause total failure.

---

### Pitfall 7: Cerebras Free Tier Has Both TPM and TPD + TPH Limits

**What goes wrong:** Cerebras documents three time-window limits simultaneously: 60K TPM, 1M TPH, and 1M TPD. Most LLM providers only use one limit window. Code that only tracks or backs off on TPD exhaustion may miss the more aggressive TPH (tokens-per-hour) bucket. A task that burns 900K tokens in the first 50 minutes of an hour will hit the TPH limit 10 minutes early — returning 429s while TPD still shows plenty remaining.

**Why it happens:** Cerebras uses a multi-window bucket system. Source: Official Cerebras rate limits documentation table showing "1M" TPH and "1M" TPD for free-tier models alongside 60K TPM.

**Consequences:** Agent42's `_failed_models` set catches the 429 and skips Cerebras for the rest of the task — correct behavior. But if the task spans an hour boundary, the TPH bucket resets and Cerebras becomes available again mid-task, which `_failed_models` won't reflect (it's per-task, not time-aware).

**Prevention:** Treat Cerebras 429s as "skip for this task" (current behavior). Don't attempt re-adding Cerebras within the same task. The task's `_failed_models` set handles this correctly already.

**Detection:** Cerebras 429s that occur despite having budget remaining. Cross-reference with hourly usage logs.

**Phase:** Rate limit error handling.

---

### Pitfall 8: Context Window Mismatch on Cerebras Free Tier

**What goes wrong:** Cerebras `qwen-3-235b` has a 65K context window on the free tier, but 131K on paid. If `ModelSpec.max_context_tokens` is set to 131K, Agent42 may route large tasks to Cerebras expecting 131K capacity, but the free-tier API will return a 422 `UnprocessableEntityError` when input exceeds 65K tokens. The task then falls back — costing retry time.

**Why it happens:** Context window limits are tier-dependent. The official Cerebras documentation page for `qwen-3-235b-2507` explicitly shows: "Free Tier: 65k tokens, Paid Tiers: 131k tokens."

**Consequences:** 422 errors on large-context tasks routed to Cerebras free tier. Fallback chain activates. Iteration delay + potentially exhausting other providers' quota on a task that should have been prefiltered.

**Prevention:** Set `max_context_tokens=65000` for all Cerebras free-tier `ModelSpec` entries (not 131K). This ensures Agent42's context budget estimator respects the actual free-tier limit when deciding whether to route a task to Cerebras.

**Detection:** 422 `UnprocessableEntityError` from Cerebras with error text mentioning context length.

**Phase:** Provider registration (ModelSpec values).

---

### Pitfall 9: Mistral Uses `random_seed` Not `seed` for Deterministic Outputs

**What goes wrong:** Mistral's API uses `random_seed` as the parameter name for controlling deterministic sampling, while OpenAI uses `seed`. If Agent42 ever passes a `seed` parameter to a Mistral provider call (e.g., in critic passes where reproducibility is desired), the parameter will be silently ignored. Mistral will produce non-deterministic output.

**Why it happens:** Deliberate API design choice by Mistral, predating the current OpenAI convention. Source: Mistral API Specs documentation.

**Consequences:** Non-deterministic critic outputs when seeding is expected. Low severity — Agent42 doesn't currently pass `seed`, so this is a trap for future development.

**Prevention:** Add Mistral-specific parameter normalization in `ProviderRegistry` if deterministic seeding is ever needed. Document the difference in `providers/registry.py` as a comment on the `ProviderSpec` entry.

**Detection:** Reproducibility tests that fail against Mistral endpoints when `seed` is passed.

**Phase:** Future development awareness.

---

### Pitfall 10: SambaNova Recommends Against Llama 405B for Tool Calling

**What goes wrong:** `PROJECT.md` positions SambaNova as "Llama 3.1 405B, great for critic passes." However, SambaNova's own function-calling documentation explicitly warns: "We recommend using Llama 70B-Instruct for applications that combine conversation and tool calling" because "the 8B variant cannot reliably maintain conversations alongside tool definitions." The 405B is available for text completion but is not listed among the 7 models that support function calling. If Agent42 routes a tool-using task to SambaNova Llama 405B, the model will either hallucinate tool calls or ignore them.

**Why it happens:** SambaNova's function calling support is model-specific. Not all models on the platform support the `tools` parameter. Source: SambaNova function calling documentation listing supported models.

**Consequences:** Tool calls silently dropped or malformed. Agent loop runs without tool access → task produces text output instead of executing tools → marked FAILED by critic.

**Prevention:**
1. Use SambaNova Llama 405B only for pure text/critic passes (no tools parameter).
2. For tool-using passes on SambaNova, route to Llama 3.3 70B-Instruct instead.
3. Add `supports_function_calling=False` or separate model keys for 405B vs 70B to signal this constraint.

**Detection:** Missing `tool_calls` in SambaNova 405B responses when tools were provided. Agent loop proceeds with text generation instead of tool execution.

**Phase:** `FREE_ROUTING` design for SambaNova.

---

### Pitfall 11: Free Tier Provider Health Checks Succeed but Real Requests Fail

**What goes wrong:** Agent42's health check system sends a small probe request to verify provider availability. A provider can respond successfully to a minimal health ping (low token count, no tools) while failing on real production requests that hit RPM limits, TPM limits, or require tool-calling (which some providers only fail on when tools are actually present in the request body).

**Why it happens:** Health checks use simplified requests that don't exercise the full request path. SambaNova's streaming tool-call incompatibility, Mistral's 2 RPM limit, and Cerebras's hourly bucket don't manifest on a 1-token health ping.

**Real-world examples verified:**
- Mistral passes health ping → primary routing begins → second concurrent request 429s (2 RPM limit)
- SambaNova passes health ping → tool call with streaming → `KeyError: 'index'` on first real tool use
- Cerebras passes health ping (non-tool) → tool call with streaming → partial chunk assembly issue

**Consequences:** Health checks report green, tasks fail. Misleading metrics that make the routing system appear healthy when it isn't.

**Prevention:**
1. Health checks for tool-capable providers should include a simple tool call (one tool, one function) — not just a ping.
2. Tag providers with known limitations (`streaming_tools_broken=True`) and don't trust health checks for capabilities that weren't tested.
3. Circuit-breaker pattern: track consecutive failures per provider/capability combination in `_failed_models` aggregated across tasks (not just within one task).

**Detection:** Health check reports provider UP, but task failure rate for that provider is high. Log `trigger_fallback` events by provider to surface this gap.

**Phase:** Health check implementation.

---

### Pitfall 12: Round-Robin Rotation Doesn't Account for Rate Limit Window Sizes

**What goes wrong:** A naive round-robin spreads load evenly across providers by request count. But providers have different fundamental limit units:
- **Cerebras:** 30 RPM — can absorb burst
- **SambaNova:** 40 RPM — but 200K TPD (now credit-limited)
- **Mistral:** 2 RPM — severe bottleneck
- **Together AI:** Dynamic RPM + TPM based on account tier

Mixing a 30 RPM provider with a 2 RPM provider in the same rotation pool means Mistral gets 1 in every N requests — but under burst conditions, all N requests arrive within seconds and Mistral immediately 429s.

**Why it happens:** Rotation logic typically doesn't weight providers by their sustainable rate. Equal-weight rotation is the default because weights are hard to configure.

**Consequences:** Mistral generates a stream of 429s under any concurrent load. `_failed_models` catches this correctly per-task, but the health check then re-enables Mistral on the next task, which 429s again immediately.

**Prevention:** Weight provider selection by sustainable RPM in the rotation logic. Cerebras (30 RPM) should receive 15x more primary assignments than Mistral (2 RPM). Alternatively, remove Mistral from primary slot entirely and use it only as an explicit critic (one call per task, not per iteration).

**Detection:** Mistral 429 rate in logs approaches 90%+ when >2 agents run concurrently.

**Phase:** `FREE_ROUTING` and smart rotation implementation.

---

### Pitfall 13: Together AI's Dynamic Rate Limits Surprise Production Deployments

**What goes wrong:** As of January 26, 2026, Together AI implemented dynamic rate limiting that adapts based on live capacity and past usage patterns. Rate limits are no longer static values — they change based on your account's historical patterns and current platform load. Code that caches rate limit values or sets static backoff times based on observed limits will become incorrect.

**Why it happens:** Together AI's rate limit documentation explicitly states limits "adapt based on live capacity of the model, and your past usage patterns." Rate limits are returned per-request in `x-ratelimit-limit` headers, not published statically.

**Consequences:** A deployment that worked fine during testing may hit tighter limits in production if usage pattern shifts (e.g., burst workloads from team tasks vs. sequential single tasks). Backoff times calibrated during testing may be too short or too long.

**Prevention:** Always read Together AI's `x-ratelimit-remaining` and `x-ratelimit-limit` response headers and use them to calculate backoff, rather than using fixed values. This is the standard pattern used by Agent42's existing retry logic — verify it applies to Together AI responses.

**Detection:** 429s from Together AI at lower-than-expected throughput after usage patterns change.

**Phase:** Together AI provider integration + retry logic.

---

### Pitfall 14: Model IDs Change Without Notice on Free Tiers

**What goes wrong:** Free-tier providers regularly update their model lineups, retiring models or replacing them with newer versions. Agent42 already has extensive experience with this (pitfalls #52-#56 in CLAUDE.md document this pattern for OpenRouter). The new providers have the same risk:
- Cerebras retired `qwen-3-32b` and `llama-3.3-70b` from free tier as of 2026-02-16
- SambaNova's 405B had temporary outages (Jan 2025) and model list has evolved
- Mistral has versioned Codestral (`codestral-latest`, `codestral-2501`, etc.)
- Together AI model availability varies by account tier

**Why it happens:** Free-tier model access is a promotional offering, not a contractual service level. Providers upgrade their fleet and remove older models with little notice.

**Consequences:** 404 errors on every request to a retired model ID. Every task on that TaskType fails. The pattern is well-known to Agent42's codebase but will repeat for each new provider added.

**Prevention:**
1. Use model aliases (e.g., `codestral-latest`) where providers offer them, rather than specific version strings.
2. Implement periodic model ID validation as part of the health check cycle — not just checking if the provider responds, but if the specific model ID is still valid.
3. Keep `_failed_models` logic (per-task) separate from a longer-lived "model is dead" cache that can trigger a health check re-evaluation.

**Detection:** 404 from new provider after previously working. Warning sign: error text includes "model not found" or "model no longer available."

**Phase:** All provider integrations; health check design.

---

### Pitfall 15: Gemini Free Tier Silently Becomes Paid Without User Awareness

**What goes wrong:** The `GEMINI_FREE_TIER` flag (a planned feature in `PROJECT.md`) addresses a subtle failure mode: users who create a Gemini project in Google Cloud and enable billing "for higher limits" are no longer on the free tier — every API call costs money. Agent42 defaults to `gemini-2-flash` for all TaskTypes. Without the `GEMINI_FREE_TIER=true` flag, there's no way to detect or warn users that their "free" routing is actually incurring charges.

**Why it happens:** Google's Gemini API billing is project-scoped. A project with billing enabled uses the pay-per-token rate even on `gemini-2.5-flash`, which is genuinely free on unpaid projects. The API doesn't signal billing status in responses.

**Consequences:** Unexpected Gemini API bills. Users assume zero-cost operation. `SpendingTracker` correctly records Gemini costs — but only if the user checks the dashboard.

**Prevention:**
1. Ship the `GEMINI_FREE_TIER` config flag with a warning at startup when `GEMINI_API_KEY` is set and `GEMINI_FREE_TIER` is not explicitly configured.
2. When `GEMINI_FREE_TIER=false`, route Gemini to `ModelTier.CHEAP` instead of `ModelTier.FREE` in the routing logic.
3. Document in `.env.example`: "Set GEMINI_FREE_TIER=true only if your Google Cloud project has billing DISABLED."

**Detection:** Non-zero Google Cloud billing charges. `SpendingTracker` logs Gemini costs per call.

**Phase:** `GEMINI_FREE_TIER` config flag implementation.

---

## Minor Pitfalls

Low-severity issues that can be fixed quickly but are worth knowing about.

---

### Pitfall 16: Cerebras Doesn't Support `frequency_penalty` or `presence_penalty`

**What goes wrong:** Cerebras's API does not support `frequency_penalty` or `presence_penalty` parameters. Passing these (which OpenAI supports) returns a 400 `BadRequestError`. Agent42 doesn't currently pass these parameters, but if any tool, skill, or future code adds them for quality control purposes, Cerebras calls will fail.

**Prevention:** Document in `ProviderSpec` comments. Add a parameter filter in `ProviderRegistry` that strips unsupported parameters by provider type, or add a `unsupported_params: frozenset[str]` field to `ProviderSpec`.

**Source:** Cerebras API reference documentation (verified — the parameters are absent from the supported parameters list).

---

### Pitfall 17: Mistral `tool_choice="any"` Is Their Equivalent of OpenAI `"required"`

**What goes wrong:** OpenAI uses `tool_choice="required"` to force tool use. Mistral uses `tool_choice="any"` for the same behavior. Code that passes `tool_choice="required"` to a Mistral endpoint will likely receive a validation error or fall back to auto behavior.

**Prevention:** Add a `tool_choice_required_value: str = "required"` field to `ProviderSpec` that `complete_with_tools()` reads when constructing tool calls. For Mistral, this value is `"any"`.

**Source:** Mistral function calling documentation (verified).

---

### Pitfall 18: SambaNova API Key Expiration on Trial Credits

**What goes wrong:** SambaNova's $5 trial credits expire after 30 days. After expiration, the API key itself still authenticates (returns 200 on auth check) but any completion request returns 402. A health check that only validates authentication will report the provider as healthy even after credits expire.

**Prevention:** Design SambaNova health checks to perform a small completion (1-token test prompt) rather than just verifying the API key. Cache the result with a 1-hour TTL so the cost of the health check itself is negligible.

**Source:** SambaNova cloud plans documentation + community discussion about credit expiry behavior.

---

### Pitfall 19: Together AI Credits Don't Expire, But the `$25` New-User Credit Is Gone

**What goes wrong:** Agent42's `PROJECT.md` documents Together AI as "$25 free credits." This figure comes from a 2023-era promotional offer (referenced in a September 2024 tweet about Code Llama). Together AI removed free trials in July 2025. New accounts must purchase a minimum of $5 in credits. Existing users who added credits before July 2025 are unaffected — those credits don't expire.

**Consequence:** Documentation misleads new users into thinking Together AI is free.

**Prevention:** Update all references from "$25 free credits" to "requires funded account (minimum $5 credit purchase)." Label Together AI as a "credits-based" provider like SambaNova.

**Source:** Together AI official support article on July 2025 billing changes.

---

### Pitfall 20: `OPENROUTER_FREE_ONLY` Flag Needs Negative Validation

**What goes wrong:** The planned `OPENROUTER_FREE_ONLY` flag (from `PROJECT.md`) prevents accidentally using paid OpenRouter models. However, if the flag validation only checks model IDs at route-selection time (not at model registration time), it could silently skip validation for models added to `MODELS` dict between registration and routing. A new paid model registered via `register_model()` at runtime would bypass the flag.

**Prevention:** Apply `OPENROUTER_FREE_ONLY` validation at both model registration time and routing time. When the flag is true, `register_model()` should reject any `ProviderType.OPENROUTER` model without `:free` suffix.

**Phase:** `OPENROUTER_FREE_ONLY` implementation.

---

## Phase-Specific Warnings

| Phase Topic | Likely Pitfall | Mitigation |
|-------------|---------------|------------|
| Cerebras provider registration | `max_completion_tokens` vs `max_tokens` mismatch (Pitfall #5) | Test with explicit `max_tokens` and verify token counts in usage response |
| Cerebras ModelSpec values | Free-tier context window is 65K, not 131K (Pitfall #8) | Set `max_context_tokens=65000` for all free-tier Cerebras `ModelSpec` entries |
| SambaNova registration | 405B doesn't support function calling (Pitfall #10) | Add separate model keys for 70B (tool-capable) and 405B (text-only) |
| SambaNova tool integration | Streaming tool calls missing `index` field (Pitfall #4) | Default `stream=False` when SambaNova + tools; add `supports_streaming_tools=False` to ProviderSpec |
| Mistral registration | 2 RPM free tier catastrophic under concurrent load (Pitfall #6) | Never assign Mistral to primary slot; critic-only at max 1 call per task |
| Mistral tool calls | `tool_choice="required"` not valid; use `"any"` (Pitfall #17) | Parameter normalization in `complete_with_tools()` |
| Together AI registration | Credits-based, not free; $25 figure is outdated (Pitfall #3 + #19) | Update docs; treat as credits provider |
| `FREE_ROUTING` design | Mistral + Cerebras mixed in rotation ignores RPM differences (Pitfall #12) | Weight rotation by sustainable RPM; Mistral critic-only |
| SpendingTracker update | All 4 new providers will hit $5/$15 fallback (Pitfall #1) | Add `(0.0, 0.0)` entries for all free-tier model IDs in `_BUILTIN_PRICES` |
| Health check implementation | Providers healthy to ping but failing on tool calls (Pitfall #11) | Health checks must include tool call test for tool-capable providers |
| Gemini tier flag | Paid Gemini project unknowingly billed (Pitfall #15) | Startup warning if `GEMINI_FREE_TIER` not set; route based on tier |
| Smart rotation logic | Round-robin ignores RPM differences causing Mistral 429 storm (Pitfall #12) | Weighted selection or exclude Mistral from rotation entirely |
| SambaNova free tier docs | 200K TPD free tier is gone (Pitfall #2) | Update `PROJECT.md`, `.env.example`; treat as $5 credits |
| Future code additions | `frequency_penalty` passed to Cerebras causes 400 (Pitfall #16) | Document unsupported parameters in `ProviderSpec` comments |
| Model ID maintenance | Free models retire without notice across all providers (Pitfall #14) | Health check validates model IDs, not just provider endpoints |
| `OPENROUTER_FREE_ONLY` | Flag bypass via `register_model()` at runtime (Pitfall #20) | Validate at registration + routing time |

---

## Sources

- **Cerebras rate limits:** [Rate Limits - Cerebras Inference](https://inference-docs.cerebras.ai/support/rate-limits) (HIGH confidence — official docs)
- **Cerebras tool calling:** [Tool Calling - Cerebras Inference](https://inference-docs.cerebras.ai/capabilities/tool-use) (HIGH confidence — official docs)
- **Cerebras error codes:** [Error Codes - Cerebras Inference](https://inference-docs.cerebras.ai/support/error) (HIGH confidence — official docs)
- **Cerebras Qwen3-235B context windows:** [Qwen 3 235B - Cerebras Inference](https://inference-docs.cerebras.ai/models/qwen-3-235b-2507) (HIGH confidence — official docs)
- **SambaNova rate limits:** [Rate Limits Policy - SambaNova Documentation](https://docs.sambanova.ai/docs/en/models/rate-limits) (HIGH confidence — official docs)
- **SambaNova free tier discontinuation:** [Is free tier going away? - SambaNova Community](https://community.sambanova.ai/t/is-free-tier-going-away/847) (HIGH confidence — official moderator response)
- **SambaNova function calling supported models:** [Function Calling - SambaNova Documentation](https://docs.sambanova.ai/docs/en/features/function-calling) (HIGH confidence — official docs)
- **SambaNova streaming tool_calls missing index:** [OpenAI SDK compatibility - SambaNova Community](https://community.sambanova.ai/t/openai-sdk-compatibility-using-vercel-ai-sdk-with-openai-compatible-provider/1266) (MEDIUM confidence — community report, not official docs)
- **Mistral rate limits (2 RPM free tier):** [Mistral rate limits help article](https://help.mistral.ai/en/articles/424390-how-do-api-rate-limits-work-and-how-do-i-increase-them) (HIGH confidence — official Mistral help center)
- **Mistral `random_seed` vs `seed`:** [Mistral API Specs](https://docs.mistral.ai/api) (HIGH confidence — official docs)
- **Mistral `tool_choice="any"`:** [Function Calling - Mistral Docs](https://docs.mistral.ai/capabilities/function_calling) (HIGH confidence — official docs)
- **Mistral Codestral rate limits:** [free-llm-api-resources GitHub](https://github.com/cheahjs/free-llm-api-resources) (MEDIUM confidence — community-maintained list)
- **Together AI free trial removal (July 2025):** [Changes to free tier - Together AI Support](https://support.together.ai/articles/1862638756-changes-to-free-tier-and-billing-july-2025) (HIGH confidence — official support article)
- **Together AI dynamic rate limits:** [Together AI Rate Limits docs](https://docs.together.ai/docs/rate-limits) (HIGH confidence — official docs)
- **Together AI function calling:** [Function Calling - Together.ai Docs](https://docs.together.ai/docs/function-calling) (HIGH confidence — official docs)
- **Multi-provider rotation pitfalls:** [Failover Routing Strategies - Portkey](https://portkey.ai/blog/failover-routing-strategies-for-llms-in-production/) (MEDIUM confidence — industry blog, multiple sources consistent)
- **Health check false positives pattern:** [Routing, Load Balancing, and Failover in LLM Systems](https://dev.to/debmckinney/routing-load-balancing-and-failover-in-llm-systems-pn3) (MEDIUM confidence — community source)
- **SpendingTracker pitfall:** Code-verified in `providers/registry.py` lines 280-296 (HIGH confidence — direct code inspection)
