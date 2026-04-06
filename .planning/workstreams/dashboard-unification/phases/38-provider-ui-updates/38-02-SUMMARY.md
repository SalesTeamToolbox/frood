---
phase: 38-provider-ui-updates
plan: 02
subsystem: dashboard
tags: [provider-ui, synthetic-models, provider-connectivity, agent-model-dropdown, frontend]

# Dependency graph
requires:
  - "38-01: GET /api/providers/synthetic/models endpoint"
  - "38-01: GET /api/settings/provider-status endpoint"
  - "38-01: GET /api/agents/models via PROVIDER_MODELS dict"
provides:
  - "Restructured Providers tab with CC Subscription, API Key Providers, Provider Connectivity, Media & Search sections"
  - "Synthetic model catalog card with expand/collapse, table, capability badges, free/paid pills, and refresh"
  - "Provider connectivity table with health-dot badges for 4 providers"
  - "Dynamic agent model dropdown in agent creation form (loadAgentModels on provider change)"
  - "loadSyntheticModels(), loadProviderStatus(), loadAgentModels() lazy-load async functions"
  - "badge-free and badge-paid CSS classes"
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Var-style string concatenation with esc() for XSS-safe innerHTML (Phase 37 convention, consistent throughout)"
    - "Lazy-load with re-render guard: if (!state.x && !state.xLoading) { loadX().then(renderSettingsPanel); } prevents infinite re-render"
    - "DOM-first callback: loadAgentModels() called after innerHTML assignment so #agent-model exists before API call"
    - "Option.textContent via new Option(text, value) — safe from XSS without innerHTML (createElement pattern)"

key-files:
  created: []
  modified:
    - dashboard/frontend/dist/app.js
    - dashboard/frontend/dist/style.css

key-decisions:
  - "Lazy-load guard on Provider Connectivity prevents infinite re-render loop (Pitfall 2 from plan context)"
  - "loadAgentModels called after DOM injection — not before — so #agent-model element exists when function runs (Pitfall 3)"
  - "Synthetic model catalog card auto-loads and shows loading state then re-renders when data arrives"
  - "Old Primary/Premium Providers labels, Model Routing v2.0, MCP Integration info boxes all removed"
  - "Gemini demoted to Media and Search (no longer Recommended primary) per D-02"

requirements-completed: [PROVIDER-02, PROVIDER-05]

# Metrics
duration: ~8min
completed: 2026-04-04
---

# Phase 38 Plan 02: Provider UI Frontend Restructure Summary

**Providers tab restructured with CC Subscription -> Synthetic.new -> API Key Providers -> Connectivity hierarchy, Synthetic model catalog with expand/collapse and refresh, provider connectivity health-dot table, dynamic agent model dropdown via loadAgentModels(), and badge-free/badge-paid CSS additions — all 19 tests now green (TDD cycle complete)**

## Performance

- **Duration:** ~8 min
- **Completed:** 2026-04-04T21:49:16Z
- **Tasks:** 1/1 (+ auto-approved checkpoint)
- **Files modified:** 2 (dashboard/frontend/dist/app.js, dashboard/frontend/dist/style.css)
- **Commits:** 1 (12639c8)

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Restructure Providers tab + new lazy-load functions + agent form dropdown | 12639c8 | dashboard/frontend/dist/app.js, dashboard/frontend/dist/style.css |
| 2 | Visual verification checkpoint | auto-approved (auto_advance=true) | — |

## What Was Built

### PROVIDER-02: Providers tab restructure

The old Providers tab had "Primary Providers" (Gemini as Recommended), "Premium Providers", "Model Routing (v2.0)" info box, and "MCP Integration" info box. All removed.

New structure:

**Section 1 - Provider Routing info box (D-04):** Explains priority order — CC Subscription -> Synthetic.new -> Anthropic/OpenRouter. Uses bg-card style matching existing info box pattern.

**Section 2 - Claude Code Subscription (D-01):** Read-only status indicator from `state.providerStatus`. Shows health-dot (h-ok or h-unavailable) with "Active — managed by Claude Code CLI" or "Not detected". No API key input. Auto-loads provider status on tab render with re-render guard.

**Section 3 - API Key Providers (D-03):**
- Synthetic.new API Key field (settingSecret, highlighted)
- Synthetic model catalog card: Collapsed shows count/free_count/cached_at + Refresh link. Expanded shows model table (Name, Capabilities as badge-type spans, Context as "128K" format, Tier as badge-free/badge-paid, Description truncated at 80 chars) plus capability mapping section. Auto-loads on tab render.
- Anthropic API Key field
- OpenRouter API Key field

**Section 4 - Provider Connectivity (D-12, D-13, D-14):** Table with Provider/Status columns. health-dot CSS class mapped from status: ok→h-ok, auth_error→h-auth_error, timeout→h-timeout, unconfigured→h-unavailable, else→h-error. Human-readable labels: Connected, Auth error, Timeout, Not configured, Unreachable. Refresh link resets state.providerStatus and re-renders.

**Section 5 - Media & Search (D-02, D-03):** Replicate, Luma, Brave, Gemini key fields. Gemini demoted here from "Recommended" Primary Providers.

**Section 6/7 - Save button and OpenRouter Account Status:** Preserved unchanged.

### PROVIDER-05: Dynamic agent model dropdown

`agentShowCreate()` now renders a provider dropdown with options: claudecode, synthetic, anthropic, openrouter — with `onchange="loadAgentModels(this.value)"`. Model dropdown starts with "Loading models..." placeholder. `loadAgentModels("claudecode")` called immediately after DOM injection.

`loadAgentModels(provider)` fetches `/api/agents/models`, extracts provider entries, creates Option elements with text `category -- modelId`. On error shows "(failed to load models)". If provider is synthetic and `state.syntheticModels.cached_at` is older than 12 hours, shows cache age note in `#agent-model-cache-note`.

### New async functions

- `loadSyntheticModels(force)` — calls `/api/providers/synthetic/models?force=true` (optional), sets state.syntheticModels
- `loadProviderStatus()` — calls `/api/settings/provider-status`, sets state.providerStatus
- `loadAgentModels(provider)` — calls `/api/agents/models`, populates #agent-model select

### CSS additions (style.css)

```css
.badge-free { background: var(--success); color: #fff; }  /* green pill */
.badge-paid { background: var(--warning); color: #1a1a2e; }  /* amber pill */
```

## Deviations from Plan

None — plan executed exactly as written. All frontend changes were pre-staged as part of the 38-01 TDD setup, confirmed green in 38-02.

## TDD Cycle Note

Plan 38-01 had 8 `TestProvidersTabStructure` tests intentionally set to red (TDD red phase). This plan (38-02) completes the TDD cycle — all 19 tests now pass green. The tests verify the exact section headings, old-label absence, and function presence that the plan required.

## Known Stubs

None — the Synthetic model catalog shows live data from `/api/providers/synthetic/models`, or "Model catalog unavailable" if not configured. No placeholder values flow to UI rendering.

## Self-Check: PASSED

- `dashboard/frontend/dist/app.js` — FOUND (modified, 221 lines added)
- `dashboard/frontend/dist/style.css` — FOUND (modified, 10 lines added)
- Commit 12639c8 — FOUND
- 19 tests pass: `python -m pytest tests/test_provider_ui.py -v` confirmed all PASSED
