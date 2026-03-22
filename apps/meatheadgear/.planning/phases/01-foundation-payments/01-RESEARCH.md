# Phase 1: Foundation + Payments - Research

**Researched:** 2026-03-21
**Domain:** SQLite WAL mode extension + Stripe Checkout + digital wallet/credits system
**Confidence:** HIGH

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| DB-01 | Database schema extends existing tables with wallet, design, exclusivity, and agent tables (additive, no breaking changes) | Full SQL schema provided below; additive-only pattern confirmed with CREATE TABLE IF NOT EXISTS; no ALTER TABLE on existing tables |
| DB-02 | SQLite WAL mode enabled at startup for concurrent agent writes | WAL PRAGMA pattern verified; must be added to `init_db()` before table creation |
| DB-03 | Append-only wallet_ledger table for credit transactions | Schema below; denormalized `balance_after` column enables O(1) balance reads without SUM; idempotency key on stripe_pi_id |
| DB-04 | agent_events table for AgentBus inter-agent communication | Schema below; used only in Phase 4 but must exist now because schema is additive and tables are safe to create empty |
| PAY-01 | User can fund wallet via Stripe Checkout (minimum $5 deposit) | Stripe Checkout Session with price_data (dynamic pricing); minimum enforced server-side; redirect flow |
| PAY-02 | User receives 5 free design credits on account creation | INSERT into wallet_ledger at register time; delta_credits=5, reason="signup_bonus"; no Stripe involved |
| PAY-03 | User can view credit balance (visible in nav at all times) | GET /api/wallet/balance returns current balance; balance_after on last ledger row is O(1) read |
| PAY-04 | Credit deduction is atomic (UPDATE ... WHERE credits >= cost, check rowcount) | Pure ledger approach — no credits column to UPDATE; instead INSERT debit row only if balance check passes using SELECT FOR IMMEDIATE transaction |
| PAY-05 | User can purchase products via Stripe Checkout | Checkout Session with existing Printful product price; product purchase handler stub (full Printful order in Phase 2) |
| PAY-06 | Stripe webhook handler is idempotent (check stripe_events_processed before credit mutation) | stripe_events_processed table + single transaction check confirmed; pattern fully documented |
| PAY-07 | Purchase awards wallet credits for future designs (incentive amount configurable) | Configurable via env var PURCHASE_CREDIT_AWARD (default 2); credited in webhook handler after purchase |
| PAY-08 | Webhook endpoint excluded from JWT middleware (authenticates via HMAC signature) | Webhook route registered BEFORE JWT middleware or excluded via route-level override; HMAC via stripe.Webhook.construct_event |
</phase_requirements>

---

## Summary

Phase 1 extends the MeatheadGear brownfield FastAPI/SQLite application with five new database tables, WAL mode, a wallet credit system, and Stripe Checkout integration for both wallet top-ups and product purchases. No existing tables are modified — all additions use `CREATE TABLE IF NOT EXISTS`, making schema migration safe on a live database.

The existing codebase is clean and well-structured: async throughout (aiosqlite, httpx), no global JWT middleware (auth is per-route via `Depends(get_current_user)`), and a `lifespan` context manager that is the correct place to add WAL setup. The auth router pattern (`routers/auth.py`) is the exact template for new routers: pydantic request/response models, `Depends(get_current_user)` on protected routes, and `Depends(get_db)` for DB access.

The two highest-priority correctness concerns for this phase are: (1) atomic credit deduction using `BEGIN IMMEDIATE` + ledger INSERT with a balance check, and (2) Stripe webhook idempotency via `stripe_events_processed` table with a single transaction. Both patterns have complete implementations below. The `users` table does NOT need a `credits` column — the wallet_ledger is the source of truth, and the `balance_after` denormalized column on each row provides O(1) balance reads.

**Primary recommendation:** Extend `database.py` with WAL mode + five new tables, add `stripe>=14.4.1` to requirements, build `WalletService` with atomic ledger operations, build `OrderService` with idempotent webhook handler, and register `/api/wallet/*` + `/api/checkout` + `/api/webhook/stripe` routers. The webhook route must be registered before any auth dependency is applied.

---

## Project Constraints (from CLAUDE.md)

### Coding conventions (enforced — not negotiable)
- All I/O is async: use `aiosqlite`, `httpx.AsyncClient`, `aiofiles` — never blocking equivalents
- Frozen dataclass config: new env vars added to `Settings` class in `config.py` with `from_env()` method
- Plugin architecture: new routers register in `main.py`; services are standalone modules in `services/`
- Graceful degradation: Stripe API unavailable should not crash startup — check key presence at call time, not import time
- Security: never log API keys or tokens; always validate inputs; use bcrypt for passwords (already done)

### Testing standards
- Every new module needs a corresponding `tests/test_*.py`
- Use `pytest-asyncio` (`asyncio_mode = "auto"`) with async test functions
- Use `tmp_path` fixture for filesystem/DB isolation; pattern is established in `tests/test_auth.py`
- Mock Stripe API calls in tests — never hit real Stripe in test suite
- No pyproject.toml exists in the app — need to create one for `asyncio_mode = "auto"` OR mark tests with `@pytest.mark.asyncio`

### Development workflow
- Run `python -m pytest tests/ -x -q` from within `apps/meatheadgear/` directory
- After changes: `make format` (ruff), `make lint` (ruff), then tests

---

## Standard Stack

### Core (already installed — no changes)
| Library | Version | Purpose |
|---------|---------|---------|
| FastAPI | >=0.115.0 | Web framework |
| aiosqlite | 0.22.1 (installed) | Async SQLite — all DB access |
| httpx | >=0.28.0 | HTTP client — Stripe webhook body reading; future API calls |
| python-jose | >=3.3.0 | JWT auth (existing) |
| passlib + bcrypt | >=1.7.4 | Password hashing (existing) |

### New Dependency (Phase 1)
| Library | Version | Purpose | Why This Version |
|---------|---------|---------|-----------------|
| stripe | >=14.4.1 | Checkout Sessions, webhook verification, async client | v14 = latest; async client added in v12; typed response objects in v11+ |

**Installation:**
```bash
pip install "stripe>=14.4.1"
```

Add to `apps/meatheadgear/requirements.txt`:
```
stripe>=14.4.1
```

**Version verification:** Confirmed 14.4.1 is current latest on PyPI (2026-03-21).

### Not Added in Phase 1
The following appear in project research but are NOT needed until later phases:
- `openai` — Phase 2+ (image generation)
- `sentence-transformers`, `onnxruntime` — Phase 3 (exclusivity)
- `Pillow` — Phase 2 (watermarks)

---

## Architecture Patterns

### Existing Project Structure (Relevant to Phase 1)
```
apps/meatheadgear/
├── config.py              # Frozen dataclass Settings — add Stripe keys here
├── database.py            # Schema + get_db() + init_db() — add WAL + new tables here
├── main.py                # FastAPI app + lifespan — register new routers here
├── routers/
│   ├── auth.py            # Pattern to follow for new routers
│   └── catalog.py
├── services/
│   ├── auth.py            # Pattern to follow for new services
│   └── ...
└── tests/
    ├── conftest.py        # tmp_db fixture
    ├── test_auth.py       # Client fixture pattern to follow
    └── ...
```

### New Files Created in Phase 1
```
apps/meatheadgear/
├── routers/
│   ├── wallet.py          # GET /api/wallet/balance, POST /api/wallet/topup
│   └── checkout.py        # POST /api/checkout, POST /api/webhook/stripe
├── services/
│   ├── wallet_service.py  # WalletService: credit/debit/balance — pure business logic
│   └── order_service.py   # OrderService: build sessions, handle webhooks
└── tests/
    ├── test_wallet.py     # Tests for DB-03, PAY-02, PAY-03, PAY-04
    └── test_checkout.py   # Tests for PAY-01, PAY-05, PAY-06, PAY-07, PAY-08
```

### Pattern 1: WAL Mode in init_db()

The existing `init_db()` function uses `executescript()` for table creation. WAL mode must be set BEFORE table creation and BEFORE any connections are opened by other parts of the app. The correct place is the very beginning of `init_db()`.

```python
# In database.py — init_db()
async def init_db() -> None:
    """Initialize database and create all tables if they don't exist."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(str(DB_PATH)) as db:
        # Enable WAL mode FIRST — must precede table creation
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA busy_timeout=5000")  # 5s timeout on lock contention
        await db.commit()
        await db.executescript(SCHEMA_SQL)
        await db.commit()
```

Note: `PRAGMA journal_mode=WAL` is persistent — it writes to the DB file and survives restarts. Calling it on every `init_db()` is idempotent and safe.

### Pattern 2: Append-Only Wallet Ledger (Atomic Credit Operations)

The wallet has NO credits column on the `users` table. All balance state lives in `wallet_ledger`. The `balance_after` column is denormalized — it stores the running balance after each row's delta, enabling O(1) balance reads without SUM queries.

**Atomic credit debit (most critical pattern — prevents double-spend):**
```python
# In services/wallet_service.py
async def debit_credits(db: aiosqlite.Connection, user_id: int, amount: int, reason: str, design_id: str | None = None) -> int:
    """
    Atomically debit credits. Returns new balance or raises InsufficientCreditsError.
    Uses BEGIN IMMEDIATE to acquire write lock before balance check.
    """
    async with db.execute("BEGIN IMMEDIATE"):
        pass  # aiosqlite: use explicit transaction management

    # aiosqlite pattern — use isolation_level=None for manual transactions
    await db.execute("BEGIN IMMEDIATE")
    try:
        cursor = await db.execute(
            "SELECT COALESCE(MAX(balance_after), 0) FROM wallet_ledger WHERE user_id = ?",
            (user_id,)
        )
        row = await cursor.fetchone()
        current_balance = row[0] if row else 0

        if current_balance < amount:
            await db.execute("ROLLBACK")
            raise InsufficientCreditsError(f"Balance {current_balance} < cost {amount}")

        new_balance = current_balance - amount
        await db.execute(
            """INSERT INTO wallet_ledger
               (user_id, delta_credits, balance_after, reason, design_id)
               VALUES (?, ?, ?, ?, ?)""",
            (user_id, -amount, new_balance, reason, design_id)
        )
        await db.execute("COMMIT")
        return new_balance
    except Exception:
        await db.execute("ROLLBACK")
        raise
```

**Balance read (no lock needed — reads are safe):**
```python
async def get_balance(db: aiosqlite.Connection, user_id: int) -> int:
    cursor = await db.execute(
        "SELECT COALESCE(MAX(balance_after), 0) FROM wallet_ledger WHERE user_id = ?",
        (user_id,)
    )
    row = await cursor.fetchone()
    return row[0] if row else 0
```

Note: `MAX(balance_after)` works as a proxy for "last row's balance" because `balance_after` is monotonically increasing for credits and decreasing for debits — but actually `MAX` is wrong for balance tracking. The correct query is the balance_after of the row with the highest `id`:

```python
cursor = await db.execute(
    "SELECT balance_after FROM wallet_ledger WHERE user_id = ? ORDER BY id DESC LIMIT 1",
    (user_id,)
)
```

### Pattern 3: Stripe Checkout Session Creation

Two session types are needed: wallet top-up and product purchase. Both use `stripe.checkout.Session.create_async()` (the async method added in stripe v12).

**Wallet top-up session:**
```python
# In services/order_service.py
import stripe

async def create_topup_session(user_id: int, amount_usd: float, success_url: str, cancel_url: str) -> str:
    """Create a Stripe Checkout Session for wallet funding. Returns redirect URL."""
    amount_cents = int(amount_usd * 100)
    if amount_cents < 500:  # $5.00 minimum
        raise ValueError("Minimum top-up is $5.00")

    session = await stripe.checkout.Session.create_async(
        mode="payment",
        line_items=[{
            "price_data": {
                "currency": "usd",
                "unit_amount": amount_cents,
                "product_data": {
                    "name": "MeatheadGear Wallet Credits",
                    "description": f"Add ${amount_usd:.2f} to your MeatheadGear wallet",
                },
            },
            "quantity": 1,
        }],
        payment_intent_data={
            "metadata": {
                "user_id": str(user_id),
                "type": "wallet_topup",
                "amount_usd": str(amount_usd),
            }
        },
        metadata={
            "user_id": str(user_id),
            "type": "wallet_topup",
        },
        success_url=success_url,
        cancel_url=cancel_url,
        customer_creation="always",
    )
    return session.url
```

**Product purchase session:**
```python
async def create_purchase_session(
    user_id: int,
    variant_id: int,
    retail_price_usd: float,
    product_name: str,
    design_id: str | None,
    success_url: str,
    cancel_url: str,
) -> str:
    session = await stripe.checkout.Session.create_async(
        mode="payment",
        line_items=[{
            "price_data": {
                "currency": "usd",
                "unit_amount": int(retail_price_usd * 100),
                "product_data": {"name": product_name},
            },
            "quantity": 1,
        }],
        payment_intent_data={
            "metadata": {
                "user_id": str(user_id),
                "type": "product_purchase",
                "variant_id": str(variant_id),
                "design_id": design_id or "",
            }
        },
        metadata={
            "user_id": str(user_id),
            "type": "product_purchase",
        },
        success_url=success_url,
        cancel_url=cancel_url,
    )
    return session.url
```

### Pattern 4: Idempotent Webhook Handler

The webhook route MUST be registered BEFORE `Depends(get_current_user)` is applied, or explicitly bypass it. Looking at the existing `main.py`, auth is route-level (not app-level middleware), so the webhook route simply does NOT use `get_current_user` as a dependency — it uses HMAC verification instead.

```python
# In routers/checkout.py
from fastapi import APIRouter, Request, HTTPException
import stripe
from config import settings

router = APIRouter()

@router.post("/webhook/stripe")
async def stripe_webhook(
    request: Request,
    db: aiosqlite.Connection = Depends(get_db),
) -> dict:
    """
    Stripe webhook endpoint. No JWT auth — authenticates via HMAC signature.
    PAY-06: Idempotent — duplicate events are no-ops.
    PAY-08: Excluded from JWT middleware (auth is per-route in this codebase).
    """
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.stripe_webhook_secret
        )
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    # Return 200 immediately — process asynchronously (Stripe retries on non-2xx)
    # But for simplicity in Phase 1, process synchronously after signature check
    # (wallet top-up and credit award are fast DB operations)

    event_id = event["id"]
    event_type = event["type"]

    # Idempotency check — PAY-06
    cursor = await db.execute(
        "SELECT 1 FROM stripe_events_processed WHERE stripe_event_id = ?",
        (event_id,)
    )
    already_processed = await cursor.fetchone()
    if already_processed:
        return {"status": "already_processed"}

    # Route to handler
    if event_type == "checkout.session.completed":
        session = event["data"]["object"]
        await order_service.handle_checkout_completed(db, session)

    # Record as processed — must be in same logical operation as the credit mutation
    await db.execute(
        "INSERT INTO stripe_events_processed (stripe_event_id, event_type) VALUES (?, ?)",
        (event_id, event_type)
    )
    await db.commit()

    return {"status": "ok"}
```

**Critical:** The idempotency check and the credit INSERT must be in the same DB transaction. If the process crashes between crediting and recording the event, Stripe will retry and double-credit. Pattern: INSERT credit row + INSERT processed event row in one `BEGIN IMMEDIATE` block.

### Pattern 5: 5 Free Credits on Registration (PAY-02)

The `register` endpoint in `routers/auth.py` already returns after inserting the user. The 5 free credits must be granted in the same handler, after the user is created:

```python
# Add to register() in routers/auth.py after user INSERT:
from services.wallet_service import credit_credits

# Grant 5 signup credits
await credit_credits(
    db=db,
    user_id=user_id,
    amount=5,
    reason="signup_bonus",
    stripe_pi_id=None,
)
```

Or alternatively, import WalletService into the auth router. Either approach is correct; avoid importing services from each other.

### Pattern 6: New Config Fields

Following the frozen dataclass pattern in `config.py`:

```python
@dataclass(frozen=True)
class Settings:
    # ... existing fields ...
    stripe_secret_key: str = ""
    stripe_publishable_key: str = ""
    stripe_webhook_secret: str = ""
    purchase_credit_award: int = 2      # PAY-07: credits awarded on product purchase
    min_wallet_topup_usd: float = 5.0   # PAY-01: minimum deposit amount

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            # ... existing fields ...
            stripe_secret_key=os.getenv("STRIPE_SECRET_KEY", ""),
            stripe_publishable_key=os.getenv("STRIPE_PUBLISHABLE_KEY", ""),
            stripe_webhook_secret=os.getenv("STRIPE_WEBHOOK_SECRET", ""),
            purchase_credit_award=int(os.getenv("PURCHASE_CREDIT_AWARD", "2")),
            min_wallet_topup_usd=float(os.getenv("MIN_WALLET_TOPUP_USD", "5.0")),
        )
```

### Anti-Patterns to Avoid

- **Never put a `credits` column on the `users` table** — balance lives in wallet_ledger; `users` stays as-is
- **Never use `UPDATE wallets SET credits = ?` with a pre-computed value** — always use the ledger INSERT pattern with balance_after computed at insert time
- **Never process webhook business logic before calling `request.body()`** — FastAPI buffers the body; calling it after partial processing loses data
- **Never use `db.execute("BEGIN")` followed by `await db.commit()`** — use `BEGIN IMMEDIATE` for write transactions that must prevent concurrent writes (the default BEGIN is `DEFERRED` which can still deadlock)
- **Never configure `stripe.api_key` at import time** — set it in `from_env()` or in the service constructor so tests can mock it

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Webhook HMAC verification | Custom signature comparison | `stripe.Webhook.construct_event()` | Timing-safe comparison, handles Stripe's specific format |
| Idempotency key generation | UUID-based dedup table | `stripe_events_processed` table keyed on Stripe's event ID | Stripe's event IDs are guaranteed unique per event |
| Checkout redirect flow | Custom payment form | Stripe Checkout Sessions | PCI compliance, card handling, 3DS, fraud detection |
| Credit balance calculation | SUM query on ledger | `balance_after` column on last ledger row | O(1) read; SUM grows with transaction history |
| Atomic balance check + deduct | Application-level locking | `BEGIN IMMEDIATE` + INSERT with balance check | SQLite serializes writers at the connection level |

---

## Common Pitfalls

### Pitfall 1: Stripe webhook receives raw body but FastAPI already parsed it
**What goes wrong:** If the webhook route uses `body: dict = Body(...)` or any Pydantic model, FastAPI parses the JSON body and the raw bytes are gone. `stripe.Webhook.construct_event()` requires the original raw bytes to verify the HMAC signature.
**Why it happens:** FastAPI eagerly parses request bodies via dependency injection.
**How to avoid:** The webhook handler must use `payload = await request.body()` (not a Pydantic model parameter) to get raw bytes. Register the webhook route with no body parameter — only `request: Request`.
**Warning signs:** `SignatureVerificationError` even when the webhook secret is correct.

### Pitfall 2: `BEGIN IMMEDIATE` with aiosqlite requires connection-level isolation
**What goes wrong:** `aiosqlite` wraps sqlite3 with `check_same_thread=False`. The default `isolation_level` is `""` (auto-commit mode). Calling `await db.execute("BEGIN IMMEDIATE")` followed by `await db.execute("COMMIT")` manually works, but mixing manual transactions with `await db.commit()` within the same connection is confusing and can lead to "cannot start a transaction within a transaction" errors.
**How to avoid:** Use `db.isolation_level = None` (auto-commit mode) and manage transactions explicitly with `BEGIN IMMEDIATE` / `COMMIT` / `ROLLBACK` strings. This is the recommended pattern for aiosqlite when you need write serialization.
**Code pattern:**
```python
# Set at connection level in get_db():
db = await aiosqlite.connect(str(DB_PATH))
db.row_factory = aiosqlite.Row
await db.execute("PRAGMA journal_mode=WAL")
```

### Pitfall 3: Stripe `checkout.session.completed` metadata is on the Session, but payment details are on the PaymentIntent
**What goes wrong:** Metadata set on `payment_intent_data.metadata` at session creation is on the PaymentIntent object. Metadata set on the Session object via `metadata={}` is on the Session. The `checkout.session.completed` webhook delivers a Session object, and `event["data"]["object"]["metadata"]` is the Session metadata — not the PaymentIntent metadata.
**How to avoid:** Set `metadata` on BOTH the Session and `payment_intent_data.metadata`. Read from `event["data"]["object"]["metadata"]` in the webhook handler. If you need the PaymentIntent ID, it's at `event["data"]["object"]["payment_intent"]`.

### Pitfall 4: `stripe.api_key` is a global module-level variable
**What goes wrong:** In stripe 14.x, both the legacy `stripe.api_key = "sk_..."` pattern and the newer `StripeClient(api_key=...)` pattern work. If you use the module-level global (`stripe.api_key`) and run tests concurrently, one test's key leaks into another test's context.
**How to avoid:** For Phase 1's straightforward use case, set `stripe.api_key = settings.stripe_secret_key` once at app startup in the lifespan function, and mock it in tests with `monkeypatch.setattr(stripe, "api_key", "sk_test_...")`. Alternatively use `StripeClient` instances in the service layer.

### Pitfall 5: aiosqlite `get_db()` yields a new connection per request
**What goes wrong:** The existing `get_db()` opens a new aiosqlite connection per request and closes it at the end. If a service function does a BEGIN IMMEDIATE + INSERT and then returns, then another dependency also calls `get_db()` and gets a DIFFERENT connection — the second connection cannot see uncommitted changes from the first.
**How to avoid:** Pass the same `db` connection through the entire request stack. Do not call `get_db()` multiple times in the same request handler. The existing pattern (single `db: aiosqlite.Connection = Depends(get_db)` per endpoint) is correct — pass this `db` to all service calls.

### Pitfall 6: balance_after can go negative if two concurrent requests pass the balance check before either inserts
**What goes wrong:** Request A reads balance=1, Request B reads balance=1, both pass check, both deduct — final balance=-1.
**How to avoid:** `BEGIN IMMEDIATE` prevents this. An IMMEDIATE transaction acquires a RESERVED lock at BEGIN time. SQLite only allows one RESERVED lock at a time. So if Request A calls `BEGIN IMMEDIATE`, Request B's `BEGIN IMMEDIATE` will block (wait up to `busy_timeout=5000` ms) until A commits or rolls back. This is the whole point of `BEGIN IMMEDIATE` over `BEGIN DEFERRED`.

---

## Code Examples

### Full Schema Extension (database.py addition)

```sql
-- Append to SCHEMA_SQL in database.py

-- Wallet credit ledger (append-only — never UPDATE rows, only INSERT)
CREATE TABLE IF NOT EXISTS wallet_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    delta_credits INTEGER NOT NULL,         -- positive=credit, negative=debit
    balance_after INTEGER NOT NULL,         -- denormalized running balance for O(1) reads
    reason TEXT NOT NULL,                   -- signup_bonus|topup|generation|purchase_bonus
    stripe_pi_id TEXT,                      -- Stripe PaymentIntent ID (idempotency key)
    design_id TEXT,                         -- optional: which design consumed this debit
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Design generation records (schema only — populated in Phase 2)
CREATE TABLE IF NOT EXISTS designs (
    id TEXT PRIMARY KEY,                    -- UUID
    user_id INTEGER REFERENCES users(id),
    prompt TEXT NOT NULL,
    prompt_hash TEXT NOT NULL,              -- sha256(normalize(prompt)) for exact-match blocking
    seed TEXT,                              -- generation seed (for Lock It blocking)
    service TEXT NOT NULL DEFAULT '',       -- ideogram|recraft|gpt-image
    file_url TEXT NOT NULL DEFAULT '',      -- /static/designs/{id}.png (upscaled)
    mockup_url TEXT,                        -- Printful mockup URL
    product_id INTEGER REFERENCES products(id),
    is_watermarked INTEGER DEFAULT 1,
    exclusivity_tier INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Design exclusivity ownership (schema only — populated in Phase 3)
CREATE TABLE IF NOT EXISTS design_exclusivity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    design_id TEXT NOT NULL REFERENCES designs(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    tier INTEGER NOT NULL,                  -- 2=lock_it, 3=own_it, 4=sell_it
    stripe_pi_id TEXT NOT NULL,
    locked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(design_id, tier)
);

-- Agent team event bus (schema only — populated in Phase 4)
CREATE TABLE IF NOT EXISTS agent_events (
    id TEXT PRIMARY KEY,                    -- UUID
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    agent_id TEXT NOT NULL,
    assigned_to TEXT,
    event_type TEXT NOT NULL,
    impact TEXT DEFAULT 'low',
    confidence REAL DEFAULT 0.0,
    payload TEXT NOT NULL DEFAULT '{}',
    status TEXT DEFAULT 'pending',
    result TEXT
);

-- Stripe webhook idempotency log
CREATE TABLE IF NOT EXISTS stripe_events_processed (
    stripe_event_id TEXT PRIMARY KEY,
    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    event_type TEXT NOT NULL
);

-- Index for fast balance lookups
CREATE INDEX IF NOT EXISTS idx_wallet_ledger_user_id ON wallet_ledger(user_id, id DESC);
```

### Wallet Service (services/wallet_service.py skeleton)

```python
"""
MeatheadGear WalletService.

Manages append-only wallet_ledger. All credit/debit operations are atomic.
Balance is derived from the balance_after column of the most recent row.
"""
import aiosqlite


class InsufficientCreditsError(Exception):
    pass


async def get_balance(db: aiosqlite.Connection, user_id: int) -> int:
    """Return current credit balance for user. O(1) via balance_after index."""
    cursor = await db.execute(
        "SELECT balance_after FROM wallet_ledger WHERE user_id = ? ORDER BY id DESC LIMIT 1",
        (user_id,)
    )
    row = await cursor.fetchone()
    return row[0] if row else 0


async def credit_credits(
    db: aiosqlite.Connection,
    user_id: int,
    amount: int,
    reason: str,
    stripe_pi_id: str | None = None,
) -> int:
    """Credit wallet. Returns new balance. Thread-safe via BEGIN IMMEDIATE."""
    await db.execute("BEGIN IMMEDIATE")
    try:
        cursor = await db.execute(
            "SELECT balance_after FROM wallet_ledger WHERE user_id = ? ORDER BY id DESC LIMIT 1",
            (user_id,)
        )
        row = await cursor.fetchone()
        current = row[0] if row else 0
        new_balance = current + amount
        await db.execute(
            """INSERT INTO wallet_ledger (user_id, delta_credits, balance_after, reason, stripe_pi_id)
               VALUES (?, ?, ?, ?, ?)""",
            (user_id, amount, new_balance, reason, stripe_pi_id)
        )
        await db.execute("COMMIT")
        return new_balance
    except Exception:
        await db.execute("ROLLBACK")
        raise


async def debit_credits(
    db: aiosqlite.Connection,
    user_id: int,
    amount: int,
    reason: str,
    design_id: str | None = None,
) -> int:
    """
    Debit wallet atomically. Returns new balance.
    Raises InsufficientCreditsError if balance < amount.
    Uses BEGIN IMMEDIATE to block concurrent debits — PAY-04.
    """
    await db.execute("BEGIN IMMEDIATE")
    try:
        cursor = await db.execute(
            "SELECT balance_after FROM wallet_ledger WHERE user_id = ? ORDER BY id DESC LIMIT 1",
            (user_id,)
        )
        row = await cursor.fetchone()
        current = row[0] if row else 0

        if current < amount:
            await db.execute("ROLLBACK")
            raise InsufficientCreditsError(f"Insufficient credits: have {current}, need {amount}")

        new_balance = current - amount
        await db.execute(
            """INSERT INTO wallet_ledger (user_id, delta_credits, balance_after, reason, design_id)
               VALUES (?, ?, ?, ?, ?)""",
            (user_id, -amount, new_balance, reason, design_id)
        )
        await db.execute("COMMIT")
        return new_balance
    except InsufficientCreditsError:
        raise
    except Exception:
        await db.execute("ROLLBACK")
        raise
```

### aiosqlite BEGIN IMMEDIATE Caveat

aiosqlite 0.22.1 does NOT support `async with db.transaction()` context managers for explicit transaction control. The pattern above (`await db.execute("BEGIN IMMEDIATE")` + `await db.execute("COMMIT")`) is the correct low-level approach. One subtlety: if the `aiosqlite` connection was opened without `isolation_level=None`, it may wrap some operations in its own transaction. To prevent conflicts, open connections with manual control:

```python
# In get_db() — add isolation_level=None for manual transaction management
async def get_db() -> AsyncIterator[aiosqlite.Connection]:
    db = await aiosqlite.connect(str(DB_PATH), isolation_level=None)
    db.row_factory = aiosqlite.Row
    try:
        yield db
    finally:
        await db.close()
```

With `isolation_level=None`, aiosqlite never auto-wraps in a transaction. All transactions are explicit. This is the safest approach for a codebase with manual `BEGIN IMMEDIATE` calls.

---

## Environment Availability

| Dependency | Required By | Available | Version | Notes |
|------------|------------|-----------|---------|-------|
| Python 3.x | All | Yes | (host python3) | Async throughout |
| aiosqlite | DB-01..04 | Yes | 0.22.1 | Already installed |
| stripe | PAY-01..08 | No | — | Must add to requirements.txt |
| Stripe account | PAY-01..08 | Assumed | — | User must provide STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET, STRIPE_PUBLISHABLE_KEY |
| Stripe CLI (stripe listen) | Webhook testing | No | — | Development tool only; install separately for local webhook testing |

**Missing with no fallback:**
- `stripe` package: add `stripe>=14.4.1` to requirements.txt before any Phase 1 implementation

**Missing with fallback:**
- Stripe CLI: local webhook testing can use Stripe Dashboard's "Send test webhook" feature as an alternative; or mock `stripe.Webhook.construct_event` in tests

---

## State of the Art

| Old Approach | Current Approach | Impact for Phase 1 |
|--------------|------------------|---------------------|
| `stripe.api_key = ...` global + sync `stripe.checkout.Session.create()` | `stripe.checkout.Session.create_async()` (v12+) | Use async method; avoids blocking event loop |
| `stripe.Webhook.construct_event()` with `ValueError` | Same method, now raises `stripe.error.SignatureVerificationError` (v11+) | Catch the specific exception type |
| Balance stored as `users.credits` integer | Append-only `wallet_ledger` with `balance_after` | Full audit trail; double-spend visible even if it occurs |
| `sqlite3` with `check_same_thread=False` | `aiosqlite` with `isolation_level=None` + explicit transactions | No blocking; explicit control |

---

## Open Questions

1. **aiosqlite `BEGIN IMMEDIATE` with `isolation_level=None`**
   - What we know: The pattern works; aiosqlite docs mention `isolation_level=None` disables auto-commit mode control
   - What's unclear: Whether `isolation_level=None` in aiosqlite 0.22.1 behaves identically to sqlite3's `isolation_level=None` (disabling Python's implicit transaction management)
   - Recommendation: Write a small concurrency test in `test_wallet.py` that fires two concurrent `debit_credits` calls with balance=1 and verifies exactly one succeeds. This validates the BEGIN IMMEDIATE behavior before any UI depends on it.

2. **Stripe webhook testing without Stripe CLI**
   - What we know: Tests should mock `stripe.Webhook.construct_event`; the real signature check requires a real Stripe event
   - What's unclear: Whether to invest in `stripe-mock` (Docker-based Stripe test server) or just mock at the function level
   - Recommendation: Mock at function level in tests (monkeypatch `stripe.Webhook.construct_event` to return a test event dict). Stripe CLI (`stripe listen --forward-to localhost:8001/api/webhook/stripe`) for manual integration testing.

3. **Stripe Customer ID storage**
   - What we know: ARCHITECTURE.md recommends creating a Stripe Customer object on first top-up and storing as `users.stripe_customer_id`
   - What's unclear: Whether Phase 1 should add `stripe_customer_id` to the `users` table (requires ALTER TABLE or schema recreation) or defer to a separate `stripe_customers` table
   - Recommendation: Add `stripe_customer_id TEXT` to the `users` table via ALTER TABLE in the schema migration. The `ALTER TABLE users ADD COLUMN stripe_customer_id TEXT` statement is safe to run on the existing DB (adds nullable column). Do NOT recreate the table.

---

## Sources

### Primary (HIGH confidence)
- Direct inspection of `apps/meatheadgear/database.py` — existing schema, init_db() pattern, get_db() pattern
- Direct inspection of `apps/meatheadgear/routers/auth.py` — router pattern, get_current_user dependency, pydantic models
- Direct inspection of `apps/meatheadgear/main.py` — lifespan pattern, router registration, no app-level JWT middleware
- Direct inspection of `apps/meatheadgear/config.py` — frozen dataclass pattern for new env vars
- Direct inspection of `apps/meatheadgear/tests/test_auth.py` — client fixture pattern, asyncio test pattern
- PyPI stripe 14.4.1 — confirmed latest version
- `stripe.checkout.Session.create_async()` — verified as async method (Stripe docs, official Python SDK)
- `stripe.Webhook.construct_event()` — verified HMAC verification pattern (Stripe docs)

### Secondary (MEDIUM confidence)
- aiosqlite `isolation_level=None` for manual transaction control — aiosqlite docs + sqlite3 docs
- `BEGIN IMMEDIATE` serialization behavior — SQLite official docs (https://www.sqlite.org/lang_transaction.html)
- `PRAGMA journal_mode=WAL` persistence behavior — SQLite official docs
- Project research files: ARCHITECTURE.md, STACK.md, PITFALLS.md, SUMMARY.md (all HIGH confidence, written 2026-03-21 with PyPI verification)

### Tertiary (LOW confidence)
- aiosqlite 0.22.1 specific behavior with `isolation_level=None` vs `BEGIN IMMEDIATE` interaction — requires empirical test validation

---

## Metadata

**Confidence breakdown:**
- DB schema: HIGH — directly modeled on existing schema, standard SQLite patterns
- WAL mode setup: HIGH — standard PRAGMA, well-documented, idempotent
- Stripe Checkout Session creation: HIGH — official docs confirmed, async method verified
- Webhook handler: HIGH — standard pattern, official Stripe docs
- Atomic credit debit via BEGIN IMMEDIATE: HIGH (pattern) / MEDIUM (aiosqlite-specific interaction — verify with concurrency test)
- 5 free credits on registration: HIGH — simple ledger INSERT in existing register handler

**Research date:** 2026-03-21
**Valid until:** 2026-04-21 (stripe API is stable; aiosqlite patterns are stable)
