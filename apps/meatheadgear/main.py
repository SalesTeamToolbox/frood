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
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# Ensure the app directory is on the path when run from repo root
sys.path.insert(0, str(Path(__file__).parent))

from database import init_db
from routers.auth import router as auth_router
from routers.catalog import router as catalog_router
from services.catalog import start_background_sync, sync_catalog

from config import settings

FRONTEND_DIR = Path(__file__).parent / "frontend"


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

# CORS — allows frontend dev server and same-origin production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8001", "http://127.0.0.1:8001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API routers first — FastAPI matches in order, static catch-all must be last
app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
app.include_router(catalog_router, prefix="/api/catalog", tags=["catalog"])


@app.get("/api/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok", "app": "meatheadgear", "version": "0.1.0"}


@app.get("/")
async def root():
    """Serve the storefront SPA entry point."""
    return FileResponse(FRONTEND_DIR / "index.html")


# Static files mount — AFTER all API routes (catch-all must be last)
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )
