# Requirements: Frood Dashboard Finalization

**Defined:** 2026-04-07
**Core Value:** Frood is the towel, not the spaceship. The dashboard is an admin/observability panel for the intelligence layer — not an end-user interface or harness.

## v1 Requirements

### Strip Harness Features

- [ ] **STRIP-01**: Remove Mission Control (Kanban board, tasks, projects)
- [ ] **STRIP-02**: Remove Workspace/IDE (Monaco editor, terminal, file browser, Claude Code chat)
- [ ] **STRIP-03**: Remove Agents page (agent lifecycle CRUD, start/stop/delete)
- [ ] **STRIP-04**: Remove Teams page (multi-agent team monitoring)
- [ ] **STRIP-05**: Remove Approvals page (human-in-the-loop task review)
- [ ] **STRIP-06**: Remove GitHub Integration (repo cloning, OAuth, account management)
- [ ] **STRIP-07**: Remove Chat features (chat sessions, message streaming, conversation interface)
- [x] **STRIP-08**: Remove Device Gateway (multi-device management, device API keys)
- [ ] **STRIP-09**: Remove GSD Workstreams UI (phase tracking in dashboard)
- [ ] **STRIP-10**: Remove Status page (platform capacity dashboard)
- [ ] **STRIP-11**: Remove Agent Profiles (profile CRUD, routing overrides — already 410 Gone)
- [ ] **STRIP-12**: Remove Persona customization (chat system prompt — no chat = no persona)

### Rebrand & Polish

- [ ] **BRAND-01**: Rename "Apps" to "Agent Apps" throughout UI and API
- [ ] **BRAND-02**: Update sidebar navigation to show only kept features
- [ ] **BRAND-03**: Ensure all remaining pages use Frood branding (no "Agent42" remnants)
- [ ] **BRAND-04**: Update setup wizard to reflect Frood-as-service identity

### Repurpose Activity Feed

- [ ] **FEED-01**: Repurpose Activity Feed from task/agent lifecycle events to memory/routing/effectiveness event log
- [ ] **FEED-02**: Log memory recall hits, learning extractions, routing decisions, effectiveness scores
- [ ] **FEED-03**: Expose as intelligence layer observability surface

### Cleanup

- [ ] **CLEAN-01**: Remove dead server.py routes for stripped features
- [ ] **CLEAN-02**: Remove dead frontend code for stripped pages/components
- [x] **CLEAN-03**: Remove unused Python modules (if any become orphaned)
- [ ] **CLEAN-04**: Ensure all tests still pass after removal
- [ ] **CLEAN-05**: Update README to reflect Frood Dashboard as intelligence layer admin panel

## Out of Scope

| Feature | Reason |
| ------- | ------ |
| Internal package rename (agent42 → frood) | Separate effort, high blast radius |
| Sidecar API changes | Sidecar is the integration surface, not a dashboard concern |
| Paperclip plugin changes | Plugin is a separate deliverable |
| New dashboard features | Strip first, add later |
