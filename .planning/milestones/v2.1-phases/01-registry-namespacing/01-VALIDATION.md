---
phase: 1
slug: registry-namespacing
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-23
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x + pytest-asyncio |
| **Config file** | pyproject.toml (asyncio_mode = "auto") |
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
| 01-01-01 | 01 | 1 | FOUND-01 | unit | `pytest tests/test_workspace_registry.py -k "test_default_seed"` | ❌ W0 | ⬜ pending |
| 01-01-02 | 01 | 1 | FOUND-02 | unit | `pytest tests/test_workspace_registry.py -k "test_crud"` | ❌ W0 | ⬜ pending |
| 01-01-03 | 01 | 1 | FOUND-04 | unit | `pytest tests/test_workspace_registry.py -k "test_path_validation"` | ❌ W0 | ⬜ pending |
| 01-01-04 | 01 | 1 | FOUND-06 | integration | `pytest tests/test_workspace_registry.py -k "test_workspace_endpoints"` | ❌ W0 | ⬜ pending |
| 01-02-01 | 02 | 1 | ISOL-06 | manual-only | — | — | ⬜ pending |
| 01-02-02 | 02 | 1 | ISOL-07 | manual-only | — | — | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_workspace_registry.py` — stubs for FOUND-01, FOUND-02, FOUND-04, FOUND-06

*Existing pytest infrastructure covers framework needs.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Zero behavior change for single-workspace users | FOUND-01 | Requires visual inspection of IDE page | Start Agent42, verify file explorer and CC chat work identically to pre-workspace state |
| Monaco URI namespace convention defined | ISOL-06 | Definition-only — no runtime behavior in Phase 1 | Verify `makeWorkspaceUri()` function exists in app.js with correct `workspace://` prefix pattern |
| localStorage key namespace helpers defined | ISOL-07 | Definition-only — no runtime behavior in Phase 1 | Verify `wsKey()` function exists in app.js with workspace_id prefix pattern |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
