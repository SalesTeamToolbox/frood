# Phase 1: Foundation - Discussion Log (Assumptions Mode)

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions captured in CONTEXT.md — this log preserves the analysis.

**Date:** 2026-03-22
**Phase:** 01-Foundation
**Mode:** assumptions
**Areas analyzed:** Schema Extension, RewardsConfig Runtime Toggle, Tier Cache and Persistence, Composite Score

## Assumptions Presented

### Schema Extension
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| Add agent_id column to existing tool_invocations via ALTER TABLE migration | Likely | memory/effectiveness.py has no agent_id; tools/registry.py:87 already receives agent_id but drops it before record() call |
| Thread agent_id from ToolRegistry.execute() into EffectivenessStore.record() | Likely | Only one call site at registry.py:131-138 needs changing |
| Add get_agent_stats(agent_id) reusing existing get_aggregated_stats() query | Likely | Existing query at effectiveness.py:110-142 computes all needed dimensions |

### RewardsConfig Runtime Toggle
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| Non-frozen dataclass backed by .agent42/rewards_config.json, AgentRoutingStore pattern | Confident | agents/agent_routing_store.py:43-62 shows mtime lazy load, os.replace() atomic write |
| Settings.rewards_enabled as startup gate, RewardsConfig for runtime toggle | Confident | core/config.py:39 is frozen=True, cannot mutate after import |

### Tier Cache and Persistence
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| Hand-rolled time.monotonic() TTL dict, no cachetools | Likely | core/rate_limiter.py:59,81 uses this pattern; no cachetools imports in codebase |
| Persistence at .agent42/tier_assignments.json | Likely | .agent42/ used for approvals.jsonl, devices.jsonl, memory/, sessions/ |

### Composite Score
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| 60/25/15 weights from tool_invocations (success_rate, COUNT, AVG duration_ms) | Likely | Research SUMMARY.md recommends these weights; effectiveness.py already stores these fields |

## Corrections Made

No corrections — all assumptions auto-confirmed in --auto mode.

## Auto-Resolved

No Unclear items — all assumptions were Confident or Likely, no auto-resolution needed.

---
*Log generated: 2026-03-22*
