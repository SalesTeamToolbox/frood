---
phase: 06-routing-config-finalization
plan: 02
subsystem: test-coverage
tags: [testing, routing, config-flags, multi-provider, cerebras, groq, codestral, cheap-tier]
dependency_graph:
  requires: [06-01]
  provides: [routing-test-coverage, config-flag-tests, fallback-diversity-tests, cheap-tier-health-check-tests, multi-provider-integration-tests]
  affects: [tests/test_model_router.py, tests/test_model_catalog.py]
tech_stack:
  added: []
  patterns: [tdd-green-on-existing-impl, settings-mock-all-fields, patch-dict-env-isolation]
key_files:
  created: []
  modified:
    - tests/test_model_router.py
    - tests/test_model_catalog.py
decisions:
  - "MagicMock for settings must include ALL fields router reads (model_routing_policy, gemini_free_tier, openrouter_free_only) to avoid AttributeError on the frozen dataclass mock"
  - "TestFallbackChainDiversity tests use explicit empty-string env overrides to simulate missing keys (empty string is falsy in api_key check)"
  - "TestCheapTierFallback.test_get_routing_uses_cheap_fallback confirms SambaNova wins when all free provider keys are absent"
  - "TestHealthCheckCheapTier uses patch.dict without clear=True to only override specific keys — simpler isolation for health check"
metrics:
  duration: 5 minutes
  completed: 2026-03-02
  tasks_completed: 2
  files_modified: 2
---

# Phase 6 Plan 2: Routing Config Finalization — Test Coverage Summary

29 new test assertions across 7 test classes covering multi-provider routing, provider-diverse fallback, CHEAP-tier escalation, GEMINI_FREE_TIER and OPENROUTER_FREE_ONLY config flags, and CHEAP-tier health check inclusion.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add routing and config flag tests to test_model_router.py | e7aae5c | tests/test_model_router.py |
| 2 | Add CHEAP-tier health check test to test_model_catalog.py | 5763d6e | tests/test_model_catalog.py |

## What Was Built

### TestFreeRoutingUpdates (ROUT-01/02/03) — 11 tests

Directly asserts FREE_ROUTING dict entries for every task-type that changed in Plan 01:
- Cerebras primary for CODING, DEBUGGING, APP_CREATE
- Codestral critic for CODING, DEBUGGING, REFACTORING, APP_CREATE
- Groq primary for RESEARCH (groq-llama-70b), CONTENT (groq-llama-70b), STRATEGY (groq-gpt-oss-120b)
- EMAIL unchanged at gemini-2-flash (regression guard)

### TestFallbackChainDiversity (ROUT-04/TEST-05) — 3 tests

- `test_fallback_returns_different_provider`: With GROQ_API_KEY set and cerebras excluded, verifies fallback doesn't return cerebras
- `test_fallback_skips_unhealthy_models`: Mocks catalog to mark all models unhealthy except groq-llama-70b; asserts that model is returned
- `test_fallback_returns_none_when_no_keys`: All provider keys set to empty string; asserts None returned (empty string is falsy in `if api_key` check)

### TestCheapTierFallback (ROUT-05) — 3 tests

- `test_cheap_fallback_returns_sambanova_or_together`: With SAMBANOVA_API_KEY set, `_find_healthy_cheap_model()` returns a sambanova key
- `test_cheap_fallback_skips_gemini`: Gemini is CHEAP tier but excluded from the cheap search (covered by free path)
- `test_get_routing_uses_cheap_fallback`: Full `get_routing()` integration — all free keys absent, SAMBANOVA_API_KEY present → primary is a sambanova model

### TestGeminiFreeTierFlag (CONF-01/TEST-04) — 3 tests

- `test_gemini_excluded_from_fallback`: gemini_free_tier=False → `_find_healthy_free_model()` skips Gemini provider
- `test_gemini_excluded_from_routing_primary`: EMAIL task (defaults to gemini-2-flash) gets a non-Gemini primary when flag is off
- `test_admin_override_beats_gemini_flag`: AGENT42_EMAIL_MODEL=gemini-2-flash wins even when gemini_free_tier=False

### TestOpenrouterFreeOnlyFlag (CONF-02/TEST-04) — 3 tests

- `test_or_free_only_skips_non_free_suffix`: Registers a test OR model without :free suffix; asserts it is not returned
- `test_or_free_only_allows_free_suffix`: With OR key set and flag on, returned model (if OR) must have :free suffix
- `test_or_free_only_does_not_affect_non_or_providers`: Cerebras still returned when only CEREBRAS_API_KEY is set

### TestMultiProviderIntegration (TEST-06) — 4 tests

- `test_coding_routes_to_cerebras_with_key`: CEREBRAS_API_KEY + CODESTRAL_API_KEY → primary=cerebras-gpt-oss-120b, critic=mistral-codestral
- `test_research_routes_to_groq_with_key`: GROQ_API_KEY → primary=groq-llama-70b
- `test_missing_primary_key_falls_to_alternative`: No CEREBRAS key but GROQ key → primary falls back (not cerebras)
- `test_all_providers_routing`: All 6 provider keys set → CODING=cerebras, RESEARCH/CONTENT=groq-llama-70b, STRATEGY=groq-gpt-oss-120b

### TestHealthCheckCheapTier (INFR-04) — 2 tests

- `test_cheap_tier_included_in_health_check`: SAMBANOVA_API_KEY + TOGETHER_API_KEY set → health_check results include both providers' model keys
- `test_cheap_tier_skipped_without_key`: All keys absent (empty string) → no SambaNova or Together models in health check results

## Deviations from Plan

None — plan executed exactly as written. Implementation from Plan 01 already existed; all 29 new tests went straight to GREEN.

## Test Count

| File | Before | After | New Tests |
|------|--------|-------|-----------|
| tests/test_model_router.py | 17 | 44 | 27 |
| tests/test_model_catalog.py | 70 | 72 | 2 |
| **Full suite** | **1927** | **1956** | **29** |

## Self-Check

### Created files exist

No new files created.

### Commits exist

- e7aae5c: test(06-02): add routing and config flag test classes to test_model_router.py — FOUND
- 5763d6e: test(06-02): add TestHealthCheckCheapTier class to test_model_catalog.py — FOUND

## Self-Check: PASSED

All artifacts verified:
- tests/test_model_router.py has 6 new test classes (TestFreeRoutingUpdates through TestMultiProviderIntegration)
- tests/test_model_catalog.py has TestHealthCheckCheapTier with 2 tests
- All 1956 tests pass (24 skipped)
- No regressions introduced
