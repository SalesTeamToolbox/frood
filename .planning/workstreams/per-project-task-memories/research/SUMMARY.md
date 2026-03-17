# Project Research Summary

**Project:** Agent42 v1.4 Per-Project/Task Memories
**Domain:** Task-level memory scoping, effectiveness tracking, and recommendations for an existing AI agent platform
**Researched:** 2026-03-17
**Confidence:** HIGH

## Executive Summary

Agent42 v1.4 is an incremental addition to a mature memory system — not a greenfield build. The platform already has Qdrant-backed semantic search, ONNX embeddings, per-project memory namespacing, and a hook-based learning pipeline. The gap is that all memory is scoped to project or global; nothing is scoped to individual tasks, and tools/skills have no outcome data. The recommended approach is to close this gap with three minimal additions: (1) `task_id`/`task_type` payload fields on Qdrant points, (2) an async SQLite store for structured effectiveness data, and (3) a post-task learning extractor that writes to the knowledge collection. All three additions are conservative extensions of existing patterns — the project's hook system, async I/O conventions, and Qdrant payload design already support these changes with minimal surface area.

The key risks are architectural, not technological. Research across this domain confirms that learning systems fail in predictable ways: noise from premature extraction poisons future recommendations, proactive context injection causes "context rot" when similarity thresholds are too low, and tool tracking adds latency if written synchronously to the hot path. All three failure modes have well-documented mitigations — minimum-evidence thresholds, score-gated injection, and fire-and-forget buffered writes — that must be implemented from day one, not added as post-launch tuning. The stack changes are minimal: `aiosqlite` for structured analytics and `instructor` for structured LLM extraction. Everything else already exists.

The correct build order is dictated by data dependencies: task metadata schema must be established before any retrieval, tracking, or extraction is built on top of it. The recommendations engine is the last component because it requires aggregated data to be meaningful — it should not be treated as a simple "add one more module" step but as the validation milestone that proves the entire pipeline works end-to-end.

---

## Key Findings

### Recommended Stack

The existing stack (Qdrant 1.17, ONNX all-MiniLM-L6-v2, Redis 7.2, AsyncOpenAI, aiofiles) covers the majority of v1.4 needs without new infrastructure. Only two net-new dependencies are justified:

**Core technologies (new additions only):**
- `aiosqlite >=0.22.1`: Async SQLite for structured task analytics — tool effectiveness counters, task records, recommendation scores. Qdrant is purpose-built for vectors, not `GROUP BY` / `AVG()` aggregation. Zero new infrastructure; SQLite is already on every deployment.
- `instructor >=1.14.5`: Structured LLM output for learning extraction. Wraps the existing `AsyncOpenAI` client; produces typed `TaskLearning` Pydantic models. Avoids brittle prompt-engineered JSON parsing. Compatible with Pydantic v2 already required by FastAPI.
- Qdrant payload indexes on `task_type` / `task_id` (keyword fields, no new dependency): Configuration change to existing `QdrantStore._ensure_collection()`. Enables O(1) filtered search as the task outcomes collection grows.

**Explicitly rejected:** pandas/numpy, scikit-learn, celery, InfluxDB, LangChain/LlamaIndex, separate Qdrant server for tasks. Each adds infrastructure overhead that is not justified at the expected data volumes (tens to hundreds of tasks/day on a single-tenant platform).

### Expected Features

**Must have — v1.4 core (P1):**
- Task-ID and task_type fields in Qdrant payloads — unlocks all downstream features; zero risk, 1-2 hours of work
- EffectivenessStore (SQLite, append-only) — data layer for all effectiveness features; isolated from existing code
- Automated post-task learning extraction via Stop hook — zero friction; task summary, outcome, tools used written to HISTORY.md + Qdrant
- Task-type-aware retrieval — `task_type_filter` parameter on `search_with_lifecycle()` and `build_context_semantic()`
- Proactive context injection at task start — extend `memory-recall.py` to detect task start and inject top-3 past learnings filtered by task_type

**Should have — after core loop validated (P2):**
- Tool/skill effectiveness aggregation — once EffectivenessStore has >10 real observations
- Recommendations engine — top-3 tools/skills by success_rate for given task_type, injected at task start
- MCP tool usage pattern tracking — PostToolUse hook writing into EffectivenessStore

**Defer — v1.5+ (P3):**
- Task-type confidence scoring (bridges EffectivenessStore and Qdrant lifecycle; high interaction surface)
- Stale learning detection (requires 6+ months of history to avoid false positives)
- Dashboard UI for effectiveness data (expose via MCP tool first; build UI only if demand materializes)

**Anti-features to avoid:** storing every tool invocation in Qdrant (vector index bloat), real-time learning during task execution (memory poisoning risk), LLM-based extraction on every session (cost + feedback loop), cross-project aggregation as default (degrades recommendation precision).

### Architecture Approach

The architecture adds a thin middleware layer (MCPCallTracker, PostTaskLearner, RecoEngine) between existing entry points and the existing memory layer. Existing modules require only small, additive changes — optional `task_id`/`task_type` kwargs threaded through 3 method signatures, a `scroll()` wrapper on QdrantStore, and a ~30-line wrapper on `MCPRegistryAdapter.call_tool()`. Three new modules live in `memory/`: `tool_tracker.py`, `task_learner.py`, and `reco_engine.py`. No new collections are needed except `agent42_task_outcomes` — task metadata is payload fields on existing collections.

**Major components:**
1. `memory/tool_tracker.py` — JSONL append store with in-memory ring buffer; async `record()` / `get_session_log()`; fire-and-forget from MCPRegistryAdapter
2. `memory/task_learner.py` — Post-task LLM summarization; writes to `agent42_knowledge` (text chunks) and `agent42_task_outcomes` (structured outcome record); triggered on task completion as background task
3. `memory/reco_engine.py` — Read-only; aggregates `agent42_task_outcomes` with `scroll()`, ranks by success_rate × recency weight, pulls semantic learnings; injected into ContextAssemblerTool
4. `mcp_registry.py` (modified) — `begin_task()` / `end_task()` protocol; call_tool() wrapper for fire-and-forget tracking
5. `tools/context_assembler.py` (modified) — `task_type` parameter; calls RecoEngine when provided; prepends recommendations to assembled context bundle

**Key patterns:** Payload field extension (optional, additive, no migration), dedicated `agent42_task_outcomes` collection for aggregate records (not text chunks), call tracking via in-memory buffer + background drain (never synchronous in hot path), task context via MCPRegistryAdapter instance state (not threaded through tool signatures).

### Critical Pitfalls

1. **Qdrant payload schema divergence on legacy points** — Existing 10K+ points have no `task_type` field. Queries with required `task_type` filter return zero results. Fix: make all `task_type` filters opt-in (`should`, not `must`); backfill legacy points with `task_type: "legacy"` via `scroll()` + `set_payload()` sweep during Phase 1 init, not startup. Never run migration in embedded mode during active queries.

2. **Learning extraction noise poisons future recommendations** — LLM extracts plausible-sounding but incorrect generalizations from single-task evidence. Single observations get boosted to `confidence: 0.9` through recall. Fix: hard cap `confidence < 0.6` until 3+ independent observations; 48-hour quarantine period for new learnings (`status: "pending"`); structured output schema requiring `tool_name` + `observed_behavior` (reject free-text assertions).

3. **Context rot from proactive injection** — Semantic similarity retrieves topic-adjacent but task-irrelevant content (Flask patterns injected into a Django task). Chroma Research (2025) documents measurable performance degradation. Fix: injection gated at `adjusted_score > 0.80`; 500-token hard cap; task-type exact match before falling back to semantic similarity; inject once at task start, not on every iteration.

4. **Tool tracking adds synchronous latency to the hot path** — Synchronous Qdrant writes in `execute()` add 3-15ms per call in embedded mode; 100-call task adds 300-1500ms overhead visible in MCP stdio transport. Fix: in-memory `deque(maxlen=1000)` buffer; background asyncio drain task every 5 seconds; never await a tracker write in the tool execution path.

5. **Recommendation engine overfits on cold start data** — `success_rate = successes / total` on 5 observations produces 100% confidence from noise. Fix: minimum 5 observations before surfacing any recommendation; Laplace smoothing `(successes + 1) / (total + 2)`; 90-day recency half-life decay; show confidence intervals, not point estimates.

---

## Implications for Roadmap

Based on the dependency graph in FEATURES.md and the build order in ARCHITECTURE.md, a 4-phase structure is the correct approach. The ordering is dictated by data dependencies — nothing downstream works until the payload schema is established.

### Phase 1: Task Metadata Foundation
**Rationale:** Task-ID and task_type are the primitive everything else depends on. Until these fields exist in Qdrant payloads, no filtered retrieval, no extraction, no recommendations are possible. This phase has zero behavior change for existing callers (all new kwargs are optional with empty-string defaults) and no new modules.
**Delivers:** `task_id`/`task_type` as optional payload fields on `agent42_memory`, `agent42_history`, `agent42_knowledge`; `agent42_task_outcomes` collection constant and `scroll()` wrapper; `task_type_filter` on `search_with_lifecycle()`; legacy point backfill with `task_type: "legacy"`.
**Addresses:** task-ID metadata (P1 table stakes), task-type-aware retrieval (P1 table stakes)
**Avoids:** Payload schema divergence pitfall (Pitfall 1), memory bloat from using wrong collections (Pitfall 5)
**Modified files only:** `memory/qdrant_store.py`, `memory/embeddings.py`, `memory/store.py`, `tools/memory_tool.py`

### Phase 2: Effectiveness Tracking and Learning Extraction
**Rationale:** Before recommendations can be built, data must be collected. EffectivenessStore and PostTaskLearner are independent of each other but both depend on Phase 1 payload fields. They can be built in parallel within this phase; ToolTracker is the prerequisite for PostTaskLearner's tool log input.
**Delivers:** `memory/tool_tracker.py` (JSONL + ring buffer); `mcp_registry.py` wrapper for fire-and-forget tracking; `memory/task_learner.py` with quarantine logic and evidence thresholds; `core/work_order.py` hook to trigger PostTaskLearner as background task.
**Addresses:** Automated post-task learning extraction (P1 table stakes), EffectivenessStore (P1 table stakes)
**Avoids:** Tracking latency pitfall (Pitfall 4 — buffered async from day one), learning noise pitfall (Pitfall 2 — evidence threshold in first implementation), circular dependency pitfall (Pitfall 6 — LearningPersistService separate from MemoryStore)
**New files:** `memory/tool_tracker.py`, `memory/task_learner.py`
**Research flag:** LLM extraction prompt engineering — the `instructor` schema and quarantine logic need careful design; recommend a focused research pass on extraction prompt patterns before implementation.

### Phase 3: Proactive Context Injection
**Rationale:** Once Phase 1 provides task-type-filtered retrieval, the injection hook can be built. This is a user-visible feature (agent prompts visibly improve) but carries the highest risk of degrading quality if the score threshold and task-type matching are not implemented correctly. Must be gated and measurable from launch.
**Delivers:** Extended `memory-recall.py` UserPromptSubmit hook detecting task-start signals; top-3 past learnings filtered by inferred task_type injected into context; score threshold gating at 0.80; 500-token cap; inject-once-per-task enforcement (not on every iteration).
**Addresses:** Proactive context injection (P1 table stakes)
**Avoids:** Context rot pitfall (Pitfall 3 — score threshold and task-type exact match mandatory); inject-on-every-iteration anti-pattern
**Research flag:** Task-type detection from prompt text — the hook must infer task_type from the incoming message without an LLM call (latency constraint). Keyword heuristics from the existing IntentClassifier routing layer should be reusable; verify this before implementation.

### Phase 4: Recommendations Engine and Context Integration
**Rationale:** The recommendations engine is the validation milestone for the entire pipeline. It requires aggregated data from Phase 2 to be meaningful. Building it last confirms the full loop (record → retrieve → inject → recommend) works end-to-end with real task data, not synthetic test data.
**Delivers:** `memory/reco_engine.py` with Laplace smoothing, 5-observation minimum gate, recency decay; `tools/context_assembler.py` extended with `task_type` parameter and recommendation injection; `mcp_server.py` wiring of RecoEngine into ContextAssemblerTool at construction.
**Addresses:** Recommendations engine (P2), MCP tool usage pattern tracking (P2), tool/skill effectiveness aggregation (P2)
**Avoids:** Cold-start overfitting pitfall (Pitfall 7 — minimum evidence guards in first implementation)
**New files:** `memory/reco_engine.py`

### Phase Ordering Rationale

- **Payload schema first** because it is the only truly blocking dependency — every other component either writes `task_id`/`task_type` or reads it back.
- **Tracking and extraction together** because they share the `ToolTracker` dependency and have similar test infrastructure (both need mock task completions).
- **Injection before recommendations** because injection is user-observable on every task (value is immediate) while recommendations require accumulated data before they add signal.
- **Recommendations last** as the validation gate — if Phase 1-3 are working correctly, Phase 4 should produce meaningful recommendations within 1-2 weeks of real usage.

### Research Flags

Phases likely needing deeper research during planning:

- **Phase 2 (learning extraction):** The `instructor` extraction prompt schema and quarantine logic need careful design. The failure mode (noisy learnings accumulate confidence) is severe and hard to reverse. Worth a focused session on extraction prompt patterns and the minimum-evidence threshold calibration before implementation begins.
- **Phase 3 (context injection):** Task-type detection from prompt text without an LLM call is a non-trivial NLP problem at the hook layer. The existing IntentClassifier keyword heuristics may be sufficient; verify reusability before building a new classifier.

Phases with standard patterns (skip deep research):

- **Phase 1 (payload schema):** Pure Qdrant configuration + method signature changes. All patterns are established in the existing codebase. No research needed.
- **Phase 4 (recommendations engine):** The aggregation math (Laplace smoothing, recency decay) is well-documented statistics. The Qdrant scroll() API is standard. No novel patterns.

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Existing versions verified via `pip show`; `aiosqlite` and `instructor` verified on PyPI with exact versions; no dependency conflicts identified |
| Features | HIGH | Grounded in existing codebase analysis; competitor comparison (Mem0, LangSmith) confirms Qdrant-payload approach is production-proven; feature dependency graph verified by reading actual module code |
| Architecture | HIGH | Based on direct analysis of all relevant modules; data flows verified against actual method signatures in `memory/store.py`, `memory/qdrant_store.py`, `mcp_registry.py`; existing `_record_recalls()` fire-and-forget pattern confirms async drain is established |
| Pitfalls | HIGH | All 7 critical pitfalls backed by published research (Chroma 2025, arXiv 2505.16067, arXiv 2511.03506) or direct codebase analysis; recovery strategies are specific and actionable |

**Overall confidence:** HIGH

### Gaps to Address

- **IntentClassifier reusability for task-type detection in hooks:** The Phase 3 injection hook needs to infer task_type from prompt text at hook time (UserPromptSubmit). The existing IntentClassifier in the routing layer uses LLM calls — likely too slow for a hook. The keyword heuristics path may be extractable but has not been verified. Validate before Phase 3 planning.

- **`agent42_task_outcomes` vector dimension:** The new collection uses a zero vector (no semantic search needed). Qdrant requires all points in a collection to share the same vector dimension. The existing dimension is 384 (all-MiniLM-L6-v2). Zero vector of length 384 is the correct approach; confirm `qdrant-client 1.17` does not enforce non-zero vector constraint before Phase 1 implementation.

- **Evidence threshold calibration:** The 5-observation minimum and 48-hour quarantine are informed by research but untested against Agent42's actual task cadence. A developer running 3-5 tasks/day may find the quarantine too slow to surface learnings. The thresholds should be config-driven (`LEARNING_MIN_EVIDENCE=5`, `LEARNING_QUARANTINE_HOURS=48`) from day one so they can be tuned without code changes.

---

## Sources

### Primary (HIGH confidence)
- Qdrant payload documentation — `create_payload_index`, payload filtering, `scroll()` API: https://qdrant.tech/documentation/concepts/payload/
- Qdrant vector search filtering patterns: https://qdrant.tech/articles/vector-search-filtering/
- `aiosqlite 0.22.1` PyPI page (released 2025-12-23, Python 3.9+): https://pypi.org/project/aiosqlite/
- `instructor 1.14.5` PyPI page (released 2026-01-29, Pydantic v2 compatible): https://pypi.org/project/instructor/
- Installed package versions verified locally: `qdrant-client 1.17.0`, `redis 7.2.1`, `onnxruntime 1.24.3`
- Direct codebase analysis: `memory/store.py`, `memory/qdrant_store.py`, `memory/consolidation.py`, `memory/project_memory.py`, `memory/embeddings.py`, `tools/memory_tool.py`, `tools/context_assembler.py`, `mcp_registry.py`, `core/work_order.py`

### Secondary (MEDIUM confidence)
- Chroma Research — Context Rot (2025): https://research.trychroma.com/context-rot — confirmed context injection degrades performance above threshold; specific numbers not yet reproduced internally
- HaluMem: Evaluating Hallucinations in Memory Systems of Agents (arXiv 2511.03506): https://arxiv.org/pdf/2511.03506 — topically-related-but-irrelevant retrieved content as primary hallucination driver
- How Memory Management Impacts LLM Agents (arXiv 2505.16067): https://arxiv.org/html/2505.16067v2 — vanilla LLM trajectory evaluator causes more harm than curated dataset; informs evidence threshold design
- Memory in the Age of AI Agents (arXiv 2512.13564) — memory hierarchy and scoping taxonomy
- ContextAgent proactive recall pattern (arXiv 2505.14668) — pre-processor similarity search before LLM invocation

### Tertiary (LOW confidence)
- Agent Observability Overhead Benchmarks (AI Multiple, 2025) — 12-15% latency overhead for synchronous instrumentation; confirms buffered async drain requirement but specific numbers depend on deployment configuration

---
*Research completed: 2026-03-17*
*Ready for roadmap: yes*
