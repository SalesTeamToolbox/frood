"""
MeatheadGear auth router.

Provides endpoints for customer registration, login, session validation,
and password reset. All endpoints are prefixed with /api/auth by main.py.
"""

import logging
from datetime import UTC, datetime, timedelta

import aiosqlite
from database import get_db
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, field_validator
from services.auth import (
    create_access_token,
    generate_reset_token,
    hash_password,
    verify_access_token,
    verify_password,
)

from config import settings

logger = logging.getLogger(__name__)

router = APIRouter()
security = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class RegisterRequest(BaseModel):
    email: str
    password: str
    name: str = ""

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class LoginRequest(BaseModel):
    email: str
    password: str


class ResetRequest(BaseModel):
    email: str


class ResetConfirm(BaseModel):
    token: str
    new_password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: int
    email: str
    name: str
    created_at: str | None = None


# ---------------------------------------------------------------------------
# Dependency: get the currently authenticated user from Bearer token
# ---------------------------------------------------------------------------


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: aiosqlite.Connection = Depends(get_db),
) -> dict:
    """Extract and validate a Bearer JWT, return the user dict or raise 401."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    payload = verify_access_token(credentials.credentials, settings.secret_key)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
    cursor = await db.execute(
        "SELECT id, email, name, created_at FROM users WHERE id = ?",
        (int(payload["sub"]),),
    )
    user = await cursor.fetchone()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    return {"id": user[0], "email": user[1], "name": user[2], "created_at": user[3]}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/register", status_code=status.HTTP_201_CREATED, response_model=UserResponse)
async def register(
    body: RegisterRequest,
    db: aiosqlite.Connection = Depends(get_db),
) -> UserResponse:
    """AUTH-01: Register a new customer account."""
    password_hash = hash_password(body.password)
    try:
        cursor = await db.execute(
            "INSERT INTO users (email, password_hash, name) VALUES (?, ?, ?)",
            (body.email.lower(), password_hash, body.name),
        )
        await db.commit()
        user_id = cursor.lastrowid
    except aiosqlite.IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with that email already exists",
        )
    return UserResponse(id=user_id, email=body.email.lower(), name=body.name)


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    db: aiosqlite.Connection = Depends(get_db),
) -> TokenResponse:
    """AUTH-02: Authenticate and return a JWT access token."""
    cursor = await db.execute(
        "SELECT id, email, password_hash FROM users WHERE email = ?",
        (body.email.lower(),),
    )
    row = await cursor.fetchone()

    # Use constant-time comparison to prevent timing attacks / email enumeration
    _invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid email or password",
    )

    if row is None:
        # Still call verify_password with a dummy hash to prevent timing attacks
        verify_password(
            body.password, "$2b$12$invalidhashpaddingtomakeitlongenough00000000000000000"
        )
        raise _invalid

    if not verify_password(body.password, row[2]):
        raise _invalid

    token = create_access_token(
        user_id=row[0],
        email=row[1],
        secret_key=settings.secret_key,
        expiry_days=settings.jwt_expiry_days,
    )
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserResponse)
async def me(
    current_user: dict = Depends(get_current_user),
) -> UserResponse:
    """AUTH-03: Return the authenticated user's profile (session persistence check)."""
    return UserResponse(**current_user)


@router.post("/reset-request")
async def reset_request(
    body: ResetRequest,
    db: aiosqlite.Connection = Depends(get_db),
) -> dict:
    """AUTH-04a: Request a password reset token (no email enumeration)."""
    _safe_response = {"message": "If an account exists, a reset link has been sent"}

    cursor = await db.execute(
        "SELECT id FROM users WHERE email = ?",
        (body.email.lower(),),
    )
    row = await cursor.fetchone()

    if row is None:
        # Always return the same message — do not reveal whether email exists
        return _safe_response

    token = generate_reset_token()
    expires = datetime.now(UTC) + timedelta(hours=1)
    expires_str = expires.strftime("%Y-%m-%d %H:%M:%S")

    await db.execute(
        "UPDATE users SET reset_token = ?, reset_token_expires = ? WHERE id = ?",
        (token, expires_str, row[0]),
    )
    await db.commit()

    # NOTE: Resend email sending is stubbed — log token for development use
    logger.info("Password reset token for %s: %s", body.email, token)

    return _safe_response


@router.post("/reset-confirm")
async def reset_confirm(
    body: ResetConfirm,
    db: aiosqlite.Connection = Depends(get_db),
) -> dict:
    """AUTH-04b: Confirm a password reset using a valid token."""
    cursor = await db.execute(
        "SELECT id, reset_token_expires FROM users WHERE reset_token = ?",
        (body.token,),
    )
    row = await cursor.fetchone()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )

    user_id, expires_str = row[0], row[1]

    # Check token expiry
    if expires_str is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )

    try:
        # SQLite stores timestamps in various formats — handle UTC-aware comparison
        expires = datetime.strptime(expires_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )

    if datetime.now(UTC) > expires:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )

    new_hash = hash_password(body.new_password)
    await db.execute(
        "UPDATE users SET password_hash = ?, reset_token = NULL, reset_token_expires = NULL WHERE id = ?",
        (new_hash, user_id),
    )
    await db.commit()

    return {"message": "Password has been reset successfully"}
