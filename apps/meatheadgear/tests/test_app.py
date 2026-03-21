"""
Foundation tests for the MeatheadGear app skeleton.

Tests verify: health endpoint, frozen config, database initialization.
"""

import sys
from pathlib import Path

import pytest

# Ensure the app directory is on sys.path when running from repo root or tests/
_app_dir = Path(__file__).parent.parent
if str(_app_dir) not in sys.path:
    sys.path.insert(0, str(_app_dir))


class TestHealthEndpoint:
    @pytest.mark.asyncio
    async def test_health_returns_ok(self):
        from httpx import ASGITransport, AsyncClient
        from main import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/health")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"
            assert data["app"] == "meatheadgear"

    @pytest.mark.asyncio
    async def test_root_returns_ok(self):
        from httpx import ASGITransport, AsyncClient
        from main import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/")
            assert resp.status_code == 200


class TestConfig:
    def test_settings_frozen(self):
        from config import settings

        with pytest.raises(
            (AttributeError, TypeError)
        ):  # frozen=True raises FrozenInstanceError (subclass of AttributeError)
            settings.port = 9999  # type: ignore[misc]

    def test_settings_defaults(self):
        from config import settings

        assert isinstance(settings.port, int)
        assert settings.target_margin == pytest.approx(0.35)
        assert settings.jwt_expiry_days == 7
        assert settings.printful_sync_interval_hours == 6

    def test_settings_has_required_fields(self):
        from config import settings

        assert hasattr(settings, "secret_key")
        assert hasattr(settings, "printful_api_key")
        assert hasattr(settings, "database_url")
        assert hasattr(settings, "resend_api_key")


class TestDatabase:
    @pytest.mark.asyncio
    async def test_init_db_creates_tables(self, tmp_db):
        import aiosqlite
        import database

        # Override DB_PATH for this test
        original_path = database.DB_PATH
        database.DB_PATH = tmp_db
        try:
            await database.init_db()
            assert tmp_db.exists()

            # Verify all 4 tables exist
            async with aiosqlite.connect(str(tmp_db)) as db:
                cursor = await db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                )
                tables = {row[0] for row in await cursor.fetchall()}
            assert "users" in tables
            assert "products" in tables
            assert "product_variants" in tables
            assert "product_images" in tables
        finally:
            database.DB_PATH = original_path

    @pytest.mark.asyncio
    async def test_get_db_yields_connection(self, tmp_db):
        import database

        original_path = database.DB_PATH
        database.DB_PATH = tmp_db
        try:
            await database.init_db()
            # get_db is an async generator
            gen = database.get_db()
            db = await gen.__anext__()
            assert db is not None
            # Clean up
            try:
                await gen.aclose()
            except Exception:
                pass
        finally:
            database.DB_PATH = original_path
