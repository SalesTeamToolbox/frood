---
phase: 43-effectiveness-workflow-offloading
plan: 01
status: complete
---

# Plan 43-01 Summary: Data Layer for Pattern Detection

## What was built

1. **3 new SQLite tables** in `memory/effectiveness.py` `_ensure_db()`:
   - `tool_sequences` — tracks tool execution patterns with compound unique index `(agent_id, task_type, fingerprint)`
   - `workflow_suggestions` — stores automation suggestions with status lifecycle (pending -> suggested -> dismissed/created)
   - `workflow_mappings` — records N8N workflow bindings per agent+fingerprint

2. **5 new EffectivenessStore methods**:
   - `record_sequence()` — upserts tool sequence with MD5 fingerprint, returns count when >= threshold
   - `create_suggestion()` — writes suggestion with token savings estimate (count * 1000)
   - `get_pending_suggestions()` — returns never-injected suggestions for an agent (limit 3)
   - `mark_suggestion_status()` — transitions suggestion status
   - `record_workflow_mapping()` — records workflow binding, auto-marks suggestion as "created"

3. **Task-context accumulator** in `core/task_context.py`:
   - `_current_task_tools` dict for per-task tool name accumulation
   - `append_tool_to_task()` and `pop_task_tools()` helper functions

4. **Config fields** in `core/config.py`:
   - `n8n_pattern_threshold: int = 3`
   - `n8n_auto_create_workflows: bool = False`
   - Both wired in `from_env()` with `N8N_PATTERN_THRESHOLD` and `N8N_AUTO_CREATE_WORKFLOWS`

## Test coverage

22 tests in `tests/test_effectiveness_offloading.py`:
- 3 schema tests (PRAGMA table_info validation)
- 6 record_sequence tests (insert, upsert, compound unique, skip rules, graceful degradation)
- 5 suggestion lifecycle tests (create, query, mark suggested/dismissed)
- 1 workflow mapping test
- 4 config tests (defaults + from_env)
- 3 task-context accumulator tests

## Decisions

- `hashlib` and `json` imported inside methods to avoid ruff removing "unused" top-level imports
- Tests for single-tool/empty skip call `_ensure_db()` explicitly since `record_sequence` short-circuits before DB init
