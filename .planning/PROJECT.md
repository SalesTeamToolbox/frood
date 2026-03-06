# Agent42

## What This Is

An AI agent platform that operates across 8 LLM providers with smart routing, provider-diverse fallback, and zero-budget operation. Agents run on free-tier LLMs (Cerebras, Groq, Codestral, Gemini, OpenRouter free) with CHEAP-tier failover (SambaNova, Together AI, Mistral La Plateforme) when free models are exhausted.

## Core Value

Agent42 must always be able to operate on free-tier LLMs, with enough model diversity and quality that no single provider outage or quota exhaustion stops the platform.

## Requirements

### Validated

- ✓ Integrate Cerebras (FREE — GPT-OSS 120B, Qwen3 235B, 3000 tok/s) — v1.0
- ✓ Integrate Groq (FREE — Llama 70B, GPT-OSS 120B, 131K context) — v1.0
- ✓ Integrate Mistral (FREE Codestral + CHEAP La Plateforme dual-key) — v1.0
- ✓ Integrate SambaNova (CHEAP — Llama 70B, DeepSeek V3, 3 request transforms) — v1.0
- ✓ Integrate Together AI (CHEAP — DeepSeek V3, Llama 70B) — v1.0
- ✓ GEMINI_FREE_TIER config flag for Gemini billing tier control — v1.0
- ✓ OPENROUTER_FREE_ONLY config flag to lock to free models — v1.0
- ✓ Smart rotation in FREE_ROUTING across Cerebras/Groq/Codestral/Gemini — v1.0
- ✓ Provider-diverse fallback chain — v1.0
- ✓ SpendingTracker pricing for all new providers — v1.0
- ✓ Health checks for new providers (including CHEAP tier) — v1.0
- ✓ SambaNova request transforms (temp clamp, stream=False, strict removal) — v1.0
- ✓ Full test coverage for all new providers — v1.0

### Active

## Current Milestone: v1.1 Layout & Authentication Fixes

**Goal:** Fix real-time UI updates, authentication problems, and error handling to improve user experience

**Target features:**
- Real-time chat updates without page refresh
- Proper user feedback during processing
- Authentication issue resolution
- Improved error messaging
- Loading indicators and status feedback

### Out of Scope

- Cloudflare Workers AI — too-low limits for agentic workloads
- NVIDIA NIM — already partially in codebase, limited free tier
- Custom fine-tuned models on any provider
- Provider-native SDKs — all use OpenAI-compatible API

## Context

Shipped v1.0 with 69,819 lines Python across 8 LLM providers.
Tech stack: Python 3.11+, FastAPI, AsyncOpenAI, aiofiles, pytest.
1,956 tests passing (90+ new provider/routing tests in v1.0).

**Current routing:**
- Cerebras primary for coding/debugging/app_create (fastest inference)
- Groq primary for research/content/strategy (131K context)
- Codestral critic for all code task types (free code-specialist)
- Gemini 2.5 Flash as general primary (if free tier active)
- Provider-diverse round-robin fallback prevents single-provider exhaustion
- CHEAP-tier failover: SambaNova + Together AI when free models exhausted

**Known concerns (from v1.0):**
- SambaNova streaming tool call `index` bug — needs real API verification
- Together AI Llama 4 Scout serverless availability unverified
- Mistral La Plateforme actual RPM unverified (2 vs ~60 RPM)

## Constraints

- **API compatibility**: All providers use OpenAI Chat Completions compatible APIs
- **No paid defaults**: Provider models default to FREE or CHEAP tier
- **Graceful degradation**: Missing API keys never crash Agent42
- **Backward compatible**: Users without new API keys keep existing routing

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Smart rotation over single-primary | Distributes free quota across providers, prevents exhaustion | ✓ Good — eliminates dual SPOF |
| Cerebras as top priority for coding | Fastest inference (3000 tok/s), critical for iterative agent loops | ✓ Good — 20x faster than cloud GPUs |
| Groq as second free anchor | Genuinely free ~14K req/day, 131K context | ✓ Good — diversifies away from Cerebras |
| SambaNova as CHEAP fallback | Credits-based, Llama 70B + DeepSeek V3 when free exhausted | ✓ Good — quality fallback |
| Mistral dual-key architecture | Codestral free for code, La Plateforme paid for critic | ✓ Good — maximizes free usage |
| Together AI as general workhorse | Credits + fast inference fills "Gemini alternative" slot | ✓ Good — broad model selection |
| GEMINI_FREE_TIER config flag | Prevents unknowing paid API costs for Gemini users | ✓ Good — operator control |
| ProviderType enum in Phase 1 | All 6 values added upfront, future phases only need Spec entries | ✓ Good — clean dependency chain |
| deepcopy for SambaNova strict removal | Prevents mutating caller's tool definitions | ✓ Good — first provider needing tool mutation |
| Provider-diverse round-robin | _find_healthy_free_model cycles providers before retrying same | ✓ Good — prevents quota exhaustion |

---
*Last updated: 2026-03-02 after v1.0 milestone*
