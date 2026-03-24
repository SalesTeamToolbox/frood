# Roadmap: Agent42 v2.1 Multi-Project Workspace

## Overview

This roadmap adds tabbed workspace support to the Agent42 IDE page so each tab scopes an independent project — its own file explorer, editor tabs, CC sessions, and terminal — without cross-contamination. The work is composition and state management: every mechanism required (Monaco model swapping, PTY cwd parameters, CC session routing, localStorage persistence) already exists. Phase 1 locks the server-side registry and client-side namespace conventions before any UI is built; Phase 2 threads those contracts into all IDE surfaces and renders the tab bar; Phase 3 adds workspace lifecycle management (add, remove, rename).

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Registry & Namespacing** - Server-side WorkspaceRegistry, CRUD API, default seeding, ID-based path resolution, and client-side storage/URI namespace conventions (completed 2026-03-24)
- [x] **Phase 2: IDE Surface Integration** - Thread workspace_id into file explorer, editor tabs, CC sessions, and terminals; render workspace tab bar (completed 2026-03-24)
- [x] **Phase 3: Workspace Management** - Add, remove, and rename workspaces with validation and guards (completed 2026-03-24)

## Phase Details

### Phase 1: Registry & Namespacing
**Goal**: The workspace data model is locked server-side and client-side — every IDE surface has a stable workspace_id to key against, raw paths never cross the API boundary, and existing single-workspace users see zero behavior change
**Depends on**: Nothing (first phase)
**Requirements**: FOUND-01, FOUND-02, FOUND-04, FOUND-06, ISOL-06, ISOL-07
**Success Criteria** (what must be TRUE):
  1. Agent42 starts with the existing workspace auto-seeded from AGENT42_WORKSPACE — a user who never adds a second workspace sees no UI or behavior difference
  2. The `/api/workspaces` endpoints list, create, update, and delete workspaces; all paths are validated against the filesystem before acceptance
  3. No raw filesystem path is accepted from the client in any API call — all calls use a workspace ID that the server resolves to a path
  4. Monaco model URIs include a workspace_id prefix so two workspaces can open the same filename without collision
  5. localStorage and sessionStorage keys for CC history, session IDs, and panel state are namespaced by workspace_id
**Plans:** 2/2 plans complete

Plans:
- [x] 01-01-PLAN.md — WorkspaceRegistry module (persistence, CRUD, default seeding), /api/workspaces endpoints, workspace_id param on IDE endpoints, agent42.py wiring
- [x] 01-02-PLAN.md — Monaco URI namespace convention (workspace_id prefix) and localStorage/sessionStorage key namespace schema (definition-only, no behavior change)

### Phase 2: IDE Surface Integration
**Goal**: Switching the active workspace tab instantly re-roots the file explorer, swaps editor tabs, shows that workspace's CC sessions, and connects terminals — all scoped to the active workspace's root path — with the workspace tab bar visible and functional
**Depends on**: Phase 1
**Requirements**: FOUND-03, FOUND-05, ISOL-01, ISOL-02, ISOL-03, ISOL-04, ISOL-05
**Success Criteria** (what must be TRUE):
  1. A workspace tab bar appears above the editor tab bar; clicking a tab switches the active workspace and all IDE surfaces update
  2. The file explorer re-roots to the active workspace folder on every tab switch — files from other workspaces are not visible
  3. Each workspace has independent editor tabs; switching tabs restores the exact open files, cursor position, scroll, and selection from the last visit to that workspace
  4. CC sessions started in a workspace have their subprocess cwd set to that workspace's root; session history is filtered per workspace
  5. Terminals opened in a workspace start with cwd set to that workspace's root; switching tabs hides/shows the correct terminal sessions
  6. Workspace tab state (open tabs, active workspace) persists across page reloads via localStorage with stale-while-revalidate against the server
**Plans:** 3/3 plans complete

Plans:
- [x] 02-01-PLAN.md — Backend workspace_id wiring (terminal_ws, cc_chat_ws, cc_sessions filter) + frontend state promotion and workspace_id threading on all fetch/WS URLs
- [x] 02-02-PLAN.md — Monaco view state save/restore, makeWorkspaceUri migration in ideOpenFile, CC session sidebar workspace filter, wsKey-based session storage
- [x] 02-03-PLAN.md — Workspace tab bar UI (render, active indicator, switchWorkspace orchestrator), initWorkspaceTabs with stale-while-revalidate localStorage persistence

### Phase 3: Workspace Management
**Goal**: Users can add a new workspace by path or Agent42 app, remove any workspace that is not the last one, and rename a workspace inline — with guards that prevent data loss
**Depends on**: Phase 2
**Requirements**: MGMT-01, MGMT-02, MGMT-03
**Success Criteria** (what must be TRUE):
  1. An "Add workspace" button opens a modal where the user can enter a filesystem path (validated against the server) or choose an Agent42 internal app from a dropdown
  2. Clicking the close button on a workspace tab shows a confirmation guard if the workspace has unsaved files; the last workspace cannot be removed
  3. Clicking a workspace tab name switches it to an inline text input; pressing Enter saves the rename and updates the tab bar immediately
**Plans**: TBD

Plans:
- [x] 03-01: Add workspace modal (path input + app dropdown, server-side validation); remove workspace with unsaved-files guard and last-workspace protection; inline rename

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Registry & Namespacing | 2/2 | Complete    | 2026-03-24 |
| 2. IDE Surface Integration | 3/3 | Complete    | 2026-03-24 |
| 3. Workspace Management | 1/1 | Complete   | 2026-03-24 |
