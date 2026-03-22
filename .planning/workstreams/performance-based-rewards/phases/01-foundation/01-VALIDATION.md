---
phase: 1
slug: foundation
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-22
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x with pytest-asyncio |
| **Config file** | pyproject.toml (asyncio_mode = "auto") |
| **Quick run command** | `python -m pytest tests/test_reward_system.py tests/test_effectiveness.py -x -q` |
| **Full suite command** | `python -m pytest tests/ -x -q` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/test_reward_system.py tests/test_effectiveness.py -x -q`
- **After every plan wave:** Run `python -m pytest tests/ -x -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 01-01-01 | 01 | 1 | CONF-01..05 | unit | `pytest tests/test_reward_system.py -k "config"` | ❌ W0 | ⬜ pending |
| 01-01-02 | 01 | 1 | DATA-01..02 | unit | `pytest tests/test_effectiveness.py -k "agent_id"` | ❌ W0 | ⬜ pending |
| 01-02-01 | 02 | 1 | TIER-01 | unit | `pytest tests/test_reward_system.py -k "score"` | ❌ W0 | ⬜ pending |
| 01-02-02 | 02 | 1 | TIER-04..05 | unit | `pytest tests/test_reward_system.py -k "cache"` | ❌ W0 | ⬜ pending |
| 01-02-03 | 02 | 1 | TEST-01,TEST-05 | integration | `pytest tests/test_reward_system.py -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_reward_system.py` — stubs for CONF-01..05, TIER-01, TIER-04..05, TEST-01, TEST-05
- [ ] Updated `tests/test_effectiveness.py` — stubs for DATA-01..02 (agent_id schema, get_agent_stats)

*Existing infrastructure (conftest.py, pytest config) covers framework needs.*

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
