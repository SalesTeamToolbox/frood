---
phase: 1
slug: auto-sync-hook
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-18
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x with pytest-asyncio |
| **Config file** | `pyproject.toml` — `asyncio_mode = "auto"` |
| **Quick run command** | `python -m pytest tests/test_cc_memory_sync.py -x -q` |
| **Full suite command** | `python -m pytest tests/ -x -q` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/test_cc_memory_sync.py -x -q`
- **After every plan wave:** Run `python -m pytest tests/ -x -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 10 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 01-01-01 | 01 | 0 | SYNC-01..04 | unit | `pytest tests/test_cc_memory_sync.py -x -q` | ❌ W0 | ⬜ pending |
| 01-01-02 | 01 | 1 | SYNC-01 | integration | `pytest tests/test_cc_memory_sync.py::TestSyncHook::test_write_triggers_qdrant_upsert -x` | ❌ W0 | ⬜ pending |
| 01-01-03 | 01 | 1 | SYNC-02 | unit | `pytest tests/test_cc_memory_sync.py::TestPathDetection::test_all_memory_file_types -x` | ❌ W0 | ⬜ pending |
| 01-01-04 | 01 | 1 | SYNC-03 | unit | `pytest tests/test_cc_memory_sync.py::TestDedup::test_upsert_same_path_no_duplicate -x` | ❌ W0 | ⬜ pending |
| 01-01-05 | 01 | 1 | SYNC-04 | unit | `pytest tests/test_cc_memory_sync.py::TestFailureSilence::test_qdrant_unreachable_no_error -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_cc_memory_sync.py` — stubs for SYNC-01, SYNC-02, SYNC-03, SYNC-04
  - `TestPathDetection` — tests `is_cc_memory_file()` path matching including Windows paths
  - `TestSyncWorker` — tests worker's embed+upsert logic with mocked ONNX + mocked Qdrant
  - `TestDedup` — tests that upsert with same file_path point ID is idempotent
  - `TestFailureSilence` — tests worker exits cleanly when Qdrant unavailable
  - `TestReindexCc` — tests `MemoryTool.reindex_cc` action scans and syncs missing files

*(No framework install needed — pytest and pytest-asyncio already installed.)*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| CC Write tool latency unaffected | SYNC-04 | Requires real CC session timing | Time a Write tool call before/after hook install; confirm <100ms delta |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
