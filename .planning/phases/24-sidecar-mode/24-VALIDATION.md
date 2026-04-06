---
phase: 24
slug: sidecar-mode
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-28
---

# Phase 24 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | `tests/` directory (existing) |
| **Quick run command** | `python -m pytest tests/test_sidecar.py -x -q` |
| **Full suite command** | `python -m pytest tests/ -x -q` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/test_sidecar.py -x -q`
- **After every plan wave:** Run `python -m pytest tests/ -x -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| TBD | TBD | TBD | SIDE-01 | integration | `pytest tests/test_sidecar.py -k sidecar_mode` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | SIDE-02 | integration | `pytest tests/test_sidecar.py -k execute` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | SIDE-03 | integration | `pytest tests/test_sidecar.py -k callback` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | SIDE-04 | integration | `pytest tests/test_sidecar.py -k health` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | SIDE-05 | integration | `pytest tests/test_sidecar.py -k auth` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | SIDE-06 | unit | `pytest tests/test_sidecar.py -k idempotent` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | SIDE-07 | unit | `pytest tests/test_sidecar.py -k json_logging` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | SIDE-08 | integration | `pytest tests/test_sidecar.py -k core_services` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | SIDE-09 | unit | `pytest tests/test_sidecar.py -k config` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_sidecar.py` — stubs for SIDE-01 through SIDE-09
- [ ] Test fixtures for sidecar FastAPI TestClient

*Existing infrastructure (pytest, conftest) covers framework needs.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| CLI `--sidecar` flag starts server | SIDE-01 | Process startup behavior | Run `python agent42.py --sidecar` and verify server starts on sidecar port |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
