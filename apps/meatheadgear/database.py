"""
MeatheadGear database module.

Async SQLite via aiosqlite. Uses raw SQL for table creation (no ORM).
Follows Agent42 async I/O conventions — no blocking operations.
"""

from collections.abc import AsyncIterator
from pathlib import Path

import aiosqlite

DB_PATH = Path(__file__).parent / ".data" / "meatheadgear.db"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    reset_token TEXT,
    reset_token_expires TIMESTAMP
);

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    printful_id INTEGER UNIQUE NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT '',
    thumbnail_url TEXT NOT NULL DEFAULT '',
    is_active INTEGER NOT NULL DEFAULT 1,
    synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS product_variants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    printful_variant_id INTEGER UNIQUE NOT NULL,
    name TEXT NOT NULL,
    size TEXT NOT NULL DEFAULT '',
    color TEXT NOT NULL DEFAULT '',
    color_hex TEXT NOT NULL DEFAULT '',
    printful_price REAL NOT NULL DEFAULT 0.0,
    retail_price REAL NOT NULL DEFAULT 0.0,
    in_stock INTEGER NOT NULL DEFAULT 1,
    synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS product_images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    url TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,
    variant_id INTEGER REFERENCES product_variants(id) ON DELETE SET NULL
);
"""


async def init_db() -> None:
    """Initialize database and create all tables if they don't exist."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(str(DB_PATH)) as db:
        await db.executescript(SCHEMA_SQL)
        await db.commit()


async def get_db() -> AsyncIterator[aiosqlite.Connection]:
    """Yield an async database connection with Row factory."""
    db = await aiosqlite.connect(str(DB_PATH))
    db.row_factory = aiosqlite.Row
    try:
        yield db
    finally:
        await db.close()
