# Phase 8 Research: Authentication Flow Improvements

**Researched:** 2026-03-05
**Status:** Complete

## Research Questions

1. How to implement httpOnly cookie-based JWT storage securely?
2. What's the best approach for token refresh without user disruption?
3. How to handle cross-tab authentication state synchronization?
4. How to implement specific JWT error handling in FastAPI?

## Technical Findings

### httpOnly Cookie JWT Storage

**Why httpOnly > localStorage:**
- XSS protection: JavaScript cannot read httpOnly cookies
- Automatic browser handling: Cookies sent with every request automatically
- CSRF protection needed when using cookies

**Implementation approach:**
```python
# FastAPI response with httpOnly cookie
response.set_cookie(
    key="access_token",
    value=token,
    httponly=True,
    secure=True,  # HTTPS only in production
    samesite="strict",
    max_age=3600  # 1 hour
)
```

**Considerations:**
- Need CSRF token for non-GET requests when using cookie auth
- OR keep using Authorization header for API, cookie for browser
- Hybrid approach: Cookie for browser sessions, header for API clients

### Token Refresh Strategy

**Option 1: Sliding Window (Chosen for Agent42)**
- Every authenticated request returns a new token with extended expiry
- Simpler implementation, good UX
- Risk: Token theft extends attack window

**Option 2: Refresh Tokens**
- Short-lived access tokens (15 min) + long-lived refresh tokens
- More secure but requires token rotation logic
- More complex for dashboard SPA use case

**Decision:** Use sliding window for dashboard (convenience) with reasonable max age (24h).

### Cross-Tab Auth Synchronization

**Approach: BroadcastChannel API (modern) + StorageEvent (fallback)**

```javascript
// Primary: BroadcastChannel
const authChannel = new BroadcastChannel('auth');
authChannel.postMessage({type: 'logout'});
authChannel.onmessage = (e) => {
  if (e.data.type === 'logout') handleLogout();
};

// Fallback: StorageEvent
window.addEventListener('storage', (e) => {
  if (e.key === 'auth_event') handleStorageChange();
});
```

**Events to sync:**
- login: token received, update state
- logout: clear state everywhere
- session_expired: redirect all tabs to login

### JWT Error Handling in FastAPI

**Current implementation issue:**
```python
# Current (dashboard/auth.py lines 125-137)
except JWTError:
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
```

This loses the specific error type (ExpiredSignatureError vs DecodeError vs InvalidTokenError).

**Improved implementation:**
```python
from jose.exceptions import ExpiredSignatureError, JWTError

try:
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
except ExpiredSignatureError:
    raise HTTPException(
        status_code=401,
        detail={"code": "token_expired", "message": "Session expired. Please log in again."}
    )
except JWTError as e:
    raise HTTPException(
        status_code=401,
        detail={"code": "invalid_token", "message": "Invalid authentication. Please log in."}
    )
```

## Validation Architecture

### Backend (Python/FastAPI)

**Tests needed:**
- `test_jwt_expired_returns_specific_error()`
- `test_login_success_sets_cookie()`
- `test_logout_clears_cookie()`
- `test_rate_limiting_still_works()`
- `test_api_key_auth_unaffected()`

**Middleware considerations:**
- Add `WWW-Authenticate` header on 401 responses
- CORS configuration must allow credentials for cookie auth

### Frontend (JavaScript)

**State management:**
```javascript
// Simple auth state store
const auth = {
  token: null,
  expiresAt: null,
  isAuthenticated: false,

  login(token) { /* set cookie, update state, broadcast */ },
  logout() { /* clear cookie, update state, broadcast */ },
  checkExpiry() { /* redirect if expired */ }
};
```

**HTTP client wrappers:**
- Intercept 401 responses with `code: token_expired`
- Trigger redirect to login with "session expired" message

## Browser Compatibility

| Feature | Chrome | Firefox | Safari | Edge |
|---------|--------|---------|--------|------|
| httpOnly cookies | ✓ | ✓ | ✓ | ✓ |
| BroadcastChannel | 54+ | 38+ | 15.4+ | 12+ |
| StorageEvent | ✓ | ✓ | ✓ | ✓ |

**Decision:** Use BroadcastChannel with StorageEvent fallback for older Safari.

## Implementation Checklist

- [ ] Add logout endpoint (`POST /api/logout`)
- [ ] Improve JWT error messages in `_validate_jwt()`
- [ ] Implement httpOnly cookie setting in login response
- [ ] Add token refresh on authenticated requests
- [ ] Add BroadcastChannel for cross-tab sync
- [ ] Add session expiry redirect handling
- [ ] Update frontend to handle specific auth errors
- [ ] Write comprehensive auth flow tests

## References

- FastAPI Cookies: https://fastapi.tiangolo.com/advanced/response-cookies/
- BroadcastChannel API: https://developer.mozilla.org/en-US/docs/Web/API/Broadcast_Channel_API
- python-jose exceptions: https://github.com/mpdavis/python-jose/blob/master/jose/exceptions.py
