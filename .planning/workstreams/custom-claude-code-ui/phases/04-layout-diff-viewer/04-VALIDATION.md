---
phase: 4
slug: layout-diff-viewer
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-19
---

# Phase 4 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.0.2 with pytest-asyncio |
| **Config file** | `pyproject.toml` — `[tool.pytest.ini_options]`, `asyncio_mode = "auto"` |
| **Quick run command** | `python -m pytest tests/test_cc_layout.py -x -q` |
| **Full suite command** | `python -m pytest tests/ -x -q` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/test_cc_layout.py -x -q`
- **After every plan wave:** Run `python -m pytest tests/ -x -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 10 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 04-01-01 | 01 | 0 | LAYOUT-01..04 | scaffold | `python -m pytest tests/test_cc_layout.py -x -q` | ❌ W0 | ⬜ pending |
| 04-02-01 | 02 | 1 | LAYOUT-01 | source inspection | `python -m pytest tests/test_cc_layout.py::TestCCPanelLayout::test_cc_tab_default_path -x` | ❌ W0 | ⬜ pending |
| 04-02-02 | 02 | 1 | LAYOUT-02 | source inspection | `python -m pytest tests/test_cc_layout.py::TestCCPanelLayout::test_panel_container_present -x` | ❌ W0 | ⬜ pending |
| 04-02-03 | 02 | 1 | LAYOUT-02 | source inspection | `python -m pytest tests/test_cc_layout.py::TestCCPanelLayout::test_panel_width_persistence -x` | ❌ W0 | ⬜ pending |
| 04-03-01 | 03 | 2 | LAYOUT-03 | source inspection | `python -m pytest tests/test_cc_layout.py::TestCCPanelLayout::test_toggle_function_defined -x` | ❌ W0 | ⬜ pending |
| 04-03-02 | 03 | 2 | LAYOUT-03 | source inspection | `python -m pytest tests/test_cc_layout.py::TestCCPanelLayout::test_panel_mode_flag -x` | ❌ W0 | ⬜ pending |
| 04-04-01 | 04 | 3 | LAYOUT-04 | source inspection | `python -m pytest tests/test_cc_layout.py::TestDiffViewer::test_open_diff_tab_defined -x` | ❌ W0 | ⬜ pending |
| 04-04-02 | 04 | 3 | LAYOUT-04 | source inspection | `python -m pytest tests/test_cc_layout.py::TestDiffViewer::test_create_diff_editor_used -x` | ❌ W0 | ⬜ pending |
| 04-04-03 | 04 | 3 | LAYOUT-04 | source inspection | `python -m pytest tests/test_cc_layout.py::TestDiffViewer::test_view_diff_button_on_file_tools -x` | ❌ W0 | ⬜ pending |
| 04-04-04 | 04 | 3 | LAYOUT-04 | source inspection | `python -m pytest tests/test_cc_layout.py::TestDiffViewer::test_diff_uses_agent42_dark_theme -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_cc_layout.py` — stubs for LAYOUT-01 through LAYOUT-04 (new file, matches established Phase 2/3 source-inspection pattern)

*Existing infrastructure covers framework setup (pyproject.toml, conftest.py already configured).*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Panel resize drag feel | LAYOUT-02 | UX quality assessment (min/max constraints are automated) | Drag panel handle left/right; verify smooth resize, min 250px, max 60% |
| Tab↔Panel mode switch visual continuity | LAYOUT-03 | Visual seamlessness hard to automate | Toggle mode while mid-conversation; verify no flash/jump |
| Diff editor side-by-side rendering | LAYOUT-04 | Monaco rendering requires actual browser | Click "View Diff" on a Write tool card; verify side-by-side display |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
