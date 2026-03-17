---
phase: 21
slug: effectiveness-tracking-and-learning-extraction
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-17
---

# Phase 21 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x with pytest-asyncio |
| **Config file** | `pyproject.toml` (`[tool.pytest.ini_options]`, `asyncio_mode = "auto"`) |
| **Quick run command** | `python -m pytest tests/test_effectiveness.py -x -q` |
| **Full suite command** | `python -m pytest tests/ -x -q` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/test_effectiveness.py -x -q`
- **After every plan wave:** Run `python -m pytest tests/ -x -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 10 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 21-01-01 | 01 | 1 | EFFT-01 | unit | `python -m pytest tests/test_effectiveness.py::TestEffectivenessStore::test_record_writes_correct_schema -x` | ❌ W0 | ⬜ pending |
| 21-01-02 | 01 | 1 | EFFT-02 | unit | `python -m pytest tests/test_effectiveness.py::TestEffectivenessStore::test_record_is_fire_and_forget -x` | ❌ W0 | ⬜ pending |
| 21-01-03 | 01 | 1 | EFFT-03 | unit | `python -m pytest tests/test_effectiveness.py::TestMCPTracking -x` | ❌ W0 | ⬜ pending |
| 21-01-04 | 01 | 1 | EFFT-04 | unit | `python -m pytest tests/test_effectiveness.py::TestEffectivenessStore::test_aggregation_query -x` | ❌ W0 | ⬜ pending |
| 21-01-05 | 01 | 1 | EFFT-05 | unit | `python -m pytest tests/test_effectiveness.py::TestEffectivenessStore::test_graceful_degradation_unwritable -x` | ❌ W0 | ⬜ pending |
| 21-02-01 | 02 | 2 | LEARN-01 | unit | `python -m pytest tests/test_effectiveness.py::TestLearningExtraction::test_extract_learning_fields -x` | ❌ W0 | ⬜ pending |
| 21-02-02 | 02 | 2 | LEARN-02 | unit | `python -m pytest tests/test_effectiveness.py::TestLearningExtraction::test_history_entry_format -x` | ❌ W0 | ⬜ pending |
| 21-02-03 | 02 | 2 | LEARN-03 | unit | `python -m pytest tests/test_effectiveness.py::TestLearningExtraction::test_qdrant_payload_fields -x` | ❌ W0 | ⬜ pending |
| 21-02-04 | 02 | 2 | LEARN-04 | unit | `python -m pytest tests/test_effectiveness.py::TestQuarantine -x` | ❌ W0 | ⬜ pending |
| 21-02-05 | 02 | 2 | LEARN-05 | unit | `python -m pytest tests/test_effectiveness.py::TestLearningExtraction::test_no_mid_task_writes -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_effectiveness.py` — stubs for EFFT-01 through EFFT-05, LEARN-01 through LEARN-05, quarantine mechanics
- [ ] Install new dependencies: `pip install aiosqlite>=0.20.0 instructor>=1.3.0` and add to `requirements.txt`
- [ ] `tests/test_effectiveness.py` needs `tmp_path` fixture for SQLite DB path (no hardcoded paths per CLAUDE.md)
- [ ] Mock `aiosqlite.connect` for EFFT-05 test (simulate unwritable DB without filesystem manipulation)
- [ ] Mock `instructor.from_openai` for LEARN-01 tests (no real API calls in tests)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Fire-and-forget latency under real load | EFFT-02 | Requires real async event loop timing | Run `agent42.py`, invoke a tool, measure that tool response arrives before SQLite write completes |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
