---
phase: 19
slug: agent-config-dashboard
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-07
---

# Phase 19 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | pyproject.toml |
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
| 19-01-01 | 01 | 1 | CONF-01 | unit | `python -m pytest tests/test_dashboard_routing.py -k "settings_routing" -v` | ❌ W0 | ⬜ pending |
| 19-01-02 | 01 | 1 | CONF-01 | unit | `python -m pytest tests/test_dashboard_routing.py -k "model_selector" -v` | ❌ W0 | ⬜ pending |
| 19-02-01 | 02 | 2 | CONF-02 | unit | `python -m pytest tests/test_dashboard_routing.py -k "agent_routing" -v` | ❌ W0 | ⬜ pending |
| 19-02-02 | 02 | 2 | CONF-02 | unit | `python -m pytest tests/test_dashboard_routing.py -k "agent_card_chip" -v` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_dashboard_routing.py` — stubs for CONF-01, CONF-02
- [ ] Test fixtures for mock API responses (`/api/agent-routing`, `/api/available-models`)

*Existing pytest infrastructure covers framework needs.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Visual layout of LLM Routing tab | CONF-01 | CSS/visual rendering | Open Settings page, verify tab appears and layout matches design |
| Model chip on agent cards | CONF-02 | Visual element positioning | Open Agents page, verify model chips appear on cards |
| Unsaved changes warning | CONF-01, CONF-02 | Browser navigation interception | Edit a dropdown, navigate away, verify warning appears |
| Changes take effect without restart | CONF-01, CONF-02 | End-to-end integration | Change routing via UI, dispatch agent, verify new model used |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
