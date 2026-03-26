---
phase: 03-checkout-fulfillment
plan: "02"
subsystem: purchase-pipeline
tags: [printful, webhooks, idempotency, tracking, email, fulfillment]
dependency_graph:
  requires: [printful-webhook-secret, order-service, printful-events-table, send-shipping-confirmation]
  provides: [printful-webhook-receiver, order-status-sync, tracking-persistence, shipping-email-trigger]
  affects: [printful_webhook-router, main, test-stubs]
tech_stack:
  added: []
  patterns: [composite-idempotency-key, event-routing, direct-sql-tracking-update, graceful-degradation]
key_files:
  created:
    - apps/meatheadgear/routers/printful_webhook.py
    - apps/meatheadgear/tests/test_printful_webhook.py
  modified:
    - apps/meatheadgear/main.py
decisions:
  - Idempotency key for package_shipped uses tracking_number (not order status) — allows re-delivery for different shipments on same order
  - Idempotency key for order_updated uses composite event_type:external_id:status — allows order to transition through multiple statuses without being blocked
  - _handle_package_shipped uses direct SQL UPDATE for tracking fields (update_order_status does not handle tracking_url/tracking_number)
  - email_row fetched before db.row_factory is set to avoid aiosqlite.Row affecting earlier tuple fetch
metrics:
  duration_minutes: 6
  completed_date: "2026-03-25"
  tasks_completed: 3
  tasks_total: 3
  files_modified: 3
---

# Phase 03 Plan 02: Printful Webhook Receiver Summary

**One-liner:** Printful webhook endpoint at POST /api/printful/webhook with composite idempotency, status mapping via PRINTFUL_STATUS_MAP, direct SQL tracking persistence, and automatic shipping confirmation email trigger on package_shipped events.

## What Was Built

Three files created or modified to implement the Printful webhook processing pipeline:

**routers/printful_webhook.py** — New file. `PRINTFUL_STATUS_MAP` maps 6 Printful statuses to app statuses (pending→submitted, in_production→printing, fulfilled→shipped, package_shipped→shipped, delivered→delivered, canceled→canceled). POST /webhook endpoint reads raw body, parses JSON (400 on failure), extracts external_id (ignores events without one), builds composite idempotency key, checks printful_events_processed table, routes to `_handle_order_updated` or `_handle_package_shipped`, then records the event and returns `{"status": "processed"}`. Duplicate events return `{"status": "already_processed"}`. `_handle_order_updated` looks up the mapped status and calls `order_service.update_order_status`. `_handle_package_shipped` does a direct SQL UPDATE on tracking_url, tracking_number, and status='shipped', then fetches the user email via JOIN and calls `order_service.send_shipping_confirmation`.

**main.py** — Added import of `printful_webhook_router` and `app.include_router(printful_webhook_router, prefix="/api/printful", tags=["printful"])` after the checkout router registration and before static file mounts.

**tests/test_printful_webhook.py** — New file with 13 test stubs across 3 classes: `TestPrintfulStatusMap` (5 concrete assertions on status mapping), `TestPrintfulWebhookEndpoint` (6 async stubs for invalid JSON, missing external_id, idempotency, order_updated, package_shipped tracking, shipping email), `TestIdempotencyKeys` (2 stubs for composite key format). All stubs pass (no-ops) so test suite stays green.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Create Printful webhook receiver router | f093934 | routers/printful_webhook.py |
| 2 | Register Printful webhook router in main.py | 07a27aa | main.py |
| 3 | Create test stubs for Printful webhook handler | 568f3e9 | tests/test_printful_webhook.py |

Note: All commits are in the `apps/meatheadgear` sub-repo (the meatheadgear app has its own git repo at `apps/meatheadgear/.git`).

## Deviations from Plan

None - plan executed exactly as written.

The row_factory was set to `aiosqlite.Row` in `_handle_package_shipped` after the initial `email_row` fetch (which returns a plain tuple), matching the pattern used in the plan's pseudocode. No behavioral change was needed.

## Known Stubs

The test file has 8 stub tests (pass-through) intentionally left for future TDD implementation. The 5 `TestPrintfulStatusMap` tests are fully implemented. The 8 stubs in `TestPrintfulWebhookEndpoint` and `TestIdempotencyKeys` are documented with TODO comments explaining implementation approach.

The webhook handler itself has no stubs — all paths are fully implemented with graceful degradation (missing API keys log and return, never crash).

## Self-Check: PASSED

Files verified:
- FOUND: apps/meatheadgear/routers/printful_webhook.py
- FOUND: apps/meatheadgear/tests/test_printful_webhook.py
- FOUND: apps/meatheadgear/main.py

Commits verified (in apps/meatheadgear sub-repo):
- FOUND: f093934 feat(03-02): create Printful webhook receiver router
- FOUND: 07a27aa feat(03-02): register Printful webhook router in main.py
- FOUND: 568f3e9 test(03-02): add Printful webhook test stubs
