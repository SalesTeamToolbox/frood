# Phase 3: Checkout & Fulfillment - Research

**Researched:** 2026-03-25
**Domain:** Stripe Checkout, Printful Orders API, Resend transactional email, FastAPI webhooks
**Confidence:** HIGH (Stripe, Resend), MEDIUM (Printful v2 order payload), LOW (Printful webhook signature)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Buy Now (single-item direct purchase), not a shopping cart.
- **D-02:** Fix `create_product_checkout()` to pass `design_id` through Stripe session metadata.
- **D-03:** Extend `_handle_checkout_completed()` for `product_purchase` type to call `create_order()` + `create_printful_order()` + `send_order_confirmation()`.
- **D-04:** Stripe Checkout collects shipping address via `shipping_address_collection: {"allowed_countries": ["US"]}`. US-only.
- **D-05:** Extract `shipping_details.name` and `shipping_details.address` from `checkout.session.completed` webhook payload. Map to Printful recipient format.
- **D-06:** Persist shipping info to existing `shipping_name` and `shipping_address` columns in the `orders` table.
- **D-07:** Status sequence: pending → paid → submitted → printing → shipped → delivered → canceled. Free-text strings, no enum.
- **D-08:** Add `tracking_url` and `tracking_number` columns to `orders` table.
- **D-09:** Enhanced status badges (colored pills), not a timeline. Tracking link clickable when available.
- **D-10:** Map Printful statuses: in_production → "Printing", fulfilled/package_shipped → "Shipped", delivered → "Delivered".
- **D-11:** New `/api/printful/webhook` endpoint. Same idempotency pattern as Stripe webhook handler.
- **D-12:** Handle `order_updated` (status changes) and `package_shipped` (tracking URL + number).
- **D-13:** Branded inline-CSS HTML templates. Python f-string templates, no Jinja2.
- **D-14:** Raw `httpx` POST to Resend REST API (not resend SDK).
- **D-15:** Two transactional email types: order confirmation and shipping confirmation.
- **D-16:** Sender: `MeatheadGear <orders@meatheadgear.com>`.
- **D-17:** Designs served via URL Printful can reach. Use ngrok/tunnel in dev; production domain in prod.

### Claude's Discretion

- Printful webhook signature verification mechanism (may differ from Stripe's HMAC)
- Exact Printful API v2 order creation payload format (current code may be v1)
- Status color mappings for the 3 new badge states (printing, shipped, delivered)
- Order confirmation email layout and exact content formatting
- Shipping email template design
- Error handling for failed Printful order creation (retry logic deferred to Phase 5 Order Agent)

### Deferred Ideas (OUT OF SCOPE)

- Shopping cart (multi-item checkout)
- Dedicated order detail page with full timeline
- Step-by-step visual progress indicator
- Resend delivery/bounce webhooks
- International shipping (non-US countries)
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| ORD-01 | Customer selects product, size, color and adds to cart | Buy Now flow: `handleProceedToCheckout()` → POST `/api/checkout/purchase` with design_id, product_id, size |
| ORD-02 | Stripe checkout flow with card payment | `create_product_checkout()` needs `shipping_address_collection` + `design_id` in metadata; existing Stripe SDK pattern extended |
| ORD-03 | On successful payment, order automatically created in Printful | `_handle_checkout_completed()` extended for `product_purchase`; calls `create_printful_order()` with v1 or v2 payload |
| ORD-04 | Customer receives order confirmation email via Resend | `send_order_confirmation()` upgraded to branded HTML f-string template via raw httpx POST |
| ORD-05 | Customer can view order status | Orders list in frontend upgraded: enhanced status badges + tracking link |
| ORD-06 | Printful fulfillment webhooks update order status in real-time | New `/api/printful/webhook` endpoint with idempotency table (`printful_events_processed`) |
| ORD-07 | Customer receives shipping confirmation email with tracking number | `send_shipping_confirmation()` new function; triggered from Printful `package_shipped` webhook handler |
</phase_requirements>

---

## Summary

Phase 3 wires together three pre-existing scaffolds — Stripe Checkout, Printful order creation, and Resend email — into a complete purchase flow. All major code structures exist; this phase primarily fills the stubs and adds the missing plumbing.

The three key integration challenges are: (1) threading `design_id` through the Stripe session metadata so the webhook handler can retrieve the print-ready image URL; (2) choosing between Printful API v1 (currently used in `printful.py` for catalog) and v2 (different order payload structure with `placements`/`layers`) for order creation; and (3) implementing the Printful webhook receiver where signature verification details are underdocumented and may need to be discovered at runtime.

The critical discovery is that the existing `order_service.create_printful_order()` uses v1 API endpoint (`https://api.printful.com/orders`) with `variant_id` + `files` payload. The v2 API uses `catalog_variant_id` + `placements`/`layers` instead. Since the catalog sync already uses v2 (`PRINTFUL_BASE_URL = "https://api.printful.com/v2"`), the planner must decide which API version to use for orders. Research recommends staying with v1 for orders since the existing scaffold is already there and v1 is not deprecated.

**Primary recommendation:** Use Printful API v1 for order creation (existing scaffold, simpler payload, not deprecated), extend Stripe Checkout with `shipping_address_collection`, build Printful webhook receiver with IP allowlist as the primary security measure (signature verification mechanism is underdocumented for v1), and implement two branded HTML email templates via raw httpx.

---

## Standard Stack

### Core (All Already Installed)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `stripe` | 12.x (async SDK v14+) | Stripe Checkout session creation + HMAC webhook verification | Already used in `stripe_service.py`; `create_async()` and `Webhook.construct_event()` are the established patterns |
| `httpx` | >=0.28.0 | Printful API calls + Resend email API calls | Established pattern across entire app; no SDK wrappers |
| `aiosqlite` | >=0.20.0 | Order CRUD, new tracking columns, idempotency tables | Already used throughout; raw SQL pattern |
| FastAPI | >=0.115.0 | Webhook receiver endpoints | Already the app framework |

### Missing from requirements.txt

| Library | Version | Purpose | Action |
|---------|---------|---------|--------|
| `stripe` | >=11.0.0 | Stripe SDK (async Checkout + HMAC) | **Must add** — used in `stripe_service.py` but not in `requirements.txt` |

**Installation:**
```bash
# Add to apps/meatheadgear/requirements.txt:
stripe>=11.0.0
```

**Version verification:**
```bash
npm view stripe version  # N/A — Python package
pip index versions stripe  # Latest: 12.x
```

The `stripe` package is already imported and used throughout the codebase but was never added to `requirements.txt`. This must be fixed as part of Wave 0 or Plan 1.

---

## Architecture Patterns

### Recommended Project Structure (Additions Only)

```
apps/meatheadgear/
├── routers/
│   ├── checkout.py         # Extend: design_id param, updated OrderResponse fields
│   └── printful_webhook.py # NEW: /api/printful/webhook endpoint
├── services/
│   ├── stripe_service.py   # Extend: shipping_address_collection, design_id metadata, order creation in webhook
│   ├── order_service.py    # Extend: tracking columns, shipping wiring, branded emails, shipping_confirmation
│   └── printful.py         # Extend: add order creation, webhook handler logic (or keep in order_service)
├── models_wallet.py        # Contains printful_events_processed table (extend)
├── database.py             # Add ALTER TABLE migrations for tracking columns
└── frontend/
    ├── app.js              # handleProceedToCheckout() → real Stripe redirect + enhanced badges
    ├── index.html          # Orders section: tracking link element
    └── style.css           # 3 new status badge color classes
```

### Pattern 1: Stripe Session with Shipping + Metadata

The existing `create_product_checkout()` needs three additions:
1. `shipping_address_collection: {"allowed_countries": ["US"]}` — collects address at Stripe Checkout
2. `design_id` in session-level `metadata` — survives to webhook payload
3. The `checkout.session.completed` webhook object provides `shipping_details` nested under `collected_information` (newer Stripe API versions) OR at the top-level `shipping_details` (older versions)

**Verified Stripe payload structure (HIGH confidence — official docs):**

The `checkout.session.completed` object contains:
```
shipping_details (top-level OR in collected_information)
  ├── name (string)
  └── address (object)
      ├── line1 (string, nullable)
      ├── line2 (string, nullable)
      ├── city (string, nullable)
      ├── state (string, nullable)
      ├── country (string, nullable)
      └── postal_code (string, nullable)
```

```python
# Source: Stripe API reference (docs.stripe.com/api/checkout/sessions/object)
session = await stripe.checkout.Session.create_async(
    mode="payment",
    line_items=[...],
    shipping_address_collection={
        "allowed_countries": ["US"],
    },
    metadata={
        "user_id": str(user_id),
        "type": "product_purchase",
        "design_id": design_id,   # NEW — thread through for webhook handler
    },
    success_url=success_url,
    cancel_url=cancel_url,
)
```

**Webhook extraction pattern:**
```python
# In _handle_checkout_completed():
design_id = metadata.get("design_id", "")
shipping = session.get("shipping_details", {})
# Also check collected_information.shipping_details (newer API versions)
if not shipping:
    shipping = session.get("collected_information", {}).get("shipping_details", {})
shipping_name = shipping.get("name", "")
addr = shipping.get("address", {})
```

### Pattern 2: Printful Order Creation (v1 API)

The existing `create_printful_order()` in `order_service.py` is already correct for v1. Key finding: **stay on v1 for order creation.** The catalog uses v2 (`/v2/catalog-products`) but orders can use v1 (`/orders`). The v1 endpoint is not deprecated and the scaffold is already written.

**v1 order creation payload (MEDIUM confidence — verified by multiple sources):**
```python
# POST https://api.printful.com/orders
{
    "external_id": order_id,          # Our DB order ID (up to 32 chars)
    "recipient": {
        "name": shipping_name,
        "address1": addr.get("line1", ""),
        "city": addr.get("city", ""),
        "state_code": addr.get("state", ""),
        "country_code": addr.get("country", "US"),
        "zip": addr.get("postal_code", ""),
    },
    "items": [{
        "variant_id": printful_variant_id,  # printful_variant_id from product_variants table
        "quantity": 1,
        "retail_price": f"{retail_price:.2f}",
        "files": [{
            "type": "default",
            "url": design_image_url,  # Must be publicly accessible
        }]
    }]
}
```

**Response structure:** `data["result"]["id"]` — the Printful order ID.

**Draft vs confirmed:** v1 orders are created as drafts by default. To auto-confirm for immediate fulfillment, call `POST https://api.printful.com/orders/{id}/confirm` after creation, OR pass `confirm=true` query parameter. Research recommends calling confirm immediately after creation in the same function to avoid stuck drafts.

**Note on v2 option (for Claude's discretion):** If Printful API key is a v2-era token, the v2 order creation at `https://api.printful.com/v2/orders` requires `catalog_variant_id` (same as `printful_variant_id` stored in DB) and `placements[{placement, technique, layers[{type, url}]}]`. The `front_large` placement should be used as of May 2025 (not `front`). Since the planner can choose, v1 is preferred for this phase for simplicity.

### Pattern 3: Printful Webhook Receiver

Printful v1 API **does not document HMAC signature verification** (LOW confidence — could not find official documentation of a header or secret for v1 webhooks). V2 states "request signing" but the exact mechanism is undocumented in publicly accessible sources.

**Pragmatic approach (Claude's discretion):** Implement the receiver without signature verification but with:
1. Idempotency check via `printful_events_processed` table (same pattern as `stripe_events_processed`)
2. Optional: validate that the IP is from Printful (Printful publishes their IP ranges)

```python
# POST /api/printful/webhook
# New router: routers/printful_webhook.py

async def handle_printful_webhook(payload: bytes, request: Request) -> dict:
    """Process Printful webhook event with idempotency."""
    data = json.loads(payload)
    event_type = data.get("type", "")

    # Note: Printful v1 does not use HMAC signature header — no verification step
    # Idempotency: use event type + order external_id as dedup key
    # (Printful does not send unique event IDs on v1 webhooks)
```

**Printful v1 webhook payload structure (MEDIUM confidence — derived from docs + community examples):**
```json
{
  "type": "package_shipped",
  "data": {
    "order": {
      "id": 12345678,
      "external_id": "our-order-uuid",
      "status": "fulfilled"
    },
    "shipment": {
      "id": 987654,
      "tracking_number": "1Z999AA10123456784",
      "tracking_url": "https://tools.usps.com/...",
      "service": "USPS",
      "ship_date": "2024-03-25"
    }
  }
}
```

For `order_updated`, the payload contains `data.order` with a `status` field. Map Printful statuses to app statuses:
- `in_production` → `"printing"`
- `fulfilled` → `"shipped"` (when `package_shipped` fires, use shipment data)
- `delivered` → `"delivered"`
- `canceled` → `"canceled"`

**Idempotency key for Printful events:** Use `f"{event_type}:{external_id}"` since Printful v1 webhooks do not include a unique event ID field.

### Pattern 4: Database Schema Migrations

Add two columns to existing `orders` table using `ALTER TABLE ... ADD COLUMN` in try/except (established pattern):

```python
# In database.py init_db():
try:
    await db.execute("ALTER TABLE orders ADD COLUMN tracking_url TEXT")
    await db.commit()
except Exception:
    pass  # Column already exists

try:
    await db.execute("ALTER TABLE orders ADD COLUMN tracking_number TEXT")
    await db.commit()
except Exception:
    pass
```

Add idempotency table for Printful events (in `models_wallet.py` or a new `models_printful.py`):
```sql
CREATE TABLE IF NOT EXISTS printful_events_processed (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_key TEXT UNIQUE NOT NULL,    -- "{type}:{external_id}"
    event_type TEXT NOT NULL,
    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Pattern 5: Branded HTML Email Templates

Python f-strings with inline CSS. No Jinja2. The `send_order_confirmation()` stub in `order_service.py` currently sends plain HTML — replace with branded template.

```python
# Color palette from style.css analysis:
# Background: #0d0d0d
# Accent: #ff2020
# Text: #e8e8e8
# Surface: #1a1a1a
# Border: #2a2a2a

def _order_confirmation_html(order: dict, product_name: str, design_thumbnail_url: str) -> str:
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#0d0d0d;font-family:Arial,sans-serif;color:#e8e8e8;">
  <div style="max-width:600px;margin:0 auto;padding:40px 20px;">
    <h1 style="font-family:Impact,Arial,sans-serif;color:#ff2020;text-transform:uppercase;
               font-size:32px;margin:0 0 24px 0;letter-spacing:2px;">
      ORDER CONFIRMED
    </h1>
    <div style="background:#1a1a1a;border:1px solid #2a2a2a;border-radius:8px;padding:24px;
                margin-bottom:24px;">
      <p style="margin:0 0 8px 0;color:#888;">Order ID</p>
      <p style="margin:0 0 16px 0;font-family:monospace;font-size:18px;">
        #{order['id'][:8].upper()}
      </p>
      ...
    </div>
    <a href="https://meatheadgear.com"
       style="display:inline-block;background:#ff2020;color:#fff;text-decoration:none;
              padding:14px 28px;font-family:Impact,Arial;text-transform:uppercase;
              font-size:16px;letter-spacing:1px;border-radius:4px;">
      VIEW ORDER STATUS
    </a>
  </div>
</body>
</html>"""
```

### Pattern 6: Frontend Checkout Flow Wire-Up

The `handleProceedToCheckout()` stub at app.js:942 calls `alert('Checkout flow coming soon!')`. It needs to:
1. Extract `state.latestDesign.id` and `state.currentProduct.id` + selected size/color from state
2. Call `POST /api/checkout/purchase` via `authFetch()`
3. Redirect to the Stripe Checkout URL returned

```javascript
// app.js — replace handleProceedToCheckout()
async function handleProceedToCheckout() {
  if (!state.latestDesign || !state.currentProduct) {
    alert('Please select a product and design first.');
    return;
  }
  hideMockupModal();

  try {
    const data = await authFetch('/api/checkout/purchase', {
      method: 'POST',
      body: JSON.stringify({
        design_id: state.latestDesign.id,
        product_id: state.currentProduct.id,
        size: state.selectedSize || 'M',
        success_url: window.location.origin + '?section=orders',
        cancel_url: window.location.href,
      }),
    });
    window.location.href = data.checkout_url;
  } catch (err) {
    alert('Checkout failed: ' + (err.message || 'Unknown error'));
  }
}
```

**State gap:** The current app state has `currentProduct` but `selectedSize` is not tracked globally. The planner must add `selectedSize` and `selectedColor` to state and populate them when a user picks a product variant in the design studio.

### Pattern 7: Enhanced Status Badges

Current CSS has 3 classes: `status-complete`, `status-pending`, `status-other`. New status map:

| Status | CSS Class | Color |
|--------|-----------|-------|
| `pending` | `status-pending` | `#eab308` (yellow) — exists |
| `paid` | `status-paid` | `#3b82f6` (blue) — new |
| `submitted` | `status-submitted` | `#a855f7` (purple) — new |
| `printing` | `status-printing` | `#f97316` (orange) — new |
| `shipped` | `status-shipped` | `#22c55e` (green) — new |
| `delivered` | `status-delivered` | `#16a34a` (dark green bold) — new |
| `canceled` | `status-canceled` | `#ff2020` (brand red) — new |

The JavaScript status→class map in `loadOrders()` currently uses a simple ternary; replace with a lookup object.

### Anti-Patterns to Avoid

- **Storing design_id only in payment_intent_data.metadata:** The payment_intent's metadata is NOT accessible in `checkout.session.completed` directly — it requires an extra API call to retrieve the payment intent. Use session-level `metadata` instead (already in the session object).
- **Using Printful v2 order payload with v1 endpoint:** The `https://api.printful.com/orders` endpoint (v1) requires `variant_id` + `files`, NOT `catalog_variant_id` + `placements`. Mixing these will produce a 400 error.
- **Creating Printful order as draft without confirming:** The v1 API creates orders as drafts by default. They must be confirmed via `POST /orders/{id}/confirm` to actually enter production. The existing scaffold does NOT call the confirm endpoint — this is a bug.
- **Shipping address fields mismatch:** Stripe uses `postal_code` and `state`. Printful v1 uses `zip` and `state_code`. The existing mapping in `create_printful_order()` is correct — don't change it.
- **Webhooks received before DB migration:** If the Printful webhook fires before the `tracking_url`/`tracking_number` columns are added, `UPDATE orders SET tracking_url = ...` will fail silently. Always migrate DB before registering webhooks.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead |
|---------|-------------|-------------|
| HMAC signature verification for Stripe | Custom HMAC comparison | `stripe.Webhook.construct_event()` (already used) |
| Async email sending | SMTP client | Raw `httpx` POST to `https://api.resend.com/emails` (established pattern) |
| Order ID generation | Sequential IDs | `uuid.uuid4()` (already used in `create_order()`) |
| Webhook deduplication | Custom set/cache | `printful_events_processed` SQLite table (replicate `stripe_events_processed` pattern) |
| Stripe test card numbers | Generating test cards | Use `4242424242424242`, exp `12/26`, CVC `123` — standard Stripe test card |

---

## Common Pitfalls

### Pitfall 1: design_id in payment_intent metadata vs session metadata

**What goes wrong:** `create_product_checkout()` currently puts `variant_id` in `payment_intent_data.metadata` but NOT in session-level `metadata`. In the webhook handler, `session.get("metadata")` returns session metadata, NOT payment intent metadata. If `design_id` is placed in `payment_intent_data.metadata`, the webhook handler can't access it without an extra Stripe API roundtrip.

**Why it happens:** The existing code already makes this mistake with `variant_id` — it's in `payment_intent_data.metadata` only.

**How to avoid:** Put `design_id` AND `variant_id` in session-level `metadata` (the `metadata={}` kwarg directly on `Session.create_async()`). Keep payment_intent_data.metadata if needed for other purposes.

**Warning signs:** Webhook handler logs "missing design_id" even though it was set in checkout creation.

### Pitfall 2: Printful order stuck in draft state

**What goes wrong:** Printful creates orders as drafts by default. `create_printful_order()` POSTs to `/orders` and gets back a Printful order ID, but the order sits in draft and is never fulfilled. The existing scaffold does not call the confirm endpoint.

**Why it happens:** Printful separates creation from confirmation for cases where you want to review orders before charging. The API returns 200 even for draft creation.

**How to avoid:** After `POST /orders` returns a valid ID, immediately call `POST https://api.printful.com/orders/{printful_id}/confirm`. Check the response status. If confirmation fails, log the error — the Order Agent in Phase 5 handles retries.

**Warning signs:** Printful dashboard shows orders in "draft" state, webhooks never fire.

### Pitfall 3: Design image URL not publicly accessible

**What goes wrong:** Printful's API downloads the print file from the URL you provide. If the URL is `localhost:8001/designs/...`, Printful's servers can't reach it, and the order will fail with a file download error.

**Why it happens:** During development, the app runs locally. The `/designs` static mount in `main.py` serves files at `http://localhost:8001/designs/...` — only accessible from the same machine.

**How to avoid:** In development, use ngrok or a similar tunnel: `ngrok http 8001`, then use the ngrok URL as the base for design images. In production, `https://meatheadgear.com/designs/{user_id}/{design_id}.png` works fine.

**Implementation:** Add `BASE_URL` to config settings. `create_printful_order()` constructs `design_image_url` from `BASE_URL + /designs/` + relative path from `designs.image_path`.

**Warning signs:** Printful order created (returns ID) but transitions to "draft" with a file error, or the order item shows "file missing" in the Printful dashboard.

### Pitfall 4: Stripe `shipping_details` field location varies by API version

**What goes wrong:** Newer Stripe API versions place `shipping_details` under `collected_information.shipping_details` rather than at the top level of the session object. This breaks extraction.

**Why it happens:** Stripe deprecated top-level `shipping_details` in newer API versions in favor of the `collected_information` wrapper.

**How to avoid:** Try both locations in the webhook handler:
```python
shipping = session.get("shipping_details") or \
            session.get("collected_information", {}).get("shipping_details", {})
```

**Warning signs:** `shipping_name` always empty in newly created orders.

### Pitfall 5: Printful webhook idempotency without unique event IDs

**What goes wrong:** Unlike Stripe which includes a unique `event_id` per webhook call, Printful v1 webhooks do NOT include a globally unique event ID. Using order ID alone as dedup key causes issues if multiple `order_updated` events fire for the same order.

**Why it happens:** Printful sends multiple `order_updated` events as an order moves through statuses — each with the same order ID.

**How to avoid:** Use a composite key: `f"{event_type}:{external_id}:{status}"` for `order_updated`, or `f"package_shipped:{external_id}:{tracking_number}"` for `package_shipped`. This allows multiple status transitions while preventing true duplicates.

**Warning signs:** Only the first `order_updated` event processed; subsequent status changes ignored.

### Pitfall 6: `stripe` missing from requirements.txt

**What goes wrong:** `stripe` is imported in `stripe_service.py` but is NOT in `apps/meatheadgear/requirements.txt`. Fresh installs fail with `ModuleNotFoundError: No module named 'stripe'`.

**How to avoid:** Add `stripe>=11.0.0` to `requirements.txt` in Wave 0.

---

## Code Examples

### Stripe Checkout Session with Shipping Collection

```python
# Source: docs.stripe.com/payments/collect-addresses (HIGH confidence)
session = await stripe.checkout.Session.create_async(
    mode="payment",
    line_items=[{
        "price_data": {
            "currency": "usd",
            "unit_amount": retail_cents,
            "product_data": {"name": product_name},
        },
        "quantity": 1,
    }],
    shipping_address_collection={
        "allowed_countries": ["US"],
    },
    metadata={
        "user_id": str(user_id),
        "type": "product_purchase",
        "variant_id": str(variant_id),
        "design_id": design_id,          # NEW
    },
    success_url=success_url,
    cancel_url=cancel_url,
)
```

### Printful Order Confirm (Missing from Current Code)

```python
# After POST /orders returns a valid printful_id:
async with httpx.AsyncClient(timeout=30.0) as client:
    confirm_resp = await client.post(
        f"https://api.printful.com/orders/{printful_id}/confirm",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    if confirm_resp.status_code not in (200, 201):
        logger.error("Printful order confirm failed: %s", confirm_resp.text)
        # Don't return None — order is created (draft), log error for Phase 5 agent
```

### Printful Webhook Handler Skeleton

```python
# routers/printful_webhook.py
@router.post("/webhook")
async def printful_webhook(request: Request) -> dict:
    payload = await request.body()
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event_type = data.get("type", "")
    order_data = data.get("data", {}).get("order", {})
    external_id = order_data.get("external_id", "")

    if not external_id:
        return {"status": "ignored", "reason": "no external_id"}

    # Idempotency key varies by event type
    if event_type == "package_shipped":
        shipment = data.get("data", {}).get("shipment", {})
        tracking_number = shipment.get("tracking_number", "")
        idem_key = f"package_shipped:{external_id}:{tracking_number}"
    else:
        order_status = order_data.get("status", "")
        idem_key = f"{event_type}:{external_id}:{order_status}"

    async with aiosqlite.connect(str(database.DB_PATH)) as db:
        cursor = await db.execute(
            "SELECT 1 FROM printful_events_processed WHERE event_key = ?",
            (idem_key,),
        )
        if await cursor.fetchone():
            return {"status": "already_processed"}

        if event_type == "order_updated":
            await _handle_order_updated(db, external_id, order_data)
        elif event_type == "package_shipped":
            await _handle_package_shipped(db, external_id, shipment)

        await db.execute(
            "INSERT INTO printful_events_processed (event_key, event_type) VALUES (?, ?)",
            (idem_key, event_type),
        )
        await db.commit()

    return {"status": "processed"}
```

### Resend Email via httpx (Established Pattern)

```python
# Source: established pattern in services/order_service.py (HIGH confidence — existing code)
async with httpx.AsyncClient(timeout=15.0) as client:
    resp = await client.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "from": "MeatheadGear <orders@meatheadgear.com>",
            "to": [user_email],
            "subject": f"Your order is confirmed — #{order['id'][:8].upper()}",
            "html": _order_confirmation_html(order, product_name, thumbnail_url),
        },
    )
```

---

## Runtime State Inventory

This phase introduces new runtime state (Printful webhook endpoint registration) but is not a rename/refactor phase. The relevant inventory:

| Category | Items | Action Required |
|----------|-------|------------------|
| Stored data | SQLite `orders` table — needs 2 new columns | ALTER TABLE migration in `database.py` init_db() |
| Stored data | New `printful_events_processed` table | CREATE TABLE IF NOT EXISTS in WALLET_SCHEMA_SQL or new model file |
| Live service config | Printful webhook URL — must be registered via Printful dashboard API settings | Manual step or POST to `/webhooks` endpoint after deployment |
| Live service config | Stripe webhook endpoint — existing, no change needed | None |
| Secrets/env vars | `PRINTFUL_WEBHOOK_SECRET` — may or may not exist; Printful v1 may not use one | Add to config.py with empty default; log warning if not set |
| Build artifacts | None | None |

**Webhook registration:** The Printful webhook URL must be registered in the Printful dashboard (or via their API) before events will arrive. This is a one-time manual setup step. The URL to register is `https://{domain}/api/printful/webhook`.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.x | Runtime | ✓ | 3.14.3 | — |
| pip | Package install | ✓ | 25.3 | — |
| `stripe` SDK | `stripe_service.py` | ✗ (not in requirements.txt) | — | Must install |
| Stripe API key (test mode) | Stripe Checkout | Unknown | — | Dev: use Stripe test mode keys |
| Printful API key | Printful order creation | Unknown (listed as blocker in STATE.md) | — | Orders skipped gracefully (existing pattern) |
| Resend API key | Confirmation email | Unknown (listed as blocker) | — | Email skipped gracefully (existing pattern) |
| ngrok or public URL | Printful can download design images | Unknown | — | Register webhook once deployed |
| SQLite (aiosqlite) | All data persistence | ✓ | >=0.20.0 | — |

**Missing dependencies with no fallback:**
- `stripe` package — must add to `requirements.txt`

**Missing dependencies with fallback:**
- Stripe API key: graceful degradation already coded (raises ValueError at call time)
- Printful API key: graceful degradation already coded (logs warning, returns None)
- Resend API key: graceful degradation already coded (logs info, returns False)

---

## Validation Architecture

`nyquist_validation` is enabled in `.planning/config.json`.

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest + pytest-asyncio |
| Config file | `pyproject.toml` (root) — `asyncio_mode = "auto"` |
| Quick run command | `python -m pytest apps/meatheadgear/tests/ -x -q` |
| Full suite command | `python -m pytest apps/meatheadgear/tests/ -v` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| ORD-01 | `handleProceedToCheckout()` submits correct payload | Manual (browser) | — | N/A — frontend |
| ORD-02 | `create_product_checkout()` includes `shipping_address_collection` + `design_id` in metadata | unit | `pytest apps/meatheadgear/tests/test_stripe_service.py -x -q` | ✅ (extend) |
| ORD-02 | Stripe Checkout webhook extracts `shipping_details` and saves to order | unit | `pytest apps/meatheadgear/tests/test_stripe_service.py -x -q` | ✅ (extend) |
| ORD-03 | `create_printful_order()` posts correct payload + confirms order | unit | `pytest apps/meatheadgear/tests/test_order_service.py -x -q` | ❌ Wave 0 |
| ORD-03 | `_handle_checkout_completed()` creates order + Printful order + email on `product_purchase` | integration | `pytest apps/meatheadgear/tests/test_stripe_service.py -x -q` | ✅ (extend) |
| ORD-04 | `send_order_confirmation()` POSTs branded HTML to Resend | unit | `pytest apps/meatheadgear/tests/test_order_service.py -x -q` | ❌ Wave 0 |
| ORD-05 | Orders list shows correct status badges + tracking link | Manual (browser) | — | N/A — frontend |
| ORD-06 | Printful webhook receiver processes `order_updated` with idempotency | unit | `pytest apps/meatheadgear/tests/test_printful_webhook.py -x -q` | ❌ Wave 0 |
| ORD-06 | Printful webhook deduplicates duplicate events | unit | `pytest apps/meatheadgear/tests/test_printful_webhook.py -x -q` | ❌ Wave 0 |
| ORD-07 | `package_shipped` webhook triggers shipping email with tracking | unit | `pytest apps/meatheadgear/tests/test_printful_webhook.py -x -q` | ❌ Wave 0 |
| ORD-07 | `send_shipping_confirmation()` POSTs branded HTML with tracking URL | unit | `pytest apps/meatheadgear/tests/test_order_service.py -x -q` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `python -m pytest apps/meatheadgear/tests/ -x -q`
- **Per wave merge:** `python -m pytest apps/meatheadgear/tests/ -v`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `apps/meatheadgear/tests/test_order_service.py` — covers ORD-03, ORD-04, ORD-07
- [ ] `apps/meatheadgear/tests/test_printful_webhook.py` — covers ORD-06, ORD-07

*(Existing: `test_stripe_service.py` covers ORD-02, ORD-03 integration — extend, don't replace.)*

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Printful v1 `files[{url}]` for print files | Printful v2 `placements[{placement, technique, layers[{type, url}]}]` | 2023 (v2 beta), 2025 (front_large replaces front) | v2 has more structured design placement; `front_large` required for full print area from May 2025 |
| Stripe `shipping_details` at session root | Newer versions: `collected_information.shipping_details` | 2024 Stripe API update | Must check both locations in webhook handler |

**Deprecated/outdated:**
- `front` placement in Printful v2: Replaced by `front_large` as of May 17, 2025. Only relevant if using v2 API for orders.

---

## Open Questions

1. **Printful webhook signature mechanism**
   - What we know: v1 does not document HMAC verification; v2 mentions "request signing" without specifics
   - What's unclear: Whether Printful v1 sends any signature header at all
   - Recommendation: Implement without signature verification for now; use IP allowlist validation as alternative security layer. Revisit when Printful publishes v1 signing documentation or when migrating to v2.

2. **Printful API version for order creation**
   - What we know: v1 works with existing scaffold; v2 requires different payload structure with `placements`/`layers`; `front_large` needed from May 2025
   - What's unclear: Whether the API key issued will work with both versions; v1 deprecation timeline
   - Recommendation: Use v1 (`https://api.printful.com/orders`) for Phase 3 since the scaffold is written. Flag migration to v2 as a Phase 5 item.

3. **`selectedSize` / `selectedColor` state in frontend**
   - What we know: `handleProceedToCheckout()` needs these values but they're not in `state`
   - What's unclear: At what point in the design studio flow the user picks size/color (before or after canvas)
   - Recommendation: Add `state.selectedSize` and `state.selectedColor` and populate them from the product variant selection UI in the design studio; default to first available variant if not set.

4. **Design image path vs URL for Printful**
   - What we know: Designs are stored at `.data/designs/{user_id}/{design_id}.png` and served at `/designs/{user_id}/{design_id}.png` via FastAPI static mount; `image_path` column in `designs` table stores the relative path
   - What's unclear: Whether `image_path` stores the full path or relative path, and whether the upscaled or original image should be sent to Printful
   - Recommendation: Add `BASE_URL` env var to config (defaults to `http://localhost:8001` for dev). Construct URL as `f"{settings.base_url}/designs/{user_id}/{design_id}.png"`. Use `upscaled_url` if available (it's the print-ready resolution), falling back to `image_url`.

---

## Project Constraints (from CLAUDE.md)

The following CLAUDE.md directives apply to this phase:

| Directive | Application |
|-----------|-------------|
| All I/O is async — never blocking | All new `httpx` calls must use `async with httpx.AsyncClient()` |
| Raw SQL via aiosqlite (no ORM) | New tracking columns: `ALTER TABLE ... ADD COLUMN` in try/except |
| Frozen dataclass Settings pattern | `printful_webhook_secret` and `base_url` added to `Settings` with defaults |
| Graceful degradation — missing keys never crash | Printful key missing: log + return None; Resend key missing: log + return False |
| Plugin/tool architecture | Phase adds a new FastAPI router (`printful_webhook.py`) + extends existing services |
| GSD workflow — no direct repo edits outside GSD | All edits via execute-phase |
| Test standards: every new module needs a test file | `test_order_service.py` and `test_printful_webhook.py` required |
| Run `make format && make lint` after changes | Enforce via Nyquist sampling |
| Security: ALWAYS validate file paths through `sandbox.resolve_path()` | N/A — MeatheadGear app does not use Agent42 sandbox |
| jcodemunch: `get_file_outline` before modifying files | Pre-read `stripe_service.py`, `order_service.py`, `printful.py`, `checkout.py` |

---

## Sources

### Primary (HIGH confidence)
- Stripe API reference — `docs.stripe.com/api/checkout/sessions/object` — `shipping_details` structure in `collected_information`
- Stripe Collect Addresses docs — `docs.stripe.com/payments/collect-addresses` — `shipping_address_collection` parameter
- Existing codebase — `apps/meatheadgear/services/stripe_service.py`, `order_service.py`, `printful.py`, `config.py`, `database.py`, `models_wallet.py` — all patterns verified by direct code read
- Resend API — pattern verified in existing `send_order_confirmation()` using `httpx.POST` to `https://api.resend.com/emails`

### Secondary (MEDIUM confidence)
- Printful API v1 order creation payload — multiple community sources + pyPrintful wrapper confirm `{"recipient": {...}, "items": [{"variant_id": ..., "files": [{...}]}]}` format
- Printful API v2 order structure — `developers.printful.com/docs/v2-beta/` fetched — `placements`/`layers` confirmed
- Printful v1 webhook payload structure — derived from Printful docs event type listing + community integrations
- Stripe idempotency pattern — existing `stripe_events_processed` table in `models_wallet.py` — replicated for Printful

### Tertiary (LOW confidence)
- Printful v1 webhook signature — no official documentation found; likely no HMAC verification on v1
- Printful `package_shipped` exact field names (`tracking_number`, `tracking_url`, `service`) — derived from community examples; not verified against official payload schema

---

## Metadata

**Confidence breakdown:**
- Stripe integration: HIGH — official docs + existing working code
- Resend email: HIGH — established pattern in existing code
- Printful order creation (v1): MEDIUM — payload format verified by multiple sources; confirm step needs testing
- Printful webhook structure: LOW — v1 payload and signature are underdocumented; verify by registering a real webhook and inspecting payloads
- Frontend changes: HIGH — direct code inspection of existing stubs

**Research date:** 2026-03-25
**Valid until:** 2026-06-25 (stable APIs; Printful v1 deprecation notice would shorten this)
