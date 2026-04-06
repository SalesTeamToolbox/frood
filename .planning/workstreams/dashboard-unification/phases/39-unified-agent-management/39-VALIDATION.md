---
phase: 39
slug: unified-agent-management
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-04
---

# Phase 39 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | tests/ directory (existing) |
| **Quick run command** | `python -m pytest tests/test_unified_agents.py -x -q` |
| **Full suite command** | `python -m pytest tests/ -x -q` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/test_unified_agents.py -x -q`
- **After every plan wave:** Run `python -m pytest tests/ -x -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 39-01-01 | 01 | 1 | AGENT-01 | unit | `python -m pytest tests/test_unified_agents.py -k "test_unified_endpoint" -x -q` | ❌ W0 | ⬜ pending |
| 39-01-02 | 01 | 1 | AGENT-02 | unit | `python -m pytest tests/test_unified_agents.py -k "test_metrics" -x -q` | ❌ W0 | ⬜ pending |
| 39-02-01 | 02 | 2 | AGENT-01 | manual | Browser verification | N/A | ⬜ pending |
| 39-02-02 | 02 | 2 | AGENT-03 | manual | Browser verification | N/A | ⬜ pending |
| 39-02-03 | 02 | 2 | AGENT-04 | unit | `python -m pytest tests/test_unified_agents.py -k "test_templates" -x -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_unified_agents.py` — stubs for AGENT-01 through AGENT-04
- [ ] Shared fixtures for mock Paperclip API responses

*Existing test infrastructure (pytest, conftest.py) covers framework needs.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Unified agent cards render with source badges | AGENT-01 | Visual UI rendering | Load /agents page, verify Agent42 and Paperclip badges visible |
| Enhanced cards show sparkline and metrics | AGENT-02 | Visual UI rendering | Click agent card, verify metrics display |
| Create form shows source badge | AGENT-03 | Visual UI element | Open create agent form, verify "Agent42" badge |
| Templates show source system | AGENT-04 | Visual UI element | Open templates gallery, verify "Agent42" badge on cards |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
