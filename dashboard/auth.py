"""
JWT authentication for the dashboard.

Security features:
- Bcrypt password hashing (preferred) with plaintext fallback + warning
- Constant-time comparison for plaintext passwords
- JWT with configurable secret (auto-generated if not set)
- Rate limiting support via login attempt tracking
"""

import hmac
import logging
import time
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext

from core.config import settings

logger = logging.getLogger("agent42.auth")

ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 24

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()

# Rate limiting: track login attempts per IP
_login_attempts: dict[str, list[float]] = {}


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
    _login_attempts[client_ip] = [
        t for t in _login_attempts[client_ip] if now - t < window
    ]

    if len(_login_attempts[client_ip]) >= max_attempts:
        return False

    _login_attempts[client_ip].append(now)
    return True


def create_token(username: str) -> str:
    """Create a JWT access token."""
    expire = datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRE_HOURS)
    return jwt.encode(
        {"sub": username, "exp": expire},
        settings.jwt_secret,
        algorithm=ALGORITHM,
    )


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> str:
    """FastAPI dependency — validates the JWT and returns the username."""
    try:
        payload = jwt.decode(
            credentials.credentials, settings.jwt_secret, algorithms=[ALGORITHM]
        )
        username = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        return username
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
