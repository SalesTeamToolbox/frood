# Requirements: Agent42 — Agent LLM Control

**Defined:** 2026-03-06
**Core Value:** Agent42 runs agents reliably with tiered provider routing (L1 workhorse -> free fallback -> L2 premium)

## v1.3 Requirements

Requirements for milestone v1.3. Each maps to roadmap phases.

### Provider Integration

- [ ] **PROV-01**: User can configure StrongWall API key and have it used as L1 provider
- [ ] **PROV-02**: Agent42 handles non-streaming responses from StrongWall without errors
- [ ] **PROV-03**: Chat messages from StrongWall display with simulated streaming UX
- [ ] **PROV-04**: StrongWall health check detects availability and queue delays

### Tier Architecture

- [ ] **TIER-01**: Model routing supports L1 (workhorse) and L2 (premium) tier concepts
- [ ] **TIER-02**: StrongWall is the default L1 provider when API key is configured
- [ ] **TIER-03**: Gemini serves as default L2 provider
- [ ] **TIER-04**: OpenRouter paid models available as L2 when balance present and not locked to FREE
- [ ] **TIER-05**: Fallback chain operates as StrongWall -> Free providers -> L2 premium

### Agent Configuration

- [ ] **CONF-01**: Settings page has LLM Routing section with global L1/L2/critic/fallback defaults
- [ ] **CONF-02**: Agents page shows per-agent routing override controls (primary, critic, fallback)
- [ ] **CONF-03**: Per-agent overrides inherit global defaults, only store differences
- [ ] **CONF-04**: Configuration persists across restarts (saved to config file)
- [ ] **CONF-05**: Available provider/model options populated dynamically from configured API keys

### Routing Overhaul

- [ ] **ROUTE-01**: Routing chain updated to check agent-level overrides first (highest priority)
- [ ] **ROUTE-02**: OR free models no longer default for critical tasks (coding, debugging, etc.)
- [ ] **ROUTE-03**: Existing free providers (Cerebras, Groq, Codestral) remain as fallback tier

## Future Requirements

Deferred to future milestones. Tracked but not in current roadmap.

### Additional StrongWall Models

- **PROV-05**: Support additional models as StrongWall adds them beyond Kimi K2.5
- **PROV-06**: Model selection dropdown for StrongWall when multiple models available

### Advanced Routing

- **ROUTE-04**: A/B testing between L1 and L2 models with quality comparison
- **ROUTE-05**: Auto-escalation from L1 to L2 based on task complexity assessment

## Out of Scope

| Feature | Reason |
|---------|--------|
| StrongWall Anthropic-compatible API | OpenAI-compatible endpoint is sufficient; both hit same backend |
| Custom fine-tuned model hosting | StrongWall serves pre-trained models only |
| Per-task-type model selection UI | Per-agent override covers this; task-type routing stays internal |
| Removing existing free providers | Cerebras/Groq/etc. remain as fallback tier |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| PROV-01 | Phase 16 | Pending |
| PROV-02 | Phase 16 | Pending |
| PROV-03 | Phase 20 | Pending |
| PROV-04 | Phase 16 | Pending |
| TIER-01 | Phase 17 | Pending |
| TIER-02 | Phase 17 | Pending |
| TIER-03 | Phase 17 | Pending |
| TIER-04 | Phase 17 | Pending |
| TIER-05 | Phase 17 | Pending |
| CONF-01 | Phase 19 | Pending |
| CONF-02 | Phase 19 | Pending |
| CONF-03 | Phase 18 | Pending |
| CONF-04 | Phase 18 | Pending |
| CONF-05 | Phase 18 | Pending |
| ROUTE-01 | Phase 17 | Pending |
| ROUTE-02 | Phase 17 | Pending |
| ROUTE-03 | Phase 17 | Pending |

**Coverage:**
- v1.3 requirements: 16 total
- Mapped to phases: 16
- Unmapped: 0

---
*Requirements defined: 2026-03-06*
*Last updated: 2026-03-06 after roadmap creation*
