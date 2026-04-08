# Phase 53: Frontend Identity + Sidecar Auth - Context

**Gathered:** 2026-04-08
**Status:** Ready for planning

<domain>
## Phase Boundary

The frontend uses Frood-namespaced storage with automatic migration of existing sessions; external consumers (Paperclip, adapters) can obtain a bearer token from the sidecar. No new features — rename keys, add one endpoint, wire adapter auto-provisioning.

</domain>

<decisions>
## Implementation Decisions

### Token Migration Strategy
- **D-01:** Read-then-write on init — synchronous IIFE runs before `const state = { token: ... }`. Reads `agent42_token`, writes to `frood_token`, deletes old key. All in one synchronous block.
- **D-02:** BroadcastChannel renamed from `agent42_auth` → `frood_auth` (line 152 in app.js). No migration needed — channel name change is a clean cutover. Old+new tab during deploy is a cosmetic edge case (no security risk).
- **D-03:** Migrate then clean break — one-time copy, then only `frood_token` is used. Old key is deleted. Consistent with Phase 52 backend approach.
- **D-04:** `a42_first_done` localStorage key (onboarding flag) should also be migrated to `frood_first_done` in the same migration IIFE if it exists.

### Sidecar /token Endpoint
- **D-05:** POST `/sidecar/token` accepts EITHER `{"username": "...", "password": "..."}` OR `{"api_key": "ak_..."}`. Single endpoint, dispatch on field presence (`api_key` field → device key path, otherwise → password path).
- **D-06:** Password path reuses `verify_password()` + `create_token()` from `dashboard/auth.py`. Device key path uses `DeviceStore.validate_api_key()` from `core/device_auth.py`.
- **D-07:** Token lifetime: 24 hours (matches `TOKEN_EXPIRE_HOURS` constant). Response: `{"token": "<jwt>", "expires_in": 86400}`.
- **D-08:** Rate limiting: reuse existing `check_rate_limit()` on both paths.
- **D-09:** `DeviceStore` dependency injected into sidecar factory as nullable (graceful degradation if absent — password-only mode).

### Adapter Auto-Provisioning (AUTH-02)
- **D-10:** Add `apiKey?: string` to `SidecarConfig` interface in `adapters/agent42-paperclip/src/types.ts` alongside existing `bearerToken`.
- **D-11:** At adapter init: if `apiKey` present and no `bearerToken`, call `POST /sidecar/token` with `{"api_key": apiKey}`, store JWT in-memory as bearer token.
- **D-12:** On 401 response: re-call `/sidecar/token` to refresh token (covers 24h expiry).
- **D-13:** `bearerToken` field preserved for operators who pre-generate tokens (backward compat).

### Settings Path Display
- **D-14:** Update 5 hardcoded description strings in app.js from `.agent42/` to `.frood/` — memory, sessions, outputs, templates, images directories.

### Frontend Cleanup (FE-03)
- **D-15:** After all renames, zero `agent42` references should remain in app.js (case-insensitive, excluding migration code comments).
- **D-16:** Update `tests/test_rebrand_phase51.py` exclusion filter and `tests/e2e/cli.py` localStorage reference to use `frood_token`.

### Claude's Discretion
- Exact IIFE placement and any defensive checks beyond the core migration logic
- Error response format for `/sidecar/token` (400 vs 401 for bad credentials)
- Whether to add a `POST /sidecar/token/refresh` endpoint or just reuse the same endpoint

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Frontend Identity
- `dashboard/frontend/dist/app.js` — All localStorage reads/writes for `agent42_token` (10 occurrences), `BroadcastChannel("agent42_auth")` (line 152), `a42_first_done` (line 140 comment area), settings path descriptions (lines ~1608-1612)
- `tests/test_rebrand_phase51.py` — Exclusion filter on lines 36-37 that skips `agent42_token` and `agent42_auth` — must be updated
- `tests/e2e/cli.py:194` — `localStorage.getItem('agent42_token')` reference — must be updated

### Sidecar Auth
- `dashboard/sidecar.py` — `create_sidecar_app()` factory, existing routes (`/sidecar/health`, `/sidecar/execute`), Bearer auth pattern
- `dashboard/auth.py` — `verify_password()`, `create_token()`, `TOKEN_EXPIRE_HOURS = 24`, `check_rate_limit()`
- `core/device_auth.py` — `DeviceStore.validate_api_key()`, `API_KEY_PREFIX = "ak_"`, HMAC-SHA256 hashing

### Adapter
- `adapters/agent42-paperclip/src/types.ts` — `SidecarConfig` interface with `bearerToken: string`
- `adapters/agent42-paperclip/src/adapter.ts` — Client construction using config
- `adapters/agent42-paperclip/src/client.ts` — `authHeaders()`, bearer token field

### Requirements
- `.planning/workstreams/frood-dashboard/REQUIREMENTS.md` — FE-01, FE-02, FE-03, AUTH-01, AUTH-02, AUTH-03

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `verify_password()` in `dashboard/auth.py` — direct reuse for password credential path
- `create_token()` in `dashboard/auth.py` — JWT generation, reuse for both credential paths
- `DeviceStore.validate_api_key()` in `core/device_auth.py` — device key validation, already HMAC-SHA256 secured
- `check_rate_limit()` in `dashboard/auth.py` — rate limiting, direct reuse
- `/api/login` endpoint pattern in `dashboard/server.py` — analog for `/sidecar/token`

### Established Patterns
- Sidecar routes follow `/sidecar/{action}` convention
- Sidecar factory accepts nullable dependencies (key_store, mcp_registry) — `DeviceStore` follows same pattern
- Frontend auth flow: login → set token → BroadcastChannel sync → state.token
- app.js is vanilla JS (~1800 lines), no build step — edit `dashboard/frontend/dist/app.js` directly

### Integration Points
- `/sidecar/token` connects to `auth.py` (password) and `device_auth.py` (API key)
- Adapter `SidecarConfig` connects to Paperclip plugin configuration
- localStorage migration connects to existing state initialization in app.js

</code_context>

<specifics>
## Specific Ideas

- Migration IIFE must run BEFORE `const state = { token: localStorage.getItem(...) }` — ordering is critical
- `a42_first_done` key should be migrated alongside the token in the same IIFE
- After migration, old key must be deleted to prevent re-migration loops
- Guard: only migrate if `frood_token` doesn't already exist (prevents overwriting a refreshed token with a stale old one)
- Phase 52's clean break pattern: no fallback, just migrate and move on

</specifics>

<deferred>
## Deferred Ideas

- **Token refresh endpoint** — `/sidecar/token/refresh` for explicit refresh. Currently, re-calling `/sidecar/token` serves the same purpose. Add if needed later.
- **Adapter package rename** — `@agent42/paperclip-adapter` → `@frood/paperclip-adapter`. Phase 54 scope (NPM-01).
- **Qdrant collection names in frontend** — Not surfaced in app.js. Phase 55 scope.

</deferred>

---

*Phase: 53-frontend-identity-sidecar-auth*
*Context gathered: 2026-04-08*
