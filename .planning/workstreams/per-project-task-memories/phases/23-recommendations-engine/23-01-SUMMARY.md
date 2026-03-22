---
phase: 23-recommendations-engine
plan: 01
subsystem: memory/effectiveness + dashboard/server
tags: [recommendations, effectiveness, api, tdd]
requirements: [RETR-05, RETR-06]
dependency_graph:
  requires: [memory/effectiveness.py (EffectivenessStore), core/config.py (Settings), dashboard/server.py (create_app)]
  provides: [EffectivenessStore.get_recommendations(), GET /api/recommendations/retrieve, recommendations_min_observations config]
  affects: [proactive-inject.py (Plan 02 consumer)]
tech_stack:
  added: []
  patterns: [aiosqlite SQL HAVING clause, FastAPI closure endpoint, TDD red-green]
key_files:
  created: [tests/test_effectiveness.py (TestEffectivenessRecommendations class), tests/test_proactive_injection.py (TestRecommendationsRetrieve class, _make_app_with_mock_effectiveness_store helper)]
  modified: [memory/effectiveness.py, core/config.py, .env.example, dashboard/server.py]
decisions:
  - "min_observations=0 sentinel triggers fallback to settings.recommendations_min_observations — avoids two separate query params with overlapping semantics"
  - "Endpoint uses module-level settings import (not closure parameter) — consistent with existing endpoints in create_app"
metrics:
  duration: 8 min
  completed: "2026-03-22T20:13:20Z"
  tasks_completed: 2
  files_modified: 6
---

# Phase 23 Plan 01: Recommendations Engine Data Layer Summary

**One-liner:** SQLite-backed get_recommendations() with HAVING threshold + top_k cap + /api/recommendations/retrieve endpoint with config-driven min_observations default.

## What Was Built

Two tasks completed under TDD (RED then GREEN):

**Task 1 — EffectivenessStore.get_recommendations() + config field**
- Added `recommendations_min_observations: int = 5` to Settings frozen dataclass and `from_env()`
- Documented `RECOMMENDATIONS_MIN_OBSERVATIONS=5` in `.env.example`
- Implemented `get_recommendations(task_type, min_observations=5, top_k=3)` in `EffectivenessStore`:
  - SQL uses `HAVING COUNT(*) >= ?` to filter tools below threshold (RETR-06)
  - `ORDER BY success_rate DESC, avg_duration_ms ASC` for tie-breaking (D-08)
  - `LIMIT ?` enforces top_k cap (D-10)
  - Returns `[]` on any exception (graceful degradation)
- Added `TestEffectivenessRecommendations` class with 6 tests covering all acceptance criteria

**Task 2 — GET /api/recommendations/retrieve endpoint**
- Added endpoint immediately after `effectiveness_stats` in `create_app()` closure
- `min_observations=0` sentinel falls back to `settings.recommendations_min_observations`
- Returns `{"recommendations": [], "task_type": ""}` on empty task_type (silent per RETR-06)
- Returns `{"recommendations": [], "task_type": task_type}` when store is None or raises
- Added `_make_app_with_mock_effectiveness_store()` test helper
- Added `TestRecommendationsRetrieve` with 6 endpoint tests

## Test Results

All 12 new tests pass. No regressions in existing test files.

```
tests/test_effectiveness.py::TestEffectivenessRecommendations  6 passed
tests/test_proactive_injection.py::TestRecommendationsRetrieve 6 passed
tests/test_effectiveness.py tests/test_proactive_injection.py  48 passed total
```

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| Task 1 | c74b191 | feat(23-01): add get_recommendations() to EffectivenessStore + config field |
| Task 2 | b6f3d8f | feat(23-01): add GET /api/recommendations/retrieve endpoint + endpoint tests |

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None. Both data layer and API endpoint are fully wired. Plan 02 will consume this endpoint from the proactive-inject.py hook.

## Self-Check: PASSED
