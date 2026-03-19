# Roadmap: Intelligent Memory Bridge

## Overview

This workstream builds an invisible bridge between Claude Code's flat-file memory and Agent42's Qdrant-backed semantic memory. Phase 1 installs a PostToolUse hook that intercepts every CC memory write and syncs it to Qdrant. Phase 2 upgrades the Stop hook to intelligently extract structured learnings from conversations — decisions, corrections, patterns, and deployments. Phase 3 wires the CLAUDE.md instructions that steer Claude toward the richer Agent42 memory for both reads and writes. Phase 4 adds memory quality mechanisms (dedup, consolidation, confidence scoring) so the Qdrant store stays clean over time. When complete, Agent42 memory becomes the primary system with zero user intervention.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Auto-Sync Hook** - Intercept CC memory writes and sync to Qdrant automatically
- [x] **Phase 2: Intelligent Learning** - Extract structured learnings from conversation context at session end (completed 2026-03-19)
- [x] **Phase 3: CLAUDE.md Integration** - Steer Claude to use Agent42 memory via instructions and setup automation (completed 2026-03-19)
- [x] **Phase 4: Memory Quality** - Keep Qdrant store clean with dedup, consolidation, and confidence scoring (completed 2026-03-19)

## Phase Details

### Phase 1: Auto-Sync Hook
**Goal**: Every write Claude Code makes to its memory files is automatically mirrored in Agent42 Qdrant, with no user action and no impact on CC's normal operation
**Depends on**: Nothing (first phase)
**Requirements**: SYNC-01, SYNC-02, SYNC-03, SYNC-04
**Success Criteria** (what must be TRUE):
  1. After Claude Code writes a memory file, the content appears in Agent42 Qdrant without any manual step
  2. Memories written from user, feedback, project, and reference file types are all present in Qdrant
  3. Writing the same content twice results in exactly one Qdrant entry (no duplicates)
  4. When Qdrant is unreachable, Claude Code's Write tool completes normally with no error shown to Claude
**Plans**: 2 (01-01 complete, 01-02 complete)

### Phase 2: Intelligent Learning
**Goal**: At session end, the Stop hook extracts structured, categorized learnings from the conversation and stores them in Qdrant with enough context to be useful on future recall
**Depends on**: Phase 1
**Requirements**: LEARN-01, LEARN-02, LEARN-03, LEARN-04, LEARN-05
**Success Criteria** (what must be TRUE):
  1. After a session where an architectural decision was made, a Qdrant entry of type "decision" exists capturing it
  2. After a session where Claude was corrected, a Qdrant entry of type "feedback" exists capturing the correction
  3. After a session involving deployment or debugging tool usage, relevant patterns are stored in Qdrant
  4. A pattern stored in prior sessions has its confidence score increased when it appears again in a new session
  5. Entries are tagged with a category (security, feature, refactor, deploy) that matches the nature of the work
**Plans**: 2 (02-01 complete, 02-02 complete)

### Phase 3: CLAUDE.md Integration
**Goal**: Claude prefers Agent42 memory for both reads and writes by default, and new Agent42 installations automatically configure this preference without any user editing CLAUDE.md manually
**Depends on**: Phase 1, Phase 2
**Requirements**: INTEG-01, INTEG-02, INTEG-03
**Success Criteria** (what must be TRUE):
  1. CLAUDE.md contains instructions that direct Claude to call `agent42_memory search` before answering from its own flat-file memory
  2. CLAUDE.md contains instructions that direct Claude to call `agent42_memory store` alongside its built-in memory write operations
  3. Running setup.sh on a fresh Agent42 installation produces a CLAUDE.md that contains both memory instructions without any manual editing
**Plans**: 1/1 complete

Plans:

- [x] 03-01-PLAN.md -- Memory instructions template, setup_helpers function, setup.sh wiring (complete)

### Phase 4: Memory Quality
**Goal**: The Agent42 Qdrant memory store remains accurate and navigable over time — duplicates are removed, related entries are merged, and search results are ranked by proven relevance
**Depends on**: Phase 1, Phase 2
**Requirements**: QUAL-01, QUAL-02
**Success Criteria** (what must be TRUE):
  1. After accumulating memory over multiple sessions, a consolidation pass runs and MEMORY.md has fewer, denser entries with duplicates removed and related entries merged
  2. Search results returned by `agent42_memory search` include a confidence score and recall count, with higher-confidence entries ranked above lower-confidence entries for the same query
**Plans**: 2 plans

Plans:

- [x] 04-01-PLAN.md -- Consolidation worker, config vars, consolidate tool action, tests (QUAL-01)
- [x] 04-02-PLAN.md -- Dashboard stats + trigger endpoint, search scoring fix (QUAL-01, QUAL-02)

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 2 -> 3 -> 4

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Auto-Sync Hook | 2/2 | Complete | 2026-03-18 |
| 2. Intelligent Learning | 2/2 | Complete | 2026-03-19 |
| 3. CLAUDE.md Integration | 1/1 | Complete | 2026-03-19 |
| 4. Memory Quality | 2/2 | Complete | 2026-03-19 |
