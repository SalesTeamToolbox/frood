---
phase: 43
slug: effectiveness-workflow-offloading
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-06
---

# Phase 43 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | `tests/` directory (existing) |
| **Quick run command** | `python -m pytest tests/test_effectiveness_offloading.py -x -q` |
| **Full suite command** | `python -m pytest tests/ -x -q` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/test_effectiveness_offloading.py -x -q`
- **After every plan wave:** Run `python -m pytest tests/ -x -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 43-01-01 | 01 | 1 | SC-1, SC-2 | unit | `pytest tests/test_effectiveness_offloading.py -k "test_record_sequence or test_create_suggestion or test_get_pending or test_mark_suggestion or test_record_workflow_mapping or test_settings" -x` | no W0 | pending |
| 43-01-02 | 01 | 1 | SC-1 | unit | `pytest tests/test_effectiveness_offloading.py -k "test_append_tool_to_task or test_pop_task_tools" -x` | no W0 | pending |
| 43-02-01 | 02 | 2 | SC-1 | integration | `pytest tests/test_effectiveness_offloading.py -k "test_registry_accumulates_tools or test_end_task_pops_accumulator" -x` | no W0 | pending |
| 43-02-02 | 02 | 2 | SC-2, SC-3 | unit | `pytest tests/test_effectiveness_offloading.py -k "test_build_prompt_injects_suggestions or test_suggestion_marked_suggested_after_injection or test_build_prompt_no_suggestions or test_build_prompt_graceful" -x` | no W0 | pending |
| 43-02-03 | 02 | 2 | SC-3 | integration | `pytest tests/test_effectiveness_offloading.py::test_create_workflow_records_mapping -x` | no W0 | pending |

*Status: pending / green / red / flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_effectiveness_offloading.py` -- stubs for all success criteria
- [ ] Test fixtures for mock EffectivenessStore, mock N8N API responses

*Existing infrastructure covers pytest framework and async test patterns.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Prompt injection suggestion display | SC-2 | Requires running agent and inspecting prompt | Start agent, run same tool chain 3x, verify suggestion appears in agent prompt |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
