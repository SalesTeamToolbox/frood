"""
JWT and API-key authentication for the dashboard and device gateway.

Security features:
- Bcrypt password hashing (preferred) with plaintext fallback + warning
- Constant-time comparison for plaintext passwords
- JWT with configurable secret (auto-generated if not set)
- API key authentication for registered devices (ak_ prefix)
- Rate limiting support via login attempt tracking
"""

import hmac
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from core.config import settings
from core.device_auth import API_KEY_PREFIX, DeviceStore

logger = logging.getLogger("agent42.auth")

ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 24


class _BcryptContext:
    """Minimal bcrypt wrapper replacing passlib.CryptContext.

    passlib 1.7.4 is incompatible with bcrypt >= 4.1 (its internal
    wrap-bug detection hashes a >72-byte secret, which newer bcrypt
    rejects with ValueError).  Using bcrypt directly avoids this.
    """

    @staticmethod
    def hash(secret: str) -> str:
        return bcrypt.hashpw(secret.encode(), bcrypt.gensalt()).decode()

    @staticmethod
    def verify(secret: str, hashed: str) -> bool:
        try:
            return bcrypt.checkpw(secret.encode(), hashed.encode())
        except (ValueError, TypeError):
            return False


pwd_context = _BcryptContext()
security = HTTPBearer()

# Rate limiting: track login attempts per IP
_login_attempts: dict[str, list[float]] = {}

# Device store — injected at startup via init_device_store()
_device_store: DeviceStore | None = None


def init_device_store(store: DeviceStore):
    """Inject the device store at application startup."""
    global _device_store
    _device_store = store


@dataclass
class AuthContext:
    """Unified authentication result for both JWT and API key auth."""

    user: str  # username (JWT) or "device" (API key)
    auth_type: str = "jwt"  # "jwt" or "api_key"
    device_id: str = ""
    device_name: str = ""


def verify_password(plain: str) -> bool:
    """Check the provided password against stored hash or plaintext.

    Prefers bcrypt hash. Falls back to constant-time plaintext comparison
    to avoid timing attacks.
    """
    if not settings.dashboard_password and not settings.dashboard_password_hash:
        return False

    if settings.dashboard_password_hash:
        return pwd_context.verify(plain, settings.dashboard_password_hash)

    # Constant-time comparison for plaintext fallback
    return hmac.compare_digest(plain.encode(), settings.dashboard_password.encode())


def check_rate_limit(client_ip: str) -> bool:
    """Check if a client IP has exceeded the login rate limit.

    Returns True if the request is allowed, False if rate limited.
    """
    now = time.time()
    window = 60.0  # 1 minute window
    max_attempts = settings.login_rate_limit

    if client_ip not in _login_attempts:
        _login_attempts[client_ip] = []

    # Prune old attempts
    _login_attempts[client_ip] = [t for t in _login_attempts[client_ip] if now - t < window]

    if len(_login_attempts[client_ip]) >= max_attempts:
        return False

    _login_attempts[client_ip].append(now)
    return True


def create_token(username: str) -> str:
    """Create a JWT access token."""
    expire = datetime.now(UTC) + timedelta(hours=TOKEN_EXPIRE_HOURS)
    return jwt.encode(
        {"sub": username, "exp": expire},
        settings.jwt_secret,
        algorithm=ALGORITHM,
    )


def _validate_jwt(token: str) -> AuthContext:
    """Validate a JWT token and return an AuthContext."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        return AuthContext(user=username, auth_type="jwt")
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )


def _validate_api_key(token: str) -> AuthContext:
    """Validate a device API key and return an AuthContext."""
    if not _device_store:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Device authentication not configured",
        )
    device = _device_store.validate_api_key(token)
    if not device:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or revoked API key",
        )
    return AuthContext(
        user="device",
        auth_type="api_key",
        device_id=device.device_id,
        device_name=device.name,
    )


def get_auth_context(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> AuthContext:
    """FastAPI dependency — validates JWT or API key, returns full AuthContext."""
    token = credentials.credentials
    if token.startswith(API_KEY_PREFIX):
        return _validate_api_key(token)
    return _validate_jwt(token)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> str:
    """FastAPI dependency — validates the JWT or API key and returns the username.

    Backwards-compatible wrapper around get_auth_context().
    """
    ctx = get_auth_context(credentials)
    return ctx.user


def require_admin(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> AuthContext:
    """FastAPI dependency — requires JWT admin auth (not device API keys)."""
    token = credentials.credentials
    if token.startswith(API_KEY_PREFIX):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required — device API keys cannot perform this action",
        )
    return _validate_jwt(token)
