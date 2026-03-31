---
phase: 30
slug: advanced-teamtool-auto-memory
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-31
---

# Phase 30 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Python Framework** | pytest (existing) |
| **TypeScript Framework** | vitest (existing) |
| **Python config** | `tests/conftest.py` + `tests/test_sidecar.py` |
| **TypeScript config** | `plugins/agent42-paperclip/vitest.config.ts` |
| **Quick run (Python)** | `python -m pytest tests/test_sidecar.py -x -q` |
| **Quick run (TypeScript)** | `cd plugins/agent42-paperclip && npx vitest run` |
| **Full suite** | `python -m pytest tests/ -x -q && cd plugins/agent42-paperclip && npx vitest run` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** `python -m pytest tests/test_sidecar.py -x -q && cd plugins/agent42-paperclip && npx vitest run`
- **After every plan wave:** `python -m pytest tests/ -x -q && cd plugins/agent42-paperclip && npx vitest run`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 30-01-01 | 01 | 1 | ADV-01 | unit | `pytest tests/test_sidecar.py::TestAutoMemoryInjection -x -q` | ❌ W0 | ⬜ pending |
| 30-01-02 | 01 | 1 | ADV-01 | unit | `pytest tests/test_sidecar.py::TestAutoMemoryInjection::test_auto_memory_in_callback -x -q` | ❌ W0 | ⬜ pending |
| 30-01-03 | 01 | 1 | ADV-01 | unit | `pytest tests/test_sidecar.py::TestAutoMemoryInjection::test_auto_memory_disabled -x -q` | ❌ W0 | ⬜ pending |
| 30-02-01 | 02 | 1 | ADV-02 | unit | `cd plugins/agent42-paperclip && npx vitest run tests/team.test.ts` | ❌ W0 | ⬜ pending |
| 30-02-02 | 02 | 1 | ADV-02 | unit | `cd plugins/agent42-paperclip && npx vitest run tests/team.test.ts` | ❌ W0 | ⬜ pending |
| 30-02-03 | 02 | 1 | ADV-03 | unit | `cd plugins/agent42-paperclip && npx vitest run tests/team.test.ts` | ❌ W0 | ⬜ pending |
| 30-02-04 | 02 | 1 | ADV-03 | unit | `cd plugins/agent42-paperclip && npx vitest run tests/team.test.ts` | ❌ W0 | ⬜ pending |
| 30-02-05 | 02 | 1 | ADV-01/02/03 | unit | `cd plugins/agent42-paperclip && npx vitest run tests/worker.test.ts` | Partial | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_sidecar.py::TestAutoMemoryInjection` class — stubs for ADV-01 (auto_memory injection, disabled flag, callback metadata)
- [ ] `plugins/agent42-paperclip/tests/team.test.ts` — stubs for ADV-02 (fan-out) and ADV-03 (wave)
- [ ] Extend `plugins/agent42-paperclip/tests/worker.test.ts` — verify manifest capabilities include new entries

*Existing test infrastructure covers framework install — no new framework needed.*

---

## Manual-Only Verifications

*All phase behaviors have automated verification.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
