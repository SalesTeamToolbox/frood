---
phase: 02
slug: intelligent-learning
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-18
---

# Phase 02 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x + pytest-asyncio |
| **Config file** | `pyproject.toml` (`asyncio_mode = "auto"`) |
| **Quick run command** | `python -m pytest tests/test_knowledge_learn.py -x -q` |
| **Full suite command** | `python -m pytest tests/ -x -q` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/test_knowledge_learn.py -x -q`
- **After every plan wave:** Run `python -m pytest tests/ -x -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 02-01-01 | 01 | 1 | LEARN-01 | unit | `pytest tests/test_knowledge_learn.py::TestExtraction::test_decision_extracted -x` | ❌ W0 | ⬜ pending |
| 02-01-02 | 01 | 1 | LEARN-02 | unit | `pytest tests/test_knowledge_learn.py::TestExtraction::test_feedback_extracted -x` | ❌ W0 | ⬜ pending |
| 02-01-03 | 01 | 1 | LEARN-03 | unit | `pytest tests/test_knowledge_learn.py::TestExtraction::test_deploy_pattern_extracted -x` | ❌ W0 | ⬜ pending |
| 02-01-04 | 01 | 1 | LEARN-04 | unit | `pytest tests/test_knowledge_learn.py::TestDedup::test_similar_entry_boosted -x` | ❌ W0 | ⬜ pending |
| 02-01-05 | 01 | 1 | LEARN-04 | unit | `pytest tests/test_knowledge_learn.py::TestDedup::test_new_entry_stored -x` | ❌ W0 | ⬜ pending |
| 02-01-06 | 01 | 1 | LEARN-05 | unit | `pytest tests/test_knowledge_learn.py::TestCategories::test_category_tagging -x` | ❌ W0 | ⬜ pending |
| 02-01-07 | 01 | 1 | All | unit | `pytest tests/test_knowledge_learn.py::TestFailureSilence::test_api_unreachable_no_crash -x` | ❌ W0 | ⬜ pending |
| 02-01-08 | 01 | 1 | All | unit | `pytest tests/test_knowledge_learn.py::TestNoiseFilter -x` | ❌ W0 | ⬜ pending |
| 02-01-09 | 01 | 1 | All | integration | `pytest tests/test_knowledge_learn.py::TestHookRegistration -x` | ❌ W0 | ⬜ pending |
| 02-01-10 | 01 | 1 | All | unit | `pytest tests/test_knowledge_learn.py::TestQdrantDimension -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_knowledge_learn.py` — stubs for LEARN-01 through LEARN-05 coverage (new file)
- [ ] No framework install needed — pytest-asyncio already configured

*Existing infrastructure covers framework requirements.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| End-to-end session extraction | All | Requires live CC session end event | 1. Run a CC session with file modifications 2. End session 3. Check Qdrant for new knowledge entries |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
