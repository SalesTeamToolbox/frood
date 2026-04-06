# Phase 38: Provider UI Updates - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions captured in CONTEXT.md — this log preserves the discussion.

**Date:** 2026-04-04
**Phase:** 38-provider-ui-updates
**Mode:** discuss (advisor)
**Areas discussed:** Provider structure & naming, Synthetic.new model display, Provider status display, Model selection UX

## Gray Areas Presented

User selected all 4 gray areas for discussion.

## Advisor Research

4 parallel research agents spawned (sonnet model, standard calibration tier). Each analyzed the codebase and returned comparison tables.

## Decisions Made

### Provider Structure & Naming

| Option | Description |
|--------|-------------|
| **Subscription vs API (SELECTED)** | CC Subscription as read-only status, API Key Providers section below |
| Routing-chain narrative | Numbered steps showing routing priority |
| Flat list with role badges | No sections, inline role badges |

**Key findings from research:**
- Gemini labeled "Recommended" primary but has no routing logic (dead provider in config.py)
- CC Subscription uses CLI token, not API key — shouldn't have a key input field
- StrongWall cleanup is minimal: 1 comment + backup file
- Current "Primary/Premium" labels don't match actual routing chain

### Synthetic.new Model Display

| Option | Description |
|--------|-------------|
| **Collapsible card (SELECTED)** | Card below API key field, collapsed by default, follows orStatus pattern |
| Always-visible table | Full table always rendered inline |
| New Model Catalog tab | Separate settings tab with filters |

**Key findings from research:**
- Backend SyntheticApiClient fully built with model discovery + caching
- orStatus card pattern is exact match for the UI approach
- New endpoint needed: GET /api/providers/synthetic/models
- 10 capability categories mapped by update_provider_models_mapping()

### Provider Status & Connectivity

| Option | Description |
|--------|-------------|
| **Key-presence + live check (SELECTED)** | Badges + new endpoint that pings providers, auto-loads on tab enter |
| Key-presence badges only | Show configured/not configured, no live ping |
| Manual check button only | Live ping but user must click to trigger |

**Key findings from research:**
- Storage status endpoint (/api/settings/storage) is the closest pattern to mirror
- health-dot CSS already has all needed status color variants
- /api/providers is intentionally stubbed (MCP pivot) — use new endpoint instead
- No auto-poll timer — only check on tab enter + manual refresh

### Model Selection UX

| Option | Description |
|--------|-------------|
| **Dynamic dropdown with optgroup (SELECTED)** | Provider change fetches models, shown in optgroup by category |
| Category picker only | User picks category, backend resolves model |
| Category + advanced override | Category picker with toggle for manual model ID |

**Key findings from research:**
- GET /api/agents/models already exists and returns the right data shape
- AgentConfig.model already stores arbitrary model ID strings
- Agent form currently has hardcoded select that doesn't change per provider
- Cache-age awareness recommended for stale model lists

## Corrections Made

No corrections — all recommended approaches confirmed.
