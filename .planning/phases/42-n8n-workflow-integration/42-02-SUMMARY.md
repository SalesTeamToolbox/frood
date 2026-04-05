---
phase: 42-n8n-workflow-integration
plan: 02
subsystem: tools
tags: [n8n, workflow-automation, tool, node-validation, templates]
dependency_graph:
  requires: [tools/base.py, core/config.py]
  provides: [tools/n8n_create_workflow.py, tools/n8n_templates/]
  affects: [mcp_server.py (registration in Plan 03)]
tech_stack:
  added: [httpx (async HTTP), uuid (node ID generation), json templates]
  patterns: [Tool ABC pattern, TDD red-green, graceful degradation, placeholder replacement]
key_files:
  created:
    - tools/n8n_create_workflow.py
    - tools/n8n_templates/webhook_to_http.json
    - tools/n8n_templates/webhook_to_transform.json
    - tools/n8n_templates/webhook_to_multi_step.json
    - tests/test_n8n_create_tool.py
  modified:
    - core/config.py (added n8n_url, n8n_api_key, n8n_allow_code_nodes fields)
decisions:
  - "Templates use {PLACEHOLDER} syntax in JSON string values — simple string replace avoids regex complexity"
  - "validate_workflow_nodes is module-level (not method) so tests can import it directly without instantiating the tool"
  - "Added n8n config fields to core/config.py in this plan because Plan 01 parallel execution had not yet added them"
  - "Pre-existing test_app_git.py failure is unrelated to this plan (Windows path sandbox issue)"
metrics:
  duration_seconds: 335
  completed: 2026-04-05
  tasks_completed: 2
  files_created: 5
  files_modified: 1
---

# Phase 42 Plan 02: N8N Create Workflow Tool Summary

**One-liner:** N8N workflow generator with JSON template skeletons, 7-node safety blocklist, and async REST API deployment via httpx.

## Tasks Completed

### Task 1: Workflow Templates in tools/n8n_templates/

Created `tools/n8n_templates/` directory with three N8N workflow JSON skeleton files:

- `webhook_to_http.json` — Webhook trigger -> HTTP Request -> respond. Use case: call external API with input data.
- `webhook_to_transform.json` — Webhook trigger -> Set node -> respond. Use case: transform/reshape incoming data.
- `webhook_to_multi_step.json` — Webhook trigger -> HTTP Request -> Set -> respond. Use case: fetch from API, transform, return.

All templates comply with N8N schema requirements:
- `responseMode: "lastNode"` on webhook nodes (ensures response waits for last node output)
- `settings.executionOrder: "v1"` (required for N8N v1+)
- Placeholder UUIDs in `id` fields (replaced with real UUIDs at creation time)
- `{PLACEHOLDER}` strings for name, path, URL, method (replaced by `_build_workflow`)

Also added `n8n_url`, `n8n_api_key`, `n8n_allow_code_nodes` config fields to `core/config.py` — these belong to Plan 01 but were absent since the parallel Plan 01 agent had not yet committed them.

**Commit:** `aa14f5b`

### Task 2: N8nCreateWorkflowTool (TDD)

**RED:** 17 failing tests covering tool name, node validation, graceful degradation, template loading, workflow generation, and full deployment flow with mocked httpx.

**GREEN:** Implemented `tools/n8n_create_workflow.py` with:

- `DANGEROUS_NODE_TYPES` — 7 blocked node types: executeCommand, ssh, code, git, localFileTrigger, readBinaryFiles, writeBinaryFile
- `validate_workflow_nodes(nodes, allow_code)` — module-level function; unblocks only `n8n-nodes-base.code` when `allow_code=True`, all other dangerous types remain blocked
- `N8nCreateWorkflowTool(Tool)` — inherits Tool ABC, returns ToolResult
- `_load_template(name)` — loads JSON from `tools/n8n_templates/`
- `_build_workflow(...)` — replaces all `{PLACEHOLDER}` strings, generates real UUIDs for node ids
- `execute()` — validates config, builds workflow, validates nodes, POSTs to `/api/v1/workflows`, activates via `/api/v1/workflows/{id}/activate`, returns webhook URL

All 17 unit tests pass. Pre-existing `test_app_git.py` failure is unrelated (Windows path sandbox incompatibility).

**Commits:** `8f2e379` (tests), `0a3f4fc` (implementation)

## Deviations from Plan

### Auto-added Missing Functionality

**1. [Rule 2 - Missing Critical Functionality] Added n8n config fields to core/config.py**
- **Found during:** Task 1 setup check
- **Issue:** Plan 01 had not yet run (parallel execution), so `n8n_url`, `n8n_api_key`, `n8n_allow_code_nodes` were absent from `Settings`
- **Fix:** Added all three fields to the `Settings` dataclass and `from_env()` using the established config pattern
- **Files modified:** `core/config.py`
- **Commit:** `aa14f5b`

## Verification Results

All plan verification commands pass:
- `python -m pytest tests/test_n8n_create_tool.py -x -q` — 17/17 passed
- `N8nCreateWorkflowTool().name` returns `"n8n_create_workflow"`
- `validate_workflow_nodes([{'name': 'bad', 'type': 'n8n-nodes-base.ssh'}])` returns non-empty list
- `webhook_to_http.json` nodes[0].type is `"n8n-nodes-base.webhook"`

## Known Stubs

None — all template placeholders are replaced at workflow creation time via `_build_workflow`. The tool returns real webhook URLs after N8N API deployment.

## Self-Check: PASSED

Files verified to exist:
- `tools/n8n_create_workflow.py` — FOUND
- `tools/n8n_templates/webhook_to_http.json` — FOUND
- `tools/n8n_templates/webhook_to_transform.json` — FOUND
- `tools/n8n_templates/webhook_to_multi_step.json` — FOUND
- `tests/test_n8n_create_tool.py` — FOUND

Commits verified:
- `aa14f5b` — feat(42-02): add n8n workflow templates and config fields
- `8f2e379` — test(42-02): add failing tests for N8nCreateWorkflowTool
- `0a3f4fc` — feat(42-02): implement N8nCreateWorkflowTool with node validation and deployment
