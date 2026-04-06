---
phase: 43-effectiveness-workflow-offloading
plan: 02
status: complete
---

# Plan 43-02 Summary: Runtime Wiring

## What was built

1. **ToolRegistry accumulator** (`tools/registry.py`):
   - After effectiveness tracking block, appends `tool_name` to per-task accumulator
   - Only runs when `effectiveness_store` is set (matches existing guard pattern)
   - Uses `append_tool_to_task(task_id, tool_name)` from task_context

2. **Shared store accessor** (`memory/effectiveness.py`):
   - `_shared_effectiveness_store` module-level singleton
   - `set_shared_store()` / `get_shared_store()` for cross-module access
   - Set by agent42.py at startup, read by task_context and agent_runtime

3. **end_task flush** (`core/task_context.py`):
   - Pops tool accumulator FIRST (always, prevents memory leaks)
   - Fire-and-forget `asyncio.create_task(store.record_sequence(...))` when 2+ tools accumulated
   - Uses `agent_id=""` (TaskContext doesn't carry agent_id — global grouping by task_type)

4. **Async _build_prompt with suggestion injection** (`core/agent_runtime.py`):
   - `_build_prompt()` changed from sync to async
   - Both call sites (`_start_openai_agent`, `_start_claude_agent`) updated to `await`
   - Injects `AUTOMATION SUGGESTION: Pattern '{tool1 -> tool2}' has repeated N times...`
   - Marks suggestions as 'suggested' after injection (no re-nagging per Pitfall 4)
   - Graceful fallback when no store or no suggestions

5. **n8n_create_workflow mapping** (`tools/n8n_create_workflow.py`):
   - When `fingerprint` kwarg is provided, fires `record_workflow_mapping()` via create_task
   - Links the created workflow back to the effectiveness suggestion that triggered it

## Test coverage

7 new tests added (29 total):
- `test_registry_accumulates_tools` — verifies ToolRegistry.execute() appends to accumulator
- `test_end_task_pops_accumulator` — verifies end_task() cleans up accumulator dict
- `test_build_prompt_injects_suggestions` — verifies suggestion text format in prompt
- `test_build_prompt_no_suggestions_when_none_pending` — verifies clean prompt
- `test_suggestion_marked_suggested_after_injection` — verifies no re-injection
- `test_build_prompt_graceful_without_store` — verifies no crash when store is None
- `test_create_workflow_records_mapping` — verifies mapping persistence

## Decisions

- `agent_id=""` in end_task flush — adding agent_id to TaskContext would require updating all begin_task() call sites (scope expansion). Global patterns are still useful for offloading.
- `asyncio` import added to n8n_create_workflow.py for create_task usage
