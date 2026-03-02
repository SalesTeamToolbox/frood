---
phase: 1
slug: foundation-cerebras
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-01
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x (pytest-asyncio auto mode) |
| **Config file** | pyproject.toml |
| **Quick run command** | `python -m pytest tests/test_registry.py tests/test_spending.py -x -q` |
| **Full suite command** | `python -m pytest tests/ -x -q` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/test_registry.py tests/test_spending.py -x -q`
- **After every plan wave:** Run `python -m pytest tests/ -x -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| TBD | 01 | 1 | INFR-01 | unit | `python -m pytest tests/test_registry.py -k "provider_type" -x -q` | ✅ | ⬜ pending |
| TBD | 01 | 1 | CERE-01 | unit | `python -m pytest tests/test_registry.py -k "cerebras" -x -q` | ❌ W0 | ⬜ pending |
| TBD | 01 | 1 | CERE-02 | unit | `python -m pytest tests/test_registry.py -k "cerebras" -x -q` | ❌ W0 | ⬜ pending |
| TBD | 01 | 1 | CERE-03 | unit | `python -m pytest tests/test_registry.py -k "cerebras and free" -x -q` | ❌ W0 | ⬜ pending |
| TBD | 01 | 1 | INFR-02 | unit | `python -m pytest tests/test_spending.py -k "free_model" -x -q` | ✅ | ⬜ pending |
| TBD | 01 | 1 | CERE-04 | unit | `python -m pytest tests/test_spending.py -k "cerebras" -x -q` | ❌ W0 | ⬜ pending |
| TBD | 01 | 1 | INFR-05 | unit | `python -m pytest tests/test_registry.py -k "missing_key" -x -q` | ❌ W0 | ⬜ pending |
| TBD | 01 | 1 | TEST-01 | unit | `python -m pytest tests/test_registry.py -k "cerebras" -x -q` | ❌ W0 | ⬜ pending |
| TBD | 01 | 1 | TEST-02 | unit | `python -m pytest tests/test_spending.py -k "cerebras" -x -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_registry.py` — add Cerebras ProviderSpec/ModelSpec test stubs
- [ ] `tests/test_spending.py` — add Cerebras $0 pricing test stubs

*Existing test infrastructure (pytest, conftest.py) covers all framework needs.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Agent42 starts without error when CEREBRAS_API_KEY is set | INFR-05 | Requires running the full application | Start `python agent42.py` with CEREBRAS_API_KEY set, verify no crash |
| Agent42 starts without error when CEREBRAS_API_KEY is absent | INFR-05 | Requires running the full application | Start `python agent42.py` without CEREBRAS_API_KEY, verify no crash |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
