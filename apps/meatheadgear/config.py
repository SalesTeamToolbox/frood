"""
MeatheadGear configuration.

Frozen dataclass loaded from environment variables at import time.
Follows the Agent42 config pattern from core/config.py.
"""

import os
import secrets
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    """Immutable application settings derived from environment variables."""

    secret_key: str = ""
    printful_api_key: str = ""
    database_url: str = "sqlite+aiosqlite:///apps/meatheadgear/.data/meatheadgear.db"
    port: int = 8001
    host: str = "127.0.0.1"
    printful_sync_interval_hours: int = 6
    jwt_expiry_days: int = 7
    target_margin: float = 0.35
    resend_api_key: str = ""

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            secret_key=os.getenv("SECRET_KEY", secrets.token_hex(32)),
            printful_api_key=os.getenv("PRINTFUL_API_KEY", ""),
            database_url=os.getenv(
                "DATABASE_URL",
                "sqlite+aiosqlite:///apps/meatheadgear/.data/meatheadgear.db",
            ),
            port=int(os.getenv("PORT", "8001")),
            host=os.getenv("HOST", "127.0.0.1"),
            printful_sync_interval_hours=int(os.getenv("PRINTFUL_SYNC_INTERVAL_HOURS", "6")),
            jwt_expiry_days=int(os.getenv("JWT_EXPIRY_DAYS", "7")),
            target_margin=float(os.getenv("TARGET_MARGIN", "0.35")),
            resend_api_key=os.getenv("RESEND_API_KEY", ""),
        )


settings = Settings.from_env()
