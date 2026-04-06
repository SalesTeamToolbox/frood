---
phase: 25
slug: memory-bridge
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-29
---

# Phase 25 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.0.2 |
| **Config file** | pytest.ini / pyproject.toml |
| **Quick run command** | `python -m pytest tests/test_memory_bridge.py -x -q` |
| **Full suite command** | `python -m pytest tests/ -x -q` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/test_memory_bridge.py -x -q`
- **After every plan wave:** Run `python -m pytest tests/test_sidecar.py tests/test_memory_bridge.py -x -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 10 seconds

---

## Per-Requirement Verification Map

| Requirement | Behavior | Test Type | Automated Command | File Exists | Status |
|-------------|----------|-----------|-------------------|-------------|--------|
| MEM-01 | recall() returns top-K memories for agent+task | unit | `python -m pytest tests/test_memory_bridge.py::TestMemoryBridgeRecall -x -q` | ❌ W0 | ⬜ pending |
| MEM-02 | recall() returns empty list when timeout exceeded | unit | `python -m pytest tests/test_memory_bridge.py::TestMemoryBridgeTimeout -x -q` | ❌ W0 | ⬜ pending |
| MEM-03 | learn_async() runs fire-and-forget, does not delay callback | unit | `python -m pytest tests/test_memory_bridge.py::TestMemoryBridgeLearn -x -q` | ❌ W0 | ⬜ pending |
| MEM-04 | POST /memory/recall and POST /memory/store respond correctly | integration | `python -m pytest tests/test_memory_bridge.py::TestMemoryRoutes -x -q` | ❌ W0 | ⬜ pending |
| MEM-05 | Two agents with different agent_ids do not share memories | unit | `python -m pytest tests/test_memory_bridge.py::TestMemoryScopeIsolation -x -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_memory_bridge.py` — stubs for MEM-01 through MEM-05 (new file)
- [ ] `core/memory_bridge.py` — MemoryBridge class (implementation target)
