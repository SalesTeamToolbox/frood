# Project Research Summary

**Project:** MeatheadGear — AI-powered gym apparel storefront
**Domain:** AI-generated print-on-demand ecommerce with design exclusivity, digital wallet, and autonomous agent operations team
**Researched:** 2026-03-21
**Confidence:** HIGH

## Executive Summary

MeatheadGear is a brownfield FastAPI/SQLite/Printful application being extended with four tightly-coupled capability domains: a multi-model AI design generation pipeline, a Stripe-backed digital wallet and credit system, a tiered design exclusivity system (Lock It / Own It / Sell It), and an 8-agent autonomous management team built on the existing Agent42 platform. Research confirms the architectural foundation is sound and the technology choices are validated — the existing stack requires only five new dependencies (openai, stripe, sentence-transformers, onnxruntime, Pillow). The recommended approach is to build bottom-up: establish the database schema extensions and Stripe core first, layer the image generation pipeline on top, then add exclusivity enforcement, and finally enable the autonomous agent team once there is real data and revenue flowing through the system.

The two highest-value user-facing features — AI design generation and the exclusivity system — have the most critical implementation risks. Images are not print-ready at generation time and must be upscaled via Claid.ai before any purchase, lock, or Printful order is created; skipping this step guarantees customer complaints. The "Own It" fuzzy exclusivity matching requires threshold calibration against a gym-prompt-specific dataset before going live — the 0.92 cosine similarity starting value is a hypothesis, not a validated number. Both risks have clear mitigations and must be resolved in the respective implementation phases, not deferred to post-launch.

The autonomous agent team is the platform's competitive differentiator but also its greatest operational risk. Research documents a real $47,000 API runaway incident in a comparable multi-agent system. Three hard requirements must be in place before any agent gets autonomous action authority: circuit breakers on inter-agent messaging, a hard pricing floor (minimum_price = printful_cost × 1.20) that no agent can override, and Protected Zones restricting agents from modifying payment, auth, or schema code without human approval. The Owner Agent coordinator pattern (hub-and-spoke, not peer-to-peer swarm) is the correct architecture for the business domain because it serializes conflicting decisions from Sales, Analytics, and Research agents.

---

## Key Findings

### Recommended Stack

The existing codebase already carries FastAPI, aiosqlite, aiofiles, httpx, python-jose, passlib, and resend — none of these should be replaced or supplemented. Five new dependencies are required: `openai>=1.109.1` (covers GPT Image 1.5 and Recraft V4 via base_url override), `stripe>=14.4.1` (v14 is required for async client and typed response objects), `sentence-transformers>=5.3.0` with `onnxruntime>=1.24.4` (ONNX backend for sub-10ms embedding inference — consistent with Agent42's existing ONNX memory system), and `Pillow>=12.1.1` (watermarks, format normalization, DPI metadata). Ideogram 3.0 requires no SDK — it is plain REST over httpx. Agent orchestration uses Agent42's existing agent runtime rather than CrewAI, LangGraph, or Celery, which would create double-scheduling conflicts and incompatible state management.

**Core technologies:**
- `openai>=1.109.1`: AI image generation (GPT Image 1.5) and Recraft V4 via OpenAI-compatible base_url — single SDK for two providers
- `stripe>=14.4.1`: Payments (Payment Intents, Checkout Sessions, Connect Express for creator payouts)
- `sentence-transformers>=5.3.0` + `onnxruntime>=1.24.4`: Local ONNX embedding inference for fuzzy prompt blocking — no API latency, no external dependency on a blocking path
- `Pillow>=12.1.1`: Watermark overlay, PNG/JPEG format normalization, DPI metadata before Claid.ai upload
- Claid.ai REST API (via existing httpx): POD-specific upscaling to 4500×5400 @ 300 DPI — no additional dependency
- Agent42 agent runtime + Synthetic.new Pro ($60/mo flat): All 8 autonomous agents, 270 req/hr shared quota

**What was explicitly rejected:**
- Third-party agent frameworks (CrewAI, LangGraph, AutoGen) — incompatible with Agent42 infrastructure
- Celery / Redis broker — overkill for 8 flat-rate agents; asyncio task loop is sufficient
- PyTorch / full transformers — ~1GB; ONNX handles inference at ~25MB
- Ideogram Python SDKs — unofficial, unmaintained; httpx is sufficient

### Expected Features

The feature landscape spans four domains with clear phase ordering driven by revenue dependency: design generation must exist before wallet top-up makes sense, wallet must exist before exclusivity add-ons can be sold, and all three must produce real data before the autonomous agent team can act meaningfully.

**Must have (table stakes) — Phase 1 and 2:**
- Chat-driven AI design generation with conversational refinement
- Real-time garment mockup via Printful API
- Watermarked preview for free-tier users (5 credits on signup)
- Credit balance visible at all times in navigation
- Add to cart from generated design (design ID survives into checkout)
- Stripe product purchase checkout
- Wallet top-up via Stripe with credit award on purchase
- "Lock It" exact prompt + seed blocking with "1 of 1" badge
- My Designs account page
- Generation failure handling with retry button

**Should have (competitive differentiators) — Phase 3:**
- Style presets for gym aesthetic (Bold, Grunge, Motivational, Skull/Edge) — high conversion impact
- Multi-model routing (Ideogram for text-heavy, Recraft for vector/catalog, GPT Image for drafts)
- "Own It" fuzzy prompt matching at ~0.92 cosine similarity threshold
- Hi-res download gate for Own It tier
- Support Agent with autonomous refund queue and escalation
- Sales Agent with bounded pricing optimization (±15%/week, Owner approval above)
- Design Agent for catalog curation and trend-driven generation

**Defer (Phase 4 / post-PMF):**
- "Sell It" creator catalog with Stripe Connect payouts — builds on KYC gate complexity
- Marketing Agent social posting (approval gate required for first 30 days)
- Research Agent competitor monitoring
- Web/Brand Agent A/B testing proposals (highest risk — Protected Zones required)
- Analytics Agent weekly reports
- Upload your own design, design resale marketplace, mobile app

### Architecture Approach

MeatheadGear uses a layered FastAPI services architecture where routers own only HTTP validation and auth, services orchestrate business logic, and the Agent42 platform layer provides the agent runtime beneath. The single most important architectural decision is the coordinator pattern for the agent team — the Owner Agent serializes all conflicting sub-agent proposals rather than allowing peer-to-peer messaging, which prevents the race conditions that cause pricing oscillation and feedback loops. The SQLite database is shared state for all components; WAL mode is non-optional from day one to support concurrent agent writes. Image generation is intentionally two-phase (generate → poll for upscale completion) because blocking a 15–45 second operation in an HTTP request causes uvicorn worker starvation.

**Major components:**
1. **ImageGenPipeline** — fans out to Ideogram/Recraft/GPT-Image based on deterministic style signals, always calls Claid.ai upscale before returning; two-phase async with webhook callback
2. **WalletService** — append-only ledger in wallet_ledger table; atomic credit deduction via `UPDATE ... WHERE credits >= 1` with rowcount check; no direct balance UPDATE statements
3. **ExclusivityService** — exact match via SHA-256 prompt hash (Lock It); cosine similarity via Qdrant ANN search (Own It); embeddings pre-computed at grant time, not at check time
4. **OrderService** — Stripe Checkout Sessions + webhook handler; idempotency via stripe_events_processed table; webhook endpoint excluded from JWT middleware
5. **AgentBus** — SQLite agent_events table; Owner Agent polls every 15 min; sub-agents propose, Owner executes; no agent-to-agent direct messaging
6. **Agent42 AgentRuntime** — spawns Claude Code subprocess per agent; 8 agents assigned purpose-fit models from Synthetic.new (DeepSeek-R1 for analysis, Kimi for research, Qwen3-Coder for Web/Brand, MiniMax for marketing)

**New file structure required:**
- `routers/`: designs.py, wallet.py, checkout.py, exclusivity.py, agent_team.py
- `services/`: design_service.py, image_pipeline.py, wallet_service.py, exclusivity_service.py, order_service.py, agent_bus.py
- `agents/`: mhg_agents.json + 8 skill CLAUDE.md files

### Critical Pitfalls

1. **AI images are not print-ready at generation time** — Always upscale via Claid.ai to 4500×5400 @ 300 DPI before storing the design record or offering Lock It. Validate file dimensions server-side (minimum 3000×3600 px) before creating any Printful order. Store pre-upscale and post-upscale separately to reduce Claid.ai API calls during iteration.

2. **Wallet credit double-spend via race conditions** — Use atomic SQL (`UPDATE wallets SET credits = credits - 1 WHERE user_id = ? AND credits >= 1`, check rowcount == 1), wrap in `BEGIN IMMEDIATE` transactions, and rate-limit to 1 in-flight generation per user. An append-only ledger makes double-spends visible even if one slips through.

3. **Stripe webhook duplicate processing credits wallet twice** — Return HTTP 200 immediately, then process asynchronously. Check stripe_event_id in processed_events table before any credit mutation. INSERT credit row + processed_event row in a single transaction keyed on Stripe payment intent ID.

4. **Autonomous agent feedback loop generates runaway API costs** — Enforce max_iterations per task (3 for action, 5 for research, 1 for report). Route all inter-agent messages through Owner Agent hub. Circuit breaker: pause both agents if >10 inter-agent messages in 60 minutes. Owner Agent prompt must explicitly forbid re-assigning to same agent more than 3 times without human approval.

5. **Web/Brand Agent self-modification breaks checkout** — Implement Protected Zones before giving Web/Brand Agent write access: never allow agents to modify payment processing, authentication, DB migrations, or Printful order code without human review. All agent-proposed code changes go through branch → automated test → dashboard diff → Owner approval → deploy pipeline.

6. **Own It exclusivity threshold is a hypothesis, not a validated value** — Build a 100+ prompt-pair calibration dataset with gym-specific prompts before going live. Start at 0.94+ (conservative/high precision) and reduce only when legitimate blocks are reported. Log all similarity scores with a gray-zone review queue for 0.88–0.96.

---

## Implications for Roadmap

Based on research findings and the hard dependency chain identified in ARCHITECTURE.md, the following 7-phase structure is recommended. Each phase builds directly on the previous and unblocks the next.

### Phase 1: Database Foundation + WAL Mode
**Rationale:** Every other phase depends on the extended schema. No external API calls are required, making this a pure foundation step with zero integration risk. WAL mode must be enabled from the start — retrofitting it after agents are writing concurrently is operationally risky.
**Delivers:** Extended schema (designs, wallet_ledger, design_exclusivity, agent_events, stripe_events_processed) with WAL mode and aiosqlite patterns confirmed working.
**Addresses:** Table-stakes requirement for all four feature domains.
**Avoids:** SQLite write contention (Pitfall 13), thread-safety corruption (Pitfall 18).
**Research flag:** Standard patterns — no phase research needed.

### Phase 2: Wallet + Stripe Core
**Rationale:** Every monetization feature depends on Stripe. The wallet credit system must be atomic and idempotent from day one — retrofitting these guarantees is the highest-risk rework. Building Stripe before image generation means generation costs are handled correctly from first use.
**Delivers:** WalletService (atomic credit ledger), Stripe Checkout Sessions for wallet top-up, webhook handler with idempotency, 5 free credits on signup.
**Uses:** stripe>=14.4.1 (async client, typed objects), Stripe Customer Balance pattern.
**Implements:** WalletService, OrderService (skeleton), stripe_events_processed idempotency table.
**Avoids:** Double-spend race condition (Pitfall 4), duplicate webhook crediting (Pitfall 5), chargeback loss (Pitfall 19).
**Research flag:** Standard patterns — Stripe webhook idempotency is well-documented.

### Phase 3: AI Image Generation Pipeline
**Rationale:** Core user value. Builds on Phase 1 (designs table) and Phase 2 (WalletService.debit). Must include full upscale pipeline before any UI is shown to users — showing a non-print-ready image creates false expectations. Two-phase async (generate → poll) prevents worker starvation.
**Delivers:** ImageGenPipeline with Ideogram/Recraft/GPT-Image routing, Claid.ai upscale webhook, DesignService, /api/designs/generate + /api/designs/{id}/status endpoints. Server-side DPI validation before Printful calls.
**Uses:** openai>=1.109.1, httpx (Ideogram + Claid.ai).
**Implements:** ImageGenPipeline, DesignService, two-phase async generation pattern.
**Avoids:** Non-print-ready images reaching Printful (Pitfall 1), text rendering errors shipping (Pitfall 3), API cost overrun (Pitfall 16).
**Research flag:** Needs validation of actual Claid.ai webhook response latency in staging before wiring to user-facing UI. Ideogram 3.0 text accuracy should be verified with OCR test suite before launch.

### Phase 4: Printful Mockup + Purchase Flow
**Rationale:** Completes the core e-commerce loop (generate → preview on garment → buy). Depends on Phase 3 (design file_url) and Phase 2 (checkout webhook). Exclusivity add-on upsell can be wired at checkout at this point.
**Delivers:** Printful mockup generation, product purchase Checkout Session, webhook handler for order fulfillment (Printful order creation, credit award, order confirmation email).
**Implements:** OrderService.handle_purchase_webhook, PrintfulService mockup extension.
**Avoids:** Missing transparent PNG background (Pitfall 11), sRGB/CMYK color shift must be sampled pre-launch (Pitfall 2), mockup placement variance disclaimer (Pitfall 17).
**Research flag:** Physical sample order required before this phase goes live — color shift and placement variance are not detectable in digital mockups.

### Phase 5: Design Exclusivity System
**Rationale:** Monetization layer above the core loop. Depends on Phase 4 (purchase webhook to grant tiers), Phase 3 (prompt embeddings generated at design creation time). Own It fuzzy matching must be validated against a calibration dataset before going live.
**Delivers:** ExclusivityService (exact SHA-256 blocking for Lock It, Qdrant ANN search for Own It), /api/exclusivity/check + /api/exclusivity/grant, "1 of 1" badge, My Designs account page, hi-res download gate for Own It tier.
**Uses:** sentence-transformers>=5.3.0, onnxruntime>=1.24.4, Qdrant (mhg_exclusive_prompts collection).
**Implements:** ExclusivityService, soft-delete pattern for account deletion.
**Avoids:** Threshold calibration failure (Pitfall 6 — must build calibration dataset first), exclusivity orphaning on account deletion (Pitfall 12).
**Research flag:** Needs pre-launch calibration work — build 100+ gym prompt pair dataset and test all-MiniLM-L6-v2 vs. alternatives before choosing final threshold.

### Phase 6: Frontend Design Chat UI
**Rationale:** Backend phases (1–5) are complete; now the user-facing interface can be assembled knowing all APIs are stable. Building UI last prevents costly rework from backend API changes during integration.
**Delivers:** Chat interface with conversational refinement, garment selector, mockup display, generation history, style presets (Bold/Grunge/Motivational/Skull), credit balance in nav, Lock It / Own It add-on at checkout, design polling for hi-res readiness.
**Avoids:** Exposing technical generation parameters to users (anti-feature), side-by-side model comparison UI (anti-feature), watermark shown after generation rather than at generation time.
**Research flag:** Standard frontend patterns — no phase research needed. Mockup loading state UX may benefit from reviewing Lovart AI and similar chat-to-design patterns.

### Phase 7: Autonomous Agent Team
**Rationale:** Agent team needs real sales data, real designs, and real customers to act on. Deploying agents against an empty store produces low-quality decisions. All Protected Zones, circuit breakers, and pricing floors must be defined before any agent gets autonomous action authority. Sub-agents should be deployed one at a time in order of risk: Support → Analytics → Sales → Marketing → Research → Design → Web/Brand.
**Delivers:** AgentBus (agent_events table + polling loop), Owner Agent coordination loop (15-min cron), all 8 agent skill files and AgentConfig definitions, /api/agent-team/* router, dashboard agent activity visibility, circuit breaker implementation.
**Uses:** Agent42 AgentRuntime, Synthetic.new Pro, asyncio lifespan task loop.
**Implements:** AgentBus, Owner Agent decision loop, Protected Zones, pricing floor constants.
**Avoids:** Agent feedback loop cost runaway (Pitfall 7 — circuit breaker required before any agent gets action authority), pricing floor breach (Pitfall 8 — hard floor in constants before Sales Agent deploys), Web/Brand Agent storefront breakage (Pitfall 9 — staged deploy pipeline), Support Agent refund overreach (Pitfall 14 — pending_refunds queue), prompt injection via user design requests (Pitfall 15 — delimited user input wrapping), Stripe keys in agent environment (Pitfall 4 anti-pattern from ARCHITECTURE.md).
**Research flag:** Marketing Agent requires social API credentials (Meta Graph API, TikTok for Business) — needs API access research before that sub-agent deploys. Sell It tier (Stripe Connect + creator KYC) should be a separate sub-phase within Phase 7 given its KYC complexity (Pitfall 10).

### Phase Ordering Rationale

- **Database first:** Every other phase writes to the schema. WAL mode and aiosqlite patterns must be established before concurrent writes begin.
- **Stripe before generation:** Credits are debited on generation start, not on success. If Stripe is not ready, credit accounting is wrong from the first user interaction.
- **Generation before mockups:** Printful mockup creation requires a design file URL. The upscale pipeline must be end-to-end validated (including DPI floor check) before Printful calls are made in any code path.
- **Purchase flow before exclusivity:** Exclusivity tiers are granted via the purchase webhook. The webhook handler is built in Phase 4; the exclusivity grant is wired in Phase 5.
- **Backend before frontend:** The UI is assembled once API contracts are stable, preventing the most common brownfield extension failure mode: building UI against incomplete APIs.
- **Agent team last:** Agents are decision-support and automation tools, not the product. The product must be functional and revenue-generating before autonomous optimization is meaningful.

### Research Flags

Phases needing deeper research during planning:
- **Phase 3 (Image Generation):** Validate Claid.ai webhook latency in a staging environment before committing to the two-phase polling architecture. Confirm Ideogram 3.0 OCR accuracy for text-in-design with a small test set.
- **Phase 5 (Exclusivity):** Build the gym-prompt calibration dataset before implementation begins. This is not a coding task — it requires human labeling of 100+ prompt pairs. Should be done in parallel with Phase 4.
- **Phase 7 (Agent Team — Marketing sub-phase):** Meta Graph API and TikTok for Business access require application and approval lead times. Research API requirements and begin application during Phase 5 or 6.
- **Phase 7 (Agent Team — Sell It sub-phase):** Stripe Connect KYC embedded onboarding component requirements should be validated against current Stripe docs before implementation; the embedded onboarding component was released in 2025 and docs may be incomplete.

Phases with standard patterns (skip research-phase):
- **Phase 1 (Database):** SQLite WAL mode, aiosqlite patterns — well-documented, already used in Agent42 codebase.
- **Phase 2 (Stripe Core):** Stripe Payment Intents, webhook idempotency — official docs are authoritative and comprehensive.
- **Phase 4 (Printful):** Printful v2 API mockup generation — existing service in codebase, patterns established.
- **Phase 6 (Frontend UI):** Standard FastAPI + vanilla JS patterns already in place in existing storefront.

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All library versions verified on PyPI; Recraft OpenAI-compat confirmed in official docs; Ideogram REST-only confirmed; ONNX backend for sentence-transformers confirmed in sbert.net docs |
| Features | HIGH | Four domains well-researched; MVP feature ordering validated against dependency graph; differentiators confirmed against competitor analysis |
| Architecture | HIGH | Based on direct inspection of Agent42 codebase + verified external API docs; component boundaries drawn from existing patterns; SQL schema modeled on known constraints |
| Pitfalls | HIGH | 10 critical + 9 moderate/minor pitfalls documented with specific prevention steps; most backed by official vendor docs or documented real-world incidents |

**Overall confidence:** HIGH

### Gaps to Address

- **Claid.ai pricing:** Credit-based system confirmed; exact credits-per-image not publicly disclosed. Must verify actual cost before setting wallet credit price. Do not set wallet price until cost per design (generation + background removal + upscaling) is confirmed from actual API calls.
- **Ideogram 3.0 pricing:** Only found via Together.ai aggregator (~$0.06/img), not from ideogram.ai pricing page directly. Verify before routing significant volume to Ideogram.
- **GPT Image 1.5 pricing volatility:** Multiple sources agree on $0.04/medium, but OpenAI pricing changes frequently. Build a cost-tracking abstraction layer from day one; do not hardcode generation costs in business logic.
- **Own It similarity threshold:** 0.92 is a starting hypothesis. A gym-prompt calibration dataset (100+ labeled pairs) is required before Phase 5 goes live. This should be treated as a pre-Phase-5 task.
- **Stripe Connect embedded onboarding:** The embedded KYC onboarding component (released 2025) is listed as the preferred pattern for completion rate. Validate current API availability and documentation completeness before designing the Sell It creator onboarding flow.

---

## Sources

### Primary (HIGH confidence)
- Agent42 codebase: `core/agent_runtime.py`, `core/agent_manager.py` — direct inspection of agent infrastructure
- MeatheadGear codebase: `main.py`, `database.py`, `models.py`, `config.py` — direct inspection of existing foundation
- [stripe PyPI](https://pypi.org/project/stripe/) v14.4.1 — version confirmed
- [sentence-transformers PyPI](https://pypi.org/project/sentence-transformers/) v5.3.0 — ONNX backend confirmed via sbert.net docs
- [onnxruntime PyPI](https://pypi.org/project/onnxruntime/) v1.24.4 — already used in Agent42 platform
- [Pillow PyPI](https://pypi.org/project/Pillow/) v12.1.1 — version confirmed
- [Claid.ai Upscale API docs](https://docs.claid.ai/guides/printing) — 300 DPI POD pipeline confirmed
- [Stripe Connect payouts](https://docs.stripe.com/connect/payouts-connected-accounts) — payout and KYC patterns
- [Printful DTG file creation guide](https://www.printful.com/creating-dtg-file) — DPI requirements confirmed
- [Recraft V4 pricing (official X post)](https://x.com/recraftai/status/1902768444325384468) — $0.04/$0.08 confirmed

### Secondary (MEDIUM confidence)
- [Ideogram API Reference](https://developer.ideogram.ai/ideogram-api/api-setup) — REST API confirmed, no SDK
- [Recraft API Getting Started](https://www.recraft.ai/api) — OpenAI-compat base_url confirmed
- [Stripe webhook idempotency](https://stripe.com/blog/idempotency) — idempotent handler pattern
- [Printful v2 API](https://developers.printful.com/docs/v2-beta/) — mockup async webhook pattern
- [Anthropic multi-agent research](https://www.anthropic.com/engineering/multi-agent-research-system) — coordinator vs. swarm pattern
- [Stripe digital wallets guide](https://stripe.com/resources/more/digital-wallets-101) — wallet integration patterns
- [McKinsey agentic commerce 2026](https://www.mckinsey.com/capabilities/quantumblack/our-insights/the-agentic-commerce-opportunity-how-ai-agents-are-ushering-in-a-new-era-for-consumers-and-merchants) — autonomous agent ecommerce patterns
- [RESEARCH-exclusivity-pricing.md](../../RESEARCH-exclusivity-pricing.md) — prior first-party research on exclusivity tier pricing

### Tertiary (LOW confidence)
- [Ideogram pricing via Together.ai](https://together.ai) — ~$0.06/img; not confirmed directly from ideogram.ai pricing page
- [Claid.ai credit pricing](https://claid.ai) — credit-based system confirmed; per-image cost not publicly disclosed; requires direct API test

---
*Research completed: 2026-03-21*
*Ready for roadmap: yes*
