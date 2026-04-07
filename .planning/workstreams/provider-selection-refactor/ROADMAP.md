# Roadmap: Provider Selection Refactor

## Milestone: v5.0 Provider Selection Refactor

**Goal:** Simplify Agent42's provider selection system — remove dead L1/L2 config, consolidate routing into TieredRoutingBridge, and wire Paperclip plugin to the simplified provider endpoints.

**Status:** Complete (2026-04-06)

### Phases

- [x] **Phase 34: System Simplification** — Remove dead L1/L2 config fields and simplify provider routing system
- [x] **Phase 35: Paperclip Integration** — Wire Paperclip plugin to simplified provider endpoints

### Superseded Phases

Phases 32 and 33 were planned when the roadmap assumed Claude Code Subscription and Synthetic.new would be integrated. Neither provider was adopted. The existing provider infrastructure (Zen free tier, OpenRouter, Anthropic, OpenAI via TieredRoutingBridge) already satisfies the core value: reliable agent execution with tiered fallback.

- ~~Phase 32: Provider Selection Core~~ — CC Subscription never adopted; StrongWall already removed; provider hierarchy already works via TieredRoutingBridge
- ~~Phase 33: Synthetic.new Integration~~ — Synthetic.new never adopted; dynamic model discovery already works via Zen API refresh

### Phase 34: System Simplification

**Goal**: Remove complex L1/L2 tiered routing system and simplify provider configuration
**Requirements**: SIMPLIFY-01, SIMPLIFY-02, SIMPLIFY-03, SIMPLIFY-04, SIMPLIFY-05
**Success Criteria** (what must be TRUE):

1. Complex L1/L2 tiered routing system has been removed from the codebase
2. Task category to provider mapping (engineer/researcher/writer/analyst) has been eliminated
3. Provider configuration has been consolidated into a single unified system
4. Provider health checks for unused providers have been removed
5. AgentRuntime environment building logic has been simplified

Plans:

- [x] 34-01-PLAN.md — Remove dead L1/L2 config fields from Settings and .env.example

### Phase 35: Paperclip Integration

**Goal**: Update Paperclip integration to work with the simplified provider selection system
**Requirements**: UI-01, UI-02, UI-03, UI-04
**Success Criteria** (what must be TRUE):

1. Paperclip plugin works correctly with the simplified provider selection system
2. Provider selection dashboard shows available models
3. Agent configuration UI allows selection from dynamically discovered models
4. Provider status dashboard shows provider connectivity

Plans:

- [x] 35-01-PLAN.md — Server-side: Pydantic models, GET /sidecar/models endpoint, enhanced health endpoint, SYNTHETIC_API_KEY config, tests
- [x] 35-02-PLAN.md — Client-side: TypeScript types, client getModels() method, available-models data handler, enhanced ProviderHealthWidget

## Progress

| Phase | Plans Complete | Status | Completed |
| ----- | -------------- | ------ | --------- |
| 34. System Simplification | 1/1 | Complete | 2026-04-06 |
| 35. Paperclip Integration | 2/2 | Complete | 2026-04-06 |

**Milestone complete: 2026-04-07**
