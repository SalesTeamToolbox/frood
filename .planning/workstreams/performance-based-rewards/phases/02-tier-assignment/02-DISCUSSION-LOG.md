# Phase 2: Tier Assignment - Discussion Log (Assumptions Mode)

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions captured in CONTEXT.md — this log preserves the analysis.

**Date:** 2026-03-22
**Phase:** 02-Tier Assignment
**Mode:** assumptions
**Areas analyzed:** AgentConfig Tier Fields, TierDeterminator, Background Recalculation Loop, Admin Override Persistence

## Assumptions Presented

### AgentConfig Tier Fields
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| Add reward_tier, tier_override, performance_score, tier_computed_at to AgentConfig | Confident | core/agent_manager.py:128-167 uses dataclass with from_dict/to_dict/asdict round-trip |
| tier_override uses None as sentinel, recalculation skips when not None | Likely | AgentRoutingStore strips None; matches codebase idiom |

### TierDeterminator
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| New class in core/reward_system.py, maps score+observations to tier string | Confident | Phase 1 convention — all scoring/tier logic in one module |
| Returns "provisional" when below min_observations, lowercase tier strings | Confident | AgentConfig.status uses lowercase strings; asdict() doesn't serialize enums |

### Background Recalculation Loop
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| HeartbeatService pattern: start()/stop(), asyncio.create_task, 900s interval | Confident | core/heartbeat.py:311-329 is canonical; SecurityScanner follows same pattern |

### Admin Override Persistence
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| Override stored on AgentConfig field, persisted via agents/{id}.json | Likely | AgentManager.update() already handles partial setattr; no new file infrastructure needed |

## Corrections Made

No corrections — all assumptions auto-confirmed in --auto mode.

---
*Log generated: 2026-03-22*
