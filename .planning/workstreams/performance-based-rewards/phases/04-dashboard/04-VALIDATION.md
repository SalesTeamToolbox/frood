---
phase: 4
slug: dashboard
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-23
---

# Phase 4 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x with pytest-asyncio + TestClient |
| **Config file** | pyproject.toml (asyncio_mode = "auto") |
| **Quick run command** | `python -m pytest tests/test_rewards_api.py -x -q` |
| **Full suite command** | `python -m pytest tests/ -x -q` |
| **Estimated runtime** | ~20 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/test_rewards_api.py -x -q`
- **After every plan wave:** Run `python -m pytest tests/ -x -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 20 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 04-01-01 | 01 | 1 | DASH-01, DASH-05 | unit | `pytest tests/test_rewards_api.py -k "effective_tier or broadcast"` | ❌ W0 | ⬜ pending |
| 04-01-02 | 01 | 1 | ADMN-02, DASH-02, DASH-04, TEST-04 | unit | `pytest tests/test_rewards_api.py -x` | ❌ W0 | ⬜ pending |
| 04-02-01 | 02 | 2 | DASH-01, DASH-05 | manual | Visual check: tier badges on agent cards | N/A | ⬜ pending |
| 04-02-02 | 02 | 2 | DASH-02, DASH-03, DASH-04 | manual | Visual check: metrics panel, toggle, override | N/A | ⬜ pending |
| 04-02-03 | 02 | 2 | ALL | checkpoint | Human verify: full dashboard walkthrough | N/A | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_rewards_api.py` — stubs for ADMN-02, DASH-01, DASH-02, DASH-04, DASH-05, TEST-04

*Existing infrastructure (conftest.py, pytest config, TestClient) covers framework needs.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Tier badge colors and positioning | DASH-01 | Visual CSS verification | Check agent cards show colored tier badges |
| Performance metrics panel layout | DASH-02 | Visual layout check | Click agent, verify metrics panel appears |
| Toggle confirmation dialog | DASH-03 | Browser dialog interaction | Click toggle, verify confirm() appears |
| Override dropdown + expiry | DASH-04 | Form interaction | Select tier from dropdown, verify API call |
| Real-time badge update | DASH-05 | WebSocket timing | Trigger recalc, watch badge update without refresh |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 20s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
