# Deferred Items — Phase 01 (cross-cli-setup-core)

Discoveries outside the plan's scope boundary (per GSD rule). Logged, not fixed.

## 2026-04-17 (during 01-06 full-suite verification)

### Pre-existing full-suite failures (17 total) — unrelated to this phase

Full suite run during 01-06 verification surfaces failures in four test files
that this phase NEVER touched:

1. `tests/test_memory_hooks.py` — 8 failures in `TestMemoryRecallHook` + `TestMemoryDegradation`
2. `tests/test_sidecar.py` — 5 failures in `TestSidecarExecute` + `TestIdempotencyGuard` + `TestAutoMemoryInjection`
3. `tests/test_sidecar_phase35.py` — 1 failure in `TestSidecarModelsEndpoint::test_get_models_includes_all_providers`
4. `tests/test_tiered_routing_bridge.py` — 3 failures in `TestRoleMapping` + `TestOrchestratorIntegration`

All 17 confirmed to fail with `tests/test_cli_setup.py` REMOVED from the tree
(verified via rename + rerun). None of the touched modules (`core/cli_setup.py`,
`core/user_frood_dir.py`, `tools/skill_bridge.py`, `commands.py`,
`dashboard/server.py`, `frood.py`) appear in the call graph of any of these
failing tests.

**Scope:** Out-of-scope per GSD rule "only auto-fix issues DIRECTLY caused by
the current task's changes." These pre-existed the cross-cli-setup workstream.

**Recommendation:** File dedicated plans on whichever workstreams own the
memory-hooks, sidecar, and tiered-routing subsystems. Do NOT conflate with
cross-cli-setup.
