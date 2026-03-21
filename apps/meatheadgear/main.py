"""
MeatheadGear FastAPI application entry point.

AI-powered gym apparel storefront with Printful POD integration.
Runs on port 8001 (Agent42 dashboard is on 8000).
"""

import sys
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

# Ensure the app directory is on the path when run from repo root
sys.path.insert(0, str(Path(__file__).parent))

from database import init_db

from config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle: init DB on startup."""
    await init_db()
    yield


app = FastAPI(
    title="MeatheadGear",
    version="0.1.0",
    description="AI-powered gym apparel storefront with Printful POD integration",
    lifespan=lifespan,
)

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
