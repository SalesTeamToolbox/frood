---
phase: 51
slug: rebrand-and-repurpose
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-07
---

# Phase 51 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest |
| **Config file** | none (default discovery) |
| **Quick run command** | `python -m pytest tests/test_rebrand_phase51.py -x -q` |
| **Full suite command** | `python -m pytest tests/ -v` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/test_rebrand_phase51.py -x -q`
- **After every plan wave:** Run `python -m pytest tests/ -x -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 5 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 51-01-01 | 01 | 1 | BRAND-01 | unit (grep) | `python -m pytest tests/test_rebrand_phase51.py::test_agent_apps_renamed -x` | ❌ W0 | ⬜ pending |
| 51-01-02 | 01 | 1 | BRAND-02 | unit (grep) | `python -m pytest tests/test_rebrand_phase51.py::test_sidebar_nav -x` | ❌ W0 | ⬜ pending |
| 51-01-03 | 01 | 1 | BRAND-03 | unit (grep) | `python -m pytest tests/test_rebrand_phase51.py::test_no_agent42_visible -x` | ❌ W0 | ⬜ pending |
| 51-01-04 | 01 | 1 | BRAND-04 | unit (grep) | `python -m pytest tests/test_rebrand_phase51.py::test_setup_wizard_copy -x` | ❌ W0 | ⬜ pending |
| 51-02-01 | 02 | 1 | RPT-01 | unit (grep) | `python -m pytest tests/test_rebrand_phase51.py::test_reports_tabs -x` | ❌ W0 | ⬜ pending |
| 51-02-02 | 02 | 1 | RPT-02 | unit (grep) | `python -m pytest tests/test_rebrand_phase51.py::test_tasks_tab_removed -x` | ❌ W0 | ⬜ pending |
| 51-02-03 | 02 | 1 | RPT-03 | unit (grep) | `python -m pytest tests/test_rebrand_phase51.py::test_health_tab_present -x` | ❌ W0 | ⬜ pending |
| 51-02-04 | 02 | 1 | RPT-04 | unit (grep) | `python -m pytest tests/test_rebrand_phase51.py::test_intelligence_overview -x` | ❌ W0 | ⬜ pending |
| 51-03-01 | 03 | 2 | FEED-01 | unit (grep) | `python -m pytest tests/test_rebrand_phase51.py::test_activity_renderer -x` | ❌ W0 | ⬜ pending |
| 51-03-02 | 03 | 2 | FEED-02 | unit (grep) | `python -m pytest tests/test_rebrand_phase51.py::test_intelligence_event_types -x` | ❌ W0 | ⬜ pending |
| 51-03-03 | 03 | 2 | FEED-03 | unit (grep) | `python -m pytest tests/test_rebrand_phase51.py::test_activity_endpoint -x` | ❌ W0 | ⬜ pending |
| 51-04-01 | 04 | 1 | SET-01 | unit (grep) | `python -m pytest tests/test_rebrand_phase51.py::test_channels_tab_removed -x` | ❌ W0 | ⬜ pending |
| 51-04-02 | 04 | 1 | SET-02 | unit (grep) | `python -m pytest tests/test_rebrand_phase51.py::test_routing_tab -x` | ❌ W0 | ⬜ pending |
| 51-04-03 | 04 | 1 | SET-03 | unit (grep) | `python -m pytest tests/test_rebrand_phase51.py::test_max_concurrent_removed -x` | ❌ W0 | ⬜ pending |
| 51-04-04 | 04 | 1 | SET-04 | unit (grep) | `python -m pytest tests/test_rebrand_phase51.py::test_load_channels_removed -x` | ❌ W0 | ⬜ pending |
| 51-05-01 | 05 | 2 | CLEAN-05 | unit (grep) | `python -m pytest tests/test_rebrand_phase51.py::test_readme_updated -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_rebrand_phase51.py` — stubs for all BRAND/RPT/FEED/SET/CLEAN requirements
  - Pattern: same as `tests/test_settings_ui.py` — read app.js and server.py at module level, assert string presence/absence
  - No network calls needed — all assertions are string grep against file content

*Existing infrastructure covers test framework. Only new test file needed.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| SVG files render correctly after rename | BRAND-03 | Visual verification | Open dashboard, check logo/avatar/favicon display |
| Activity Feed real-time updates | FEED-02 | WebSocket behavior | Trigger a memory recall, verify event appears in feed |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 5s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
