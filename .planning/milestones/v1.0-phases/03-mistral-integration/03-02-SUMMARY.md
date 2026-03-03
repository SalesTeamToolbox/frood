---
phase: 03-mistral-integration
plan: "02"
subsystem: providers/tests
tags: [testing, mistral, spending-tracker, provider-registry]
dependency_graph:
  requires: [03-01]
  provides: [TestMistralRegistration, TestMistralSpendingTracker]
  affects: [tests/test_providers.py, tests/test_model_catalog.py]
tech_stack:
  added: []
  patterns: [class-based test organization, local SpendingTracker imports, dual-provider test coverage]
key_files:
  created: []
  modified:
    - tests/test_providers.py
    - tests/test_model_catalog.py
decisions:
  - Mistral test pattern mirrors Groq (8-test registration class for dual providers, 5-test spending tracker)
  - ModelTier imported locally inside test methods (consistent with Cerebras/Groq pattern)
  - TestMistralSpendingTracker validates mixed pricing: $0 for Codestral, non-zero for La Plateforme
metrics:
  duration: "3 min"
  completed: "2026-03-02"
  tasks_completed: 2
  files_modified: 2
---

# Phase 3 Plan 02: Mistral Test Coverage Summary

**One-liner:** Dual-provider Mistral test suite with $0 Codestral and non-zero La Plateforme spending tracker verification.

## What Was Built

Added two new test classes covering all Phase 3 production code:

1. **`TestMistralRegistration`** in `tests/test_providers.py` (8 tests):
   - `test_mistral_provider_registered` — MISTRAL ProviderSpec base_url, api_key_env, display_name
   - `test_mistral_codestral_provider_registered` — MISTRAL_CODESTRAL ProviderSpec base_url, api_key_env, display_name
   - `test_codestral_model_registered` — codestral-latest on MISTRAL_CODESTRAL, FREE tier, 32K context
   - `test_la_plateforme_models_registered` — mistral-large/small on MISTRAL, CHEAP tier, 128K context
   - `test_mistral_client_builds_with_key` — MISTRAL client build with MISTRAL_API_KEY
   - `test_codestral_client_builds_with_key` — MISTRAL_CODESTRAL client build with CODESTRAL_API_KEY
   - `test_mistral_client_raises_without_key` — ValueError on missing MISTRAL_API_KEY
   - `test_codestral_client_raises_without_key` — ValueError on missing CODESTRAL_API_KEY

2. **`TestMistralSpendingTracker`** in `tests/test_model_catalog.py` (5 tests):
   - `test_codestral_builtin_prices_exist` — codestral-latest has $0/$0 in _BUILTIN_PRICES
   - `test_la_plateforme_builtin_prices_exist` — mistral-large-latest and mistral-small-latest have non-zero prices
   - `test_codestral_zero_cost` — Codestral usage produces $0 daily spend
   - `test_mistral_large_incurs_cost` — La Plateforme usage produces non-zero daily spend
   - `test_mistral_tokens_tracked` — Token counts tracked for both free and paid Mistral models

Also updated `TestProviderRegistry.test_all_providers_registered` to include `"mistral"` and `"mistral_codestral"` in the expected set.

## Test Results

- `tests/test_providers.py`: 33 passed (25 original + 8 new)
- `tests/test_model_catalog.py`: 60 passed (55 original + 5 new)
- Full suite: 1900 passed, 24 skipped, 2 warnings — no regressions

## Deviations from Plan

None - plan executed exactly as written.

## Key Decisions

- Dual-provider test coverage requires 8 tests (not 6 like single-provider phases) because both MISTRAL and MISTRAL_CODESTRAL need independent client-build and graceful-failure tests
- Mixed pricing validation is the key differentiator from Cerebras/Groq: Codestral uses a genuinely free endpoint ($0), while La Plateforme is credits-based (non-zero)
- `ModelTier` imported locally inside methods to stay consistent with the existing Cerebras and Groq test pattern in both files

## Commits

- `c20eaf7`: test(03-02): add TestMistralRegistration to test_providers.py
- `f0c3a8e`: test(03-02): add TestMistralSpendingTracker to test_model_catalog.py

## Self-Check: PASSED
