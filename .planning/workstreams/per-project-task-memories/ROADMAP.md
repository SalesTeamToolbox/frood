# Roadmap: Agent42 v1.4 Per-Project/Task Memories

**Milestone:** v1.4 Per-Project/Task Memories
**Created:** 2026-03-17
**Granularity:** Standard
**Requirements covered:** 20/20

---

## Phases

- [x] **Phase 20: Task Metadata Foundation** - Establish task_id/task_type payload schema and type-aware retrieval
- [x] **Phase 21: Effectiveness Tracking and Learning Extraction** - Async tool tracking, SQLite store, and post-task learning pipeline
- [x] **Phase 22: Proactive Context Injection** - Inject past learnings into new tasks at UserPromptSubmit (completed 2026-03-22)
- [x] **Phase 23: Recommendations Engine** - Surface tool/skill recommendations from aggregated effectiveness data (completed 2026-03-22)

---

## Phase Details

### Phase 20: Task Metadata Foundation
**Goal**: Task context fields exist in Qdrant payloads and filtered retrieval works for downstream consumers
**Depends on**: Nothing (first phase of this milestone)
**Requirements**: TMETA-01, TMETA-02, TMETA-03, TMETA-04, RETR-01, RETR-02
**Success Criteria** (what must be TRUE):
  1. A memory entry created during a task includes `task_id` and `task_type` in its Qdrant payload, visible via direct Qdrant inspection
  2. Existing memory entries without task fields are still returned by searches (no regression in recall)
  3. `search_with_lifecycle()` called with `task_type_filter="coding"` returns only entries tagged `task_type: "coding"` — not entries tagged other types
  4. Calling `begin_task()` sets task context so that all subsequent memory writes in that session inherit the task_id and task_type without the caller passing them explicitly
  5. Qdrant `task_type` and `task_id` payload indexes exist — a filtered query on 100K points runs in under 50ms
**Plans**: 1 of 1 (20-01-PLAN.md complete)

### Phase 21: Effectiveness Tracking and Learning Extraction
**Goal**: Every completed task produces structured effectiveness records and a durable learning entry, with zero latency added to the tool execution path
**Depends on**: Phase 20 (task_id/task_type fields must exist before writing to them)
**Requirements**: EFFT-01, EFFT-02, EFFT-03, EFFT-04, EFFT-05, LEARN-01, LEARN-02, LEARN-03, LEARN-04, LEARN-05
**Success Criteria** (what must be TRUE):
  1. After a task completes, the SQLite EffectivenessStore contains a row for each tool invoked during that task, with tool_name, task_type, success flag, duration_ms, and task_id
  2. Calling a tool mid-task does not add measurable latency — tracking writes are fire-and-forget (the tool call returns before any SQLite write is awaited)
  3. After task completion, HISTORY.md contains a new entry in `[task_type][task_id][outcome]` format summarizing what happened
  4. The new HISTORY.md entry is also indexed in Qdrant with the correct task_id and task_type payload fields
  5. A brand-new learning entry is not surfaced to the agent until at least 3 independent observations support it (confidence capped at 0.6 until threshold met)
  6. If the SQLite database file is missing or unwritable, tool execution continues normally — no exception propagates to the agent
**Plans**: 2 of 2 complete (21-01: EFFT-01 through EFFT-05; 21-02: LEARN-01 through LEARN-05)

### Phase 22: Proactive Context Injection
**Goal**: When a user starts a new task, relevant past learnings are automatically injected into context before the agent responds
**Depends on**: Phase 20 (task-type-filtered retrieval), Phase 21 (learning entries must exist to inject)
**Requirements**: RETR-03, RETR-04
**Success Criteria** (what must be TRUE):
  1. When a user prompt signals the start of a new coding task, the agent's context includes up to 3 past learnings tagged `task_type: "coding"` — without any user action
  2. A past learning with a semantic similarity score below 0.80 is never injected, even if it matches the task type
  3. Injected context does not exceed 500 tokens, regardless of how many past learnings are available
  4. Past learnings are injected once when the task starts — not re-injected on every subsequent message in the same task
**Plans:** 2/2 plans complete

Plans:
- [x] 22-01-PLAN.md — Learnings retrieval API endpoint (GET /api/learnings/retrieve with score gate, quarantine filter, token cap)
- [x] 22-02-PLAN.md — Proactive injection UserPromptSubmit hook (keyword task-type inference, session-once guard, formatted stderr output)

### Phase 23: Recommendations Engine
**Goal**: Agent42 recommends which tools and skills to use based on aggregated effectiveness data from past tasks of the same type
**Depends on**: Phase 21 (EffectivenessStore must have real data), Phase 22 (injection pipeline established)
**Requirements**: RETR-05, RETR-06
**Success Criteria** (what must be TRUE):
  1. For a given task_type with 5+ recorded observations, the agent receives a ranked list of up to 3 tool/skill recommendations at task start, based on historical success_rate
  2. No recommendations are surfaced for a task_type with fewer than 5 recorded observations — the engine stays silent rather than extrapolating from noise
  3. The aggregation query for a given task_type returns the correct success_rate and avg_duration from the EffectivenessStore records
**Plans:** 2/2 plans complete

Plans:
- [x] 23-01-PLAN.md — Recommendations data layer and API endpoint (get_recommendations() method, GET /api/recommendations/retrieve, config field, tests)
- [x] 23-02-PLAN.md — Hook extension for recommendations injection (fetch_recommendations(), format output, updated main() dual-call flow, hook tests)

---

## Progress Table

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 20. Task Metadata Foundation | 2/2 | Complete    | 2026-03-17 |
| 21. Effectiveness Tracking and Learning Extraction | 2/2 | Complete    | 2026-03-18 |
| 22. Proactive Context Injection | 2/2 | Complete   | 2026-03-22 |
| 23. Recommendations Engine | 2/2 | Complete   | 2026-03-22 |

---

## Coverage Map

| Requirement | Phase |
|-------------|-------|
| TMETA-01 | Phase 20 |
| TMETA-02 | Phase 20 |
| TMETA-03 | Phase 20 |
| TMETA-04 | Phase 20 |
| RETR-01 | Phase 20 |
| RETR-02 | Phase 20 |
| EFFT-01 | Phase 21 |
| EFFT-02 | Phase 21 |
| EFFT-03 | Phase 21 |
| EFFT-04 | Phase 21 |
| EFFT-05 | Phase 21 |
| LEARN-01 | Phase 21 |
| LEARN-02 | Phase 21 |
| LEARN-03 | Phase 21 |
| LEARN-04 | Phase 21 |
| LEARN-05 | Phase 21 |
| RETR-03 | Phase 22 |
| RETR-04 | Phase 22 |
| RETR-05 | Phase 23 |
| RETR-06 | Phase 23 |

**Total mapped:** 20/20

---

## Key Constraints

- All tracking writes must be async-buffered (EFFT-02) — no synchronous writes on the tool execution hot path
- No mid-task memory writes (LEARN-05) — learning extraction runs only after task completion with known outcome
- Quarantine period (LEARN-04) is architectural from day one — cannot be retrofitted
- Proactive injection score threshold (RETR-04 >= 0.80) prevents context rot — mandatory from first deploy
- Recommendations minimum sample size (RETR-06 >= 5 observations) prevents cold-start overfitting

---
*Roadmap created: 2026-03-17*
