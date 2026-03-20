---
phase: 17
slug: tier-routing-architecture
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-06
---

# Phase 17 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | pyproject.toml |
| **Quick run command** | `python -m pytest tests/test_model_router.py -x -q` |
| **Full suite command** | `python -m pytest tests/test_model_router.py tests/test_providers.py -v` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/test_model_router.py -x -q`
- **After every plan wave:** Run `python -m pytest tests/test_model_router.py tests/test_providers.py -v`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 17-01-01 | 01 | 1 | TIER-01 | unit | `pytest tests/test_model_router.py -k "l1"` | ❌ W0 | ⬜ pending |
| 17-01-02 | 01 | 1 | TIER-02 | unit | `pytest tests/test_model_router.py -k "strongwall_l1"` | ❌ W0 | ⬜ pending |
| 17-01-03 | 01 | 1 | TIER-03 | unit | `pytest tests/test_model_router.py -k "l2_gemini"` | ❌ W0 | ⬜ pending |
| 17-01-04 | 01 | 1 | TIER-04 | unit | `pytest tests/test_model_router.py -k "l2_or_paid"` | ❌ W0 | ⬜ pending |
| 17-02-01 | 02 | 1 | TIER-05 | unit | `pytest tests/test_model_router.py -k "fallback_chain"` | ❌ W0 | ⬜ pending |
| 17-02-02 | 02 | 1 | ROUTE-01 | unit | `pytest tests/test_model_router.py -k "agent_override"` | ❌ W0 | ⬜ pending |
| 17-02-03 | 02 | 1 | ROUTE-02 | unit | `pytest tests/test_model_router.py -k "no_or_free_critical"` | ❌ W0 | ⬜ pending |
| 17-02-04 | 02 | 1 | ROUTE-03 | unit | `pytest tests/test_model_router.py -k "free_providers_fallback"` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_model_router.py` — add test classes for L1/L2 tier routing, fallback chain, backward compat
- [ ] Existing `conftest.py` fixtures sufficient (sandbox, mock_tool, etc.)

*Existing infrastructure covers framework — only new test cases needed.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Backward compat with no StrongWall key | TIER-05 | Requires clean env without STRONGWALL_API_KEY | Set env without key, verify routing matches pre-L1 behavior |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
