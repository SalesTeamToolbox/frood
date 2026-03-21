"""
MeatheadGear data models.

Python dataclasses for type-safe data transfer between database and API.
Uses raw SQL — these are NOT SQLAlchemy ORM models.
"""

from dataclasses import dataclass


@dataclass
class User:
    id: int
    email: str
    password_hash: str
    name: str
    created_at: str
    updated_at: str
    reset_token: str | None = None
    reset_token_expires: str | None = None


@dataclass
class Product:
    id: int
    printful_id: int
    name: str
    description: str
    category: str
    thumbnail_url: str
    is_active: bool
    synced_at: str
    created_at: str


@dataclass
class ProductVariant:
    id: int
    product_id: int
    printful_variant_id: int
    name: str
    size: str
    color: str
    color_hex: str
    printful_price: float
    retail_price: float
    in_stock: bool
    synced_at: str


@dataclass
class ProductImage:
    id: int
    product_id: int
    url: str
    position: int
    variant_id: int | None = None
