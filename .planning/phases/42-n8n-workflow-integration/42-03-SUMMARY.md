---
phase: 42-n8n-workflow-integration
plan: 03
subsystem: mcp, infrastructure
tags: [n8n, mcp-server, docker-compose, tool-registration, deployment]
dependency_graph:
  requires: [tools/n8n_workflow.py, tools/n8n_create_workflow.py, mcp_server.py]
  provides: [mcp_server.py (N8N tools registered), docker-compose.n8n.yml]
  affects: [agents using MCP tools (now have n8n_workflow and n8n_create_workflow available)]
tech_stack:
  added: [docker.n8n.io/n8nio/n8n Docker image]
  patterns: [_safe_import graceful degradation, separate compose file pattern]
key_files:
  created:
    - docker-compose.n8n.yml
  modified:
    - mcp_server.py (added N8nWorkflowTool and N8nCreateWorkflowTool to Group A)
decisions:
  - "N8N tools added to Group A (no-dependency) in _build_registry() -- both tools use deferred settings import internally"
  - "Separate docker-compose.n8n.yml matches Phase 31 pattern (docker-compose.paperclip.yml) for independent lifecycle management"
  - "N8N_ENCRYPTION_KEY uses :? syntax to fail fast if not set -- avoids silent credential corruption"
  - "NODES_EXCLUDE set at Docker level as belt-and-suspenders alongside Agent42 validate_workflow_nodes() validation"
metrics:
  duration_seconds: 420
  completed: 2026-04-05
  tasks_completed: 2
  files_created: 1
  files_modified: 1
---

# Phase 42 Plan 03: MCP Registration + Docker Compose Summary

**One-liner:** N8N tools wired into MCP server via _safe_import Group A registration and standalone Docker Compose with encryption key enforcement, node blocking, and execution pruning.

## Tasks Completed

### Task 1: Register both N8N tools in mcp_server.py

Added `N8nWorkflowTool` and `N8nCreateWorkflowTool` to the Group A `_build_registry()` loop in `mcp_server.py` (lines 119-129). Both tools take no constructor arguments and use deferred settings import internally, matching the no-dependency group pattern.

The registration uses the existing `_safe_import` / `_register` pattern — if either tool fails to import (e.g., missing `httpx` dep), the MCP server still starts and the tool is simply absent from the registry. This satisfies D-14 graceful degradation.

**Verification:** `python -c "from mcp_server import _build_registry; r = _build_registry(); names = [t.name for t in r._tools.values()]; assert 'n8n_workflow' in names; assert 'n8n_create_workflow' in names"` — passes.

**Commit:** `fee7ae2`

### Task 2: Create docker-compose.n8n.yml for N8N deployment

Created `docker-compose.n8n.yml` in the project root following the Phase 31 precedent of separate compose files (`docker-compose.paperclip.yml`). This keeps N8N's lifecycle independent from Agent42's main stack.

Key configuration decisions:

- **`N8N_ENCRYPTION_KEY: ${N8N_ENCRYPTION_KEY:?...}`** — Docker Compose `:?` syntax causes `docker compose up` to fail immediately with a clear error if the key is not set in `.env`. This prevents silent credential corruption (all stored N8N credentials become unreadable if the encryption key changes).
- **`NODES_EXCLUDE`** — Blocks `executeCommand`, `ssh`, and `localFileTrigger` at the N8N level. Belt-and-suspenders alongside `validate_workflow_nodes()` in `N8nCreateWorkflowTool`.
- **`EXECUTIONS_DATA_PRUNE: "true"` / `EXECUTIONS_DATA_MAX_AGE: "336"`** — Auto-prune execution history after 14 days to prevent unbounded storage growth.
- **`N8N_RUNNERS_ENABLED: "true"`** — Enables task runner isolation for code nodes.
- **`${N8N_PORT:-5678}:5678`** — Port configurable via env var, defaults to 5678.
- **`n8n_data:/home/node/.n8n`** — Named volume for persistent workflow and credential storage.

Operator workflow: set `N8N_ENCRYPTION_KEY`, `N8N_WEBHOOK_URL`, and `N8N_HOST` in `.env`, then `docker compose -f docker-compose.n8n.yml up -d`.

**Commit:** `c4a7e2d`

## Deviations from Plan

### Architecture Decision (pre-approved in plan)

**1. [Pre-approved] Separate docker-compose.n8n.yml instead of modifying existing docker-compose.yml**
- **Specified in plan:** D-20 says "added to existing docker-compose" but the plan explicitly overrides this with the Phase 31 pattern.
- **Rationale from plan:** Separate files keep concerns isolated, allow independent lifecycle management, prevent accidental N8N downtime when updating Agent42's main compose stack.
- **No additional deviation — plan itself documents this revision.**

## Verification Results

All plan verification commands pass:

- `python -c "from mcp_server import _build_registry; r = _build_registry(); print([t.name for t in r._tools.values() if 'n8n' in t.name])"` → `['n8n_workflow', 'n8n_create_workflow']`
- `python -c "import yaml; yaml.safe_load(open('docker-compose.n8n.yml')); print('Valid YAML')"` → Valid YAML
- `python -m pytest tests/test_n8n_tool.py tests/test_n8n_create_tool.py -v` → 37/37 passed
- Pre-existing `test_app_git.py` failure is unrelated to this plan (Windows path sandbox issue, documented in Plan 42-02)

## Known Stubs

None — the docker-compose.n8n.yml is fully functional configuration. The MCP registration is live and both tools are accessible to agents once N8N is running and configured.

## Self-Check: PASSED

Files verified to exist:
- `mcp_server.py` — FOUND (modified)
- `docker-compose.n8n.yml` — FOUND (created)

Commits verified:
- `fee7ae2` — feat(42-03): register N8nWorkflowTool and N8nCreateWorkflowTool in MCP server
- `c4a7e2d` — feat(42-03): add docker-compose.n8n.yml for N8N deployment
