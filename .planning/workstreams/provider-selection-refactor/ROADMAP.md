# Roadmap: Provider Selection Refactor

## Milestone: v5.0 Provider Selection Refactor

**Goal:** Modernize Agent42's provider selection system with Claude Code Subscription as the primary provider, properly integrated Synthetic.new as the reliable fallback, and dynamic model discovery for all providers.

### Phases

- [ ] **Phase 32: Provider Selection Core** — Refactor core provider selection logic to prioritize Claude Code Subscription
- [ ] **Phase 33: Synthetic.new Integration** — Implement dynamic model discovery and integration with Synthetic.new API
- [ ] **Phase 34: System Simplification** — Remove StrongWall references and simplify provider routing system
- [ ] **Phase 35: Paperclip Integration** — Update Paperclip integration to work with simplified provider system

### Phase 32: Provider Selection Core

**Goal**: Refactor Agent42's core provider selection to prioritize Claude Code Subscription with Synthetic.new as fallback
**Depends on**: Nothing (first phase of this milestone)
**Requirements**: PROVIDER-01, PROVIDER-02, PROVIDER-03, PROVIDER-04, PROVIDER-05, PROVIDER-06
**Success Criteria** (what must be TRUE):

1. Claude Code Subscription is the default provider for all agent executions when available
2. Synthetic.new is used as fallback when Claude Code Subscription is unavailable or task violates CC Subscription TOS
3. All StrongWall.ai references and integration code have been removed from the codebase
4. Provider selection follows the hierarchy: Claude Code Subscription → Synthetic.new → Other API keys
5. Provider selection bridge reports which provider was used in callback response for budget tracking

### Phase 33: Synthetic.new Integration

**Goal**: Implement dynamic model discovery for Synthetic.new API and integrate it properly
**Depends on**: Phase 32
**Requirements**: SYNTHETIC-01, SYNTHETIC-02, SYNTHETIC-03, SYNTHETIC-04
**Success Criteria** (what must be TRUE):

1. Agent42 can dynamically discover available models from Synthetic.new API and cache them
2. Model list is refreshed every 24 hours or on demand via admin endpoint
3. Agent configuration allows selection from available Synthetic.new models
4. Synthetic.new API key is validated on startup with health check

### Phase 34: System Simplification

**Goal**: Remove complex L1/L2 tiered routing system and simplify provider configuration
**Depends on**: Phase 32
**Requirements**: SIMPLIFY-01, SIMPLIFY-02, SIMPLIFY-03, SIMPLIFY-04, SIMPLIFY-05
**Plans:** 1 plan
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
**Depends on**: Phase 32, Phase 33, Phase 34
**Requirements**: UI-01, UI-02, UI-03, UI-04
**Plans:** 2 plans
**Success Criteria** (what must be TRUE):

1. Paperclip plugin works correctly with the simplified provider selection system
2. Provider selection dashboard shows available models from Synthetic.new
3. Agent configuration UI allows selection from dynamically discovered models
4. Provider status dashboard shows Claude Code Subscription and Synthetic.new connectivity

Plans:

- [x] 35-01-PLAN.md — Server-side: Pydantic models, GET /sidecar/models endpoint, enhanced health endpoint, SYNTHETIC_API_KEY config, tests
- [x] 35-02-PLAN.md — Client-side: TypeScript types, client getModels() method, available-models data handler, enhanced ProviderHealthWidget

## Progress

| Phase | Plans Complete | Status | Completed |
| ----- | -------------- | ------ | --------- |
| 32. Provider Selection Core | 1/1 | Planned | 2026-04-01 |
| 33. Synthetic.new Integration | 1/1 | Planned | 2026-04-01 |
| 34. System Simplification | 1/1 | Complete | 2026-04-06 |
| 35. Paperclip Integration | 2/2 | Complete | 2026-04-06 |
