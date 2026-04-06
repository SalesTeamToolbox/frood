# Requirements: Agent42 v6.0 Dashboard Unification

**Defined:** 2026-04-02
**Core Value:** Agent42 must always provide reliable intelligence services to Claude Code and Paperclip harnesses, with tiered provider routing ensuring no single provider outage stops the platform.

## v1 Requirements

Requirements for this milestone. Each maps to roadmap phases.

### Paperclip Integration Mode

- [ ] **PAPERCLIP-01**: When Paperclip is active, integrate workspace coding terminal into Paperclip dashboard
- [ ] **PAPERCLIP-02**: When Paperclip is active, integrate sandboxed apps into Paperclip dashboard
- [ ] **PAPERCLIP-03**: When Paperclip is active, integrate tools and skills into Paperclip dashboard
- [ ] **PAPERCLIP-04**: Retain settings management in Paperclip dashboard
- [ ] **PAPERCLIP-05**: Remove redundant Agent42 dashboard components when Paperclip is active

### Standalone Mode

- [ ] **STANDALONE-01**: When running without Paperclip (Claude Code only), provide simplified dashboard for settings management
- [ ] **STANDALONE-02**: When running without Paperclip, provide tool/skill management interface
- [ ] **STANDALONE-03**: When running without Paperclip, provide basic agent monitoring capabilities
- [ ] **STANDALONE-04**: When running without Paperclip, provide provider configuration UI

### Provider UI Updates

- [ ] **PROVIDER-01**: Remove all StrongWall.ai references from dashboard UI
- [ ] **PROVIDER-02**: Update provider configuration UI to match current provider structure (Claude Code Subscription, Synthetic.new, Anthropic, OpenRouter)
- [ ] **PROVIDER-03**: Display dynamic model discovery from Synthetic.new in provider selection UI
- [ ] **PROVIDER-04**: Show provider status and connectivity in dashboard
- [ ] **PROVIDER-05**: Enable model selection from dynamically discovered Synthetic.new models

### Unified Agent Management

- [ ] **AGENT-01**: Single interface to monitor and control agents from both Agent42 and Paperclip
- [ ] **AGENT-02**: Unified view of agent performance metrics across both systems
- [ ] **AGENT-03**: Consistent agent configuration interface regardless of deployment mode
- [ ] **AGENT-04**: Shared agent templates that work in both Paperclip and standalone modes

### Settings Consolidation

- [ ] **SETTINGS-01**: Streamlined settings management that works in both Paperclip and standalone modes
- [ ] **SETTINGS-02**: Unified API key management interface
- [ ] **SETTINGS-03**: Consistent memory and learning configuration across both modes
- [ ] **SETTINGS-04**: Shared tool and skill enable/disable controls

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Advanced Features

- **ADV-01**: Real-time collaboration features in Paperclip-integrated mode
- **ADV-02**: Cross-node monitoring and management
- **ADV-03**: Advanced analytics and reporting dashboard
- **ADV-04**: Custom dashboard widgets and layouts

### Mobile Support

- **MOBILE-01**: Responsive dashboard design for mobile devices
- **MOBILE-02**: Mobile-specific features and optimizations
- **MOBILE-03**: Offline capabilities for standalone mode

## Out of Scope

| Feature | Reason |
| ------- | ------ |
| Full Agent42 dashboard when Paperclip is active | Redundant UI, maintenance liability; use native Paperclip UI slots instead |
| Agent template management in standalone mode | Paperclip handles orchestration; Agent42 focuses on intelligence layer |
| Complex workflow orchestration in standalone mode | Paperclip's responsibility; Agent42 provides tools/skills |
| Real-time collaborative editing | High complexity, out of scope for v1 |
| Native mobile app | Web-first approach; mobile later if needed |

## Traceability

| Requirement | Phase | Status |
| ----------- | ----- | ------ |
| PAPERCLIP-01 | TBD | Pending |
| PAPERCLIP-02 | TBD | Pending |
| PAPERCLIP-03 | TBD | Pending |
| PAPERCLIP-04 | TBD | Pending |
| PAPERCLIP-05 | TBD | Pending |
| STANDALONE-01 | TBD | Pending |
| STANDALONE-02 | TBD | Pending |
| STANDALONE-03 | TBD | Pending |
| STANDALONE-04 | TBD | Pending |
| PROVIDER-01 | TBD | Pending |
| PROVIDER-02 | TBD | Pending |
| PROVIDER-03 | TBD | Pending |
| PROVIDER-04 | TBD | Pending |
| PROVIDER-05 | TBD | Pending |
| AGENT-01 | TBD | Pending |
| AGENT-02 | TBD | Pending |
| AGENT-03 | TBD | Pending |
| AGENT-04 | TBD | Pending |
| SETTINGS-01 | TBD | Pending |
| SETTINGS-02 | TBD | Pending |
| SETTINGS-03 | TBD | Pending |
| SETTINGS-04 | TBD | Pending |

**Coverage:**

- v1 requirements: 24 total
- Mapped to phases: 0
- Unmapped: 24 ✓

---
*Requirements defined: 2026-04-02*
*Last updated: 2026-04-02 — v6.0 Dashboard Unification requirements*