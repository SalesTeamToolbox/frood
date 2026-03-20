---
phase: 4
slug: memory-quality
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-18
---

# Phase 4 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (asyncio_mode = "auto") |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `python -m pytest tests/test_memory_tool.py tests/test_consolidation_worker.py -x -q` |
| **Full suite command** | `python -m pytest tests/ -x -q` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/test_memory_tool.py tests/test_consolidation_worker.py -x -q`
- **After every plan wave:** Run `python -m pytest tests/ -x -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 04-01-01 | 01 | 1 | QUAL-01 | unit | `python -m pytest tests/test_consolidation_worker.py::TestDedupLogic -x` | ❌ W0 | ⬜ pending |
| 04-01-02 | 01 | 1 | QUAL-01 | unit | `python -m pytest tests/test_consolidation_worker.py::TestConsolidationTrigger -x` | ❌ W0 | ⬜ pending |
| 04-01-03 | 01 | 1 | QUAL-01 | unit | `python -m pytest tests/test_memory_tool.py::TestMemoryToolConsolidate -x` | ❌ W0 | ⬜ pending |
| 04-02-01 | 02 | 1 | QUAL-01 | unit | `python -m pytest tests/test_memory_tool.py::TestConsolidationDashboard -x` | ❌ W0 | ⬜ pending |
| 04-02-02 | 02 | 1 | QUAL-02 | unit | `python -m pytest tests/test_memory_tool.py::TestMemoryToolSearch -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_consolidation_worker.py` — stubs for QUAL-01 dedup logic, status file writes, trigger threshold
- [ ] Extend `tests/test_memory_tool.py` with `TestMemoryToolConsolidate` class — covers QUAL-01 `consolidate` action
- [ ] Extend `tests/test_memory_tool.py` with lifecycle assertions in existing `TestMemoryToolSearch` — covers QUAL-02 score fields

*Existing infrastructure covers framework and conftest — no new framework install needed.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Dashboard consolidation stats widget displays correctly | QUAL-01 | Visual UI verification | Start dashboard, navigate to Storage section, verify consolidation stats appear |
| Dashboard manual trigger button works | QUAL-01 | Requires running Qdrant + dashboard | Click "Consolidate Now" button, verify status updates |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
