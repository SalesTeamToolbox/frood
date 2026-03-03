---
phase: 05-together-ai-integration
plan: 01
subsystem: providers
tags: [together-ai, provider-registration, cheap-tier, spending-tracker, config]
dependency_graph:
  requires: [01-01]  # ProviderType.TOGETHER enum value from Phase 1 infra
  provides: [TOGR-01, TOGR-02, TOGR-03]
  affects: [providers/registry.py, core/config.py, .env.example]
tech_stack:
  added: []
  patterns: [org-namespaced-model-id, cheap-tier-credits-provider]
key_files:
  created: []
  modified:
    - providers/registry.py
    - core/config.py
    - .env.example
decisions:
  - "Together AI _BUILTIN_PRICES keys use org/ namespace prefix (deepseek-ai/DeepSeek-V3, meta-llama/Llama-3.3-70B-Instruct-Turbo) matching ModelSpec.model_id exactly — case-sensitive lookup, mismatch triggers $5/$15 conservative fallback"
  - "ProviderType.TOGETHER enum value already existed from Phase 1 (INFR-01) — only ProviderSpec and ModelSpecs added here, no enum modification needed"
  - "Together AI fully OpenAI spec-compliant — no request transforms needed (no temp clamp, no stream workaround, no strict removal)"
metrics:
  duration: "5 min"
  completed: "2026-03-02T22:08:07Z"
  tasks: 2
  files_modified: 3
---

# Phase 5 Plan 01: Together AI Provider Registration Summary

**One-liner:** Together AI registered as CHEAP-tier credits provider with 2 org-namespaced models (DeepSeek V3 128K + Llama 3.3 70B Turbo 131K) and accurate per-token pricing.

## What Was Built

Together AI has been registered as Agent42's 6th independent inference backend. The integration follows the same CHEAP-tier credits pattern established by SambaNova in Phase 4, with one key difference: Together AI uses org-namespaced model IDs (e.g., `deepseek-ai/DeepSeek-V3`) rather than bare model names.

**Models added:**
- `together-deepseek-v3` — DeepSeek V3 via Together AI, 128K context, $0.60/M input + $1.70/M output
- `together-llama-70b` — Llama 3.3 70B Instruct Turbo, 131K context, $0.88/M flat (in+out)

**Configuration:**
- `Settings.together_api_key` field loads from `TOGETHER_API_KEY` env var
- `.env.example` documents TOGETHER_API_KEY with CHEAP tier labeling and signup URL

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add Together AI ProviderSpec, 2 ModelSpecs, and pricing to registry.py | 998098a | providers/registry.py |
| 2 | Add together_api_key to Settings and document in .env.example | b68c64a | core/config.py, .env.example |

## Verification Results

- `ProviderType.TOGETHER in PROVIDERS` — PASSED
- `PROVIDERS[ProviderType.TOGETHER].base_url == 'https://api.together.xyz/v1'` — PASSED
- `together-deepseek-v3` and `together-llama-70b` in MODELS — PASSED
- Both models are `ModelTier.CHEAP` — PASSED
- `deepseek-ai/DeepSeek-V3` in `_BUILTIN_PRICES` with non-zero pricing — PASSED
- `meta-llama/Llama-3.3-70B-Instruct-Turbo` in `_BUILTIN_PRICES` with non-zero pricing — PASSED
- `Settings.together_api_key` loads from env, defaults to `""` — PASSED
- `.env.example` contains `TOGETHER_API_KEY` — PASSED
- Together AI model count = 2 — PASSED
- `tests/test_providers.py` + `tests/test_model_catalog.py`: 109 passed, 0 failed — PASSED

## Decisions Made

1. **Org-namespaced model IDs**: Together AI model IDs include the `org/ModelName` prefix (e.g., `deepseek-ai/DeepSeek-V3`). The `_BUILTIN_PRICES` keys must match exactly — a case or prefix mismatch triggers the $5/$15 conservative fallback that would instantly exhaust the daily spend cap.

2. **ProviderType.TOGETHER enum pre-exists**: The enum value was created in Phase 1 (INFR-01) alongside all other provider types. Only the `ProviderSpec` registration was needed here — no enum modification required.

3. **No request transforms**: Together AI is fully OpenAI spec-compliant. No temperature clamping, no streaming workarounds, no strict mode removal needed (unlike SambaNova).

4. **No FREE_ROUTING changes**: Together AI is CHEAP tier (credits required). Routing changes targeting CHEAP tier models are Phase 6 scope (ROUT-05).

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check

- `providers/registry.py` — modified with ProviderSpec, ModelSpecs, pricing entries
- `core/config.py` — modified with together_api_key field and from_env() loading
- `.env.example` — modified with TOGETHER_API_KEY documentation block
- Commit 998098a exists (Task 1)
- Commit b68c64a exists (Task 2)
- 109 provider/model catalog tests pass

## Self-Check: PASSED
