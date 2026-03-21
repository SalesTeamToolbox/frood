# Architecture Patterns

**Project:** MeatheadGear — AI-powered gym apparel storefront
**Researched:** 2026-03-21
**Confidence:** HIGH (based on existing codebase + Agent42 platform internals + verified external APIs)

---

## System Overview

MeatheadGear is a brownfield FastAPI application that needs four new capability domains
layered onto an existing foundation:

1. **Design Generation Pipeline** — multi-service AI image generation + upscaling
2. **Wallet / Credits / Payments** — Stripe integration with internal credit ledger
3. **Design Exclusivity System** — fuzzy prompt matching + ownership enforcement
4. **Autonomous Agent Management Team** — Owner agent coordinating 7 domain sub-agents

These domains are largely independent of each other during development but share the
SQLite database as their common state store.

---

## Recommended Architecture

```
                          ┌─────────────────────────────────┐
                          │         FastAPI (port 8001)      │
                          │                                  │
    Browser / SPA ───────►│  /api/auth     /api/catalog      │
                          │  /api/designs  /api/wallet       │
                          │  /api/checkout /api/exclusivity  │
                          │  /api/webhook  /api/agent-team   │
                          └────────────┬────────────────────┘
                                       │ async
                          ┌────────────▼────────────────────┐
                          │         Services Layer           │
                          │                                  │
                          │  DesignService  WalletService    │
                          │  ExclusivityService  PricingService│
                          │  OrderService   AgentBus         │
                          └────────────┬────────────────────┘
                                       │
              ┌────────────────────────┼──────────────────────┐
              │                        │                      │
    ┌─────────▼──────────┐  ┌──────────▼──────────┐  ┌───────▼───────────┐
    │  Image Generation  │  │  Stripe / Payments  │  │  SQLite DB (WAL)  │
    │  Pipeline          │  │                     │  │                   │
    │                    │  │  Checkout Sessions  │  │  users            │
    │  Ideogram 3.0      │  │  Webhooks (signed)  │  │  designs          │
    │  Recraft V4        │  │  Customer objects   │  │  wallet_ledger    │
    │  GPT-Image 1.5     │  │  Connect (creators) │  │  exclusivity      │
    │  Claid.ai upscaler │  │                     │  │  agent_events     │
    └────────────────────┘  └─────────────────────┘  └───────────────────┘

                          ┌─────────────────────────────────┐
                          │   Agent42 Platform Layer         │
                          │                                  │
                          │   AgentRuntime (subprocess CC)  │
                          │   AgentManager (config/CRUD)    │
                          │   Memory (Qdrant + embeddings)  │
                          │   MCP Server (36+ tools)        │
                          └────────────┬────────────────────┘
                                       │
                          ┌────────────▼────────────────────┐
                          │    MHG Autonomous Agent Team     │
                          │                                  │
                          │   [Owner Agent]                  │
                          │       ├─ Marketing Agent         │
                          │       ├─ Sales Agent             │
                          │       ├─ Support Agent           │
                          │       ├─ Research Agent          │
                          │       ├─ Design Agent            │
                          │       ├─ Web/Brand Agent         │
                          │       └─ Analytics Agent         │
                          └─────────────────────────────────┘
```

---

## Component Boundaries

| Component | Responsibility | Communicates With |
|-----------|---------------|-------------------|
| **FastAPI routers** | HTTP boundary, request validation, auth middleware | Services layer |
| **DesignService** | Orchestrate generation pipeline, store design records, return mockup URLs | ImageGenPipeline, Printful, DB |
| **ImageGenPipeline** | Fan out to Ideogram/Recraft/GPT-Image, upscale via Claid.ai, return file URL | Ideogram API, Recraft API, OpenAI API, Claid.ai API |
| **WalletService** | Credit balance reads/writes, debit on generation, credit on purchase | Stripe, DB (wallet_ledger) |
| **ExclusivityService** | Tier enforcement, fuzzy prompt matching, ownership queries | DB (exclusivity table), embedding store (Qdrant) |
| **OrderService** | Build Stripe Checkout sessions, handle webhooks, route to Printful | Stripe, Printful, WalletService |
| **AgentBus** | Durable task queue for agent team (SQLite WAL table), event ingestion | DB (agent_events), AgentRuntime |
| **Agent42 AgentRuntime** | Spawn CC subprocess per agent, manage lifecycle, route logs | Claude Code CLI, Synthetic.new API |
| **Owner Agent** | Read AgentBus queue, assign tasks to sub-agents, approve decisions | AgentBus, all sub-agents (via CC `--resume`) |
| **Sub-agents (7x)** | Execute domain tasks, write results to memory + AgentBus | MCP tools, Agent42 memory, AgentBus |

**Hard rules on component coupling:**
- Routers MUST NOT call Stripe or image APIs directly — only via Services
- Services MUST NOT import from each other (pass data, not references)
- Agent team MUST NOT write directly to user data tables — only via MHG API or AgentBus events
- ImageGenPipeline is the only component that holds AI image generation API keys

---

## Data Flow

### 1. Design Generation Flow

```
User chat prompt
  → POST /api/designs/generate
    → DesignService.generate(user_id, prompt, product_id)
      → WalletService.check_and_debit(user_id, cost=1_credit)
      → ImageGenPipeline.generate(prompt, style_hint)
          → Pick primary service based on style_hint:
              "text-heavy"    → Ideogram 3.0 (native transparency PNG)
              "vector/clean"  → Recraft V4 (300 DPI, CMYK-ready SVG/PNG)
              "quick draft"   → GPT-Image 1.5 (fastest, cheapest)
          → Claid.ai upscale(image_url) → 4500x5400 @ 300 DPI
          → Store file → /static/designs/{uuid}.png
      → Printful.generate_mockup(design_url, product_id, placement)
      → DB: INSERT designs (user_id, prompt, seed, file_url, mockup_url, tier=0)
    ← Return {design_id, mockup_url, watermarked: true}
  ← User sees watermarked preview on garment
```

**Image service selection is deterministic at call time, not LLM-decided.** The
DesignService inspects the prompt for style signals and picks the best service.
The Design Agent (autonomous) can override recommendations for catalog generation
but never for user-facing real-time generation (latency budget: 15s).

### 2. Wallet / Payment Flow

```
User funds wallet:
  POST /api/wallet/topup {amount: 10.00}
    → Stripe Checkout Session (mode=payment, metadata={user_id, type=wallet_topup})
    ← redirect_url
  User completes payment
    → Stripe sends webhook: checkout.session.completed
    → POST /api/webhook/stripe (HMAC verified)
      → OrderService.handle_webhook(event)
        → WalletService.credit(user_id, amount_in_credits)
          → DB: INSERT wallet_ledger (user_id, delta=+N, reason="topup", stripe_pi_id)

User buys product + exclusivity:
  POST /api/checkout {variant_id, design_id, exclusivity_tier}
    → WalletService.check balance if using credits
    → OrderService.build_checkout(user_id, items, exclusivity_tier)
      → Stripe Checkout Session (payment_intent_data.metadata has design_id, tier)
    ← redirect_url
  Stripe webhook: checkout.session.completed
    → OrderService.handle_purchase_webhook(event)
      → ExclusivityService.grant_tier(user_id, design_id, tier)
      → WalletService.credit(user_id, purchase_bonus_credits)
      → Printful.create_order(variant_id, shipping_address, design_url)
      → Resend.send_order_confirmation(user_email)
```

**Idempotency rule:** Every webhook handler checks `stripe_event_id` in the DB
before processing. Duplicate events are a no-op (Stripe retries are expected).

### 3. Exclusivity Enforcement Flow

```
Tier 2 (Lock It) enforcement — exact match:
  User submits prompt
    → ExclusivityService.check_prompt_locked(prompt)
      → DB: SELECT WHERE prompt_hash = sha256(normalized_prompt) AND tier >= 2
      ← {locked: true, owner_name: "...", tier: 2} → block with badge

Tier 3 (Own It) enforcement — fuzzy match:
  User submits prompt
    → ExclusivityService.check_prompt_fuzzy(prompt)
      → Embedding: embed(prompt) via Agent42 ONNX model
      → Qdrant: similarity search in "mhg_exclusive_prompts" collection
      → Filter: cosine_similarity >= 0.92 AND tier == 3
      ← {similar: true, similarity: 0.94, original_prompt: "..."}
      → block with "Similar to an owned design" message
```

**Threshold 0.92 is a starting value.** The Sales Agent monitors false-positive
complaints (legitimate prompts blocked) and false-negative reports (owners seeing
copies) and proposes threshold adjustments to the Owner Agent.

### 4. Autonomous Agent Team Data Flow

```
Agent coordination via AgentBus (SQLite table: agent_events):

  ┌──────────────────────────────────────────────────────┐
  │  agent_events table                                  │
  │  id, created_at, agent_id, type, payload JSON,       │
  │  status (pending/claimed/done/failed), result JSON   │
  └──────────────────────────────────────────────────────┘

Owner Agent loop (cron: every 15 min):
  1. Read agent_events WHERE status='pending' ORDER BY priority DESC
  2. Assign to appropriate sub-agent (UPDATE status='claimed', assigned_to=agent_id)
  3. Launch sub-agent via AgentRuntime.start_agent(config)
  4. Sub-agent reads its claimed event, executes, writes result
  5. UPDATE status='done', result={...}
  6. Owner Agent reviews results of high-impact decisions (pricing changes, UI changes)
  7. Approve → trigger execution via MHG API  |  Reject → feedback loop

Sub-agent reporting:
  All sub-agents write findings to Agent42 memory (scoped: "mhg-{agent-name}")
  AND write a summary event to agent_events for Owner Agent visibility.
```

---

## Autonomous Agent Team: Detailed Design

### Architecture Decision: Coordinator Pattern (not Swarm)

Use a **centralized coordinator** (Owner Agent) rather than a peer-to-peer swarm.
Rationale: swarms introduce spec drift and merge conflicts when agents touch the same
data. The Owner Agent serializes conflicting decisions (e.g., Sales Agent wants 20%
discount vs. Research Agent reporting competitor raised prices 10%).

Owner Agent is the only agent with write access to the MHG API for structural changes.
Sub-agents propose, Owner Agent executes.

### Agent Definitions

Each agent is an `AgentConfig` in Agent42's `agents.json` store with these overrides:

| Agent | Model | Schedule | Memory Scope | Primary Tools | Max Iter |
|-------|-------|----------|--------------|---------------|----------|
| Owner | `reasoning` (Kimi-K2-Thinking) | Every 15 min | `mhg-owner` | `http_request`, `memory`, `data` | 25 |
| Marketing | `marketing` (MiniMax-M2.5) | 9am daily | `mhg-marketing` | `web_search`, `http_request`, `template`, `memory` | 15 |
| Sales | `analysis` (DeepSeek-R1) | 6am daily | `mhg-sales` | `data`, `http_request`, `memory`, `web_search` | 20 |
| Support | `general` (GLM-4.7) | Always-on (triggered) | `mhg-support` | `http_request`, `memory`, `template` | 10 |
| Research | `research` (Kimi-K2.5) | 2am daily | `mhg-research` | `web_search`, `web_fetch`, `data`, `memory` | 30 |
| Design | `general` (GLM-4.7) | 10am daily | `mhg-design` | `http_request`, `data`, `memory` | 15 |
| Web/Brand | `coding` (Qwen3-Coder) | Manual + weekly | `mhg-webbrand` | `shell`, `read_file`, `git`, `http_request`, `memory` | 30 |
| Analytics | `analysis` (DeepSeek-R1) | 8am daily | `mhg-analytics` | `data`, `http_request`, `memory` | 20 |

**Model selection rationale:** Each agent uses a purpose-fit model from Synthetic.new
to avoid rate-limit conflicts on any single model. DeepSeek-R1 for Sales/Analytics
(data reasoning), Kimi for long-context research, Qwen3-Coder for Web/Brand agent
(writes actual code), MiniMax for marketing (long-form content).

### Agent Communication Protocol

Agents do NOT call each other directly. All coordination goes through:

1. **AgentBus (SQLite `agent_events`)** — durable, async, auditable
2. **Agent42 Memory (Qdrant)** — shared knowledge store, scoped by agent
3. **MHG API** — agents call `POST /api/agent-team/report` to submit findings

```
MHG API: /api/agent-team/

  POST /report      — Agent submits findings (auth: AGENT_API_KEY header)
  POST /propose     — Agent proposes an action for Owner approval
  GET  /queue       — Owner Agent reads its work queue
  POST /execute     — Owner Agent triggers an approved action
  GET  /status      — Dashboard view of all agent activity
```

The `AGENT_API_KEY` is a shared secret in `.env` — NOT a user-facing JWT. All
agents are given this key in their launch environment by AgentRuntime.

### Owner Agent Decision Loop

```python
# Owner Agent executes this logic each cycle (pseudocode):

proposals = GET /api/agent-team/queue?status=pending_approval
for p in proposals:
    if p.impact == "low":           # Price change < 5%, content post, report
        execute(p)                   # Auto-approve
    elif p.impact == "medium":      # Price change 5-15%, A/B test, discount
        if p.confidence >= 0.85:
            execute(p)               # Auto-approve with logging
        else:
            defer(p, reason="low confidence")
    elif p.impact == "high":         # UI redesign, new feature, >15% price change
        POST /api/agent-team/propose  # Escalate to human (dashboard notification)
```

This gives the autonomous team full operational autonomy for tactical decisions while
preserving human oversight for structural ones.

---

## Database Schema Extensions

The existing schema (users, products, product_variants, product_images) needs these
additions:

```sql
-- Design generation records
CREATE TABLE designs (
    id TEXT PRIMARY KEY,                    -- UUID
    user_id INTEGER REFERENCES users(id),
    prompt TEXT NOT NULL,
    prompt_hash TEXT NOT NULL,              -- sha256(normalize(prompt)) for exact match
    prompt_embedding BLOB,                  -- float32 vector, also stored in Qdrant
    seed TEXT,                              -- generation seed (for blocking)
    service TEXT NOT NULL,                  -- ideogram|recraft|gpt-image
    file_url TEXT NOT NULL,                 -- /static/designs/{id}.png (upscaled)
    mockup_url TEXT,                        -- Printful mockup URL
    product_id INTEGER REFERENCES products(id),
    is_watermarked INTEGER DEFAULT 1,
    exclusivity_tier INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Wallet credit ledger (append-only)
CREATE TABLE wallet_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    delta_credits INTEGER NOT NULL,         -- positive=credit, negative=debit
    balance_after INTEGER NOT NULL,         -- denormalized for fast reads
    reason TEXT NOT NULL,                   -- topup|generation|purchase_bonus|exclusivity
    stripe_pi_id TEXT,                      -- Stripe PaymentIntent ID (idempotency key)
    design_id TEXT REFERENCES designs(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Exclusivity ownership records
CREATE TABLE design_exclusivity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    design_id TEXT NOT NULL REFERENCES designs(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    tier INTEGER NOT NULL,                  -- 2=lock_it, 3=own_it, 4=sell_it
    stripe_pi_id TEXT NOT NULL,             -- prevents double-grant
    locked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(design_id, tier)                 -- one owner per tier per design
);

-- Agent team event bus
CREATE TABLE agent_events (
    id TEXT PRIMARY KEY,                    -- UUID
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    agent_id TEXT NOT NULL,                 -- which agent generated this
    assigned_to TEXT,                       -- which agent should handle it
    event_type TEXT NOT NULL,               -- report|proposal|result|error
    impact TEXT DEFAULT 'low',              -- low|medium|high
    confidence REAL DEFAULT 0.0,
    payload TEXT NOT NULL,                  -- JSON blob
    status TEXT DEFAULT 'pending',          -- pending|claimed|approved|rejected|done|failed
    result TEXT,                            -- JSON blob from executing agent
    stripe_event_id TEXT                    -- for Stripe webhook idempotency
);

-- Webhook idempotency log
CREATE TABLE stripe_events_processed (
    stripe_event_id TEXT PRIMARY KEY,
    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    event_type TEXT NOT NULL
);
```

**SQLite WAL mode is required.** Enable at DB init:
```python
await db.execute("PRAGMA journal_mode=WAL")
await db.execute("PRAGMA busy_timeout=5000")
```
This allows multiple agent readers concurrent with one writer without contention.

---

## New Router/Service File Structure

```
apps/meatheadgear/
├── routers/
│   ├── auth.py               ← existing
│   ├── catalog.py            ← existing
│   ├── designs.py            ← NEW: /api/designs/*
│   ├── wallet.py             ← NEW: /api/wallet/*
│   ├── checkout.py           ← NEW: /api/checkout, /api/webhook/stripe
│   ├── exclusivity.py        ← NEW: /api/exclusivity/*
│   └── agent_team.py         ← NEW: /api/agent-team/*
├── services/
│   ├── auth.py               ← existing
│   ├── catalog.py            ← existing
│   ├── pricing.py            ← existing
│   ├── printful.py           ← existing
│   ├── design_service.py     ← NEW: orchestrates generation pipeline
│   ├── image_pipeline.py     ← NEW: Ideogram/Recraft/GPT-Image/Claid.ai clients
│   ├── wallet_service.py     ← NEW: credit ledger, balance queries
│   ├── exclusivity_service.py← NEW: tier grants, fuzzy matching
│   ├── order_service.py      ← NEW: Stripe Checkout, webhook handling
│   └── agent_bus.py          ← NEW: AgentBus reads/writes for agent team
├── agents/
│   ├── mhg_agents.json       ← Agent42 AgentConfig definitions for all 8 agents
│   └── skills/               ← Agent skill CLAUDE.md files
│       ├── mhg-owner.md
│       ├── mhg-marketing.md
│       ├── mhg-sales.md
│       ├── mhg-support.md
│       ├── mhg-research.md
│       ├── mhg-design.md
│       ├── mhg-webbrand.md
│       └── mhg-analytics.md
└── database.py               ← existing + schema extensions
```

---

## Design Generation Pipeline: Service Selection Logic

```python
class ImageGenPipeline:
    """Pick the right service per prompt. Never mix services in one request."""

    def select_service(self, prompt: str, context: dict) -> str:
        prompt_lower = prompt.lower()
        # Text-heavy requests → Ideogram (best text rendering)
        if any(kw in prompt_lower for kw in ["text", "letters", "words", "slogan", "font"]):
            return "ideogram"
        # Catalog/hi-res/vector requests → Recraft (CMYK-ready, 300 DPI native)
        if context.get("catalog_submission") or context.get("vector_preferred"):
            return "recraft"
        # Quick drafts, user chat iteration → GPT-Image 1.5 (fastest, cheapest)
        return "gpt-image"

    async def generate(self, prompt: str, context: dict) -> GeneratedImage:
        service = self.select_service(prompt, context)
        raw = await self._call_service(service, prompt)
        upscaled = await self._upscale_claid(raw.url)  # → 4500x5400 @ 300 DPI
        return GeneratedImage(url=upscaled.url, service=service, seed=raw.seed)
```

**Upscaling is always applied** — even for quick drafts. POD requires 300 DPI minimum.
Claid.ai's async webhook API is used for upscaling (submit job → webhook callback).
Design generation is therefore a two-phase async operation:
Phase 1: generate (synchronous-ish, 5-15s) → return watermarked preview
Phase 2: upscale (async, webhook, 10-30s) → update design record with hi-res URL

The frontend polls `/api/designs/{id}/status` for hi-res readiness rather than
blocking the generate endpoint.

---

## Stripe Integration Architecture

```
Stripe objects per user:
  - Customer object (created on first wallet top-up, stored as users.stripe_customer_id)
  - PaymentIntents for wallet top-ups (metadata: user_id, type=wallet_topup)
  - Checkout Sessions for product purchases (metadata: user_id, design_id, tier)
  - Connect Accounts for Tier 4 creators (created on Sell It activation)

Webhook handler hierarchy:
  POST /api/webhook/stripe
    → Verify HMAC signature (stripe.Webhook.construct_event)
    → Check stripe_events_processed (idempotency)
    → Route by event.type:
        checkout.session.completed → OrderService.handle_checkout(event)
        payment_intent.succeeded   → OrderService.handle_payment(event)
        account.updated            → CreatorService.handle_account_update(event)

Critical: Webhook endpoint has NO auth middleware — Stripe signs every request.
All other /api/* endpoints require JWT. The webhook route MUST be excluded from
the JWT middleware in main.py.
```

---

## Build Order (Dependencies)

Phase dependencies flow bottom-up. Each phase must be complete before the next starts.

**Phase 1: Database Foundation**
- Extend `database.py` schema (designs, wallet_ledger, design_exclusivity, agent_events, stripe_events_processed)
- Enable WAL mode in `init_db()`
- No external dependencies

**Phase 2: Wallet + Stripe Core**
- `WalletService` (credit/debit, balance queries against wallet_ledger)
- `OrderService` (Stripe Checkout Session creation, webhook handler skeleton)
- `POST /api/wallet/topup`, `POST /api/checkout`, `POST /api/webhook/stripe`
- Depends on: Phase 1 (wallet_ledger table, idempotency table)

**Phase 3: Image Generation Pipeline**
- `ImageGenPipeline` (Ideogram + Recraft + GPT-Image clients, service selection)
- Claid.ai upscale integration (async + webhook callback endpoint)
- `DesignService` (orchestrate pipeline, debit credits, store design record)
- `POST /api/designs/generate`, `GET /api/designs/{id}/status`
- Depends on: Phase 1 (designs table), Phase 2 (WalletService.debit)

**Phase 4: Printful Mockups + Purchase Flow**
- Extend `PrintfulService` with design upload + mockup generation
- `OrderService.handle_purchase_webhook` → grant exclusivity + award credits
- Depends on: Phase 2 (checkout webhook), Phase 3 (design file_url)

**Phase 5: Exclusivity System**
- `ExclusivityService` (exact + fuzzy prompt matching)
- Qdrant collection: `mhg_exclusive_prompts` populated on tier 2/3 grant
- `GET /api/exclusivity/check`, `POST /api/exclusivity/grant`
- Depends on: Phase 1 (design_exclusivity table), Phase 3 (prompt embeddings), Phase 4 (purchase webhook)

**Phase 6: Frontend Design Chat UI**
- Chat interface → calls `/api/designs/generate`
- Polls `/api/designs/{id}/status` for hi-res readiness
- Mockup display on product card
- Exclusivity tier add-on in checkout flow
- Depends on: Phases 3-5

**Phase 7: Autonomous Agent Team**
- Agent skill files (8x CLAUDE.md with YAML frontmatter)
- `mhg_agents.json` AgentConfig definitions (register in Agent42 agent manager)
- `AgentBus` service + `agent_events` table
- `/api/agent-team/*` router
- Owner Agent coordination loop (cron via Agent42 scheduler)
- Sub-agents deployed one at a time: Support → Analytics → Sales → Marketing → Research → Design → Web/Brand
- Depends on: All of Phases 1-5 (agents need data to act on)

---

## Anti-Patterns to Avoid

### Anti-Pattern 1: Synchronous image generation in the HTTP request
**What:** `await generate_image()` blocks the request for 15-45 seconds
**Why bad:** Uvicorn worker starvation, user sees frozen UI, mobile browsers time out
**Instead:** Return immediately with `design_id`, poll `/api/designs/{id}/status`

### Anti-Pattern 2: Agents writing directly to user tables
**What:** Web/Brand Agent directly executes `UPDATE users SET...` via shell tool
**Why bad:** No audit trail, bypasses business logic, race conditions with user sessions
**Instead:** Agents post proposals to AgentBus; Owner Agent calls MHG API to execute

### Anti-Pattern 3: Single embedding model call for fuzzy blocking (Tier 3)
**What:** Re-embed every existing owned prompt on each user generation request
**Why bad:** O(n) embedding calls as catalog grows, 100ms latency per owned prompt
**Instead:** Pre-embed owned prompts at grant time, store in Qdrant, query via ANN search (O(log n))

### Anti-Pattern 4: Stripe secret key in agents' environment
**What:** Giving agents full Stripe API access to call arbitrary endpoints
**Why bad:** Agent hallucination → accidental refunds, payouts, subscription changes
**Instead:** Agents call `/api/agent-team/propose` with action type + data; Owner Agent reviews; OrderService executes

### Anti-Pattern 5: Shared `agent_events` table without WAL mode
**What:** Multiple concurrent agents writing to SQLite without WAL
**Why bad:** "Database is locked" errors when 3+ agents try to write simultaneously
**Instead:** `PRAGMA journal_mode=WAL` at DB init; `PRAGMA busy_timeout=5000` as safety net

### Anti-Pattern 6: One image service for all generation types
**What:** Using only Ideogram for everything (even vector/catalog designs)
**Why bad:** Ideogram is optimized for text; Recraft produces POD-native files at 300 DPI CMYK
**Instead:** Deterministic service selection based on use-case signals in the prompt + context

---

## Scalability Considerations

| Concern | Current (SQLite, single server) | When to re-address |
|---------|----------------------------------|-------------------|
| DB concurrent writes | WAL mode handles 10+ concurrent writers adequately | >50 req/s or agent team grows past 12 agents |
| Image generation throughput | Sequential per-user; parallel OK up to API rate limits | >100 designs/hour → implement queue + worker pool |
| Agent team cost | 8 agents on Synthetic.new flat-rate Pro ($60/mo) — safe | Adding >15 agents or switching to per-token billing |
| Fuzzy prompt index | Qdrant embedded mode in Agent42 memory — adequate | >50K exclusive designs |
| Stripe webhooks | Single FastAPI instance, synchronous processing | >1K events/hour → add idempotency cache in Redis |

---

## Sources

- Agent42 codebase: `core/agent_runtime.py`, `core/agent_manager.py` (HIGH confidence — direct inspection)
- MeatheadGear codebase: `main.py`, `database.py`, `models.py`, `config.py` (HIGH confidence — direct inspection)
- Ideogram API: https://developer.ideogram.ai/ideogram-api/api-overview (MEDIUM confidence — WebSearch verified, official docs URL)
- Recraft API: https://www.recraft.ai/api (MEDIUM confidence — WebSearch verified, official docs URL)
- Claid.ai API: https://docs.claid.ai/guides/printing (HIGH confidence — official docs, 300 DPI pipeline confirmed)
- Stripe Connect payouts: https://docs.stripe.com/connect/payouts-connected-accounts (HIGH confidence — official Stripe docs)
- Stripe webhook idempotency: https://www.magicbell.com/blog/stripe-webhooks-guide (MEDIUM confidence)
- Printful v2 API: https://developers.printful.com/docs/v2-beta/ (MEDIUM confidence — WebSearch, official URL)
- Multi-agent orchestration: https://www.anthropic.com/engineering/multi-agent-research-system (MEDIUM confidence)
- SQLite WAL concurrency: https://iifx.dev/en/articles/17373144 (MEDIUM confidence — verified against SQLite docs)
- Agent42 PROVIDER_MODELS mapping: `core/agent_manager.py` line 26-51 (HIGH confidence — direct inspection)
