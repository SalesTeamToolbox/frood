---
phase: 1
slug: setup-foundation
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-18
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x with pytest-asyncio |
| **Config file** | `pyproject.toml` (`[tool.pytest.ini_options]`, asyncio_mode = "auto") |
| **Quick run command** | `python -m pytest tests/test_setup.py -x -q` |
| **Full suite command** | `python -m pytest tests/ -x -q` |
| **Estimated runtime** | ~10 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/test_setup.py -x -q`
- **After every plan wave:** Run `python -m pytest tests/ -x -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 01-01-01 | 01 | 0 | SETUP-01..05 | unit | `pytest tests/test_setup.py -x` | ❌ W0 | ⬜ pending |
| 01-02-01 | 02 | 1 | SETUP-01 | unit | `pytest tests/test_setup.py::TestMcpConfigGeneration -x` | ❌ W0 | ⬜ pending |
| 01-02-02 | 02 | 1 | SETUP-01 | unit | `pytest tests/test_setup.py::TestMcpConfigMerge -x` | ❌ W0 | ⬜ pending |
| 01-03-01 | 03 | 1 | SETUP-02 | unit | `pytest tests/test_setup.py::TestHookRegistration -x` | ❌ W0 | ⬜ pending |
| 01-03-02 | 03 | 1 | SETUP-02 | unit | `pytest tests/test_setup.py::TestHookMerge -x` | ❌ W0 | ⬜ pending |
| 01-04-01 | 04 | 1 | SETUP-03 | unit | `pytest tests/test_setup.py::TestJcodemunchIndex -x` | ❌ W0 | ⬜ pending |
| 01-04-02 | 04 | 1 | SETUP-03 | unit | `pytest tests/test_setup.py::TestJcodemunchIndexFailure -x` | ❌ W0 | ⬜ pending |
| 01-05-01 | 05 | 2 | SETUP-04 | unit | `pytest tests/test_setup.py::TestIdempotency -x` | ❌ W0 | ⬜ pending |
| 01-06-01 | 06 | 2 | SETUP-05 | unit | `pytest tests/test_setup.py::TestHealthReport -x` | ❌ W0 | ⬜ pending |
| 01-06-02 | 06 | 2 | SETUP-05 | integration | `pytest tests/test_setup.py::TestMcpHealthProbe -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_setup.py` — stubs for SETUP-01 through SETUP-05 (all test classes above)
- [ ] `tests/conftest.py` — verify `tmp_path` fixture sufficient for setup tests (likely yes, already exists)
- [ ] `scripts/` directory — must be created for `jcodemunch_index.py`

*Existing test infrastructure covers framework; only test file is missing.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| `bash setup.sh` full E2E on Linux/VPS | SETUP-01..05 | Requires actual Linux env with Claude Code, Redis, Qdrant, jcodemunch | SSH to VPS, clone fresh, run `bash setup.sh`, verify `.mcp.json`, `.claude/settings.json`, health report |
| Idempotent re-run preserves config | SETUP-04 | Full script re-run behavior needs real filesystem | Run `bash setup.sh` twice, diff `.mcp.json` and `settings.json` |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
