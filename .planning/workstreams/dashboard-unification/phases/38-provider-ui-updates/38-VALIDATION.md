---
phase: 38
slug: provider-ui-updates
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-04
---

# Phase 38 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | tests/ (existing) |
| **Quick run command** | `python -m pytest tests/ -x -q` |
| **Full suite command** | `python -m pytest tests/ -v` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/ -x -q`
- **After every plan wave:** Run `python -m pytest tests/ -v`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 38-01-T1 | 01 | 1 | PROVIDER-01 | grep | `! grep -q "StrongWall" dashboard/server.py` | ✅ | ⬜ pending |
| 38-01-T2 | 01 | 1 | PROVIDER-01,03,04,05 | unit | `python -m pytest tests/test_provider_ui.py -x -q` | ❌ W0 | ⬜ pending |
| 38-02-T1 | 02 | 2 | PROVIDER-02,03,04,05 | grep | `grep -c "loadSyntheticModels" dashboard/frontend/dist/app.js` | ✅ | ⬜ pending |
| 38-02-T2 | 02 | 2 | PROVIDER-02 | manual | Human visual verification of Providers tab | N/A | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_provider_ui.py` — stubs for PROVIDER-01 through PROVIDER-05
- [ ] `tests/conftest.py` — shared fixtures (if needed)

*Existing test infrastructure covers framework needs.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Provider tab UI renders correctly | PROVIDER-02 | Visual layout | Open dashboard, navigate to Providers tab, verify card layout |
| Synthetic model dropdown populates | PROVIDER-03 | Browser interaction | Create agent, verify model dropdown shows Synthetic models |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
