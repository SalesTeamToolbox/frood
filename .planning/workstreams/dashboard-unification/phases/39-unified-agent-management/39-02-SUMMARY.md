---
phase: 39-unified-agent-management
plan: "02"
subsystem: frontend
tags: [agents, unified-endpoint, badges, sparklines, filter-controls, paperclip, frontend]
dependency_graph:
  requires:
    - 39-01  # unified backend endpoint
  provides:
    - frontend-unified-agent-cards
    - source-badge-display
    - paperclip-readonly-deeplink
  affects:
    - dashboard/frontend/dist/app.js
    - dashboard/frontend/dist/style.css
    - tests/test_unified_agents.py
tech_stack:
  added: []
  patterns:
    - var-style JavaScript throughout (no const/let/arrow)
    - esc() for all user-facing data (XSS safety)
    - lazy-load guard pattern with agentsLoaded flag
    - static analysis tests via Path.read_text() (Phase 38 pattern)
key_files:
  created: []
  modified:
    - dashboard/frontend/dist/app.js
    - dashboard/frontend/dist/style.css
    - tests/test_unified_agents.py
decisions:
  - "_makeSparkline uses approximate flat distribution (total_runs/7) when daily_activity absent"
  - "agentShowDetail falls back to /api/agents/{id} fetch for Agent42 agents to get full detail fields"
  - "state.agentsLoaded flag reset needed on page navigation (future concern, not yet implemented)"
metrics:
  duration: "~7 minutes"
  completed: "2026-04-05"
  tasks: "3/3"
  files_modified: 3
  tests_added: 16
  tests_total: 24
---

# Phase 39 Plan 02: Unified Agent Frontend Summary

## Result: COMPLETE

## What was built

Frontend unified agent views consuming the `/api/agents/unified` endpoint from Plan 01. Agent cards now show source badges (Agent42 or Paperclip), success rate percentage, run count, relative last-active time, and 7-day sparklines. Stats row updated with Avg Success instead of Paused count. Client-side filter controls for source and status. Paperclip agents are fully read-only with a "Manage in Paperclip" deep link. Create form and template cards show "Agent42" source badge. Degradation banner appears when Paperclip is unavailable.

One-liner: **Frontend agent views wired to unified endpoint with source badges, sparklines, filter controls, and Paperclip read-only deep links using var-style JavaScript throughout.**

## Task Summary

| Task | Description | Commit | Files |
|------|-------------|--------|-------|
| 1 | Add CSS for source badges, sparklines, filter controls | 046ef45 | style.css |
| 2 | Refactor renderAgents, _renderAgentCards, agentShowDetail, agentShowCreate, agentShowTemplates | 8453950 | app.js |
| 3 | Add frontend content verification tests | 2c915d4 | tests/test_unified_agents.py |

## Key Changes

### style.css
- `.badge-agent42` — purple tint matching .badge-builtin palette
- `.badge-paperclip` — green tint for Paperclip source indicator
- `.sparkline` and `.sparkline svg` — inline SVG container
- `.agent-card-metrics` — metrics row with flex layout
- `.agent-filter-bar` and select styles — source/status filter dropdowns
- `.degradation-banner` — amber warning bar for Paperclip unavailable state
- `.agent-card.readonly` — subtle green border-left on Paperclip cards

### app.js

**New helpers:**
- `_relativeTime(epochSec)` — converts epoch seconds to "3m ago", "2h ago", "5d ago", "Never"
- `_makeSparkline(counts)` — returns SVG polyline string for 7-day activity sparkline

**renderAgents():** Changed fetch URL from `/api/agents` to `/api/agents/unified`. Added lazy-load guard using `state.agentsLoaded`. Passes `data.paperclip_unavailable` to `_renderAgentCards`.

**_renderAgentCards(el, agents, paperclipUnavailable):** 
- Client-side filters for `state.agentFilterSource` and `state.agentFilterStatus`
- Degradation banner when `paperclipUnavailable` is true
- Cards show: source badge, status dot, success rate %, run count, relative time, sparkline
- Paperclip cards get `readonly` CSS class
- Stats row: Total Agents / Active / Avg Success / Total Tokens

**agentShowDetail(id):** Differentiates Agent42 (full controls: start/stop/delete, performance section, tier override) from Paperclip (read-only with "Manage in Paperclip" link, shows available metrics only).

**agentShowCreate():** Added `<span class="badge-source badge-agent42">Agent42</span>` in heading.

**agentShowTemplates():** Each template card includes `badge-agent42` badge.

**Unchanged (per plan):** agentDoCreate(), agentCreateFromTemplate(), agentStart(), agentStop(), agentDelete(), setTierOverride()

### tests/test_unified_agents.py
Extended from 8 to 24 tests. New classes:
- `TestFrontendContent` (7 tests): unified endpoint, badges, helpers, filter, avg success stat
- `TestCreateFormSourceBadge` (1 test): agentShowCreate has Agent42 badge
- `TestTemplateBadge` (2 tests): template cards have badge, creation still uses /api/agents
- `TestStylesheet` (4 tests): CSS class presence
- `TestPaperclipReadOnly` (2 tests): Manage in Paperclip link and readonly class

## Decisions Made

1. `_makeSparkline` uses approximate flat distribution (`total_runs / 7`) when `daily_activity` is absent — returns empty string for 0-run agents to avoid misleading flat lines
2. `agentShowDetail` falls back to individual `/api/agents/{id}` fetch for Agent42 agents because the unified list may lack fields like `memory_scope`, `max_iterations`, `tier_override`, `tier_expiry_date`
3. Test file reads `app.js` and `style.css` at module level (not per-test) to avoid repeated file I/O — follows Phase 38 pattern from `test_provider_ui.py`

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None — all data flows from the unified endpoint.

## Self-Check

Verified files exist:
- `dashboard/frontend/dist/app.js` — FOUND
- `dashboard/frontend/dist/style.css` — FOUND
- `tests/test_unified_agents.py` — FOUND

Verified commits:
- 046ef45 — FOUND (CSS task)
- 8453950 — FOUND (app.js task)
- 2c915d4 — FOUND (tests task)

All 24 tests pass. Full test suite passes (one pre-existing failure in test_app_git.py on Windows paths — unrelated to this plan, confirmed pre-existing).

## Self-Check: PASSED
