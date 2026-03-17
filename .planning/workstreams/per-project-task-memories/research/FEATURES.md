# Feature Research

**Domain:** Task-level memory, effectiveness tracking, and recommendations for an AI agent platform
**Researched:** 2026-03-17
**Confidence:** HIGH (grounded in existing codebase + verified against external sources)

---

## Context: What Already Exists

This milestone adds to an existing memory system. The following are **not** new:

- `ProjectMemoryStore` — per-project MEMORY.md/HISTORY.md with 60/40 budget split
- `QdrantStore` — lifecycle scoring (confidence, recall_count, decay over 30 days)
- `MemoryTool` — store/recall/log/search/forget/correct/strengthen actions
- Conversation consolidation pipeline — summarize → embed → index
- Semantic deduplication — 0.90 write-time, 0.85 search-time Jaccard threshold
- `memory-learn.py` hook — session-level HISTORY.md append on Stop
- `learning-engine.py` hook — file co-occurrence and task_type_frequency tracking
- Qdrant payload fields: `project_id`, `confidence`, `recall_count`, `status`, `timestamp`

**The gap:** All memory is scoped to project or global. Nothing is scoped to an individual task. Tools/skills have no outcome data. Learning extraction is heuristic-only (file names, session end). Context injection at task start is manual (the agent must call `memory recall` itself).

---

## Feature Landscape

### Table Stakes (Users Expect These)

Features the milestone explicitly defines and that any "learning agent" must have.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Task-ID metadata on memory entries | Task-scoped retrieval is impossible without it; `project_id` exists but no `task_id` | LOW | Add `task_id` and `task_type` fields to Qdrant point payloads. Qdrant already supports arbitrary payload fields. No schema migration needed — new points get the fields, old points don't have them and fall through gracefully |
| Task-type-aware retrieval | "Show me learnings from past Flask builds" requires a `task_type` filter alongside the vector query | LOW | Extend `QdrantStore.search_with_lifecycle()` with a `task_type_filter` parameter. Wire through `ProjectMemoryStore.build_context_semantic()` |
| Tool/skill success+failure recording | Without outcome data, effectiveness tracking is impossible | MEDIUM | New `EffectivenessStore` (SQLite or append-only JSON) recording tool_name, task_type, success bool, duration_ms, task_id per invocation. SQLite preferred — structured queries needed for aggregation |
| Tool/skill effectiveness aggregation | Aggregated win rates and avg durations per (tool, task_type) pair are the raw material for recommendations | MEDIUM | Read-path query over `EffectivenessStore`. Needs groupby tool+task_type with count/success_rate/avg_duration. Keep it simple: no ML, pure SQL or dict aggregation |
| Automated post-task learning extraction | Users should never have to manually trigger learning; hook-based extraction on task completion | MEDIUM | Extend `memory-learn.py` Stop hook OR add a dedicated `task-complete` hook. Extract: task summary, outcome (pass/fail), tools used, duration, files modified. Write to HISTORY.md + Qdrant with task_id tag |
| Proactive context injection at task start | Agent should receive relevant past learnings automatically when a new task begins, not only when it explicitly searches | MEDIUM | Extend `memory-recall.py` UserPromptSubmit hook. Detect task-start signals (new task_id, first message in session). Run semantic search with task_type hint. Inject top-N learnings into context window |

### Differentiators (Competitive Advantage)

Features that go beyond the minimum and make Agent42's memory system meaningfully smarter than storing-and-retrieving text.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Recommendations engine | Agent suggests "use skill X" or "avoid tool Y" based on effectiveness history for this task type — reduces manual configuration, improves outcomes silently | HIGH | Requires effectiveness aggregation to be working first. Output: ranked list of (tool/skill, confidence, basis) for a given task_type. Injected into system prompt or returned by a `recommend` action on MemoryTool |
| MCP tool usage pattern tracking | Tracks which Agent42 MCP tools Claude Code calls during a session, correlates with task outcome — reveals which tools are actually used vs just registered | MEDIUM | PostToolUse hook intercepts MCP tool calls. Record tool_name, task_type, timestamp, success into EffectivenessStore. Differs from in-agent tool tracking: this captures the *LLM* choosing tools, not just the server executing them |
| Task-type confidence scoring | Each (tool, task_type) pair accumulates a confidence score that feeds back into Qdrant lifecycle scoring — memories associated with high-confidence tools get boosted | HIGH | Bridges the effectiveness store and the memory lifecycle. When tool X shows 90%+ success on flask_build tasks, memories tagged with tool X + flask_build get a confidence boost. Complex interaction surface — defer to v2 if scope is tight |
| Stale learning detection | Flags learnings older than N days that conflict with recent outcomes — prevents the agent from acting on outdated patterns (e.g. an API that changed) | HIGH | Requires comparing old memories against new task outcomes semantically. Significant false-positive risk. Worth designing but low priority for first release |

### Anti-Features (Commonly Requested, Often Problematic)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| Store every tool invocation in Qdrant | "More data = better learning" intuition | Vector index bloat, noise drowns signal, embedding cost per call, dedup churn. Research shows "add-all" strategies cause sustained performance decline after initial phases | Store only task-level summaries in Qdrant. Track individual invocations in a lightweight structured store (SQLite/JSON) that never touches the vector index |
| Real-time learning during task execution | Feels responsive — agent updates memory as it works | Mid-task memory updates pollute the index with partial, potentially wrong information. If the task fails, the "learnings" are wrong learnings. Memory poisoning risk is highest here | Write learning only after task completes and outcome is known (pass/fail). This is the same discipline that makes the existing history system reliable |
| LLM-based learning extraction on every session | "Use GPT-4 to summarize what was learned" sounds thorough | Adds 2-5s and LLM cost to every session Stop event. Most sessions have nothing worth learning. Creates a feedback loop where LLM errors become "learnings" | Use heuristic extraction in the hook (tools used, files modified, outcome code, test results). Reserve LLM extraction for flagged high-value tasks (long duration, many iterations, explicit user request) |
| Cross-project effectiveness aggregation as default | Seems like more data = better recommendations | Flask patterns from project A may be wrong for project B with different constraints. Mixing without project context degrades recommendation precision | Recommend from project-scoped data first (60% budget, matching existing memory split). Fall through to global aggregates only when project data is sparse (< 5 observations for this task_type) |
| Reinforcement learning / gradient updates | "Proper" ML feels more rigorous | Overkill for the data volumes Agent42 sees (tens to hundreds of tasks, not millions). Requires training infrastructure. Brittle when distribution shifts. Simple aggregation (success_rate, avg_duration) outperforms ML models until data volume is >10K observations | Bayesian-style confidence scoring: start at 0.5, update with each outcome. Simple, auditable, reversible |
| User-facing "learning dashboard" UI | Admins want to see what the agent has learned | Very high complexity for marginal value in v1.4. The memory already surfaces in the existing Memory page. Dashboard pages have historically been the most bug-prone surface in Agent42 | Expose via MCP tool first (`memory search`, `memory effectiveness`). Add dashboard UI only if user demand materializes |

---

## Feature Dependencies

```
[Task-ID metadata on Qdrant payloads]
    └──required by──> [Task-type-aware retrieval]
    └──required by──> [Automated post-task learning extraction]
    └──required by──> [MCP tool usage pattern tracking]

[Tool/skill success+failure recording]  (EffectivenessStore)
    └──required by──> [Tool/skill effectiveness aggregation]
                          └──required by──> [Recommendations engine]
                          └──enhances──>   [Task-type confidence scoring]

[Automated post-task learning extraction]
    └──enhances──> [Task-type-aware retrieval]  (more typed entries = better filtered search)

[Proactive context injection at task start]
    └──depends on──> [Task-type-aware retrieval]  (needs task_type to filter what to inject)
    └──optionally enhanced by──> [Recommendations engine]  (inject recs alongside memories)

[Task-type confidence scoring]
    └──depends on──> [Tool/skill effectiveness aggregation]
    └──modifies──> [QdrantStore lifecycle scoring]  (existing system)
    └──conflicts with (complexity risk)──> [Automated post-task learning extraction]  (don't build both in same phase)
```

### Dependency Notes

- **Task-ID metadata is the foundation:** Every other feature in this milestone either writes `task_id`/`task_type` to Qdrant or reads it back. Build this first and nothing else is blocked.
- **EffectivenessStore is independent of Qdrant:** It does not need to be a vector store. SQLite is the right tool — it handles aggregation queries natively, survives Qdrant being unavailable, and requires no embedding budget.
- **Recommendations require aggregation, not the other way around:** Don't build the recommendation output before the aggregation query is solid. A recommendation based on 2 observations is noise.
- **Proactive injection needs task_type detection:** The hook must identify task type from the incoming prompt (reuse `IntentClassifier` or keyword heuristics from the existing routing layer) before it can inject the right memories.
- **Task-type confidence scoring conflicts with scope:** It touches both EffectivenessStore and QdrantStore lifecycle scoring simultaneously. Defer to v1.4.x — build it after the core loop (record → aggregate → recommend) is validated.

---

## MVP Definition

### Launch With (v1.4 core)

Minimum feature set that delivers observable value and validates the architecture.

- [ ] **Task-ID and task_type fields in Qdrant payloads** — without this nothing else works; zero risk, 1-2 hours
- [ ] **EffectivenessStore** (SQLite, append-only) recording tool_name, task_type, success, duration_ms, task_id — the data layer for all effectiveness features; isolated from existing code
- [ ] **Automated post-task learning extraction** via Stop hook — task summary, outcome, tools used written to HISTORY.md + Qdrant with task_id; no user action needed
- [ ] **Task-type-aware retrieval** — `task_type_filter` added to `search_with_lifecycle()` and wired through `build_context_semantic()`
- [ ] **Proactive context injection at task start** — extend `memory-recall.py` to detect task start and inject top-3 past learnings filtered by task_type

### Add After Validation (v1.4.x)

Add when the core loop (record → retrieve → inject) is confirmed working on real tasks.

- [ ] **Tool/skill effectiveness aggregation query** — once EffectivenessStore has >10 real observations, add the aggregation read path (success_rate, avg_duration by tool+task_type)
- [ ] **Recommendations engine** (simple: top-3 tools/skills by success_rate for given task_type, injected into task start context) — triggers when EffectivenessStore has sufficient data per task_type
- [ ] **MCP tool usage pattern tracking** — PostToolUse hook writing into EffectivenessStore; adds signal volume without changing core logic

### Future Consideration (v1.5+)

Defer until v1.4 core is proven and real usage data exists.

- [ ] **Task-type confidence scoring** — bridges EffectivenessStore → Qdrant lifecycle; high interaction surface, significant test coverage needed; value unclear until recommendations are working
- [ ] **Stale learning detection** — requires semantic comparison of old memories vs new outcomes; high false-positive risk; build only after the memory base has 6+ months of history
- [ ] **Dashboard UI for effectiveness data** — defer until MCP tool interface shows user demand

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Task-ID metadata on Qdrant payloads | HIGH (unlocks everything) | LOW | P1 |
| EffectivenessStore (SQLite) | HIGH (unlocks recommendations) | LOW | P1 |
| Automated post-task learning extraction | HIGH (zero friction learning) | MEDIUM | P1 |
| Task-type-aware retrieval | HIGH (precision recall) | LOW | P1 |
| Proactive context injection | HIGH (zero friction context) | MEDIUM | P1 |
| Tool/skill effectiveness aggregation | MEDIUM (read path, needs data) | LOW | P2 |
| Recommendations engine | HIGH (active guidance) | MEDIUM | P2 |
| MCP tool usage pattern tracking | MEDIUM (richer signal) | MEDIUM | P2 |
| Task-type confidence scoring | LOW (marginal lift over existing lifecycle) | HIGH | P3 |
| Stale learning detection | LOW (premature without history) | HIGH | P3 |
| Dashboard UI for effectiveness | LOW (MCP tool sufficient) | HIGH | P3 |

**Priority key:**
- P1: Must have for v1.4 launch
- P2: Add after core loop validated
- P3: Future consideration

---

## Competitor Feature Analysis

| Feature | Mem0 (open source) | LangSmith / LangChain | Agent42 Approach |
|---------|--------------------|-----------------------|------------------|
| Task-scoped memory | Session-level isolation with user_id/agent_id/run_id hierarchy | LangSmith traces have run_id but memory not scoped to traces | Add task_id + task_type to existing Qdrant payloads; lean on existing project_id scoping |
| Metadata filtering | Full operators (eq, in, gte, contains) in Mem0 1.0+ | Filter by run metadata via LangSmith API | Extend existing `FieldCondition` filters in `QdrantStore.search_with_lifecycle()` |
| Effectiveness tracking | None built-in (mem0 is memory-only) | LangSmith has eval metrics but requires manual annotation | EffectivenessStore in SQLite — lightweight, no external dependency |
| Automated learning extraction | Mem0 uses LLM to extract entities/facts from messages automatically | LangSmith requires explicit eval runs | Hook-based heuristic extraction (no LLM cost), LLM extraction as opt-in for flagged tasks |
| Proactive injection | Pre-processor similarity search before LLM call (documented pattern) | Not a native feature — requires manual RAG setup | Extend existing `memory-recall.py` hook — already fires on every UserPromptSubmit |
| Recommendations | None (mem0 is storage, not recommendation) | None native | New capability: aggregate EffectivenessStore, surface top tools/skills for task_type |

**Key insight:** Mem0's metadata filtering implementation confirms the Qdrant-payload approach is correct and production-proven. The effectiveness tracking and recommendations engine are genuinely novel — neither Mem0 nor LangSmith offer this out of the box. That's the actual differentiator for v1.4.

---

## "Done" Criteria Per Feature

Concrete, testable definitions of done for each P1 feature:

**Task-ID metadata on Qdrant payloads**
- New memory entries written during a task include `task_id` and `task_type` in their Qdrant payload
- Existing entries without these fields are not broken (graceful absence)
- Unit test: write entry with task_id, retrieve it, verify payload contains task_id

**EffectivenessStore**
- SQLite file at `.agent42/effectiveness.db` with table: `tool_calls(id, task_id, task_type, tool_name, success, duration_ms, timestamp)`
- Records are written after each tool execution (success or failure)
- Graceful degradation: if SQLite is unavailable, agent continues without crashing
- Unit test: write 10 records, query success_rate for a tool+task_type pair

**Automated post-task learning extraction**
- On Stop event with a detected task completion, a structured entry is written to HISTORY.md with: `[task_type][task_id][outcome] summary`
- Entry is indexed in Qdrant with task_id and task_type in payload
- No user action required — fully automatic
- Integration test: simulate Stop event, verify HISTORY.md and Qdrant have new entry

**Task-type-aware retrieval**
- `search_with_lifecycle(task_type_filter="flask_build")` returns only entries tagged with that task_type
- Without filter, behavior is identical to current (no regression)
- Unit test: insert entries with two different task_types, verify filter returns only matching entries

**Proactive context injection**
- On UserPromptSubmit, if a new task is detected (keyword heuristic or new task_id), top-3 past learnings filtered by inferred task_type are prepended to context
- If no relevant learnings exist, no injection occurs (no noise)
- Injection is visible in the context payload (testable via hook stderr output)

---

## Sources

- [Mem0 Enhanced Metadata Filtering docs](https://docs.mem0.ai/open-source/features/metadata-filtering) — confirms Qdrant-payload filtering approach
- [Memory in the Age of AI Agents (arxiv 2512.13564)](https://arxiv.org/abs/2512.13564) — memory hierarchy and scoping taxonomy
- [AI Agent Anti-Patterns: Architectural Pitfalls (Medium, 2026)](https://achan2013.medium.com/ai-agent-anti-patterns-part-1-architectural-pitfalls-that-break-enterprise-agents-before-they-32d211dded43) — add-all memory failure mode, invisible state
- [Memory poisoning in AI agents (Christian Schneider)](https://christian-schneider.net/blog/persistent-memory-poisoning-in-ai-agents/) — mid-task write risks, MINJA attack
- [ContextAgent: Context-Aware Proactive LLM Agents (arxiv 2505.14668)](https://arxiv.org/abs/2505.14668) — proactive recall pattern (pre-processor similarity search before LLM invocation)
- [Context Engineering for AI Agents (Kubiya, 2025)](https://www.kubiya.ai/blog/context-engineering-ai-agents) — inject only relevant tools/memories, not everything
- [AI Agent Metrics: How Elite Teams Evaluate (Galileo)](https://galileo.ai/blog/ai-agent-metrics) — tool selection effectiveness metrics, 15% teams achieve elite coverage
- [Build agents from experiences using Amazon Bedrock AgentCore episodic memory (AWS)](https://aws.amazon.com/blogs/machine-learning/build-agents-to-learn-from-experiences-using-amazon-bedrock-agentcore-episodic-memory/) — episodic memory for task-level learning
- Existing Agent42 codebase: `memory/qdrant_store.py`, `memory/project_memory.py`, `tools/memory_tool.py`, `.claude/hooks/memory-learn.py`, `.claude/hooks/learning-engine.py`

---
*Feature research for: Agent42 v1.4 Per-Project/Task Memories milestone*
*Researched: 2026-03-17*
