# Roadmap: Dashboard Unification

## Milestone: v6.0 Dashboard Unification

**Goal:** Unify Agent42's dashboard experience for both standalone Claude Code integration and Paperclip orchestration, with simplified provider management and integrated workspace features.

### Phases

- [x] **Phase 36: Paperclip Integration Core** — Integrate workspace features into Paperclip dashboard (COMPLETE)
- [x] **Phase 37: Standalone Dashboard** — Create simplified dashboard for standalone mode (COMPLETE)
- [x] **Phase 38: Provider UI Updates** — Update provider configuration UI to match current structure (COMPLETE)
- [x] **Phase 39: Unified Agent Management** — Single interface for agent monitoring and control (COMPLETE)
- [x] **Phase 40: Settings Consolidation** — Streamlined settings management across both modes (completed 2026-04-05)

### Phase 36: Paperclip Integration Core

**Goal**: Integrate workspace coding terminal, sandboxed apps, tools and skills into Paperclip dashboard
**Depends on**: Nothing (first phase of this milestone)
**Requirements**: PAPERCLIP-01, PAPERCLIP-02, PAPERCLIP-03, PAPERCLIP-04, PAPERCLIP-05
**Plans:** 3 plans

Plans:
- [x] 36-01-PLAN.md — Contracts + Backend: TypeScript types/client/manifest + sidecar endpoints + dashboard gate (COMPLETE: 839240e, df6f4cf, b27de3b)
- [x] 36-02-PLAN.md — Worker + UI: Worker handlers + 5 new React components + plugin build (COMPLETE: 529c1be, f2fd7c7, 2266a84)
- [x] 36-03-PLAN.md — Tests: Python sidecar tests + TypeScript manifest/worker tests (COMPLETE: d252a3d, c098c72)

**Success Criteria** (what must be TRUE):

1. When Paperclip is active, workspace coding terminal is accessible within Paperclip dashboard
2. When Paperclip is active, sandboxed apps are accessible within Paperclip dashboard
3. When Paperclip is active, tools and skills are accessible within Paperclip dashboard
4. When Paperclip is active, redundant Agent42 dashboard components are removed
5. Settings management is available within Paperclip dashboard

### Phase 37: Standalone Dashboard

**Goal**: Create simplified dashboard for standalone mode (Claude Code only)
**Depends on**: Phase 36
**Requirements**: STANDALONE-01, STANDALONE-02, STANDALONE-03, STANDALONE-04
**Plans:** 2 plans

Plans:
- [ ] 37-01-PLAN.md — Backend standalone infrastructure: config field, CLI flag, guard decorator, /health update, tool source field
- [ ] 37-02-PLAN.md — Frontend mode awareness + enhanced tool/skill tables + test coverage

**Success Criteria** (what must be TRUE):

1. When running without Paperclip, simplified dashboard provides settings management
2. When running without Paperclip, tool/skill management interface is available
3. When running without Paperclip, basic agent monitoring capabilities are available
4. When running without Paperclip, provider configuration UI is available

### Phase 38: Provider UI Updates

**Goal**: Update provider configuration UI to match current provider structure
**Depends on**: Phase 36, Phase 37
**Requirements**: PROVIDER-01, PROVIDER-02, PROVIDER-03, PROVIDER-04, PROVIDER-05
**Plans:** 2/2 plans complete

Plans:

- [x] 38-01-PLAN.md — Backend: StrongWall cleanup + Synthetic models endpoint + provider status endpoint + tests (COMPLETE: ef1928d, dd27c4f)
- [x] 38-02-PLAN.md — Frontend: Providers tab restructure + dynamic agent model dropdown + visual verification (COMPLETE: 12639c8)

**Success Criteria** (what must be TRUE):

1. All StrongWall.ai references are removed from dashboard UI
2. Provider configuration UI matches current provider structure (Claude Code Subscription, Synthetic.new, Anthropic, OpenRouter)
3. Dynamic model discovery from Synthetic.new is displayed in provider selection UI
4. Provider status and connectivity are shown in dashboard
5. Model selection from dynamically discovered Synthetic.new models is enabled

### Phase 39: Unified Agent Management

**Goal**: Single interface to monitor and control agents from both Agent42 and Paperclip
**Depends on**: Phase 36, Phase 37
**Requirements**: AGENT-01, AGENT-02, AGENT-03, AGENT-04
**Plans:** 2 plans

Plans:
- [x] 39-01-PLAN.md — Backend: Unified agent endpoint with Paperclip proxy, embedded performance data, graceful degradation + tests (COMPLETE: 9e3b201, 7275511)
- [x] 39-02-PLAN.md — Frontend: Enhanced agent cards with source badges, sparklines, filter controls, stats row, template badges + tests (COMPLETE: 046ef45, 8453950, 2c915d4)

**Success Criteria** (what must be TRUE):

1. Single interface allows monitoring and control of agents from both Agent42 and Paperclip
2. Unified view of agent performance metrics across both systems
3. Consistent agent configuration interface regardless of deployment mode
4. Shared agent templates work in both Paperclip and standalone modes

### Phase 40: Settings Consolidation

**Goal**: Streamlined settings management that works in both Paperclip and standalone modes
**Depends on**: Phase 36, Phase 37, Phase 38, Phase 39
**Requirements**: SETTINGS-01, SETTINGS-02, SETTINGS-03, SETTINGS-04
**Plans:** 3/3 plans complete

Plans:
- [x] 40-01-PLAN.md — Backend: Source field on settings keys, delete-on-empty, LEARNING_ENABLED config, learning guards, memory purge endpoint, sidecar proxies + tests
- [x] 40-02-PLAN.md — Paperclip TypeScript: Updated types, client methods (toggleTool/Skill, memoryStats, purge), worker handlers, sidecar PATCH proxies (COMPLETE: 7a1e135, a0e5c82)
- [x] 40-03-PLAN.md — Frontend: Paperclip SettingsPage 6-tab expansion + standalone Memory & Learning tab + visual verification

**Success Criteria** (what must be TRUE):

1. Streamlined settings management works in both Paperclip and standalone modes
2. Unified API key management interface is available
3. Consistent memory and learning configuration across both modes
4. Shared tool and skill enable/disable controls work in both modes

## Progress

| Phase | Plans Complete | Status | Completed |
| ----- | -------------- | ------ | --------- |
| 36. Paperclip Integration Core | 3/3 | Complete | 2026-04-03 |
| 37. Standalone Dashboard | 2/2 | Complete | 2026-04-03 |
| 38. Provider UI Updates | 2/2 | Complete    | 2026-04-04 |
| 39. Unified Agent Management | 2/2 | Complete | 2026-04-05 |
| 40. Settings Consolidation | 3/3 | Complete   | 2026-04-05 |
