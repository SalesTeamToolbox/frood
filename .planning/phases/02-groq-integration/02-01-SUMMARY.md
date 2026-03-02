---
phase: 02-groq-integration
plan: 01
subsystem: providers
tags: [groq, provider, registry, config, free-tier]
dependency_graph:
  requires: [01-01]
  provides: [GROQ-01, GROQ-02, GROQ-03, GROQ-04]
  affects: [providers/registry.py, core/config.py, .env.example]
tech_stack:
  added: []
  patterns: [ProviderSpec registration, ModelSpec declaration, SpendingTracker pricing]
key_files:
  modified:
    - providers/registry.py
    - core/config.py
    - .env.example
decisions:
  - "openai/gpt-oss-120b namespace prefix retained in ModelSpec.model_id and _BUILTIN_PRICES key to ensure SpendingTracker $0 pricing lookup matches exactly"
  - "No default_model set on Groq ProviderSpec — routing handles model selection dynamically"
  - "requires_model_prefix=False (default) is correct for Groq — no provider prefix needed in API calls"
metrics:
  duration: "4 min"
  completed: "2026-03-02"
  tasks_completed: 2
  tasks_total: 2
  files_modified: 3
---

# Phase 2 Plan 1: Groq Provider Registration Summary

**One-liner:** Groq registered as free provider with 3 OpenAI-compatible models (llama-3.3-70b-versatile, openai/gpt-oss-120b, llama-3.1-8b-instant) and $0 SpendingTracker pricing covering 131K context windows.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add Groq ProviderSpec, 3 ModelSpecs, and $0 pricing entries | 8abcd99 | providers/registry.py |
| 2 | Add groq_api_key to Settings and document in .env.example | 3f204ba | core/config.py, .env.example |

## What Was Built

### providers/registry.py

Added three changes:

1. **Groq ProviderSpec** in `PROVIDERS` dict after the Cerebras entry:
   - `base_url`: `https://api.groq.com/openai/v1` (OpenAI-compatible)
   - `api_key_env`: `GROQ_API_KEY`
   - `supports_function_calling`: `True`

2. **3 Groq ModelSpec entries** in `MODELS` dict after Cerebras models:
   - `groq-llama-70b`: `llama-3.3-70b-versatile` — 131K context, 8192 max_tokens
   - `groq-gpt-oss-120b`: `openai/gpt-oss-120b` — 131K context, 8192 max_tokens (includes namespace prefix)
   - `groq-llama-8b`: `llama-3.1-8b-instant` — 131K context, 4096 max_tokens
   - All: `ModelTier.FREE`, `ProviderType.GROQ`

3. **$0 pricing entries** in `SpendingTracker._BUILTIN_PRICES`:
   - `"llama-3.3-70b-versatile": (0.0, 0.0)`
   - `"openai/gpt-oss-120b": (0.0, 0.0)` — key includes `openai/` prefix to match ModelSpec.model_id exactly
   - `"llama-3.1-8b-instant": (0.0, 0.0)`

### core/config.py

- Added `groq_api_key: str = ""` field to `Settings` dataclass
- Added `groq_api_key=os.getenv("GROQ_API_KEY", "")` to `Settings.from_env()`

### .env.example

Added documentation block after Cerebras section:
```
# Groq — free inference (rate-limited on free plan, no credit card required)
# Get key: https://console.groq.com/ (free account)
# GROQ_API_KEY=gsk_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

## Verification Results

All plan verification checks passed:
- GROQ-01: ProviderType.GROQ in PROVIDERS with correct base_url and api_key_env
- GROQ-02: 3 ModelSpecs with correct model_ids, provider, and 131K context windows
- GROQ-03: All 3 models classified ModelTier.FREE
- GROQ-04: SpendingTracker records $0.00 for all 3 Groq model_ids

Full test suite: **1876 passed, 24 skipped, 0 failures** — no regressions.

## Deviations from Plan

None — plan executed exactly as written.

## Decisions Made

1. **openai/gpt-oss-120b namespace prefix**: The `_BUILTIN_PRICES` key for this model is `"openai/gpt-oss-120b"` (with prefix) matching `ModelSpec.model_id` exactly. Using just `"gpt-oss-120b"` would miss the lookup and trigger the conservative $5/$15 fallback pricing.

2. **No default_model on ProviderSpec**: Groq's ProviderSpec has no `default_model` — routing dynamically selects among the 3 registered models. This matches how Cerebras was wired.

3. **No groq Python package**: The `AsyncOpenAI` client works directly with Groq's OpenAI-compatible endpoint. No additional dependency needed (same pattern as all other providers).

## Self-Check: PASSED

- FOUND: providers/registry.py
- FOUND: core/config.py
- FOUND: .env.example
- FOUND commit: 8abcd99 (Task 1)
- FOUND commit: 3f204ba (Task 2)
