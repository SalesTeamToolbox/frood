---
phase: 21-effectiveness-tracking-and-learning-extraction
plan: 02
subsystem: learning-extraction
tags: [stop-hook, instructor, pydantic, quarantine, task-context-bridge, effectiveness]
dependency_graph:
  requires: [21-01]
  provides: [LEARN-01, LEARN-02, LEARN-03, LEARN-04, LEARN-05]
  affects: [core/task_context.py, dashboard/server.py, .claude/hooks/effectiveness-learn.py, .claude/settings.json]
tech_stack:
  added: [instructor>=1.3.0 (already added in 21-01), pydantic ExtractedLearning model]
  patterns: [Stop hook HTTP API call, cross-process file bridge, quarantine promotion, fire-and-forget asyncio.create_task]
key_files:
  created:
    - .claude/hooks/effectiveness-learn.py
    - tests/test_learning_extraction.py
  modified:
    - core/task_context.py
    - dashboard/server.py
decisions:
  - "Quarantine fields applied via update_payload after log_event_semantic — not embedded in log_event_semantic itself — avoids coupling memory layer to learning-extraction concepts"
  - "Using instructor.Mode.JSON for broad model compatibility — Gemini Flash via OpenRouter may not support function calling mode"
  - "Trivial session guard threshold: <2 tool calls OR <1 file modification — skips noise without LLM call"
  - "_maybe_promote_quarantined defined as inner function within create_app scope to access memory_store closure"
  - "Task context bridge file at .agent42/current-task.json — written by begin_task, removed by end_task, read by Stop hook subprocess"
metrics:
  duration_minutes: 28
  completed_date: "2026-03-17"
  tasks_completed: 3
  files_created: 2
  files_modified: 2
---

# Phase 21 Plan 02: Learning Extraction Pipeline Summary

**One-liner:** Stop hook using instructor + Pydantic to extract structured learnings post-session, persisted to HISTORY.md + Qdrant with quarantine fields (observation_count=1, confidence=0.6) and automatic promotion after LEARNING_MIN_EVIDENCE observations.

## What Was Built

### Task 1: Task Context File Bridge + Learning API Endpoint

**`core/task_context.py`** — Added cross-process file bridge:

- `_write_task_file(task_id, task_type)` — writes `.agent42/current-task.json` with JSON task context
- `_remove_task_file()` — removes the file when task ends
- `begin_task()` now calls `_write_task_file()` after setting contextvars
- `end_task()` now calls `_remove_task_file()` on cleanup
- All file operations are wrapped in `try/except` — non-critical, never raises

**`dashboard/server.py`** — Added two new elements:

- `POST /api/effectiveness/learn` endpoint: accepts learning payload, calls `memory_store.log_event_semantic()` with `[task_type][task_id][outcome]` event format, then updates the Qdrant point with `observation_count=1, confidence=0.6, quarantined=True, outcome`
- `_maybe_promote_quarantined()` async helper: searches for semantically similar quarantined learnings with same outcome (score >= 0.70), increments `observation_count`, promotes to `confidence=1.0, quarantined=False` when count reaches `LEARNING_MIN_EVIDENCE`

### Task 2: effectiveness-learn.py Stop Hook

**`.claude/hooks/effectiveness-learn.py`** — New Stop hook implementing LEARN-01 through LEARN-05:

- `count_tool_calls(event)` / `count_file_modifications(event)` — trivial session guard functions
- Trivial sessions (<2 tool calls OR <1 file modification) exit immediately without LLM call
- `read_task_context(project_dir)` — reads `.agent42/current-task.json`, falls back to generated UUID + "general"
- `extract_learning_with_instructor()` — uses `instructor.from_openai()` with `Mode.JSON` and Gemini Flash via OpenRouter (or OpenAI fallback) to extract `ExtractedLearning(outcome, summary, key_insight)`
- `persist_learning()` — HTTP POST to `http://127.0.0.1:8000/api/effectiveness/learn`
- All errors caught, always exits code 0

**`.claude/settings.json`** — Hook registered with 30s timeout in Stop hooks array (after memory-learn.py, before jcodemunch-reindex.py).

### Task 3: Tests

**`tests/test_learning_extraction.py`** — 17 tests across 5 classes:

- `TestTaskContextBridge` — file creation/removal on begin_task/end_task, read_task_context from file and missing file
- `TestTrivialSessionGuard` — tool call counting, file mod counting, trivial/sufficient session detection
- `TestLearningExtraction` — graceful None return without API keys, tool name deduplication, file basename extraction
- `TestQuarantine` — default quarantine field values, promotion threshold logic, outcome mismatch guard
- `TestNoMidTaskWrites` — verifies hook only registered in Stop, not PreToolUse/PostToolUse

## Deviations from Plan

None - plan executed exactly as written.

The pre-existing `test_auth_flow.py::TestAuthIntegration::test_protected_endpoint_requires_auth` failure (returns 404 instead of 401) was confirmed as a pre-existing issue present in the baseline before any plan 21-02 changes. It is out of scope and has been logged to the deferred items.

## Key Decisions Made

1. **Quarantine fields applied via update_payload after log_event_semantic** — separates the memory layer from learning-extraction semantics, maintaining clean module boundaries.

2. **`instructor.Mode.JSON` for broad model compatibility** — Gemini Flash via OpenRouter may not support function calling mode; JSON mode works across all providers.

3. **Trivial session guard: `<2 tool calls OR <1 file modification`** — skips noise (pure read sessions, single-tool queries) without making an LLM call.

4. **`_maybe_promote_quarantined` as inner function within `create_app`** — accesses `memory_store` via closure, avoiding it being passed as a parameter.

5. **Task context bridge file at `.agent42/current-task.json`** — separate subprocess (Stop hook) can't access contextvars; file bridge is the correct solution. Non-critical writes with silent `try/except` throughout.

## Commits

| Hash | Task | Description |
|------|------|-------------|
| 3385308 | Task 1 | feat(21-02): task context file bridge, learning endpoint, quarantine logic |
| 6aa639d | Task 2 | feat(21-02): effectiveness-learn Stop hook and settings.json registration |
| 025880f | Task 3 | test(21-02): learning extraction tests for LEARN-01 through LEARN-05 |

## Self-Check: PASSED

- FOUND: .claude/hooks/effectiveness-learn.py
- FOUND: tests/test_learning_extraction.py
- FOUND: core/task_context.py
- FOUND: commit 3385308 (Task 1)
- FOUND: commit 6aa639d (Task 2)
- FOUND: commit 025880f (Task 3)
