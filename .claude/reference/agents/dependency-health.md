# Dependency Health Agent

## Purpose

Verify OpenRouter model availability against the MODELS dict, check pip package versions against PyPI, and flag stale or dead entries in model routing configuration. This agent helps prevent production failures caused by dead models (Pitfall 90) and outdated dependencies.

## Context

Agent42 uses a dynamic model routing system with multiple LLM providers:

- **Model registry:** `providers/registry.py` contains the `MODELS` dict (model ID -> ModelSpec) and `PROVIDERS` dict (provider name -> ProviderSpec)
- **Routing config:** `model_router.py` contains the `FREE_ROUTING` dict with fallback model lists per task type
- **Dependencies:** `requirements.txt` has pinned pip package versions
- **Known issue:** Dead OR free models have caused infrastructure failures (Pitfall 90, 91) — ComplexityAssessor, IntentClassifier, and Learner broke when models went offline

### External APIs

- **OpenRouter model list:** `GET https://openrouter.ai/api/v1/models` (no auth required) — returns `{"data": [{"id": "model-id", ...}]}`
- **PyPI package info:** `GET https://pypi.org/pypi/<package>/json` — returns `{"info": {"version": "X.Y.Z"}}`

## Analysis Steps

1. **Extract model registry:**
   Read `providers/registry.py`. Extract all model IDs from the `MODELS` dict. Group by provider (openrouter, gemini, cerebras, groq, mistral, sambanova, together, etc.). Note the total count per provider.

2. **Check OpenRouter model availability:**
   Fetch `https://openrouter.ai/api/v1/models` using `curl` or the WebFetch tool. Extract the `id` field from each model in the `data` array. Cross-reference against all OpenRouter model IDs in the MODELS dict. Flag any IDs not found in the API response as DEAD or RENAMED. Check if similar model IDs exist (suggesting a rename).

3. **Check fallback model lists:**
   Read `model_router.py`. Find the `FREE_ROUTING` dict and any other hardcoded model ID lists (critic models, fallback chains). Cross-reference each model ID against the OpenRouter API response. Flag dead models in fallback lists — these cause silent failures and wasted retry time (Pitfall 91).

4. **Check pip dependencies:**
   Read `requirements.txt`. For each package with a pinned version (e.g., `openai==1.x.x`), fetch `https://pypi.org/pypi/<package>/json` and compare `info.version` (latest) against the pinned version. Flag packages that are:
   - 1+ **major** version behind (CRITICAL — likely breaking changes)
   - 2+ **minor** versions behind (WARN — may have useful fixes/features)
   - Packages without pinned versions (INFO — could cause reproducibility issues)

5. **Check for security advisories:**
   Run `pip audit` (if available) or `safety check -r requirements.txt` to identify known CVEs in pinned package versions. If neither tool is available, note this as a gap and recommend installation.

## Output Format

```
# Dependency Health Report

## Model Availability

### By Provider
| Provider | Total | Alive | Dead | Renamed |
|----------|-------|-------|------|---------|
| OpenRouter | N | N | N | N |
| Gemini | N | -- | -- | -- |

### OpenRouter Model Status
| Model ID | Status | Notes |
|----------|--------|-------|
| openrouter/model-name | ALIVE | -- |
| openrouter/dead-model | DEAD | Not found in API response |
| openrouter/old-name | RENAMED | Now available as new-name |

## Stale Fallbacks
| File | Line | Model ID | Status | Impact |
|------|------|----------|--------|--------|
| model_router.py | 45 | or-free-mistral-small | DEAD | Critic fallback will fail, wasting retry time |

## Package Versions
| Package | Pinned | Latest | Behind | Action |
|---------|--------|--------|--------|--------|
| openai | 1.30.0 | 1.35.0 | 5 minor | Update recommended |
| fastapi | 0.110.0 | 0.115.0 | 5 minor | Update recommended |
| qdrant-client | 1.17.0 | 1.17.0 | Current | -- |

## Security Advisories
[Any CVEs found by pip audit or safety check, with severity and affected package]

## Summary
- Models: N alive, N dead, N renamed
- Packages: N current, N outdated, N with CVEs
- Action items: [prioritized list of fixes]
```
