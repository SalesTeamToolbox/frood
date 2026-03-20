---
phase: 02-intelligent-learning
plan: 02
subsystem: memory
tags: [qdrant, instructor, pydantic, openrouter, gemini, asyncio, stop-hook, knowledge-extraction]

# Dependency graph
requires:
  - phase: 02-01-intelligent-learning
    provides: knowledge-learn.py hook, knowledge-learn-worker.py, KNOWLEDGE collection, /api/knowledge/learn call contract
provides:
  - POST /api/knowledge/learn endpoint in dashboard/server.py with instructor + Pydantic extraction
  - KNOWLEDGE collection payload indexes (learning_type, category) in qdrant_store.py
  - 5 new TestKnowledgeIndexes tests verifying index creation behavior
affects: [dashboard-knowledge-panel, knowledge-recall, memory-search-by-type]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "LLM extraction via asyncio.to_thread(_sync_extract) — instructor sync call wrapped to avoid blocking FastAPI event loop"
    - "Provider fallback: OPENROUTER_API_KEY / GEMINI_API_KEY -> openrouter.ai with gemini-2.0-flash-001; OPENAI_API_KEY -> gpt-4o-mini direct"
    - "Pydantic models defined inside endpoint function — avoids module-level import side effects for rarely-used types"
    - "KNOWLEDGE payload indexes: _ensure_collection dispatches to _ensure_knowledge_indexes for learning_type + category KEYWORD fields"

key-files:
  created:
    - .planning/workstreams/intelligent-memory-bridge/phases/02-intelligent-learning/02-02-SUMMARY.md
  modified:
    - dashboard/server.py
    - memory/qdrant_store.py
    - tests/test_knowledge_learn.py

key-decisions:
  - "Pydantic models (ExtractedLearning, ExtractionResult) defined inside endpoint function to avoid module-level import issues and stay co-located with the instructor call that uses them"
  - "asyncio.to_thread wraps the instructor sync call — instructor's OpenAI client is synchronous; blocking the FastAPI event loop would degrade all concurrent requests"
  - "Provider selection: OPENROUTER_API_KEY -> openrouter.ai/gemini-2.0-flash-001; OPENAI_API_KEY -> gpt-4o-mini — matches pitfall #90 routing guidance (avoid dead OR free models)"

patterns-established:
  - "knowledge-extraction pattern: endpoint parses session context -> builds prompt -> to_thread(sync instructor call) -> filter trivials -> return learnings list"
  - "payload-index pattern: _ensure_collection checks suffix and dispatches to type-specific _ensure_*_indexes method (task indexes for MEMORY/HISTORY, knowledge indexes for KNOWLEDGE)"

requirements-completed: [LEARN-01, LEARN-02, LEARN-03, LEARN-04, LEARN-05]

# Metrics
duration: 14min
completed: 2026-03-19
---

# Phase 02 Plan 02: Knowledge-Learn API Endpoint and Qdrant Indexes Summary

POST /api/knowledge/learn endpoint with instructor + Pydantic structured extraction via asyncio.to_thread, and KNOWLEDGE collection payload indexes for learning_type and category filtered queries

## Performance

- **Duration:** 14 min
- **Started:** 2026-03-19T04:29:05Z
- **Completed:** 2026-03-19T04:43:15Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- `POST /api/knowledge/learn` endpoint in `dashboard/server.py` — accepts session context (summary, tools, files, messages), runs instructor + Pydantic extraction via `asyncio.to_thread`, filters trivials, returns learnings list
- `memory/qdrant_store.py` — `_ensure_knowledge_indexes()` method creates learning_type and category KEYWORD payload indexes; `_ensure_collection()` calls it when KNOWLEDGE collection is initialized
- `tests/test_knowledge_learn.py` — 5 new `TestKnowledgeIndexes` tests; total suite expanded from 35 to 40 tests; full project suite 1474 passed, 0 failures

## Task Commits

Each task was committed atomically:

1. **Task 1: Add /api/knowledge/learn endpoint to server.py** - `9a347e4` (feat)
2. **Task 2: Register hook in settings.json and add KNOWLEDGE payload indexes** - `d534b1b` (feat)

**Plan metadata:** (see final commit below)

## Files Created/Modified

- `dashboard/server.py` — Added `extract_knowledge` endpoint at `/api/knowledge/learn`; uses instructor + Pydantic (ExtractedLearning, ExtractionResult) with asyncio.to_thread; supports OpenRouter (gemini-2.0-flash-001) and OpenAI (gpt-4o-mini); no auth required; graceful error handling throughout
- `memory/qdrant_store.py` — Added `_ensure_knowledge_indexes()` method; updated `_ensure_collection()` to dispatch to it for KNOWLEDGE suffix
- `tests/test_knowledge_learn.py` — Added `TestKnowledgeIndexes` class with 5 tests covering method existence, learning_type/category field creation, collection trigger behavior, MEMORY suffix skips, and silent failure on Qdrant error

## Decisions Made

- Pydantic models defined inside the endpoint function to avoid module-level import side effects — they're only needed at request time and co-locating them with the instructor call is cleaner
- `asyncio.to_thread` wraps the synchronous instructor/OpenAI call — FastAPI event loop must never be blocked by network I/O
- Provider routing follows pitfall #90 guidance: OPENROUTER_API_KEY tries OpenRouter with gemini-2.0-flash-001 (reliable), falls back to OPENAI_API_KEY with gpt-4o-mini; avoids dead OR free models

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed incorrect patch target in TestKnowledgeIndexes test**

- **Found during:** Task 2 (running tests after adding TestKnowledgeIndexes)
- **Issue:** Test patched `memory.qdrant_store.PayloadSchemaType` but `PayloadSchemaType` is imported locally inside `_ensure_knowledge_indexes()` (not at module level) — patch raised `AttributeError: module does not have attribute 'PayloadSchemaType'`
- **Fix:** Removed the patch — `PayloadSchemaType` resolves via local import inside the method; the mock_client's `create_payload_index` captures the field names regardless
- **Files modified:** `tests/test_knowledge_learn.py`
- **Verification:** All 40 knowledge-learn tests pass after fix
- **Committed in:** `d534b1b` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - Bug in test mock patch target)
**Impact on plan:** Auto-fix necessary for test correctness. No scope creep.

## Issues Encountered

The `settings.json` hook registration was noted in the plan as part of Task 2, but `knowledge-learn.py` was already registered during plan 02-01 (it was added to settings.json in that plan's Task 2). The settings.json change was effectively a no-op — verified the hook was already there with timeout=30, positioned after jcodemunch-reindex.py. The `TestHookRegistration` tests were already passing.

## User Setup Required

None — no external service configuration required. The complete pipeline is now active: Stop event fires knowledge-learn.py hook, which spawns the background worker, which calls `/api/knowledge/learn`, which extracts learnings via LLM (requires OPENROUTER_API_KEY or OPENAI_API_KEY in .env), and stores to Qdrant KNOWLEDGE collection with ONNX embeddings.

## Next Phase Readiness

- Full knowledge-learn pipeline is complete: Stop event -> hook -> worker -> API -> instructor -> worker -> ONNX embed -> Qdrant upsert
- KNOWLEDGE collection gets learning_type and category indexes on first initialization for efficient filtered queries
- Phase 02 (Intelligent Learning) is now 100% complete — both plans 02-01 and 02-02 done
- Workstream intelligent-memory-bridge is complete

## Self-Check: PASSED

All created/modified files verified on disk. All commits confirmed in git log.

- FOUND: `dashboard/server.py` contains `extract_knowledge` endpoint
- FOUND: `memory/qdrant_store.py` contains `_ensure_knowledge_indexes`
- FOUND: `tests/test_knowledge_learn.py` contains `TestKnowledgeIndexes`
- FOUND commit `9a347e4`: feat(02-02) - knowledge/learn endpoint
- FOUND commit `d534b1b`: feat(02-02) - KNOWLEDGE indexes and tests

---
*Phase: 02-intelligent-learning*
*Completed: 2026-03-19*
