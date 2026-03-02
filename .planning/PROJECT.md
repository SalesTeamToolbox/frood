# Agent42 Free LLM Provider Expansion

## What This Is

A resilience and capability upgrade to Agent42's LLM provider ecosystem. Adds 5 new providers (Cerebras, Groq, Mistral, SambaNova, Together AI) with smart rotation across all providers as primaries, so Agent42 is always operational with top-tier brain power — even on zero budget. Cerebras and Groq are genuinely free; Mistral Codestral is free; SambaNova and Together AI are credits-based (CHEAP tier).

## Core Value

Agent42 must always be able to operate on free-tier LLMs, with enough model diversity and quality that no single provider outage or quota exhaustion stops the platform.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Integrate Cerebras (FREE — 1M tokens/day, GPT-OSS 120B, Qwen3 235B, fastest inference)
- [ ] Integrate Groq (FREE — ~14K req/day, Llama 70B, GPT-OSS 120B, 280-560 tok/s)
- [ ] Integrate Mistral (FREE Codestral endpoint + CHEAP La Plateforme, elite code gen)
- [ ] Integrate SambaNova (CHEAP — $5 trial credits, Llama 70B, DeepSeek V3, temp clamp needed)
- [ ] Integrate Together AI (CHEAP — credits-based, DeepSeek V3, Llama models)
- [ ] Add `GEMINI_FREE_TIER` config flag (true/false) so users declare their Gemini billing tier
- [ ] Add `OPENROUTER_FREE_ONLY` config flag to lock to free models only
- [ ] Smart rotation in FREE_ROUTING across Cerebras/Groq/Codestral/Gemini(if free)
- [ ] Provider-diverse fallback chain
- [ ] SpendingTracker pricing for all new providers
- [ ] Health checks for new providers
- [ ] SambaNova request transforms (temp clamp, stream=False for tools, strict removal)
- [ ] Tests for all new provider integrations

### Out of Scope

- Cloudflare Workers AI — too-low limits for agentic workloads
- NVIDIA NIM — already partially in codebase, limited free tier
- Paid tier integration for new providers — free tier only in this milestone
- Custom fine-tuned models on any provider
- Groq paid tier — free tier only

## Context

Agent42 currently uses a 5-layer model routing chain (admin override > dynamic > trial > policy > hardcoded defaults). The FREE_ROUTING dict maps every TaskType to a primary + critic model. Today, all 7 free models route through OpenRouter, with Gemini 2.5 Flash as the universal primary.

**Problem:** This creates two single points of failure:
1. OpenRouter free tier degradation kills all free model access
2. Gemini paid-project activation silently converts "free" routing to paid

**The fix:** Add 5 independent providers with their own API keys, distribute primary routing across them, and let users flag their Gemini billing status.

**Provider capabilities (research-verified):**
- **Cerebras** (FREE): GPT-OSS 120B (3000 tok/s), Qwen3 235B (1400 tok/s), Llama 8B (1800 tok/s). 1M tokens/day free. Fastest inference alive.
- **Groq** (FREE): Llama 3.3 70B (280 tok/s, 1K RPM), GPT-OSS 120B (500 tok/s). ~14K req/day free. 131K context.
- **Mistral** (FREE Codestral / CHEAP La Plateforme): Codestral free endpoint (30 RPM, 2K RPD). La Plateforme 2 RPM free = critic-only.
- **SambaNova** (CHEAP): $5 trial credits (30-day expiry). Llama 3.3 70B, DeepSeek V3. Temp max 1.0. Streaming tool call bugs.
- **Together AI** (CHEAP): Credits-based ($5 min purchase). DeepSeek V3, Llama models. Sub-100ms latency.

**All 5 providers use OpenAI-compatible APIs**, making integration straightforward — same `AsyncOpenAI` client pattern already used for Gemini and OpenRouter.

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
| Groq as second free anchor | Genuinely free ~14K req/day, diversifies away from Cerebras single-point | — Pending |
| SambaNova as CHEAP fallback | Credits-based, Llama 70B + DeepSeek V3 for quality when free exhausted | — Pending |
| Mistral for code specialist roles | Codestral is elite for code gen; low RPM limits it to critic/review | — Pending |
| Together AI as general workhorse | $25 credits + fast inference fills the "Gemini alternative" slot | — Pending |
| GEMINI_FREE_TIER config flag | Users on paid Gemini projects shouldn't unknowingly incur costs | — Pending |

---
*Last updated: 2026-03-01 after initialization*
