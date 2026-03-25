# Phase 3: Checkout & Fulfillment - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-03-25
**Phase:** 03-checkout-fulfillment
**Areas discussed:** Cart & purchase flow, Shipping address, Order tracking UX, Email notifications

---

## Cart & Purchase Flow

| Option | Description | Selected |
|--------|-------------|----------|
| Buy Now (single-item) | Direct purchase from design studio, matches all existing code | ✓ |
| Shopping cart | Multi-item cart with add/remove, bundled Stripe checkout | |

**User's choice:** Buy Now (Recommended)
**Notes:** Entire codebase is single-item (one design_id + variant_id per order row). Core product is custom AI-generated designs — each unique to a session. Cart deferred to future phase.

**Key finding surfaced:** `create_product_checkout()` doesn't pass `design_id` through Stripe metadata, and webhook handler never creates orders for product purchases — only awards bonus credits. Must be fixed.

---

## Shipping Address

| Option | Description | Selected |
|--------|-------------|----------|
| Stripe Checkout built-in | Add `shipping_address_collection` param, Stripe handles validation + autocomplete | ✓ |
| Custom MHG form | Build 6+ form fields in vanilla JS before Stripe redirect | |
| Stripe Elements (embedded) | Different integration pattern from existing Checkout Sessions | |

**User's choice:** Stripe Checkout (Recommended)
**Notes:** US-only via `allowed_countries: ["US"]`. Address returned in webhook `shipping_details`. Avoids building custom form in vanilla JS frontend that has no form library.

---

## Order Tracking UX

| Option | Description | Selected |
|--------|-------------|----------|
| Enhanced status badges | Colored pills with 6 states, extends existing CSS classes | ✓ |
| Inline step indicator | Horizontal dots/steps within order row | |
| Expandable row + timeline | Click to expand, vertical timeline + tracking | |
| Dedicated order detail page | New SPA section like product-detail | |

**User's choice:** Enhanced badges (Recommended)
**Notes:** Dark minimal brand aesthetic. Extend existing 3-color `.order-status` classes to 6 states. Tracking link clickable when available. Timeline/detail page deferred to post-MVP.

---

## Email Notifications

| Option | Description | Selected |
|--------|-------------|----------|
| Branded inline-CSS HTML | Dark theme matching site, design thumbnail, product details | ✓ |
| Minimal styled HTML | Basic structure, no brand colors/fonts | |
| Plain text | Universal rendering, zero maintenance | |

**User's choice:** Branded HTML (Recommended)
**Notes:** Customers spending $30-55 expect polished emails. Two types: order confirmation + shipping confirmation. Python f-string templates with inline CSS, no Jinja2. Continue using raw httpx to Resend API.

---

## Claude's Discretion

- Printful webhook signature verification mechanism
- Exact Printful API v2 order creation payload format
- Status color mappings for new badge states
- Email template layout and content formatting
- Error handling for failed Printful orders

## Deferred Ideas

- Shopping cart (multi-item checkout) — future phase
- Dedicated order detail page with timeline — post-MVP
- Step-by-step visual progress indicator — post-MVP
- International shipping — v2
- Resend delivery/bounce monitoring — operational concern
