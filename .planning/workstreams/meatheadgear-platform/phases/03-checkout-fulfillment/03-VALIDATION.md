---
phase: 03
slug: checkout-fulfillment
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-25
---

# Phase 03 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x + pytest-asyncio |
| **Config file** | `apps/meatheadgear/tests/` (existing test dir) |
| **Quick run command** | `python -m pytest apps/meatheadgear/tests/ -x -q` |
| **Full suite command** | `python -m pytest apps/meatheadgear/tests/ -v` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest apps/meatheadgear/tests/ -x -q`
- **After every plan wave:** Run `python -m pytest apps/meatheadgear/tests/ -v`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 03-01-01 | 01 | 1 | ORD-01 | unit | `pytest tests/test_checkout.py -k add_to_cart` | ❌ W0 | ⬜ pending |
| 03-01-02 | 01 | 1 | ORD-02 | unit | `pytest tests/test_stripe.py -k create_checkout` | ❌ W0 | ⬜ pending |
| 03-01-03 | 01 | 1 | ORD-03 | unit | `pytest tests/test_orders.py -k printful_order` | ❌ W0 | ⬜ pending |
| 03-02-01 | 02 | 2 | ORD-04 | unit | `pytest tests/test_orders.py -k confirmation_email` | ❌ W0 | ⬜ pending |
| 03-02-02 | 02 | 2 | ORD-05 | unit | `pytest tests/test_orders.py -k order_status` | ❌ W0 | ⬜ pending |
| 03-02-03 | 02 | 2 | ORD-06 | unit | `pytest tests/test_printful_webhook.py` | ❌ W0 | ⬜ pending |
| 03-02-04 | 02 | 2 | ORD-07 | unit | `pytest tests/test_orders.py -k shipping_email` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `apps/meatheadgear/tests/test_checkout.py` — stubs for ORD-01, ORD-02
- [ ] `apps/meatheadgear/tests/test_orders.py` — stubs for ORD-03, ORD-04, ORD-05, ORD-07
- [ ] `apps/meatheadgear/tests/test_printful_webhook.py` — stubs for ORD-06
- [ ] `apps/meatheadgear/tests/test_stripe.py` — extend for product checkout sessions
- [ ] `stripe>=11.0.0` added to requirements.txt

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Stripe test card payment | ORD-02 | Requires browser + Stripe test keys | Navigate to checkout, use card 4242424242424242 |
| Printful order visible in dashboard | ORD-03 | Requires live Printful API key | Check Printful dashboard after test order |
| Email arrives in inbox | ORD-04, ORD-07 | Requires Resend API key + real email | Trigger order, check recipient inbox |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
