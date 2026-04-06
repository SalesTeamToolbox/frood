# Phase 29: Plugin UI + Learning Extraction - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-03-30
**Phase:** 29-plugin-ui-learning-extraction
**Areas discussed:** UI slot architecture, Data API surface, Learning job design, Memory browser UX

---

## UI Slot Architecture

| Option | Description | Selected |
|--------|-------------|----------|
| Per-slot files | src/ui/index.tsx re-exports from AgentEffectivenessTab.tsx, ProviderHealthWidget.tsx, MemoryBrowserTab.tsx, RoutingDecisionsWidget.tsx | ✓ |
| Single index.tsx | All 4 components in one src/ui/index.tsx file | |
| You decide | Claude picks during implementation | |

**User's choice:** Per-slot files with re-exporting index
**Notes:** SDK mandates entrypoints.ui as directory path, esbuild for browser bundle. Two-step build required (tsc for worker, esbuild for UI).

---

## Data API Surface

| Option | Description | Selected |
|--------|-------------|----------|
| New endpoints (full suite) | 5 new GET endpoints + extend /sidecar/health. Requires new routing_decisions log and spend_history table in SQLite. | ✓ |
| Minimal new + defer history | Add endpoints for existing data only; defer routing history and spend history | |
| You decide | Claude determines optimal API surface | |

**User's choice:** Full new endpoint suite
**Notes:** Endpoints: GET /agent/{agentId}/profile, GET /agent/{agentId}/effectiveness, GET /agent/{agentId}/routing-history, extend GET /sidecar/health, GET /memory/run-trace/{runId}, GET /agent/{agentId}/spend?hours=24.

---

## Learning Job Design

| Option | Description | Selected |
|--------|-------------|----------|
| SDK ctx.jobs | Manifest jobs[] with cron schedule. Paperclip manages scheduling, retry, status visibility. Plugin POSTs to sidecar /memory/extract. | ✓ |
| Sidecar Python cron | asyncio timer in sidecar. Direct learn_async(), invisible to Paperclip. | |
| setInterval in worker | Node.js timer. Same as SDK jobs but no Paperclip visibility. | |
| You decide | Claude picks during planning | |

**User's choice:** SDK ctx.jobs scheduler
**Notes:** Critical finding: plugin worker has NO SDK access to run transcripts (heartbeatRunEvents is host-internal). Sidecar captures transcripts during execute_async(), plugin job triggers batch extraction via POST /memory/extract.

---

## Memory Browser UX

| Option | Description | Selected |
|--------|-------------|----------|
| Qdrant run_id field | Thread run_id through recall()/learn_async() into Qdrant payloads. Add keyword index. New GET /memory/run-trace/{runId}. | ✓ |
| In-memory + Qdrant hybrid | Cache in-process for immediate display, persist to Qdrant for durability | |
| You decide | Claude picks during planning | |

**User's choice:** Qdrant run_id field (follows existing task_id pattern)
**Notes:** run_id already flows via AdapterExecutionContext — gap is only passing it down to MemoryBridge/Qdrant. Display: "Injected Memories" (before run) and "Extracted Learnings" (after run) sections.

---

## Claude's Discretion

- Exact manifest metadata, cron expression, Pydantic model shapes
- SQLite schema for routing_decisions and spend_history tables
- esbuild script location and configuration
- Memory browser loading/refresh UX for async learning extraction delay
- Error response formatting, Vitest organization

## Deferred Ideas

None — discussion stayed within phase scope
