---
phase: 01-foundation-cerebras
plan: 01
subsystem: providers
tags: [cerebras, provider-registry, model-routing, spending-tracker, async-openai]

# Dependency graph
requires: []
provides:
  - "ProviderType enum extended with CEREBRAS, GROQ, MISTRAL, MISTRAL_CODESTRAL, SAMBANOVA, TOGETHER values"
  - "Cerebras ProviderSpec registered with base_url https://api.cerebras.ai/v1"
  - "4 Cerebras ModelSpec entries: cerebras-gpt-oss-120b, cerebras-qwen3-235b, cerebras-llama-8b, cerebras-zai-glm"
  - "SpendingTracker._BUILTIN_PRICES has $0 entries for all 4 Cerebras model_ids"
  - "Settings.cerebras_api_key field for introspection/reporting"
affects: [02-groq, 03-mistral, 04-sambanova, 05-together, 06-routing]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "OpenAI-compatible client pattern: ProviderType enum + ProviderSpec + ModelSpec + _BUILTIN_PRICES = complete provider registration"
    - "Zero-cost pricing: explicit (0.0, 0.0) entries in _BUILTIN_PRICES prevent conservative-fallback spend-cap trips for free providers"

key-files:
  created: []
  modified:
    - providers/registry.py
    - core/config.py
    - .env.example
    - tests/test_providers.py
    - tests/test_model_catalog.py

key-decisions:
  - "CUSTOM enum value kept at end of ProviderType — 6 new providers inserted before CUSTOM to maintain enum ordering"
  - "Cerebras display_name simplified to 'Provider Name (Cerebras)' pattern vs plan's '(~3000 tok/s)' verbose form"
  - "Cerebras ProviderSpec default_model set to llama3.1-8b (lightest model) for health check purposes"
  - "$0 pricing keyed by model_id (not model_key) to match SpendingTracker._get_price() resolution step 2"

patterns-established:
  - "4-step provider registration: ProviderType enum value + ProviderSpec in PROVIDERS + ModelSpec(s) in MODELS + _BUILTIN_PRICES entries"
  - "Free provider model_id-keyed pricing: Cerebras model_ids don't match 'or-free-' prefix or ':free' suffix, so explicit $0 entries are mandatory"

requirements-completed: [CERE-01, CERE-02, CERE-03, CERE-04, INFR-01, INFR-02, INFR-05]

# Metrics
duration: 15min
completed: 2026-03-02
---

# Phase 1 Plan 01: Foundation — Cerebras Provider Registration Summary

**Cerebras registered as free-tier provider via OpenAI-compatible AsyncOpenAI client with 4 ModelSpecs (gpt-oss-120b, qwen-3-235b, llama3.1-8b, zai-glm-4.7), $0 SpendingTracker pricing, and 6 new ProviderType enum values for all Phase 1-5 providers**

## Performance

- **Duration:** 15 min
- **Started:** 2026-03-02T05:06:00Z
- **Completed:** 2026-03-02T05:21:05Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments

- Extended ProviderType enum with all 6 new provider values (CEREBRAS, GROQ, MISTRAL, MISTRAL_CODESTRAL, SAMBANOVA, TOGETHER) — future phases only need ProviderSpec + ModelSpec, not enum changes
- Registered Cerebras as a functional provider: ProviderSpec with correct base_url/api_key_env, 4 FREE-tier ModelSpecs covering 8K-65K context windows
- Added $0 _BUILTIN_PRICES entries keyed by model_id to prevent SpendingTracker conservative fallback from falsely tripping the daily spend cap
- Added Settings.cerebras_api_key field (introspection/reporting) with correct from_env() wiring
- Added 10 new tests (TestCerebrasRegistration x5 + TestCerebrasSpendingTracker x5) — all pass

## Task Commits

1. **Task 1: ProviderType enum, Cerebras ProviderSpec, ModelSpecs, pricing** - `3aac192` (feat)
2. **Task 2: cerebras_api_key Settings field and .env.example documentation** - `195ab0c` (feat)

## Files Created/Modified

- `providers/registry.py` - Added 6 ProviderType enum values, Cerebras ProviderSpec, 4 Cerebras ModelSpecs, 4 $0 _BUILTIN_PRICES entries
- `core/config.py` - Added cerebras_api_key field to Settings dataclass and from_env() method
- `.env.example` - Added CEREBRAS_API_KEY comment with signup URL and key format
- `tests/test_providers.py` - Added TestCerebrasRegistration class (5 tests): provider/model registration, FREE tier, client builds with key, raises without key
- `tests/test_model_catalog.py` - Added TestCerebrasSpendingTracker class (5 tests): _BUILTIN_PRICES entries, zero cost recording, all models, spend limit check, token tracking

## Decisions Made

- **Enum placement:** 6 new values inserted between VLLM and CUSTOM in ProviderType. CUSTOM kept at end as documented. No ordering issues.
- **ModelSpec display_name pattern:** Used "Model Name (Cerebras)" pattern (e.g., "GPT-OSS 120B (Cerebras)") rather than plan's verbose "(~3000 tok/s)" form — cleaner for UI display
- **$0 pricing keyed by model_id:** Cerebras model IDs (e.g., "gpt-oss-120b") don't match "or-free-" prefix or ":free" suffix, so explicit entries in _BUILTIN_PRICES at resolution step 2 are mandatory
- **No new dependencies:** AsyncOpenAI works directly with Cerebras API — no cerebras-cloud-sdk needed (per plan)

## Deviations from Plan

None — plan executed exactly as specified. All functionality was already present in the working tree (prior partial implementation) and verified correct against the plan's verification checks.

## Issues Encountered

None — all 69 provider and catalog tests passed on first run. Verification script confirmed all 7 requirements satisfied (CERE-01 through CERE-04, INFR-01, INFR-02, INFR-05).

## User Setup Required

None required to start Agent42 — graceful degradation is in place (`CEREBRAS_API_KEY` not set logs an error but does not crash).

To activate Cerebras inference:
1. Sign up at https://cloud.cerebras.ai/ (free account, no credit card needed)
2. Add `CEREBRAS_API_KEY=csk-xxxxxxxx` to `.env`
3. Restart Agent42

## Next Phase Readiness

- Phase 1 Plan 01 complete: all ProviderType enum values for Phases 2-6 are in place
- Cerebras is fully registered and operational once API key is set
- Phase 2 (Groq) can proceed immediately — ProviderType.GROQ already exists, only ProviderSpec + ModelSpec needed

---
*Phase: 01-foundation-cerebras*
*Completed: 2026-03-02*
