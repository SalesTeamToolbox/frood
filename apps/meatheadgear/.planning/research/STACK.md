# Technology Stack

**Project:** MeatheadGear — AI-powered gym apparel storefront (milestone additions)
**Researched:** 2026-03-21
**Scope:** Additions to existing FastAPI/SQLite/Printful foundation

---

## Context: What Already Exists

The existing codebase already has these locked in:

| Technology | Version | Role |
|------------|---------|------|
| FastAPI | >=0.115.0 | Web framework — keep |
| uvicorn[standard] | >=0.34.0 | ASGI server — keep |
| aiosqlite | >=0.20.0 | Async SQLite — keep for now |
| aiofiles | >=24.1.0 | Async file I/O — keep |
| httpx | >=0.28.0 (latest: 0.28.1) | HTTP client — keep, use for all new API calls |
| python-jose[cryptography] | >=3.3.0 | JWT auth — keep |
| passlib[bcrypt] | >=1.7.4 | Password hashing — keep |
| resend | >=2.0.0 (latest: 2.26.0) | Transactional email — keep |

Do NOT re-implement or replace any of these.

---

## New Dependencies by Feature Area

### 1. AI Image Generation

#### Core Pattern

Use `httpx.AsyncClient` directly against each provider's REST API. Do NOT add
provider-specific SDK packages — every provider supports REST with Bearer auth,
and the openai Python SDK >=1.x supports custom `base_url` for OpenAI-compatible
APIs. Keep the dependency surface minimal.

| Library | Version | Purpose | Confidence |
|---------|---------|---------|------------|
| openai | >=1.109.1 | GPT Image 1.5 via OpenAI Images API; also Synthetic.new via base_url override | HIGH — verified PyPI, official docs |

**Why `openai` and not three separate SDKs:**
- GPT Image 1.5 requires the official `openai` SDK (Images API)
- Recraft V4 is OpenAI-compatible (accepts `base_url='https://external.api.recraft.ai/v1'`)
- Ideogram 3.0 is REST-only with no official Python SDK; call via httpx
- httpx is already in requirements.txt

**Ideogram 3.0 — no SDK needed:**

```python
# POST https://api.ideogram.ai/generate with Authorization: Bearer {key}
async with httpx.AsyncClient() as client:
    resp = await client.post(
        "https://api.ideogram.ai/generate",
        headers={"Authorization": f"Bearer {IDEOGRAM_KEY}"},
        json={"image_request": {"prompt": prompt, "model": "V_3", ...}}
    )
```

**Recraft V4 — via openai SDK with base_url:**

```python
from openai import AsyncOpenAI
recraft_client = AsyncOpenAI(
    base_url="https://external.api.recraft.ai/v1",
    api_key=RECRAFT_KEY,
)
```

**GPT Image 1.5 — standard openai SDK:**

```python
from openai import AsyncOpenAI
client = AsyncOpenAI(api_key=OPENAI_KEY)
response = await client.images.generate(
    model="gpt-image-1.5",
    prompt=prompt,
    size="1024x1024",
    quality="medium",  # low / medium / high
)
```

**Routing logic (cost-first):**
- Default to Recraft V4: $0.04/raster, best for print vectors
- Recraft V4 Pro: $0.08/raster, higher fidelity for hero designs
- Ideogram 3.0: ~$0.06/image (via Together.ai at $0.06/MP), best for text-in-design
- GPT Image 1.5 medium: ~$0.04/image, fastest drafts / iterative chat refinement
- GPT Image 1.5 high: ~$0.13-0.20/image, reserve for final hi-res export only

**CAUTION — pricing volatility:** All three providers have changed pricing within 2025.
Recraft reduced Creative Upscale from $0.80 to $0.25. Build a cost-tracking layer from
day one; do not hardcode generation costs in business logic.

#### Upscaling to Print Resolution

| Library | Version | Purpose | Confidence |
|---------|---------|---------|------------|
| (httpx — already present) | — | Claid.ai REST API for POD upscaling | HIGH |

Use Claid.ai REST API (the API layer of LetsEnhance). Printify integrated Claid for
exactly this use case — converting web-resolution AI images to 300 DPI print-ready
files at 4500x5400+. Call via `httpx.AsyncClient`; no SDK needed.

```python
# POST https://api.claid.ai/v1-beta1/image/edit
# header: Authorization: Bearer {CLAID_KEY}
# body: {"input": {"url": image_url}, "operations": {"resizing": {"width": 4500}}}
```

Do NOT use LetsEnhance's consumer web UI API — Claid is their B2B/developer product.

---

### 2. Payments — Stripe

| Library | Version | Purpose | Confidence |
|---------|---------|---------|------------|
| stripe | >=14.4.1 | Payments, wallet, Connect payouts | HIGH — verified PyPI latest 14.4.1 |

**Why stripe 14.x over earlier versions:**
- v11+ uses typed Python objects (not raw dicts) for all response objects
- v12+ added async client (`stripe.AsyncStripe`)
- v14.x includes latest Connect and Billing endpoints

**Three Stripe subsystems needed:**

1. **Payment Intents** — product purchases, exclusivity add-ons
2. **Customer Balance / Credits** — wallet top-up + deductions
3. **Connect Express** — creator payouts (15% revenue share on Sell It designs)

**Wallet implementation pattern:**

Use Stripe Customer Balance (not a custom credits table) for wallet deposits. This
offloads balance tracking, refund accounting, and audit trail to Stripe. Local DB
tracks design credits (the MHG abstraction over dollar balance):

```
Stripe Customer Balance = dollars deposited (source of truth for money)
DB wallet_credits column = design generation credits (1 credit = ~$0.75)
```

**Connect Express for creator payouts:**

```python
# Create connected account at Sell It signup
account = stripe.Account.create(type="express", country="US", ...)

# Transfer after each catalog sale
stripe.Transfer.create(
    amount=int(sale_price * 0.15 * 100),  # 15% in cents
    currency="usd",
    destination=creator.stripe_account_id,
)
```

**Webhook handler pattern:**

```python
@app.post("/webhooks/stripe")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig = request.headers["stripe-signature"]
    event = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
    # handle checkout.session.completed, transfer.paid, etc.
```

Do NOT use Stripe Checkout Sessions for wallet top-up — use Payment Intents directly
so the wallet UI stays in-app. Use Checkout Sessions only for product purchases where
redirect UX is acceptable.

---

### 3. Semantic Similarity — Fuzzy Prompt Blocking

| Library | Version | Purpose | Confidence |
|---------|---------|---------|------------|
| sentence-transformers | >=5.3.0 | Embedding model for prompt similarity | HIGH — verified PyPI latest 5.3.0 |
| onnxruntime | >=1.24.4 | ONNX backend for inference (already used in Agent42 platform) | HIGH — verified PyPI latest 1.24.4 |

**Why sentence-transformers + ONNX:**
- Agent42 already uses ONNX runtime for memory embeddings — consistent dependency
- `all-MiniLM-L6-v2` ONNX export: 22MB, 384-dim, sub-10ms per inference on CPU
- No GPU required, no PyTorch dependency — keep Docker image small

**Implementation:**

```python
from sentence_transformers import SentenceTransformer

# Load once at startup with ONNX backend
model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2", backend="onnx")

def similarity(a: str, b: str) -> float:
    embs = model.encode([a, b], normalize_embeddings=True)
    return float(embs[0] @ embs[1])  # cosine sim for unit vectors

def is_blocked(prompt: str, locked_prompts: list[str], threshold: float = 0.92) -> bool:
    return any(similarity(prompt, lp) >= threshold for lp in locked_prompts)
```

**Threshold guidance:**
- 0.92+ for "Own It" blocking — very conservative, only catches near-identical prompts
- 0.85 for soft warning ("Similar design exists") — shown in UI but not a hard block
- Research shows MPNet achieves 75.6% accuracy at 0.671 threshold for paraphrase detection;
  for exclusivity the use case requires higher precision (fewer false positives), hence 0.92

**Storage of locked prompt embeddings:**
- Store as BLOB (numpy float32 array serialized via `np.save`) in SQLite initially
- When volume demands it, move to Qdrant (already running in Agent42 platform) for
  nearest-neighbor search instead of linear scan

Do NOT use OpenAI's text-embedding-3-small for this — it's $0.02/1M tokens which is
fine, but it introduces latency + API dependency for a blocking operation that runs on
every design generation request. Local inference is faster and free.

---

### 4. Autonomous Agent Team Orchestration

**Decision: Use Agent42's existing agent infrastructure directly.**

Do NOT add CrewAI, LangGraph, AutoGen, or any third-party orchestration framework.
Rationale:
- Agent42 already provides agent runtime, tool dispatch, MCP server, memory, and
  scheduling as a platform — MHG is an Agent42 App
- Adding a second orchestration layer creates double scheduling, double retry logic,
  and incompatible state management
- Synthetic.new is accessed via `openai.AsyncOpenAI(base_url=..., api_key=...)` using
  the existing Agent42 provider pattern — already implemented

**Agent42 hooks for MHG agents:**

```python
# Each MHG agent = an Agent42 agent configured with Synthetic.new Pro
# Scheduling = Agent42's background task loop (already exists)
# Inter-agent communication = Agent42 MCP tool calls
# Memory = Agent42 ONNX + Qdrant memory system
```

**Synthetic.new Pro integration:**

```python
from openai import AsyncOpenAI

synthetic_client = AsyncOpenAI(
    base_url="https://api.synthetic.new/v1",
    api_key=SYNTHETIC_API_KEY,
)
# 270 req/hr flat-rate, 17+ models, fully OpenAI-compatible
```

**Agent scheduling — no new library needed:**

Use FastAPI's `lifespan` + `asyncio.create_task` for lightweight recurring agent
triggers, the same pattern already used in Agent42:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(agent_scheduler_loop())
    yield
    task.cancel()
```

For heavier periodic jobs (Research Agent daily crawl, Analytics Agent nightly report),
add APScheduler if the asyncio loop pattern proves insufficient. But start without it.

| Library | Version | Purpose | Confidence |
|---------|---------|---------|------------|
| APScheduler | >=4.0.0a5 (async) | Periodic agent trigger scheduling — add only if needed | MEDIUM |

Do NOT use Celery for agent scheduling. Celery requires Redis as a broker (separate
process), adds significant operational complexity, and is overkill for 8 agents that
run on a flat-rate API with no per-task cost pressure.

---

### 5. Image Processing — Watermarks and Mockups

| Library | Version | Purpose | Confidence |
|---------|---------|---------|------------|
| Pillow | >=12.1.1 | Watermark overlay on free-tier previews; composite mockup images | HIGH — verified PyPI latest 12.1.1 |

**Watermark pattern:**

```python
from PIL import Image, ImageDraw, ImageFont

def apply_watermark(img: Image.Image, text: str = "PREVIEW - MeatheadGear") -> Image.Image:
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    # diagonal text at 30% opacity
    draw.text((img.width // 4, img.height // 2), text, fill=(255, 255, 255, 77))
    return Image.alpha_composite(img.convert("RGBA"), overlay)
```

Pillow is also used for format normalization (PNG → JPEG for Printful uploads) and
DPI metadata embedding before Claid.ai upscaling.

---

### 6. Email — Already Decided

`resend` 2.26.0 is already in requirements.txt. No change needed.

Use cases: order confirmation, creator payout notification, design generation receipt,
password reset (already implemented), weekly digest (Marketing Agent output).

---

## Complete New Requirements

The additions needed on top of the existing requirements.txt:

```txt
# AI Image Generation
openai>=1.109.1

# Payments
stripe>=14.4.1

# Semantic similarity (fuzzy prompt blocking)
sentence-transformers>=5.3.0
onnxruntime>=1.24.4

# Image processing (watermarks, mockups, format conversion)
Pillow>=12.1.1

# Optional: periodic agent scheduling (add when needed)
# apscheduler>=4.0.0a5
```

**What is NOT added and why:**

| Rejected Library | Why Rejected |
|-----------------|-------------|
| ideogram-python / pydeogram | Unofficial community SDK, unmaintained; Ideogram is simple REST — use httpx directly |
| crewai / langgraph / autogen | Third-party orchestration frameworks conflict with Agent42's existing agent infrastructure |
| celery / rq | Overkill for 8 flat-rate agents; asyncio task loop is sufficient; adds Redis broker dependency |
| torch / transformers | PyTorch is ~1GB; ONNX runtime (already present) handles inference at ~25MB |
| opencv-python | cv2 is 80MB+ for tasks Pillow handles adequately; overkill for watermarking |
| boto3 / s3 | No S3 in scope; AI providers serve images via URL; Printful handles product file storage |
| numpy (explicit) | numpy is a sentence-transformers transitive dep; don't pin separately |

---

## API Credentials Needed

| Service | Env Var | Notes |
|---------|---------|-------|
| Ideogram | `IDEOGRAM_API_KEY` | REST bearer, $0.06/img via Together.ai or direct |
| Recraft | `RECRAFT_API_KEY` | OpenAI-compat, $0.04/raster $0.08/vector |
| OpenAI | `OPENAI_API_KEY` | GPT Image 1.5, $0.04/medium $0.13-0.20/high |
| Claid.ai | `CLAID_API_KEY` | Upscaling to 300 DPI, credit-based |
| Stripe | `STRIPE_SECRET_KEY` | Payments |
| Stripe | `STRIPE_WEBHOOK_SECRET` | Webhook signature verification |
| Stripe | `STRIPE_PUBLISHABLE_KEY` | Frontend checkout |
| Synthetic.new | `SYNTHETIC_API_KEY` | Agent LLM backbone, $60/mo flat |
| Resend | `RESEND_API_KEY` | Already in use |

---

## Confidence Assessment

| Area | Confidence | Basis |
|------|------------|-------|
| stripe 14.4.1 | HIGH | Verified PyPI — exact version confirmed |
| openai >=1.109.1 | HIGH | Verified PyPI — Recraft OpenAI-compat confirmed in official docs |
| sentence-transformers 5.3.0 | HIGH | Verified PyPI — ONNX backend confirmed in sbert.net docs |
| onnxruntime 1.24.4 | HIGH | Verified PyPI — already used in Agent42 platform |
| Pillow 12.1.1 | HIGH | Verified PyPI |
| resend 2.26.0 | HIGH | Verified PyPI — already installed |
| Ideogram REST/httpx approach | HIGH | Official docs confirm REST API, no official Python SDK |
| Recraft pricing ($0.04/$0.08) | HIGH | Confirmed from official X post + docs |
| GPT Image 1.5 pricing ($0.04 medium) | MEDIUM | Multiple sources agree; OpenAI pricing page changes frequently |
| Ideogram pricing (~$0.06/img) | LOW | Only found via Together.ai aggregator, not direct from ideogram.ai pricing page |
| Claid.ai pricing | LOW | Credit-based system confirmed; exact credits-per-image not disclosed publicly |
| Agent42 as orchestration layer | HIGH | Project decision in PROJECT.md; consistent with existing platform |

---

## Sources

- [Ideogram API Reference](https://developer.ideogram.ai/ideogram-api/api-setup)
- [Recraft API Getting Started](https://www.recraft.ai/docs/api-reference/getting-started)
- [Recraft V4 Pricing (official X post)](https://x.com/recraftai/status/1902768444325384468)
- [OpenAI GPT Image 1.5 Model Docs](https://platform.openai.com/docs/models/gpt-image-1.5)
- [Claid.ai Upscale API](https://claid.ai/api-products/upscale-image)
- [stripe PyPI](https://pypi.org/project/stripe/) — v14.4.1 latest
- [stripe Connect Payouts](https://docs.stripe.com/connect/payouts-connected-accounts)
- [sentence-transformers ONNX Backend](https://sbert.net/docs/sentence_transformer/usage/efficiency.html)
- [sentence-transformers PyPI](https://pypi.org/project/sentence-transformers/) — v5.3.0 latest
- [resend PyPI](https://pypi.org/project/resend/) — v2.26.0 latest
- [Pillow PyPI](https://pypi.org/project/Pillow/) — v12.1.1 latest
- [onnxruntime PyPI](https://pypi.org/project/onnxruntime/) — v1.24.4 latest
- [httpx PyPI](https://pypi.org/project/httpx/) — v0.28.1 latest
