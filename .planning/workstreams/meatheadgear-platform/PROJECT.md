# MeatheadGear Platform

## What This Is

MeatheadGear is an autonomous AI-run gym apparel e-commerce platform living inside Agent42's app system. Customers visit meatheadgear.com, log in, generate custom designs using AI, place them on gym wear (t-shirts, hoodies, compression leggings, shorts, bags), and checkout — after which a team of 7 AI agents handles every aspect of the business on full autopilot: order fulfillment, customer support, marketing campaigns, financial reporting, and social media.

## Core Value

A customer can go from "I want a shirt with an angry gorilla" to checkout in under 3 minutes, and AI agents handle everything that follows without human intervention.

## Requirements

### Validated

- [x] Customer auth (sign up, log in, session persistence) — Validated in Phase 1
- [x] Product catalog synced from Printful (t-shirts, hoodies, leggings, hats, bags) — Validated in Phase 1
- [x] AI design generation: Flux 1.1 Pro for graphics, Ideogram v3 for text/slogans — Validated in Phase 2
- [x] Background removal + upscaling pipeline (fal.ai BiRefNet + Real-ESRGAN) — Validated in Phase 2
- [x] Fabric.js canvas editor: place design on product mockup, resize, position — Validated in Phase 2
- [x] Printful Mockup Generator API: render photorealistic product mockup from design — Validated in Phase 2
- [x] Stripe checkout: create payment intent, handle webhook, create Printful order — Validated in Phase 3
- [x] Order tracking: sync Printful fulfillment status to customer order page — Validated in Phase 3

### Active

- [ ] Agent infrastructure: registry, Redis report bus, webhook routing, scheduler
- [ ] Order Agent: Stripe→Printful→Resend confirmation loop
- [ ] Finance Agent: daily P&L, margin tracking, Stripe reconciliation
- [ ] Support Agent: Resend inbound email parsing, refund/replacement handling
- [ ] CEO Agent: daily digest from all agent reports, escalation routing
- [ ] Marketing Agent: Klaviyo campaigns + abandoned cart + Upload-Post social

### Out of Scope

- Shopify — building custom storefront (user wants it as Agent42 app)
- Own inventory / warehousing — pure print-on-demand model
- Mobile app — web-first
- Multi-currency / international shipping at launch — US-first
- Review/Reputation Agent — v2 (needs accumulated orders first)
- Inventory Agent advanced features — v2

## Context

- **App system**: Lives in `apps/meatheadgear/` as an Agent42-managed app
- **POD**: Printful primary (API v2, Growth plan), CustomCat for compression shorts
- **AI generation**: fal.ai as single vendor for Flux, Ideogram, BiRefNet, Real-ESRGAN (~$0.05/design)
- **Agents**: Event-driven via Stripe + Printful webhooks. Redis keyed report bus. No agent mesh.
- **Email**: Resend (transactional) + Klaviyo (marketing). Two services, different jobs.
- **Social**: Upload-Post.com for Instagram + TikTok autonomous posting
- **Escalation**: <$75 auto, $75–$500 execute+notify, >$500 human approval required
- **Domain**: meatheadgear.com (owned)
- **Brand**: Edgy, fun, "meaty" — gym-goers, powerlifters, bodybuilders

## Constraints

- **Tech Stack**: FastAPI + SQLite + React/Vanilla JS — matches Agent42 app conventions
- **Async I/O**: All I/O must be async (aiofiles, httpx) — Agent42 convention
- **Security**: Auth via JWT, Stripe webhooks verified by signature, no API keys in frontend
- **Autonomy**: Agents run on full autopilot — no human approval needed under $75 threshold
- **POD pricing**: Retail prices must maintain 30–40% gross margin after Printful + Stripe fees

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Printful as primary POD | Best API, quality, AOP leggings catalog, mockup API | — Pending |
| fal.ai for all AI generation | Single vendor for Flux+Ideogram+BiRefNet+ESRGAN, $0.05/design | — Pending |
| Custom storefront, not Shopify | User wants Agent42 app, full control, no platform fees | — Pending |
| Redis report bus for agents | Decoupled, no agent mesh, CEO reads all reports | — Pending |
| Resend + Klaviyo email split | Transactional vs marketing are different systems/flows | — Pending |
| Dollar-threshold escalation | Simple, auditable — <$75 auto, >$500 human | — Pending |

---
*Last updated: 2026-03-25 after Phase 03 completion*
