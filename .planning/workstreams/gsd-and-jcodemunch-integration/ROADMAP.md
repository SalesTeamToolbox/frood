# Roadmap: Agent42 v3.0 — GSD & jcodemunch Integration

## Overview

This milestone unifies Agent42's developer tooling into a zero-friction platform. Phase 1 delivers one-command setup for Linux/VPS — generating .mcp.json, registering hooks, indexing the repo, and validating health. Phase 2 extends that setup to Windows and adds CLAUDE.md template generation. Phase 3 replaces the naive mtime-wins memory sync with conflict-resistant entry-union merge backed by UUID+timestamp entries, and wires per-project memory namespaces into MemoryTool. Phase 4 completes the milestone by adding jcodemunch code symbols and GSD workstream state to the unified context engine, plus effectiveness-ranked tool/skill injection.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

- [x] **Phase 1: Setup Foundation** - One-command Linux/VPS setup that generates .mcp.json, registers hooks, indexes repo, and validates health
- [ ] **Phase 2: Windows + CLAUDE.md** - Windows Git Bash support and CLAUDE.md template generation with Agent42 conventions
- [ ] **Phase 3: Memory Sync** - Conflict-resistant memory sync with UUID+timestamp entries, entry-union merge, and per-project namespaces
- [ ] **Phase 4: Context Engine** - Unified context engine merging jcodemunch code symbols, GSD workstream state, and effectiveness-ranked tools/skills

## Phase Details

### Phase 1: Setup Foundation
**Goal**: Users can run a single command on Linux/VPS and have a fully configured Agent42 + Claude Code environment with working MCP, hooks, and jcodemunch index
**Depends on**: Nothing (first phase)
**Requirements**: SETUP-01, SETUP-02, SETUP-03, SETUP-04, SETUP-05
**Success Criteria** (what must be TRUE):
  1. User runs `bash setup.sh` on Linux/VPS and `.mcp.json` exists with Agent42 MCP server entry pointing to the correct Python path
  2. User runs `bash setup.sh` and `.claude/settings.json` contains all Agent42 hooks registered under the correct hook event keys
  3. User runs `bash setup.sh` and the project repo is indexed in jcodemunch (verifiable via `list_repos` returning the project)
  4. User re-runs `bash setup.sh` on an already-configured system and no existing configuration is overwritten or corrupted
  5. User sees a post-setup health report listing MCP server reachable, jcodemunch responding, and Qdrant accessible (with pass/fail per service)
**Plans**: 3 plans

- [x] 01-01-PLAN.md — Hook frontmatter + test scaffolding (Wave 1)
- [x] 01-02-PLAN.md — Python setup helpers + MCP health flag (Wave 1)
- [x] 01-03-PLAN.md — jcodemunch indexer + setup.sh integration + tests (Wave 2)

### Phase 2: Windows + CLAUDE.md
**Goal**: Users on Windows with Git Bash can run the same setup command without errors, and any user can generate a project CLAUDE.md pre-loaded with Agent42 conventions and pitfall patterns
**Depends on**: Phase 1
**Requirements**: SETUP-06, SETUP-07
**Success Criteria** (what must be TRUE):
  1. User on Windows runs `bash setup.sh` in Git Bash without path errors, CRLF failures, or Python venv activation errors — setup completes successfully
  2. User runs the CLAUDE.md generation command and receives a CLAUDE.md file containing Agent42 hook protocol, memory system description, and at least the current pitfall patterns from CLAUDE.md
  3. Generated CLAUDE.md is project-aware (references the correct project name, repo identifier, and active workstream)
**Plans**: TBD

### Phase 3: Memory Sync
**Goal**: Memory entries carry stable identifiers so sync across nodes produces a lossless union of all entries, and MemoryTool isolates memories by project namespace when a project parameter is provided
**Depends on**: Phase 1
**Requirements**: MEM-01, MEM-02, MEM-03
**Success Criteria** (what must be TRUE):
  1. MEMORY.md entries each contain a UUID and ISO timestamp field that persists across sync operations and is assigned on creation (not on sync)
  2. User runs `node_sync merge` after independent edits on two nodes and all entries from both nodes appear in the merged result — no entry from either node is silently lost
  3. User calls MemoryTool with `project="myproject"` and memories are stored in and retrieved from a project-scoped namespace, not the global store
  4. User calls MemoryTool without a project parameter and existing global store behavior is unchanged (backward compatible)
**Plans**: TBD

### Phase 4: Context Engine
**Goal**: A single `agent42_context` call returns a unified response that merges code symbols from jcodemunch, the active GSD workstream phase plan, and effectiveness-ranked tools/skills — all within a single token budget
**Depends on**: Phase 3
**Requirements**: CTX-01, CTX-02, CTX-03
**Success Criteria** (what must be TRUE):
  1. User calls `agent42_context` with a code-related query and receives jcodemunch symbol search results merged with semantic memory results in a single response, with no duplicate content between sources
  2. User calls `agent42_context` while a GSD workstream is active and the response includes the current phase goal and open plan items when the query topic matches current work context
  3. User calls `agent42_context` and tools/skills that performed well on the current task type appear ranked above tools/skills with no effectiveness history for that task type
  4. `agent42_context` degrades gracefully — when jcodemunch is unavailable, the response omits code symbols but still returns memory and GSD context without error
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Setup Foundation | 3/3 | Complete | 2026-03-18 |
| 2. Windows + CLAUDE.md | 0/TBD | Not started | - |
| 3. Memory Sync | 0/TBD | Not started | - |
| 4. Context Engine | 0/TBD | Not started | - |
