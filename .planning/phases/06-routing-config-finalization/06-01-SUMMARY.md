---
phase: 06-routing-config-finalization
plan: 01
subsystem: routing
tags: [routing, config, multi-provider, cerebras, groq, codestral, health-check]
dependency_graph:
  requires: [01-01, 02-01, 03-01, 04-01, 05-01]
  provides: [multi-provider-routing, gemini-free-tier-flag, openrouter-free-only-flag, cheap-tier-fallback, cheap-tier-health-check]
  affects: [agents/model_router.py, agents/model_catalog.py, core/config.py]
tech_stack:
  added: []
  patterns: [provider-diverse-round-robin, cheap-tier-fallback, config-flag-enforcement]
key_files:
  created: []
  modified:
    - agents/model_router.py
    - agents/model_catalog.py
    - core/config.py
    - .env.example
    - tests/test_model_router.py
    - tests/test_dynamic_routing.py
    - tests/test_openclaw_features.py
decisions:
  - "Cerebras primary for coding/debugging/app_create: 3000 tok/s throughput makes it ideal for iteration-heavy tasks"
  - "Groq primary for research/content/strategy: 131K context + 280-500 tok/s balances context and speed for writing tasks"
  - "Codestral critic for all code task types: dedicated free code endpoint gives genuinely code-aware second opinion"
  - "CHEAP-tier fallback added after free models exhausted: SambaNova + Together AI provide fallback when all free providers down"
  - "Provider-diverse round-robin in _find_healthy_free_model: prevents single-provider exhaustion by cycling across providers"
  - "GEMINI_FREE_TIER and OPENROUTER_FREE_ONLY flags: allows operators to reduce Google dependency or enforce OR :free suffix"
  - "Gemini special-case block kept in health_check: CHEAP-tier loop skips Gemini to avoid duplicate pings"
metrics:
  duration: 17 minutes
  completed: 2026-03-02
  tasks_completed: 2
  files_modified: 7
---

# Phase 6 Plan 1: Routing Config Finalization Summary

Multi-provider task-specialized routing with provider-diverse fallback, CHEAP-tier safety net, GEMINI_FREE_TIER and OPENROUTER_FREE_ONLY config flags, and extended health checks covering SambaNova and Together AI.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add config flags + update FREE_ROUTING + provider-diverse fallback + CHEAP fallback | 4be8ec0 | core/config.py, agents/model_router.py, tests/test_model_router.py |
| 2 | Extend health check to CHEAP tier + update .env.example | 4b08c34 | agents/model_catalog.py, .env.example, tests/test_dynamic_routing.py, tests/test_openclaw_features.py |

## What Was Built

### FREE_ROUTING Updates (ROUT-01, ROUT-02, ROUT-03)

Task-type routing now leverages all registered free providers:

| Task Type | Primary | Critic |
|-----------|---------|--------|
| CODING | cerebras-gpt-oss-120b (3000 tok/s) | mistral-codestral (code-aware) |
| DEBUGGING | cerebras-gpt-oss-120b | mistral-codestral |
| APP_CREATE | cerebras-gpt-oss-120b | mistral-codestral |
| REFACTORING | gemini-2-flash (1M context) | mistral-codestral |
| RESEARCH | groq-llama-70b (131K ctx) | or-free-llama-70b |
| CONTENT | groq-llama-70b | or-free-gemma-27b |
| STRATEGY | groq-gpt-oss-120b (500 tok/s) | or-free-llama-70b |
| APP_UPDATE | gemini-2-flash | or-free-qwen-coder |
| All others | gemini-2-flash | various OR free |

### Provider-Diverse Round-Robin (ROUT-04)

`_find_healthy_free_model()` rewritten to group models by provider and alternate across groups before repeating any single provider. Accepts `skip_providers` parameter. Respects `gemini_free_tier` and `openrouter_free_only` flags (loaded inside method for test patchability).

### CHEAP-Tier Fallback (ROUT-05)

New `_find_healthy_cheap_model()` method iterates CHEAP-tier models (excluding Gemini, which is already handled by the free-model path). Called in `get_routing()` at two points:
1. When health-check detects the primary is down and no free replacement found
2. When API key validation fails and `_find_healthy_free_model()` returns None

### Config Flag Enforcement (CONF-01, CONF-02)

In `get_routing()`, before primary validation:
- `GEMINI_FREE_TIER=false`: if primary was Gemini Flash, replaced with `_find_healthy_free_model(exclude={"gemini-2-flash"})`
- `OPENROUTER_FREE_ONLY=true`: if primary is an OR model without `:free` suffix, find replacement
- Admin override always beats config flags (guarded by `is_admin_override`)

### Settings Fields (CONF-01, CONF-02)

Added to `Settings` dataclass in `core/config.py`:
```python
gemini_free_tier: bool = True   # env: GEMINI_FREE_TIER
openrouter_free_only: bool = False  # env: OPENROUTER_FREE_ONLY
```

### Health Check Extended to CHEAP Tier (INFR-04)

`health_check()` tier filter updated from `tier != ModelTier.FREE` to `tier not in (ModelTier.FREE, ModelTier.CHEAP)`. Added Gemini skip guard in the main loop to avoid double-pinging Gemini (handled by dedicated special-case block). SambaNova and Together AI are now health-checked when their API keys are set.

### .env.example Documentation (CONF-04)

Added GEMINI_FREE_TIER and OPENROUTER_FREE_ONLY entries with usage examples in the Dynamic Model Routing section.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] test_free_only_uses_free_routing_defaults assertion broken by FREE_ROUTING change**
- **Found during:** Task 1 verification
- **Issue:** Test set only GEMINI_API_KEY but CODING primary is now Cerebras. No CEREBRAS_API_KEY → fallback to OR model → assertion `routing["primary"] == FREE_ROUTING[CODING]["primary"]` fails.
- **Fix:** Added CEREBRAS_API_KEY to test's patch.dict
- **Files modified:** tests/test_model_router.py
- **Commit:** 4be8ec0 (included in task commit)

**2. [Rule 1 - Bug] 4 tests in test_dynamic_routing.py with same provider key pattern**
- **Found during:** Task 2 full suite run
- **Issue:** test_hardcoded_fallback, test_dynamic_routing_missing_task_type, test_dynamic_routing_invalid_file, test_dynamic_routing_no_file all set only GEMINI_API_KEY but now need CEREBRAS_API_KEY (coding) or GROQ_API_KEY (research) for FREE_ROUTING defaults to resolve.
- **Fix:** Added appropriate provider API keys to each test
- **Files modified:** tests/test_dynamic_routing.py
- **Commit:** 4b08c34

**3. [Rule 1 - Bug] 3 tests in test_openclaw_features.py — hardcoded gemini-2-flash assertion + broken context_window tests**
- **Found during:** Task 2 full suite run
- **Issue:** test_get_routing_default_context_unchanged hardcoded `== "gemini-2-flash"` but CODING primary is now Cerebras. Context window tests also only set GEMINI_API_KEY.
- **Fix:** Updated assertion to use `FREE_ROUTING[TaskType.CODING]["primary"]`, added CEREBRAS_API_KEY/GROQ_API_KEY. Context window assertions updated to reflect actual behavior (no FREE-tier 500K models → task default used).
- **Files modified:** tests/test_openclaw_features.py
- **Commit:** 4b08c34

## Self-Check

### Created files exist
No new files created.

### Commits exist

- 4be8ec0: feat(06-01): add config flags + multi-provider FREE_ROUTING + CHEAP fallback — FOUND
- 4b08c34: feat(06-01): extend health check to CHEAP tier + update .env.example + fix tests — FOUND

## Self-Check: PASSED

All artifacts verified:
- core/config.py has gemini_free_tier and openrouter_free_only fields
- agents/model_router.py has cerebras-gpt-oss-120b in FREE_ROUTING and _find_healthy_cheap_model method
- agents/model_catalog.py health_check includes ModelTier.CHEAP
- .env.example has GEMINI_FREE_TIER and OPENROUTER_FREE_ONLY entries
- All 1927 tests pass (24 skipped)
