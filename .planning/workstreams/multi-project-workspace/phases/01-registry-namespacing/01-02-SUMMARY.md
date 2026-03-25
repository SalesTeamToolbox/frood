---
phase: 01-registry-namespacing
plan: 02
subsystem: frontend/namespace
tags: [javascript, monaco, localstorage, namespace, workspace]
dependency_graph:
  requires: []
  provides: [WORKSPACE_URI_SCHEME, makeWorkspaceUri, wsKey]
  affects: [dashboard/frontend/dist/app.js]
tech_stack:
  added: []
  patterns: [workspace-uri-scheme, storage-key-namespacing]
key_files:
  created: []
  modified:
    - dashboard/frontend/dist/app.js
decisions:
  - "Placed helpers after brand constants section, before API helpers — logical grouping with other module-level declarations"
  - "Used var (not const/let) to match existing coding style in app.js"
  - "WORKSPACE_URI_SCHEME defined as 'workspace' per ISOL-06 requirement"
  - "wsKey format is ws_{id}_{key} per ISOL-07 requirement"
  - "cc_hist_{sessionId} explicitly documented as NOT needing namespace — session UUIDs already globally unique"
metrics:
  duration: "5m"
  completed: "2026-03-24"
  tasks_completed: 1
  tasks_total: 1
  files_modified: 1
---

# Phase 01 Plan 02: Workspace Namespace Helpers Summary

**One-liner:** JavaScript workspace URI scheme constant and storage key namespace helpers added to app.js — pure definition, no behavior change, locking the Phase 2 migration contract.

## What Was Built

Added three namespace convention artifacts to `dashboard/frontend/dist/app.js`:

1. **`WORKSPACE_URI_SCHEME`** constant (= `"workspace"`) — the URI scheme for all workspace-scoped Monaco model URIs going forward.

2. **`makeWorkspaceUri(workspaceId, filePath)`** — produces `workspace://{workspaceId}/{filePath}` strings. Phase 2 will call this from `ideOpenFile()` instead of the current `"file:///" + path` construction.

3. **`wsKey(workspaceId, key)`** — produces `ws_{workspaceId}_{key}` strings. Phase 2 will call this for all workspace-scoped localStorage and sessionStorage keys (`cc_active_session`, `cc_panel_width`, `cc_panel_session_id`).

All helpers were placed after brand constants and before the API helpers section, matching the existing module-level declaration style.

## Verification

- `grep -c "WORKSPACE_URI_SCHEME" app.js` → 2 (definition + usage in makeWorkspaceUri)
- `grep -c "function makeWorkspaceUri" app.js` → 1
- `grep -c "function wsKey" app.js` → 1
- `grep -n "file:///"` → line 3802 (untouched original Monaco URI)
- Existing localStorage/sessionStorage call sites at lines 4854, 4858, 6383, 6403, 6496, 6499 — all unchanged
- Python test suite: 314 passed, 1 pre-existing error (test_auth_flow.py — documented in MEMORY.md as known since v2.0)

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None — this plan is purely additive definitions. The helpers exist but are not yet called by any production code path. That is intentional by design: Phase 2 plans will wire the call sites. No stub that blocks the plan's goal (locking the namespace contract) exists.

## Phase 2 Contract Locked

The following conventions are now the authoritative specification for Phase 2:

| Item | Format | Notes |
|------|--------|-------|
| Monaco workspace URI | `workspace://{workspaceId}/{filePath}` | Replace `file:///` + path |
| Namespaced storage key | `ws_{workspaceId}_{key}` | For cc_active_session, cc_panel_width, cc_panel_session_id |
| Auth token key | `agent42_token` (no prefix) | Global — workspace-independent |
| Onboarding flag key | `a42_first_done` (no prefix) | Global — one-time flag |
| Chat history key | `cc_hist_{sessionId}` (no prefix) | Session UUIDs are already globally unique |

## Self-Check: PASSED

- `dashboard/frontend/dist/app.js` exists and contains all required definitions
- Commit `65c8558` exists in git log
- No files created or modified outside the task scope
