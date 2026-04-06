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
from starlette.responses import JSONResponse, Response, StreamingResponse
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

# Free Zen models — used for fallback chain ordering
_ZEN_FREE_MODELS = [
    "qwen3.6-plus-free",
    "minimax-m2.5-free",
    "nemotron-3-super-free",
    "big-pickle",
    "trinity-large-preview-free",
]

# Known paid Zen models (for ZEN_ALLOW_PAID passthrough check)
_ZEN_PAID_MODELS = {
    "claude-opus-4-6",
    "claude-opus-4-5",
    "claude-opus-4-1",
    "claude-sonnet-4-6",
    "claude-sonnet-4-5",
    "claude-sonnet-4",
    "claude-haiku-4-5",
    "claude-3-5-haiku",
    "gemini-3.1-pro",
    "gemini-3-pro",
    "gemini-3-flash",
    "gpt-5.4",
    "gpt-5.4-pro",
    "gpt-5.4-mini",
    "gpt-5.4-nano",
    "gpt-5.3-codex-spark",
    "gpt-5.3-codex",
    "gpt-5.2",
    "gpt-5.2-codex",
    "gpt-5.1",
    "gpt-5.1-codex-max",
    "gpt-5.1-codex",
    "gpt-5.1-codex-mini",
    "gpt-5",
    "gpt-5-codex",
    "gpt-5-nano",
    "glm-5",
    "glm-4.7",
    "glm-4.6",
    "minimax-m2.5",
    "minimax-m2.1",
    "kimi-k2.5",
    "kimi-k2",
    "kimi-k2-thinking",
}


def _is_known_zen_model(model: str) -> bool:
    """Check if a model is a known Zen model (free or paid)."""
    return model in _ZEN_FREE_MODELS or model in _ZEN_PAID_MODELS


def _get_fallback_chain(default_model: str) -> list[str]:
    """Build ordered fallback chain starting with the user's default model."""
    chain = [default_model]
    for m in _ZEN_FREE_MODELS:
        if m != default_model:
            chain.append(m)
    return chain


def _swap_model(body: bytes, new_model: str) -> bytes:
    """Replace the model field in a JSON body."""
    try:
        data = json.loads(body)
        data["model"] = new_model
        return json.dumps(data).encode("utf-8")
    except (json.JSONDecodeError, TypeError):
        return body


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


def _is_anthropic_path(path: str) -> bool:
    """Detect Anthropic-style API paths that need translation."""
    return "messages" in path or "v1/messages" in path


def _anthropic_to_openai(body: bytes) -> bytes:
    """Translate Anthropic /v1/messages format to OpenAI /chat/completions format.

    Claude Code sends POST /v1/messages with Anthropic schema:
    - system as a separate top-level field
    - messages array with role "user"/"assistant"/"tool"
    - max_tokens, stop_sequences, temperature, etc.

    Zen API only accepts OpenAI /chat/completions format:
    - system as a message with role "system"
    - messages array with role "system"/"user"/"assistant"/"tool"
    - max_tokens, stop, temperature, etc.
    """
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return body

    openai_body: dict[str, Any] = {}

    # Model resolution — supports 3 modes:
    #   1. "zen:model-name"  → explicit Zen model (bypasses remapping)
    #   2. Claude/Anthropic names → remapped to ZEN_DEFAULT_MODEL (free)
    #   3. Already a Zen model → passed through as-is
    # ZEN_ALLOW_PAID=true skips remapping for known paid Zen models
    _default = os.environ.get("ZEN_DEFAULT_MODEL", "qwen3.6-plus-free")
    _allow_paid = os.environ.get("ZEN_ALLOW_PAID", "false").lower() in ("true", "1", "yes")
    _REMAP_PREFIXES = ("claude-", "anthropic/")
    _REMAP_ALIASES = {"sonnet", "opus", "haiku"}

    if "model" in data:
        original_model = data["model"]

        if original_model.startswith("zen:"):
            # Explicit Zen model selection: "zen:nemotron-3-super-free"
            openai_body["model"] = original_model[4:]
        elif _allow_paid and _is_known_zen_model(original_model):
            # Paid passthrough: model is a known Zen model and paid is allowed
            openai_body["model"] = original_model
        elif original_model in _REMAP_ALIASES or any(
            original_model.startswith(p) for p in _REMAP_PREFIXES
        ):
            # Claude model → remap to user's default free model
            openai_body["model"] = _default
        else:
            openai_body["model"] = original_model

    # System message: Anthropic uses top-level "system" (string or array)
    system = data.get("system")
    if system:
        if isinstance(system, str):
            openai_body["messages"] = [{"role": "system", "content": system}]
        elif isinstance(system, list):
            content_parts = []
            for block in system:
                if isinstance(block, str):
                    content_parts.append(block)
                elif isinstance(block, dict):
                    content_parts.append(block.get("text", ""))
            openai_body["messages"] = [{"role": "system", "content": " ".join(content_parts)}]

    # Messages array
    messages = data.get("messages", [])
    if "messages" not in openai_body:
        openai_body["messages"] = []

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        # Anthropic content can be string or array of blocks
        if isinstance(content, list):
            text_parts = []
            for block in content:
                if isinstance(block, str):
                    text_parts.append(block)
                elif isinstance(block, dict):
                    if block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                    elif block.get("type") == "tool_use":
                        text_parts.append(json.dumps(block))
                    elif block.get("type") == "tool_result":
                        text_parts.append(json.dumps(block))
            content = " ".join(text_parts)
        openai_body["messages"].append({"role": role, "content": content})

    # Parameter mapping
    if "max_tokens" in data:
        openai_body["max_tokens"] = data["max_tokens"]
    if "temperature" in data:
        openai_body["temperature"] = data["temperature"]
    if "top_p" in data:
        openai_body["top_p"] = data["top_p"]
    if "stop_sequences" in data:
        openai_body["stop"] = data["stop_sequences"]
    if "stream" in data:
        openai_body["stream"] = data["stream"]

    return json.dumps(openai_body).encode("utf-8")


def _openai_to_anthropic(openai_resp: dict, model: str = "") -> dict:
    """Translate OpenAI Chat Completions response to Anthropic Messages format.

    Claude Code CLI expects Anthropic Messages API responses:
    - id, type="message", role="assistant"
    - content: [{type: "text", text: "..."}]
    - stop_reason, usage with input_tokens/output_tokens
    """
    import uuid as _uuid

    choice = openai_resp.get("choices", [{}])[0]
    msg = choice.get("message", {})
    content_text = msg.get("content", "")
    finish = choice.get("finish_reason", "stop")

    # Map OpenAI finish reasons to Anthropic stop reasons
    stop_reason_map = {
        "stop": "end_turn",
        "length": "max_tokens",
        "content_filter": "end_turn",
        "tool_calls": "tool_use",
    }

    usage = openai_resp.get("usage", {})

    # Build content blocks
    content_blocks = []
    if content_text:
        content_blocks.append({"type": "text", "text": content_text})

    # Handle tool calls if present
    tool_calls = msg.get("tool_calls", [])
    for tc in tool_calls:
        fn = tc.get("function", {})
        try:
            args = json.loads(fn.get("arguments", "{}"))
        except (json.JSONDecodeError, TypeError):
            args = {}
        content_blocks.append(
            {
                "type": "tool_use",
                "id": tc.get("id", f"toolu_{_uuid.uuid4().hex[:12]}"),
                "name": fn.get("name", ""),
                "input": args,
            }
        )

    if not content_blocks:
        content_blocks.append({"type": "text", "text": ""})

    return {
        "id": f"msg_{_uuid.uuid4().hex[:12]}",
        "type": "message",
        "role": "assistant",
        "content": content_blocks,
        "model": model or openai_resp.get("model", ""),
        "stop_reason": stop_reason_map.get(finish, "end_turn"),
        "stop_sequence": None,
        "usage": {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
        },
    }


def _translate_auth_headers(headers: dict) -> dict:
    """Translate Anthropic auth headers to OpenAI-style Bearer auth.

    Claude Code sends: x-api-key: <key>
    Zen/OpenRouter expect: Authorization: Bearer <key>

    If the key is empty/dummy, auto-resolve from ZEN_API_KEY in os.environ
    (injected by KeyStore at Agent42 startup).
    """
    import os as _os

    translated = dict(headers)
    api_key = headers.get("x-api-key", "")

    # Auto-resolve key: replace dummy/Anthropic-format keys with real Zen key
    zen_key = _os.environ.get("ZEN_API_KEY", "")
    if (
        not api_key
        or api_key.startswith("sk-ant-")
        or api_key in ("dummy", "dummy-key", "placeholder")
    ):
        if zen_key:
            api_key = zen_key

    if api_key and "authorization" not in {k.lower() for k in headers}:
        translated["Authorization"] = f"Bearer {api_key}"
    translated.pop("x-api-key", None)
    # Remove anthropic-specific headers that confuse OpenAI endpoints
    translated.pop("anthropic-version", None)
    translated.pop("anthropic-beta", None)
    return translated


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

        # Auto-inject ZEN_API_KEY from key store if not in env
        if not os.environ.get("ZEN_API_KEY"):
            try:
                from core.key_store import KeyStore

                ks = KeyStore()
                ks.inject_into_environ()
            except Exception:
                pass

    def _create_client(self) -> httpx.AsyncClient:
        """Create an httpx client tuned for proxy reliability."""
        limits = httpx.Limits(
            max_connections=200,
            max_keepalive_connections=50,
            keepalive_expiry=30.0,
        )
        timeout = httpx.Timeout(
            connect=15.0,
            read=120.0,
            write=30.0,
            pool=10.0,
        )
        return httpx.AsyncClient(
            timeout=timeout,
            limits=limits,
            http2=True,
        )

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

        self._client = self._create_client()
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

        # Proactive path detection: rewrite Anthropic-style paths to OpenAI
        anthropic_path = _is_anthropic_path(path)
        if anthropic_path:
            path = "chat/completions"
            upstream_url = f"{self._upstream}/{path}"
            body = _anthropic_to_openai(body)
            headers = _translate_auth_headers(headers)
            # Clean headers: only keep essential ones for upstream
            clean_headers = {
                "Authorization": headers.get("Authorization", ""),
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
            headers = {k: v for k, v in clean_headers.items() if v}
            logger.info(
                "Anthropic->OpenAI: %s -> %s (model=%s, auth=%s)",
                request.path_params.get("path", ""),
                path,
                _extract_model_from_body(body),
                bool(headers.get("Authorization")),
            )

        # Extract model from body for per-model rate limiting
        model = _extract_model_from_body(body)

        if not self._client:
            return JSONResponse({"error": "Proxy not started"}, status_code=503)

        # Apply per-model rate limiting on chat completion requests
        if model and path == "chat/completions":
            await self._rate_limiter.wait(model)

        # Fast path: streaming + Anthropic translation uses dedicated handler
        is_stream = False
        try:
            is_stream = bool(body and json.loads(body).get("stream", False))
        except (json.JSONDecodeError, TypeError):
            pass

        if is_stream and anthropic_path:
            return await self._handle_streaming_anthropic(
                upstream_url, headers, body, model, request.query_params
            )

        max_retries = 3
        last_error: str | None = None
        translated_405 = False

        for attempt in range(max_retries + 1):
            try:
                resp = await self._client.request(
                    method=request.method,
                    url=upstream_url,
                    headers=headers,
                    content=body,
                    params=request.query_params,
                )

                # 405 — Method Not Allowed: likely Anthropic format hitting OpenAI-only endpoint
                if resp.status_code == 405 and not translated_405:
                    error_text = (await resp.aread()).decode("utf-8", errors="replace")[:500]
                    logger.warning(
                        "405 on attempt %d, translating Anthropic->OpenAI and retrying",
                        attempt + 1,
                    )
                    # Re-read original body and translate
                    original_body = await request.body()
                    body = _anthropic_to_openai(original_body)
                    path = "chat/completions"
                    upstream_url = f"{self._upstream}/{path}"
                    model = _extract_model_from_body(body)
                    translated_405 = True
                    continue

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

                # Stream the response through instead of buffering
                is_stream = body and json.loads(body).get("stream", False) if body else False
                if is_stream and anthropic_path:
                    # Translate OpenAI SSE stream to Anthropic SSE stream
                    async def stream_anthropic(response=resp, _model=model):
                        import uuid as _uuid

                        msg_id = f"msg_{_uuid.uuid4().hex[:12]}"
                        # Emit message_start
                        start_event = {
                            "type": "message_start",
                            "message": {
                                "id": msg_id,
                                "type": "message",
                                "role": "assistant",
                                "content": [],
                                "model": _model or "",
                                "stop_reason": None,
                                "stop_sequence": None,
                                "usage": {"input_tokens": 0, "output_tokens": 0},
                            },
                        }
                        yield f"event: message_start\ndata: {json.dumps(start_event)}\n\n".encode()

                        # Emit content_block_start
                        block_start = {
                            "type": "content_block_start",
                            "index": 0,
                            "content_block": {"type": "text", "text": ""},
                        }
                        yield f"event: content_block_start\ndata: {json.dumps(block_start)}\n\n".encode()

                        # Stream content deltas from OpenAI SSE
                        try:
                            buffer = b""
                            async for chunk in response.aiter_bytes(chunk_size=8192):
                                buffer += chunk
                                while b"\n" in buffer:
                                    line, buffer = buffer.split(b"\n", 1)
                                    line_str = line.decode("utf-8", errors="replace").strip()
                                    if not line_str.startswith("data: "):
                                        continue
                                    data_str = line_str[6:]
                                    if data_str == "[DONE]":
                                        break
                                    try:
                                        sse_data = json.loads(data_str)
                                        delta = sse_data.get("choices", [{}])[0].get("delta", {})
                                        text = delta.get("content", "")
                                        if text:
                                            delta_event = {
                                                "type": "content_block_delta",
                                                "index": 0,
                                                "delta": {"type": "text_delta", "text": text},
                                            }
                                            yield f"event: content_block_delta\ndata: {json.dumps(delta_event)}\n\n".encode()
                                    except (json.JSONDecodeError, IndexError):
                                        pass
                        except Exception:
                            pass

                        # Emit content_block_stop + message_delta + message_stop
                        yield b'event: content_block_stop\ndata: {"type": "content_block_stop", "index": 0}\n\n'
                        delta_msg = {
                            "type": "message_delta",
                            "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                            "usage": {"output_tokens": 0},
                        }
                        yield f"event: message_delta\ndata: {json.dumps(delta_msg)}\n\n".encode()
                        yield b'event: message_stop\ndata: {"type": "message_stop"}\n\n'

                    return StreamingResponse(
                        stream_anthropic(),
                        status_code=resp.status_code,
                        media_type="text/event-stream",
                        headers={"cache-control": "no-cache"},
                    )

                if is_stream and not anthropic_path:
                    # Pass-through streaming for native OpenAI clients
                    async def stream_upstream(response=resp):
                        try:
                            async for chunk in response.aiter_bytes(chunk_size=8192):
                                yield chunk
                        except Exception:
                            pass

                    out_headers = dict(resp.headers)
                    out_headers.pop("content-encoding", None)
                    out_headers.pop("transfer-encoding", None)
                    out_headers.pop("content-length", None)
                    return StreamingResponse(
                        stream_upstream(),
                        status_code=resp.status_code,
                        headers=out_headers,
                        media_type=resp.headers.get("content-type", "application/json"),
                    )

                resp_body = await resp.aread()

                # Translate OpenAI response back to Anthropic format if needed
                if anthropic_path:
                    try:
                        openai_data = json.loads(resp_body)
                        anthropic_data = _openai_to_anthropic(openai_data, model or "")
                        resp_body = json.dumps(anthropic_data).encode("utf-8")
                    except (json.JSONDecodeError, TypeError) as e:
                        logger.warning("Failed to translate response to Anthropic format: %s", e)

                out_headers = dict(resp.headers)
                out_headers.pop("content-encoding", None)
                out_headers.pop("transfer-encoding", None)
                out_headers["content-length"] = str(len(resp_body))
                return Response(
                    content=resp_body,
                    status_code=resp.status_code,
                    headers=out_headers,
                    media_type="application/json",
                )

            except httpx.ConnectError as e:
                if model:
                    self._rate_limiter.record_error(model)
                last_error = f"Connection failed: {e}"
                logger.warning(
                    "Zen upstream connection error (model=%s, attempt %d/%d): %s",
                    model or "unknown",
                    attempt + 1,
                    max_retries,
                    e,
                )
                if attempt < max_retries:
                    wait = min(2**attempt, 10)
                    await asyncio.sleep(wait)
                    continue
                return self._error_response(502, last_error)

            except httpx.TimeoutException:
                if model:
                    self._rate_limiter.record_error(model)
                last_error = "Request timed out"
                logger.warning(
                    "Zen upstream timeout (model=%s, attempt %d/%d)",
                    model or "unknown",
                    attempt + 1,
                    max_retries,
                )
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
                logger.warning(
                    "Zen upstream request error (model=%s, attempt %d/%d): %s",
                    model or "unknown",
                    attempt + 1,
                    max_retries,
                    e,
                )
                if attempt < max_retries:
                    wait = 3.0
                    if model:
                        delay = self._rate_limiter.get_stats(model).get("current_delay", 3.0)
                        wait = delay * (attempt + 1)
                    await asyncio.sleep(wait)
                    continue
                return self._error_response(502, last_error)

        return self._error_response(500, last_error or "Max retries exceeded")

    async def _handle_streaming_anthropic(self, upstream_url, headers, body, model, query_params):
        """Handle streaming requests with SSE translation and fallback chain.

        Uses httpx.stream() for true chunked streaming.
        On 429/exhaustion, tries next free model in the fallback chain.
        """
        import uuid as _uuid

        _RETRIABLE_PATTERNS = re.compile(
            r"rate.?limit|exhaust|too.?many|credits|slow.?down|quota", re.I
        )

        async def _try_model(try_model, try_body):
            """Attempt streaming with a specific model. Returns (success, error_text)."""
            # Patch the model in the body
            try:
                bd = json.loads(try_body)
                bd["model"] = try_model
                patched = json.dumps(bd).encode("utf-8")
            except (json.JSONDecodeError, TypeError):
                patched = try_body

            async with self._client.stream(
                "POST", upstream_url, headers=headers, content=patched, params=query_params
            ) as resp:
                if resp.status_code == 200:
                    return resp, None
                error_body = await resp.aread()
                error_text = error_body.decode("utf-8", errors="replace")[:500]
                return None, (resp.status_code, error_text)

        async def generate():
            msg_id = f"msg_{_uuid.uuid4().hex[:12]}"

            # Build fallback chain
            default = os.environ.get("ZEN_DEFAULT_MODEL", "qwen3.6-plus-free")
            chain = _get_fallback_chain(model if model in _ZEN_FREE_MODELS else default)
            active_model = model or default

            # Emit Anthropic message_start
            start_event = {
                "type": "message_start",
                "message": {
                    "id": msg_id,
                    "type": "message",
                    "role": "assistant",
                    "content": [],
                    "model": active_model,
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": 0, "output_tokens": 0},
                },
            }
            yield f"event: message_start\ndata: {json.dumps(start_event)}\n\n"

            block_start = {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            }
            yield f"event: content_block_start\ndata: {json.dumps(block_start)}\n\n"

            # Try each model in the fallback chain
            success = False
            for i, try_model in enumerate(chain):
                try:
                    async with self._client.stream(
                        "POST",
                        upstream_url,
                        headers=headers,
                        content=_swap_model(body, try_model),
                        params=query_params,
                    ) as resp:
                        if resp.status_code != 200:
                            error_body = await resp.aread()
                            error_text = error_body.decode("utf-8", errors="replace")[:500]
                            retriable = bool(_RETRIABLE_PATTERNS.search(error_text))

                            if retriable and i < len(chain) - 1:
                                logger.warning(
                                    "Model %s failed (%d), falling back to %s",
                                    try_model,
                                    resp.status_code,
                                    chain[i + 1],
                                )
                                if try_model:
                                    self._rate_limiter.record_rate_limit(try_model)
                                continue

                            # Non-retriable or last model — emit error
                            err_delta = {
                                "type": "content_block_delta",
                                "index": 0,
                                "delta": {
                                    "type": "text_delta",
                                    "text": f"[All models failed. Last: {try_model} ({resp.status_code}): {error_text[:200]}]",
                                },
                            }
                            yield f"event: content_block_delta\ndata: {json.dumps(err_delta)}\n\n"
                            break

                        # Success — stream content
                        if try_model:
                            self._rate_limiter.record_success(try_model)
                        if try_model != active_model:
                            logger.info("Fallback succeeded: %s -> %s", active_model, try_model)

                        async for line in resp.aiter_lines():
                            line = line.strip()
                            if not line or not line.startswith("data: "):
                                continue
                            data_str = line[6:]
                            if data_str == "[DONE]":
                                break
                            try:
                                sse_data = json.loads(data_str)
                                delta = sse_data.get("choices", [{}])[0].get("delta", {})
                                text = delta.get("content", "")
                                if text:
                                    delta_event = {
                                        "type": "content_block_delta",
                                        "index": 0,
                                        "delta": {"type": "text_delta", "text": text},
                                    }
                                    yield f"event: content_block_delta\ndata: {json.dumps(delta_event)}\n\n"
                            except (json.JSONDecodeError, IndexError, KeyError):
                                pass
                        success = True
                        break

                except Exception as e:
                    logger.warning("Stream error on %s: %s", try_model, e)
                    if i < len(chain) - 1:
                        continue
                    err_delta = {
                        "type": "content_block_delta",
                        "index": 0,
                        "delta": {"type": "text_delta", "text": f"[Stream error: {e}]"},
                    }
                    yield f"event: content_block_delta\ndata: {json.dumps(err_delta)}\n\n"

            # Emit Anthropic closing events
            yield 'event: content_block_stop\ndata: {"type": "content_block_stop", "index": 0}\n\n'
            delta_msg = {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                "usage": {"output_tokens": 0},
            }
            yield f"event: message_delta\ndata: {json.dumps(delta_msg)}\n\n"
            yield 'event: message_stop\ndata: {"type": "message_stop"}\n\n'

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"cache-control": "no-cache", "x-accel-buffering": "no"},
        )

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
