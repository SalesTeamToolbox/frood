---
phase: 29-plugin-ui-learning-extraction
plan: "01"
subsystem: sidecar-api
tags: [sidecar, memory, effectiveness, learning-extraction, run-id]
dependency_graph:
  requires: [28-paperclip-plugin]
  provides: [plugin-ui-data-endpoints, run-id-tracing, transcript-capture]
  affects: [dashboard/sidecar.py, core/memory_bridge.py, memory/effectiveness.py]
tech_stack:
  added: []
  patterns: [pydantic-v2-camelcase-models, sqlite-append-tables, fastapi-get-routes]
key_files:
  created: []
  modified:
    - core/sidecar_models.py
    - memory/effectiveness.py
    - memory/qdrant_store.py
    - core/memory_bridge.py
    - core/sidecar_orchestrator.py
    - dashboard/sidecar.py
    - tests/test_sidecar.py
    - tests/test_memory_bridge.py
decisions:
  - "TierDeterminator.determine(score, obs_count) used for agent tier — success_rate as score, task_volume as obs_count"
  - "get_aggregated_stats() extended with agent_id filter (not breaking — default empty string preserves backward compat)"
  - "drain_pending_transcripts strips internal id before returning to prevent leaking SQLite internals"
  - "run_id tagged in recall results only when non-empty — avoids polluting existing consumers with empty key"
metrics:
  duration: "~25 min"
  completed: "2026-03-31"
  tasks: 2
  files: 8
---

# Phase 29 Plan 01: Sidecar Data API, run_id Threading, and Learning Extraction Summary

Python sidecar backend: 6 new HTTP endpoints, 3 new SQLite tables, run_id keyword indexes, transcript capture, and drain-based learning extraction.

## What Was Built

**Task 1: Pydantic models, SQLite tables, run_id index, MemoryBridge threading**

Added 7 new Pydantic v2 models to `core/sidecar_models.py` with camelCase aliases per existing pattern: `AgentProfileResponse`, `TaskTypeStats`, `AgentEffectivenessResponse`, `RoutingHistoryEntry`, `RoutingHistoryResponse`, `MemoryTraceItem`, `MemoryRunTraceResponse`, `SpendEntry`, `AgentSpendResponse`, `ExtractLearningsRequest`, `ExtractLearningsResponse`.

Extended `memory/effectiveness.py` `_ensure_db()` with 3 new SQLite tables: `routing_decisions` (run_id, agent, provider, tier, timestamp), `spend_history` (agent, provider, tokens, cost, hour bucket), and `run_transcripts` (run_id unique, agent, summary, extracted flag). Added proper indexes and 6 new async methods: `log_routing_decision`, `get_routing_history`, `log_spend`, `get_agent_spend`, `save_transcript`, `drain_pending_transcripts`. Extended `get_aggregated_stats()` with optional `agent_id` filter.

Added `run_id` keyword index to both `_ensure_task_indexes` and `_ensure_knowledge_indexes` in `memory/qdrant_store.py`.

Threaded `run_id: str = ""` through `core/memory_bridge.py` — added as optional parameter to both `recall()` (tags result dicts when non-empty) and `learn_async()` (stored in Qdrant KNOWLEDGE payload for run-trace queries).

Updated `core/sidecar_orchestrator.py` `execute_async()` to: pass `run_id=run_id` to `memory_bridge.recall()`, log routing decisions via `effectiveness_store.log_routing_decision()` after Step 1.5, log spend via `effectiveness_store.log_spend()` after Step 2, capture transcripts via `effectiveness_store.save_transcript()` in the finally block, pass `run_id=run_id` to `memory_bridge.learn_async()`.

**Task 2: Sidecar HTTP routes + tests**

Added 6 new routes to `dashboard/sidecar.py` (all Bearer auth required):
- `GET /agent/{agent_id}/profile` — returns tier (via TierDeterminator), success_rate, task_volume, avg_speed_ms
- `GET /agent/{agent_id}/effectiveness` — per-task-type success rate breakdown from get_aggregated_stats
- `GET /agent/{agent_id}/routing-history` — recent routing decisions from SQLite
- `GET /memory/run-trace/{run_id}` — Qdrant scroll over MEMORY+HISTORY+KNOWLEDGE filtered by run_id
- `GET /agent/{agent_id}/spend` — token spend grouped by provider over last 24h
- `POST /memory/extract` — drains pending run_transcripts and fires learn_async per transcript

Extended `GET /sidecar/health` with `configured_providers` dict showing which API keys are set.

Added 8 new test classes to `tests/test_sidecar.py` covering profile, effectiveness, routing-history, run-trace, spend, extract, auth gates, and health-still-public. Added `TestMemoryBridgeRunId` class to `tests/test_memory_bridge.py` with 4 tests covering run_id pass-through in recall, default behavior, payload storage in learn_async, and the learn->recall feedback loop (LEARN-02).

## Verification

All acceptance criteria met:
- 6 new endpoint functions in `dashboard/sidecar.py`
- All 78 sidecar + memory bridge tests pass
- Full models import cleanly
- 3 SQLite tables with indexes in `memory/effectiveness.py`
- run_id threaded through MemoryBridge and Qdrant indexes

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None — all endpoints return real data from SQLite/Qdrant. The routing-history, spend, and run-trace endpoints will return empty results until actual agent executions populate the tables (which is correct behavior for a new deployment).

## Self-Check: PASSED

Files verified to exist:
- `core/sidecar_models.py` — contains AgentProfileResponse (confirmed)
- `memory/effectiveness.py` — contains routing_decisions, spend_history, run_transcripts tables (confirmed)
- `memory/qdrant_store.py` — run_id in _ensure_task_indexes (confirmed)
- `core/memory_bridge.py` — run_id in recall() and learn_async() signatures (confirmed)
- `core/sidecar_orchestrator.py` — log_routing_decision, log_spend, save_transcript, run_id=run_id in learn_async (confirmed)
- `dashboard/sidecar.py` — 6 new route functions (confirmed, grep count=6)
- `tests/test_sidecar.py` — Phase 29 test classes present (confirmed)
- `tests/test_memory_bridge.py` — TestMemoryBridgeRunId present (confirmed)

Commits verified:
- `387ee0c` — feat(29-01): Pydantic models, SQLite tables, run_id index, MemoryBridge threading
- `4466c80` — feat(29-01): sidecar HTTP routes, health extension, and test suites
