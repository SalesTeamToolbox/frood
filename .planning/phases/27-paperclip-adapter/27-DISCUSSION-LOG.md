# Phase 27: Paperclip Adapter - Discussion Log (Assumptions Mode)

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions captured in CONTEXT.md — this log preserves the analysis.

**Date:** 2026-03-30
**Phase:** 27-paperclip-adapter
**Mode:** assumptions (auto)
**Areas analyzed:** Package structure, Callback handling, Session codec, Wake reason mapping, Agent ID preservation, HTTP client design, Testing approach

## Assumptions Presented

### Package Structure
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| `adapters/agent42-paperclip/` at repo root | Likely | ARCHITECTURE.md recommendation; no existing TS infra |
| npm + tsc (no bundler) | Likely | Library package, not webapp; standard for npm packages |
| Flat src/ layout (adapter.ts, client.ts, session.ts, types.ts) | Likely | Matches ARCHITECTURE.md recommended structure |

### Callback Handling
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| Thin passthrough — adapter returns 202, Paperclip handles callback | Confident | Agent42 POSTs to PAPERCLIP_API_URL callback endpoint; adapter doesn't own callback server |
| No polling or callback server in adapter | Confident | ServerAdapterModule contract delegates async delivery to framework |

### Session Codec
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| JSON-based, base64-encoded {agentId, lastRunId, executionCount} | Likely | session_key is plain string in AdapterConfig; JSON is simplest codec |
| No encryption (internal network) | Likely | Same-host or trusted VPC communication |
| Forward-compatible via spread operator for unknown fields | Likely | Standard practice for versioned codecs |

### Wake Reason Mapping
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| Direct passthrough to sidecar | Confident | Sidecar logs wake_reason; orchestrator treats all values identically currently |
| Validate known values, warn on unknown | Confident | Defensive logging without breaking execution |

### Agent ID Preservation
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| Direct mapping — adapterConfig.agentId → agent_id | Confident | AdapterConfig.agent_id already exists in sidecar_models.py |
| Populate both top-level agentId and adapterConfig.agentId | Confident | ADAPT-04 requires continuity for memory and effectiveness |

### Testing Approach
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| Vitest for unit tests with mocked HTTP | Likely | Modern TS standard; no existing test framework to match |
| Optional integration tests against live sidecar | Likely | Contract verification requires running Python process |

## Corrections Made

No corrections — all assumptions auto-confirmed (--auto mode).

## Auto-Resolved

- Package Structure: auto-selected `adapters/agent42-paperclip/` with npm + tsc (recommended default)
- Callback Handling: auto-selected thin passthrough (recommended default)
- Session Codec: auto-selected JSON base64 codec (recommended default)
- Wake Reason Mapping: auto-selected direct passthrough with validation (recommended default)
- Agent ID Preservation: auto-selected direct mapping (recommended default)
- Testing Approach: auto-selected Vitest (recommended default)

## External Research

Advisor agents were unavailable (rate limit). All assumptions resolved from codebase analysis and prior phase context.
