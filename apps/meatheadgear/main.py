"""
MeatheadGear FastAPI application entry point.

AI-powered gym apparel storefront with Printful POD integration.
Runs on port 8001 (Agent42 dashboard is on 8000).
"""

import asyncio
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

# Ensure the app directory is on the path when run from repo root
sys.path.insert(0, str(Path(__file__).parent))

from database import init_db
from routers.auth import router as auth_router
from routers.catalog import router as catalog_router
from services.catalog import start_background_sync, sync_catalog

from config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle: init DB on startup, then kick off catalog sync."""
    await init_db()
    # Non-blocking catalog sync — server starts immediately, catalog populates in background
    asyncio.create_task(sync_catalog())
    asyncio.create_task(start_background_sync())
    yield


app = FastAPI(
    title="MeatheadGear",
    version="0.1.0",
    description="AI-powered gym apparel storefront with Printful POD integration",
    lifespan=lifespan,
)

# Register routers
app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
app.include_router(catalog_router, prefix="/api/catalog", tags=["catalog"])

# Serve frontend assets
_frontend_dir = Path(__file__).parent / "frontend"
if _frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=str(_frontend_dir)), name="static")


@app.get("/api/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok", "app": "meatheadgear", "version": "0.1.0"}


@app.get("/")
async def root():
    """Root redirect — frontend served from /static."""
    return {"status": "ok", "app": "meatheadgear"}


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )
