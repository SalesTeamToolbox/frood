# Roadmap: Frood Dashboard Finalization

## Milestone: v6.0 Frood Dashboard

**Goal:** Transform the Agent42 dashboard into the Frood Dashboard — strip all harness features (orchestration, IDE, chat, agent management), keep intelligence layer features (memory, tools, skills, reports, effectiveness, provider health, Agent Apps), repurpose the activity feed for routing/memory observability, and polish the Frood branding.

### Phases

- [x] **Phase 50: Strip Harness Features** — Remove all orchestration, IDE, chat, agent management, and device gateway features from dashboard (completed 2026-04-07)
- [x] **Phase 51: Rebrand & Repurpose** — Rename Apps to Agent Apps, repurpose Activity Feed, update navigation, polish Frood identity (completed 2026-04-07)

### Phase 50: Strip Harness Features

**Goal**: Remove all harness features from the dashboard, leaving only intelligence layer admin/observability
**Depends on**: Nothing
**Requirements**: STRIP-01 through STRIP-12, CLEAN-01 through CLEAN-04
**Plans:** 4/4 plans complete

Plans:
- [x] 50-01-PLAN.md — Strip all harness route groups from server.py (bottom-to-top deletion)
- [x] 50-02-PLAN.md — Strip harness render functions, sidebar, renderers map from app.js
- [x] 50-03-PLAN.md — Simplify auth.py to JWT-only, clean websocket_manager.py, update agent42.py launcher
- [x] 50-04-PLAN.md — Delete harness test files, clean mixed tests, full suite validation

**Success Criteria** (what must be TRUE):

1. No Mission Control, Workspace, Agents, Teams, Approvals, Chat, or Status pages exist
2. No GitHub integration, Device Gateway, GSD Workstreams, Agent Profiles, or Persona features exist
3. All dead server.py routes for stripped features return 404 or are removed
4. All dead frontend code for stripped pages is removed
5. Full test suite passes after removal

### Phase 51: Rebrand & Repurpose

**Goal**: Polish Frood branding, repurpose Reports for intelligence metrics, clean up Settings, repurpose Activity Feed for observability
**Depends on**: Phase 50
**Requirements**: BRAND-01 through BRAND-04, RPT-01 through RPT-04, FEED-01 through FEED-03, SET-01 through SET-04, CLEAN-05
**Plans:** 4 plans

Plans:
- [x] 51-01-PLAN.md — Test scaffold + branding sweep (Agent42 to Frood, Sandboxed Apps to Agent Apps) + SVG rename + Settings cleanup (Channels removal, Orchestrator to Routing)
- [x] 51-02-PLAN.md — Reports page repurpose (remove Tasks tab, rewrite Overview with intelligence metrics)
- [x] 51-03-PLAN.md — Activity Feed (server ring buffer + /api/activity + frontend page + sidebar entry + CSS)
- [x] 51-04-PLAN.md — Setup wizard copy update + README rewrite for Frood identity

**Success Criteria** (what must be TRUE):

1. "Sandboxed Apps" renamed to "Agent Apps" in sidebar, page title, and API routes
2. Sidebar shows only: Agent Apps, Tools, Skills, Reports, Settings, Activity
3. No "Agent42" text remains in UI (all Frood branding — logo, titles, descriptions)
4. Reports Overview shows intelligence metrics (memory recalls, effectiveness, routing), not task/project counts
5. Reports "Tasks & Projects" tab removed
6. Settings "Channels" tab removed, "Orchestrator" renamed to "Routing", MAX_CONCURRENT_AGENTS removed
7. Activity Feed logs memory recalls, routing decisions, learning extractions, effectiveness scores
8. Setup wizard updated for Frood-as-service identity
9. README reflects Frood Dashboard as intelligence layer admin panel

## Progress

| Phase | Plans Complete | Status | Completed |
| ----- | -------------- | ------ | --------- |
| 50. Strip Harness Features | 4/4 | Complete   | 2026-04-07 |
| 51. Rebrand & Repurpose | 4/4 | Complete   | 2026-04-07 |
