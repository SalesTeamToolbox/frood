# Roadmap: Agent42 Free LLM Provider Expansion

## Overview

Add five independent LLM inference providers (Cerebras, Groq, Mistral, SambaNova, Together AI) to Agent42's routing system, eliminating the dual single-point-of-failure on OpenRouter and Gemini. Each phase integrates one provider end-to-end — registry entries, SpendingTracker pricing, health checks, and tests — then Phase 6 wires everything together with smart rotation and config flags.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Foundation + Cerebras** (2/2 plans) - Lay provider enum plumbing, fix SpendingTracker free-model detection, integrate Cerebras (genuinely free, fastest inference)
- [x] **Phase 2: Groq Integration** (1/2 plans) - Add Groq (genuinely free ~14K req/day, Llama 70B + GPT-OSS 120B) (completed 2026-03-02)
- [x] **Phase 3: Mistral Integration** - Add Mistral via two-key architecture (Codestral free endpoint + La Plateforme critic-only) (completed 2026-03-02)
- [x] **Phase 4: SambaNova Integration** - Add SambaNova (credits-based) with request transforms for temp clamp, stream=False for tools, and strict removal (completed 2026-03-02)
- [x] **Phase 5: Together AI Integration** (2 plans) - Add Together AI (credits-based, high-context Llama 4 Scout / DeepSeek V3) (completed 2026-03-02)
- [ ] **Phase 6: Routing + Config Finalization** (2 plans) - Smart FREE_ROUTING rotation across all providers, provider-diverse fallback chain, GEMINI_FREE_TIER and OPENROUTER_FREE_ONLY config flags

## Phase Details

### Phase 1: Foundation + Cerebras
**Goal**: The provider registry supports all new provider types with correct free-model cost tracking, and Cerebras is fully operational as a primary/fallback model
**Depends on**: Nothing (first phase)
**Requirements**: CERE-01, CERE-02, CERE-03, CERE-04, INFR-01, INFR-02, INFR-05, TEST-01, TEST-02
**Success Criteria** (what must be TRUE):
  1. Agent42 starts without error when CEREBRAS_API_KEY is set and when it is absent
  2. A task routed to a Cerebras model incurs $0 in SpendingTracker — no false spend-cap trips
  3. All 5 new ProviderType enum values exist and the registry can construct a client for Cerebras given a valid key
  4. SpendingTracker free-model detection works for Cerebras model IDs without relying on `or-free-` prefix or `:free` suffix naming
  5. Unit tests for Cerebras ProviderSpec, ModelSpec registration, and $0 pricing pass
**Plans:** 2/2 plans complete
Plans:
- [x] 01-01-PLAN.md — Register Cerebras provider + enum plumbing + $0 pricing + config (DONE 2026-03-02)
- [ ] 01-02-PLAN.md — Unit tests for Cerebras registration and SpendingTracker pricing

### Phase 2: Groq Integration
**Goal**: Groq is registered as a second genuinely-free provider with three model options and accurate $0 cost tracking
**Depends on**: Phase 1
**Requirements**: GROQ-01, GROQ-02, GROQ-03, GROQ-04
**Success Criteria** (what must be TRUE):
  1. Agent42 starts without error when GROQ_API_KEY is set and when it is absent
  2. A task routed to a Groq model incurs $0 in SpendingTracker
  3. Three Groq ModelSpec entries exist (llama-70b, gpt-oss-120b, llama-8b) with correct context windows and throughput metadata
  4. Unit tests for Groq ProviderSpec, ModelSpec registration, and $0 pricing pass
**Plans:** 2/2 plans complete
Plans:
- [x] 02-01-PLAN.md — Register Groq provider + 3 ModelSpecs + $0 pricing + config (DONE 2026-03-02)
- [ ] 02-02-PLAN.md — Unit tests for Groq registration and SpendingTracker pricing

### Phase 3: Mistral Integration
**Goal**: Mistral's two-key architecture is registered — Codestral as a free code-specialist endpoint and La Plateforme as a rate-limited critic — with correct pricing and safeguards against primary-slot assignment
**Depends on**: Phase 2
**Requirements**: MIST-01, MIST-02, MIST-03, MIST-04, MIST-05
**Success Criteria** (what must be TRUE):
  1. Agent42 starts without error when either or both Mistral API keys are absent
  2. Codestral (MISTRAL_CODESTRAL provider) and La Plateforme (MISTRAL provider) are registered as separate providers with independent base URLs and API keys
  3. codestral-latest is classified ModelTier.FREE with $0 SpendingTracker pricing; mistral-large-latest and mistral-small-latest are classified ModelTier.CHEAP with actual pricing
  4. Unit tests for both Mistral ProviderSpec registrations and pricing entries pass
**Plans**: 1/2 plans
Plans:
- [x] 03-01-PLAN.md — Register 2 Mistral ProviderSpecs (MISTRAL + MISTRAL_CODESTRAL) + 3 ModelSpecs + pricing + config (DONE 2026-03-02)
- [ ] 03-02-PLAN.md — Unit tests for Mistral dual-provider registration and SpendingTracker pricing

### Phase 4: SambaNova Integration
**Goal**: SambaNova is registered as a credits-based provider with all three request transforms active — temperature clamping, stream=False for tools, and strict removal — preventing the known failure modes
**Depends on**: Phase 3
**Requirements**: SAMB-01, SAMB-02, SAMB-03, SAMB-04, SAMB-05, INFR-03, TEST-03
**Success Criteria** (what must be TRUE):
  1. Agent42 starts without error when SAMBANOVA_API_KEY is absent
  2. A request sent to SambaNova with temperature > 1.0 is clamped to 1.0 before transmission
  3. A request with tools present and provider SAMBANOVA has stream=False enforced regardless of caller setting
  4. Tool definitions sent to SambaNova have strict field removed or set to false
  5. Unit tests for all three request transforms pass (temp clamp, stream=False, strict removal)
**Plans**: TBD

### Phase 5: Together AI Integration
**Goal**: Together AI is registered as a credits-based provider with verified model IDs and accurate pricing documentation that correctly labels it as credits-required (not free)
**Depends on**: Phase 4
**Requirements**: TOGR-01, TOGR-02, TOGR-03
**Success Criteria** (what must be TRUE):
  1. Agent42 starts without error when TOGETHER_API_KEY is absent
  2. Two Together AI ModelSpec entries exist (together-deepseek-v3, together-llama-70b) classified as ModelTier.CHEAP
  3. SpendingTracker has credit-based pricing for Together AI models (not $0 — this is a credits provider)
  4. Unit tests for Together AI ProviderSpec, ModelSpec, and pricing entries pass
**Plans:** 2/2 plans complete
Plans:
- [ ] 05-01-PLAN.md — Register Together AI ProviderSpec + 2 ModelSpecs + pricing + config
- [ ] 05-02-PLAN.md — Unit tests for Together AI registration and SpendingTracker pricing

### Phase 6: Routing + Config Finalization
**Goal**: All providers are wired into FREE_ROUTING with smart rotation, the fallback chain is provider-diverse, and GEMINI_FREE_TIER and OPENROUTER_FREE_ONLY flags give users control over billing exposure
**Depends on**: Phase 5
**Requirements**: ROUT-01, ROUT-02, ROUT-03, ROUT-04, ROUT-05, CONF-01, CONF-02, CONF-03, CONF-04, INFR-04, TEST-04, TEST-05, TEST-06
**Success Criteria** (what must be TRUE):
  1. Coding and debugging task types use Cerebras as primary and Codestral as critic in FREE_ROUTING
  2. Research and content task types use Groq models as primary in FREE_ROUTING
  3. The fallback chain cycles through different providers before retrying the same provider
  4. Setting GEMINI_FREE_TIER=false excludes Gemini from FREE_ROUTING and free fallback candidates
  5. Setting OPENROUTER_FREE_ONLY=true restricts OpenRouter calls to :free-suffix models only
  6. All new API key variables and config flags are in Settings dataclass, from_env(), and .env.example with accurate free-vs-credits documentation
**Plans:** 1/2 plans executed
Plans:
- [ ] 06-01-PLAN.md — Config flags + FREE_ROUTING updates + provider-diverse fallback + CHEAP fallback + health check extension
- [ ] 06-02-PLAN.md — Unit tests for routing updates, config flags, fallback diversity, and multi-provider integration

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5 → 6

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Foundation + Cerebras | 2/2 | Complete   | 2026-03-02 |
| 2. Groq Integration | 2/2 | Complete   | 2026-03-02 |
| 3. Mistral Integration | 2/2 | Complete   | 2026-03-02 |
| 4. SambaNova Integration | 2/2 | Complete   | 2026-03-02 |
| 5. Together AI Integration | 2/2 | Complete   | 2026-03-02 |
| 6. Routing + Config Finalization | 1/2 | In Progress|  |
