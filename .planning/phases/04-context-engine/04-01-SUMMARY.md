---
phase: "04"
plan: "01"
subsystem: "tools"
tags: [context-engine, jcodemunch, mcp, gsd, effectiveness, token-budget]
dependency_graph:
  requires: [tools/context_assembler.py, tools/mcp_client.py, memory/effectiveness.py]
  provides: [tools/unified_context.py]
  affects: [mcp_server.py, agent42.py _register_tools()]
tech_stack:
  added: []
  patterns: [mcp-to-mcp per-call connect/disconnect, asyncio.gather parallel sources, budget redistribution]
key_files:
  created: [tools/unified_context.py, tests/test_unified_context.py]
  modified: []
decisions:
  - "UnifiedContextTool wraps ContextAssemblerTool (not extends) — internal instance delegates base 4 sources"
  - "Per-call MCPConnection pattern: connect + timeout + call_tool + disconnect in _fetch_code_symbols"
  - "GSD state uses keyword overlap >= 1 against stopped_at + ws_name for relevance filtering"
  - "Budget redistribution: unavailable source budget divided equally among active sources"
  - "Keyword-to-work-type lookup is case-insensitive against topic.lower()"
  - "Tool name is 'unified_context' to avoid collision with existing 'context' tool (produces agent42_unified_context in MCP)"
metrics:
  duration_min: 13
  completed_date: "2026-03-25"
  tasks_completed: 1
  files_changed: 2
---

# Phase 04 Plan 01: UnifiedContextTool — 6-Source Context Assembly Summary

**One-liner:** Token-budgeted 6-source context tool wrapping ContextAssemblerTool with jcodemunch MCP symbols, GSD workstream state, and effectiveness-ranked tool recommendations.

## What Was Built

`tools/unified_context.py` — `UnifiedContextTool(Tool)` with:

- **4 base sources via ContextAssemblerTool:** semantic memory, project docs (CLAUDE.md, MEMORY.md), git history, skills
- **Source 5 — jcodemunch code symbols:** `_fetch_code_symbols()` using `MCPConnection("jcodemunch", {"command": "uvx", "args": ["jcodemunch-mcp"]})` with 3-second connect timeout and 5-second per-call timeout; searches `search_symbols` + `search_text` with SHA256 dedup
- **Source 6a — GSD workstream state:** `_fetch_gsd_state()` globs `.planning/workstreams/*/STATE.md`, skips `Complete` workstreams, picks most recently updated by `last_updated` ISO timestamp, includes GSD section only when query keyword overlap >= 1 against `stopped_at + ws_name`
- **Source 6b — effectiveness ranking:** `_fetch_effectiveness()` calls `EffectivenessStore.get_recommendations(task_type)` and formats ranked tool list

**Budget allocations (D-13):** memory 30%, code 25%, GSD 15%, git 10%, skills 10%, effectiveness 10%.

**Budget redistribution (D-14):** unavailable source budgets are divided equally among sources that produced content, then each section is re-truncated to its expanded budget.

**Task type inference:** `_infer_task_type(topic)` scans `_WORK_TYPE_KEYWORDS` (10 work types copied from `context-loader.py` hook) and maps the first matching work type through `_WORK_TYPE_TO_TASK_TYPE` to an effectiveness task type string.

**Code symbol fetch scope:** Only fetches jcodemunch for `_CODE_TASK_TYPES` = {coding, debugging, refactoring, app_create, app_update, project_setup} or when task type is unknown.

`tests/test_unified_context.py` — 16 tests across two classes:

- `TestUnifiedContext` (12 tests): jcodemunch happy path, TimeoutError degradation, GSD keyword match/no-match/Complete skip, effectiveness with/without data, budget redistribution, tool name, MCP schema name, parameter schema, empty topic error
- `TestTaskTypeInference` (4 tests): security->debugging, tools->coding, deployment->project_setup, unknown->""

## Verification Results

```
python -m pytest tests/test_unified_context.py -x -q
16 passed in 1.79s

python -c "from tools.unified_context import UnifiedContextTool; print(UnifiedContextTool().name)"
unified_context

ruff check tools/unified_context.py tests/test_unified_context.py
All checks passed!
```

## Decisions Made

| Decision | Rationale |
|----------|-----------|
| Wrap ContextAssemblerTool (not inherit) | Composition avoids overriding all 4 base source methods; `_assembler.execute()` is the stable interface |
| Per-call MCPConnection | Research Pattern 1 — no persistent connection needed for 1-2 calls; avoids orphaned processes on failures |
| Budget redistribution to active sources | D-14 — prevents wasted token budget when jcodemunch is down |
| GSD keyword overlap threshold = 1 | Lower threshold means more GSD context when query is broadly related; avoids noise |
| Keyword lists copied, not imported | `context-loader.py` is a hook script with hook-specific metadata; extracting just the keyword lists keeps unified_context.py library-only |

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None — all 6 sources are fully wired with real implementation logic.

## Self-Check
