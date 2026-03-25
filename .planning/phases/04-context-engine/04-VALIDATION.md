---
phase: 4
slug: context-engine
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-25
---

# Phase 4 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x + pytest-asyncio |
| **Config file** | pyproject.toml (asyncio_mode = "auto") |
| **Quick run command** | `python -m pytest tests/test_unified_context.py -x -q` |
| **Full suite command** | `python -m pytest tests/ -x -q` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/test_unified_context.py -x -q`
- **After every plan wave:** Run `python -m pytest tests/ -x -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 04-01-01 | 01 | 1 | CTX-01 | unit | `pytest tests/test_unified_context.py -k "jcodemunch"` | ❌ W0 | ⬜ pending |
| 04-01-02 | 01 | 1 | CTX-04 | unit | `pytest tests/test_unified_context.py -k "degradation"` | ❌ W0 | ⬜ pending |
| 04-02-01 | 02 | 1 | CTX-02 | unit | `pytest tests/test_unified_context.py -k "gsd_state"` | ❌ W0 | ⬜ pending |
| 04-02-02 | 02 | 1 | CTX-03 | unit | `pytest tests/test_unified_context.py -k "effectiveness"` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_unified_context.py` — stubs for CTX-01, CTX-02, CTX-03
- [ ] Test fixtures for mock jcodemunch MCP responses, mock EffectivenessStore, mock GSD state files

*Existing pytest infrastructure covers framework needs.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| jcodemunch MCP call works end-to-end | CTX-01 | Requires live jcodemunch server | Start jcodemunch, call agent42_unified_context with code query, verify symbols in response |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
