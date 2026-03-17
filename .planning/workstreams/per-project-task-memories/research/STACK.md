# Stack Research

**Domain:** Task-level memory scoping, effectiveness tracking, automated learning extraction, recommendations engine — added to an existing Python AI agent platform
**Researched:** 2026-03-17
**Confidence:** HIGH (existing stack verified by installed versions; new additions verified via PyPI and official Qdrant docs)

---

## What Already Covers the New Features (Do Not Re-Add)

The existing stack handles the majority of what v1.4 needs. These are NOT gaps:

| Capability | Existing Solution | Status |
|-----------|-------------------|--------|
| Vector storage + semantic search | `qdrant-client 1.17.0` (installed) | Already in requirements (optional) |
| Semantic embeddings | `onnxruntime 1.24.3` + `tokenizers` + all-MiniLM-L6-v2 (384 dims) | Already installed |
| Per-project memory namespacing | `ProjectMemoryStore` + `project_id` Qdrant payload field | Already built |
| Memory lifecycle scoring | `recall_count`, `confidence`, `last_recalled` in Qdrant payloads | Already in QdrantStore |
| Session caching + TTL | `redis 7.2.1` (installed) | Already in requirements (optional) |
| Async I/O | `aiofiles`, `asyncio` throughout | Already the project standard |
| LLM calls | `openai>=1.40.0` via AsyncOpenAI | Already the project standard |
| Hook system for post-task events | `.claude/hooks/` pattern (memory-learn.py, memory-recall.py) | Already established |

---

## Recommended Stack (New Additions Only)

### Core Technologies (New)

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| `aiosqlite` | `>=0.22.1` | Structured analytics store for task metadata, tool effectiveness counters, and recommendation scores | SQLite is already on every deployment (stdlib backend); aiosqlite makes it async-native matching the project's all-async I/O pattern. Zero new infrastructure — no additional server or Docker container. Qdrant is purpose-built for vectors, not row-level analytics counters; SQLite fills the relational gap. Released 2025-12-23, Python 3.9+ |
| Qdrant payload indexes (`task_type`, `task_id` keyword fields) | Qdrant 1.17+ feature (already installed) | Enable O(1) filtered semantic search by task type ("show learnings from past Flask builds") | `create_payload_index(field_schema="keyword")` transforms the existing `project` filter pattern to also filter on `task_type`. No new dependency — configuration change only. Without indexes, Qdrant scans all vectors for filter cardinality, causing slow filtered searches as collection grows |

### Supporting Libraries (New)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `instructor` | `>=1.14.5` | Structured LLM output for automated learning extraction | Use in the post-task learning extractor to parse task outcomes into typed `TaskLearning` Pydantic models. Wraps the existing `AsyncOpenAI` client — no new provider or auth needed. Built on Pydantic (already used in FastAPI routes). 3M+ monthly downloads, supports all 15+ providers Agent42 uses. Avoids brittle prompt-engineered JSON parsing |

### Development Tools (No New Additions Needed)

The existing `pytest`, `pytest-asyncio`, `ruff` toolchain is sufficient. `aiosqlite` has no special test infrastructure requirements — use `tmp_path` fixture with in-memory SQLite (`:memory:`) for unit tests.

---

## What NOT to Add

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| `pandas` / `numpy` for analytics | 50-200 MB install for what is ~30 lines of SQL aggregation. Overkill for per-task counters with <10K rows | Raw `aiosqlite` queries with `GROUP BY` and `AVG()` |
| `scikit-learn` for recommendations | 30+ MB for a recommendation engine that is: count tool uses by task_type, sort by success rate. No matrix factorization needed | Weighted scoring in Python: `score = success_rate * recency_weight` — 10 lines |
| External time-series DB (InfluxDB, TimescaleDB) | New infrastructure, new client, ops overhead. The event volume (dozens of tasks/day) does not justify a dedicated TSDB | `aiosqlite` with a `timestamp` column and SQLite's built-in datetime functions |
| `celery` / background task queue for learning extraction | Over-engineered for a post-task hook that runs once after task completion. Adds broker dependency (Redis already used for sessions, not task queuing) | `asyncio.create_task()` to fire the extraction coroutine after agent loop exits — same pattern used in existing hook system |
| Separate embedding model for task metadata | ONNX all-MiniLM-L6-v2 already installed and producing 384-dim vectors. Task summaries are short text — perfectly suited | Reuse existing `EmbeddingStore` |
| `langchain` / `llamaindex` | Would compete with Agent42's own tool/memory abstractions and add 50+ transitive dependencies | Direct `instructor` + `AsyncOpenAI` (already the project pattern) |
| Qdrant Cloud / separate Qdrant server just for tasks | Current embedded Qdrant at `.agent42/qdrant/` is sufficient; task metadata goes in SQLite, not Qdrant | Existing embedded QdrantStore |

---

## Integration Points With Existing Stack

### 1. Qdrant Payload Augmentation (No New Dependency)

Add `task_id` and `task_type` to every Qdrant payload upsert that originates from a task context. The existing `upsert_vector` / `upsert_vectors` methods accept a `payload: dict` argument — extend callers to pass these fields. Then create payload indexes at collection init time:

```python
# In QdrantStore._ensure_collection() after creating each collection:
self._client.create_payload_index(
    collection_name=name,
    field_name="task_type",
    field_schema="keyword",
)
self._client.create_payload_index(
    collection_name=name,
    field_name="task_id",
    field_schema="keyword",
)
```

Filter usage follows existing `FieldCondition` / `MatchValue` pattern already in `QdrantStore.search()`.

### 2. aiosqlite Task Analytics DB

New module `memory/task_analytics.py`. Single SQLite file at `{workspace_dir}/task_analytics.db`. Three tables:

- `task_records` — one row per completed task: `task_id`, `task_type`, `project_id`, `agent_name`, `started_at`, `completed_at`, `success`, `duration_s`, `tool_calls_json`
- `tool_effectiveness` — aggregated: `tool_name`, `task_type`, `total_calls`, `success_count`, `avg_duration_ms`, `last_used_at`
- `skill_effectiveness` — aggregated: `skill_name`, `task_type`, `activation_count`, `task_success_rate`

This is purely structured/relational data. Putting it in Qdrant would waste vector space on non-semantic data. Putting it in Redis loses persistence after TTL.

### 3. instructor for Post-Task Learning Extraction

New module `memory/learning_extractor.py`. Triggered via the existing hook pattern (or `asyncio.create_task()` in the agent iteration loop after task completion). Uses `instructor.from_openai(AsyncOpenAI(...))` — the same client already instantiated in `providers/`. Extract a `TaskLearning` Pydantic model:

```python
class TaskLearning(BaseModel):
    summary: str                    # 1-2 sentence outcome
    tools_effective: list[str]      # Tools that worked well
    tools_ineffective: list[str]    # Tools that failed or were slow
    skills_activated: list[str]     # Skills that contributed
    patterns: list[str]             # Reusable patterns discovered
    pitfalls: list[str]             # What went wrong
    confidence: float               # 0.0–1.0 extraction confidence
```

The extracted learning is then stored via the existing `MemoryStore.log_event_semantic()` (for Qdrant indexing with `task_id`/`task_type` payload) AND written to the new `task_records` SQLite table.

### 4. Recommendation Engine (Pure Python, No New Library)

New module `memory/recommendations.py`. Query pattern: given a new task of type T, query `tool_effectiveness` WHERE `task_type = T` ORDER BY `(success_count / total_calls) * recency_weight DESC`. No ML required — the signal is explicit success/failure counts from `task_records`. The ONNX embeddings are used for semantic similarity between task descriptions (existing capability), not for the recommendation score itself.

---

## Installation

```bash
# New runtime dependency
pip install aiosqlite>=0.22.1
pip install instructor>=1.14.5

# Already installed — no action needed:
# qdrant-client 1.17.0
# onnxruntime 1.24.3
# redis 7.2.1
# openai (via AsyncOpenAI)
```

Add to `requirements.txt`:
```
# Task analytics (v1.4)
aiosqlite>=0.22.1
instructor>=1.14.5
```

---

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| `aiosqlite` for analytics DB | Redis hashes/sorted sets | Only if you need sub-ms analytics lookups AND are already paying for Redis persistence; complexity not worth it here |
| `aiosqlite` for analytics DB | Qdrant for all storage | Qdrant is not designed for aggregate queries (COUNT, AVG, GROUP BY). Forcing relational analytics into a vector DB means fetching all points and aggregating in Python — worse than SQLite |
| `instructor` for extraction | Raw JSON mode (`response_format={"type": "json_object"}`) | If the codebase already has stable, well-tested JSON parsing prompts; instructor's retry-on-validation-failure is worth the dep for a new extraction path |
| `instructor` for extraction | Fine-tuned classifier | Only if extraction quality is unacceptably low after prompt tuning; adds training data management overhead |
| Weighted score for recommendations | Collaborative filtering (scikit-learn Surprise) | Only at 100K+ task records with diverse agent/user populations — overkill for a single-tenant agent platform |

---

## Stack Patterns by Variant

**If Qdrant is unavailable (JSON fallback mode):**
- Task metadata still flows to `aiosqlite` — analytics and recommendations work fully
- Semantic search degrades to grep (existing fallback)
- Post-task learnings are written to `MEMORY.md` / `HISTORY.md` only (existing behavior)

**If Redis is unavailable:**
- No impact on task analytics or learning extraction
- Embedding cache misses — slightly slower extraction (existing behavior)

**If LLM API is unavailable at task completion:**
- Learning extraction is skipped for that task (non-blocking — wrapped in try/except)
- Raw task record (duration, success, tool_calls) still written to `aiosqlite`
- Recommendations still work from existing effectiveness data

---

## Version Compatibility

| Package | Compatible With | Notes |
|---------|-----------------|-------|
| `aiosqlite>=0.22.1` | Python 3.9+ | Agent42 requires Python 3.11+ — fully compatible |
| `instructor>=1.14.5` | `openai>=1.40.0` | Agent42 already pins `openai>=1.40.0` — compatible. instructor wraps the existing client |
| Qdrant payload indexes | `qdrant-client 1.17.0` | `create_payload_index` available since qdrant-client 0.9.x. UUID index type requires 1.11+, not needed here |
| `instructor` + Pydantic v2 | FastAPI (which requires Pydantic v2) | instructor 1.14.x uses Pydantic v2 — same version FastAPI uses |

---

## Sources

- [qdrant.tech/documentation/concepts/indexing/](https://qdrant.tech/documentation/concepts/indexing/) — Payload index types and `create_payload_index` API; keyword and integer index performance — HIGH confidence (official Qdrant docs)
- [qdrant.tech/articles/vector-search-filtering/](https://qdrant.tech/articles/vector-search-filtering/) — Agent payload design patterns (agent_id, task_type, success_status) — HIGH confidence (official Qdrant blog)
- [pypi.org/project/aiosqlite/](https://pypi.org/project/aiosqlite/) — v0.22.1, released 2025-12-23, Python 3.9+ — HIGH confidence (official PyPI)
- [pypi.org/project/instructor/](https://pypi.org/project/instructor/) — v1.14.5, released 2026-01-29, Pydantic v2 compatible — HIGH confidence (official PyPI)
- [python.useinstructor.com](https://python.useinstructor.com/) — Multi-provider support including OpenAI-compatible APIs — HIGH confidence (official docs)
- Installed package versions verified locally: `qdrant-client 1.17.0`, `redis 7.2.1`, `onnxruntime 1.24.3` — HIGH confidence (pip show)

---

*Stack research for: Agent42 v1.4 Per-Project/Task Memories — incremental additions to existing Python/Qdrant/Redis/ONNX stack*
*Researched: 2026-03-17*
