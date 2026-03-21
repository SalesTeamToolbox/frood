---
phase: 01-store-foundation
plan: 02
subsystem: auth
tags: [jwt, bcrypt, fastapi, sqlite, password-reset]

requires:
  - phase: 01-store-foundation-01
    provides: FastAPI app skeleton, aiosqlite database with users table, frozen Settings config

provides:
  - JWT-based customer authentication (register, login, session persistence)
  - bcrypt password hashing via direct bcrypt library (not passlib)
  - Password reset token flow stored in users.reset_token/reset_token_expires
  - auth router mounted at /api/auth with 5 endpoints

affects:
  - 01-store-foundation-03 (catalog router — mounted alongside auth in main.py)
  - 02-design-studio (requires auth for customer identification)
  - 03-checkout (requires auth for order association)

tech-stack:
  added:
    - python-jose[cryptography] (JWT encode/decode with HS256)
    - bcrypt>=4.0 direct (password hashing — passlib dropped due to bcrypt>=4.0 incompatibility)
  patterns:
    - Direct bcrypt library usage (not passlib) due to bcrypt 5.x breaking passlib integration
    - FastAPI HTTPBearer with auto_error=False for clean 401 responses
    - No-enumeration pattern for login (same error for wrong email vs wrong password) and reset-request (always 200)
    - Timing-attack mitigation: dummy verify_password call on non-existent user login path

key-files:
  created:
    - apps/meatheadgear/services/auth.py
    - apps/meatheadgear/routers/auth.py
    - apps/meatheadgear/tests/test_auth.py
  modified:
    - apps/meatheadgear/main.py

key-decisions:
  - "Use bcrypt directly (not passlib) — passlib is incompatible with bcrypt>=4.0/5.x due to bcrypt wrap-bug detection change"
  - "Resend email integration stubbed — token logged to console; actual email sending requires Resend API key in a later plan"
  - "HTTPBearer with auto_error=False — allows custom 401 JSON responses instead of FastAPI default format"

patterns-established:
  - "Auth service pattern: pure functions in services/auth.py (no class), router imports from services"
  - "No-enumeration security: login and reset-request never distinguish between wrong email vs wrong password"
  - "Timing attack mitigation: always call verify_password even for non-existent users"

requirements-completed: [AUTH-01, AUTH-02, AUTH-03, AUTH-04]

duration: 15min
completed: 2026-03-20
---

# Phase 01 Plan 02: Auth — Customer Authentication Summary

**JWT auth with bcrypt password hashing, 5 FastAPI endpoints covering register/login/session/password-reset, and no-enumeration security patterns**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-03-20T06:15:00Z
- **Completed:** 2026-03-20T06:30:00Z
- **Tasks:** 1 (TDD: tests + implementation)
- **Files modified:** 4

## Accomplishments

- Customer registration with bcrypt-hashed password stored in users table (AUTH-01)
- Login endpoint returning HS256 JWT valid for 7 days (AUTH-02)
- GET /api/auth/me verifies JWT and returns user profile for session persistence (AUTH-03)
- Password reset flow: reset-request stores token in DB, reset-confirm validates + changes password (AUTH-04)
- 13 tests covering all 4 AUTH requirements, all passing green
- Fixed parallel plan conflict: added missing `catalog_router` import in main.py

## Task Commits

Each task was committed atomically:

1. **Task 1: Auth service and API endpoints** - `fe6b22b` (feat)

**Plan metadata:** (docs commit to follow)

_Note: TDD task — tests and implementation committed together after GREEN phase_

## Files Created/Modified

- `apps/meatheadgear/services/auth.py` - Auth utilities: hash_password, verify_password, create_access_token, verify_access_token, generate_reset_token
- `apps/meatheadgear/routers/auth.py` - Auth router: /register, /login, /me, /reset-request, /reset-confirm with Pydantic models and get_current_user dependency
- `apps/meatheadgear/tests/test_auth.py` - 13 tests for all 4 AUTH requirements
- `apps/meatheadgear/main.py` - Added auth_router include_router + fixed missing catalog_router import from parallel plan

## Decisions Made

- **Direct bcrypt instead of passlib**: passlib has not been updated for bcrypt>=4.0/5.x which changed the wrap-bug detection API. Using `bcrypt.hashpw()`/`bcrypt.checkpw()` directly is simpler and future-proof.
- **Resend email stubbed**: Password reset token is stored in DB and logged; actual email via Resend API deferred until API key is available.
- **HTTPBearer auto_error=False**: Allows the `get_current_user` dependency to return a proper JSON 401 with a custom detail message instead of FastAPI's default Unauthorized response format.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] passlib incompatible with bcrypt>=4.0/5.0**
- **Found during:** Task 1 (running tests in RED phase)
- **Issue:** passlib's CryptContext with bcrypt scheme raises ValueError on bcrypt>=4.0 due to `detect_wrap_bug()` calling `_bcrypt.hashpw()` with a 256-byte test vector, which bcrypt 5.x now rejects with "password cannot be longer than 72 bytes"
- **Fix:** Replaced `passlib.context.CryptContext` with direct `bcrypt.hashpw()`/`bcrypt.checkpw()` in services/auth.py
- **Files modified:** apps/meatheadgear/services/auth.py
- **Verification:** All 13 tests passing
- **Committed in:** fe6b22b

**2. [Rule 3 - Blocking] Missing catalog_router import in main.py from parallel plan**
- **Found during:** Task 1 (running full test suite after implementation)
- **Issue:** Parallel plan 03 had written `app.include_router(catalog_router, ...)` to main.py but didn't add the import, causing NameError when importing main.app in tests
- **Fix:** Added `from routers.catalog import router as catalog_router` to main.py imports
- **Files modified:** apps/meatheadgear/main.py
- **Verification:** All 37 tests pass (test_auth.py + test_app.py + test_catalog.py + test_pricing.py)
- **Committed in:** fe6b22b

---

**Total deviations:** 2 auto-fixed (1 bug, 1 blocking)
**Impact on plan:** Both fixes necessary for correctness and test execution. No scope creep.

## Known Stubs

- `apps/meatheadgear/routers/auth.py:210` — Resend email sending is stubbed: reset token is stored in DB and logged to console. Actual email sending via Resend API is deferred pending `RESEND_API_KEY`. This is intentional per plan spec and does NOT block the password reset flow (token is visible in DB/logs for development). Future plan will wire Resend.

## Issues Encountered

- bcrypt 5.0.0 is installed and is stricter than earlier versions — passlib has not been updated to handle the API change. Resolved by dropping passlib and using bcrypt directly.
- Parallel execution conflict: plan 03 modified main.py simultaneously, leaving an incomplete import. Fixed inline.

## User Setup Required

None — no external service configuration required for auth to function. Password reset email delivery requires `RESEND_API_KEY` in `.env` (future plan).

## Next Phase Readiness

- Auth endpoints are live at `/api/auth/*`
- JWT tokens are valid for 7 days by default (configurable via `JWT_EXPIRY_DAYS` env var)
- `get_current_user` FastAPI dependency is available for import by any future router
- Catalog router (Plan 03) is already mounted alongside auth — no integration work needed

## Self-Check: PASSED

- FOUND: apps/meatheadgear/services/auth.py
- FOUND: apps/meatheadgear/routers/auth.py
- FOUND: apps/meatheadgear/tests/test_auth.py
- FOUND: .planning/workstreams/meatheadgear-platform/phases/01-store-foundation/01-02-SUMMARY.md
- FOUND commit: fe6b22b

---
*Phase: 01-store-foundation*
*Completed: 2026-03-20*
