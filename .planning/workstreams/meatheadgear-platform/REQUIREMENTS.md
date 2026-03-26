# Requirements: MeatheadGear Platform

**Defined:** 2026-03-20
**Core Value:** A customer can go from "I want a shirt with an angry gorilla" to checkout in under 3 minutes, and AI agents handle everything that follows without human intervention.

## v1 Requirements

### Authentication

- [x] **AUTH-01**: Customer can sign up with email and password
- [x] **AUTH-02**: Customer can log in and receive a JWT session token
- [x] **AUTH-03**: Customer session persists across browser refresh
- [x] **AUTH-04**: Customer can reset password via email link (Resend)

### Catalog

- [x] **CAT-01**: Product catalog synced from Printful API (t-shirts, hoodies, leggings, shorts, hats, bags)
- [x] **CAT-02**: Each product shows available sizes, colors, and base price
- [ ] **CAT-03**: Product detail page shows high-quality product photos from Printful
- [x] **CAT-04**: Retail prices calculated to maintain ≥30% gross margin after Printful + Stripe fees

### Design Studio

- [ ] **DES-01**: Customer can type a design prompt and generate an image via AI (Flux 1.1 Pro via fal.ai)
- [ ] **DES-02**: If prompt contains text/slogans, route to Ideogram v3 for superior text rendering
- [ ] **DES-03**: Generated image has background automatically removed (BiRefNet via fal.ai)
- [ ] **DES-04**: Image is upscaled to 300 DPI print-ready resolution (Real-ESRGAN via fal.ai)
- [ ] **DES-05**: Customer can place design on a Fabric.js canvas showing selected product
- [ ] **DES-06**: Customer can resize, reposition, and rotate design on the canvas
- [ ] **DES-07**: Canvas generates a photorealistic mockup via Printful Mockup Generator API
- [ ] **DES-08**: Customer can upload their own PNG/SVG instead of AI generation
- [ ] **DES-09**: Design is saved to customer account for reuse

### Checkout & Orders

- [x] **ORD-01**: Customer selects product, size, color and adds to cart
- [x] **ORD-02**: Stripe checkout flow with card payment
- [x] **ORD-03**: On successful payment, order automatically created in Printful
- [x] **ORD-04**: Customer receives order confirmation email via Resend
- [x] **ORD-05**: Customer can view order status (processing → printed → shipped → delivered)
- [x] **ORD-06**: Printful fulfillment webhooks update order status in real-time
- [x] **ORD-07**: Customer receives shipping confirmation email with tracking number

### Agent Infrastructure

- [ ] **INF-01**: Webhook receiver endpoints for Stripe and Printful events
- [ ] **INF-02**: Redis report bus — each agent writes daily JSON report to keyed hash
- [ ] **INF-03**: Agent scheduler — runs agent decision loops on configurable intervals
- [ ] **INF-04**: Escalation framework — dollar-threshold routing (<$75 auto, $75–$500 notify, >$500 hold)
- [ ] **INF-05**: Agent action log — every autonomous action recorded with timestamp and rationale

### Order & Operations Agent

- [ ] **AGT-01**: Detects failed Printful orders and auto-retries or flags for review
- [ ] **AGT-02**: Monitors fulfillment SLA — alerts if order >5 days without ship confirmation
- [ ] **AGT-03**: Handles Printful stock-out events by suggesting substitute product or notifying customer

### Finance Agent

- [ ] **AGT-04**: Calculates daily P&L from Stripe revenue minus Printful COGS minus Stripe fees
- [ ] **AGT-05**: Writes daily finance report to Redis (revenue, orders, avg order value, margin %)
- [ ] **AGT-06**: Alerts CEO agent if daily margin drops below 25%

### Support Agent

- [ ] **AGT-07**: Parses inbound customer emails via Resend webhooks
- [ ] **AGT-08**: Handles order status inquiries automatically (looks up order, replies with status)
- [ ] **AGT-09**: Processes refund requests under $75 automatically via Stripe
- [ ] **AGT-10**: Handles Printful replacement requests for damaged/wrong items

### CEO Agent

- [ ] **AGT-11**: Reads all agent daily reports from Redis and generates consolidated daily digest
- [ ] **AGT-12**: Routes escalations to human (email via Resend) for >$500 decisions
- [ ] **AGT-13**: Posts weekly business summary to Agent42 dashboard

### Marketing Agent

- [ ] **AGT-14**: Klaviyo: triggers abandoned cart email sequence (2h, 24h, 72h) when cart abandoned
- [ ] **AGT-15**: Klaviyo: sends post-purchase follow-up 7 days after delivery (review request + upsell)
- [ ] **AGT-16**: Upload-Post.com: posts 3x/week to Instagram and TikTok with product mockups
- [ ] **AGT-17**: Finance-aware: promotes discounts only when Finance Agent reports strong margins

## v2 Requirements

### Review & Reputation Agent

- **REV-01**: Monitors new product reviews, flags negative reviews for CEO digest
- **REV-02**: Auto-responds to positive reviews with personalized thank-you
- **REV-03**: Extracts product feedback from reviews to surface to CEO agent weekly

### Inventory & Catalog Agent

- **INV-01**: Monitors Printful catalog for new products in gym wear category, adds to catalog
- **INV-02**: Detects discontinued products and removes from storefront automatically
- **INV-03**: Tracks bestsellers and surfaces reorder/restock recommendations

### Advanced Marketing

- **MKT-01**: SEO blog post generation (weekly, gym tips + product features)
- **MKT-02**: Email segmentation by purchase history (leggings buyer vs t-shirt buyer)
- **MKT-03**: Dynamic pricing — small discount trigger when inventory has slow-moving SKUs

### Design Features

- **DES-10**: Design templates library — pre-made edgy gym templates customer can customize
- **DES-11**: LoRA fine-tuning on MeatheadGear brand style for consistent AI generation

## Out of Scope

| Feature | Reason |
|---------|--------|
| Shopify / WooCommerce | Building as Agent42 app — full control, no platform fees |
| Own inventory / warehousing | Pure POD model — zero inventory risk |
| Mobile app (iOS/Android) | Web-first, PWA sufficient for v1 |
| Multi-currency / international | US-first for launch simplicity |
| Midjourney for design gen | No official API — ToS violation via wrappers |
| Recraft v3 vector output | Only needed for screen printing, not v1 DTG |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| AUTH-01–04 | Phase 1 | Verified |
| CAT-01–04 | Phase 1 | Verified |
| DES-01–09 | Phase 2 | Verified (human UAT pending) |
| ORD-01–04 | Phase 3 Plan 01 | Backend implemented |
| ORD-05 | Phase 3 Plan 03 | Implemented — 7-color status badges + tracking link UI |
| ORD-06–07 | Phase 3 Plan 02 | Implemented — Printful webhook receiver with idempotency, tracking persistence, shipping email |
| INF-01–05 | Phase 4 | Pending |
| AGT-01–03 | Phase 5 | Pending |
| AGT-04–06 | Phase 5 | Pending |
| AGT-07–10 | Phase 6 | Pending |
| AGT-11–13 | Phase 6 | Pending |
| AGT-14–17 | Phase 7 | Pending |

**Coverage:**
- v1 requirements: 43 total
- Mapped to phases: 43
- Unmapped: 0 ✓

---
*Requirements defined: 2026-03-20*
*Last updated: 2026-03-25 after Phase 03 Plan 02 completion (all Phase 03 plans complete)*
