---
phase: 26-tiered-routing-bridge
plan: "01"
subsystem: tiered-routing-bridge
tags: [routing, bridge, tdd, rewards, providers]
dependency_graph:
  requires:
    - core/agent_manager.py (resolve_model, _TIER_CATEGORY_UPGRADE, PROVIDER_MODELS)
    - core/reward_system.py (RewardSystem, TierDeterminator)
  provides:
    - core/tiered_routing_bridge.py (TieredRoutingBridge, RoutingDecision)
  affects:
    - core/sidecar_orchestrator.py (Phase 26-02 will inject bridge here)
    - dashboard/sidecar.py (Phase 26-02 will construct bridge in create_sidecar_app)
tech_stack:
  added: []
  patterns:
    - MemoryBridge composition pattern applied to routing
    - frozen dataclass for immutable RoutingDecision
    - TDD red-green workflow
key_files:
  created:
    - core/tiered_routing_bridge.py
    - tests/test_tiered_routing_bridge.py
  modified: []
decisions:
  - obs_count=0 passed to TierDeterminator as safe default (Pitfall 1 from RESEARCH.md)
  - reward_system=None returns tier="" with no crash (required by ROUTE-02 graceful degradation)
  - base_category field separate from task_category for tier-upgrade log observability
  - analyst->strategy mapping uses resolve_model general-fallback on synthetic (D-07 behavior)
metrics:
  duration: "~15 minutes"
  completed: "2026-03-30"
  tasks_completed: 1
  tasks_total: 1
  files_changed: 2
---

# Phase 26 Plan 01: TieredRoutingBridge Class and Tests Summary

**One-liner:** TieredRoutingBridge composing RewardSystem + TierDeterminator + resolve_model() into a single resolve() call with static pricing table, RoutingDecision frozen dataclass, and 20 tests covering ROUTE-01 through ROUTE-04.

## What Was Built

Created `core/tiered_routing_bridge.py` — a bridge class following the MemoryBridge architectural pattern — and `tests/test_tiered_routing_bridge.py` with 20 tests covering all four ROUTE-xx requirements.

### TieredRoutingBridge class

- `resolve(role, agent_id, preferred_provider="")` — async method that maps a Paperclip role to a provider+model via reward tier lookup
- `estimate_cost(model, input_tokens, output_tokens)` — static pricing table lookup returning cost in USD
- Role mapping: engineer->coding, researcher->research, writer->content, analyst->strategy; unknown/empty/None->general
- Provider chain: preferred_provider override > synthetic (SYNTHETIC_API_KEY) > anthropic fallback
- Tier upgrade: delegates entirely to existing `resolve_model(provider, category, tier)` — gold->reasoning, silver->general, bronze->fast, provisional->no change
- `obs_count=0` passed to TierDeterminator as safe default so new sidecar agents always start provisional
- `reward_system=None` handled gracefully: tier="" returned, no crash

### RoutingDecision frozen dataclass

Six fields: `provider`, `model`, `tier`, `task_category`, `base_category`, `cost_estimate`.

`base_category` and `task_category` are both present to make tier-upgrade effects observable in logs — when a gold-tier agent upgrades from "coding" to "reasoning", both fields are populated.

### Pricing table

Static `_MODEL_PRICING` dict covering all 14 models in `PROVIDER_MODELS` (anthropic, synthetic, openrouter) plus `_PRICING_FALLBACK = (5.0/M, 15.0/M)` for unknown models.

### Test suite

20 tests across 4 classes:
- `TestRoleMapping` (7 tests): all 4 mapped roles + unknown/empty/None fallback (ROUTE-01)
- `TestTierUpgrade` (5 tests): gold upgrade, bronze upgrade, provisional no-upgrade, rewards-disabled, reward_system=None graceful (ROUTE-02)
- `TestProviderSelection` (4 tests): preferred override, synthetic default, anthropic fallback, unmapped category (ROUTE-03)
- `TestCostEstimation` (4 tests): known model, unknown model fallback, zero tokens, RoutingDecision field set (ROUTE-04)

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

- `cost_estimate=0.0` in all `RoutingDecision` objects returned by `resolve()`. This is intentional per D-09: the pricing table exists and `estimate_cost()` works correctly, but the `resolve()` method itself doesn't populate `cost_estimate` because real token counts come from AgentRuntime (not available until Phase 27+). Phase 27 will wire the actual token counts and call `estimate_cost()` to populate this field in the callback payload.

## Pre-existing Test Failure (Out of Scope)

`tests/test_app_git.py::TestAppManagerGit::test_persistence_with_git_fields` fails with a `ValueError` from `Path.relative_to()` when app directories are in a temp directory outside the project root. This failure exists before and after this plan's changes — verified by running the test against the previous commit. Documented here for awareness; out of scope for this plan.

## Self-Check: PASSED

Files created:
- FOUND: core/tiered_routing_bridge.py
- FOUND: tests/test_tiered_routing_bridge.py

Commits:
- FOUND: e9ca702 (test RED phase)
- FOUND: 782d1bc (feat GREEN phase)

Tests: 20/20 passed
Lint: ruff check passed — no issues
