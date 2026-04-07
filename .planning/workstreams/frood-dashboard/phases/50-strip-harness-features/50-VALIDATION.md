---
phase: 50
slug: strip-harness-features
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-07
---

# Phase 50 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | `tests/` directory (no pytest.ini — uses defaults) |
| **Quick run command** | `python -m pytest tests/ -x -q` |
| **Full suite command** | `python -m pytest tests/ -v` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/ -x -q`
- **After every plan wave:** Run `python -m pytest tests/ -v`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 50-01-01 | 01 | 1 | STRIP-01 through STRIP-14 | integration | `python -m pytest tests/ -x -q` | ✅ | ⬜ pending |
| 50-01-02 | 01 | 1 | CLEAN-01 | integration | `python -m pytest tests/ -x -q` | ✅ | ⬜ pending |
| 50-02-01 | 02 | 1 | STRIP-02, STRIP-07 | integration | `python -m pytest tests/ -x -q` | ✅ | ⬜ pending |
| 50-03-01 | 03 | 2 | CLEAN-02 | integration | `python -m pytest tests/ -x -q` | ✅ | ⬜ pending |
| 50-04-01 | 04 | 2 | CLEAN-03, CLEAN-04 | integration | `python -m pytest tests/ -v` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

*Existing infrastructure covers all phase requirements. This is a deletion phase — tests verify nothing is broken, not that new behavior exists.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Sidebar shows only kept pages | CLEAN-02 | Visual layout check | Load dashboard, verify sidebar only shows Memory, Tools, Skills, Reports, Settings, Apps |
| No 500 errors on remaining pages | CLEAN-04 | Smoke test | Navigate to each kept page, verify no server errors |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
