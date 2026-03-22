# Roadmap: MeatheadGear

## Overview

MeatheadGear is built in four phases that follow the natural dependency chain: establish
the transactional foundation first (database schema + Stripe payments), then build the
core user value (AI design generation + purchase flow + chat UI), then add the exclusivity
system that turns designs into owned assets, and finally deploy the autonomous agent team
that operates the business 24/7. Each phase delivers a coherent, independently-verifiable
capability. Agents are last — they need real sales data and real customers to be useful.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Foundation + Payments** - Extended database schema, wallet credits, and Stripe checkout
- [ ] **Phase 2: Design + Commerce** - AI design generation pipeline, purchase flow, and chat UI
- [ ] **Phase 3: Exclusivity System** - Lock It / Own It tiers with fuzzy prompt blocking
- [ ] **Phase 4: Autonomous Agent Team + Creator Catalog** - 8-agent management team and Sell It creator tier

## Phase Details

### Phase 1: Foundation + Payments
**Goal**: Users can fund a wallet and purchase products — the transactional layer is live and correct
**Depends on**: Nothing (first phase)
**Requirements**: DB-01, DB-02, DB-03, DB-04, PAY-01, PAY-02, PAY-03, PAY-04, PAY-05, PAY-06, PAY-07, PAY-08
**Success Criteria** (what must be TRUE):
  1. User receives 5 free design credits on account creation and sees the balance in the navigation bar at all times
  2. User can deposit money into their wallet via Stripe Checkout and the credit balance updates correctly after payment
  3. User can purchase a product via Stripe Checkout and receives a purchase credit award to their wallet
  4. Stripe webhook processing is idempotent — replaying the same event does not double-credit the wallet
  5. All schema extensions (wallet, designs, exclusivity, agent_events) exist with WAL mode enabled; concurrent writes do not corrupt data
**Plans:** 3 plans
Plans:
- [ ] 01-01-PLAN.md — Database schema extension, WAL mode, config, models
- [ ] 01-02-PLAN.md — WalletService with atomic credit/debit, wallet router, signup credits
- [ ] 01-03-PLAN.md — Stripe Checkout integration, idempotent webhook handler, order service

### Phase 2: Design + Commerce
**Goal**: Users can generate a custom AI design via chat, preview it on a garment, and buy it — the core product loop is complete
**Depends on**: Phase 1
**Requirements**: DES-01, DES-02, DES-03, DES-04, DES-05, DES-06, DES-07, DES-08, DES-09, DES-10, DES-11, DES-12, DES-13, PUR-01, PUR-02, PUR-03, PUR-04, PUR-05, UI-01, UI-02, UI-03, UI-04, UI-05, UI-06, UI-07, UI-08
**Success Criteria** (what must be TRUE):
  1. User can describe a design in the chat interface, select a garment and style preset, and see an AI-generated mockup on the garment
  2. User can refine the design conversationally ("make the skull bigger", "try grunge style") and see an updated mockup
  3. Free-tier previews are watermarked; a credit is deducted from the wallet before generation begins; generation failures show a clear error with a retry button
  4. User can add the generated design to cart, select size and color, and complete a Stripe checkout that creates a Printful order
  5. User receives an order confirmation email and can view the order in their account page; a wallet credit award is issued post-purchase
**Plans**: TBD

### Phase 3: Exclusivity System
**Goal**: Users can own their designs — Lock It and Own It tiers are purchasable and enforced, no other user can reproduce an owned design
**Depends on**: Phase 2
**Requirements**: EXC-01, EXC-02, EXC-03, EXC-04, EXC-05, EXC-06, EXC-07, EXC-08, EXC-09, EXC-10
**Success Criteria** (what must be TRUE):
  1. User can add "Lock It" (+$14.99) at checkout; the design shows a "1 of 1" badge and the exact prompt+seed combination is blocked for all other users
  2. User can add "Own It" (+$34.99) at checkout; semantically similar prompts (cosine similarity above threshold) are blocked and the user can download the hi-res design file
  3. User can view all owned and locked designs on the "My Designs" account page
  4. Exclusivity upsell is shown in the cart and on the product detail page
  5. Gray-zone similarity scores (0.88–0.96) are routed to a review queue rather than auto-blocked
**Plans**: TBD

### Phase 4: Autonomous Agent Team + Creator Catalog
**Goal**: The business runs autonomously — 8 agents operate pricing, support, marketing, design curation, and self-improvement 24/7; creators can submit designs and earn revenue share
**Depends on**: Phase 3
**Requirements**: AGT-01, AGT-02, AGT-03, AGT-04, AGT-05, AGT-06, AGT-07, AGT-08, AGT-09, AGT-10, AGT-11, AGT-12, AGT-13, AGT-14, CRE-01, CRE-02, CRE-03, CRE-04, CRE-05
**Success Criteria** (what must be TRUE):
  1. Owner Agent coordinates all sub-agents via AgentBus; no agent-to-agent direct messaging; circuit breakers pause runaway message pairs
  2. Support Agent handles customer tickets and processes refunds within policy without human intervention; Sales Agent adjusts pricing within the ±15% weekly bound with the hard floor enforced
  3. Marketing Agent posts social media content autonomously (with approval gate for first 30 days); Research Agent monitors competitors and feeds data to Owner Agent
  4. Web/Brand Agent proposes and deploys UI improvements through the branch → test → review → deploy pipeline; Protected Zones prevent modifications to payment, auth, and schema code
  5. User can submit a design to the MHG public catalog ("Sell It") and earn 15% revenue share on sales; Stripe Connect Express handles creator payouts with KYC verification
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Foundation + Payments | 0/3 | Planning complete | - |
| 2. Design + Commerce | 0/TBD | Not started | - |
| 3. Exclusivity System | 0/TBD | Not started | - |
| 4. Autonomous Agent Team + Creator Catalog | 0/TBD | Not started | - |
