# Phase 53: Frontend Identity + Sidecar Auth - Research

**Researched:** 2026-04-08
**Domain:** Vanilla JS localStorage migration, BroadcastChannel rename, FastAPI auth endpoint, TypeScript adapter auto-provisioning
**Confidence:** HIGH

## Summary

This phase is a well-scoped rename + small feature addition. The frontend work is vanilla JS edits to a single minified-but-readable file (`dashboard/frontend/dist/app.js`). The sidecar auth work adds one new FastAPI endpoint (`POST /sidecar/token`) that reuses existing `auth.py` functions. The adapter work adds an optional `apiKey` field to the TypeScript `SidecarConfig` interface with auto-provisioning logic.

All backend functions needed (`verify_password`, `create_token`, `check_rate_limit`, `DeviceStore.validate_api_key`) already exist and are tested. No new dependencies are required. The primary risk is ordering: the localStorage migration IIFE must execute before `const state = { token: localStorage.getItem("agent42_token") }` on line 8 of app.js, and the `DeviceStore` needs to be instantiated in `frood.py` and injected into `create_sidecar_app()`.

`a42_first_done` appears only in a comment (line 140) in app.js — it is NOT used in actual code. D-04 (migrate `a42_first_done`) should migrate the key if it exists, but there is nothing in the current app code that writes or reads it. The guard is still correct: check for existence before migrating.

**Primary recommendation:** Work in four discrete units — (1) app.js localStorage/BroadcastChannel rename + migration IIFE, (2) settings path description strings, (3) `POST /sidecar/token` endpoint in sidecar.py, (4) adapter auto-provisioning in TypeScript.

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Token Migration Strategy**
- D-01: Read-then-write on init — synchronous IIFE runs before `const state = { token: ... }`. Reads `agent42_token`, writes to `frood_token`, deletes old key. All in one synchronous block.
- D-02: BroadcastChannel renamed from `agent42_auth` → `frood_auth` (line 152 in app.js). No migration needed — channel name change is a clean cutover. Old+new tab during deploy is a cosmetic edge case (no security risk).
- D-03: Migrate then clean break — one-time copy, then only `frood_token` is used. Old key is deleted. Consistent with Phase 52 backend approach.
- D-04: `a42_first_done` localStorage key (onboarding flag) should also be migrated to `frood_first_done` in the same migration IIFE if it exists.

**Sidecar /token Endpoint**
- D-05: POST `/sidecar/token` accepts EITHER `{"username": "...", "password": "..."}` OR `{"api_key": "ak_..."}`. Single endpoint, dispatch on field presence (`api_key` field → device key path, otherwise → password path).
- D-06: Password path reuses `verify_password()` + `create_token()` from `dashboard/auth.py`. Device key path uses `DeviceStore.validate_api_key()` from `core/device_auth.py`.
- D-07: Token lifetime: 24 hours (matches `TOKEN_EXPIRE_HOURS` constant). Response: `{"token": "<jwt>", "expires_in": 86400}`.
- D-08: Rate limiting: reuse existing `check_rate_limit()` on both paths.
- D-09: `DeviceStore` dependency injected into sidecar factory as nullable (graceful degradation if absent — password-only mode).

**Adapter Auto-Provisioning (AUTH-02)**
- D-10: Add `apiKey?: string` to `SidecarConfig` interface in `adapters/agent42-paperclip/src/types.ts` alongside existing `bearerToken`.
- D-11: At adapter init: if `apiKey` present and no `bearerToken`, call `POST /sidecar/token` with `{"api_key": apiKey}`, store JWT in-memory as bearer token.
- D-12: On 401 response: re-call `/sidecar/token` to refresh token (covers 24h expiry).
- D-13: `bearerToken` field preserved for operators who pre-generate tokens (backward compat).

**Settings Path Display**
- D-14: Update 5 hardcoded description strings in app.js from `.agent42/` to `.frood/` — memory, sessions, outputs, templates, images directories.

**Frontend Cleanup (FE-03)**
- D-15: After all renames, zero `agent42` references should remain in app.js (case-insensitive, excluding migration code comments).
- D-16: Update `tests/test_rebrand_phase51.py` exclusion filter and `tests/e2e/cli.py` localStorage reference to use `frood_token`.

### Claude's Discretion
- Exact IIFE placement and any defensive checks beyond the core migration logic
- Error response format for `/sidecar/token` (400 vs 401 for bad credentials)
- Whether to add a `POST /sidecar/token/refresh` endpoint or just reuse the same endpoint

### Deferred Ideas (OUT OF SCOPE)
- **Token refresh endpoint** — `/sidecar/token/refresh` for explicit refresh. Currently, re-calling `/sidecar/token` serves the same purpose. Add if needed later.
- **Adapter package rename** — `@agent42/paperclip-adapter` → `@frood/paperclip-adapter`. Phase 54 scope (NPM-01).
- **Qdrant collection names in frontend** — Not surfaced in app.js. Phase 55 scope.
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| FE-01 | localStorage key renamed from `agent42_token` to `frood_token` (with migration on load) | Migration IIFE pattern documented; 10 call sites identified in app.js |
| FE-02 | BroadcastChannel renamed from `agent42_auth` to `frood_auth` | Single occurrence at line 152; clean cutover with no migration needed |
| FE-03 | Zero `agent42` references remain in `app.js` (case-insensitive, excluding migration comments) | 5 remaining `.agent42/` path strings at lines 1608-1612; token/channel already covered by FE-01/FE-02 |
| AUTH-01 | Sidecar exposes a `/sidecar/token` endpoint that generates a JWT given valid credentials | `verify_password()`, `create_token()`, `check_rate_limit()`, `DeviceStore.validate_api_key()` all available for reuse |
| AUTH-02 | Adapter config accepts `apiKey` field that auto-provisions a bearer token on first connect | `SidecarConfig` in types.ts + `parseSidecarConfig()` + `Agent42Client` all ready for extension |
| AUTH-03 | Sidecar health endpoint (`/sidecar/health`) remains unauthenticated for container probes | Already implemented at line 146 of sidecar.py with no auth dependency; no changes needed |
</phase_requirements>

---

## Standard Stack

### Core (no new dependencies needed)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| FastAPI | existing | `POST /sidecar/token` route | Already used for all sidecar routes |
| python-jose | existing | JWT creation via `create_token()` | Used by `dashboard/auth.py` already |
| bcrypt | existing | Password verification via `verify_password()` | Used by `dashboard/auth.py` already |
| Pydantic BaseModel | existing | Request/response model for `/sidecar/token` | Project standard for all FastAPI models |
| TypeScript (native fetch) | existing | Adapter HTTP calls | Project decision D-15/D-16 from Phase 27 — no external HTTP lib |

**No new pip or npm packages required for this phase.**

### Key Files to Edit

| File | Change Type | Lines Affected |
|------|-------------|----------------|
| `dashboard/frontend/dist/app.js` | Migration IIFE + 10 token/auth renames + 5 path strings | 1, 8, 152, 157, 162, 189, 298, 704, 742, 773, 1608-1612 |
| `dashboard/sidecar.py` | New `POST /sidecar/token` endpoint + `device_store` param | Factory signature + new route |
| `frood.py` | Instantiate `DeviceStore` + pass to `create_sidecar_app()` | ~130-278 (Frood class init + sidecar setup) |
| `adapters/agent42-paperclip/src/types.ts` | Add `apiKey?: string` to `SidecarConfig` + update `parseSidecarConfig()` | Lines 21-57 |
| `adapters/agent42-paperclip/src/adapter.ts` | Auto-provisioning logic + 401 retry | Lines 46-116 |
| `adapters/agent42-paperclip/src/client.ts` | Update `bearerToken` field to be mutable (for refresh) | Constructor + `authHeaders()` |
| `tests/test_rebrand_phase51.py` | Remove exclusion filter for `agent42_token` / `agent42_auth` | Lines 36-37 |
| `tests/e2e/cli.py` | Update `localStorage.getItem('agent42_token')` | Line 194 |

---

## Architecture Patterns

### Pattern 1: localStorage Migration IIFE

The migration block must execute **before** `const state = { token: localStorage.getItem(...) }` on line 8. The current file structure is:

```
Line 1:   /* Frood Dashboard — Single-page Application */
Line 2:   "use strict";
Line 4:   // State
Line 7:   const state = {
Line 8:     token: localStorage.getItem("agent42_token") || "",
```

The IIFE goes between line 4 comment and line 7. Pattern:

```javascript
// One-time migration: agent42 -> frood namespace (Phase 53)
(function migrateStorage() {
  if (!localStorage.getItem("frood_token")) {
    const old = localStorage.getItem("agent42_token");
    if (old) {
      localStorage.setItem("frood_token", old);
      localStorage.removeItem("agent42_token");
    }
  } else {
    // frood_token already set — just clean up old key if it lingers
    localStorage.removeItem("agent42_token");
  }
  // Migrate onboarding flag
  if (!localStorage.getItem("frood_first_done") && localStorage.getItem("a42_first_done")) {
    localStorage.setItem("frood_first_done", localStorage.getItem("a42_first_done"));
    localStorage.removeItem("a42_first_done");
  }
})();
```

Then line 8 becomes: `token: localStorage.getItem("frood_token") || ""`

**Critical ordering note:** `a42_first_done` only appears in a comment in the current app.js code (line 140). It is NOT actively written or read by any live code path. The IIFE migration for it is still correct defensively, but there are no other call sites to update.

### Pattern 2: BroadcastChannel Rename (line 152)

Clean cutover — change the string literal only:

```javascript
// Before:
const _authChannel = typeof BroadcastChannel !== "undefined" ? new BroadcastChannel("agent42_auth") : null;

// After:
const _authChannel = typeof BroadcastChannel !== "undefined" ? new BroadcastChannel("frood_auth") : null;
```

No data migration needed. A tab on the old channel simply won't receive messages from a tab on the new channel — this is acceptable per D-02.

### Pattern 3: POST /sidecar/token Endpoint

Analog to `/api/login` in `server.py` but for the sidecar. Follow the existing sidecar pattern exactly:

```python
# In sidecar.py — create_sidecar_app() factory params:
def create_sidecar_app(
    ...
    device_store: Any = None,   # <-- new param (nullable per D-09)
) -> FastAPI:

# Pydantic model (define inside or above factory, matching server.py style):
class SidecarTokenRequest(BaseModel):
    username: str = ""
    password: str = ""
    api_key: str = ""

class SidecarTokenResponse(BaseModel):
    token: str
    expires_in: int = 86400

# Route (placed after /sidecar/health, before /sidecar/execute):
@app.post("/sidecar/token", response_model=SidecarTokenResponse)
async def sidecar_token(req: SidecarTokenRequest, request: Request) -> SidecarTokenResponse:
    """Issue a JWT for external consumers (Paperclip adapters, automation).

    Accepts either username+password OR api_key (ak_... device key).
    Rate limited on both paths. DeviceStore is optional — omitted means
    password-only mode.
    AUTH-01, D-05 through D-09.
    """
    from dashboard.auth import check_rate_limit, create_token, verify_password
    client_ip = request.client.host if request.client else "unknown"

    if not check_rate_limit(client_ip):
        raise HTTPException(status_code=429, detail="Too many attempts.")

    if req.api_key:
        # Device key path (D-06)
        if device_store is None:
            raise HTTPException(status_code=503, detail="Device auth not available")
        device = device_store.validate_api_key(req.api_key)
        if not device:
            raise HTTPException(status_code=401, detail="Invalid API key")
        username = f"device:{device.device_id}"
    else:
        # Password path (D-06)
        from core.config import settings as _settings
        if req.username != _settings.dashboard_username or not verify_password(req.password):
            raise HTTPException(status_code=401, detail="Invalid credentials")
        username = req.username

    token = create_token(username)
    return SidecarTokenResponse(token=token, expires_in=86400)
```

**Import pattern:** `dashboard.auth` is already imported at module level (`from dashboard.auth import get_current_user`). Add `check_rate_limit`, `create_token`, `verify_password` to that import.

**Request import:** `from fastapi import ..., Request` — `Request` is already in the FastAPI imports at the top of sidecar.py.

### Pattern 4: DeviceStore Injection in frood.py

`frood.py` already instantiates `KeyStore` in `Frood.__init__()`. DeviceStore follows the same pattern:

```python
# In Frood.__init__():
from core.device_auth import DeviceStore
self.device_store = DeviceStore(data_dir / "devices.jsonl")

# In sidecar app creation (~line 268):
app = create_sidecar_app(
    ...
    key_store=self.key_store,
    device_store=self.device_store,   # <-- new
)
```

### Pattern 5: Adapter Auto-Provisioning

The `Agent42Client` constructor currently takes `bearerToken: string` as a readonly field. For token refresh to work (D-12), the bearer token must be mutable. The cleanest approach is:

**Option A (preferred):** Make `bearerToken` a private mutable field in `Agent42Client`:
```typescript
export class Agent42Client {
  private bearerToken: string;  // mutable (was readonly)

  constructor(
    private readonly baseUrl: string,
    bearerToken: string,
  ) {
    this.bearerToken = bearerToken;
  }

  // New method for token refresh
  setBearerToken(token: string): void {
    this.bearerToken = token;
  }
}
```

**Option B:** Keep client immutable, store token in adapter's closure and recreate client on refresh. Simpler for the adapter but less clean.

The CONTEXT.md decision D-11 says "store JWT in-memory as bearer token" — this implies Option A or a mutable holder in the adapter closure. The discretion is left to the planner.

**Auto-provisioning in adapter.ts:**

```typescript
// In execute():
const config = parseSidecarConfig(ctx.agent.adapterConfig);
let bearerToken = config.bearerToken;

// Auto-provision if apiKey present and no bearerToken (D-11)
if (config.apiKey && !bearerToken) {
  bearerToken = await provisionToken(config.sidecarUrl, config.apiKey);
}

const client = new Agent42Client(config.sidecarUrl, bearerToken);

// On 401, refresh and retry once (D-12)
try {
  return await client.execute(sidecarBody);
} catch (err) {
  if (is401(err) && config.apiKey) {
    bearerToken = await provisionToken(config.sidecarUrl, config.apiKey);
    client.setBearerToken(bearerToken);
    return await client.execute(sidecarBody);
  }
  throw err;
}
```

`provisionToken` is a small helper that POSTs to `/sidecar/token`:
```typescript
async function provisionToken(sidecarUrl: string, apiKey: string): Promise<string> {
  const resp = await fetch(`${sidecarUrl}/sidecar/token`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ api_key: apiKey }),
  });
  if (!resp.ok) throw new Error(`Token provisioning failed: HTTP ${resp.status}`);
  const data = await resp.json();
  return data.token;
}
```

### Pattern 6: parseSidecarConfig Extension

Add `apiKey` alongside `bearerToken` with the same defensive parsing pattern:

```typescript
export interface SidecarConfig {
  sidecarUrl: string;
  bearerToken: string;
  apiKey: string;        // <-- new, optional in source but string in normalized form
  agentId: string;
  preferredProvider: string;
  memoryScope: string;
}

// In parseSidecarConfig():
return {
  ...existing fields...
  apiKey: typeof r["apiKey"] === "string" ? r["apiKey"] : defaults.apiKey,
};
```

`defaults.apiKey` is `""` — consistent with `bearerToken` default.

### Anti-Patterns to Avoid

- **Don't migrate then read old key:** The IIFE must delete `agent42_token` after copying. If it only copies without deleting, the guard (`!localStorage.getItem("frood_token")`) prevents overwrite on re-load, but the old key lingers and fails FE-03's zero-`agent42` test.
- **Don't place IIFE after `const state`:** The state object reads `agent42_token` at initialization. The IIFE must run first or `state.token` will always be empty for migrating users.
- **Don't make DeviceStore required in sidecar factory:** D-09 says nullable. Operators who don't use device auth must still get a working sidecar.
- **Don't bypass `check_rate_limit` for api_key path:** D-08 requires rate limiting on both paths.
- **Don't forget to update `create_sidecar_app()` call in frood.py:** The factory signature change is meaningless unless the call site also passes `device_store`.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| JWT generation | Custom token signing | `create_token()` in `dashboard/auth.py` | Already handles expiry, secret, algorithm |
| Password verification | Custom bcrypt check | `verify_password()` in `dashboard/auth.py` | Handles both hash and plaintext fallback |
| Rate limiting | Custom counter | `check_rate_limit()` in `dashboard/auth.py` | Already uses windowed counter per IP |
| API key hashing | Custom SHA-256 | `DeviceStore.validate_api_key()` | Already handles HMAC-SHA256 + legacy migration |

---

## Runtime State Inventory

| Category | Items Found | Action Required |
|----------|-------------|-----------------|
| Stored data (localStorage) | `agent42_token` — user JWT stored client-side in browser localStorage | IIFE migration in app.js: copy to `frood_token`, delete old key |
| Stored data (localStorage) | `a42_first_done` — onboarding flag; **only in a comment** in current app.js, no live code writes/reads it | Defensive migration in IIFE (safe to include, will no-op for most users) |
| Live service config | BroadcastChannel `agent42_auth` — in-memory, tab-lifetime only | Clean cutover (rename string at line 152); no migration of existing channel data |
| OS-registered state | None — verified by search | None |
| Secrets/env vars | None — no env vars for client-side storage keys | None |
| Build artifacts | app.js is edited directly (no build step per CONTEXT.md) | Edit `dashboard/frontend/dist/app.js` directly |

---

## Common Pitfalls

### Pitfall 1: Migration IIFE Ordering
**What goes wrong:** IIFE placed after `const state = {...}` → `state.token` initializes to `""` because `agent42_token` was already deleted, and `frood_token` hasn't been set yet in the same JS execution tick.
**Why it happens:** JavaScript `const` declarations with initializers execute immediately. The IIFE must be a statement, not a function declaration, and must appear before the `state` const.
**How to avoid:** Place IIFE between the `"use strict";` section and the `// State` comment block. Verify by grepping `const state` — IIFE must appear before it.
**Warning signs:** Users get logged out on first visit after deploy despite having a valid `agent42_token` in browser.

### Pitfall 2: Double Migration Loop
**What goes wrong:** If the guard is `if (!localStorage.getItem("frood_token")) { copy; }` only, and the old key is NOT deleted, then on next page load `frood_token` exists (skip migration) but `agent42_token` still exists (fails FE-03 test).
**Why it happens:** Missing `localStorage.removeItem("agent42_token")` in the "already migrated" branch.
**How to avoid:** Always delete `agent42_token` — both in the migration branch AND in the "already migrated" guard branch (as shown in Pattern 1 above).

### Pitfall 3: test_no_agent42_visible Still Excluding Old Keys
**What goes wrong:** Phase 51's `test_rebrand_phase51.py` at lines 36-37 excludes lines containing `agent42_token` and `agent42_auth`. After Phase 53, those exclusions must be removed — otherwise the test silently passes even if old keys are still present.
**Why it happens:** The exclusion was intentionally added in Phase 51 to defer Phase 53 work. D-16 explicitly calls this out.
**How to avoid:** Remove `"agent42_token" not in line` and `"agent42_auth" not in line` from the filter. The test will then fail unless FE-01 and FE-02 are complete.

### Pitfall 4: sidecar_client fixture doesn't pass device_store
**What goes wrong:** New tests for `POST /sidecar/token` call `create_sidecar_app()` without `device_store` → 503 on api_key path, always.
**Why it happens:** The existing `sidecar_client` fixture uses `create_sidecar_app()` with no args.
**How to avoid:** Add a new fixture `sidecar_client_with_device_store` that creates a temp `DeviceStore` and passes it in, for the api_key test path.

### Pitfall 5: Agent42Client.bearerToken is readonly
**What goes wrong:** TypeScript compile error when trying to update `bearerToken` after token refresh if the field stays `readonly`.
**Why it happens:** The current constructor declares `private readonly bearerToken: string`.
**How to avoid:** Change to `private bearerToken: string` (remove `readonly`) and add `setBearerToken()` method, or pass token via closure.

### Pitfall 6: frood.py sidecar creation missing device_store
**What goes wrong:** `DeviceStore` is instantiated in `Frood.__init__()` but `create_sidecar_app()` call (line ~268) doesn't pass it → api_key path always returns 503 in production.
**Why it happens:** Developer adds param to factory but forgets to update the call site in frood.py.
**How to avoid:** Update both the factory signature AND the call site in `frood.py` in the same task/commit.

---

## Code Examples

### app.js: Full Changeset Summary

```javascript
// 1. Migration IIFE (INSERT before "const state = {")
(function migrateStorage() {
  if (!localStorage.getItem("frood_token")) {
    var _old = localStorage.getItem("agent42_token");
    if (_old) { localStorage.setItem("frood_token", _old); }
  }
  localStorage.removeItem("agent42_token");
  if (!localStorage.getItem("frood_first_done")) {
    var _oldflag = localStorage.getItem("a42_first_done");
    if (_oldflag) { localStorage.setItem("frood_first_done", _oldflag); }
  }
  localStorage.removeItem("a42_first_done");
})();

// 2. state.token (line 8): agent42_token -> frood_token
token: localStorage.getItem("frood_token") || "",

// 3. BroadcastChannel (line 152): agent42_auth -> frood_auth
new BroadcastChannel("frood_auth")

// 4. All localStorage calls: agent42_token -> frood_token
// Lines: 157, 162, 189, 298, 704, 742, 773

// 5. Settings descriptions (lines 1608-1612): .agent42/ -> .frood/
"Default: .frood/memory. ..."
"Default: .frood/sessions. ..."
// etc.
```

**Exact occurrences of `agent42_token` in app.js (10 total):**
- Line 8: `localStorage.getItem("agent42_token")`
- Line 139 (comment only — leave or update to frood_token)
- Line 157: `localStorage.removeItem("agent42_token")`
- Line 162: `localStorage.setItem("agent42_token", ev.data.token)`
- Line 189: `localStorage.removeItem("agent42_token")`
- Line 298: `localStorage.setItem("agent42_token", data.token)`
- Line 704: `localStorage.setItem("agent42_token", data.token)`
- Line 742: `localStorage.setItem("agent42_token", data.token)`
- Line 773: `localStorage.removeItem("agent42_token")`

**Note:** The migration IIFE itself may reference `agent42_token` — these references are in the migration code and should be excluded from the FE-03 "zero agent42" assertion (per D-15: "excluding migration code comments"). The test already handles this via comment exclusion. Better to phrase as an inline comment: `// migrate from agent42_token`.

### sidecar.py: SidecarTokenRequest Pydantic Model

```python
class SidecarTokenRequest(BaseModel):
    """Request body for POST /sidecar/token.

    Either username+password OR api_key must be provided.
    D-05: dispatches on field presence.
    """
    username: str = ""
    password: str = ""
    api_key: str = ""


class SidecarTokenResponse(BaseModel):
    """Response for POST /sidecar/token. D-07."""
    token: str
    expires_in: int = TOKEN_EXPIRE_HOURS * 3600  # 86400
```

`TOKEN_EXPIRE_HOURS` is importable from `dashboard.auth`.

### tests/test_sidecar.py: New Test Class

```python
class TestSidecarToken:
    """AUTH-01: /sidecar/token endpoint."""

    @pytest.fixture
    def sidecar_client_with_devices(self, tmp_path):
        from core.device_auth import DeviceStore
        ds = DeviceStore(tmp_path / "devices.jsonl")
        app = create_sidecar_app(device_store=ds)
        return TestClient(app), ds

    def test_token_password_path_returns_jwt(self, ...):
        # POST /sidecar/token with username+password

    def test_token_api_key_path_returns_jwt(self, sidecar_client_with_devices):
        # POST /sidecar/token with api_key

    def test_token_no_device_store_503(self, sidecar_client):
        # sidecar_client has no device_store; api_key path returns 503

    def test_token_invalid_password_401(self, ...): ...
    def test_token_invalid_api_key_401(self, sidecar_client_with_devices): ...
    def test_token_rate_limited_429(self, ...): ...
    def test_health_still_unauthenticated(self, sidecar_client): ...  # AUTH-03 regression
```

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest (existing) |
| Config file | `pytest.ini` or `pyproject.toml` (check existing) |
| Quick run command | `python -m pytest tests/test_sidecar.py tests/test_rebrand_phase51.py -x -q` |
| Full suite command | `python -m pytest tests/ -x -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| FE-01 | `frood_token` is read; `agent42_token` is absent | unit (static analysis) | `pytest tests/test_rebrand_phase51.py -x -q` | Yes (exclusion filter must be removed) |
| FE-02 | `BroadcastChannel("frood_auth")` present; `agent42_auth` absent | unit (static analysis) | `pytest tests/test_rebrand_phase51.py -x -q` | Yes (exclusion filter must be removed) |
| FE-03 | Zero `agent42` in app.js outside migration comments | unit (static analysis) | `pytest tests/test_rebrand_phase51.py -x -q` | Yes (after exclusion filter removal) |
| AUTH-01 | `POST /sidecar/token` returns 200 + JWT for valid creds | unit (FastAPI TestClient) | `pytest tests/test_sidecar.py -x -q` | No — Wave 0 gap |
| AUTH-02 | Adapter auto-provisions token when `apiKey` set | unit (TypeScript) | `npm test` in adapters/agent42-paperclip | No — Wave 0 gap |
| AUTH-03 | `/sidecar/health` returns 200 without auth | unit (regression) | `pytest tests/test_sidecar.py::TestSidecarHealth -x -q` | Yes (existing passing test) |

### Wave 0 Gaps

- [ ] `tests/test_sidecar.py` — add `TestSidecarToken` class covering AUTH-01 (password path, api_key path, 503 no device store, 401 bad creds, 429 rate limited)
- [ ] `adapters/agent42-paperclip/src/__tests__/adapter.test.ts` — if it exists, add test for apiKey auto-provisioning; if not, manual verification only
- [ ] `tests/test_rebrand_phase51.py` — remove exclusion filter lines 36-37 (D-16). This is a test UPDATE, not a new test.
- [ ] `tests/e2e/cli.py` line 194 — update `agent42_token` → `frood_token` (D-16). This is a code UPDATE, not a new test.

---

## Environment Availability

Step 2.6: SKIPPED (no external dependencies — all changes are code/config edits to existing files; no new services, databases, or CLI tools required).

---

## Open Questions

1. **IIFE comment exclusion in test_rebrand_phase51.py**
   - What we know: FE-03 (D-15) says exclude "migration code comments" from the zero-agent42 check.
   - What's unclear: The migration IIFE itself uses the string `"agent42_token"` as a JavaScript string literal, not a comment. The test filters by line. If the IIFE lines contain `agent42_token`, they'll still be filtered by the existing exclusion logic — but that exclusion is being REMOVED in D-16.
   - Recommendation: The IIFE should use a variable approach or inline comment to make exclusion explicit: `var _oldKey = "agent42_token"; // migrate`. OR the test should add a new exclusion for lines that contain both `agent42_token` AND `migrate`. The planner should decide which pattern to use for the test exclusion of migration code.

2. **Agent42Client mutable bearerToken**
   - What we know: Current client has `private readonly bearerToken`.
   - What's unclear: The planner has discretion on whether to use Option A (mutable field + setter) or Option B (closure-based token holder in adapter.ts).
   - Recommendation: Option A (mutable field) is cleaner since the client owns the auth state. Option B avoids touching client.ts. Either works.

3. **Username for device key JWT subject**
   - What we know: `create_token(username)` sets the JWT `sub` claim. For device key path, there's no "username" — D-09 suggests `device:{device_id}`.
   - What's unclear: Whether downstream token validation (`get_current_user`) or anything that reads `sub` will break on a `device:` prefixed subject.
   - Recommendation: Check `get_current_user` usage — it only returns `ctx.user` (the `sub` claim) and nothing downstream validates the format. `device:{device_id}` is safe. Use it.

---

## Sources

### Primary (HIGH confidence)
- Direct code inspection of `dashboard/auth.py` — all functions (`verify_password`, `create_token`, `check_rate_limit`, `TOKEN_EXPIRE_HOURS`) verified
- Direct code inspection of `core/device_auth.py` — `DeviceStore.validate_api_key()`, `API_KEY_PREFIX` verified
- Direct code inspection of `dashboard/sidecar.py` — factory pattern, existing route structure, `get_current_user` dependency injection verified
- Direct code inspection of `dashboard/frontend/dist/app.js` — all 10 `agent42_token` occurrences line-identified, 1 BroadcastChannel occurrence at line 152 confirmed, 5 `.agent42/` path strings at lines 1608-1612 confirmed, `a42_first_done` confirmed as comment-only (no live usage)
- Direct code inspection of `adapters/agent42-paperclip/src/types.ts` — `SidecarConfig` interface verified, `parseSidecarConfig()` pattern verified
- Direct code inspection of `adapters/agent42-paperclip/src/client.ts` — `bearerToken` as `readonly`, `authHeaders()` method verified
- Direct code inspection of `tests/test_rebrand_phase51.py` lines 36-37 — exclusion filter confirmed
- Direct code inspection of `tests/e2e/cli.py` line 194 — `agent42_token` reference confirmed
- Direct code inspection of `frood.py` — `DeviceStore` NOT yet instantiated; `KeyStore` injection pattern available as model

### Secondary (MEDIUM confidence)
- `.planning/workstreams/frood-dashboard/phases/53-frontend-identity-sidecar-auth/53-CONTEXT.md` — all decisions (D-01 through D-16) read and incorporated

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries are existing project dependencies, no new installs
- Architecture: HIGH — all patterns verified against live code; no assumptions
- Pitfalls: HIGH — pitfalls derived from actual code inspection, not speculation

**Research date:** 2026-04-08
**Valid until:** 2026-05-08 (stable codebase, no fast-moving external deps)
