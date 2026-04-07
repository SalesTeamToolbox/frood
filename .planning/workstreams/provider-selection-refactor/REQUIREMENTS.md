# Requirements: Agent42 v5.0 Provider Selection Refactor

**Defined:** 2026-04-01
**Core Value:** Agent42 must always be able to run agents reliably, with tiered provider routing ensuring no single provider outage stops the platform.

## v1 Requirements

Requirements for this milestone. Each maps to roadmap phases.

### Provider Selection

- [ ] **PROVIDER-01**: Claude Code Subscription is the primary provider for all agent executions
- [ ] **PROVIDER-02**: Synthetic.new API is the fallback provider when Claude Code Subscription is unavailable or task violates CC Subscription TOS
- [ ] **PROVIDER-03**: Remove all StrongWall.ai references and integration from the codebase
- [ ] **PROVIDER-04**: Other LLM providers (Anthropic, OpenRouter, etc.) are used only when CC Subscription and Synthetic.new are unavailable
- [ ] **PROVIDER-05**: Provider selection follows hierarchy: Claude Code Subscription → Synthetic.new → Other API keys
- [ ] **PROVIDER-06**: Provider selection bridge reports which provider was used in callback response for budget tracking

### Synthetic.new Integration

- [ ] **SYNTHETIC-01**: Dynamic model discovery pulls available models from Synthetic.new API and caches them
- [ ] **SYNTHETIC-02**: Model list is refreshed every 24 hours or on demand via admin endpoint
- [ ] **SYNTHETIC-03**: Agent configuration allows selection from available Synthetic.new models
- [ ] **SYNTHETIC-04**: Synthetic.new API key validation on startup with health check

### Provider System Simplification

- [x] **SIMPLIFY-01**: Remove complex L1/L2 tiered routing system
- [x] **SIMPLIFY-02**: Eliminate task category to provider mapping (engineer/researcher/writer/analyst)
- [x] **SIMPLIFY-03**: Consolidate provider configuration into single unified system
- [x] **SIMPLIFY-04**: Remove provider health checks for unused providers
- [x] **SIMPLIFY-05**: Simplify AgentRuntime environment building logic

### User Interface

- [ ] **UI-01**: Update Paperclip plugin to work with simplified provider selection system
- [x] **UI-02**: Provider selection dashboard shows available models from Synthetic.new
- [x] **UI-03**: Agent configuration UI allows selection from dynamically discovered models
- [x] **UI-04**: Provider status dashboard shows Claude Code Subscription and Synthetic.new connectivity

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Performance & Monitoring

- **PERF-01**: Track model response times and reliability for intelligent selection
- **PERF-02**: Cost optimization based on cost/performance ratio for different task types

### Advanced Features

- **ADV-01**: Model fallback within provider based on task type and model capabilities
- **ADV-02**: Automatic provider switching based on performance metrics

## Out of Scope

| Feature | Reason |
| ------- | ------ |
| TypeScript rewrite of Agent42 sidecar | Agent42's value (ONNX, Qdrant, asyncio) is Python-native; rewriting wastes months |
| Agent42 plugin managing Paperclip budgets | Budget authority belongs to Paperclip; dual accounting creates drift |
| Full Agent42 dashboard embedded via iframe | Maintenance liability; use native Paperclip UI slots instead |
| Plugin storing full conversation transcripts | Transcripts live in Paperclip's DB; duplicating creates bloat and consistency issues |
| Agent42 reading Paperclip's PostgreSQL directly | Creates tight schema coupling; trust the AdapterExecutionContext payload |
| Per-company plugin instances | Plugins are installation-global by design; use per-company config in plugin_state |

## Traceability

| Requirement | Phase | Status |
| ----------- | ----- | ------ |
| PROVIDER-01 | Phase 32 | Pending |
| PROVIDER-02 | Phase 32 | Pending |
| PROVIDER-03 | Phase 32 | Pending |
| PROVIDER-04 | Phase 32 | Pending |
| PROVIDER-05 | Phase 32 | Pending |
| PROVIDER-06 | Phase 32 | Pending |
| SYNTHETIC-01 | Phase 33 | Pending |
| SYNTHETIC-02 | Phase 33 | Pending |
| SYNTHETIC-03 | Phase 33 | Pending |
| SYNTHETIC-04 | Phase 33 | Pending |
| SIMPLIFY-01 | Phase 34 | Complete |
| SIMPLIFY-02 | Phase 34 | Complete |
| SIMPLIFY-03 | Phase 34 | Complete |
| SIMPLIFY-04 | Phase 34 | Complete |
| SIMPLIFY-05 | Phase 34 | Complete |
| UI-01 | Phase 35 | Pending |
| UI-02 | Phase 35 | Complete |
| UI-03 | Phase 35 | Complete |
| UI-04 | Phase 35 | Complete |

**Coverage:**

- v1 requirements: 16 total
- Mapped to phases: 16
- Unmapped: 0 ✓

---
*Requirements defined: 2026-04-01*
*Last updated: 2026-04-06 — UI-02, UI-03, UI-04 marked complete (35-02)*
