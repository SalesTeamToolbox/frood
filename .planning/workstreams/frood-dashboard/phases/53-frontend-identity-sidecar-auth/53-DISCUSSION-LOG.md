# Phase 53: Frontend Identity + Sidecar Auth - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-08
**Phase:** 53-frontend-identity-sidecar-auth
**Areas discussed:** Token migration strategy, Sidecar /token endpoint, Settings path display, Clean break vs fallback

---

## Token Migration Strategy

| Option | Description | Selected |
|--------|-------------|----------|
| Read-then-write on init | Synchronous IIFE before state init: copy agent42_token → frood_token, delete old key. Zero re-login, each tab self-migrates. | ✓ |
| Force re-login | Just rename keys. All users must re-login once. Simplest code but worst UX. | |
| Lazy on API call | Only migrate when api() needs the token. Risk: premature logged-out render, cross-tab race. | |

**User's choice:** Read-then-write on init (Recommended)
**Notes:** Synchronous migration guarantees no render flash. Each tab self-migrates independently.

---

## Sidecar /token Endpoint

| Option | Description | Selected |
|--------|-------------|----------|
| Both password + API key | Single endpoint, dispatch on field presence. Adapters use apiKey path, admin uses password as fallback. Reuses both existing auth systems. | ✓ |
| API key only | Cleaner for machine consumers. Admin must create a device key to use the endpoint. | |
| Password only | Simpler, but adapter config must store the admin password — security downgrade. | |

**User's choice:** Both password + API key (Recommended)
**Notes:** Reuses both existing credential systems. Device keys for adapters, password for admin fallback.

---

## Settings Path Display

| Option | Description | Selected |
|--------|-------------|----------|
| Rename to .frood/ | Update the 5 hardcoded description strings in app.js from '.agent42/' to '.frood/'. Consistent with Phase 52 config changes. | ✓ |
| Remove path from description | Just show description text without the default path. Less maintenance. | |
| Leave as-is | Keep '.agent42/' in descriptions. Technically accurate for unmigrated deployments. | |

**User's choice:** Rename to .frood/ (Recommended)
**Notes:** Part of FE-03 (zero agent42 refs in app.js).

---

## Clean Break vs Fallback

| Option | Description | Selected |
|--------|-------------|----------|
| Migrate then clean break | One-time migration copies agent42_token → frood_token. After that, only frood_token used. Old key deleted. Consistent with backend. | ✓ |
| Permanent dual-read fallback | Always check frood_token first, fall back to agent42_token. Old key stays forever. | |
| Time-limited fallback | Read both for N days, then remove fallback in a future release. | |

**User's choice:** Migrate then clean break (Recommended)
**Notes:** Consistent with Phase 52 backend approach. No long-term tech debt.

---

## Claude's Discretion

- IIFE placement details and defensive checks
- Error response format for /sidecar/token
- Whether to add a /sidecar/token/refresh endpoint

## Deferred Ideas

- Token refresh endpoint — re-calling /sidecar/token serves the same purpose for now
- Adapter package rename — Phase 54 scope (NPM-01)
