"""
MeatheadGear Printful API v2 client.

Async HTTP client for fetching catalog products and product details from Printful.
Uses httpx.AsyncClient (non-blocking) per Agent42 async I/O conventions.

Rate limit handling: 429 responses return empty results without crashing.
Network error handling: httpx.HTTPError exceptions are caught, logged, and return empty.
"""

import logging
from typing import Any

import httpx

logger = logging.getLogger("meatheadgear.printful")

PRINTFUL_BASE_URL = "https://api.printful.com/v2"

# Gym wear category names to filter from Printful catalog.
# Printful's type_name field uses these category strings.
GYM_WEAR_CATEGORY_IDS = [
    "T-shirts",
    "Hoodies & Sweatshirts",
    "Leggings",
    "Shorts",
    "Hats",
    "Bags",
]


class PrintfulClient:
    """Async Printful API v2 client for catalog fetching."""

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    async def get_catalog_products(self) -> list[dict[str, Any]]:
        """
        Fetch all catalog products from Printful, filtered to gym wear categories.

        Returns:
            List of product dicts matching gym wear categories. Empty list on error or rate limit.
        """
        products: list[dict[str, Any]] = []
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    f"{PRINTFUL_BASE_URL}/catalog-products",
                    headers=self._headers,
                )
                if resp.status_code == 429:
                    logger.warning("Printful rate limited — skipping catalog sync")
                    return []
                resp.raise_for_status()
                data = resp.json()
                # Filter to gym wear categories only
                for product in data.get("data", []):
                    category = product.get("type_name", "")
                    if any(cat.lower() in category.lower() for cat in GYM_WEAR_CATEGORY_IDS):
                        products.append(product)
        except httpx.HTTPError as e:
            logger.error("Printful catalog API error: %s", e)
        return products

    async def get_product_details(self, product_id: int) -> dict[str, Any] | None:
        """
        Fetch detailed product info including variants and pricing.

        Args:
            product_id: Printful catalog product ID.

        Returns:
            Product detail dict with variants and images, or None on error.
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    f"{PRINTFUL_BASE_URL}/catalog-products/{product_id}",
                    headers=self._headers,
                )
                if resp.status_code == 429:
                    logger.warning("Printful rate limited on product %d — skipping", product_id)
                    return None
                resp.raise_for_status()
                return resp.json().get("data")
        except httpx.HTTPError as e:
            logger.error("Printful product %d API error: %s", product_id, e)
            return None
