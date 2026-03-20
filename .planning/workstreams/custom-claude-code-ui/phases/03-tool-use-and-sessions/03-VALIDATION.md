---
phase: 3
slug: tool-use-and-sessions
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-18
---

# Phase 3 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x + pytest-asyncio (asyncio_mode = "auto") |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `python -m pytest tests/test_cc_tool_use.py -x -q` |
| **Full suite command** | `python -m pytest tests/ -x -q` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/test_cc_tool_use.py tests/test_cc_bridge.py -x -q`
- **After every plan wave:** Run `python -m pytest tests/ -x -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 03-01-01 | 01 | 1 | TOOL-01 | unit (source inspection) | `pytest tests/test_cc_tool_use.py::TestToolCards::test_tool_card_created_on_tool_start -x` | ❌ W0 | ⬜ pending |
| 03-01-02 | 01 | 1 | TOOL-02 | unit (source inspection) | `pytest tests/test_cc_tool_use.py::TestToolCards::test_tool_card_input_from_delta -x` | ❌ W0 | ⬜ pending |
| 03-01-03 | 01 | 1 | TOOL-03 | unit (_parse_cc_event) | `pytest tests/test_cc_tool_use.py::TestParseToolResult::test_tool_result_emits_tool_output -x` | ❌ W0 | ⬜ pending |
| 03-01-04 | 01 | 1 | TOOL-04 | unit (source inspection) | `pytest tests/test_cc_tool_use.py::TestToolCards::test_file_tool_card_shows_path -x` | ❌ W0 | ⬜ pending |
| 03-01-05 | 01 | 1 | TOOL-05 | unit (source inspection) | `pytest tests/test_cc_tool_use.py::TestToolCards::test_bash_tool_card_shows_command -x` | ❌ W0 | ⬜ pending |
| 03-02-01 | 02 | 2 | TOOL-06 | unit (_parse_cc_event) | `pytest tests/test_cc_tool_use.py::TestPermissionRequest::test_permission_tool_emits_permission_request -x` | ❌ W0 | ⬜ pending |
| 03-03-01 | 03 | 1 | SESS-01 | source inspection | `pytest tests/test_cc_tool_use.py::TestSessionPersistence::test_session_id_in_ws_url -x` | ❌ W0 | ⬜ pending |
| 03-03-02 | 03 | 1 | SESS-02 | source inspection | `pytest tests/test_cc_tool_use.py::TestSessionPersistence::test_session_id_stored_in_session_storage -x` | ❌ W0 | ⬜ pending |
| 03-03-03 | 03 | 1 | SESS-03 | source inspection | `pytest tests/test_cc_tool_use.py::TestMultiSessionTabs::test_tab_strip_rendered -x` | ❌ W0 | ⬜ pending |
| 03-03-04 | 03 | 1 | SESS-04 | source inspection | `pytest tests/test_cc_tool_use.py::TestSessionSidebar::test_sidebar_loads_sessions -x` | ❌ W0 | ⬜ pending |
| 03-03-05 | 03 | 1 | SESS-05 | source inspection | `pytest tests/test_cc_tool_use.py::TestSessionSidebar::test_sidebar_click_resumes -x` | ❌ W0 | ⬜ pending |
| 03-03-06 | 03 | 1 | SESS-06 | source inspection | `pytest tests/test_cc_tool_use.py::TestTokenBar::test_token_bar_rendered -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_cc_tool_use.py` — stubs for TOOL-01 through TOOL-06, SESS-01 through SESS-06 (all 12 requirements)
- [ ] `tests/fixtures/cc_tool_result_sample.ndjson` — live-verified tool_result event fixture (needed for TOOL-03 unit test)

*Existing infrastructure covers framework install — `python -m pytest tests/ -x -q` passes.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Tool card collapse/expand animation | TOOL-01 | CSS animation not testable in unit tests | Open CC chat, trigger a tool, verify card animates on click |
| Permission card pulse effect while waiting | TOOL-06 | CSS animation + blocking UX flow | Send a command requiring permission, verify pulse appears and blocks until response |
| Session tab switching swaps chat content | SESS-03 | Multi-tab browser state interaction | Open 2+ sessions, switch tabs, verify each shows its own messages |
| Session resume shows "Session resumed" | SESS-05 | Full CC subprocess lifecycle + --resume | Click a past session, verify status message appears and CC has context |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
