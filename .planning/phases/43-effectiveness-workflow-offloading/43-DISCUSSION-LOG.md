# Phase 43: Effectiveness-Driven Workflow Offloading - Discussion Log (Assumptions Mode)

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions captured in CONTEXT.md — this log preserves the analysis.

**Date:** 2026-04-05
**Phase:** 43-effectiveness-workflow-offloading
**Mode:** assumptions
**Areas analyzed:** Pattern Detection, Effectiveness Integration, Suggestion Mechanism, Auto-Creation Flow, Configuration

## Assumptions Presented

### Pattern Detection
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| New tool_sequences table in effectiveness.db | Likely | memory/effectiveness.py:52-140 existing table patterns |
| MD5 fingerprint of tool name sequence for dedup | Likely | Simple, proven approach for sequence matching |
| Threshold of 3+ executions triggers suggestion | Likely | Balances sensitivity vs noise |

### Effectiveness Integration
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| Hook into ToolRegistry.execute() for accumulation | Confident | tools/registry.py:131-148 existing hook pattern |
| Task-scoped accumulator via task_context | Confident | core/task_context.py:71-104 lifecycle hooks |
| Heuristic token savings (1000 tokens/run) | Likely | No spend_history in main runtime yet |

### Suggestion Mechanism
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| Agent prompt injection via _build_prompt() | Likely | core/agent_runtime.py:72-95 existing injection point |
| No dashboard panel in Phase 43 | Confident | Scope boundary — keep it prompt-only |
| Suggestion stored in workflow_suggestions table | Likely | Follows effectiveness.db pattern |

### Auto-Creation Flow
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| Template selection heuristic based on tool types | Likely | tools/n8n_templates/ has 3 templates |
| workflow_mappings table for pattern→workflow storage | Likely | Follows effectiveness.db pattern |
| N8N_AUTO_CREATE_WORKFLOWS config setting | Likely | Follows existing config patterns |

## Corrections Made

No corrections — all assumptions auto-confirmed (user approved approach).

## Auto-Resolved

None — no Unclear items.
