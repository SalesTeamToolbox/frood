---
phase: 23
slug: recommendations-engine
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-22
---

# Phase 23 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x + pytest-asyncio |
| **Config file** | pyproject.toml (asyncio_mode = "auto") |
| **Quick run command** | `python -m pytest tests/test_effectiveness.py tests/test_proactive_injection.py -x -q` |
| **Full suite command** | `python -m pytest tests/ -x -q` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/test_effectiveness.py tests/test_proactive_injection.py -x -q`
- **After every plan wave:** Run `python -m pytest tests/ -x -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 23-01-01 | 01 | 1 | RETR-05 | unit | `python -m pytest tests/test_effectiveness.py -k "get_recommendations" -v` | ❌ W0 | ⬜ pending |
| 23-01-02 | 01 | 1 | RETR-06 | unit | `python -m pytest tests/test_effectiveness.py -k "min_observations" -v` | ❌ W0 | ⬜ pending |
| 23-01-03 | 01 | 1 | RETR-05 | integration | `python -m pytest tests/test_proactive_injection.py -k "recommendations" -v` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_effectiveness.py` — add test cases for `get_recommendations()` method (min observations, ranking, top-3 limit)
- [ ] `tests/test_proactive_injection.py` — add test cases for recommendations injection in hook

*Existing test files cover infrastructure — only new test methods needed.*

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
