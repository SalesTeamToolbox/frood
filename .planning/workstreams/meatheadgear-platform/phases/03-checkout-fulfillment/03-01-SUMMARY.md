---
phase: 03-checkout-fulfillment
plan: "01"
subsystem: purchase-pipeline
tags: [stripe, printful, resend, checkout, orders, email, fulfillment]
dependency_graph:
  requires: [stripe-checkout-session, printful-api, resend-email]
  provides: [purchase-flow, order-creation, printful-order-submit, order-confirmation-email, shipping-email]
  affects: [checkout-router, stripe-service, order-service, database, wallet]
tech_stack:
  added: [stripe>=11.0.0]
  patterns: [session-level-metadata, shipping-address-collection, printful-order-confirm, branded-html-email, httpx-resend]
key_files:
  created:
    - apps/meatheadgear/models_wallet.py
    - apps/meatheadgear/routers/checkout.py
    - apps/meatheadgear/services/stripe_service.py
    - apps/meatheadgear/services/order_service.py
  modified:
    - apps/meatheadgear/requirements.txt
    - apps/meatheadgear/config.py
    - apps/meatheadgear/database.py
decisions:
  - stripe>=11.0.0 added to requirements.txt — was imported but missing from dependency declaration
  - design_id and variant_id placed in session-level metadata (not payment_intent_data.metadata) so webhook handler reads from session.metadata
  - shipping_address_collection restricted to US only at launch (international shipping deferred)
  - Printful order confirmed immediately after creation to exit draft state — Order Agent handles retry if confirm fails
  - Branded dark-theme HTML email uses inline CSS only (email client compatibility) with Impact font, #ff2020 accent
  - send_shipping_confirmation() added for Phase 4 Order Agent to call when tracking webhook fires
  - base_url config field added for constructing public design image URLs sent to Printful (ngrok in dev, domain in prod)
  - printful_webhook_secret config field added for future Printful webhook signature verification
metrics:
  duration_minutes: 7
  completed_date: "2026-03-25"
  tasks_completed: 2
  tasks_total: 2
  files_modified: 7
---

# Phase 03 Plan 01: Checkout + Fulfillment Backend Summary

**One-liner:** Complete backend purchase pipeline — Stripe Checkout collects payment and US shipping address, webhook handler creates order with `design_id` in metadata, confirms Printful production order immediately (not draft), and sends branded dark-theme (#0d0d0d / #ff2020 / Impact) confirmation email via Resend.

## What Was Built

Seven files created or updated to implement the complete revenue path from Stripe checkout to Printful fulfillment:

**requirements.txt** — Added `stripe>=11.0.0`. The `stripe` package was already imported in stripe_service.py but not declared in requirements.

**config.py** — Added two fields to the `Settings` frozen dataclass: `base_url` (reads `BASE_URL` env var, used to construct publicly-accessible design image URLs for Printful — ngrok in dev, `https://meatheadgear.com` in prod) and `printful_webhook_secret` (reads `PRINTFUL_WEBHOOK_SECRET`, for future Printful webhook signature verification).

**models_wallet.py** — Added `PRINTFUL_EVENTS_SCHEMA_SQL` constant with a `printful_events_processed` table for Printful webhook idempotency, and a corresponding `PrintfulEventProcessed` dataclass.

**database.py** — Updated `init_db()` to: import and execute `PRINTFUL_EVENTS_SCHEMA_SQL`; add `ALTER TABLE orders ADD COLUMN tracking_url TEXT` migration (with try/except for idempotency); add `ALTER TABLE orders ADD COLUMN tracking_number TEXT` migration.

**routers/checkout.py** — Added `tracking_url`, `tracking_number`, and `shipping_name` fields to `OrderResponse` Pydantic model. Updated `purchase_design()` to pass `design_id=body.design_id` to `create_product_checkout()`. Updated `_order_response()` helper to include new fields.

**services/stripe_service.py** — Three major changes:
- `create_product_checkout()` now accepts `design_id: str = ""`, adds `shipping_address_collection={"allowed_countries": ["US"]}`, and moves `variant_id` plus `design_id` to session-level metadata (previously `variant_id` was only in `payment_intent_data.metadata`, making it invisible to the webhook handler that reads `session.metadata`).
- `_handle_checkout_completed()` product_purchase branch fully rewritten: extracts shipping from `session.shipping_details` with fallback to `collected_information.shipping_details`, looks up user email, creates order in DB, builds design image URL using `base_url` + `image_path`, creates Printful order (if image URL available), sends branded confirmation email, and optionally awards bonus credits.
- Added `from services import order_service` import.

**services/order_service.py** — Four changes:
- `create_order()` now accepts `shipping_name: str = ""` and `shipping_address: dict | str = ""` parameters. Shipping address is serialized as JSON if a dict. INSERT includes both new columns.
- `create_printful_order()` now confirms the order after creation by POSTing to `/orders/{printful_id}/confirm`, moving it out of draft state. Confirm failure is logged but not fatal (Order Agent handles retries).
- `send_order_confirmation()` replaced with branded dark-theme HTML template: bg `#0d0d0d`, accent `#ff2020`, Impact font uppercase headings, surface `#1a1a1a`, border `#2a2a2a`. Subject: `"Your order is confirmed — #{id[:8]}"`. Sender: `MeatheadGear <orders@meatheadgear.com>`. Uses `httpx.AsyncClient` directly (not resend SDK). Looks up product name and size from variant if not supplied.
- Added `send_shipping_confirmation()` function for Phase 4 Order Agent to call when Printful fires a tracking webhook. Same dark theme, tracking number in monospace, "TRACK YOUR ORDER" CTA button linking to the provided `tracking_url`.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | DB migrations, config additions, and stripe dependency | 0fd3710 | requirements.txt, config.py, database.py, models_wallet.py |
| 2 | Stripe checkout enhancement + webhook handler + Printful order confirm + branded email | 168aaa6 | routers/checkout.py, services/stripe_service.py, services/order_service.py |

Note: All commits are in the `apps/meatheadgear` sub-repo (the meatheadgear app has its own git repo at `apps/meatheadgear/.git`). The parent `agent42` repo ignores `apps/*` via `.gitignore`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Removed unused `base` variable in `send_shipping_confirmation()`**
- **Found during:** Task 2 ruff check
- **Issue:** `base = settings.base_url...` was assigned but never interpolated into the shipping HTML template (shipping email links directly to `tracking_url`, not a relative path)
- **Fix:** Removed the unused variable assignment
- **Files modified:** apps/meatheadgear/services/order_service.py
- **Commit:** 168aaa6

**2. [Rule 1 - Bug] Removed redundant `int()` around `round()` in `create_product_checkout()`**
- **Found during:** Task 2 ruff check (RUF046)
- **Issue:** `int(round(...))` — `round()` already returns an int when called with a float and no ndigits argument
- **Fix:** Changed `retail_cents = int(round(row["retail_price"] * 100))` to `retail_cents = round(row["retail_price"] * 100)`
- **Files modified:** apps/meatheadgear/services/stripe_service.py
- **Commit:** 168aaa6

### Notes

**Pre-existing ruff issues out of scope:** `services/design_session.py` (F841 unused `debit_entry`), `services/image_gen.py` (SIM110 for-loop can be `any()`), and `tests/test_wallet.py` (RUF003 ambiguous multiplication signs) all had pre-existing ruff errors. These were not introduced by this plan and are out of scope. Logged as deferred items.

**stripe package not installed in default Python:** The `stripe` package was only available in the root venv at `.venv/Scripts/python`. Verification ran using the venv python explicitly.

**Sub-repo commit pattern:** Same as prior phases — meatheadgear has its own git repo at `apps/meatheadgear/.git`.

**Spurious `=11.0.0` file:** A pip install command run earlier in the session created a spurious file named `=11.0.0` in the meatheadgear directory (from `pip install stripe>=11.0.0` without proper shell escaping). File was deleted before committing.

## Known Stubs

None. All functions are fully implemented:
- `create_printful_order()` submits to Printful API and confirms immediately
- `send_order_confirmation()` sends branded HTML email via Resend
- `send_shipping_confirmation()` sends branded HTML email via Resend with tracking link
- Graceful degradation throughout: missing API keys log and return False, never crash

The purchase flow will not trigger Printful without `PRINTFUL_API_KEY` configured (logs a warning). Email will not send without `RESEND_API_KEY` (logs info). This is intentional graceful degradation, not a stub.

## Self-Check: PASSED

Files verified:
- FOUND: apps/meatheadgear/requirements.txt
- FOUND: apps/meatheadgear/config.py
- FOUND: apps/meatheadgear/database.py
- FOUND: apps/meatheadgear/models_wallet.py
- FOUND: apps/meatheadgear/routers/checkout.py
- FOUND: apps/meatheadgear/services/stripe_service.py
- FOUND: apps/meatheadgear/services/order_service.py
- FOUND: .planning/workstreams/meatheadgear-platform/phases/03-checkout-fulfillment/03-01-SUMMARY.md

Commits verified (in apps/meatheadgear sub-repo):
- FOUND: 0fd3710 feat(03-01): DB migrations, config additions, and stripe dependency
- FOUND: 168aaa6 feat(03-01): complete backend purchase pipeline
