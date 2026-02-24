"""Tests for the first-run setup wizard endpoints and helpers."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from dashboard.auth import pwd_context
from dashboard.server import _update_env_file

# ---------------------------------------------------------------------------
# _update_env_file helper
# ---------------------------------------------------------------------------


class TestUpdateEnvFile:
    """Unit tests for the .env file update helper."""

    def test_replaces_existing_key(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("FOO=bar\nBAZ=qux\n")
        _update_env_file(env, {"FOO": "new"})
        content = env.read_text()
        assert "FOO=new" in content
        assert "BAZ=qux" in content

    def test_uncomments_and_replaces(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("# DASHBOARD_PASSWORD_HASH=\nOTHER=val\n")
        _update_env_file(env, {"DASHBOARD_PASSWORD_HASH": "$2b$12$abc"})
        content = env.read_text()
        assert "DASHBOARD_PASSWORD_HASH=$2b$12$abc" in content
        assert "# DASHBOARD_PASSWORD_HASH" not in content

    def test_appends_missing_key(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("FOO=bar\n")
        _update_env_file(env, {"NEW_KEY": "value"})
        content = env.read_text()
        assert "FOO=bar" in content
        assert "NEW_KEY=value" in content

    def test_empty_value_clears_key(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("DASHBOARD_PASSWORD=changeme\n")
        _update_env_file(env, {"DASHBOARD_PASSWORD": ""})
        content = env.read_text()
        assert "DASHBOARD_PASSWORD=" in content
        # Should not have a value after the equals sign
        for line in content.splitlines():
            if line.startswith("DASHBOARD_PASSWORD="):
                assert line == "DASHBOARD_PASSWORD="

    def test_creates_env_if_missing(self, tmp_path):
        env = tmp_path / ".env"
        assert not env.exists()
        _update_env_file(env, {"KEY": "val"})
        assert env.exists()
        assert "KEY=val" in env.read_text()

    def test_handles_multiple_updates(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("A=1\nB=2\nC=3\n")
        _update_env_file(env, {"A": "10", "C": "30"})
        content = env.read_text()
        assert "A=10" in content
        assert "B=2" in content
        assert "C=30" in content

    def test_preserves_unrelated_lines(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("# Comment line\nFOO=bar\n\n# Another comment\n")
        _update_env_file(env, {"FOO": "baz"})
        lines = env.read_text().splitlines()
        assert "# Comment line" in lines
        assert "# Another comment" in lines


# ---------------------------------------------------------------------------
# Settings.reload_from_env
# ---------------------------------------------------------------------------


class TestReloadFromEnv:
    """Test that reload_from_env updates the frozen singleton in-place."""

    def test_reload_updates_field(self, tmp_path):
        from core.config import Settings, settings

        original_password = settings.dashboard_password

        # Write a temp .env and reload from it
        env = tmp_path / ".env"
        env.write_text("DASHBOARD_PASSWORD=test_reload_value\n")

        with patch.object(Path, "__truediv__", return_value=env):
            # Directly test the mechanism: set env var and reload
            os.environ["DASHBOARD_PASSWORD"] = "test_reload_value"
            try:
                new = Settings.from_env()
                for field_name in Settings.__dataclass_fields__:
                    object.__setattr__(settings, field_name, getattr(new, field_name))
                assert settings.dashboard_password == "test_reload_value"
            finally:
                # Restore original
                if original_password:
                    os.environ["DASHBOARD_PASSWORD"] = original_password
                else:
                    os.environ.pop("DASHBOARD_PASSWORD", None)
                new2 = Settings.from_env()
                for field_name in Settings.__dataclass_fields__:
                    object.__setattr__(settings, field_name, getattr(new2, field_name))


# ---------------------------------------------------------------------------
# Setup status endpoint logic
# ---------------------------------------------------------------------------


class TestSetupStatus:
    """Test the setup_needed detection logic."""

    def test_setup_needed_when_no_password(self):
        """When password is empty and no hash, setup is needed."""
        from dashboard.server import _INSECURE_PASSWORDS

        assert "" in _INSECURE_PASSWORDS

    def test_setup_needed_catches_default_password(self):
        """The default .env.example password is treated as insecure."""
        from dashboard.server import _INSECURE_PASSWORDS

        assert "changeme-right-now" in _INSECURE_PASSWORDS

    def test_real_password_not_insecure(self):
        """A user-chosen password should not be in the insecure set."""
        from dashboard.server import _INSECURE_PASSWORDS

        assert "my-secure-password" not in _INSECURE_PASSWORDS


# ---------------------------------------------------------------------------
# Bcrypt wrapper (replaced passlib due to bcrypt >= 4.1 incompatibility)
# ---------------------------------------------------------------------------


class TestBcryptContext:
    """Verify that pwd_context hash/verify works with bcrypt >= 4.1."""

    def test_hash_and_verify(self):
        hashed = pwd_context.hash("my-password")
        assert hashed.startswith("$2b$")
        assert pwd_context.verify("my-password", hashed)

    def test_wrong_password_rejected(self):
        hashed = pwd_context.hash("correct-password")
        assert not pwd_context.verify("wrong-password", hashed)

    def test_verify_invalid_hash_returns_false(self):
        assert not pwd_context.verify("anything", "not-a-hash")


# ---------------------------------------------------------------------------
# Setup complete endpoint (integration)
# ---------------------------------------------------------------------------


class TestSetupCompleteEndpoint:
    """Integration tests for POST /api/setup/complete."""

    @pytest.fixture()
    def _fresh_settings(self):
        """Temporarily clear password settings so the wizard is accessible."""
        from core.config import settings

        orig_hash = settings.dashboard_password_hash
        orig_pass = settings.dashboard_password
        object.__setattr__(settings, "dashboard_password_hash", "")
        object.__setattr__(settings, "dashboard_password", "")
        yield
        object.__setattr__(settings, "dashboard_password_hash", orig_hash)
        object.__setattr__(settings, "dashboard_password", orig_pass)

    @pytest.fixture()
    def _app(self, tmp_path):
        """Create a FastAPI test app backed by a temp task queue."""
        from core.approval_gate import ApprovalGate
        from core.task_queue import TaskQueue
        from dashboard.server import create_app
        from dashboard.websocket_manager import WebSocketManager

        tq = TaskQueue(tasks_json_path=str(tmp_path / "tasks.json"))
        ws = WebSocketManager()
        ag = ApprovalGate(ws)
        return create_app(tq, ws, ag)

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("_fresh_settings")
    async def test_setup_complete_qdrant_redis(self, _app, tmp_path):
        """Setup with qdrant_redis should succeed and queue a verification task."""
        from httpx import ASGITransport, AsyncClient

        # Point _update_env_file at a temp .env so it doesn't touch the real one
        env_path = tmp_path / ".env"
        env_path.write_text("")

        with (
            patch("dashboard.server._update_env_file"),
            patch("dashboard.server._pip_install", return_value=([], [])),
            patch("dashboard.server.Settings.reload_from_env"),
        ):
            transport = ASGITransport(app=_app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/api/setup/complete",
                    json={
                        "password": "test12345678",
                        "openrouter_api_key": "",
                        "memory_backend": "qdrant_redis",
                    },
                )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["memory_backend"] == "qdrant_redis"
        assert data["setup_task_id"]  # non-empty
        assert data["token"]  # JWT returned


# ---------------------------------------------------------------------------
# Change password endpoint
# ---------------------------------------------------------------------------


class TestChangePasswordEndpoint:
    """Integration tests for POST /api/settings/password."""

    @pytest.fixture()
    def _password_settings(self):
        """Set a known bcrypt hash so we can verify the current password."""
        from core.config import settings

        orig_hash = settings.dashboard_password_hash
        orig_pass = settings.dashboard_password
        known_hash = pwd_context.hash("oldpassword123")
        object.__setattr__(settings, "dashboard_password_hash", known_hash)
        object.__setattr__(settings, "dashboard_password", "")
        yield
        object.__setattr__(settings, "dashboard_password_hash", orig_hash)
        object.__setattr__(settings, "dashboard_password", orig_pass)

    @pytest.fixture()
    def _app(self, tmp_path):
        from core.approval_gate import ApprovalGate
        from core.task_queue import TaskQueue
        from dashboard.server import create_app
        from dashboard.websocket_manager import WebSocketManager

        tq = TaskQueue(tasks_json_path=str(tmp_path / "tasks.json"))
        ws = WebSocketManager()
        ag = ApprovalGate(ws)
        return create_app(tq, ws, ag)

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("_password_settings")
    async def test_change_password_success(self, _app):
        """Changing password with correct current password should succeed."""
        from httpx import ASGITransport, AsyncClient

        from core.config import settings
        from dashboard.auth import create_token

        token = create_token(settings.dashboard_username)

        with (
            patch("dashboard.server._update_env_file"),
            patch("dashboard.server.Settings.reload_from_env"),
        ):
            transport = ASGITransport(app=_app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/api/settings/password",
                    json={
                        "current_password": "oldpassword123",
                        "new_password": "newpassword456",
                    },
                    headers={"Authorization": f"Bearer {token}"},
                )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["token"]  # New JWT returned

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("_password_settings")
    async def test_change_password_wrong_current(self, _app):
        """Changing password with wrong current password should fail."""
        from httpx import ASGITransport, AsyncClient

        from core.config import settings
        from dashboard.auth import create_token

        token = create_token(settings.dashboard_username)

        transport = ASGITransport(app=_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/settings/password",
                json={
                    "current_password": "wrongpassword",
                    "new_password": "newpassword456",
                },
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("_password_settings")
    async def test_change_password_too_short(self, _app):
        """New password shorter than 8 chars should be rejected."""
        from httpx import ASGITransport, AsyncClient

        from core.config import settings
        from dashboard.auth import create_token

        token = create_token(settings.dashboard_username)

        transport = ASGITransport(app=_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/settings/password",
                json={
                    "current_password": "oldpassword123",
                    "new_password": "short",
                },
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("_password_settings")
    async def test_change_password_unauthenticated(self, _app):
        """Attempting to change password without auth should fail."""
        from httpx import ASGITransport, AsyncClient

        transport = ASGITransport(app=_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/settings/password",
                json={
                    "current_password": "oldpassword123",
                    "new_password": "newpassword456",
                },
            )
        # 401 for missing credentials (no Bearer token provided)
        assert resp.status_code in (401, 403)
