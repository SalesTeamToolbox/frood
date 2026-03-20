---
gathered: 2026-03-05
status: Ready for planning
source: Codebase analysis via jcodemunch
---

# Phase 8: Authentication Flow Improvements - Context

## Phase Boundary

Refactor authentication to handle edge cases, improve error handling, and ensure session persistence. Focus on dashboard login/logout flows, JWT token management, and graceful session expiration handling.

## Implementation Decisions (Locked)

### Error Handling
- JWT validation must return specific error messages (expired vs invalid vs missing)
- Login endpoint must distinguish between: bad credentials, rate limited, server error
- All auth errors must include actionable user messages

### Session Management
- Token storage must use httpOnly cookies (not localStorage) for XSS protection
- JWT expiration must trigger automatic redirect to login
- Session refresh mechanism needed before expiration

### Edge Cases
- Browser back button after logout must not restore authenticated state
- Multiple tabs must sync auth state (login/logout across tabs)
- Network interruptions during auth flows must be handled gracefully

### Security
- Rate limiting already implemented (1 minute window) - preserve and extend
- bcrypt password hashing already in place - verify no plaintext storage
- Device API keys validated via HMAC - preserve this mechanism

## Claude's Discretion

- Frontend state management approach (vanilla JS vs minimal framework)
- Token refresh strategy (sliding window vs fixed expiry with refresh)
- Specific UI copy for error messages
- Animation/transition details for redirects

## Specific Ideas

### From Codebase Analysis (jcodemunch)

**Current auth components:**
- `dashboard/auth.py::AuthContext` - Unified auth result dataclass
- `dashboard/auth.py::_validate_jwt()` - JWT validation (lines 125-137)
- `dashboard/auth.py::get_auth_context()` - FastAPI dependency for JWT/API key
- `dashboard/server.py::create_app.login()` - Login handler (lines 636-675)
- `dashboard/auth.py::require_admin()` - Admin-only dependency

**Current gaps identified:**
1. No logout endpoint found in server.py
2. No token refresh mechanism
3. JWT errors return generic 401 without specifics
4. Frontend token storage mechanism unknown (no localStorage usage found in JS)
5. No session expiration redirect logic visible

**Requirements from v1.1-ROADMAP.md:**
- AUTH-01: Authentication works consistently across different browsers and network conditions
- AUTH-02: Session expiration is handled gracefully with automatic redirects
- AUTH-03: Error messages for authentication failures are clear and actionable
- AUTH-04: Unit tests for authentication flows pass

## Deferred Ideas

- OAuth integration (GitHub device flow exists but that's separate)
- Multi-factor authentication
- Role-based access control (beyond simple admin/device split)
- Session management UI (view/kill active sessions)

---

*Phase: 08-authentication-flow*
*Context gathered: 2026-03-05 via jcodemunch analysis*
