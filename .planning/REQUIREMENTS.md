# Requirements: Agent42 v2.1 Multi-Project Workspace

**Defined:** 2026-03-23
**Core Value:** Agent42 must always be able to run agents reliably — multi-workspace extends this to running agents scoped to specific projects.

## v2.1 Requirements

Requirements for this milestone. Each maps to roadmap phases.

### Foundation

- [ ] **FOUND-01**: Server-side WorkspaceRegistry persists workspace configs (ID, name, root_path) in `.agent42/workspaces.json`
- [ ] **FOUND-02**: `/api/workspaces` CRUD endpoints (list, create, update, delete) with path validation against filesystem
- [ ] **FOUND-03**: Workspace tab bar renders above editor tab bar with active workspace indicator
- [ ] **FOUND-04**: Default workspace auto-seeded from `AGENT42_WORKSPACE` on first load — zero behavior change for existing users
- [ ] **FOUND-05**: Workspace configuration persists across page reloads via localStorage (stale-while-revalidate against server)
- [ ] **FOUND-06**: Workspace IDs used in all API calls — server resolves ID to path, never accepts raw paths from client

### Isolation

- [ ] **ISOL-01**: File explorer re-roots to active workspace folder on tab switch via `workspace_id` param on `/api/ide/tree`
- [ ] **ISOL-02**: Editor tabs partitioned by `workspace_id` — each workspace has independent open files, saved/restored on switch
- [ ] **ISOL-03**: Monaco view state (cursor, scroll, selection) saved per workspace tab and restored on switch
- [ ] **ISOL-04**: CC sessions scoped per workspace — subprocess `cwd` set to workspace root, session history filtered by workspace
- [ ] **ISOL-05**: Terminal sessions scoped per workspace — PTY spawned with `cwd` = workspace root, terminals hidden/shown on switch
- [ ] **ISOL-06**: Monaco model URIs prefixed with workspace ID to prevent cross-workspace file collisions
- [ ] **ISOL-07**: localStorage/sessionStorage keys namespaced by workspace ID (CC history, session IDs, panel state)

### Management

- [ ] **MGMT-01**: Add workspace modal — manual path input with filesystem validation + dropdown for Agent42 internal apps
- [ ] **MGMT-02**: Remove workspace — close button with unsaved-files guard, cannot remove last workspace
- [ ] **MGMT-03**: Rename workspace — click workspace tab name to edit inline

## v2.2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Enhanced UX

- **EUX-01**: Git branch indicator per workspace tab
- **EUX-02**: Workspace-scoped search (search within active workspace only)
- **EUX-03**: Drag-and-drop workspace tab reordering
- **EUX-04**: Workspace color coding / custom icons
- **EUX-05**: CC warm pool keyed by (user, workspace_id) for faster first response per workspace

## Out of Scope

| Feature | Reason |
| ------- | ------ |
| Cross-workspace search | High complexity, unclear UX value — search within active workspace is sufficient |
| Shared editor tabs across workspaces | Violates isolation contract, causes state contamination bugs |
| Conflating Agent42 Projects (Kanban) with workspaces | Different concepts — Projects are task management, workspaces are filesystem scope |
| Multiple Monaco editor instances | 80MB RAM each — use model swapping instead |
| Global cross-workspace file tree | VS Code multi-root model — wrong for Agent42's context-switching model |

## Traceability

| Requirement | Phase | Phase Name | Status |
| ----------- | ----- | ---------- | ------ |
| FOUND-01 | Phase 1 | Registry & Namespacing | Pending |
| FOUND-02 | Phase 1 | Registry & Namespacing | Pending |
| FOUND-04 | Phase 1 | Registry & Namespacing | Pending |
| FOUND-06 | Phase 1 | Registry & Namespacing | Pending |
| ISOL-06 | Phase 1 | Registry & Namespacing | Pending |
| ISOL-07 | Phase 1 | Registry & Namespacing | Pending |
| FOUND-03 | Phase 2 | IDE Surface Integration | Pending |
| FOUND-05 | Phase 2 | IDE Surface Integration | Pending |
| ISOL-01 | Phase 2 | IDE Surface Integration | Pending |
| ISOL-02 | Phase 2 | IDE Surface Integration | Pending |
| ISOL-03 | Phase 2 | IDE Surface Integration | Pending |
| ISOL-04 | Phase 2 | IDE Surface Integration | Pending |
| ISOL-05 | Phase 2 | IDE Surface Integration | Pending |
| MGMT-01 | Phase 3 | Workspace Management | Pending |
| MGMT-02 | Phase 3 | Workspace Management | Pending |
| MGMT-03 | Phase 3 | Workspace Management | Pending |

**Coverage:**
- v2.1 requirements: 16 total
- Mapped to phases: 16
- Unmapped: 0

---
*Requirements defined: 2026-03-23*
*Last updated: 2026-03-23 after roadmap creation*
