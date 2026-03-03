---
phase: 03-mistral-integration
plan: 01
subsystem: providers
tags: [mistral, codestral, provider-registration, spending-tracker, config]
dependency_graph:
  requires: [01-01, 02-01]
  provides: [MIST-01, MIST-02, MIST-03, MIST-04, MIST-05]
  affects: [providers/registry.py, core/config.py, .env.example]
tech_stack:
  added: []
  patterns: [ProviderSpec registration, ModelSpec tiers, _BUILTIN_PRICES pricing]
key_files:
  created: []
  modified:
    - providers/registry.py
    - core/config.py
    - .env.example
decisions:
  - "Mistral Codestral placed in FREE tier (dedicated free API, 30 RPM) — not CHEAP"
  - "La Plateforme models (mistral-large, mistral-small) placed in CHEAP tier — credits required"
  - "max_context_tokens=32000 for Codestral per REQUIREMENTS.md spec (community reports 256K but unverified)"
  - "Conservative La Plateforme pricing: $2.00/$6.00 per M for large, $0.20/$0.60 for small"
metrics:
  duration: "4 min"
  completed_date: "2026-03-02"
  tasks_completed: 2
  files_modified: 3
---

# Phase 3 Plan 1: Mistral Provider Registration Summary

**One-liner:** Dual Mistral provider integration — Codestral (free code endpoint, MISTRAL_CODESTRAL) and La Plateforme (credits-based, MISTRAL) — with accurate $0/$2/$0.20 per-million-token SpendingTracker pricing.

## What Was Built

Registered Mistral's two separate API endpoints as distinct providers in Agent42's registry, along with three models spanning FREE and CHEAP tiers.

### Changes Made

**`providers/registry.py`** — 3 additive changes:

1. **2 ProviderSpec entries added to PROVIDERS dict:**
   - `ProviderType.MISTRAL` → `https://api.mistral.ai/v1` (La Plateforme, credits-based)
   - `ProviderType.MISTRAL_CODESTRAL` → `https://codestral.mistral.ai/v1` (free code specialist)

2. **3 ModelSpec entries added to MODELS dict:**
   - FREE tier: `mistral-codestral` (`codestral-latest`, 32K context, MISTRAL_CODESTRAL provider)
   - CHEAP tier: `mistral-large` (`mistral-large-latest`, 128K context, MISTRAL provider)
   - CHEAP tier: `mistral-small` (`mistral-small-latest`, 128K context, MISTRAL provider)

3. **3 pricing entries added to `_BUILTIN_PRICES`:**
   - `codestral-latest`: `(0.0, 0.0)` — free endpoint
   - `mistral-large-latest`: `(2.0e-6, 6.0e-6)` — $2.00/$6.00 per million tokens
   - `mistral-small-latest`: `(0.20e-6, 0.60e-6)` — $0.20/$0.60 per million tokens

**`core/config.py`** — 2 new Settings fields:
- `mistral_api_key: str = ""` — populated by `MISTRAL_API_KEY` env var
- `codestral_api_key: str = ""` — populated by `CODESTRAL_API_KEY` env var

**`.env.example`** — 2 new provider blocks documented with:
- Signup URLs (`https://console.mistral.ai/`)
- Tier classification (CHEAP for La Plateforme, FREE for Codestral)
- Note that Codestral key is separate from the main API key

## Verification Results

All MIST-01 through MIST-05 assertions passed:
- PROVIDERS dict contains both Mistral entries with correct URLs and env var names
- MODELS dict contains mistral-codestral (FREE), mistral-large and mistral-small (CHEAP)
- SpendingTracker returns $0.0000 for Codestral and non-zero for La Plateforme models
- Settings has both new API key fields with empty string defaults
- `.env.example` contains both MISTRAL_API_KEY and CODESTRAL_API_KEY

Test suite: **1887 passed, 24 skipped, 0 failures** (no regressions)

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| Task 1 | d1a4808 | feat(03-01): add 2 Mistral ProviderSpecs, 3 ModelSpecs, and 3 pricing entries |
| Task 2 | 000a9a0 | feat(03-01): add mistral_api_key and codestral_api_key to Settings and .env.example |

## Deviations from Plan

None — plan executed exactly as written. Both ProviderType enum values (`MISTRAL` and `MISTRAL_CODESTRAL`) already existed from Phase 1 INFR-01 as specified. No duplicate enum entries added.

## Self-Check: PASSED

Files verified:
- `providers/registry.py` — FOUND (modified, 46 lines added)
- `core/config.py` — FOUND (modified, 4 lines added)
- `.env.example` — FOUND (modified, 8 lines added)

Commits verified:
- d1a4808 — FOUND
- 000a9a0 — FOUND
