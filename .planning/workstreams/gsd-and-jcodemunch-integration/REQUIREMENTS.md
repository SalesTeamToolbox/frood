# Requirements: Agent42 v3.0 — GSD & jcodemunch Integration

**Defined:** 2026-03-17
**Core Value:** Agent42 must always be able to run agents reliably, with tiered provider routing ensuring no single provider outage stops the platform.

## v1 Requirements

### Setup

- [ ] **SETUP-01**: User can run `bash setup.sh` on Linux/VPS and have `.mcp.json` generated with Agent42 MCP server entry
- [ ] **SETUP-02**: User can run `bash setup.sh` on Linux/VPS and have `.claude/settings.json` patched to register all Agent42 hooks
- [ ] **SETUP-03**: User can run `bash setup.sh` on Linux/VPS and have the project repo indexed by jcodemunch automatically
- [ ] **SETUP-04**: User can re-run `bash setup.sh` without overwriting existing configuration (idempotent)
- [ ] **SETUP-05**: User can see a post-setup health report confirming MCP server, jcodemunch, and Qdrant are reachable
- [x] **SETUP-06**: User on Windows with Git Bash can run `bash setup.sh` without path errors or CRLF failures
- [x] **SETUP-07**: User can run a setup command to generate a CLAUDE.md template with Agent42 conventions and pitfall patterns baked in

### Memory

- [x] **MEM-01**: MEMORY.md entries include a UUID and ISO timestamp so sync can identify individual entries across nodes
- [x] **MEM-02**: User can run `node_sync merge` and have divergent entries union-merged without silent data loss (replaces mtime-wins)
- [x] **MEM-03**: User can call MemoryTool with a `project` parameter and have memories stored/retrieved in a project-scoped namespace

### Context

- [x] **CTX-01**: User can call `agent42_context` and receive code symbols from jcodemunch merged with memory results in a single response
- [x] **CTX-02**: User can call `agent42_context` and see the active GSD workstream phase plan when the query matches current work context
- [x] **CTX-03**: User can call `agent42_context` and see effectiveness-ranked tools/skills for the current task type at the top of results

## v2 Requirements

### Enterprise

- **ENT-01**: Multi-user authentication in dashboard (replaces single admin)
- **ENT-02**: User can access a team-shared memory namespace where sessions from any member contribute
- **ENT-03**: System proposes CLAUDE.md additions via dashboard diff when new pitfalls accumulate (requires human approval)
- **ENT-04**: OAuth2/SSO login for dashboard

## Out of Scope

| Feature | Reason |
|---------|--------|
| Qdrant cluster sync (replication protocol) | Over-engineered for 2-node scenario; flat files as source of truth is correct |
| Real-time memory sync (websocket/live) | Fragile over SSH tunnels, marginal benefit; periodic sync sufficient |
| CLAUDE.md auto-update without human review | Prompt injection risk — approval gate is mandatory, not optional |
| Custom fine-tuned models per user | Out of scope per PROJECT.md; use memory + skills for personalization |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| SETUP-01 | Phase 1 | Helpers done (01-02), setup.sh integration pending (01-03) |
| SETUP-02 | Phase 1 | Helpers done (01-02), setup.sh integration pending (01-03) |
| SETUP-03 | Phase 1 | Pending (01-03) |
| SETUP-04 | Phase 1 | Helpers done (01-02), setup.sh integration pending (01-03) |
| SETUP-05 | Phase 1 | Helpers done (01-02), setup.sh integration pending (01-03) |
| SETUP-06 | Phase 2 | Complete |
| SETUP-07 | Phase 2 | Complete |
| MEM-01 | Phase 3 | Complete |
| MEM-02 | Phase 3 | Complete |
| MEM-03 | Phase 3 | Complete |
| CTX-01 | Phase 4 | Complete |
| CTX-02 | Phase 4 | Complete |
| CTX-03 | Phase 4 | Complete |

**Coverage:**
- v1 requirements: 13 total
- Mapped to phases: 13
- Unmapped: 0 ✓

---
*Requirements defined: 2026-03-17*
*Last updated: 2026-03-18 — Plan 01-02 complete: setup_helpers.py + mcp_server.py --health implemented*
