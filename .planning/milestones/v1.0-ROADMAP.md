# Roadmap: MeatheadGear Platform

## Overview

Build a fully autonomous AI-run gym apparel e-commerce platform as an Agent42 app. Customers generate AI designs and check out; 7 AI agents run the business on full autopilot. Phases are ordered so each delivers a working, testable slice — storefront first, agents last.

## Phases

- [ ] **Phase 1: Store Foundation** — FastAPI app, auth, Printful catalog sync, product browsing UI
- [ ] **Phase 2: Design Studio** — AI generation (Flux + Ideogram), canvas editor, mockup preview
- [ ] **Phase 3: Checkout & Fulfillment** — Stripe payments, Printful order creation, order tracking
- [x] **Phase 4: Agent Infrastructure** — Webhook receivers, Redis report bus, scheduler, escalation (completed 2026-03-21)
- [ ] **Phase 5: Order & Finance Agents** — Fulfillment loop, P&L tracking, daily reports
- [ ] **Phase 6: Support & CEO Agents** — Inbound email handling, refunds, daily business digest
- [ ] **Phase 7: Marketing Agent** — Klaviyo abandoned cart, post-purchase flows, social media posting

## Phase Details

### Phase 1: Store Foundation
**Goal**: Working storefront — customers can browse gym wear products with real Printful catalog data
**Depends on**: Nothing (first phase)
**Requirements**: AUTH-01–04, CAT-01–04
**Plans:** 3/4 plans executed

Plans:
- [x] 01-01-PLAN.md — App skeleton: FastAPI, config, database, models, Agent42 registration
- [x] 01-02-PLAN.md — Authentication: register, login, JWT sessions, password reset
- [x] 01-03-PLAN.md — Printful catalog sync: API client, pricing engine, product endpoints
- [x] 01-04-PLAN.md — Frontend: product grid, product detail, auth modal, brand styling

**Success Criteria:**
  1. Customer can sign up, log in, and stay logged in across refresh
  2. Product catalog displays real Printful products (t-shirts, hoodies, leggings) with photos, sizes, colors, prices
  3. Retail prices are calculated at >=30% margin over Printful base cost
  4. App runs under Agent42 app system at `localhost:8001` (or configured port)

### Phase 2: Design Studio
**Goal**: Customer types a prompt -> AI generates design -> they place it on a product -> see a realistic mockup
**Depends on**: Phase 1 (needs product catalog)
**Requirements**: DES-01–09
**Success Criteria:**
  1. Customer types "angry gorilla lifting weights" -> Flux 1.1 generates a graphic in <15s
  2. Prompt with slogans ("NO DAYS OFF") routes to Ideogram v3 with legible text in image
  3. Background is automatically removed and image upscaled to print-ready resolution
  4. Fabric.js canvas lets customer place, resize, rotate design on product
  5. Dynamic Mockups API returns photorealistic product photo with design applied
  6. Customer can upload their own design as alternative to AI generation

### Phase 3: Checkout & Fulfillment
**Goal**: Customer can pay and their order flows automatically to Printful for printing and shipping
**Depends on**: Phase 2 (needs design + product selection)
**Requirements**: ORD-01–07
**Success Criteria:**
  1. Stripe checkout completes with real (test mode) card
  2. Printful order created automatically within 60s of payment
  3. Customer receives order confirmation email (Resend) within 2 minutes
  4. Order status page shows real-time fulfillment state from Printful webhooks
  5. Shipping confirmation email sent with tracking link when Printful ships

### Phase 4: Agent Infrastructure
**Goal**: The plumbing that lets autonomous agents receive events, communicate, and take actions safely
**Depends on**: Phase 3 (needs live order/payment events)
**Requirements**: INF-01–05
**Success Criteria:**
  1. Stripe `payment_intent.succeeded` and `charge.refunded` webhooks received and verified
  2. Printful order status webhooks received and routed to correct agent handler
  3. Each agent can write a JSON report to Redis (keyed `agent:{name}:daily:{date}`)
  4. Agent scheduler triggers each agent's decision loop on configurable cron
  5. Every autonomous action logged to SQLite with timestamp, agent name, action type, amount, rationale

### Phase 5: Order & Finance Agents
**Goal**: Two agents running on autopilot — one managing fulfillment health, one tracking money
**Depends on**: Phase 4
**Requirements**: AGT-01–06
**Success Criteria:**
  1. Order Agent detects a failed Printful order and auto-retries within 30 minutes
  2. Order Agent flags any order >5 days unshipped in its daily Redis report
  3. Finance Agent calculates correct daily P&L from Stripe + Printful data
  4. Finance Agent writes daily report with: revenue, order count, avg order value, gross margin %
  5. Finance Agent alert fires (logged + CEO notified) when margin drops below 25%

### Phase 6: Support & CEO Agents
**Goal**: Customer emails handled automatically; CEO gets a daily briefing of the whole business
**Depends on**: Phase 5
**Requirements**: AGT-07–13
**Success Criteria:**
  1. Customer sends "where is my order?" email -> Support Agent replies with tracking info within 5 minutes
  2. Refund request under $75 -> Support Agent issues Stripe refund automatically, emails confirmation
  3. CEO Agent reads all agent Redis reports and generates a readable daily digest
  4. CEO Agent escalation email sent to human (Rick) for any decision >$500
  5. Weekly business summary visible on Agent42 dashboard

### Phase 7: Marketing Agent
**Goal**: Business promotes itself — abandoned carts recovered, customers followed up, social media posts going out
**Depends on**: Phase 6 (needs Finance Agent reports to gate spending decisions)
**Requirements**: AGT-14–17
**Success Criteria:**
  1. Cart abandoned -> Klaviyo sequence fires (2h, 24h, 72h) with product in cart
  2. Order delivered -> Klaviyo post-purchase email fires 7 days later with review request
  3. 3 social posts/week automatically published to Instagram + TikTok via Upload-Post.com
  4. Marketing Agent checks Finance report before running a promotion — skips if margin <28%

## Progress

| Phase | Plans | Status | Completed |
|-------|-------|--------|-----------|
| 1. Store Foundation | 3/4 | In Progress|  |
| 2. Design Studio | TBD | Not started | — |
| 3. Checkout & Fulfillment | TBD | Not started | — |
| 4. Agent Infrastructure | 2/2 | Complete   | 2026-03-21 |
| 5. Order & Finance Agents | TBD | Not started | — |
| 6. Support & CEO Agents | TBD | Not started | — |
| 7. Marketing Agent | TBD | Not started | — |

---
*Roadmap created: 2026-03-20*
*Workstream: meatheadgear-platform*
