# Requirements: Agent42 v5.0 Provider Selection Refactor

**Defined:** 2026-04-01
**Closed:** 2026-04-07
**Core Value:** Agent42 must always be able to run agents reliably, with tiered provider routing ensuring no single provider outage stops the platform.

## v1 Requirements

### Provider Selection (Superseded)

Phases 32/33 assumed Claude Code Subscription and Synthetic.new adoption. Neither provider was adopted. The existing TieredRoutingBridge with Zen/OpenRouter/Anthropic/OpenAI already satisfies the core value.

- ~~**PROVIDER-01**: Claude Code Subscription is the primary provider~~ — Superseded: CC Subscription not adopted
- ~~**PROVIDER-02**: Synthetic.new API is the fallback provider~~ — Superseded: Synthetic.new not adopted
- [x] **PROVIDER-03**: Remove all StrongWall.ai references and integration from the codebase — Already done prior to this milestone
- ~~**PROVIDER-04**: Other LLM providers used only when CC Subscription and Synthetic.new unavailable~~ — Superseded: current hierarchy (Zen free → OpenRouter → Anthropic → OpenAI) is the production system
- ~~**PROVIDER-05**: Provider selection follows hierarchy: CC Subscription → Synthetic.new → Other~~ — Superseded: hierarchy is Zen → OpenRouter → Anthropic → OpenAI via TieredRoutingBridge
- ~~**PROVIDER-06**: Provider selection bridge reports which provider was used~~ — Superseded: TieredRoutingBridge.resolve() already returns RoutingDecision with provider field

### Synthetic.new Integration (Superseded)

Synthetic.new was never adopted. Dynamic model discovery already works via Zen API refresh.

- ~~**SYNTHETIC-01**: Dynamic model discovery from Synthetic.new API~~ — Superseded
- ~~**SYNTHETIC-02**: Model list refreshed every 24 hours~~ — Superseded (Zen refresh already exists)
- ~~**SYNTHETIC-03**: Agent configuration allows Synthetic.new model selection~~ — Superseded
- ~~**SYNTHETIC-04**: Synthetic.new API key validation on startup~~ — Superseded

### Provider System Simplification

- [x] **SIMPLIFY-01**: Remove complex L1/L2 tiered routing system
- [x] **SIMPLIFY-02**: Eliminate task category to provider mapping (engineer/researcher/writer/analyst)
- [x] **SIMPLIFY-03**: Consolidate provider configuration into single unified system
- [x] **SIMPLIFY-04**: Remove provider health checks for unused providers
- [x] **SIMPLIFY-05**: Simplify AgentRuntime environment building logic

### User Interface

- [x] **UI-01**: Update Paperclip plugin to work with simplified provider selection system
- [x] **UI-02**: Provider selection dashboard shows available models
- [x] **UI-03**: Agent configuration UI allows selection from dynamically discovered models
- [x] **UI-04**: Provider status dashboard shows provider connectivity

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
| PROVIDER-01 | — | Superseded |
| PROVIDER-02 | — | Superseded |
| PROVIDER-03 | — | Already done |
| PROVIDER-04 | — | Superseded |
| PROVIDER-05 | — | Superseded |
| PROVIDER-06 | — | Superseded |
| SYNTHETIC-01 | — | Superseded |
| SYNTHETIC-02 | — | Superseded |
| SYNTHETIC-03 | — | Superseded |
| SYNTHETIC-04 | — | Superseded |
| SIMPLIFY-01 | Phase 34 | Complete |
| SIMPLIFY-02 | Phase 34 | Complete |
| SIMPLIFY-03 | Phase 34 | Complete |
| SIMPLIFY-04 | Phase 34 | Complete |
| SIMPLIFY-05 | Phase 34 | Complete |
| UI-01 | Phase 35 | Complete |
| UI-02 | Phase 35 | Complete |
| UI-03 | Phase 35 | Complete |
| UI-04 | Phase 35 | Complete |

---

*Requirements defined: 2026-04-01*
*Milestone closed: 2026-04-07 — Phases 32/33 superseded (providers not adopted), Phases 34/35 complete*
