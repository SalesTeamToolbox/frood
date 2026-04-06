---
phase: 29
slug: plugin-ui-learning-extraction
status: draft
nyquist_compliant: true
wave_0_complete: true
created: 2026-03-30
---

# Phase 29 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | vitest 3.x (TypeScript plugin) + pytest 7.x (Python sidecar) |
| **Config file** | `plugins/agent42-paperclip/vitest.config.ts` + `pytest.ini` |
| **Quick run command** | `cd plugins/agent42-paperclip && npx vitest run --reporter=verbose` |
| **Full suite command** | `cd plugins/agent42-paperclip && npx vitest run && cd ../.. && python -m pytest tests/ -x -q` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `cd plugins/agent42-paperclip && npx vitest run --reporter=verbose`
- **After every plan wave:** Run full suite (vitest + pytest)
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | Test File | Status |
|---------|------|------|-------------|-----------|-------------------|-----------|--------|
| 29-01-01 | 01 | 1 | UI-01..04, LEARN-01..02 | unit | `python -c "from core.sidecar_models import AgentProfileResponse; print('OK')"` | core/sidecar_models.py (models), memory/effectiveness.py (tables) | created in task |
| 29-01-02 | 01 | 1 | UI-01..04, LEARN-01..02 | unit+integration | `python -m pytest tests/test_sidecar.py tests/test_memory_bridge.py -x -q` | tests/test_sidecar.py, tests/test_memory_bridge.py | created in task |
| 29-02-01 | 02 | 2 | UI-01..04, LEARN-01..02 | unit | `cd plugins/agent42-paperclip && npx tsc --noEmit && npx vitest run tests/client.test.ts` | plugins/agent42-paperclip/tests/client.test.ts | created in task |
| 29-02-02 | 02 | 2 | UI-01..04, LEARN-01..02 | unit+integration | `cd plugins/agent42-paperclip && npx vitest run` | plugins/agent42-paperclip/tests/worker.test.ts, plugins/agent42-paperclip/tests/data-handlers.test.ts | created in task |
| 29-03-01 | 03 | 3 | UI-01..04 | build | `cd plugins/agent42-paperclip && pnpm run build && ls dist/ui/*.js` | build-ui.mjs (build script, not test file) | created in task |
| 29-03-02 | 03 | 3 | UI-01..04 | checkpoint | manual visual inspection | N/A (checkpoint:human-verify) | pending |

*Status: pending · green · red · flaky*

---

## Wave 0 Requirements

All test files are created within the plan tasks themselves (no separate Wave 0 stubs needed):

- [x] `tests/test_sidecar.py` — extended by Plan 01 Task 2 with new endpoint tests
- [x] `tests/test_memory_bridge.py` — extended by Plan 01 Task 2 with run_id + recall loop tests
- [x] `plugins/agent42-paperclip/tests/client.test.ts` — extended by Plan 02 Task 1 with new client method tests
- [x] `plugins/agent42-paperclip/tests/worker.test.ts` — extended by Plan 02 Task 2 with handler registration tests
- [x] `plugins/agent42-paperclip/tests/data-handlers.test.ts` — created by Plan 02 Task 2 with data handler + job tests
- [x] `esbuild` + `react` + `@types/react` installed as devDependencies in Plan 02 Task 1

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| detailTab renders on Paperclip agent page | UI-01 | Requires running Paperclip host | Open agent detail page, verify "Effectiveness" tab appears |
| dashboardWidget renders on Paperclip dashboard | UI-02 | Requires running Paperclip host | Open dashboard, verify "Provider Health" widget appears |
| Memory browser shows injected/extracted data | UI-03 | Requires run with memory pipeline | Execute an agent run, open run detail, verify Memory tab |
| Learning extraction feedback loop | LEARN-02 | End-to-end across sidecar + Qdrant | Run agent, wait 1h, recall memories for same agent type |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 15s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** ready
