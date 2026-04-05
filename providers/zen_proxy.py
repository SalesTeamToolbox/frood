"""
Local Zen API proxy with adaptive per-model rate limiting.

Runs as a lightweight HTTP server that intercepts ALL Zen API traffic
(from OpenCode CLI, Agent42 agents, etc.) and applies TCP-style congestion
control before forwarding to the real Zen API.

This ensures a single rate-limit budget across all consumers, preventing
the "request rate increased too quickly" errors from free-tier models.

Rate limits are per-model (resolved by vendor prefix matching), so a
rate-limited Qwen doesn't throttle MiniMax or Nemotron calls.

Usage:
    python -m providers.zen_proxy          # standalone (port 8765)
    # or started programmatically from MCP server lifecycle
"""

import asyncio
import json
import logging
import os
import re
from typing import Any

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from core.rate_limiter import PerModelRateLimiter

logger = logging.getLogger("agent42.zen_proxy")

DEFAULT_PORT = 8765
DEFAULT_BIND = "127.0.0.1"

# Rate-limit error patterns from upstream providers
_RATE_LIMIT_PATTERNS = [
    r"rate\s*limit",
    r"too\s*many\s*requests",
    r"request\s*rate\s*increased\s*too\s*quickly",
    r"scale\s*requests\s*more\s*smoothly",
    r"slow\s*down",
    r"throttl",
]


def _extract_model_from_body(body: bytes) -> str | None:
    """Extract the model ID from a JSON request body.

    Handles both OpenAI-style ({"model": "..."}) and Anthropic-style
    ({"model": "..."}) payloads. Returns None if model can't be found.
    """
    try:
        data = json.loads(body)
        return data.get("model")
    except (json.JSONDecodeError, TypeError):
        return None


class ZenProxy:
    """Local proxy that rate-limits all Zen API traffic per model."""

    def __init__(
        self,
        upstream_url: str = "https://opencode.ai/zen/v1",
        enabled: bool = True,
        port: int = DEFAULT_PORT,
    ):
        self._upstream = upstream_url.rstrip("/")
        self._enabled = enabled
        self._port = port
        self._rate_limiter = PerModelRateLimiter()
        self._client: httpx.AsyncClient | None = None
        self._server_task: asyncio.Task | None = None

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    @property
    def local_url(self) -> str:
        """URL that clients should use to reach this proxy."""
        return f"http://{DEFAULT_BIND}:{self._port}"

    @property
    def stats(self) -> dict:
        return self._rate_limiter.get_stats()

    async def start(self) -> None:
        """Start the proxy HTTP server in the background."""
        if not self._enabled:
            logger.info("Zen proxy disabled — clients will connect directly")
            return

        self._client = httpx.AsyncClient(timeout=120.0)
        app = self._build_app()

        import uvicorn

        config = uvicorn.Config(
            app,
            host=DEFAULT_BIND,
            port=self._port,
            log_level="warning",
            access_log=False,
        )
        server = uvicorn.Server(config)
        self._server_task = asyncio.create_task(server.serve())

        # Wait for server to be ready
        await asyncio.sleep(0.3)
        logger.info(
            "Zen proxy started on %s:%d (upstream: %s)",
            DEFAULT_BIND,
            self._port,
            self._upstream,
        )

    async def stop(self) -> None:
        """Shutdown the proxy server."""
        if self._server_task:
            self._server_task.cancel()
            try:
                await self._server_task
            except asyncio.CancelledError:
                pass
            self._server_task = None
        if self._client:
            await self._client.aclose()
            self._client = None
        logger.info("Zen proxy stopped")

    def _build_app(self) -> Starlette:
        """Build the Starlette app with a catch-all proxy route."""

        async def catch_all(request: Request) -> Response:
            return await self._proxy_request(request)

        app = Starlette(
            routes=[
                Route(
                    "/{path:path}",
                    endpoint=catch_all,
                    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
                ),
            ]
        )
        return app

    async def _proxy_request(self, request: Request) -> Response:
        """Forward a request to upstream Zen API with per-model rate limiting."""
        if not self._enabled:
            return JSONResponse(
                {"error": "Zen proxy is disabled"},
                status_code=503,
            )

        # Build upstream URL
        path = request.path_params.get("path", "")
        upstream_url = f"{self._upstream}/{path}"

        # Forward headers (preserve auth, strip hop-by-hop)
        headers = {
            k: v
            for k, v in request.headers.items()
            if k.lower() not in ("host", "connection", "transfer-encoding")
        }

        # Read body
        body = await request.body()

        # Extract model from body for per-model rate limiting
        model = _extract_model_from_body(body)

        if not self._client:
            return JSONResponse({"error": "Proxy not started"}, status_code=503)

        # Apply per-model rate limiting on chat completion requests
        if model and path == "chat/completions":
            await self._rate_limiter.wait(model)

        max_retries = 3
        last_error: str | None = None

        for attempt in range(max_retries + 1):
            try:
                resp = await self._client.request(
                    method=request.method,
                    url=upstream_url,
                    headers=headers,
                    content=body,
                    params=request.query_params,
                )

                # 429 — rate limited by upstream
                if resp.status_code == 429:
                    retry_after = self._parse_retry_after(resp)
                    if model:
                        self._rate_limiter.record_rate_limit(model, retry_after)
                    logger.warning(
                        "Zen upstream rate limited (model=%s, attempt %d/%d), retry_after=%.1fs",
                        model or "unknown",
                        attempt + 1,
                        max_retries,
                        retry_after or 0,
                    )
                    if attempt < max_retries:
                        wait = retry_after
                        if not wait and model:
                            wait = self._rate_limiter.get_stats(model).get("current_delay", 3.0)
                        await asyncio.sleep(wait or 3.0)
                        continue
                    return self._error_response(
                        429,
                        f"Rate limited after {max_retries + 1} attempts. Slow down.",
                    )

                # Other errors — check for rate-limit text
                if resp.status_code >= 400:
                    error_text = (await resp.aread()).decode("utf-8", errors="replace")[:500]
                    if self._is_rate_limit_error(error_text):
                        if model:
                            self._rate_limiter.record_rate_limit(model)
                        logger.warning(
                            "Zen upstream rate error (model=%s, attempt %d/%d): %s",
                            model or "unknown",
                            attempt + 1,
                            max_retries,
                            error_text[:200],
                        )
                        if attempt < max_retries:
                            wait = 3.0
                            if model:
                                wait = self._rate_limiter.get_stats(model).get("current_delay", 3.0)
                            await asyncio.sleep(wait)
                            continue
                        return self._error_response(resp.status_code, error_text[:300])
                    else:
                        if model:
                            self._rate_limiter.record_error(model)
                    return Response(
                        content=error_text.encode(),
                        status_code=resp.status_code,
                        headers=dict(resp.headers),
                        media_type=resp.headers.get("content-type", "application/json"),
                    )

                # Success
                if model:
                    self._rate_limiter.record_success(model)
                return Response(
                    content=await resp.aread(),
                    status_code=resp.status_code,
                    headers=dict(resp.headers),
                    media_type=resp.headers.get("content-type", "application/json"),
                )

            except httpx.TimeoutException:
                if model:
                    self._rate_limiter.record_error(model)
                last_error = "Request timed out"
                if attempt < max_retries:
                    wait = 3.0
                    if model:
                        delay = self._rate_limiter.get_stats(model).get("current_delay", 3.0)
                        wait = delay * (attempt + 1)
                    await asyncio.sleep(wait)
                    continue
                return self._error_response(504, last_error)

            except httpx.RequestError as e:
                if model:
                    self._rate_limiter.record_error(model)
                last_error = str(e)
                if attempt < max_retries:
                    wait = 3.0
                    if model:
                        delay = self._rate_limiter.get_stats(model).get("current_delay", 3.0)
                        wait = delay * (attempt + 1)
                    await asyncio.sleep(wait)
                    continue
                return self._error_response(502, last_error)

        return self._error_response(500, last_error or "Max retries exceeded")

    @staticmethod
    def _parse_retry_after(resp: httpx.Response) -> float | None:
        header = resp.headers.get("retry-after")
        if header:
            try:
                return float(header)
            except (ValueError, TypeError):
                pass
        return None

    @staticmethod
    def _is_rate_limit_error(text: str) -> bool:
        text_lower = text.lower()
        return any(re.search(p, text_lower) for p in _RATE_LIMIT_PATTERNS)

    @staticmethod
    def _error_response(status_code: int, message: str) -> JSONResponse:
        return JSONResponse(
            {"error": message[:500]},
            status_code=status_code,
        )


# Module-level singleton
_proxy: ZenProxy | None = None


def get_proxy() -> ZenProxy:
    """Get or create the Zen proxy singleton."""
    global _proxy
    if _proxy is None:
        from core.config import settings

        _proxy = ZenProxy(
            upstream_url=settings.zen_base_url or "https://opencode.ai/zen/v1",
            enabled=settings.zen_proxy_enabled,
            port=settings.zen_proxy_port,
        )
    return _proxy


async def start_proxy() -> ZenProxy:
    """Start the Zen proxy server. Safe to call multiple times."""
    proxy = get_proxy()
    await proxy.start()
    return proxy


async def stop_proxy() -> None:
    """Stop the Zen proxy server."""
    global _proxy
    if _proxy:
        await _proxy.stop()
        _proxy = None
