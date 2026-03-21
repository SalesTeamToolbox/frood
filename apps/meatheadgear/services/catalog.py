"""
MeatheadGear catalog sync service.

Orchestrates syncing products from Printful API into local SQLite:
  1. Fetches gym wear products via PrintfulClient
  2. Calculates retail prices via calculate_retail_price()
  3. Upserts products, variants, and images to SQLite

Background sync: start_background_sync() runs every N hours (default 6).

Graceful degradation: if PRINTFUL_API_KEY is not set, sync is skipped.
Catalog API endpoints continue to work from local DB regardless.
"""

import asyncio
import logging
from datetime import UTC, datetime

import aiosqlite
import database

from config import settings
from services.pricing import calculate_retail_price
from services.printful import PrintfulClient

logger = logging.getLogger("meatheadgear.catalog")


async def sync_catalog() -> None:
    """
    Fetch products from Printful, calculate retail prices, upsert to SQLite.

    If PRINTFUL_API_KEY is not set, logs a warning and returns immediately.
    The catalog API endpoints will still serve whatever is in the local DB.

    Uses database.DB_PATH (resolved at call time, not import time) so tests
    can patch database.DB_PATH before calling this function.
    """
    if not settings.printful_api_key:
        logger.warning("PRINTFUL_API_KEY not set — skipping catalog sync")
        return

    client = PrintfulClient(settings.printful_api_key)
    products = await client.get_catalog_products()
    logger.info("Fetched %d gym wear products from Printful", len(products))

    # Use database.DB_PATH here (not a local import-time binding) so test patches work
    db_path = str(database.DB_PATH)

    async with aiosqlite.connect(db_path) as db:
        for product in products:
            now = datetime.now(UTC).isoformat()

            # Upsert product record
            await db.execute(
                """INSERT INTO products (printful_id, name, description, category, thumbnail_url, synced_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(printful_id) DO UPDATE SET
                       name=excluded.name,
                       description=excluded.description,
                       category=excluded.category,
                       thumbnail_url=excluded.thumbnail_url,
                       synced_at=excluded.synced_at""",
                (
                    product["id"],
                    product.get("title", ""),
                    product.get("description", ""),
                    product.get("type_name", ""),
                    product.get("image", ""),
                    now,
                ),
            )

            # Fetch detailed product info for variants and images
            details = await client.get_product_details(product["id"])
            if not details:
                continue

            # Get the local product ID after upsert
            cursor = await db.execute(
                "SELECT id FROM products WHERE printful_id = ?", (product["id"],)
            )
            row = await cursor.fetchone()
            if not row:
                continue
            local_product_id = row[0]

            # Upsert variants
            for variant in details.get("variants", []):
                printful_price = float(variant.get("price", 0))
                retail_price = calculate_retail_price(printful_price, settings.target_margin)
                is_active = 0 if variant.get("availability_status") == "discontinued" else 1

                await db.execute(
                    """INSERT INTO product_variants
                       (product_id, printful_variant_id, name, size, color, color_hex,
                        printful_price, retail_price, in_stock, synced_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(printful_variant_id) DO UPDATE SET
                           name=excluded.name,
                           size=excluded.size,
                           color=excluded.color,
                           color_hex=excluded.color_hex,
                           printful_price=excluded.printful_price,
                           retail_price=excluded.retail_price,
                           in_stock=excluded.in_stock,
                           synced_at=excluded.synced_at""",
                    (
                        local_product_id,
                        variant["id"],
                        variant.get("name", ""),
                        variant.get("size", ""),
                        variant.get("color", ""),
                        variant.get("color_code", ""),
                        printful_price,
                        retail_price,
                        is_active,
                        now,
                    ),
                )

            # Upsert images (skip duplicates by URL)
            for idx, image in enumerate(details.get("images", [])):
                url = image.get("url", "")
                if not url:
                    continue
                await db.execute(
                    """INSERT INTO product_images (product_id, url, position)
                       VALUES (?, ?, ?)
                       ON CONFLICT DO NOTHING""",
                    (local_product_id, url, idx),
                )

        await db.commit()

    logger.info("Catalog sync complete — %d products synced", len(products))


async def start_background_sync() -> None:
    """
    Start background task that re-syncs catalog every N hours.

    Runs in an infinite loop with asyncio.sleep() between syncs.
    Errors are caught and logged — the loop continues regardless.
    """
    interval = settings.printful_sync_interval_hours * 3600
    while True:
        await asyncio.sleep(interval)
        try:
            await sync_catalog()
        except Exception as e:
            logger.error("Background catalog sync failed: %s", e)
