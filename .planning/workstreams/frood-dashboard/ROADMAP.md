# Roadmap: Frood Dashboard Finalization

<details>
<summary>✅ v6.0 Frood Dashboard (Phases 50-51) - SHIPPED 2026-04-08</summary>

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
**Plans:** 4/4 plans complete

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

</details>

## Milestone: v7.0 Full Agent42 → Frood Rename

**Goal:** Complete the Frood identity by renaming every Agent42 reference in the codebase — entry point, data directory, environment variables, Python internals, frontend identity, Docker infrastructure, NPM packages, and Qdrant collections — while fixing the sidecar auth gap and ensuring backward compatibility throughout.

### Phases

- [x] **Phase 52: Core Identity Rename** — Rename entry point, data directory, env vars, and all Python internal references (frood.py, .frood/, FROOD_* vars, logger names)
- [ ] **Phase 53: Frontend Identity + Sidecar Auth** — Migrate frontend storage keys and BroadcastChannel names; add /sidecar/token provisioning endpoint
- [ ] **Phase 54: Infrastructure + Packages** — Rename Docker services, volumes, compose env vars; rename NPM adapter and plugin packages
- [ ] **Phase 55: Qdrant Migration + Test Suite** — Migrate collection names with aliases for backward compat; update all tests and docs; full suite validation

## Phase Details

### Phase 52: Core Identity Rename

**Goal**: The backend fully speaks "frood" — entry point, data directory, env vars, config reads, and all Python internals use the new name with clean break (no backward-compat env var fallbacks)
**Depends on**: Phase 51
**Requirements**: ENTRY-01, ENTRY-02, ENTRY-03, ENTRY-04, ENTRY-05, DATA-01, DATA-02, DATA-03, PY-01, PY-02, PY-03, PY-04
**Success Criteria** (what must be TRUE):
  1. Running `python frood.py` starts the application; running `python agent42.py` also starts it via shim
  2. Starting the app with `.agent42/` present and no `.frood/` auto-migrates the directory and logs a migration message
  3. All `AGENT42_*` env vars replaced with `FROOD_*` (clean break, no fallback)
  4. No `agent42.*` logger names or `[agent42-*]` print prefixes remain in Python source
  5. CLAUDE.md marker injection writes `FROOD_MEMORY` markers, not `AGENT42_MEMORY`
**Plans:** 3 plans

Plans:
- [x] 52-01-PLAN.md — Create frood.py entry point, agent42.py shim, config.py defaults, data dir migration
- [x] 52-02-PLAN.md — Rename AGENT42_* env vars, mcp_server.py internals, CLAUDE.md markers, .agent42/ paths
- [x] 52-03-PLAN.md — Batch logger rename, hook files, test file updates

### Phase 53: Frontend Identity + Sidecar Auth

**Goal**: The frontend uses Frood-namespaced storage with automatic migration of existing sessions; external consumers (Paperclip, adapters) can obtain a bearer token from the sidecar
**Depends on**: Phase 52
**Requirements**: FE-01, FE-02, FE-03, AUTH-01, AUTH-02, AUTH-03
**Success Criteria** (what must be TRUE):
  1. Existing sessions stored under `agent42_token` are automatically migrated to `frood_token` on first page load — no re-login required
  2. BroadcastChannel cross-tab auth sync uses `frood_auth`; no `agent42` channel names remain in app.js
  3. POST `/sidecar/token` with valid credentials returns a signed JWT that subsequent API calls accept
  4. Adapter config with an `apiKey` field auto-provisions a token on first connect without manual JWT management
  5. GET `/sidecar/health` returns 200 without authentication (safe for container liveness probes)
**Plans**: TBD

### Phase 54: Infrastructure + Packages

**Goal**: Docker compose and NPM packages carry the Frood name — services, volumes, env vars, and package scopes all updated
**Depends on**: Phase 52
**Requirements**: INFRA-01, INFRA-02, INFRA-03, INFRA-04, NPM-01, NPM-02, NPM-03
**Success Criteria** (what must be TRUE):
  1. `docker-compose.paperclip.yml` defines service `frood-sidecar` and volume `frood-data`; no `agent42` service or volume names remain
  2. Compose env vars use `FROOD_*` naming throughout
  3. Dockerfile user and CMD references use `frood`
  4. Adapter package is published/installable as `@frood/paperclip-adapter`; plugin as `@frood/paperclip-plugin`
  5. Package directories renamed from `agent42-paperclip` to `frood-paperclip`
**Plans**: TBD

### Phase 55: Qdrant Migration + Test Suite

**Goal**: Qdrant collections use Frood names with aliases preserving backward compat; all tests and docs reflect the rename; full suite green
**Depends on**: Phase 52, Phase 53, Phase 54
**Requirements**: QDRANT-01, QDRANT-02, QDRANT-03, DOCS-01, DOCS-02, DOCS-03, DOCS-04
**Success Criteria** (what must be TRUE):
  1. New deployments create `frood_memory` and `frood_history` Qdrant collections
  2. Existing deployments with `agent42_memory`/`agent42_history` collections continue to work via collection aliases
  3. `QDRANT_COLLECTION_PREFIX` env var defaults to `frood`
  4. All test files reference `frood` (no `agent42` assertions, fixture names, or collection names)
  5. CLAUDE.md, `.env.example`, and planning docs all reflect Frood naming
  6. Full test suite passes with zero failures after all v7.0 renames
**Plans**: TBD

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 50. Strip Harness Features | v6.0 | 4/4 | Complete | 2026-04-07 |
| 51. Rebrand & Repurpose | v6.0 | 4/4 | Complete | 2026-04-08 |
| 52. Core Identity Rename | v7.0 | 1/3 | Executing | - |
| 53. Frontend Identity + Sidecar Auth | v7.0 | 0/TBD | Not started | - |
| 54. Infrastructure + Packages | v7.0 | 0/TBD | Not started | - |
| 55. Qdrant Migration + Test Suite | v7.0 | 0/TBD | Not started | - |
