# Phase 24: Sidecar Mode - Discussion Log (Assumptions Mode)

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions captured in CONTEXT.md — this log preserves the analysis.

**Date:** 2026-03-28
**Phase:** 24-Sidecar Mode
**Mode:** assumptions
**Areas analyzed:** Sidecar Server Architecture, Authentication Reuse, Callback & Async Execution, Run ID Idempotency, Structured JSON Logging

## Assumptions Presented

### Sidecar Server Architecture
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| Separate `create_sidecar_app()` in `dashboard/sidecar.py` | Confident | agent42.py headless pattern, ARCHITECTURE.md lines 146-147 |
| `--sidecar` adds third mode to Agent42 class, not separate entry point | Confident | Agent42.__init__() unconditional core init, SIDE-08 requirement |

### Authentication Reuse
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| Reuse existing HTTPBearer JWT from dashboard/auth.py | Confident | auth.py get_current_user(), _validate_jwt(), HTTPBearer security |
| Health endpoint public (no auth), all others require Bearer | Likely | Dashboard /health pattern, Paperclip testEnvironment() needs |

### Callback & Async Execution
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| Use httpx.AsyncClient for callback POST | Confident | httpx in 15+ files, established pattern |

### Run ID Idempotency
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| In-memory dict with TTL, not database table | Likely | AgentRuntime._processes dict pattern, no existing idempotency table |

### Structured JSON Logging
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| Custom stdlib logging.Formatter, no new dependencies | Confident | No third-party logging libs in codebase, ANSI stripping exists |

## Corrections Made

No corrections — all assumptions confirmed.

## External Research

Deferred to plan-phase (research SUMMARY.md flags Phase 1 as "standard patterns, no research phase needed"):
- Paperclip AdapterExecutionContext exact payload schema — derivable from hermes adapter reference + Mintlify docs
- Paperclip callback endpoint contract — documented in HTTP adapter docs

---

*Discussion log: 2026-03-28*
