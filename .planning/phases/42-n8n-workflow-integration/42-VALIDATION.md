---
phase: 42
slug: n8n-workflow-integration
status: draft
nyquist_compliant: true
wave_0_complete: true
created: 2026-04-05
---

# Phase 42 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (existing in project) |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `python -m pytest tests/test_n8n_tool.py tests/test_n8n_create_tool.py -x -q` |
| **Full suite command** | `python -m pytest tests/ -x -q` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/test_n8n_tool.py tests/test_n8n_create_tool.py -x -q`
- **After every plan wave:** Run `python -m pytest tests/ -x -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 10 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 42-01-01 | 01 | 1 | D-11,D-12,D-13 | unit | `pytest tests/test_n8n_tool.py::test_config -x` | No — W0 | pending |
| 42-01-02 | 01 | 1 | D-04 | unit (mock httpx) | `pytest tests/test_n8n_tool.py::test_list_workflows -x` | No — W0 | pending |
| 42-01-03 | 01 | 1 | D-05 | unit (mock httpx) | `pytest tests/test_n8n_tool.py::test_trigger_workflow -x` | No — W0 | pending |
| 42-01-04 | 01 | 1 | D-06 | unit (mock httpx) | `pytest tests/test_n8n_tool.py::test_get_status -x` | No — W0 | pending |
| 42-01-05 | 01 | 1 | D-07 | unit | `pytest tests/test_n8n_tool.py::test_get_output -x` | No — W0 | pending |
| 42-01-06 | 01 | 1 | D-14 | unit | `pytest tests/test_n8n_tool.py::test_unconfigured -x` | No — W0 | pending |
| 42-01-07 | 01 | 1 | D-22 | unit | `pytest tests/test_n8n_tool.py::test_rate_limiting -x` | No — W0 | pending |
| 42-02-01 | 02 | 2 | D-08 | unit | `pytest tests/test_n8n_create_tool.py::test_workflow_generation -x` | No — W0 | pending |
| 42-02-02 | 02 | 2 | D-10 | unit | `pytest tests/test_n8n_create_tool.py::test_node_validation -x` | No — W0 | pending |
| 42-02-03 | 02 | 2 | D-09 | unit | `pytest tests/test_n8n_create_tool.py::test_template_loading -x` | No — W0 | pending |

*Status: pending / green / red / flaky*

---

## Wave 0 Requirements

*Tests are embedded in TDD tasks (Plan 01 Task 1, Plan 02 Task 2) — no separate Wave 0 plan needed.*

- [x] `tests/test_n8n_tool.py` — created as TDD in Plan 01 Task 1
- [x] `tests/test_n8n_create_tool.py` — created as TDD in Plan 02 Task 2
- [x] Mock fixtures embedded in test files

*Existing infrastructure covers pytest framework — no new framework installation needed.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Docker N8N container starts | D-18 | Requires Docker daemon | `docker run -d --name n8n-test -p 5678:5678 n8nio/n8n && curl http://localhost:5678/healthz` |
| Webhook trigger end-to-end | D-05 | Requires live N8N | Create test workflow in N8N UI, trigger via tool, verify response |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
