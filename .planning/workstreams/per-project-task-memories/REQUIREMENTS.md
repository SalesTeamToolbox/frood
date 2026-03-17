# Requirements: Agent42 v1.4 Per-Project/Task Memories

**Defined:** 2026-03-17
**Core Value:** Agent42 must always be able to run agents reliably, with tiered provider routing ensuring no single provider outage stops the platform.

## v1.4 Requirements

Requirements for task-aware memory. Each maps to roadmap phases.

### Task Metadata

- [ ] **TMETA-01**: New memory entries include `task_id` and `task_type` in Qdrant payload
- [ ] **TMETA-02**: Existing entries without task fields remain queryable (no regression)
- [ ] **TMETA-03**: Qdrant payload indexes created on `task_type` and `task_id` for filtered queries
- [ ] **TMETA-04**: `begin_task()` / `end_task()` protocol propagates task context through memory operations

### Effectiveness Tracking

- [ ] **EFFT-01**: EffectivenessStore (SQLite) records tool_name, task_type, success, duration_ms, task_id per invocation
- [ ] **EFFT-02**: Tool outcome recording is async-buffered (no latency on tool execution hot path)
- [ ] **EFFT-03**: MCP tool usage tracked via PostToolUse hook or MCPRegistryAdapter wrapper
- [ ] **EFFT-04**: Effectiveness aggregation query returns success_rate, avg_duration by tool+task_type pair
- [ ] **EFFT-05**: Graceful degradation — agent continues without crashing if SQLite is unavailable

### Learning Extraction

- [ ] **LEARN-01**: Stop hook auto-extracts task summary, outcome, tools used, files modified
- [ ] **LEARN-02**: Extracted learnings written to HISTORY.md with `[task_type][task_id][outcome]` format
- [ ] **LEARN-03**: Extracted learnings indexed in Qdrant with task_id and task_type payload fields
- [ ] **LEARN-04**: Learning entries have quarantine period (confidence capped at 0.6 until ≥3 observations)
- [ ] **LEARN-05**: No mid-task memory writes (only after task completion with known outcome)

### Retrieval & Injection

- [x] **RETR-01**: `search_with_lifecycle()` accepts optional `task_type_filter` parameter
- [x] **RETR-02**: `build_context_semantic()` passes task_type through to filtered search
- [ ] **RETR-03**: Proactive context injection on UserPromptSubmit injects top-3 past learnings by inferred task_type
- [ ] **RETR-04**: Injection score threshold (>0.80) prevents irrelevant context injection
- [ ] **RETR-05**: Recommendations engine suggests top-3 tools/skills by success_rate for given task_type
- [ ] **RETR-06**: Recommendations require minimum sample size (>=5 observations per task_type) before surfacing

## v1.5 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Advanced Intelligence

- **CONF-01**: Task-type confidence scoring bridges EffectivenessStore to Qdrant lifecycle scoring
- **CONF-02**: Memories associated with high-effectiveness tools get confidence boost
- **STALE-01**: Stale learning detection flags learnings that conflict with recent outcomes
- **DASH-01**: Dashboard UI for effectiveness data visualization

## Out of Scope

| Feature | Reason |
|---------|--------|
| Store every tool invocation in Qdrant | Vector index bloat, noise drowns signal; use SQLite for structured data |
| Real-time learning during task execution | Mid-task writes pollute index with partial/wrong information; memory poisoning risk |
| LLM-based extraction on every session | 2-5s + token cost per Stop event; most sessions have nothing worth learning |
| Cross-project aggregation as default | Project-specific patterns may not apply elsewhere; project-scoped data first |
| Reinforcement learning / gradient updates | Overkill for Agent42's data volumes (tens-hundreds of tasks, not millions) |
| Dashboard UI for effectiveness | MCP tool interface sufficient for v1.4; add UI only if demand materializes |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| TMETA-01 | Phase 20 | Pending |
| TMETA-02 | Phase 20 | Pending |
| TMETA-03 | Phase 20 | Pending |
| TMETA-04 | Phase 20 | Pending |
| RETR-01 | Phase 20 | Complete |
| RETR-02 | Phase 20 | Complete |
| EFFT-01 | Phase 21 | Pending |
| EFFT-02 | Phase 21 | Pending |
| EFFT-03 | Phase 21 | Pending |
| EFFT-04 | Phase 21 | Pending |
| EFFT-05 | Phase 21 | Pending |
| LEARN-01 | Phase 21 | Pending |
| LEARN-02 | Phase 21 | Pending |
| LEARN-03 | Phase 21 | Pending |
| LEARN-04 | Phase 21 | Pending |
| LEARN-05 | Phase 21 | Pending |
| RETR-03 | Phase 22 | Pending |
| RETR-04 | Phase 22 | Pending |
| RETR-05 | Phase 23 | Pending |
| RETR-06 | Phase 23 | Pending |

**Coverage:**
- v1.4 requirements: 20 total
- Mapped to phases: 20
- Unmapped: 0

---
*Requirements defined: 2026-03-17*
*Last updated: 2026-03-17 after roadmap creation*
