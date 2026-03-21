"""
MeatheadGear catalog tests.

Tests for: pricing engine, Printful API client, catalog sync service, product API endpoints.
All Printful API calls are mocked — no real API key required.
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure the app directory is on sys.path when running from repo root or tests/
_app_dir = Path(__file__).parent.parent
if str(_app_dir) not in sys.path:
    sys.path.insert(0, str(_app_dir))


# ---------------------------------------------------------------------------
# Pricing engine tests
# ---------------------------------------------------------------------------


class TestPricingEngine:
    def test_calculate_retail_price_13_50(self):
        """13.50 / 0.65 = 20.77 -> round up to 20.99"""
        from services.pricing import calculate_retail_price

        price = calculate_retail_price(13.50)
        assert price == pytest.approx(20.99, abs=0.01)

    def test_calculate_retail_price_9_49(self):
        """9.49 / 0.65 = 14.60 -> round up to 14.99"""
        from services.pricing import calculate_retail_price

        price = calculate_retail_price(9.49)
        assert price == pytest.approx(14.99, abs=0.01)

    def test_calculate_retail_price_29_94(self):
        """29.94 / 0.65 = 46.06 -> round up to 46.99"""
        from services.pricing import calculate_retail_price

        price = calculate_retail_price(29.94)
        assert price == pytest.approx(46.99, abs=0.01)

    def test_calculate_retail_price_zero(self):
        """Edge case: zero cost returns 0.0"""
        from services.pricing import calculate_retail_price

        price = calculate_retail_price(0)
        assert price == 0.0

    def test_margin_verification_all_cases(self):
        """Verify (retail - cost) / retail >= 0.30 for all test cases"""
        from services.pricing import calculate_retail_price

        test_costs = [13.50, 9.49, 29.94, 5.00, 25.00]
        for cost in test_costs:
            price = calculate_retail_price(cost)
            if price > 0:
                margin = (price - cost) / price
                assert margin >= 0.30, f"Margin {margin:.2%} too low for cost {cost}"


# ---------------------------------------------------------------------------
# Printful API client tests (mocked httpx)
# ---------------------------------------------------------------------------


class TestPrintfulClient:
    @pytest.mark.asyncio
    async def test_get_catalog_products_returns_list(self):
        """get_catalog_products() returns list of products from mocked Printful API"""
        from services.printful import PrintfulClient

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {
                    "id": 1,
                    "title": "Classic Tee",
                    "type_name": "T-shirts",
                    "image": "http://img.com/1.jpg",
                },
                {
                    "id": 2,
                    "title": "Hoody",
                    "type_name": "Hoodies & Sweatshirts",
                    "image": "http://img.com/2.jpg",
                },
                {
                    "id": 3,
                    "title": "Business Suit",
                    "type_name": "Formal Wear",
                    "image": "http://img.com/3.jpg",
                },
            ]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)

            client = PrintfulClient("test_api_key")
            products = await client.get_catalog_products()

        # Only gym wear categories should be returned (not "Formal Wear")
        assert isinstance(products, list)
        assert len(products) == 2
        assert products[0]["title"] == "Classic Tee"
        assert products[1]["title"] == "Hoody"

    @pytest.mark.asyncio
    async def test_get_product_details_returns_product(self):
        """get_product_details(product_id) returns product with variants from mocked response"""
        from services.printful import PrintfulClient

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "id": 1,
                "title": "Classic Tee",
                "variants": [
                    {
                        "id": 101,
                        "name": "Classic Tee / S / Black",
                        "size": "S",
                        "color": "Black",
                        "color_code": "#000000",
                        "price": "13.50",
                        "availability_status": "active",
                    },
                    {
                        "id": 102,
                        "name": "Classic Tee / M / Black",
                        "size": "M",
                        "color": "Black",
                        "color_code": "#000000",
                        "price": "13.50",
                        "availability_status": "active",
                    },
                ],
                "images": [{"url": "http://img.com/1.jpg"}],
            }
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)

            client = PrintfulClient("test_api_key")
            details = await client.get_product_details(1)

        assert details is not None
        assert details["id"] == 1
        assert len(details["variants"]) == 2

    @pytest.mark.asyncio
    async def test_get_catalog_products_handles_429(self):
        """Client handles 429 rate limit response gracefully (returns empty, does not crash)"""
        from services.printful import PrintfulClient

        mock_response = MagicMock()
        mock_response.status_code = 429

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)

            client = PrintfulClient("test_api_key")
            products = await client.get_catalog_products()

        assert products == []

    @pytest.mark.asyncio
    async def test_get_catalog_products_handles_network_error(self):
        """Client handles network error gracefully (returns empty, does not crash)"""
        import httpx
        from services.printful import PrintfulClient

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))

            client = PrintfulClient("test_api_key")
            products = await client.get_catalog_products()

        assert products == []


# ---------------------------------------------------------------------------
# Catalog sync service tests (mocked PrintfulClient)
# ---------------------------------------------------------------------------


class TestCatalogSync:
    @pytest.mark.asyncio
    async def test_sync_catalog_inserts_products(self, tmp_path):
        """sync_catalog() fetches products from Printful and inserts into products table"""
        import aiosqlite
        import database
        import services.catalog as catalog_mod

        db_file = tmp_path / "test_sync.db"
        original_path = database.DB_PATH
        database.DB_PATH = db_file
        try:
            await database.init_db()

            mock_products = [
                {
                    "id": 10,
                    "title": "Test Tee",
                    "type_name": "T-shirts",
                    "description": "A test tee",
                    "image": "http://img.com/tee.jpg",
                }
            ]
            mock_details = {
                "id": 10,
                "variants": [
                    {
                        "id": 201,
                        "name": "Test Tee / S / Red",
                        "size": "S",
                        "color": "Red",
                        "color_code": "#FF0000",
                        "price": "13.50",
                        "availability_status": "active",
                    },
                ],
                "images": [{"url": "http://img.com/tee.jpg"}],
            }

            mock_client = AsyncMock()
            mock_client.get_catalog_products = AsyncMock(return_value=mock_products)
            mock_client.get_product_details = AsyncMock(return_value=mock_details)

            with (
                patch("services.catalog.PrintfulClient", return_value=mock_client),
                patch("services.catalog.settings") as mock_settings,
            ):
                mock_settings.printful_api_key = "test_key"
                mock_settings.target_margin = 0.35
                mock_settings.printful_sync_interval_hours = 6
                await catalog_mod.sync_catalog()

            async with aiosqlite.connect(str(db_file)) as db:
                cursor = await db.execute("SELECT COUNT(*) FROM products")
                count = (await cursor.fetchone())[0]
                assert count == 1

                cursor = await db.execute("SELECT printful_id, name FROM products")
                row = await cursor.fetchone()
                assert row[0] == 10
                assert row[1] == "Test Tee"
        finally:
            database.DB_PATH = original_path

    @pytest.mark.asyncio
    async def test_sync_catalog_calculates_retail_prices(self, tmp_path):
        """sync_catalog() calculates retail prices for each variant using calculate_retail_price()"""
        import aiosqlite
        import database
        import services.catalog as catalog_mod

        db_file = tmp_path / "test_prices.db"
        original_path = database.DB_PATH
        database.DB_PATH = db_file
        try:
            await database.init_db()

            mock_products = [
                {
                    "id": 11,
                    "title": "Price Tee",
                    "type_name": "T-shirts",
                    "description": "",
                    "image": "",
                }
            ]
            mock_details = {
                "id": 11,
                "variants": [
                    {
                        "id": 301,
                        "name": "Price Tee / M / Blue",
                        "size": "M",
                        "color": "Blue",
                        "color_code": "#0000FF",
                        "price": "13.50",
                        "availability_status": "active",
                    },
                ],
                "images": [],
            }

            mock_client = AsyncMock()
            mock_client.get_catalog_products = AsyncMock(return_value=mock_products)
            mock_client.get_product_details = AsyncMock(return_value=mock_details)

            with (
                patch("services.catalog.PrintfulClient", return_value=mock_client),
                patch("services.catalog.settings") as mock_settings,
            ):
                mock_settings.printful_api_key = "test_key"
                mock_settings.target_margin = 0.35
                mock_settings.printful_sync_interval_hours = 6
                await catalog_mod.sync_catalog()

            async with aiosqlite.connect(str(db_file)) as db:
                cursor = await db.execute(
                    "SELECT printful_price, retail_price FROM product_variants WHERE printful_variant_id = 301"
                )
                row = await cursor.fetchone()
                assert row is not None
                printful_price = row[0]
                retail_price = row[1]
                assert printful_price == pytest.approx(13.50, abs=0.01)
                # Margin check
                assert retail_price > printful_price
                margin = (retail_price - printful_price) / retail_price
                assert margin >= 0.30
        finally:
            database.DB_PATH = original_path

    @pytest.mark.asyncio
    async def test_sync_catalog_handles_empty_response(self, tmp_path):
        """sync_catalog() handles empty Printful response gracefully (no crash, no data loss)"""
        import aiosqlite
        import database
        import services.catalog as catalog_mod

        db_file = tmp_path / "test_empty.db"
        original_path = database.DB_PATH
        database.DB_PATH = db_file
        try:
            await database.init_db()

            mock_client = AsyncMock()
            mock_client.get_catalog_products = AsyncMock(return_value=[])

            with (
                patch("services.catalog.PrintfulClient", return_value=mock_client),
                patch("services.catalog.settings") as mock_settings,
            ):
                mock_settings.printful_api_key = "test_key"
                mock_settings.target_margin = 0.35
                mock_settings.printful_sync_interval_hours = 6
                # Should not raise
                await catalog_mod.sync_catalog()

            async with aiosqlite.connect(str(db_file)) as db:
                cursor = await db.execute("SELECT COUNT(*) FROM products")
                count = (await cursor.fetchone())[0]
                assert count == 0
        finally:
            database.DB_PATH = original_path

    @pytest.mark.asyncio
    async def test_sync_catalog_upserts_not_duplicates(self, tmp_path):
        """Re-running sync_catalog() updates existing products (upsert, not duplicate)"""
        import aiosqlite
        import database
        import services.catalog as catalog_mod

        db_file = tmp_path / "test_upsert.db"
        original_path = database.DB_PATH
        database.DB_PATH = db_file
        try:
            await database.init_db()

            mock_products = [
                {
                    "id": 12,
                    "title": "Upsert Tee v1",
                    "type_name": "T-shirts",
                    "description": "",
                    "image": "http://v1.jpg",
                }
            ]
            mock_details = {
                "id": 12,
                "variants": [
                    {
                        "id": 401,
                        "name": "Upsert Tee / S",
                        "size": "S",
                        "color": "Green",
                        "color_code": "#00FF00",
                        "price": "10.00",
                        "availability_status": "active",
                    },
                ],
                "images": [],
            }

            mock_client = AsyncMock()
            mock_client.get_catalog_products = AsyncMock(return_value=mock_products)
            mock_client.get_product_details = AsyncMock(return_value=mock_details)

            with (
                patch("services.catalog.PrintfulClient", return_value=mock_client),
                patch("services.catalog.settings") as mock_settings,
            ):
                mock_settings.printful_api_key = "test_key"
                mock_settings.target_margin = 0.35
                mock_settings.printful_sync_interval_hours = 6
                await catalog_mod.sync_catalog()

            # Second sync with updated name
            mock_products[0]["title"] = "Upsert Tee v2"
            mock_client.get_catalog_products = AsyncMock(return_value=mock_products)
            mock_client.get_product_details = AsyncMock(return_value=mock_details)

            with (
                patch("services.catalog.PrintfulClient", return_value=mock_client),
                patch("services.catalog.settings") as mock_settings,
            ):
                mock_settings.printful_api_key = "test_key"
                mock_settings.target_margin = 0.35
                mock_settings.printful_sync_interval_hours = 6
                await catalog_mod.sync_catalog()

            async with aiosqlite.connect(str(db_file)) as db:
                cursor = await db.execute("SELECT COUNT(*) FROM products")
                count = (await cursor.fetchone())[0]
                assert count == 1  # Not 2 — upsert, not duplicate

                cursor = await db.execute("SELECT name FROM products WHERE printful_id = 12")
                row = await cursor.fetchone()
                assert row[0] == "Upsert Tee v2"
        finally:
            database.DB_PATH = original_path


# ---------------------------------------------------------------------------
# Catalog API endpoint tests
# ---------------------------------------------------------------------------


class TestCatalogAPI:
    @pytest.mark.asyncio
    async def test_list_products_returns_empty_when_no_products(self, tmp_path):
        """GET /api/catalog/products returns list of products"""
        import database
        from httpx import ASGITransport, AsyncClient
        from main import app

        db_file = tmp_path / "test_api.db"
        original_path = database.DB_PATH
        database.DB_PATH = db_file
        try:
            await database.init_db()
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/catalog/products")
                assert resp.status_code == 200
                data = resp.json()
                assert "products" in data
                assert isinstance(data["products"], list)
        finally:
            database.DB_PATH = original_path

    @pytest.mark.asyncio
    async def test_get_product_detail_with_variants(self, tmp_path):
        """GET /api/catalog/products/{id} returns product with variants and images"""
        import aiosqlite
        import database
        from httpx import ASGITransport, AsyncClient
        from main import app

        db_file = tmp_path / "test_detail.db"
        original_path = database.DB_PATH
        database.DB_PATH = db_file
        try:
            await database.init_db()
            # Insert test product and variant
            async with aiosqlite.connect(str(db_file)) as db:
                db.row_factory = aiosqlite.Row
                await db.execute(
                    "INSERT INTO products (printful_id, name, description, category, thumbnail_url) "
                    "VALUES (99, 'Test Tee', 'Desc', 'T-shirts', 'http://thumb.jpg')"
                )
                await db.execute(
                    "INSERT INTO product_variants (product_id, printful_variant_id, name, size, color, "
                    "color_hex, printful_price, retail_price) VALUES (1, 999, 'Test / S', 'S', 'Black', "
                    "'#000000', 13.50, 20.99)"
                )
                await db.execute(
                    "INSERT INTO product_images (product_id, url, position) VALUES (1, 'http://img.jpg', 0)"
                )
                await db.commit()

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/catalog/products/1")
                assert resp.status_code == 200
                data = resp.json()
                assert data["id"] == 1
                assert data["name"] == "Test Tee"
                assert "variants" in data
                assert len(data["variants"]) == 1
                assert data["variants"][0]["size"] == "S"
                assert data["variants"][0]["color"] == "Black"
                assert data["variants"][0]["retail_price"] == pytest.approx(20.99, abs=0.01)
                assert "images" in data
                assert len(data["images"]) == 1
        finally:
            database.DB_PATH = original_path

    @pytest.mark.asyncio
    async def test_get_product_detail_404_for_missing(self, tmp_path):
        """GET /api/catalog/products/{id} with non-existent ID returns 404"""
        import database
        from httpx import ASGITransport, AsyncClient
        from main import app

        db_file = tmp_path / "test_404.db"
        original_path = database.DB_PATH
        database.DB_PATH = db_file
        try:
            await database.init_db()
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/catalog/products/9999")
                assert resp.status_code == 404
        finally:
            database.DB_PATH = original_path

    @pytest.mark.asyncio
    async def test_list_products_filter_by_category(self, tmp_path):
        """GET /api/catalog/products?category=t-shirts filters by category"""
        import aiosqlite
        import database
        from httpx import ASGITransport, AsyncClient
        from main import app

        db_file = tmp_path / "test_filter.db"
        original_path = database.DB_PATH
        database.DB_PATH = db_file
        try:
            await database.init_db()
            async with aiosqlite.connect(str(db_file)) as db:
                await db.execute(
                    "INSERT INTO products (printful_id, name, category) VALUES (1, 'Tee', 'T-shirts')"
                )
                await db.execute(
                    "INSERT INTO products (printful_id, name, category) VALUES (2, 'Hoodie', 'Hoodies & Sweatshirts')"
                )
                await db.commit()

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/catalog/products?category=t-shirts")
                assert resp.status_code == 200
                data = resp.json()
                assert len(data["products"]) == 1
                assert data["products"][0]["name"] == "Tee"
        finally:
            database.DB_PATH = original_path
