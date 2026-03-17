---
phase: 20
slug: task-metadata-foundation
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-17
---

# Phase 20 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x with pytest-asyncio |
| **Config file** | `pyproject.toml` — `asyncio_mode = "auto"`, testpaths = ["tests"] |
| **Quick run command** | `python -m pytest tests/test_task_context.py tests/test_memory.py -x -q` |
| **Full suite command** | `python -m pytest tests/ -x -q` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/test_task_context.py tests/test_memory.py -x -q`
- **After every plan wave:** Run `python -m pytest tests/ -x -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 20-01-01 | 01 | 1 | TMETA-01 | unit | `pytest tests/test_task_context.py::TestPayloadInjection -x` | ❌ W0 | ⬜ pending |
| 20-01-02 | 01 | 1 | TMETA-02 | unit | `pytest tests/test_task_context.py::TestBackwardCompat -x` | ❌ W0 | ⬜ pending |
| 20-01-03 | 01 | 1 | TMETA-03 | unit | `pytest tests/test_task_context.py::TestPayloadIndexes -x` | ❌ W0 | ⬜ pending |
| 20-01-04 | 01 | 1 | TMETA-04 | unit | `pytest tests/test_task_context.py::TestLifecycle -x` | ❌ W0 | ⬜ pending |
| 20-01-05 | 01 | 1 | RETR-01 | unit | `pytest tests/test_task_context.py::TestFilteredSearch -x` | ❌ W0 | ⬜ pending |
| 20-01-06 | 01 | 1 | RETR-02 | unit | `pytest tests/test_task_context.py::TestBuildContextSemantic -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_task_context.py` — stubs for TMETA-01 through RETR-02
- [ ] No framework install needed — pytest + pytest-asyncio already installed

*Existing infrastructure covers framework requirements.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Filtered query on 100K points runs in <50ms | TMETA-03 | Requires populated Qdrant instance | Load 100K test vectors, run filtered search, measure latency |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
