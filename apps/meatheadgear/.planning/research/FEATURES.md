# Feature Landscape: MeatheadGear

**Domain:** AI-powered POD apparel storefront with design exclusivity, digital wallet/credits, and autonomous AI agent management team
**Researched:** 2026-03-21
**Confidence:** HIGH (stack decisions already made; research validates and extends known domain)

---

## Domain Overview

MHG spans four distinct feature domains that interact tightly:

1. **AI Design Generation** — chat-driven image generation with mockup preview
2. **Design Exclusivity System** — NFT-free ownership tiers ("Lock It / Own It / Sell It")
3. **Digital Wallet + Credits** — in-store currency funded by Stripe, awarded on purchase
4. **Autonomous Agent Team** — 8 specialized agents running the business 24/7

Each domain has its own table stakes and differentiators. They are listed separately then synthesized at the end.

---

## Domain 1: AI Design Generation (Chat Interface + Mockup)

### Table Stakes

Features users expect from an AI-design-to-apparel flow. Missing any of these kills the experience.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Natural language prompt input | Every AI product uses text-to-image; this is the entry point | Low | Single textarea or chat bubble; clear placeholder copy is critical |
| Conversational refinement | Users expect "make it darker" / "add text" follow-ups; one-shot designs are rarely right | Medium | Requires prompt history context passed to generation API; not just new calls |
| Real-time mockup on garment | Users must see design on the actual shirt, not as a flat art file | Medium | Printful mockup API is async (webhook-based); must handle loading state gracefully |
| Garment selector before/during generation | User picks t-shirt vs hoodie vs tank before or immediately after generation | Low | Affects mockup template; garment determines print area constraints |
| Size/color variant selection | Ecommerce baseline — user needs to pick their size | Low | Already exists in existing storefront |
| Watermarked preview for free tier | Industry standard for freemium generative tools; prevents print-without-paying | Low | Watermark at generation time, not download time; must cover the printable region |
| Credit balance visible during session | User must know how many free generations remain before committing | Low | Shown persistently in nav or design UI — never hide this |
| Generation failure handling | APIs fail; timeouts happen; must not leave user on blank screen | Low | Retry button + clear error message; do not silently retry multiple times |
| Add to cart from design | After generation, direct path to purchase with design attached | Low | Design ID / asset URL must survive session into cart and checkout |

### Differentiators

Features that give MHG competitive advantage in the AI design space.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Multi-model pipeline (Ideogram / Recraft / GPT Image) | Different models excel at different styles; route to best model for the prompt type | High | Already decided (see PROJECT.md). Routing logic by style keyword or user style preference |
| Style presets for gym/fitness aesthetic | "Bold", "Grunge", "Motivational", "Skull/Edge" presets reduce blank-slate paralysis | Low | Essentially a prompt prefix library; very high conversion impact for non-creative users |
| Design history in session | "Go back to version 2" — users iterate non-linearly | Medium | Store last N generated assets per session; display as thumbnails |
| Prompt quality guidance | Real-time tips: "Add a mood, a subject, and a style for best results" | Low | Static helper text or simple character/keyword count feedback |
| Print-quality upscaling pipeline | POD requires 4500x5400 @ 300 DPI; generation models output 1024px max | Medium | Already decided: LetsEnhance/Claid.ai. Must happen before lock/purchase, not after |
| Background removal for vector designs | Clean PNG needed for most apparel placements | Medium | Can be Recraft V4 native or a post-processing step |

### Anti-Features

Deliberately exclude these from the AI design domain.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| Side-by-side model comparison UI | Adds cognitive load; most users don't know or care which model generated what | Route automatically; let users pick "style" not "model" |
| Technical generation parameters (CFG scale, steps, seed) exposed to users | Target audience is gym-goers, not Stable Diffusion power users | Expose seed internally only (for Lock It seed-blocking); never surface to user |
| Full design editor (move, resize, layer) | Scope creep; not a design tool, it's an apparel store | "Reposition" and "scale" via constrained sliders are fine; full canvas editor is not |
| Upload your own design (at launch) | Complicates IP ownership, exclusivity verification, and quality gating | Defer to post-PMF; AI-only is the brand position |

---

## Domain 2: Design Exclusivity System

### Table Stakes

Without these, the exclusivity system lacks credibility and cannot be enforced.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| "1 of 1" badge on locked designs (Lock It) | Visual proof of exclusivity on product page and order confirmation | Low | DB flag `is_locked = true`; display on product card and order email |
| Exact prompt + seed blocking after Lock It | Core promise: nobody else can generate the same design with same inputs | Medium | Store prompt hash + image generation seed at lock time; check on every new generation |
| Locked design visible on user's account page | User needs to see what they own; builds perceived value | Low | "My Designs" tab showing owned/locked designs |
| Lock activation before OR at purchase | Offering the add-on at checkout is the standard conversion point | Low | Upsell at cart/checkout; also accessible on product detail page |
| "1 of 1" language, not NFT/crypto language | Target audience is skeptical of Web3; plain language required | Low | "Only yours. Forever." — never "mint", "token", "blockchain" |

### Differentiators

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Fuzzy prompt matching (Own It tier) | Blocks semantically similar prompts, not just exact copies; genuine exclusivity | High | Cosine similarity on sentence embeddings at ~0.92 threshold. Most expensive feature to build correctly. Requires embedding storage + query on every generation |
| Hi-res download for Own It tier | User gets the actual asset file — tangible value beyond exclusivity | Low | Already generated by upscaling pipeline; just gate the download endpoint |
| Creator catalog submission (Sell It) | Users can earn from their designs; turns buyers into brand advocates | High | Requires creator payout via Stripe Connect; revenue tracking per design; quality review gate |
| Revenue share leaderboard / creator profile | Public attribution motivates catalog submissions | Low | Simple "Designed by [username]" on catalog items |
| Exclusivity history / transfer | If Own It was purchased, show when and by whom (anonymized) | Low | Builds scarcity credibility: "Locked 6 months ago" |

### Anti-Features

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| NFT/blockchain proof of ownership | Unnecessary complexity; alienates target audience; regulatory risk | Database ownership record + email confirmation is sufficient |
| Design resale marketplace | Opens IP disputes, fraud vectors, and support complexity | Out of scope (PROJECT.md confirms). Creator earns via catalog rev share only |
| Ownership expiry / rental model | Adds confusion; undermines "yours forever" value prop | Keep ownership permanent; subscription is for generation credits, not ownership renewal |
| Transferring exclusivity between accounts | Edge case; high support cost; low demand at launch | Explicitly decline at launch; revisit post-PMF |

---

## Domain 3: Digital Wallet + Credits System

### Table Stakes

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Credit balance displayed in UI | Users funded the wallet; they expect to see it prominently | Low | Show in nav + in design generation UI |
| 5 free credits on signup | Freemium standard; removes barrier to first experience | Low | Generated at account creation via DB migration / signup trigger |
| Wallet top-up via Stripe | Minimum $5 deposit; must feel simple and instant | Medium | Stripe PaymentIntent or Checkout; wallet balance updated via webhook on payment_intent.succeeded |
| Cost shown before generation | "This will use 1 credit ($0.75)" before pressing Generate | Low | Static display based on tier; not dynamic calculation per request |
| Credits awarded on purchase | Incentivizes repeat purchasing; rewards loyal customers | Medium | Trigger credit award in order fulfillment webhook; amount set by Sales Agent |
| Credits never expire | Avoids the resentment of expiring loyalty points | Low | No expiry TTL on credit rows; just a balance |
| Purchase history / credit ledger | User expects to see where credits came from and were spent | Low | Simple transaction log: awarded, spent, topped-up |

### Differentiators

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Credits as purchase reward (not just top-up) | Turns buyers into repeat design creators; closes the loop between purchase and creation | Medium | Pricing agent sets reward rate dynamically based on margin/AOV |
| Dynamic credit cost (priced by Sales Agent) | Pricing agent can respond to model costs, promotion periods | Low | Single configurable value in DB; agent updates it; user sees current cost |
| Credit bundles (e.g., 10 credits for $8) | Bulk discount incentivizes commitment; common in generative AI tools | Low | Add as a Stripe product; simple to add post-MVP |
| Referral credits | Viral loop: invite a friend, both get credits | Low | Simple referral code at signup; credit awarded on first purchase of referee |

### Anti-Features

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| Subscription-gated generation (no wallet) | Locks out the "try before commit" user; kills top-of-funnel | Keep free tier; wallet is for power users |
| Credit marketplace (sell unused credits) | Fraud vector; devalues credits; support nightmare | Credits are non-transferable |
| Complex tier-based pricing per model | Confusing; "advanced model costs 3 credits, standard costs 1" creates friction | Flat credit cost per generation; model selection is internal routing |
| Cash-out / withdrawal of credits | Turns credits into currency, triggering financial regulation | Credits are store value only; not redeemable for cash |

---

## Domain 4: Autonomous Agent Team

### Table Stakes

For the autonomous agent platform to be functional, these baseline capabilities must work.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Owner Agent coordination | Without a coordinator, agents conflict or duplicate work | High | Owner Agent must maintain task queue, priority, and veto capability |
| Support Agent: ticket routing and response | Customer support is non-negotiable; can't ignore tickets | Medium | Integrates with order data; knows refund policy; escalates to human on edge cases |
| Support Agent: refund initiation within policy | Users expect resolution, not "I'll pass this on" | Medium | Stripe refund API; policy config (e.g., "refund within 30 days, no questions") |
| Design Agent: catalog curation | Catalog quality degrades without active curation | Medium | Scores designs by visual quality, style coherence, predicted sell-through |
| Agent activity log (dashboard-visible) | Human oversight requires visibility into what agents are doing | Low | Already available via Agent42 platform; just connect MHG-specific events |
| Agent guardrails on spend | Agents must not trigger unbounded API costs | Medium | Agent42 SpendingTracker already exists; configure per-agent daily caps |

### Differentiators

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Sales Agent: dynamic pricing optimization | Margin adjusts based on demand, season, inventory, competitor pricing | High | Reads sales data + Research Agent outputs; adjusts TARGET_MARGIN config |
| Marketing Agent: autonomous social posts | Instagram/TikTok content generated and posted without human | High | Requires social API access (Meta Graph, TikTok for Business); image generation; approval gate for first N posts |
| Research Agent: competitor price monitoring | Automated scraped competitor pricing informs Sales Agent | Medium | Web scraping with rate limiting; Gymshark, Alphalete, Raw Gear as targets |
| Web/Brand Agent: A/B test proposals | Suggests and implements copy, layout, CTA changes based on conversion data | High | Highest risk agent; must have human approval gate for production pushes |
| Analytics Agent: weekly insight reports | Surfaces trends, anomalies, and opportunities from sales data | Medium | Advisory only (no autonomous action); generates structured report to Owner Agent |
| Design Agent: trend-driven generation | Proactively generates seasonal/trend-aligned designs for catalog | Medium | Ingests Research Agent outputs; prompts Design generation pipeline autonomously |

### Anti-Features

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| Agents that can modify pricing without limit | Runaway discounting or price gouging destroys the brand and revenue | Hard floor/ceiling constraints in pricing config; Owner Agent approval above threshold |
| Marketing Agent posting without approval gate | First-party social credibility is hard to recover; one bad post damages brand | Approval queue for first 30 days; then supervised autonomy with retrospective review |
| Support Agent initiating charges to customers | Risk of unauthorized charges, fraud, and chargebacks | Support Agent can only refund or credit, never charge; escalate for billing changes |
| Autonomous product catalog changes | Adding/removing products from Printful affects the entire store | Owner Agent proposes; human reviews before Printful catalog sync |
| Agents with direct production DB write access | Bypasses application validation; creates data integrity risks | Agents call MHG API endpoints, not the DB directly; API enforces business rules |

---

## Feature Dependencies

Critical ordering constraints:

```
Stripe integration
  → Wallet top-up
  → Product purchase checkout
  → Credit award on purchase
  → Creator payouts (Stripe Connect — Sell It only)

AI design generation pipeline
  → Upscaling (LetsEnhance/Claid.ai) — must complete before lock is offered
  → Printful mockup API — must succeed before design is shown to user
  → Credit deduction — must be atomic with generation start (not on success)

Design exclusivity DB schema
  → Exact prompt + seed blocking (Lock It)
  → Fuzzy embedding storage (Own It) — depends on vector store availability
  → Creator catalog submission (Sell It) — depends on Stripe Connect

Agent42 platform integration
  → All agent team features
  → Agent activity logging
  → Spend tracking per agent
```

---

## MVP Recommendation

**Phase priority order, based on feature dependencies and user value:**

### Phase 1: Design Generation + Checkout (Core Loop)
Prioritize these — without them, nothing else matters:
1. Chat interface for AI design generation (multi-model routing)
2. Printful mockup preview on garment
3. Stripe product purchase checkout
4. 5 free credits on signup + credit deduction on generation
5. Add to cart from generated design

### Phase 2: Wallet + Exclusivity (Monetization)
Once the core loop is proven:
1. Wallet top-up via Stripe
2. Lock It tier (exact prompt + seed blocking, "1 of 1" badge)
3. Credits awarded on purchase
4. My Designs account page

### Phase 3: Own It + Agent Team Foundation
After purchase flow is solid:
1. Own It tier (fuzzy prompt matching, hi-res download)
2. Support Agent (ticket response, refund initiation)
3. Sales Agent (pricing optimization)
4. Design Agent (catalog curation)
5. Owner Agent coordination layer

### Phase 4: Creator Economy + Full Agent Team
After PMF validation:
1. Sell It tier (Stripe Connect, creator catalog, revenue share)
2. Marketing Agent (social posts with approval gate)
3. Research Agent (competitor monitoring)
4. Web/Brand Agent (A/B testing proposals)
5. Analytics Agent (weekly reports)

**Defer indefinitely:**
- Upload your own design
- Design resale marketplace
- Mobile app
- Subscription tier (Meathead Pro) — add once free-tier retention is proven

---

## Cross-Domain Feature Interactions

| Interaction | Why It Matters |
|-------------|----------------|
| Design generation cost → credit system | Credit cost per generation must be set before wallet top-up is built; price anchors user expectations |
| Upscaling completion → Lock It offer | Never show Lock It option until hi-res is ready; locking a 1024px image is a trust violation |
| Stripe webhook → credit award | Order confirmed webhook must atomically award credits; failure must not silently skip reward |
| Own It fuzzy matching → generation pipeline | Every new generation must query the fuzzy match index; adds ~50-100ms latency; test under load |
| Marketing Agent → design generation | Agent uses same image pipeline as users; must respect rate limits and cost caps |
| Research Agent → Sales Agent | Research Agent feeds pricing data; Sales Agent acts on it; both must share state via Owner Agent |

---

## Sources

- [Printful API v2 documentation](https://developers.printful.com/docs/v2-beta/) — mockup generation async webhook pattern (HIGH confidence)
- [Stripe payment processing best practices](https://stripe.com/guides/payment-processing-best-practices) — wallet/checkout patterns (HIGH confidence)
- [Lovart AI mockup generator](https://www.lovart.ai/tools/free-ai-mockup-generator) — chat refinement UX pattern (MEDIUM confidence)
- [Redbubble vs TeePublic creator earnings](https://earnifyhub.com/blog/redbubble-vs-teepublic.php) — creator revenue share models (MEDIUM confidence)
- [Agentic commerce 2026 — McKinsey](https://www.mckinsey.com/capabilities/quantumblack/our-insights/the-agentic-commerce-opportunity-how-ai-agents-are-ushering-in-a-new-era-for-consumers-and-merchants) — autonomous agent commerce patterns (HIGH confidence)
- [BigCommerce: Ecommerce AI Agents 2026](https://www.bigcommerce.com/blog/ecommerce-ai-agents/) — agentic ecommerce feature taxonomy (MEDIUM confidence)
- [Siena AI autonomous support](https://www.siena.cx/) — autonomous refund/return handling pattern (MEDIUM confidence)
- [Stripe digital wallets guide](https://stripe.com/resources/more/digital-wallets-101) — wallet integration patterns (HIGH confidence)
- [Gelato: AI print on demand 2026](https://www.gelato.com/blog/ai-print-on-demand) — POD AI feature landscape (MEDIUM confidence)
- [Print on demand trends 2026](https://pbfulfill.com/blogs/marketing-strategy/print-on-demand-trends) — market context (MEDIUM confidence)
- [Redis: fuzzy matching algorithms](https://redis.io/blog/what-is-fuzzy-matching/) — fuzzy match + semantic similarity architecture (HIGH confidence)
- [Yotpo loyalty platform](https://www.yotpo.com/platform/loyalty/) — credit/rewards system patterns (MEDIUM confidence)
- [RESEARCH-exclusivity-pricing.md](../../RESEARCH-exclusivity-pricing.md) — prior project research on exclusivity tiers (HIGH confidence — first-party)
