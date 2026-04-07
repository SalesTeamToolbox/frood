---
phase: 34-system-simplification
plan: "01"
subsystem: core/config
tags: [cleanup, dead-code, config, l1-l2-removal]
dependency_graph:
  requires: []
  provides: [Settings without L1/L2 fields, .env.example without L1/L2 section]
  affects: [core/config.py, .env.example]
tech_stack:
  added: []
  patterns: [dead-code removal, config cleanup]
key_files:
  modified:
    - core/config.py
    - .env.example
decisions:
  - "gemini_free_tier inline comment updated: removed stale FALLBACK_ROUTING reference (Rule 1 auto-fix)"
metrics:
  duration: "~10 minutes"
  completed: "2026-04-06"
  tasks: 2
  files: 2
---

# Phase 34 Plan 01: Remove Dead L1/L2 Config Fields Summary

**One-liner:** Deleted 8 dead L1/L2 Settings fields and 29-line .env.example section left over from superseded tier-routing system; full 2190-test suite stays green.

## What Was Done

Removed all L1/L2 agent tier system dead configuration from two files:

### core/config.py

**Dataclass fields removed (former lines 272-280):**
- `l1_default_model: str = ""`
- `l1_critic_model: str = ""`
- `l2_enabled: bool = True`
- `l2_default_model: str = ""`
- `l2_default_profile: str = ""`
- `l2_auto_escalate: bool = False`
- `l2_auto_escalate_task_types: str = ""`
- `l2_task_types: str = ""`

**from_env() assignments removed (former lines 547-555):**
All 8 corresponding `os.getenv("L1_*")` / `os.getenv("L2_*")` calls deleted.

**Comment cleaned:**
- Stale `FALLBACK_ROUTING` term removed from `gemini_free_tier` inline comment (auto-fix Rule 1 — referenced a routing system that no longer exists)

### .env.example

Removed 29-line section (`# ── L1/L2 Agent Tier System` through per-task-type L2 model overrides), including:
- Section header and description block
- L1_DEFAULT_MODEL, L1_CRITIC_MODEL
- L2_ENABLED, L2_DEFAULT_MODEL, L2_DEFAULT_PROFILE, L2_AUTO_ESCALATE, L2_AUTO_ESCALATE_TASK_TYPES, L2_TASK_TYPES
- Per-task-type L2 model override comment block

Section spacing before `# ── Recursive Language Models` preserved (blank line intact).

## Verification

### Post-removal checks

```
grep "l1_default_model|l2_enabled|FALLBACK_ROUTING" core/config.py  → no output (PASS)
grep "L1/L2 Agent Tier System" .env.example                         → no output (PASS)
grep -rn "l1_default_model|l2_enabled|l2_auto_escalate" core/ tests/ → no output (PASS)
python -c "from core.config import settings; print(settings.rewards_enabled)"  → False (PASS)
```

### Test suite

```
python3 -m pytest tests/ -x -q
2190 passed, 11 skipped, 14 xfailed, 46 xpassed, 548 warnings in 283.06s
```

## SIMPLIFY-03/04/05 Confirmed Already Satisfied

**SIMPLIFY-03: Provider config consolidated**
`grep -rn "PROVIDER_MODELS" core/ --include="*.py"` shows PROVIDER_MODELS defined and used exclusively in `core/agent_manager.py` (and referenced in `core/tiered_routing_bridge.py`). Confirmed consolidated — no scattered provider config files.

**SIMPLIFY-04: No unused health check functions**
`grep -rn "health_check|healthcheck" core/ --include="*.py"` returns only `core/app_manager.py:async def health_check(self, app_id)` — this is an app health check (active, used), not a dead provider health check. No unused provider health checks exist.

**SIMPLIFY-05: AgentRuntime._build_env clean**
`grep -n "l1|l2|L1|L2" core/agent_runtime.py` returns no output. AgentRuntime has zero L1/L2 references — confirmed clean.

## Commits

| Hash | Message |
| ---- | ------- |
| 9e98dff | feat(34-01): remove dead L1/L2 config fields from Settings dataclass |
| 636ec1c | feat(34-01): remove L1/L2 section from .env.example |
| 7e77203 | fix(34-01): remove stale FALLBACK_ROUTING reference from gemini_free_tier comment |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Removed stale FALLBACK_ROUTING reference from gemini_free_tier comment**
- **Found during:** Final success criteria verification (Task 2)
- **Issue:** `gemini_free_tier` field comment read "When false, Gemini excluded from FALLBACK_ROUTING and fallback" — FALLBACK_ROUTING routing system no longer exists and was the same concept being removed in this plan
- **Fix:** Updated comment to "When false, Gemini excluded from free-tier fallback routing"
- **Files modified:** `core/config.py` (line 273)
- **Commit:** 7e77203

## Known Stubs

None — this plan removes code only, no new stubs introduced.

## Self-Check: PASSED

Files verified:
- `core/config.py` — exists, no l1_/l2_ fields, no FALLBACK_ROUTING references
- `.env.example` — exists, no L1/L2 Agent Tier System section

Commits verified:
- 9e98dff — FOUND
- 636ec1c — FOUND
- 7e77203 — FOUND
