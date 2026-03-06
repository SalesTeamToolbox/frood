# Roadmap: Agent42 v1.3 — Agent LLM Control

## Overview

Restructure Agent42's model routing around L1 (workhorse) and L2 (premium) tiers, integrate StrongWall.ai as the L1 provider, add per-agent routing configuration through the dashboard, and deliver simulated streaming for non-streaming providers. Five phases progressing from provider integration through tier architecture, backend configuration, dashboard UI, and finally streaming simulation.

## Phases

**Phase Numbering:**
- Continues from v1.2 (phases 13-15)
- Integer phases (16, 17, ...): Planned milestone work
- Decimal phases (16.1, 16.2): Urgent insertions (marked with INSERTED)

- [x] **Phase 16: StrongWall Provider** - Integrate StrongWall.ai as OpenAI-compatible provider with health check and non-streaming response handling
- [ ] **Phase 17: Tier Routing Architecture** - Restructure model_router.py around L1/L2 tiers with new fallback chain
- [ ] **Phase 18: Agent Config Backend** - Per-agent routing config storage, API endpoints, and inheritance from global defaults
- [ ] **Phase 19: Agent Config Dashboard** - Settings page LLM Routing section and Agents page per-agent override UI
- [ ] **Phase 20: Streaming Simulation** - Simulated streaming for chat display from non-streaming providers

## Phase Details

### Phase 16: StrongWall Provider
**Goal**: Agent42 can use StrongWall.ai (Kimi K2.5) as a working LLM provider for agent tasks
**Depends on**: Nothing (first phase in v1.3)
**Requirements**: PROV-01, PROV-02, PROV-04
**Success Criteria** (what must be TRUE):
  1. User sets STRONGWALL_API_KEY in .env and Agent42 starts without errors, recognizing StrongWall as an available provider
  2. Agent tasks dispatched to StrongWall receive complete, correctly parsed responses (including tool calls) without streaming-related errors
  3. StrongWall health check endpoint reports availability status and detects when the API is unreachable or returning errors
  4. Agent42 without STRONGWALL_API_KEY configured continues to operate with existing providers (graceful degradation)
**Plans**: 2 plans

Plans:
- [x] 16-01-PLAN.md — Register StrongWall provider/model, enforce non-streaming for all requests
- [x] 16-02-PLAN.md — Provider health check polling, flat-rate cost tracking, dashboard integration

### Phase 17: Tier Routing Architecture
**Goal**: Model routing operates on L1/L2 tier concepts with StrongWall as default L1, Gemini/OR-paid as L2, and existing free providers as fallback
**Depends on**: Phase 16
**Requirements**: TIER-01, TIER-02, TIER-03, TIER-04, TIER-05, ROUTE-01, ROUTE-02, ROUTE-03
**Success Criteria** (what must be TRUE):
  1. When StrongWall is configured, agents default to StrongWall (L1) for primary model selection across all task types
  2. When StrongWall is unavailable, routing falls through to free providers (Cerebras, Groq, Codestral) before escalating to L2 premium (Gemini, OR paid)
  3. OpenRouter paid models are available as L2 when OR balance is present and OPENROUTER_FREE_ONLY is not set
  4. Critical task types (coding, debugging, app_create) no longer default to OR free models -- they use L1 or established free providers
  5. Users without StrongWall API key retain existing routing behavior (backward compatible)
**Plans**: TBD

Plans:
- [ ] 17-01: L1/L2 tier structure and resolution chain
- [ ] 17-02: Fallback chain and backward compatibility

### Phase 18: Agent Config Backend
**Goal**: Per-agent routing overrides are stored, served via API, and inherit from global defaults
**Depends on**: Phase 17
**Requirements**: CONF-03, CONF-04, CONF-05
**Success Criteria** (what must be TRUE):
  1. API endpoint returns per-agent routing config (primary, critic, fallback models) that correctly merges agent-specific overrides with global defaults
  2. Agent routing config persists across server restarts (saved to disk)
  3. Available model/provider options returned by API reflect only providers with configured API keys (no dead options)
**Plans**: TBD

Plans:
- [ ] 18-01: Config storage, API endpoints, and dynamic provider enumeration

### Phase 19: Agent Config Dashboard
**Goal**: Users can view and modify LLM routing through the dashboard -- global defaults on Settings page, per-agent overrides on Agents page
**Depends on**: Phase 18
**Requirements**: CONF-01, CONF-02
**Success Criteria** (what must be TRUE):
  1. Settings page shows LLM Routing section where user can set global default L1, L2, critic, and fallback providers/models
  2. Agents page shows per-agent routing controls where user can override primary, critic, and fallback models for individual agents
  3. Changes made in the UI take effect on subsequent agent dispatches without requiring server restart
**Plans**: TBD

Plans:
- [ ] 19-01: Settings page LLM Routing section
- [ ] 19-02: Agents page per-agent override controls

### Phase 20: Streaming Simulation
**Goal**: Chat messages from non-streaming providers (StrongWall) display with progressive token reveal, matching the UX of streaming providers
**Depends on**: Phase 16, Phase 19
**Requirements**: PROV-03
**Success Criteria** (what must be TRUE):
  1. Chat messages from StrongWall appear token-by-token in the dashboard chat UI, not as a single block after full response
  2. Background agent tasks (non-chat) continue to use standard non-streaming handling without simulated streaming overhead
**Plans**: TBD

Plans:
- [ ] 20-01: Simulated streaming implementation and hybrid context handling

## Progress

**Execution Order:**
Phases execute in numeric order: 16 -> 17 -> 18 -> 19 -> 20

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 16. StrongWall Provider | 2/2 | Complete | 2026-03-06 |
| 17. Tier Routing Architecture | 0/2 | Not started | - |
| 18. Agent Config Backend | 0/1 | Not started | - |
| 19. Agent Config Dashboard | 0/2 | Not started | - |
| 20. Streaming Simulation | 0/1 | Not started | - |

---
*Roadmap created: 2026-03-06*
*Last updated: 2026-03-06 (16-02 complete, Phase 16 done)*
