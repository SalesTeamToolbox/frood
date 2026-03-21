"""
MeatheadGear catalog router.

Read-only product browsing API. All data served from local SQLite — endpoints
work even when Printful API is unreachable. Catalog is populated by sync_catalog().

Endpoints:
  GET /products           — list active products with price ranges
  GET /products/{id}      — product detail with variants and images
"""

from database import get_db
from fastapi import APIRouter, Depends, HTTPException

router = APIRouter()


@router.get("/products")
async def list_products(category: str | None = None, db=Depends(get_db)):
    """
    List active products with optional category filter.

    Query params:
        category: Optional substring match on category (case-insensitive).

    Returns:
        {"products": [...]} where each product has id, printful_id, name, category,
        thumbnail_url, price_min, price_max.
    """
    query = (
        "SELECT id, printful_id, name, category, thumbnail_url FROM products WHERE is_active = 1"
    )
    params: list = []

    if category:
        query += " AND LOWER(category) LIKE ?"
        params.append(f"%{category.lower()}%")

    cursor = await db.execute(query, params)
    products = await cursor.fetchall()

    result = []
    for p in products:
        price_cursor = await db.execute(
            "SELECT MIN(retail_price), MAX(retail_price) "
            "FROM product_variants WHERE product_id = ? AND in_stock = 1",
            (p[0],),
        )
        prices = await price_cursor.fetchone()
        result.append(
            {
                "id": p[0],
                "printful_id": p[1],
                "name": p[2],
                "category": p[3],
                "thumbnail_url": p[4],
                "price_min": prices[0] if prices[0] is not None else 0,
                "price_max": prices[1] if prices[1] is not None else 0,
            }
        )

    return {"products": result}


@router.get("/products/{product_id}")
async def get_product(product_id: int, db=Depends(get_db)):
    """
    Get product detail with variants and images.

    Args:
        product_id: Local SQLite product ID.

    Returns:
        Product dict with id, printful_id, name, description, category, thumbnail_url,
        variants (list), images (list).

    Raises:
        404 if product not found or inactive.
    """
    cursor = await db.execute(
        "SELECT id, printful_id, name, description, category, thumbnail_url "
        "FROM products WHERE id = ? AND is_active = 1",
        (product_id,),
    )
    product = await cursor.fetchone()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    var_cursor = await db.execute(
        "SELECT id, name, size, color, color_hex, retail_price, in_stock "
        "FROM product_variants WHERE product_id = ?",
        (product_id,),
    )
    variants = [
        {
            "id": v[0],
            "name": v[1],
            "size": v[2],
            "color": v[3],
            "color_hex": v[4],
            "retail_price": v[5],
            "in_stock": bool(v[6]),
        }
        for v in await var_cursor.fetchall()
    ]

    img_cursor = await db.execute(
        "SELECT url, position FROM product_images WHERE product_id = ? ORDER BY position",
        (product_id,),
    )
    images = [{"url": i[0], "position": i[1]} for i in await img_cursor.fetchall()]

    return {
        "id": product[0],
        "printful_id": product[1],
        "name": product[2],
        "description": product[3],
        "category": product[4],
        "thumbnail_url": product[5],
        "variants": variants,
        "images": images,
    }
