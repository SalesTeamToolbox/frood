# Requirements: Frood Dashboard Finalization

**Defined:** 2026-04-07
**Core Value:** Frood is the towel, not the spaceship. The dashboard is an admin/observability panel for the intelligence layer — not an end-user interface or harness.

## v1 Requirements

### Strip Harness Features

- [x] **STRIP-01**: Remove Mission Control (Kanban board, tasks, projects)
- [x] **STRIP-02**: Remove Workspace/IDE (Monaco editor, terminal, file browser, Claude Code chat)
- [x] **STRIP-03**: Remove Agents page (agent lifecycle CRUD, start/stop/delete)
- [x] **STRIP-04**: Remove Teams page (multi-agent team monitoring)
- [x] **STRIP-05**: Remove Approvals page (human-in-the-loop task review)
- [x] **STRIP-06**: Remove GitHub Integration (repo cloning, OAuth, account management)
- [x] **STRIP-07**: Remove Chat features (chat sessions, message streaming, conversation interface)
- [x] **STRIP-08**: Remove Device Gateway (multi-device management, device API keys)
- [x] **STRIP-09**: Remove GSD Workstreams UI (phase tracking in dashboard)
- [x] **STRIP-10**: Remove Status page (platform capacity dashboard)
- [x] **STRIP-11**: Remove Agent Profiles (profile CRUD, routing overrides — already 410 Gone)
- [x] **STRIP-12**: Remove Persona customization (chat system prompt — no chat = no persona)

### Rebrand & Polish

- [x] **BRAND-01**: Rename "Sandboxed Apps" to "Agent Apps" throughout UI and API
- [x] **BRAND-02**: Update sidebar navigation to show only kept features
- [x] **BRAND-03**: Ensure all remaining pages use Frood branding (no "Agent42" remnants — logo alt, provider routing text, page titles, etc.)
- [x] **BRAND-04**: Update setup wizard to reflect Frood-as-service identity

### Repurpose Reports Page

- [x] **RPT-01**: Repurpose Overview tab — replace harness metrics (Total Tasks, Success Rate, Projects, Task Type Breakdown) with intelligence layer metrics (memory recall stats, routing decisions, effectiveness scores, learning extractions)
- [x] **RPT-02**: Remove "Tasks & Projects" tab entirely — pure harness content
- [x] **RPT-03**: Keep "System Health" tab as-is (MCP transport, tools, skills, token tracking)
- [x] **RPT-04**: Add memory/effectiveness data to Overview (recall hit rate, learning count, top-performing models, routing tier distribution)

### Repurpose Activity Feed

- [x] **FEED-01**: Repurpose Activity Feed from task/agent lifecycle events to memory/routing/effectiveness event log
- [x] **FEED-02**: Log memory recall hits, learning extractions, routing decisions, effectiveness scores
- [x] **FEED-03**: Expose as intelligence layer observability surface

### Settings Cleanup

- [x] **SET-01**: Remove "Channels" tab — backend route removed, frontend still references it
- [x] **SET-02**: Rename "Orchestrator" tab to "Routing" or "LLM Proxy" — no longer an agent orchestrator
- [x] **SET-03**: Remove MAX_CONCURRENT_AGENTS setting from Orchestrator/Routing tab — harness concept
- [x] **SET-04**: Remove `loadChannels()` from `loadAll()` in app.js

### Cleanup

- [x] **CLEAN-01**: Remove dead server.py routes for stripped features
- [x] **CLEAN-02**: Remove dead frontend code for stripped pages/components
- [x] **CLEAN-03**: Remove unused Python modules (if any become orphaned)
- [x] **CLEAN-04**: Ensure all tests still pass after removal
- [x] **CLEAN-05**: Update README to reflect Frood Dashboard as intelligence layer admin panel

## v7.0 Requirements

### Sidecar Auth

- [ ] **AUTH-01**: Sidecar exposes a `/sidecar/token` endpoint that generates a JWT given valid credentials (API key or password)
- [ ] **AUTH-02**: Adapter config accepts `apiKey` field that auto-provisions a bearer token on first connect
- [ ] **AUTH-03**: Sidecar health endpoint (`/sidecar/health`) remains unauthenticated for container probes

### Entry Point & Config

- [ ] **ENTRY-01**: Main entry point renamed from `agent42.py` to `frood.py`
- [ ] **ENTRY-02**: `agent42.py` backward-compat shim exists that imports and runs `frood.py`
- [ ] **ENTRY-03**: All `AGENT42_*` environment variables renamed to `FROOD_*` with fallback to old names
- [ ] **ENTRY-04**: `core/config.py` Settings reads `FROOD_*` vars (falling back to `AGENT42_*`)
- [ ] **ENTRY-05**: `.env.example` updated with `FROOD_*` variable names

### Data Directory Migration

- [ ] **DATA-01**: Default data directory changed from `.agent42/` to `.frood/`
- [ ] **DATA-02**: On startup, if `.agent42/` exists and `.frood/` does not, auto-migrate (rename) with log message
- [ ] **DATA-03**: All hardcoded `.agent42/` path references in code updated to `.frood/`

### Python Internals

- [ ] **PY-01**: All logger names changed from `agent42.*` to `frood.*`
- [ ] **PY-02**: All `[agent42-*]` print prefixes changed to `[frood-*]`
- [ ] **PY-03**: MCP server module references updated from `agent42` to `frood`
- [ ] **PY-04**: CLAUDE.md marker injection updated from `AGENT42_MEMORY` to `FROOD_MEMORY`

### Frontend Identity

- [ ] **FE-01**: localStorage key renamed from `agent42_token` to `frood_token` (with migration on load)
- [ ] **FE-02**: BroadcastChannel renamed from `agent42_auth` to `frood_auth`
- [ ] **FE-03**: Zero `agent42` references remain in `app.js` (case-insensitive, excluding comments about migration)

### Docker & Infrastructure

- [ ] **INFRA-01**: Docker service renamed from `agent42-sidecar` to `frood-sidecar` in compose files
- [ ] **INFRA-02**: Docker volume renamed from `agent42-data` to `frood-data`
- [ ] **INFRA-03**: Dockerfile updated: user, command references use `frood`
- [ ] **INFRA-04**: `docker-compose.paperclip.yml` env vars use `FROOD_*` names

### NPM Packages

- [ ] **NPM-01**: Adapter package renamed from `@agent42/paperclip-adapter` to `@frood/paperclip-adapter`
- [ ] **NPM-02**: Plugin package renamed from `@agent42/paperclip-plugin` to `@frood/paperclip-plugin`
- [ ] **NPM-03**: Adapter/plugin directory names renamed from `agent42-paperclip` to `frood-paperclip`

### Qdrant Collections

- [ ] **QDRANT-01**: Default collection names changed from `agent42_memory`/`agent42_history` to `frood_memory`/`frood_history`
- [ ] **QDRANT-02**: Migration code creates aliases from old collection names to new ones for backward compat
- [ ] **QDRANT-03**: `QDRANT_COLLECTION_PREFIX` env var default updated

### Tests & Documentation

- [ ] **DOCS-01**: All test files updated to reference `frood` instead of `agent42`
- [ ] **DOCS-02**: CLAUDE.md updated with `frood` references (entry point, data dir, env vars)
- [ ] **DOCS-03**: `.env.example` fully reflects Frood naming
- [ ] **DOCS-04**: Full test suite passes after all renames

## Out of Scope

| Feature | Reason |
| ------- | ------ |
| Git repo rename (agent42 → frood) | GitHub repo URL stays as-is for now — separate concern |
| New dashboard features | Rename first, add features later |
| Paperclip core changes | Only rename Frood-side adapter/plugin packages |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| AUTH-01 | Phase 53 | Pending |
| AUTH-02 | Phase 53 | Pending |
| AUTH-03 | Phase 53 | Pending |
| ENTRY-01 | Phase 52 | Pending |
| ENTRY-02 | Phase 52 | Pending |
| ENTRY-03 | Phase 52 | Pending |
| ENTRY-04 | Phase 52 | Pending |
| ENTRY-05 | Phase 52 | Pending |
| DATA-01 | Phase 52 | Pending |
| DATA-02 | Phase 52 | Pending |
| DATA-03 | Phase 52 | Pending |
| PY-01 | Phase 52 | Pending |
| PY-02 | Phase 52 | Pending |
| PY-03 | Phase 52 | Pending |
| PY-04 | Phase 52 | Pending |
| FE-01 | Phase 53 | Pending |
| FE-02 | Phase 53 | Pending |
| FE-03 | Phase 53 | Pending |
| INFRA-01 | Phase 54 | Pending |
| INFRA-02 | Phase 54 | Pending |
| INFRA-03 | Phase 54 | Pending |
| INFRA-04 | Phase 54 | Pending |
| NPM-01 | Phase 54 | Pending |
| NPM-02 | Phase 54 | Pending |
| NPM-03 | Phase 54 | Pending |
| QDRANT-01 | Phase 55 | Pending |
| QDRANT-02 | Phase 55 | Pending |
| QDRANT-03 | Phase 55 | Pending |
| DOCS-01 | Phase 55 | Pending |
| DOCS-02 | Phase 55 | Pending |
| DOCS-03 | Phase 55 | Pending |
| DOCS-04 | Phase 55 | Pending |
