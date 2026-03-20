---
phase: 02-intelligent-learning
plan: 01
subsystem: memory
tags: [qdrant, onnx, hooks, knowledge-extraction, dedup, background-worker, stop-hook]

# Dependency graph
requires:
  - phase: 01-auto-sync-hook
    provides: QdrantStore KNOWLEDGE collection, ONNX embedding pattern, detached subprocess spawn pattern, settings.json hook registration
provides:
  - Stop hook entry point (knowledge-learn.py) — stdlib-only, spawns detached worker
  - Background worker (knowledge-learn-worker.py) — calls /api/knowledge/learn, ONNX embed, dedup-or-store to KNOWLEDGE collection
  - Test suite (test_knowledge_learn.py) — 35 tests covering all LEARN-01 through LEARN-05 requirements
affects: [02-02, api-knowledge-learn-endpoint, dashboard-knowledge-panel]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Dedup via raw_score (not lifecycle-adjusted score) against 0.85 threshold — boost existing or store new"
    - "Hook pre-extracts last 20 messages to temp JSON file; worker reads and deletes it"
    - "SIMILARITY_THRESHOLD = 0.85 constant; uses raw_score field from search_with_lifecycle hits"
    - "QdrantConfig(vector_dim=384) for KNOWLEDGE collection (ONNX, not OpenAI 1536-dim)"

key-files:
  created:
    - .claude/hooks/knowledge-learn.py
    - .claude/hooks/knowledge-learn-worker.py
    - tests/test_knowledge_learn.py
  modified:
    - .claude/settings.json

key-decisions:
  - "Hook pre-extracts last 20 messages to temp file rather than passing all messages on command line — avoids shell arg length limits and keeps hook startup under 30ms"
  - "Worker uses raw_score (not lifecycle-adjusted score) for dedup threshold — prevents confidence-boosted entries from being treated as highly similar when they may not be semantically so"
  - "Silent failure at every level — API unreachable, Qdrant unavailable, ONNX missing all result in clean exit (not crash) with status file recording the error"

patterns-established:
  - "knowledge-learn pattern: stdlib-only entry point → temp JSON file → detached worker → API call → ONNX embed → dedup-or-store"
  - "dedup_or_store: search_with_lifecycle(top_k=3) → check raw_score >= 0.85 → strengthen_point OR upsert new PointStruct"

requirements-completed: [LEARN-01, LEARN-02, LEARN-03, LEARN-04, LEARN-05]

# Metrics
duration: 13min
completed: 2026-03-19
---

# Phase 02 Plan 01: Knowledge-Learn Hook and Worker Summary

Stop hook + detached worker that extract structured learnings from CC sessions into Qdrant's KNOWLEDGE collection with raw_score-based dedup (0.85 threshold) and ONNX 384-dim embedding

## Performance

- **Duration:** 13 min
- **Started:** 2026-03-19T04:16:15Z
- **Completed:** 2026-03-19T04:29:05Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- Stop hook entry point `knowledge-learn.py` — stdlib-only, noise guard (2+ tool calls + 1+ file mod), pre-extracts last 20 messages to temp JSON, spawns detached worker with DETACHED_PROCESS on Windows
- Background worker `knowledge-learn-worker.py` — calls `/api/knowledge/learn` via urllib, ONNX embedding at 384-dim, dedup via raw_score >= 0.85 threshold (boost existing or store new point), silent failure on all error conditions
- 35-test suite covering all 8 requirement areas — TestNoiseFilter, TestMessageExtraction, TestExtraction (LEARN-01/02/03), TestDedup (LEARN-04), TestCategories (LEARN-05), TestFailureSilence, TestQdrantDimension, TestHookRegistration
- Hook registered in `.claude/settings.json` Stop hooks with 30s timeout

## Task Commits

Each task was committed atomically:

1. **Task 1: Create test scaffold for knowledge-learn hook and worker** - `99e48eb` (test)
2. **Task 2: Create knowledge-learn hook entry point and background worker** - `7419436` (feat)

**Plan metadata:** (see final commit below)

## Files Created/Modified

- `.claude/hooks/knowledge-learn.py` — Stop hook entry point; stdlib-only; noise guard; pre-extracts session data to temp JSON; spawns detached worker
- `.claude/hooks/knowledge-learn-worker.py` — Background worker; calls `/api/knowledge/learn`; ONNX embed 384-dim; dedup-or-store with raw_score threshold; status file tracking
- `tests/test_knowledge_learn.py` — 35 tests covering LEARN-01 through LEARN-05 plus noise filter, message extraction, silent failure, Qdrant dimension, and hook registration
- `.claude/settings.json` — Added `knowledge-learn.py` to Stop hooks array (timeout=30)

## Decisions Made

- Pre-extract to temp file (not command-line arg): avoids shell arg length limits on Windows and keeps the hook's main process lifetime short
- Raw score dedup: `raw_score` from `search_with_lifecycle` is the geometric similarity before lifecycle boosting — more accurate for dedup than the adjusted `score`
- Silent failures at all levels: consistent with SYNC-04 pattern from Phase 01 — no crash, no stderr output, status file records error for dashboard inspection

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed incorrect QdrantStore mock in test_decision_extracted**

- **Found during:** Task 2 (running tests after hook/worker creation)
- **Issue:** Test patched `QdrantStore` with `type(mock_store)` (a MagicMock class) which lacks the `KNOWLEDGE` string constant that the worker accesses as `QdrantStore.KNOWLEDGE`
- **Fix:** Removed the incorrect `patch.object(self.worker, "QdrantStore", ...)` — the worker receives `mock_store` directly as an argument; `QdrantStore.KNOWLEDGE` constant stays accessible from the real module
- **Files modified:** `tests/test_knowledge_learn.py`
- **Committed in:** `7419436` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - Bug in test mock setup)
**Impact on plan:** Auto-fix necessary for test correctness. No scope creep. Tests now accurately verify the dedup_or_store function contract.

## Issues Encountered

None beyond the auto-fixed test mock bug above.

## User Setup Required

None — no external service configuration required. The hook activates automatically on the next CC session Stop event once registered in settings.json. The `/api/knowledge/learn` API endpoint (plan 02-02) must be implemented for the worker to extract learnings; until then, the worker exits silently when the API is unreachable.

## Next Phase Readiness

- Hook and worker infrastructure complete — ready for plan 02-02 (Agent42 API endpoint `/api/knowledge/learn`)
- KNOWLEDGE collection will be created on first store (QdrantStore._ensure_collection is called before upsert)
- Status file at `.agent42/knowledge-learn-status.json` is ready for dashboard display

## Self-Check: PASSED

All created files exist on disk. All commits confirmed in git log.

- FOUND: `.claude/hooks/knowledge-learn.py`
- FOUND: `.claude/hooks/knowledge-learn-worker.py`
- FOUND: `tests/test_knowledge_learn.py`
- FOUND commit `99e48eb`: test(02-01) - test scaffold
- FOUND commit `7419436`: feat(02-01) - hook and worker implementation

---
*Phase: 02-intelligent-learning*
*Completed: 2026-03-19*
