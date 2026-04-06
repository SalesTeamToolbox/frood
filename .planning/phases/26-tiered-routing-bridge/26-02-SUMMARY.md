---
phase: 26-tiered-routing-bridge
plan: "02"
subsystem: tiered-routing-bridge
tags: [routing, bridge, tdd, orchestrator, sidecar]
dependency_graph:
  requires:
    - core/tiered_routing_bridge.py (TieredRoutingBridge, RoutingDecision — Plan 01)
    - core/sidecar_orchestrator.py (SidecarOrchestrator — Phase 24)
    - dashboard/sidecar.py (create_sidecar_app — Phase 24)
    - core/reward_system.py (TierDeterminator)
  provides:
    - core/sidecar_orchestrator.py (routing step between memory recall and execution stub)
    - dashboard/sidecar.py (TieredRoutingBridge construction and injection)
    - tests/test_tiered_routing_bridge.py (TestOrchestratorIntegration — 5 integration tests)
  affects:
    - core/sidecar_orchestrator.py (tiered_routing_bridge parameter + routing step + usage dict)
    - dashboard/sidecar.py (TieredRoutingBridge constructed in create_sidecar_app)
tech_stack:
  added: []
  patterns:
    - MemoryBridge composition pattern extended to TieredRoutingBridge
    - TDD red-green workflow (RED commit then GREEN commit)
    - Graceful degradation: routing failure falls back to empty model/provider
key_files:
  created: []
  modified:
    - core/sidecar_orchestrator.py
    - dashboard/sidecar.py
    - tests/test_tiered_routing_bridge.py
decisions:
  - agentRole key in ctx.context uses Paperclip camelCase convention (TODO phase-27 to verify against real payload)
  - routing step placed between Step 1 (memory recall) and Step 2 (execution stub) per plan spec
  - routing exception caught and logged as warning, not fatal — run always completes with callback
  - TieredRoutingBridge constructed once in create_sidecar_app, shared across all requests (D-11, D-14)
metrics:
  duration: "~12 minutes"
  completed: "2026-03-30"
  tasks_completed: 1
  tasks_total: 1
  files_changed: 3
---

# Phase 26 Plan 02: SidecarOrchestrator Wiring Summary

**One-liner:** TieredRoutingBridge wired into SidecarOrchestrator.execute_async() between memory recall and execution stub, with usage dict populated from RoutingDecision and 5 integration tests covering graceful degradation, logging, and stub token values.

## What Was Built

Modified `core/sidecar_orchestrator.py` and `dashboard/sidecar.py` to connect the TieredRoutingBridge (created in Plan 01) to the execution pipeline, and appended `TestOrchestratorIntegration` to `tests/test_tiered_routing_bridge.py`.

### SidecarOrchestrator changes

- `__init__()` now accepts `tiered_routing_bridge: Any = None` parameter (stored as `self.tiered_routing_bridge`)
- `execute_async()` has a new Step 1.5 between memory recall and the execution stub:
  - Calls `self.tiered_routing_bridge.resolve(role, agent_id, preferred_provider)`
  - Role is extracted from `ctx.context.get("agentRole", "")` (Paperclip camelCase convention)
  - On success: emits structured `logger.info` with run_id, agent_id, role, tier, provider, model, base_cat, cat
  - On exception: emits `logger.warning` and continues with routing=None (graceful degradation)
- Usage dict now populated from routing decision:
  - `"model": routing.model if routing else ""`
  - `"provider": routing.provider if routing else ""`
  - `"inputTokens": 0, "outputTokens": 0, "costUsd": 0.0` (per D-09)

### create_sidecar_app() changes

- Added imports: `from core.tiered_routing_bridge import TieredRoutingBridge` and `from core.reward_system import TierDeterminator`
- Constructs `TieredRoutingBridge(reward_system=reward_system, tier_determinator=TierDeterminator())` after `MemoryBridge` construction
- Passes `tiered_routing_bridge=tiered_routing_bridge` to `SidecarOrchestrator`

### Integration test suite (5 tests in TestOrchestratorIntegration)

- `test_execute_async_populates_usage_with_routing` — usage dict contains model and provider from RoutingDecision
- `test_execute_async_routing_failure_degrades_gracefully` — RuntimeError in bridge.resolve() → status="completed", empty model/provider
- `test_execute_async_no_bridge_uses_empty_usage` — tiered_routing_bridge=None → empty model/provider
- `test_execute_async_routing_logged` — caplog verifies structured log line with tier, provider, model, task_category
- `test_usage_dict_stub_values` — inputTokens=0, outputTokens=0, costUsd=0.0 always present

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

- `inputTokens=0, outputTokens=0, costUsd=0.0` in all usage dicts (D-09): intentional stub. Real token counts come from AgentRuntime which will be wired in Phase 27+.
- `agentRole` key in `ctx.context` has a TODO comment to verify against real Paperclip payload in Phase 27.

## Pre-existing Test Failure (Out of Scope)

`tests/test_app_git.py::TestAppManagerGit::test_persistence_with_git_fields` fails with a `ValueError` from `Path.relative_to()` when app directories are in a temp directory outside the project root. This failure was present in Plan 01 and continues to be out of scope for Plan 02.

## Self-Check: PASSED

Files modified:
- FOUND: core/sidecar_orchestrator.py
- FOUND: dashboard/sidecar.py
- FOUND: tests/test_tiered_routing_bridge.py (appended TestOrchestratorIntegration)

Commits:
- FOUND: 755102e (test RED phase — 5 integration tests)
- FOUND: ba250ba (feat GREEN phase — SidecarOrchestrator + create_sidecar_app)

Tests: 25/25 passed (20 unit + 5 integration)
Lint: ruff check passed — no issues
