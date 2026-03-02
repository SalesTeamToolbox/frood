---
phase: 05-together-ai-integration
verified: 2026-03-02T22:30:00Z
status: passed
score: 9/9 must-haves verified
re_verification: false
---

# Phase 5: Together AI Integration Verification Report

**Phase Goal:** Together AI is registered as a credits-based provider with verified model IDs and accurate pricing documentation that correctly labels it as credits-required (not free)
**Verified:** 2026-03-02T22:30:00Z
**Status:** PASSED
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | ProviderType.TOGETHER has a ProviderSpec in PROVIDERS with base_url https://api.together.xyz/v1 | VERIFIED | `providers/registry.py` line 159-165: `ProviderType.TOGETHER: ProviderSpec(base_url="https://api.together.xyz/v1", ...)` — programmatic assertion passed |
| 2 | Two Together AI ModelSpecs exist in MODELS (together-deepseek-v3, together-llama-70b) classified as CHEAP tier | VERIFIED | `providers/registry.py` lines 347-364: both ModelSpecs present, `tier=ModelTier.CHEAP`, model count == 2 confirmed |
| 3 | SpendingTracker has non-zero pricing entries for both Together AI model_ids including org/ prefix | VERIFIED | `_BUILTIN_PRICES["deepseek-ai/DeepSeek-V3"] = (0.60e-6, 1.70e-6)` and `_BUILTIN_PRICES["meta-llama/Llama-3.3-70B-Instruct-Turbo"] = (0.88e-6, 0.88e-6)` at registry.py lines 454-455 |
| 4 | Settings.together_api_key loads from TOGETHER_API_KEY env var | VERIFIED | `core/config.py` line 55: `together_api_key: str = ""`, line 332: `together_api_key=os.getenv("TOGETHER_API_KEY", "")` |
| 5 | Agent42 does not crash when TOGETHER_API_KEY is absent | VERIFIED | `Settings.from_env()` defaults to empty string; `registry.get_client()` raises ValueError (expected behavior, not a crash); programmatic import confirmed clean |
| 6 | TestTogetherRegistration class exists with 6 passing tests | VERIFIED | `tests/test_providers.py` line 492-539: 6 substantive tests, all 6 passed in live test run (1.43s) |
| 7 | TestTogetherSpendingTracker class exists with 5 passing tests | VERIFIED | `tests/test_model_catalog.py` line 694-741: 5 substantive tests, all 5 passed in live test run |
| 8 | test_all_providers_registered expected set includes "together" | VERIFIED | `tests/test_providers.py` line 21: `expected = {..., "sambanova", "together"}` |
| 9 | All existing provider and catalog tests still pass (no regressions) | VERIFIED | Full run: `tests/test_providers.py` + `tests/test_model_catalog.py` — 120 passed, 0 failed |

**Score:** 9/9 truths verified

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `providers/registry.py` | ProviderSpec, 2 ModelSpecs, 2 pricing entries | VERIFIED | ProviderSpec at line 159, ModelSpecs at lines 347/356, pricing at lines 454-455 |
| `core/config.py` | together_api_key Settings field and from_env() loading | VERIFIED | Field at line 55, env loading at line 332 |
| `.env.example` | TOGETHER_API_KEY documented with credits-required label | VERIFIED | Lines 33-35: "CHEAP tier (credits required, funded account needed)" |
| `tests/test_providers.py` | TestTogetherRegistration class (6 tests) | VERIFIED | Class at line 492, all 6 tests substantive and passing |
| `tests/test_model_catalog.py` | TestTogetherSpendingTracker class (5 tests) | VERIFIED | Class at line 694, all 5 tests substantive and passing |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `MODELS["together-deepseek-v3"].model_id` | `_BUILTIN_PRICES["deepseek-ai/DeepSeek-V3"]` | exact string match including org/ prefix | WIRED | `model_id = "deepseek-ai/DeepSeek-V3"` at registry.py line 348; pricing key `"deepseek-ai/DeepSeek-V3"` at line 455 — exact match confirmed |
| `MODELS["together-llama-70b"].model_id` | `_BUILTIN_PRICES["meta-llama/Llama-3.3-70B-Instruct-Turbo"]` | exact string match including org/ prefix | WIRED | `model_id = "meta-llama/Llama-3.3-70B-Instruct-Turbo"` at registry.py line 357; pricing key at line 454 — exact match confirmed |
| `TestTogetherRegistration` | `PROVIDERS[ProviderType.TOGETHER]` | direct import and assertion | WIRED | Tests import from `providers.registry`, assert `spec.base_url == "https://api.together.xyz/v1"` |
| `TestTogetherSpendingTracker` | `SpendingTracker._BUILTIN_PRICES` | direct import and key assertion with org/ prefix | WIRED | Tests assert `"meta-llama/Llama-3.3-70B-Instruct-Turbo" in SpendingTracker._BUILTIN_PRICES` |

---

## Requirements Coverage

| Requirement | Source Plans | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| TOGR-01 | 05-01, 05-02 | Register ProviderType.TOGETHER with ProviderSpec (base_url: `https://api.together.xyz/v1`, api_key_env: `TOGETHER_API_KEY`) | SATISFIED | ProviderSpec present in PROVIDERS dict at registry.py line 159; `test_together_provider_registered` asserts all three fields |
| TOGR-02 | 05-01, 05-02 | Register ModelSpec entries — `together-deepseek-v3` and `together-llama-70b`, classified as ModelTier.CHEAP | SATISFIED | Both ModelSpecs in MODELS at registry.py lines 347/356 with `tier=ModelTier.CHEAP`; `test_together_models_registered` and `test_together_context_windows` verify model_ids, tier, and context windows |
| TOGR-03 | 05-01, 05-02 | Add credit-based pricing to SpendingTracker for Together AI models | SATISFIED | Org-namespaced pricing entries at registry.py lines 454-455: DeepSeek $0.60/$1.70 per M tokens, Llama $0.88/$0.88 per M tokens; `TestTogetherSpendingTracker` verifies non-zero pricing and cost recording |

**All 3 requirements satisfied. No orphaned requirements detected.**

REQUIREMENTS.md status column for all three: marked `[x] Complete`.

---

## Anti-Patterns Found

None detected. Scan of all 5 phase-modified files (`providers/registry.py`, `core/config.py`, `.env.example`, `tests/test_providers.py`, `tests/test_model_catalog.py`) found:
- No TODO/FIXME/HACK/PLACEHOLDER comments in Together AI sections
- No empty implementations (return null, return {}, etc.)
- No stub handlers

---

## Human Verification Required

None. All phase 5 changes are data registration (no UI, no real-time behavior, no external service calls made during the phase). The test suite verifies all observable behaviors programmatically.

---

## Commits Verified

| Hash | Description | Status |
|------|-------------|--------|
| `998098a` | feat(05-01): add Together AI ProviderSpec, ModelSpecs, and pricing to registry | EXISTS |
| `b68c64a` | feat(05-01): add together_api_key to Settings and document in .env.example | EXISTS |
| `d5e2569` | test(05-02): add TestTogetherRegistration to test_providers.py | EXISTS |
| `febe35d` | test(05-02): add TestTogetherSpendingTracker to test_model_catalog.py | EXISTS |

---

## Summary

Phase 5 goal is fully achieved. Together AI is registered as a credits-based CHEAP-tier provider with:

- A `ProviderSpec` at `https://api.together.xyz/v1` using `TOGETHER_API_KEY`
- Two `ModelSpec` entries with org-namespaced model IDs (`deepseek-ai/DeepSeek-V3`, `meta-llama/Llama-3.3-70B-Instruct-Turbo`) both classified `ModelTier.CHEAP`
- Accurate per-token pricing in `_BUILTIN_PRICES` with org-namespace keys that exactly match `ModelSpec.model_id` — the critical wiring that prevents falling back to the $5/$15 conservative pricing fallback
- `Settings.together_api_key` loading from `TOGETHER_API_KEY` env var with graceful empty-string default
- `.env.example` documentation explicitly labeled "CHEAP tier (credits required, funded account needed)"
- 11 new unit tests (6 registration + 5 spending tracker) all passing, with zero regressions across the 120-test provider/catalog suite

All 3 requirements (TOGR-01, TOGR-02, TOGR-03) are satisfied and marked complete in REQUIREMENTS.md.

---

_Verified: 2026-03-02T22:30:00Z_
_Verifier: Claude (gsd-verifier)_
