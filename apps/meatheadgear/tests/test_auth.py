"""
Auth endpoint tests for MeatheadGear.

Covers AUTH-01 through AUTH-04:
  AUTH-01: Customer can register with email and password
  AUTH-02: Customer can log in and receive a JWT token
  AUTH-03: JWT token persists session — GET /api/auth/me returns user with valid token
  AUTH-04: Customer can request and complete password reset
"""

import sys
from datetime import UTC
from pathlib import Path

import pytest

# Ensure the app directory is on sys.path
_app_dir = Path(__file__).parent.parent
if str(_app_dir) not in sys.path:
    sys.path.insert(0, str(_app_dir))


@pytest.fixture
async def client(tmp_path):
    """Async test client with an isolated temporary database."""
    import database
    from httpx import ASGITransport, AsyncClient
    from main import app

    db_file = tmp_path / "test_auth.db"
    original_path = database.DB_PATH
    database.DB_PATH = db_file

    # Re-initialize DB with temp path
    await database.init_db()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    database.DB_PATH = original_path
    if db_file.exists():
        db_file.unlink()


class TestRegister:
    """AUTH-01: Customer can register with email and password."""

    @pytest.mark.asyncio
    async def test_register_success(self, client):
        """Test 1: Successful registration returns 201 with user data."""
        resp = await client.post(
            "/api/auth/register",
            json={"email": "test@test.com", "password": "StrongPass1!", "name": "Test User"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "id" in data
        assert data["email"] == "test@test.com"
        assert "name" in data
        assert "password" not in data
        assert "password_hash" not in data

    @pytest.mark.asyncio
    async def test_register_duplicate_email_returns_409(self, client):
        """Test 2: Duplicate email registration returns 409."""
        payload = {"email": "dupe@test.com", "password": "StrongPass1!"}
        await client.post("/api/auth/register", json=payload)
        resp = await client.post("/api/auth/register", json=payload)
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_register_weak_password_returns_422(self, client):
        """Test 3: Weak password (less than 8 chars) returns 422."""
        resp = await client.post(
            "/api/auth/register",
            json={"email": "weak@test.com", "password": "short"},
        )
        assert resp.status_code == 422


class TestLogin:
    """AUTH-02: Customer can log in and receive a JWT token."""

    @pytest.fixture(autouse=True)
    async def register_user(self, client):
        """Register a test user before each login test."""
        await client.post(
            "/api/auth/register",
            json={"email": "login@test.com", "password": "StrongPass1!", "name": "Login User"},
        )

    @pytest.mark.asyncio
    async def test_login_success_returns_token(self, client):
        """Test 4: Valid credentials return 200 with access_token."""
        resp = await client.post(
            "/api/auth/login",
            json={"email": "login@test.com", "password": "StrongPass1!"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    @pytest.mark.asyncio
    async def test_login_wrong_password_returns_401(self, client):
        """Test 5: Wrong password returns 401."""
        resp = await client.post(
            "/api/auth/login",
            json={"email": "login@test.com", "password": "WrongPass1!"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_login_nonexistent_email_returns_401(self, client):
        """Test 6: Non-existent email returns 401."""
        resp = await client.post(
            "/api/auth/login",
            json={"email": "ghost@test.com", "password": "StrongPass1!"},
        )
        assert resp.status_code == 401


class TestMe:
    """AUTH-03: JWT token persists session across browser refresh."""

    @pytest.fixture(autouse=True)
    async def setup_user_and_token(self, client):
        """Register + login to get a valid token."""
        await client.post(
            "/api/auth/register",
            json={"email": "me@test.com", "password": "StrongPass1!", "name": "Me User"},
        )
        resp = await client.post(
            "/api/auth/login",
            json={"email": "me@test.com", "password": "StrongPass1!"},
        )
        self.token = resp.json()["access_token"]

    @pytest.mark.asyncio
    async def test_me_with_valid_token_returns_user(self, client):
        """Test 7: GET /api/auth/me with valid token returns user profile."""
        resp = await client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "id" in data
        assert data["email"] == "me@test.com"
        assert "name" in data

    @pytest.mark.asyncio
    async def test_me_without_token_returns_401(self, client):
        """Test 8: GET /api/auth/me without token returns 401."""
        resp = await client.get("/api/auth/me")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_me_with_expired_token_returns_401(self, client):
        """Test 9: GET /api/auth/me with expired token returns 401."""
        from datetime import datetime, timedelta

        from jose import jwt

        from config import settings

        # Create a token that expired 1 hour ago
        expired_payload = {
            "sub": "1",
            "email": "me@test.com",
            "exp": datetime.now(UTC) - timedelta(hours=1),
        }
        expired_token = jwt.encode(expired_payload, settings.secret_key, algorithm="HS256")
        resp = await client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {expired_token}"},
        )
        assert resp.status_code == 401


class TestPasswordReset:
    """AUTH-04: Customer can request and complete password reset."""

    @pytest.fixture(autouse=True)
    async def setup_user(self, client):
        """Register a test user."""
        await client.post(
            "/api/auth/register",
            json={"email": "reset@test.com", "password": "OldPass1!", "name": "Reset User"},
        )

    @pytest.mark.asyncio
    async def test_reset_request_existing_email_returns_200(self, client):
        """Test 10: Reset request always returns 200 (no email enumeration)."""
        resp = await client.post(
            "/api/auth/reset-request",
            json={"email": "reset@test.com"},
        )
        assert resp.status_code == 200
        assert "message" in resp.json()

    @pytest.mark.asyncio
    async def test_reset_request_nonexistent_email_returns_200(self, client):
        """Test 10b: Reset request for unknown email also returns 200 (no enumeration)."""
        resp = await client.post(
            "/api/auth/reset-request",
            json={"email": "nobody@test.com"},
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_reset_confirm_valid_token_changes_password(self, client):
        """Test 11: Valid reset token changes the password."""
        import database

        # Request a reset so token is stored in DB
        await client.post(
            "/api/auth/reset-request",
            json={"email": "reset@test.com"},
        )

        # Retrieve the token directly from the database
        import aiosqlite

        async with aiosqlite.connect(str(database.DB_PATH)) as db:
            cursor = await db.execute(
                "SELECT reset_token FROM users WHERE email = ?",
                ("reset@test.com",),
            )
            row = await cursor.fetchone()
        assert row is not None
        token = row[0]
        assert token is not None

        # Confirm the reset
        resp = await client.post(
            "/api/auth/reset-confirm",
            json={"token": token, "new_password": "NewPass1!"},
        )
        assert resp.status_code == 200

        # Verify old password no longer works
        login_old = await client.post(
            "/api/auth/login",
            json={"email": "reset@test.com", "password": "OldPass1!"},
        )
        assert login_old.status_code == 401

        # Verify new password works
        login_new = await client.post(
            "/api/auth/login",
            json={"email": "reset@test.com", "password": "NewPass1!"},
        )
        assert login_new.status_code == 200

    @pytest.mark.asyncio
    async def test_reset_confirm_invalid_token_returns_400(self, client):
        """Test 12: Invalid reset token returns 400."""
        resp = await client.post(
            "/api/auth/reset-confirm",
            json={"token": "completely-invalid-token", "new_password": "NewPass1!"},
        )
        assert resp.status_code == 400
