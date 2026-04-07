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
- [ ] **BRAND-04**: Update setup wizard to reflect Frood-as-service identity

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
- [ ] **CLEAN-05**: Update README to reflect Frood Dashboard as intelligence layer admin panel

## Out of Scope

| Feature | Reason |
| ------- | ------ |
| Internal package rename (agent42 → frood) | Separate effort, high blast radius |
| Sidecar API changes | Sidecar is the integration surface, not a dashboard concern |
| Paperclip plugin changes | Plugin is a separate deliverable |
| New dashboard features | Strip first, add later |
