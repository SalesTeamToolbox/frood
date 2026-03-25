---
phase: 3
slug: memory-sync
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-24
---

# Phase 3 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x + pytest-asyncio |
| **Config file** | pyproject.toml (asyncio_mode = "auto") |
| **Quick run command** | `python -m pytest tests/test_memory_sync.py tests/test_memory_tool.py tests/test_project_memory.py -x -q` |
| **Full suite command** | `python -m pytest tests/ -x -q` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/test_memory_sync.py tests/test_memory_tool.py tests/test_project_memory.py -x -q`
- **After every plan wave:** Run `python -m pytest tests/ -x -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| TBD | TBD | TBD | MEM-01 | unit | `pytest tests/test_memory_sync.py -k uuid_timestamp -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | MEM-02 | unit | `pytest tests/test_memory_sync.py -k entry_union_merge -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | MEM-03 | unit | `pytest tests/test_project_memory.py -k project_namespace -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_memory_sync.py` — stubs for MEM-01 (UUID+timestamp injection), MEM-02 (entry-union merge, conflict resolution)
- [ ] `tests/test_project_memory.py` — extend with MEM-03 stubs (namespace routing via factory)
- [ ] `tests/test_memory_tool.py` — extend with project routing tests

*Existing test infrastructure covers framework and fixtures (conftest.py exists).*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Cross-node merge via SSH | MEM-02 | Requires two physical nodes with SSH access | Run `node_sync merge` between laptop and VPS after independent edits on both |
| Legacy migration on production | MEM-01 | Requires actual legacy MEMORY.md on VPS | SSH to VPS, verify auto-migration produces valid UUIDs on first MemoryStore access |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
