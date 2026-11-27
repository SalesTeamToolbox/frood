"""Claude Code gateway (/gw) — T1 passthrough to OpenCode Go models.

Terminal Claude Code talks native Anthropic Messages (streaming + tool use)
to ``POST /gw/v1/messages``; this module forwards the request body unchanged
(except ``model``, rewritten to the routed upstream id) to the OpenCode Go
endpoint ``<GATEWAY_GO_BASE_URL>/messages`` and relays the upstream response.

No format translation happens here (T1 is a pure passthrough). The legacy
text-only routes (``/v1/messages``, ``/llm/v1/*``) are untouched.

Security properties (see Mandate gw-t1):
- Fail closed: an empty/non-str token refuses every request with 503.
- Loopback only: served only when DASHBOARD_HOST is loopback, and only to
  loopback clients.
- No secrets are ever logged; httpx/httpcore DEBUG output is suppressed so
  request headers cannot leak through their loggers.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import sqlite3
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

logger = logging.getLogger("frood.gateway")

GATEWAY_VERSION = "0.4.0"

DEFAULT_GO_BASE_URL = "https://opencode.ai/zen/go/v1"
DEFAULT_GO_MODELS = (
    "deepseek-v4.1-flash,glm-5.3-flash,kimi-k3,minimax-m3,qwen3.8-flash,kimi-k2.7-code,glm-5.3"
)
DEFAULT_TIMEOUT_S = 600.0
CONNECT_TIMEOUT_S = 10.0

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})

_ANTHROPIC_VERSION_DEFAULT = "2023-06-01"

# Hosts the key reader consults; mirrors orchestrator/bin/go-usage.mjs.
_CREDENTIAL_SQL = (
    "SELECT value FROM credential WHERE integration_id = 'opencode-go' AND active = 1 LIMIT 1"
)

# Once-per-process record of hosts already warned about (critical log fires once).
_crit_logged_hosts: set[str] = set()

# Go-key cache keyed by resolved db path (env-provided keys are never cached).
_go_key_cache: dict[str, str] = {}


def _as_str(value: object, default: str = "") -> str:
    return value if isinstance(value, str) else default


def build_route_table(models_csv: str) -> dict[str, str]:
    """Parse the routed Go model list into {model_id: upstream_model_id}.

    In T1 every id maps to itself on Go (pure passthrough).
    """
    table: dict[str, str] = {}
    for part in (models_csv or "").split(","):
        model_id = part.strip()
        if model_id:
            table[model_id] = model_id
    return table


def parse_routed_models(models_csv: object, default: str = DEFAULT_GO_MODELS) -> list[str]:
    """Ordered routed model ids, falling back to the default when unusable."""
    if not isinstance(models_csv, str) or not models_csv.strip():
        models_csv = default
    seen: list[str] = []
    for part in models_csv.split(","):
        model_id = part.strip()
        if model_id and model_id not in seen:
            seen.append(model_id)
    return seen


def is_claude_model(model_id: str) -> bool:
    """True for claude-* ids, which must never be sent to OpenCode Go."""
    return isinstance(model_id, str) and model_id.lower().startswith("claude")


def filter_anthropic_beta(value: str | None) -> dict[str, str]:
    """Headers for the upstream anthropic-beta value (T1: passed through unchanged).

    T2/T3 may add a drop list here; callers must keep using this function.
    """
    if value is None:
        return {}
    return {"anthropic-beta": value}


def derive_session_id(body: dict, header_session_id: str | None) -> str:
    """Derive a stable opencode session id for one conversation.

    Precedence: ``x-claude-code-session-id`` header, then the part of
    ``metadata.user_id`` after the last ``session_``, else the sha256 of the
    JSON of the first message. Returned as ``ses_<alnum>`` (a value already
    starting with ``ses_`` is kept as-is).
    """
    raw: str | None = None
    if header_session_id:
        raw = header_session_id
    elif isinstance(body, dict):
        metadata = body.get("metadata")
        if isinstance(metadata, dict):
            user_id = metadata.get("user_id")
            if isinstance(user_id, str) and user_id:
                raw = user_id.split("session_")[-1] if "session_" in user_id else user_id
    if not raw:
        messages = body.get("messages") if isinstance(body, dict) else None
        first = messages[0] if isinstance(messages, list) and messages else body
        try:
            payload = json.dumps(first, sort_keys=True, separators=(",", ":"), default=str)
        except Exception:
            payload = str(first)
        raw = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]
    if raw.startswith("ses_"):
        return raw
    return "ses_" + re.sub(r"[^0-9A-Za-z]", "", raw)


def error_response(
    status: int, kind: str, message: str, headers: dict[str, str] | None = None
) -> JSONResponse:
    """Anthropic-shaped error body. Never raised — always returned directly."""
    return JSONResponse(
        status_code=status,
        content={"type": "error", "error": {"type": kind, "message": message}},
        headers=headers,
    )


def check_gateway_auth(request: Request, token: object) -> JSONResponse | None:
    """Validate the gateway token. Returns None when authorized, else a response."""
    configured = token if isinstance(token, str) else ""
    if not configured:
        return error_response(503, "api_error", "gateway disabled: FROOD_GATEWAY_TOKEN not set")
    bearer = request.headers.get("authorization", "")
    provided = bearer[7:].strip() if bearer.lower().startswith("bearer ") else ""
    if not provided:
        provided = request.headers.get("x-api-key", "")
    if not provided or not hmac.compare_digest(provided, configured):
        return error_response(401, "authentication_error", "gateway: invalid gateway token")
    return None


def resolve_opencode_db_path(explicit: str | Path | None = None) -> Path:
    """Db path for the Go credential row: explicit > OPENCODE_DB > XDG default."""
    if explicit is not None and str(explicit):
        return Path(str(explicit))
    override = os.environ.get("OPENCODE_DB", "")
    if override:
        return Path(override)
    xdg = os.environ.get("XDG_DATA_HOME", "") or str(Path.home() / ".local" / "share")
    return Path(xdg) / "opencode" / "opencode.db"


def read_go_key_sync(db_path: str | Path | None = None) -> str | None:
    """Return the OpenCode Go key, or None when unavailable.

    ``OPENCODE_GO_KEY`` wins; else a read-only sqlite read of the active
    ``opencode-go`` credential row. Any error gives None. Never raises, never
    logs key material. Successful db reads are cached per resolved db path.
    """
    from_env = os.environ.get("OPENCODE_GO_KEY", "")
    if from_env:
        return from_env
    resolved = str(resolve_opencode_db_path(db_path))
    cached = _go_key_cache.get(resolved)
    if cached:
        return cached
    try:
        conn = sqlite3.connect(f"file:{resolved}?mode=ro", uri=True, timeout=2.0)
    except Exception:
        return None
    try:
        try:
            conn.execute("PRAGMA busy_timeout=2000;")
        except Exception:
            pass
        try:
            row = conn.execute(_CREDENTIAL_SQL).fetchone()
        except Exception:
            return None
        if not row or not isinstance(row[0], str):
            return None
        try:
            parsed = json.loads(row[0])
        except Exception:
            return None
        key = parsed.get("key") if isinstance(parsed, dict) else None
        if not isinstance(key, str) or not key:
            return None
        _go_key_cache[resolved] = key
        return key
    finally:
        try:
            conn.close()
        except Exception:
            pass


async def read_go_key(db_path: str | Path | None = None) -> str | None:
    """Async wrapper: the (possibly blocking) sqlite read runs in a thread."""
    return await asyncio.to_thread(read_go_key_sync, db_path)


def _upstream_host(base_url: str) -> str:
    try:
        return urlparse(base_url).hostname or base_url
    except Exception:
        return "upstream"


def build_gateway_router(
    token: object = "",
    host: object = "127.0.0.1",
    go_base_url: object = DEFAULT_GO_BASE_URL,
    models: object = DEFAULT_GO_MODELS,
    transport: httpx.AsyncBaseTransport | None = None,
    timeout_s: object = DEFAULT_TIMEOUT_S,
    version: str = GATEWAY_VERSION,
    db_path: str | Path | None = None,
    test_client_host: str | None = "testclient",
) -> APIRouter:
    """Build the /gw router. All config is passed explicitly (never read from
    a possibly-mocked settings object at request time); non-str values fail
    closed to safe defaults, never to a 500.

    ``test_client_host`` names the synthetic TestClient host treated as
    loopback; pass None to enforce strict loopback (used by the 403 test).
    """

    base_url = _as_str(go_base_url, DEFAULT_GO_BASE_URL).rstrip("/") or DEFAULT_GO_BASE_URL
    routed_models = parse_routed_models(models if isinstance(models, str) else "")
    route_table = build_route_table(",".join(routed_models))
    try:
        read_timeout = float(timeout_s)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        read_timeout = DEFAULT_TIMEOUT_S

    # httpx/httpcore must not emit DEBUG records carrying request headers.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    state: dict[str, httpx.AsyncClient | None] = {"client": None}

    def _get_client() -> httpx.AsyncClient:
        client = state["client"]
        if client is None:
            client = httpx.AsyncClient(
                transport=transport,
                timeout=httpx.Timeout(
                    connect=CONNECT_TIMEOUT_S,
                    read=read_timeout,
                    write=60.0,
                    pool=10.0,
                ),
            )
            state["client"] = client
        return client

    async def _shutdown() -> None:
        client = state["client"]
        state["client"] = None
        if client is not None:
            try:
                await client.aclose()
            except Exception:
                pass

    router = APIRouter(prefix="/gw", on_shutdown=[_shutdown])

    def _preflight(request: Request) -> JSONResponse | None:
        """Service-level gates: config host, token presence, auth, client host."""
        configured_host = host if isinstance(host, str) else "127.0.0.1"
        if configured_host not in LOOPBACK_HOSTS:
            if configured_host not in _crit_logged_hosts:
                _crit_logged_hosts.add(configured_host)
                logger.critical(
                    "gateway refuses to serve: DASHBOARD_HOST is not loopback (host=%s)",
                    configured_host,
                )
            return error_response(
                503,
                "api_error",
                "gateway refuses to serve: DASHBOARD_HOST is not loopback",
            )
        denied = check_gateway_auth(request, token)
        if denied is not None:
            return denied
        client_host = request.client.host if request.client else ""
        allowed = set(LOOPBACK_HOSTS)
        if test_client_host:
            allowed = allowed | {test_client_host}
        if client_host not in allowed:
            return error_response(403, "permission_error", "gateway refuses non-loopback client")
        return None

    async def _read_go_key() -> str | None:
        return await read_go_key(db_path)

    def _upstream_headers(request: Request, go_key: str, session_id: str) -> dict[str, str]:
        headers: dict[str, str] = {
            "content-type": "application/json",
            "accept": request.headers.get("accept", "application/json"),
            "anthropic-version": request.headers.get(
                "anthropic-version", _ANTHROPIC_VERSION_DEFAULT
            ),
            "x-api-key": go_key,
            "user-agent": f"frood-gateway/{version}",
            "x-opencode-session": session_id,
        }
        headers.update(filter_anthropic_beta(request.headers.get("anthropic-beta")))
        return headers

    def _error_passthrough(status: int, raw: bytes, upstream_headers: httpx.Headers) -> Response:
        headers: dict[str, str] = {}
        if status == 429:
            headers["x-should-retry"] = "false"
            retry_after = upstream_headers.get("retry-after")
            if retry_after is not None:
                headers["retry-after"] = retry_after
        media_type = upstream_headers.get("content-type", "application/json").split(";")[0].strip()
        return Response(content=raw, status_code=status, media_type=media_type, headers=headers)

    def _upstream_failure(exc: Exception) -> JSONResponse:
        if isinstance(exc, httpx.ConnectError):
            return error_response(
                502, "api_error", f"gateway: upstream unreachable ({_upstream_host(base_url)})"
            )
        return error_response(
            504, "api_error", f"gateway: upstream timed out ({_upstream_host(base_url)})"
        )

    @router.post("/v1/messages")
    async def gateway_messages(request: Request):
        denied = _preflight(request)
        if denied is not None:
            return denied
        try:
            body = await request.json()
        except Exception:
            return error_response(400, "invalid_request_error", "gateway: invalid JSON body")
        if not isinstance(body, dict):
            return error_response(400, "invalid_request_error", "gateway: invalid JSON body")
        model_id = body.get("model", "")
        if not isinstance(model_id, str) or not model_id:
            return error_response(400, "invalid_request_error", "gateway: missing model")
        if is_claude_model(model_id):
            return error_response(
                403,
                "permission_error",
                "gateway: claude-* models are never sent to OpenCode Go",
            )
        upstream_model = route_table.get(model_id)
        if upstream_model is None:
            return error_response(
                404, "not_found_error", f"gateway: model '{model_id}' is not routed"
            )
        go_key = await _read_go_key()
        if not go_key:
            return error_response(503, "api_error", "gateway: no OpenCode Go key")
        out_body = dict(body)
        out_body["model"] = upstream_model
        session_id = derive_session_id(body, request.headers.get("x-claude-code-session-id"))
        url = base_url + "/messages"
        headers = _upstream_headers(request, go_key, session_id)
        stream = body.get("stream") is True
        client = _get_client()
        if stream:
            try:
                upstream = await client.send(
                    client.build_request("POST", url, headers=headers, json=out_body),
                    stream=True,
                )
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                return _upstream_failure(exc)
            except Exception:
                return error_response(
                    502,
                    "api_error",
                    f"gateway: upstream unreachable ({_upstream_host(base_url)})",
                )
            if upstream.status_code >= 400:
                try:
                    raw = await upstream.aread()
                finally:
                    await upstream.aclose()
                logger.warning(
                    "gateway upstream error status=%s host=%s",
                    upstream.status_code,
                    _upstream_host(base_url),
                )
                return _error_passthrough(upstream.status_code, raw, upstream.headers)

            async def _relay():
                try:
                    async for chunk in upstream.aiter_raw():
                        try:
                            if await request.is_disconnected():
                                break
                        except Exception:
                            break
                        yield chunk
                finally:
                    try:
                        await upstream.aclose()
                    except Exception:
                        pass

            content_type = upstream.headers.get("content-type", "text/event-stream")
            return StreamingResponse(
                _relay(),
                status_code=upstream.status_code,
                media_type=content_type.split(";")[0].strip(),
                headers={"cache-control": "no-cache", "x-accel-buffering": "no"},
            )
        try:
            upstream = await client.post(url, headers=headers, json=out_body)
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            return _upstream_failure(exc)
        except Exception:
            return error_response(
                502, "api_error", f"gateway: upstream unreachable ({_upstream_host(base_url)})"
            )
        if upstream.status_code >= 400:
            logger.warning(
                "gateway upstream error status=%s host=%s",
                upstream.status_code,
                _upstream_host(base_url),
            )
            return _error_passthrough(upstream.status_code, upstream.content, upstream.headers)
        content_type = upstream.headers.get("content-type", "application/json")
        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            media_type=content_type.split(";")[0].strip(),
        )

    @router.post("/v1/messages/count_tokens")
    async def gateway_count_tokens(request: Request):
        denied = _preflight(request)
        if denied is not None:
            return denied
        return error_response(404, "not_found_error", "gateway: count_tokens is not supported")

    @router.get("/v1/models")
    async def gateway_models(request: Request):
        denied = _preflight(request)
        if denied is not None:
            return denied
        data = [
            {
                "type": "model",
                "id": model_id,
                "display_name": model_id,
                "created_at": "1970-01-01T00:00:00Z",
            }
            for model_id in routed_models
        ]
        content: dict[str, object] = {
            "data": data,
            "has_more": False,
            "first_id": routed_models[0] if routed_models else None,
            "last_id": routed_models[-1] if routed_models else None,
        }
        return JSONResponse(status_code=200, content=content)

    return router
