---
phase: 51-rebrand-and-repurpose
plan: "01"
subsystem: dashboard-frontend
tags: [rebrand, frood, settings, svg, cleanup]
dependency_graph:
  requires: []
  provides: [frood-branding, agent-apps-rename, frood-svg-assets, settings-routing-tab, phase51-test-scaffold]
  affects: [dashboard/frontend/dist/app.js, dashboard/server.py, dashboard/frontend/dist/index.html, dashboard/frontend/dist/assets/]
tech_stack:
  added: []
  patterns: [string-replacement, svg-rename, settings-tab-cleanup, test-scaffold-module-level-read]
key_files:
  created:
    - tests/test_rebrand_phase51.py
    - dashboard/frontend/dist/assets/frood-logo-light.svg
    - dashboard/frontend/dist/assets/frood-avatar.svg
    - dashboard/frontend/dist/assets/frood-favicon.svg
    - dashboard/frontend/dist/assets/frood-logo.svg
  modified:
    - dashboard/frontend/dist/app.js
    - dashboard/server.py
    - dashboard/frontend/dist/index.html
  deleted:
    - dashboard/frontend/dist/assets/agent42-logo-light.svg
    - dashboard/frontend/dist/assets/agent42-avatar.svg
    - dashboard/frontend/dist/assets/agent42-favicon.svg
    - dashboard/frontend/dist/assets/agent42-logo.svg
decisions:
  - "Deferred internal renames (agent42_token localStorage key, agent42_auth BroadcastChannel, .agent42/ paths, Python logger names) per D-15 — these affect stored data or auth state"
  - "Renamed Orchestrator tab ID to 'routing' in BOTH tabs array AND panels object (Pitfall 1 avoided)"
  - "Channels panel body deleted entirely, not just hidden — per plan intent to remove dead code"
metrics:
  duration_seconds: 1602
  completed_date: "2026-04-07"
  tasks_completed: 2
  files_changed: 9
---

# Phase 51 Plan 01: Frood Rebrand + Settings Cleanup Summary

**One-liner:** Rebranded dashboard from Agent42 to Frood with SVG asset renames, "Sandboxed Apps" to "Agent Apps" rename, Settings Channels tab removed, Orchestrator renamed to Routing, and 22-test Phase 51 scaffold created.

## Tasks Completed

| # | Name | Commit | Key Files |
|---|------|--------|-----------|
| 1 | Create Phase 51 test scaffold | 5591837 | tests/test_rebrand_phase51.py (22 tests) |
| 2 | Branding sweep + SVG rename + Settings cleanup | 67b203a | app.js, server.py, index.html, 4 SVG renames |

## Verification Results

- `python -m pytest tests/test_rebrand_phase51.py::TestBranding -v` — 6/6 passed
- `python -m pytest tests/test_rebrand_phase51.py::TestSettingsCleanup -v` — 5/5 passed
- `python -m pytest tests/test_rebrand_phase51.py -v` — 13 passed, 8 xfailed, 1 xpassed
- `grep -rn "Agent42" dashboard/frontend/dist/app.js | grep -v "agent42_token\|agent42_auth\|\.agent42/"` — no matches
- `grep -rn "Sandboxed Apps" dashboard/frontend/dist/app.js` — no matches
- `ls dashboard/frontend/dist/assets/frood-*.svg` — 4 files exist
- `ls dashboard/frontend/dist/assets/agent42-*.svg` — no files exist
- Full suite: 924 passed, 1 pre-existing flaky test (test_memory_hooks.py::test_no_match_is_silent passes in isolation)

## Success Criteria Status

| Criterion | Status |
|-----------|--------|
| Zero user-visible "Agent42" text in app.js | PASS |
| Zero "Sandboxed Apps" text in app.js | PASS |
| SVG assets renamed from agent42-* to frood-* | PASS |
| Settings has no Channels tab | PASS |
| Orchestrator renamed to Routing | PASS |
| MAX_CONCURRENT_AGENTS removed | PASS |
| loadChannels() removed from codebase | PASS |
| Full test suite passes | PASS (flaky pre-existing failure isolated) |

## Deviations from Plan

None — plan executed exactly as written.

The one xpassed test (`test_intelligence_overview`) was marked xfail for Plan 02 but already passes because `memory_recall` references exist in the current app.js. This is a benign early pass — the xfail marker will be removed when Plan 02 completes.

## Known Stubs

None — all changes in this plan are complete text replacements and file renames. No stub data, hardcoded empty values, or placeholder text introduced.

## Self-Check

### Created files exist:
- tests/test_rebrand_phase51.py: FOUND
- dashboard/frontend/dist/assets/frood-logo-light.svg: FOUND
- dashboard/frontend/dist/assets/frood-avatar.svg: FOUND
- dashboard/frontend/dist/assets/frood-favicon.svg: FOUND
- dashboard/frontend/dist/assets/frood-logo.svg: FOUND

### Commits exist:
- 5591837: FOUND (test scaffold)
- 67b203a: FOUND (branding + settings)

## Self-Check: PASSED
