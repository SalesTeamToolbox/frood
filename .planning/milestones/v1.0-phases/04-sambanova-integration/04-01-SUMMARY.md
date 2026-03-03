---
phase: 04-sambanova-integration
plan: 01
subsystem: providers
tags: [sambanova, provider-registration, request-transforms, spending-tracker, config]
dependency_graph:
  requires: []
  provides: [sambanova-provider, sambanova-llama-70b, sambanova-deepseek-v3, sambanova-pricing, sambanova-transforms]
  affects: [providers/registry.py, core/config.py, .env.example]
tech_stack:
  added: [SambaNova OpenAI-compatible API]
  patterns: [provider-registration, inline-request-transforms, deepcopy-protection]
key_files:
  modified:
    - providers/registry.py
    - core/config.py
    - .env.example
decisions:
  - "SambaNova PROVIDERS entry already existed from Phase 1 (INFR-01) - only ModelSpecs, pricing, and transforms were needed"
  - "DeepSeek-V3-0324 used as model_id (dated release alias, more stable than DeepSeek-V3.1)"
  - "import copy placed inside SAMB-05 guard block (Python caches module imports, O(1) subsequent calls)"
  - "stream=False enforced only in complete_with_tools() - simple completions don't stream by default"
metrics:
  duration: "~8 min"
  completed_date: "2026-03-02"
  tasks_completed: 2
  files_modified: 3
---

# Phase 4 Plan 1: SambaNova Provider Registration and Request Transforms Summary

**One-liner:** SambaNova credits-based provider registered with 2 CHEAP-tier models, mixed-case pricing, and 3 inline API compatibility transforms (temp clamp, stream=False, strict removal).

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add SambaNova ProviderSpec, 2 ModelSpecs, pricing, and 3 request transforms | b051559 | providers/registry.py |
| 2 | Add sambanova_api_key to Settings and document in .env.example | 0418b45 | core/config.py, .env.example |

## What Was Built

### providers/registry.py

**ModelSpec entries (CHEAP tier):**
- `sambanova-llama-70b` → `Meta-Llama-3.3-70B-Instruct` (128K context, $0.60/$1.20 per M tokens)
- `sambanova-deepseek-v3` → `DeepSeek-V3-0324` (128K context, $0.80/$1.60 per M tokens)

**Pricing entries in `_BUILTIN_PRICES`:**
- `"Meta-Llama-3.3-70B-Instruct": (0.60e-6, 1.20e-6)` — mixed-case key, exact match to model_id
- `"DeepSeek-V3-0324": (0.80e-6, 1.60e-6)` — mixed-case key, exact match to model_id

**Request transforms:**
- **SAMB-03** (temp clamp): `resolved_temp = min(resolved_temp, 1.0)` when `spec.provider == ProviderType.SAMBANOVA` — in BOTH `complete()` and `complete_with_tools()`
- **SAMB-04** (stream=False): `kwargs["stream"] = False` when SAMBANOVA provider and tools present — only in `complete_with_tools()`
- **SAMB-05** (strict removal): `copy.deepcopy(tools)` then sets `fn["strict"] = False` for any `strict: true` — only in `complete_with_tools()`

### core/config.py

- `sambanova_api_key: str = ""` field added to Settings dataclass
- `sambanova_api_key=os.getenv("SAMBANOVA_API_KEY", "")` added to `from_env()`

### .env.example

- `SAMBANOVA_API_KEY` documented with signup URL and CHEAP tier note

## Decisions Made

1. **ProviderSpec already existed**: `ProviderType.SAMBANOVA` enum value and PROVIDERS entry were both added in Phase 1 (INFR-01). Task 1 only needed ModelSpecs, pricing, and transforms — no ProviderSpec addition required.

2. **Mixed-case model IDs critical**: SambaNova uses `Meta-Llama-3.3-70B-Instruct` and `DeepSeek-V3-0324` (not lowercase). Both `ModelSpec.model_id` and `_BUILTIN_PRICES` keys use exact mixed-case to ensure pricing lookup works (case mismatch triggers $5/$15 conservative fallback).

3. **deepcopy for SAMB-05**: The `copy.deepcopy(tools)` before mutating `strict` fields ensures the caller's original tool list is never modified. This is the first provider requiring tool list mutation before API call.

4. **No FREE_ROUTING changes**: SambaNova is CHEAP tier (credits required). Routing integration is Phase 6 (ROUT-05).

## Deviations from Plan

None - plan executed exactly as written. The note about ProviderSpec already existing (from Phase 1) was correctly documented in the plan itself and was not a deviation.

## Verification Results

All plan verification checks passed:
- PROVIDERS[ProviderType.SAMBANOVA] has correct base_url and api_key_env
- MODELS has sambanova-llama-70b and sambanova-deepseek-v3 (both CHEAP tier, mixed-case model_ids)
- SpendingTracker returns non-zero cost for both models via _BUILTIN_PRICES lookup
- complete() source contains SAMBANOVA guard and min() clamp
- complete_with_tools() source contains SAMBANOVA guard, stream, strict, and deepcopy
- Settings.sambanova_api_key exists with empty string default
- 90 provider/registry tests pass, 0 failures

## Self-Check: PASSED

Files exist:
- providers/registry.py — FOUND (modified)
- core/config.py — FOUND (modified)
- .env.example — FOUND (modified)

Commits exist:
- b051559 — FOUND (feat(04-01): add SambaNova ProviderSpec, 2 ModelSpecs, pricing, and 3 request transforms)
- 0418b45 — FOUND (feat(04-01): add sambanova_api_key to Settings and document in .env.example)
