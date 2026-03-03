---
phase: 05-together-ai-integration
plan: "02"
subsystem: tests
tags: [together-ai, testing, provider-registration, spending-tracker]
dependency_graph:
  requires: [05-01]
  provides: [TOGR-01-test, TOGR-02-test, TOGR-03-test]
  affects: [tests/test_providers.py, tests/test_model_catalog.py]
tech_stack:
  added: []
  patterns: [TestXxxRegistration (6 tests), TestXxxSpendingTracker (5 tests)]
key_files:
  created: []
  modified:
    - tests/test_providers.py
    - tests/test_model_catalog.py
decisions:
  - "Together AI pricing keys use org/ namespace prefix (deepseek-ai/DeepSeek-V3, meta-llama/Llama-3.3-70B-Instruct-Turbo) in _BUILTIN_PRICES — must match ModelSpec.model_id exactly"
  - "test_all_providers_registered expected set updated to include 'together'"
metrics:
  duration: "4 min"
  completed_date: "2026-03-02"
  tasks_completed: 2
  files_modified: 2
requirements: [TOGR-01, TOGR-02, TOGR-03]
---

# Phase 5 Plan 02: Together AI Test Coverage Summary

**One-liner:** 11 unit tests for Together AI registration (6) and org-namespaced SpendingTracker pricing (5) with zero regressions across 1927-test suite.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add TestTogetherRegistration to test_providers.py | d5e2569 | tests/test_providers.py |
| 2 | Add TestTogetherSpendingTracker to test_model_catalog.py | febe35d | tests/test_model_catalog.py |

## What Was Built

### TestTogetherRegistration (6 tests in tests/test_providers.py)

- `test_together_provider_registered` — TOGR-01: ProviderType.TOGETHER in PROVIDERS with correct base_url (`https://api.together.xyz/v1`), api_key_env (`TOGETHER_API_KEY`), and display_name (`Together AI`)
- `test_together_models_registered` — TOGR-02: Both models (`together-deepseek-v3`, `together-llama-70b`) registered with correct org-namespaced model_ids and CHEAP tier
- `test_together_models_all_cheap_tier` — All 2 Together AI models are CHEAP tier (credits required)
- `test_together_context_windows` — TOGR-02: DeepSeek-V3 at 128000, Llama-70B at 131000 tokens
- `test_together_client_builds_with_key` — Client builds successfully when TOGETHER_API_KEY is set
- `test_together_client_raises_without_key` — ValueError raised when TOGETHER_API_KEY is empty

Also updated `test_all_providers_registered` expected set to include `"together"`.

### TestTogetherSpendingTracker (5 tests in tests/test_model_catalog.py)

- `test_together_llama_builtin_prices_exist` — `meta-llama/Llama-3.3-70B-Instruct-Turbo` key in `_BUILTIN_PRICES` with non-zero pricing
- `test_together_deepseek_builtin_prices_exist` — `deepseek-ai/DeepSeek-V3` key in `_BUILTIN_PRICES` with non-zero pricing
- `test_together_llama_incurs_cost` — record_usage with org-namespaced model_id records non-zero daily_spend_usd
- `test_together_deepseek_incurs_cost` — record_usage with org-namespaced model_id records non-zero daily_spend_usd
- `test_together_not_free_model_detection` — `_get_price` resolves to explicit entry (not $0 free path), price[0] > 0

## Verification Results

- TestTogetherRegistration: 6/6 passed
- TestTogetherSpendingTracker: 5/5 passed
- Full test suite: 1927 passed, 24 skipped, 0 failures

## Deviations from Plan

None - plan executed exactly as written.

## Key Design Notes

**Org-namespace prefix in pricing keys:** Together AI model_ids include an org prefix (e.g., `deepseek-ai/DeepSeek-V3`, `meta-llama/Llama-3.3-70B-Instruct-Turbo`). The `_BUILTIN_PRICES` keys must exactly match the `ModelSpec.model_id` to avoid falling back to the conservative $5/$15 per M token fallback pricing. This is the first provider in the codebase to use org-namespaced pricing keys.

**No transforms needed:** Together AI is fully OpenAI spec-compliant — no temperature clamping, no stream=False override, no strict removal. No transform tests were needed for this phase (contrast with Phase 4 SambaNova which required 5 transform tests).

## Self-Check: PASSED

| Item | Status |
|------|--------|
| tests/test_providers.py | FOUND |
| tests/test_model_catalog.py | FOUND |
| Commit d5e2569 (Task 1) | FOUND |
| Commit febe35d (Task 2) | FOUND |
