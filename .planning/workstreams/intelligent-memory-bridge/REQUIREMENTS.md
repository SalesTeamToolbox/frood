# Requirements: Intelligent Memory Bridge

**Defined:** 2026-03-18
**Core Value:** When Agent42 is installed, its enhanced Qdrant-backed memory becomes the primary memory system automatically — no user intervention needed.

## v1 Requirements

### Auto-Sync

- [ ] **SYNC-01**: When Claude Code writes to `~/.claude/projects/.../memory/`, the content is automatically stored in Agent42 Qdrant
- [ ] **SYNC-02**: Sync handles all memory file types (user, feedback, project, reference)
- [ ] **SYNC-03**: Dedup prevents storing identical content that already exists in Qdrant
- [ ] **SYNC-04**: Sync failure is silent (never blocks Claude Code's Write operation)

### Intelligent Learning

- [ ] **LEARN-01**: Stop hook extracts architectural decisions from conversation and stores in Qdrant
- [ ] **LEARN-02**: Stop hook extracts user feedback/corrections and stores with "feedback" type
- [ ] **LEARN-03**: Stop hook extracts deployment/debugging patterns from tool usage
- [ ] **LEARN-04**: Stop hook detects repeated patterns across sessions (confidence boosting)
- [ ] **LEARN-05**: Extraction is category-aware (security fix vs feature vs refactor vs deploy)

### CLAUDE.md Integration

- [ ] **INTEG-01**: CLAUDE.md instructs Claude to use `agent42_memory search` before answering from memory
- [ ] **INTEG-02**: CLAUDE.md instructs Claude to use `agent42_memory store` alongside its built-in memory writes
- [ ] **INTEG-03**: Setup.sh generates CLAUDE.md memory section automatically when Agent42 is installed

### Memory Quality

- [ ] **QUAL-01**: Agent42 MEMORY.md is periodically consolidated (remove duplicates, merge related entries)
- [ ] **QUAL-02**: Search results include confidence scores and recall counts for relevance ranking

## Out of Scope

| Feature | Reason |
|---------|--------|
| Replace Claude Code's built-in memory entirely | CC's auto-memory is system-level, can't be disabled — augment instead |
| Cross-machine memory sync | Handled by existing node_sync tool, not this workstream |
| Real-time memory streaming | Batch sync at write-time and stop-time is sufficient |
| LLM-powered memory summarization | Would require API calls in hooks, adding latency and cost |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| SYNC-01 | — | Pending |
| SYNC-02 | — | Pending |
| SYNC-03 | — | Pending |
| SYNC-04 | — | Pending |
| LEARN-01 | — | Pending |
| LEARN-02 | — | Pending |
| LEARN-03 | — | Pending |
| LEARN-04 | — | Pending |
| LEARN-05 | — | Pending |
| INTEG-01 | — | Pending |
| INTEG-02 | — | Pending |
| INTEG-03 | — | Pending |
| QUAL-01 | — | Pending |
| QUAL-02 | — | Pending |

**Coverage:**
- v1 requirements: 14 total
- Mapped to phases: 0
- Unmapped: 14 ⚠️

---
*Requirements defined: 2026-03-18*
*Last updated: 2026-03-18 after initial definition*
