"""
Test authentication flow improvements.

Tests cover:
- JWT error handling with specific codes
- httpOnly cookie login/logout
- Auth error messages
"""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from jose import jwt

from core.config import settings
from dashboard.auth import (
    ALGORITHM,
    AuthContext,
    _validate_jwt,
    check_rate_limit,
    create_token,
    pwd_context,
)


class TestJWTValidation:
    """Test JWT validation with specific error codes."""

    def test_valid_token_returns_auth_context(self):
        """Valid token should return AuthContext with user info."""
        token = create_token("admin")
        ctx = _validate_jwt(token)
        assert isinstance(ctx, AuthContext)
        assert ctx.user == "admin"
        assert ctx.auth_type == "jwt"

    def test_expired_token_returns_specific_error(self):
        """Expired token should return 'token_expired' error code."""
        # Create an expired token manually
        expire = datetime.now(UTC) - timedelta(hours=1)
        token = jwt.encode(
            {"sub": "admin", "exp": expire},
            settings.jwt_secret,
            algorithm=ALGORITHM,
        )

        with pytest.raises(HTTPException) as exc_info:
            _validate_jwt(token)

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail["code"] == "token_expired"
        assert "expired" in exc_info.value.detail["message"].lower()

    def test_invalid_token_returns_specific_error(self):
        """Invalid token should return 'invalid_token' error code."""
        with pytest.raises(HTTPException) as exc_info:
            _validate_jwt("invalid.token.here")

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail["code"] == "invalid_token"
        assert "invalid" in exc_info.value.detail["message"].lower()

    def test_missing_subject_returns_specific_error(self):
        """Token without 'sub' claim should return 'missing_subject' error."""
        # Create token without subject
        expire = datetime.now(UTC) + timedelta(hours=1)
        token = jwt.encode(
            {"exp": expire},  # No 'sub' claim
            settings.jwt_secret,
            algorithm=ALGORITHM,
        )

        with pytest.raises(HTTPException) as exc_info:
            _validate_jwt(token)

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail["code"] == "missing_subject"


class TestRateLimit:
    """Test login rate limiting."""

    def setup_method(self):
        """Reset rate limit state before each test."""
        from dashboard import auth

        auth._login_attempts.clear()

    def test_rate_limit_blocks_excessive_attempts(self):
        """Multiple rapid login attempts should be rate limited."""
        # Make max attempts from same IP
        for i in range(settings.login_rate_limit):
            allowed = check_rate_limit("192.168.1.1")
            assert allowed is True

        # Next attempt should be blocked
        allowed = check_rate_limit("192.168.1.1")
        assert allowed is False

    def test_different_ips_not_affected(self):
        """Rate limit should be per-IP."""
        # Exhaust limit for IP1
        for i in range(settings.login_rate_limit):
            check_rate_limit("192.168.1.1")

        # IP2 should still be allowed
        allowed = check_rate_limit("192.168.1.2")
        assert allowed is True


class TestPasswordHashing:
    """Test password hashing utilities."""

    def test_bcrypt_hash_creation(self):
        """bcrypt should hash passwords correctly."""
        hashed = pwd_context.hash("testpassword")
        assert hashed.startswith("$2")
        assert pwd_context.verify("testpassword", hashed) is True
        assert pwd_context.verify("wrongpassword", hashed) is False


class TestAuthIntegration:
    """Integration tests for auth endpoints."""

    @pytest.fixture
    def client(self):
        """Create test client with mocked dependencies."""
        from core.device_auth import DeviceStore
        from dashboard.server import create_app
        from dashboard.websocket_manager import WebSocketManager

        device_store = DeviceStore(path=":memory:")
        ws_manager = WebSocketManager()

        app = create_app(
            device_store=device_store,
            ws_manager=ws_manager,
        )

        with TestClient(app) as client:
            yield client

    def test_logout_endpoint_returns_ok(self, client):
        """Logout endpoint should return success even without auth."""
        res = client.post("/api/logout", json={})

        # Logout should succeed regardless of auth state
        assert res.status_code == 200

    def test_protected_endpoint_requires_auth(self, client):
        """Protected endpoints should require authentication."""
        res = client.get("/api/tasks")

        assert res.status_code == 401


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
