---
phase: 3
slug: claude-md-integration
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
| **Framework** | pytest (asyncio_mode = "auto") |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `python -m pytest tests/test_setup.py -x -q` |
| **Full suite command** | `python -m pytest tests/ -x -q` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/test_setup.py -x -q`
- **After every plan wave:** Run `python -m pytest tests/ -x -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 10 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 03-01-01 | 01 | 1 | INTEG-01 | unit | `python -m pytest tests/test_setup.py::TestClaudeMdGeneration::test_creates_claude_md_when_absent -x` | ❌ W0 | ⬜ pending |
| 03-01-02 | 01 | 1 | INTEG-02 | unit | `python -m pytest tests/test_setup.py::TestClaudeMdGeneration::test_template_contains_store_and_log -x` | ❌ W0 | ⬜ pending |
| 03-01-03 | 01 | 1 | INTEG-03 | unit | `python -m pytest tests/test_setup.py::TestClaudeMdGeneration::test_idempotent_on_rerun -x` | ❌ W0 | ⬜ pending |
| 03-01-04 | 01 | 1 | INTEG-03 | unit | `python -m pytest tests/test_setup.py::TestClaudeMdGeneration::test_appends_to_existing_claude_md -x` | ❌ W0 | ⬜ pending |
| 03-01-05 | 01 | 1 | INTEG-03 | unit | `python -m pytest tests/test_setup.py::TestClaudeMdGeneration::test_replaces_managed_section_on_rerun -x` | ❌ W0 | ⬜ pending |
| 03-01-06 | 01 | 1 | INTEG-03 | unit | `python -m pytest tests/test_setup.py::TestClaudeMdGeneration::test_preserves_content_outside_markers -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_setup.py::TestClaudeMdGeneration` — stubs for INTEG-01, INTEG-02, INTEG-03
- [ ] No new test files needed — uses existing `tests/test_setup.py`
- [ ] No new framework install needed — pytest already configured

*Existing infrastructure covers all phase requirements.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| setup.sh step calls python3 correctly | INTEG-03 | Shell script integration | Run `bash setup.sh` against a test project directory and verify CLAUDE.md is created with memory section |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
