# Phase 3: Checkout & Fulfillment - Context

**Gathered:** 2026-03-25
**Status:** Ready for planning

<domain>
## Phase Boundary

Customer selects a design on a product, pays via Stripe, and the order flows automatically to Printful for printing and shipping. Customer receives confirmation email, can view order status with real-time updates from Printful webhooks, and gets a shipping notification with tracking link when the order ships.

Requirements: ORD-01 through ORD-07.

</domain>

<decisions>
## Implementation Decisions

### Purchase Flow
- **D-01:** Buy Now (single-item direct purchase from design studio), not a shopping cart. Current code is single-item throughout — one design_id + one variant_id per order row. Cart can be added as a future phase if customers want same-design-on-multiple-products.
- **D-02:** Fix `create_product_checkout()` to pass `design_id` through Stripe session metadata so the webhook handler can associate the order with the correct design and its print-ready image file.
- **D-03:** Extend `_handle_checkout_completed()` for `product_purchase` type to call `create_order()` followed by `create_printful_order()` and `send_order_confirmation()` — currently it only awards bonus credits.

### Shipping Address Collection
- **D-04:** Stripe Checkout collects shipping address via `shipping_address_collection: {"allowed_countries": ["US"]}` parameter on session creation. US-only matches project constraints.
- **D-05:** Extract `shipping_details.name` and `shipping_details.address` from the `checkout.session.completed` webhook payload. Map to Printful's recipient format (line1, city, state_code, country_code, zip).
- **D-06:** Persist shipping info to the existing `shipping_name` and `shipping_address` columns in the `orders` table.

### Order Status & Tracking
- **D-07:** Extend order statuses: pending → paid → submitted → printing → shipped → delivered → canceled. Stored as free-text strings in existing `orders.status` TEXT column — no enum needed.
- **D-08:** Add `tracking_url` and `tracking_number` columns to the `orders` table for Printful shipping data.
- **D-09:** Enhanced status badges in the orders list — colored pills matching brand (not a timeline or step indicator). Make tracking link clickable when available.
- **D-10:** Map Printful statuses to customer-friendly labels: in_production → "Printing", fulfilled/package_shipped → "Shipped", delivered → "Delivered".

### Printful Webhook Receiver
- **D-11:** New `/api/printful/webhook` endpoint following the same idempotency pattern as Stripe webhook handler — verify signature, check processed-events table, update order status.
- **D-12:** Handle at minimum: `order_updated` (status changes), `package_shipped` (tracking URL + number). Update order status and trigger shipping notification email.

### Email Notifications
- **D-13:** Branded inline-CSS HTML templates matching site dark theme (#0d0d0d background, #ff2020 accent, Oswald headings, Inter body text). Python f-string templates, no Jinja2.
- **D-14:** Continue using raw `httpx` POST to Resend REST API (not the `resend` SDK — listed in requirements.txt but never imported, and httpx is the established pattern).
- **D-15:** Two transactional email types:
  - Order confirmation: order ID, product name, size, price, design thumbnail, link to orders page
  - Shipping confirmation: tracking link, carrier info, estimated delivery if available
- **D-16:** Sender: `MeatheadGear <orders@meatheadgear.com>` (already configured).

### Design Image URL for Printful
- **D-17:** Printful's API needs a publicly accessible URL to download the print file. Designs stored locally at `.data/designs/{user_id}/{design_id}.png` must be served via a URL Printful can reach. In development use ngrok/tunnel; in production the domain serves the file directly.

### Claude's Discretion
- Printful webhook signature verification mechanism (may differ from Stripe's HMAC)
- Exact Printful API v2 order creation payload format (current code may be v1)
- Status color mappings for the 3 new badge states (printing, shipped, delivered)
- Order confirmation email layout and exact content formatting
- Shipping email template design
- Error handling for failed Printful order creation (retry logic deferred to Phase 5 Order Agent)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase Requirements
- `.planning/workstreams/meatheadgear-platform/REQUIREMENTS.md` — ORD-01 through ORD-07 requirement specs

### Prior Phase Context
- `.planning/workstreams/meatheadgear-platform/phases/01-store-foundation/01-CONTEXT.md` — App structure, auth patterns, database patterns, frontend conventions
- `.planning/workstreams/meatheadgear-platform/phases/02-design-studio/02-CONTEXT.md` — Design storage, fal.ai pipeline, canvas editor, design data model

### Existing Implementation (to modify/extend)
- `apps/meatheadgear/routers/checkout.py` — Purchase endpoint + order history (needs design_id wiring)
- `apps/meatheadgear/services/stripe_service.py` — Stripe Checkout + webhook handler (needs shipping collection, design_id metadata, order creation in webhook)
- `apps/meatheadgear/services/order_service.py` — Order CRUD + Printful order creation + confirmation email (needs schema additions, shipping wiring, branded templates)
- `apps/meatheadgear/services/printful.py` — Printful API client (catalog reads only — needs webhook handling)
- `apps/meatheadgear/config.py` — Settings (may need printful_webhook_secret)
- `apps/meatheadgear/database.py` — Schema initialization (needs tracking columns migration)
- `apps/meatheadgear/models_wallet.py` — Stripe events processed table (reuse idempotency pattern)
- `apps/meatheadgear/frontend/app.js` — `handleProceedToCheckout()` stub + `loadOrders()` (needs wiring + enhanced badges)
- `apps/meatheadgear/frontend/index.html` — Orders section HTML
- `apps/meatheadgear/frontend/style.css` — Order status badge styles (needs 3 new color classes)

### External API Documentation
- Stripe Checkout Session: `shipping_address_collection` parameter, `shipping_details` in completed session
- Printful API: order creation endpoint, webhook event types (`order_updated`, `package_shipped`)
- Resend API: `POST https://api.resend.com/emails` with HTML body

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `services/stripe_service.py` — Full Stripe Checkout + webhook pattern with idempotency (reuse for Printful webhooks)
- `services/order_service.py` — Order CRUD, Printful order creation, confirmation email scaffold
- `routers/checkout.py` — Purchase + order history endpoints (extend, don't rewrite)
- `models_wallet.py` — `stripe_events_processed` table pattern (replicate for `printful_events_processed`)
- `frontend/style.css` — `.order-status` classes with 3 color variants (extend to 6)

### Established Patterns
- All HTTP calls via `httpx.AsyncClient` (not SDK wrappers) — follow for Resend emails and Printful webhooks
- Raw SQL via aiosqlite (no ORM) — add columns with `ALTER TABLE ... ADD COLUMN` in try/except
- Stripe webhook: HMAC verify → idempotency check → route by type → record processed
- Config via frozen dataclass from `.env`
- Frontend: vanilla JS, DOM manipulation, fetch API, SPA section navigation

### Integration Points
- Design studio "Proceed to Checkout" button → `handleProceedToCheckout()` in app.js (currently stubbed)
- Stripe `checkout.session.completed` webhook → needs to create order + Printful order + send email
- Printful webhooks → new endpoint, updates order status, triggers shipping email
- Orders list in frontend → needs enhanced status badges + tracking link
- `designs` table → lookup design image_path for Printful order creation

</code_context>

<specifics>
## Specific Ideas

- Design thumbnail in order confirmation email — pull from `designs.thumbnail_url` or `mockup_url`
- Tracking link opens in new tab from orders list (small icon next to status badge when shipped)
- Status badges: pending (yellow), paid (blue), printing (orange), shipped (green), delivered (green bold), canceled (red)
- "Checkout flow coming soon!" stub in app.js:942 becomes the real Stripe redirect

</specifics>

<deferred>
## Deferred Ideas

- Shopping cart (multi-item checkout) — future phase if customer demand warrants it
- Dedicated order detail page with full timeline — post-MVP enhancement
- Step-by-step visual progress indicator — can layer on top of badges later
- Resend delivery/bounce webhooks for email reliability monitoring — future operational concern
- International shipping (non-US countries) — v2 per project constraints

</deferred>

---
*Phase: 03-checkout-fulfillment*
*Context gathered: 2026-03-25*
