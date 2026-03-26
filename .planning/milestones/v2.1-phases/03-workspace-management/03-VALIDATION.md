---
phase: 3
slug: workspace-management
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-24
---

# Phase 3 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x + pytest-asyncio |
| **Config file** | pyproject.toml |
| **Quick run command** | `python -m pytest tests/test_workspace_registry.py -x -q` |
| **Full suite command** | `python -m pytest tests/ -x -q` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/test_workspace_registry.py -x -q`
- **After every plan wave:** Run `python -m pytest tests/ -x -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 03-01-01 | 01 | 1 | MGMT-01 | integration | `python -m pytest tests/test_workspace_registry.py -x -q` | TBD | ⬜ pending |
| 03-01-02 | 01 | 1 | MGMT-02 | integration | `python -m pytest tests/test_workspace_registry.py -x -q` | TBD | ⬜ pending |
| 03-01-03 | 01 | 1 | MGMT-03 | integration | `python -m pytest tests/test_workspace_registry.py -x -q` | TBD | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

*Existing infrastructure covers all phase requirements. Backend CRUD API has full test coverage (36 tests passing). Frontend changes are manual verification.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Add workspace modal opens, validates path, creates workspace | MGMT-01 | Frontend DOM interaction | Click "+", enter path, verify tab appears |
| Close button shows confirmation when unsaved files exist | MGMT-02 | Frontend confirm() dialog | Open file, modify it, click X on workspace tab |
| Last workspace close button is disabled | MGMT-02 | Frontend DOM state | Verify X button greyed out when 1 workspace |
| Inline rename on active tab click | MGMT-03 | Frontend DOM interaction | Click active tab name, type new name, press Enter |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
