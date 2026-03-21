"""
MeatheadGear auth service.

JWT creation/verification, password hashing/verification, and reset token generation.
Uses bcrypt directly for passwords (passlib has compatibility issues with bcrypt>=4.0),
and python-jose for JWT.
"""

import secrets
from datetime import UTC, datetime, timedelta

import bcrypt
from jose import JWTError, jwt


def hash_password(password: str) -> str:
    """Hash a plain-text password with bcrypt."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plain-text password against a bcrypt hash."""
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def create_access_token(user_id: int, email: str, secret_key: str, expiry_days: int = 7) -> str:
    """Create a signed JWT for the given user."""
    expire = datetime.now(UTC) + timedelta(days=expiry_days)
    payload = {"sub": str(user_id), "email": email, "exp": expire}
    return jwt.encode(payload, secret_key, algorithm="HS256")


def verify_access_token(token: str, secret_key: str) -> dict | None:
    """Decode and verify a JWT. Returns payload dict or None if invalid/expired."""
    try:
        payload = jwt.decode(token, secret_key, algorithms=["HS256"])
        return payload
    except JWTError:
        return None


def generate_reset_token() -> str:
    """Generate a cryptographically secure URL-safe reset token."""
    return secrets.token_urlsafe(32)
