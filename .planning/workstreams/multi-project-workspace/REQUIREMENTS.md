# Requirements: Multi-Project Workspace (v2.1)

**Coverage:** 13/16 satisfied | 3/16 partial (gap closure pending)

## Requirements

### Foundation (FOUND)

- [x] **FOUND-01**: WorkspaceRegistry persists workspaces in SQLite with CRUD operations `[Phase 1]`
- [x] **FOUND-02**: Default workspace auto-seeded from AGENT42_WORKSPACE on startup `[Phase 1]`
- [x] **FOUND-03**: File explorer re-roots to active workspace on tab switch `[Phase 2]`
- [x] **FOUND-04**: No raw filesystem path accepted from client — all calls use workspace_id `[Phase 1]`
- [x] **FOUND-05**: Each workspace has independent editor tabs, cursor, scroll, and selection state `[Phase 2]`
- [x] **FOUND-06**: All IDE API calls pass workspace_id so file ops and search resolve to active workspace `[Phase 1, 2 | Gap closure: Phase 4]`

### Isolation (ISOL)

- [x] **ISOL-01**: File explorer scoped — files from other workspaces not visible `[Phase 2]`
- [x] **ISOL-02**: File save resolves to active workspace root path `[Phase 2]`
- [x] **ISOL-03**: Monaco view state saved/restored per workspace (in-memory) `[Phase 2]`
- [x] **ISOL-04**: CC sessions scoped — subprocess cwd set to workspace root `[Phase 2]`
- [x] **ISOL-05**: Terminals scoped — cwd set to workspace root, switching hides/shows correct sessions `[Phase 2]`
- [x] **ISOL-06**: Monaco model URIs include workspace_id prefix to prevent filename collision `[Phase 1]`
- [ ] **ISOL-07**: All localStorage/sessionStorage keys namespaced by workspace_id via wsKey() `[Phase 1 | Gap closure: Phase 5]`

### Management (MGMT)

- [x] **MGMT-01**: Add workspace modal with path input, app dropdown, and server-side validation `[Phase 3]`
- [ ] **MGMT-02**: Remove workspace shows confirmation guard when workspace has unsaved files `[Phase 3 | Gap closure: Phase 5]`
- [x] **MGMT-03**: Inline rename with Enter to save and immediate tab bar update `[Phase 3]`

## Traceability

| REQ-ID | Priority | Phase | Status | Verified |
|--------|----------|-------|--------|----------|
| FOUND-01 | must | 1 | Satisfied | Phase 1 VERIFICATION.md |
| FOUND-02 | must | 1 | Satisfied | Phase 1 VERIFICATION.md |
| FOUND-03 | must | 2 | Satisfied | Phase 2 VERIFICATION.md |
| FOUND-04 | must | 1 | Satisfied | Phase 1 VERIFICATION.md |
| FOUND-05 | must | 2 | Satisfied | Phase 2 VERIFICATION.md |
| FOUND-06 | must | 1, 2, **4** | Partial | Audit: body/query mismatch + missing search param |
| ISOL-01 | must | 2 | Satisfied | Phase 2 VERIFICATION.md |
| ISOL-02 | must | 2 | Satisfied | Phase 2 VERIFICATION.md |
| ISOL-03 | should | 2 | Satisfied | Phase 2 VERIFICATION.md |
| ISOL-04 | must | 2 | Satisfied | Phase 2 VERIFICATION.md |
| ISOL-05 | must | 2 | Satisfied | Phase 2 VERIFICATION.md |
| ISOL-06 | must | 1 | Satisfied | Phase 1 VERIFICATION.md |
| ISOL-07 | should | 1, **5** | Partial | Audit: cc_panel_width, cc_panel_session_id bare keys |
| MGMT-01 | must | 3 | Satisfied | Phase 3 VERIFICATION.md |
| MGMT-02 | must | 3, **5** | Partial | Audit: stale _wsTabState in unsaved guard |
| MGMT-03 | must | 3 | Satisfied | Phase 3 VERIFICATION.md |

**Bold phase numbers** = gap closure phases from v2.1 audit.
