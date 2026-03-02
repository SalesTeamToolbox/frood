# Agent42 Free LLM Provider Expansion

## What This Is

A resilience and capability upgrade to Agent42's LLM provider ecosystem. Adds 4 new free-tier providers (Cerebras, SambaNova, Mistral, Together AI) with smart rotation across all providers as primaries, so Agent42 is always operational with top-tier brain power — even on zero budget.

## Core Value

Agent42 must always be able to operate on free-tier LLMs, with enough model diversity and quality that no single provider outage or quota exhaustion stops the platform.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Integrate Cerebras as a provider (OpenAI-compatible API, 1M tokens/day free, Qwen3 235B + Llama 70B)
- [ ] Integrate SambaNova as a provider (Llama 3.1 405B, 200K TPD free, great for critic passes)
- [ ] Integrate Mistral as a provider (Codestral for code gen, 1B tokens/month free on Experiment tier)
- [ ] Integrate Together AI as a provider ($25 free credits, sub-100ms latency, Llama/DeepSeek models)
- [ ] Add `GEMINI_FREE_TIER` config flag (true/false) so users declare their Gemini billing tier
- [ ] Implement smart rotation in FREE_ROUTING — spread primary load across Cerebras/SambaNova/Together/Gemini(if free)
- [ ] Update fallback chain to leverage all new providers with provider-diversity awareness
- [ ] Register all new models in MODELS dict with correct ModelSpec (tiers, context windows, speeds)
- [ ] Add new ProviderType enum values and ProviderSpec entries for each provider
- [ ] Update spending tracker with pricing for new providers (free models = $0)
- [ ] Ensure health checks cover new providers (model_catalog.py)
- [ ] Update .env.example with all new API key variables
- [ ] Add `OPENROUTER_FREE_ONLY` config flag to lock OpenRouter to free models only (users add $10 to unlock free tier but don't want to accidentally use paid models)
- [ ] Tests for all new provider integrations

### Out of Scope

- Cloudflare Workers AI — too-low limits for agentic workloads
- NVIDIA NIM — already partially in codebase, limited free tier
- Paid tier integration for new providers — free tier only in this milestone
- Custom fine-tuned models on any provider
- Groq integration — already integrated per user's research notes

## Context

Agent42 currently uses a 5-layer model routing chain (admin override > dynamic > trial > policy > hardcoded defaults). The FREE_ROUTING dict maps every TaskType to a primary + critic model. Today, all 7 free models route through OpenRouter, with Gemini 2.5 Flash as the universal primary.

**Problem:** This creates two single points of failure:
1. OpenRouter free tier degradation kills all free model access
2. Gemini paid-project activation silently converts "free" routing to paid

**The fix:** Add 4 independent providers with their own API keys, distribute primary routing across them, and let users flag their Gemini billing status.

**Provider capabilities (from research):**
- **Cerebras:** 1,800 tok/s (8B), 450 tok/s (70B), 1,400 tok/s (Qwen3 235B). OpenAI-compatible. Free: 1M tokens/day.
- **SambaNova:** Custom RDU hardware. Free: 200K TPD + $5 trial credits, 10-30 RPM. Models: Llama 3.1 405B, Qwen 2.5 72B.
- **Mistral:** Codestral (elite code gen), Mistral Large. Free: 2 RPM, 1B tokens/month on Experiment tier. Low RPM = best for critic/review.
- **Together AI:** $25 free credits. Sub-100ms latency. Llama 4 Scout, DeepSeek models. Multimodal.

**All 4 providers use OpenAI-compatible APIs**, making integration straightforward — same `AsyncOpenAI` client pattern already used for Gemini and OpenRouter.

## Constraints

- **API compatibility**: All new providers must be OpenAI Chat Completions compatible (they are)
- **No paid defaults**: New provider models must default to FREE tier in ModelSpec
- **Graceful degradation**: Missing API keys for any new provider must not crash Agent42
- **Backward compatible**: Existing routing must continue to work unchanged for users who don't add new API keys

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Smart rotation over single-primary | Distributes free quota across providers, prevents exhaustion | — Pending |
| Cerebras as top priority for agent loops | Fastest inference (20x GPU clouds), critical for iterative coding | — Pending |
| SambaNova for critic passes | Llama 405B free gives best critic quality on free tier | — Pending |
| Mistral for code specialist roles | Codestral is elite for code gen; low RPM limits it to critic/review | — Pending |
| Together AI as general workhorse | $25 credits + fast inference fills the "Gemini alternative" slot | — Pending |
| GEMINI_FREE_TIER config flag | Users on paid Gemini projects shouldn't unknowingly incur costs | — Pending |

---
*Last updated: 2026-03-01 after initialization*
