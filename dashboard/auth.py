"""
JWT authentication for the dashboard.
"""

import logging
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


def verify_password(plain: str) -> bool:
    """Check the provided password against stored hash or plaintext."""
    if settings.dashboard_password_hash:
        return pwd_context.verify(plain, settings.dashboard_password_hash)
    return plain == settings.dashboard_password


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
