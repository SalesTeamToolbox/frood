"""Claude Code gateway (/gw) — tier routing over OpenCode Go and Nvidia.

Terminal Claude Code talks native Anthropic Messages (streaming + tool use)
to ``POST /gw/v1/messages``. A Go-routed id is forwarded unchanged (except
``model``, rewritten to the routed upstream id) to the OpenCode Go endpoint
``<GATEWAY_GO_BASE_URL>/messages``; an Nvidia-routed id is translated to
OpenAI Chat Completions (``dashboard/gateway_translate.py``) and served from
``<GATEWAY_NVIDIA_BASE_URL>/chat/completions``. When the Go pace guard reads
``over`` — or a Go attempt fails before any response byte reaches the
client — the request falls back to its mapped Nvidia id.

Security properties (see Mandates gw-t1, gw-t3):
- Fail closed: an empty/non-str token refuses every request with 503.
- Loopback only: served only when DASHBOARD_HOST is loopback, and only to
  loopback clients.
- No secrets are ever logged; httpx/httpcore DEBUG output is suppressed so
  request headers cannot leak through their loggers. Nvidia gets its own
  header builder so no Go key or ``anthropic-*`` header can reach it.
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
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from dashboard.gateway_translate import (
    StreamTranslator,
    anthropic_to_openai,
    openai_error_to_anthropic,
    openai_to_anthropic,
)

logger = logging.getLogger("frood.gateway")

GATEWAY_VERSION = "0.4.0"

DEFAULT_GO_BASE_URL = "https://opencode.ai/zen/go/v1"
DEFAULT_GO_MODELS = (
    "deepseek-v4.1-flash,glm-5.3-flash,kimi-k3,minimax-m3,qwen3.8-flash,kimi-k2.7-code,glm-5.3"
)
DEFAULT_NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_NVIDIA_MODELS = "nvidia/nemotron-3.5-super-vl-120b-a12b,qwen/qwen3-coder-480b-a35b-instruct"
DEFAULT_GO_FALLBACK = (
    "kimi-k3=nvidia/nemotron-3.5-super-vl-120b-a12b,"
    "glm-5.3-flash=nvidia/nemotron-3.5-super-vl-120b-a12b,"
    "deepseek-v4.1-flash=qwen/qwen3-coder-480b-a35b-instruct"
)
DEFAULT_GO_PACE_MAX_PCT = 90.0
DEFAULT_GO_USAGE_PATH = "~/.config/orchestrator/go-usage.jsonl"
GO_STATE_CACHE_TTL_S = 60.0
GO_STATE_STALE_S = 6 * 3600.0
DEFAULT_TIMEOUT_S = 600.0
CONNECT_TIMEOUT_S = 10.0

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})

_ANTHROPIC_VERSION_DEFAULT = "2023-06-01"

# Hosts the key reader consults; mirrors orchestrator/bin/go-usage.mjs.
_CREDENTIAL_SQL = "SELECT value FROM credential WHERE integration_id = ? AND active = 1 LIMIT 1"

# Once-per-process record of hosts already warned about (critical log fires once).
_crit_logged_hosts: set[str] = set()

# Credential keys resolved from the opencode credential db, cached per
# (integration_id, resolved db path); env-provided keys are never cached.
_key_cache: dict[tuple[str, str], str] = {}

# Backward-compatible name: tests clear gw_module._go_key_cache between runs;
# it aliases _key_cache so a single clear() resets both readers.
_go_key_cache = _key_cache


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
    """Ordered routed model ids.

    An explicit empty string routes nothing (fail closed); only a non-str
    value (e.g. a mocked settings object) falls back to the default list.
    """
    if not isinstance(models_csv, str):
        models_csv = default
    seen: list[str] = []
    for part in models_csv.split(","):
        model_id = part.strip()
        if model_id and model_id not in seen:
            seen.append(model_id)
    return seen


def is_claude_model(model_id: str) -> bool:
    """True for claude-* ids, which must never be sent to any upstream.

    Refuses when any ``/``-separated segment starts with ``claude``
    (case-insensitive), so ``anthropic/claude-x`` and ``nvidia/Claude-y``
    are refused as well as bare ``claude-*`` ids.
    """
    if not isinstance(model_id, str):
        return False
    return any(seg.lower().startswith("claude") for seg in model_id.split("/"))


def parse_go_fallback(fallback_csv: object, default: str = DEFAULT_GO_FALLBACK) -> dict[str, str]:
    """Parse the Go -> Nvidia fallback map (``go_id=nvidia_id`` pairs).

    An explicitly empty string means no fallback. A non-str value (e.g. a
    mocked settings object) falls back to the default map.
    """
    if not isinstance(fallback_csv, str):
        fallback_csv = default
    mapping: dict[str, str] = {}
    for part in fallback_csv.split(","):
        go_id, sep, nvidia_id = part.partition("=")
        go_id = go_id.strip()
        nvidia_id = nvidia_id.strip()
        if sep and go_id and nvidia_id and go_id not in mapping:
            mapping[go_id] = nvidia_id
    return mapping


# Go pace-guard state cache: {(path, max_pct): (now, state)}. The read runs
# in asyncio.to_thread per request and is cached here for 60 s (on the
# injected clock), never re-read per request.
_go_state_cache: dict[tuple[str, float], tuple[float, str]] = {}


def _parse_epoch(value: object) -> float | None:
    """Epoch seconds from a snapshot timestamp (number, numeric string or ISO)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        seconds = float(value)
        return seconds / 1000.0 if seconds > 1e12 else seconds
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            seconds = float(text)
            return seconds / 1000.0 if seconds > 1e12 else seconds
        except ValueError:
            pass
        try:
            iso = text.replace("Z", "+00:00") if text.endswith("Z") else text
            moment = datetime.fromisoformat(iso)
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=UTC)
            return moment.timestamp()
        except ValueError:
            return None
    return None


def _read_last_snapshot(path_str: str) -> dict | None:
    """Last non-empty JSON line of the file as a dict, else None.

    Split out from read_go_state so tests can count file reads.
    """
    try:
        with open(path_str, encoding="utf-8") as handle:
            text = handle.read()
    except OSError:
        return None
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return None
    try:
        data = json.loads(lines[-1])
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _read_go_state_uncached(path_str: str, limit: float, now_s: float) -> str:
    """Evaluate one snapshot: "ok", "over" or "unknown"."""
    snapshot = _read_last_snapshot(os.path.expanduser(path_str))
    if snapshot is None:
        return "unknown"
    taken_at = _parse_epoch(snapshot.get("at"))
    if taken_at is None:
        return "unknown"
    if now_s - taken_at > GO_STATE_STALE_S:
        return "unknown"
    for window in ("rolling", "weekly", "monthly"):
        stats = snapshot.get(window)
        if not isinstance(stats, dict):
            continue
        pct = stats.get("pct")
        if isinstance(pct, bool) or not isinstance(pct, (int, float)):
            continue
        if float(pct) >= limit:
            return "over"
        if stats.get("status", "ok") != "ok":
            resets_at = _parse_epoch(stats.get("resets_at"))
            if resets_at is not None and resets_at > now_s:
                return "over"
    return "ok"


def read_go_state(
    path: object = DEFAULT_GO_USAGE_PATH,
    max_pct: object = DEFAULT_GO_PACE_MAX_PCT,
    now: object = None,
) -> str:
    """Go pace state from the go-usage.jsonl snapshot: "ok"|"over"|"unknown".

    Reads the last JSON line: "over" when a rolling/weekly/monthly ``pct``
    reaches ``max_pct``, or when a window has a non-"ok" status with a
    ``resets_at`` still in the future. "unknown" for a missing/unparsable
    file, a snapshot without a parseable ``at``, or a snapshot older than
    6 h (staleness uses the snapshot's ``at``, not the file mtime).
    "unknown" counts as allowed: Go itself refuses with 429 when it is
    really out, and the pre-stream fallback below handles that. A window
    with a missing or non-number ``pct`` is skipped. Cached for 60 s on
    the injected clock (``now``); ``now`` defaults to ``time.time()``.
    """
    path_str = _as_str(path, DEFAULT_GO_USAGE_PATH) or DEFAULT_GO_USAGE_PATH
    try:
        limit = float(max_pct)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        limit = DEFAULT_GO_PACE_MAX_PCT
    if isinstance(now, bool) or not isinstance(now, (int, float)):
        now_s = time.time()
    else:
        now_s = float(now)
    cache_key = (path_str, limit)
    cached = _go_state_cache.get(cache_key)
    if cached is not None and now_s - cached[0] < GO_STATE_CACHE_TTL_S:
        return cached[1]
    state = _read_go_state_uncached(path_str, limit, now_s)
    _go_state_cache[cache_key] = (now_s, state)
    return state


# A routing candidate: (provider, upstream_model), provider is "go"|"nvidia".
Candidate = tuple[str, str]


@dataclass(frozen=True)
class RouteTables:
    """The tables plan_route consults. Built once per router from settings."""

    go: dict[str, str] = field(default_factory=dict)
    nvidia: dict[str, str] = field(default_factory=dict)
    fallback: dict[str, str] = field(default_factory=dict)
    nvidia_key: str = ""


@dataclass(frozen=True)
class PlanError:
    """Terminal routing refusal: no candidate may be attempted."""

    status: int
    kind: str
    message: str
    headers: dict[str, str] = field(default_factory=dict)


def _nvidia_fallback_for(tables: RouteTables, model_id: str) -> Candidate | None:
    """The Nvidia candidate for a Go id, or None when there is none.

    An empty fallback map means no fallback is configured at all
    (``GATEWAY_GO_FALLBACK=`` opts out); the first-Nvidia-id default applies
    only when a map is configured but has no entry for this id.
    """
    if not tables.nvidia_key:
        return None
    fallback = tables.fallback if isinstance(tables.fallback, dict) else {}
    if not fallback:
        return None
    upstream = fallback.get(model_id)
    if upstream is None and tables.nvidia:
        upstream = next(iter(tables.nvidia.values()))
    if upstream is None:
        return None
    return ("nvidia", upstream)


def plan_route(
    model_id: str, tables: RouteTables, go_state: str
) -> tuple[list[Candidate], PlanError | None]:
    """Route one model id to ordered upstream candidates.

    Pure: no I/O. ``claude*`` is refused (403) before anything else, for
    every provider. A Go-routed id gives ``[go, (nvidia fallback)]``; when
    ``go_state == "over"`` the Go candidate is dropped so Nvidia goes first,
    and when that leaves no candidate the plan is a 429. An Nvidia-routed
    id gives ``[nvidia]`` (503 with an empty Nvidia key). Unknown ids give
    404. When an id is in both tables, Go wins.
    """
    if is_claude_model(model_id):
        return (
            [],
            PlanError(
                403,
                "permission_error",
                "gateway: claude-* models are never sent to OpenCode Go",
            ),
        )
    go_table = tables.go if isinstance(tables.go, dict) else {}
    nvidia_table = tables.nvidia if isinstance(tables.nvidia, dict) else {}
    # A non-str key counts as empty (e.g. a mocked settings object); same for
    # a non-dict fallback map.
    key = tables.nvidia_key if isinstance(tables.nvidia_key, str) else ""
    fallback_map = tables.fallback if isinstance(tables.fallback, dict) else {}
    keyed = RouteTables(go=go_table, nvidia=nvidia_table, fallback=fallback_map, nvidia_key=key)
    if model_id in go_table:
        if go_state == "over":
            fallback = _nvidia_fallback_for(keyed, model_id)
            if fallback is not None:
                return ([fallback], None)
            return (
                [],
                PlanError(
                    429,
                    "rate_limit_error",
                    "gateway: OpenCode Go allowance is nearly spent "
                    "and no Nvidia fallback is configured",
                    {"x-should-retry": "false"},
                ),
            )
        candidates: list[Candidate] = [("go", go_table[model_id])]
        fallback = _nvidia_fallback_for(keyed, model_id)
        if fallback is not None:
            candidates.append(fallback)
        return (candidates, None)
    if model_id in nvidia_table:
        if not key:
            return (
                [],
                PlanError(503, "api_error", "gateway: no NVIDIA_API_KEY"),
            )
        return ([("nvidia", nvidia_table[model_id])], None)
    return (
        [],
        PlanError(404, "not_found_error", f"gateway: model '{model_id}' is not routed"),
    )


def build_route_view(tables: RouteTables) -> dict[str, list[str]]:
    """Static route table for GET /gw/v1/routes: no secrets, no go_state."""
    keyed = RouteTables(
        go=tables.go if isinstance(tables.go, dict) else {},
        nvidia=tables.nvidia if isinstance(tables.nvidia, dict) else {},
        fallback=tables.fallback if isinstance(tables.fallback, dict) else {},
        nvidia_key=tables.nvidia_key if isinstance(tables.nvidia_key, str) else "",
    )
    view: dict[str, list[str]] = {}
    for model_id, upstream in keyed.go.items():
        entry = [f"go:{upstream}"]
        fallback = _nvidia_fallback_for(keyed, model_id)
        if fallback is not None:
            entry.append(f"{fallback[0]}:{fallback[1]}")
        view[model_id] = entry
    if keyed.nvidia_key:
        for model_id, upstream in keyed.nvidia.items():
            if model_id not in view:  # Go wins when an id is in both tables.
                view[model_id] = [f"nvidia:{upstream}"]
    return view


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
    if not provided or not hmac.compare_digest(
        provided.encode("utf-8", "surrogateescape"), configured.encode("utf-8")
    ):
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


def read_opencode_key_sync(integration_id: str, db_path: str | Path | None = None) -> str | None:
    """Read-only sqlite read of the active credential row for ``integration_id``.

    Returns ``json.loads(value)["key"]`` or None on any error (missing db,
    missing row, bad JSON, non-str or empty key). Successful reads are cached
    per (integration_id, resolved db path). Never raises and never logs key
    material; env vars are read by the caller's wrapper.
    """
    resolved = str(resolve_opencode_db_path(db_path))
    cache_key = (integration_id, resolved)
    cached = _key_cache.get(cache_key)
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
            row = conn.execute(_CREDENTIAL_SQL, (integration_id,)).fetchone()
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
        _key_cache[cache_key] = key
        return key
    finally:
        try:
            conn.close()
        except Exception:
            pass


def read_go_key_sync(db_path: str | Path | None = None) -> str | None:
    """Return the OpenCode Go key, or None when unavailable.

    ``OPENCODE_GO_KEY`` wins; else a read-only sqlite read of the active
    ``opencode-go`` credential row. Any error gives None. Never raises, never
    logs key material. Successful db reads are cached per resolved db path.
    """
    from_env = os.environ.get("OPENCODE_GO_KEY", "")
    if from_env:
        return from_env
    return read_opencode_key_sync("opencode-go", db_path)


def read_nvidia_key_sync(db_path: str | Path | None = None) -> str | None:
    """Return the Nvidia key, or None when unavailable.

    ``NVIDIA_API_KEY`` wins; else a read-only sqlite read of the active
    ``nvidia`` credential row
    (``integration_id = 'nvidia' AND active = 1``,
    ``json.loads(value)["key"]``). Any error gives None. Never raises, never
    logs key material. Successful db reads are cached per resolved db path.
    """
    from_env = os.environ.get("NVIDIA_API_KEY", "")
    if from_env:
        return from_env
    return read_opencode_key_sync("nvidia", db_path)


async def read_go_key(db_path: str | Path | None = None) -> str | None:
    """Async wrapper: the (possibly blocking) sqlite read runs in a thread."""
    return await asyncio.to_thread(read_go_key_sync, db_path)


async def read_nvidia_key(db_path: str | Path | None = None) -> str | None:
    """Async wrapper: the (possibly blocking) sqlite read runs in a thread."""
    return await asyncio.to_thread(read_nvidia_key_sync, db_path)


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
    test_client_host: str | None = None,
    nvidia_base_url: object = DEFAULT_NVIDIA_BASE_URL,
    nvidia_models: object = DEFAULT_NVIDIA_MODELS,
    go_fallback: object = DEFAULT_GO_FALLBACK,
    go_pace_max_pct: object = DEFAULT_GO_PACE_MAX_PCT,
    go_usage_path: object = DEFAULT_GO_USAGE_PATH,
    nvidia_key: object = "",
) -> APIRouter:
    """Build the /gw router. All config is passed explicitly (never read from
    a possibly-mocked settings object at request time); non-str values fail
    closed to safe defaults, never to a 500.

    ``test_client_host`` names an extra host treated as loopback (the
    synthetic Starlette TestClient host); it defaults to None so production
    enforces strict loopback — tests pass it explicitly.
    """

    base_url = _as_str(go_base_url, DEFAULT_GO_BASE_URL).rstrip("/") or DEFAULT_GO_BASE_URL
    routed_models = parse_routed_models(models)
    if not routed_models:
        logger.warning(
            "gateway: no Go models routed (GATEWAY_GO_MODELS is empty); every model will 404"
        )
    route_table = build_route_table(",".join(routed_models))
    nvidia_base = (
        _as_str(nvidia_base_url, DEFAULT_NVIDIA_BASE_URL).rstrip("/") or DEFAULT_NVIDIA_BASE_URL
    )
    nvidia_routed = parse_routed_models(nvidia_models, default=DEFAULT_NVIDIA_MODELS)
    if not nvidia_routed:
        logger.warning("gateway: no Nvidia models routed (GATEWAY_NVIDIA_MODELS is empty)")
    nvidia_table = build_route_table(",".join(nvidia_routed))
    fallback_map = parse_go_fallback(go_fallback)
    try:
        pace_max = float(go_pace_max_pct)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        pace_max = DEFAULT_GO_PACE_MAX_PCT
    usage_path = _as_str(go_usage_path, DEFAULT_GO_USAGE_PATH) or DEFAULT_GO_USAGE_PATH
    # A non-str key counts as empty: no Nvidia routes, never a 500.
    nvidia_key_str = nvidia_key if isinstance(nvidia_key, str) else ""
    tables = RouteTables(
        go=route_table,
        nvidia=nvidia_table,
        fallback=fallback_map,
        nvidia_key=nvidia_key_str,
    )
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
            # Identity only: the relay forwards aiter_raw() bytes verbatim and
            # never forwards content-encoding, so the upstream must not compress.
            "accept-encoding": "identity",
            "anthropic-version": request.headers.get(
                "anthropic-version", _ANTHROPIC_VERSION_DEFAULT
            ),
            "x-api-key": go_key,
            "user-agent": f"frood-gateway/{version}",
            "x-opencode-session": session_id,
        }
        headers.update(filter_anthropic_beta(request.headers.get("anthropic-beta")))
        return headers

    def _nvidia_headers(nvidia_key: str) -> dict[str, str]:
        """Headers for the Nvidia OpenAI-compatible endpoint.

        Separate from _upstream_headers on purpose: no Go key, no
        ``anthropic-*`` headers and no session header may ever reach Nvidia.
        """
        return {
            "content-type": "application/json",
            "accept": "application/json",
            "accept-encoding": "identity",
            "authorization": f"Bearer {nvidia_key}",
            "user-agent": f"frood-gateway/{version}",
        }

    def _error_passthrough(status: int, raw: bytes, upstream_headers: httpx.Headers) -> Response:
        headers: dict[str, str] = {}
        if status == 429:
            headers["x-should-retry"] = "false"
            retry_after = upstream_headers.get("retry-after")
            if retry_after is not None:
                headers["retry-after"] = retry_after
        # The upstream content-type passes through unchanged (parameters kept),
        # set as an explicit header so Starlette keeps it verbatim.
        headers["content-type"] = upstream_headers.get("content-type", "application/json")
        return Response(content=raw, status_code=status, headers=headers)

    def _upstream_failure(exc: Exception, host: str | None = None) -> JSONResponse:
        host = host or _upstream_host(base_url)
        if isinstance(exc, httpx.ConnectError):
            return error_response(502, "api_error", f"gateway: upstream unreachable ({host})")
        return error_response(504, "api_error", f"gateway: upstream timed out ({host})")

    def _nvidia_error(status: int, raw: bytes, upstream_headers: httpx.Headers) -> JSONResponse:
        """Map an Nvidia OpenAI-style error body with its status code."""
        content = openai_error_to_anthropic(status, raw)
        headers: dict[str, str] = {}
        if status == 429:
            headers["x-should-retry"] = "false"
            retry_after = upstream_headers.get("retry-after")
            if retry_after is not None:
                headers["retry-after"] = retry_after
        return JSONResponse(status_code=status, content=content, headers=headers)

    def _go_retry_status(status: int) -> bool:
        """Pre-stream Go statuses worth falling back on: 429, 402 or 5xx."""
        return status == 429 or status == 402 or 500 <= status <= 599

    def _with_route(response: Response, provider: str, upstream_model: str) -> Response:
        """Stamp every served response with its route. Never raises."""
        response.headers["x-frood-route"] = f"{provider}:{upstream_model}"
        return response

    async def _attempt_go(
        candidate_upstream: str,
        out_body: dict,
        headers: dict[str, str],
        url: str,
        stream: bool,
        client: httpx.AsyncClient,
    ) -> tuple[str, object, object]:
        """Try the Go candidate once.

        Returns ``("response", starlette_response, None)`` to send, or
        ``("fallback", label, terminal_response)``: the caller logs one INFO
        line and tries the next candidate, or sends ``terminal_response``
        (today's error, unchanged) when none remains.
        """
        if stream:
            try:
                upstream = await client.send(
                    client.build_request("POST", url, headers=headers, json=out_body),
                    stream=True,
                )
            except httpx.TransportError as exc:
                return ("fallback", type(exc).__name__, _upstream_failure(exc))
            except Exception as exc:
                return (
                    "fallback",
                    type(exc).__name__,
                    error_response(
                        502,
                        "api_error",
                        f"gateway: upstream unreachable ({_upstream_host(base_url)})",
                    ),
                )
            if upstream.status_code >= 400:
                status = upstream.status_code
                upstream_headers = upstream.headers
                try:
                    raw = await upstream.aread()
                except Exception:
                    try:
                        await upstream.aclose()
                    except Exception:
                        pass
                    return (
                        "fallback",
                        "read-error",
                        error_response(
                            502,
                            "api_error",
                            f"gateway: upstream error body unreadable ({_upstream_host(base_url)})",
                        ),
                    )
                try:
                    await upstream.aclose()
                except Exception:
                    pass
                terminal = _error_passthrough(status, raw, upstream_headers)
                if _go_retry_status(status):
                    return ("fallback", str(status), terminal)
                logger.warning(
                    "gateway upstream error status=%s host=%s",
                    status,
                    _upstream_host(base_url),
                )
                return ("response", terminal, None)

            async def _relay():
                try:
                    async for chunk in upstream.aiter_raw():
                        yield chunk
                finally:
                    try:
                        await upstream.aclose()
                    except Exception:
                        pass

            content_type = upstream.headers.get("content-type", "text/event-stream")
            return (
                "response",
                StreamingResponse(
                    _relay(),
                    status_code=upstream.status_code,
                    headers={
                        "content-type": content_type,
                        "cache-control": "no-cache",
                        "x-accel-buffering": "no",
                    },
                ),
                None,
            )
        try:
            upstream = await client.post(url, headers=headers, json=out_body)
        except httpx.TransportError as exc:
            return ("fallback", type(exc).__name__, _upstream_failure(exc))
        except Exception as exc:
            return (
                "fallback",
                type(exc).__name__,
                error_response(
                    502,
                    "api_error",
                    f"gateway: upstream unreachable ({_upstream_host(base_url)})",
                ),
            )
        if upstream.status_code >= 400:
            terminal = _error_passthrough(upstream.status_code, upstream.content, upstream.headers)
            if _go_retry_status(upstream.status_code):
                return ("fallback", str(upstream.status_code), terminal)
            logger.warning(
                "gateway upstream error status=%s host=%s",
                upstream.status_code,
                _upstream_host(base_url),
            )
            return ("response", terminal, None)
        content_type = upstream.headers.get("content-type", "application/json")
        return (
            "response",
            Response(
                content=upstream.content,
                status_code=upstream.status_code,
                headers={"content-type": content_type},
            ),
            None,
        )

    async def _attempt_nvidia(
        requested_model: str,
        candidate_upstream: str,
        body: dict,
        stream: bool,
        client: httpx.AsyncClient,
        nvidia_key: str,
    ) -> tuple[str, object, object]:
        """Try the Nvidia candidate once (same contract as _attempt_go)."""
        openai_body, warnings = anthropic_to_openai(body, candidate_upstream)
        logger.debug("gateway nvidia translation warnings=%d", len(warnings))
        headers = _nvidia_headers(nvidia_key)
        url = nvidia_base + "/chat/completions"
        host = _upstream_host(nvidia_base)
        if stream:
            try:
                upstream = await client.send(
                    client.build_request("POST", url, headers=headers, json=openai_body),
                    stream=True,
                )
            except httpx.TransportError as exc:
                return ("fallback", type(exc).__name__, _upstream_failure(exc, host))
            except Exception as exc:
                return (
                    "fallback",
                    type(exc).__name__,
                    error_response(502, "api_error", f"gateway: upstream unreachable ({host})"),
                )
            if upstream.status_code >= 400:
                status = upstream.status_code
                upstream_headers = upstream.headers
                try:
                    raw = await upstream.aread()
                except Exception:
                    try:
                        await upstream.aclose()
                    except Exception:
                        pass
                    return (
                        "fallback",
                        "read-error",
                        error_response(
                            502,
                            "api_error",
                            f"gateway: upstream error body unreadable ({host})",
                        ),
                    )
                try:
                    await upstream.aclose()
                except Exception:
                    pass
                terminal = _nvidia_error(status, raw, upstream_headers)
                if _go_retry_status(status):
                    return ("fallback", str(status), terminal)
                return ("response", terminal, None)
            translator = StreamTranslator(requested_model)

            async def _nvidia_relay():
                try:
                    async for chunk in upstream.aiter_bytes():
                        out = translator.feed(chunk)
                        if out:
                            yield out
                except Exception:
                    tail = translator.error("gateway: nvidia stream interrupted")
                    if tail:
                        yield tail
                else:
                    tail = translator.finish()
                    if tail:
                        yield tail
                finally:
                    try:
                        await upstream.aclose()
                    except Exception:
                        pass

            return (
                "response",
                StreamingResponse(
                    _nvidia_relay(),
                    status_code=200,
                    headers={
                        "content-type": "text/event-stream",
                        "cache-control": "no-cache",
                        "x-accel-buffering": "no",
                    },
                ),
                None,
            )
        try:
            upstream = await client.post(url, headers=headers, json=openai_body)
        except httpx.TransportError as exc:
            return ("fallback", type(exc).__name__, _upstream_failure(exc, host))
        except Exception as exc:
            return (
                "fallback",
                type(exc).__name__,
                error_response(502, "api_error", f"gateway: upstream unreachable ({host})"),
            )
        if upstream.status_code >= 400:
            terminal = _nvidia_error(upstream.status_code, upstream.content, upstream.headers)
            if _go_retry_status(upstream.status_code):
                return ("fallback", str(upstream.status_code), terminal)
            return ("response", terminal, None)
        try:
            data = upstream.json()
        except Exception:
            return (
                "response",
                error_response(502, "api_error", f"gateway: invalid Nvidia response ({host})"),
                None,
            )
        if isinstance(data, dict) and "error" in data:
            mapped = openai_error_to_anthropic(502, upstream.content)
            return ("response", JSONResponse(status_code=502, content=mapped), None)
        return (
            "response",
            JSONResponse(status_code=200, content=openai_to_anthropic(data, requested_model)),
            None,
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
        go_state = await asyncio.to_thread(read_go_state, usage_path, pace_max, time.time())
        # Resolve the Nvidia key lazily at request time, once, then cached:
        # configured value (build-time) > env NVIDIA_API_KEY > credential db
        # row ``integration_id = 'nvidia' AND active = 1``. Never logged.
        nvidia_configured = tables.nvidia_key if isinstance(tables.nvidia_key, str) else ""
        effective_nvidia_key = nvidia_configured or await read_nvidia_key(db_path)
        keyed = RouteTables(
            go=tables.go,
            nvidia=tables.nvidia,
            fallback=tables.fallback,
            nvidia_key=effective_nvidia_key or "",
        )
        candidates, plan_error = plan_route(model_id, keyed, go_state)
        if plan_error is not None:
            # Pre-route refusals name no provider or upstream.
            headers = dict(plan_error.headers or {})
            headers["x-frood-route"] = "none"
            return error_response(
                plan_error.status,
                plan_error.kind,
                plan_error.message,
                headers=headers,
            )
        go_key: str | None = None
        if any(provider == "go" for provider, _ in candidates):
            go_key = await _read_go_key()
            if not go_key:
                # Missing Go key drops the Go candidate; Nvidia serves when
                # one is mapped, else today's 503 (GW-10c pins the message).
                candidates = [
                    (provider, upstream) for provider, upstream in candidates if provider != "go"
                ]
                if not candidates:
                    return error_response(503, "api_error", "gateway: no OpenCode Go key")
        stream = body.get("stream") is True
        session_id = derive_session_id(body, request.headers.get("x-claude-code-session-id"))
        client = _get_client()
        pending = list(candidates)
        nvidia_key = effective_nvidia_key or ""
        while pending:
            provider, candidate_upstream = pending.pop(0)
            if provider == "go":
                if go_key is None:
                    # Defensive: never assert here; drop a keyless Go candidate
                    # and try the next (or refuse when none remains).
                    if pending:
                        logger.info("gateway fallback provider=go status=missing-key")
                        continue
                    return error_response(503, "api_error", "gateway: no OpenCode Go key")
                out_body = dict(body)
                out_body["model"] = candidate_upstream
                kind, first, second = await _attempt_go(
                    candidate_upstream,
                    out_body,
                    _upstream_headers(request, go_key, session_id),
                    base_url + "/messages",
                    stream,
                    client,
                )
            else:
                kind, first, second = await _attempt_nvidia(
                    model_id, candidate_upstream, body, stream, client, nvidia_key
                )
            if kind == "response":
                return _with_route(first, provider, candidate_upstream)  # type: ignore[return-value]
            if pending:
                logger.info("gateway fallback provider=%s status=%s", provider, first)
                continue
            return _with_route(second, provider, candidate_upstream)  # type: ignore[return-value]
        return error_response(503, "api_error", "gateway: no route available")

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
        listed = list(routed_models)
        effective = tables.nvidia_key if isinstance(tables.nvidia_key, str) else ""
        if not effective:
            effective = await read_nvidia_key(db_path) or ""
        if effective:
            listed.extend(nvidia_id for nvidia_id in nvidia_routed if nvidia_id not in listed)
        data = [
            {
                "type": "model",
                "id": model_id,
                "display_name": model_id,
                "created_at": "1970-01-01T00:00:00Z",
            }
            for model_id in listed
        ]
        content: dict[str, object] = {
            "data": data,
            "has_more": False,
            "first_id": listed[0] if listed else None,
            "last_id": listed[-1] if listed else None,
        }
        return JSONResponse(status_code=200, content=content)

    @router.get("/v1/routes")
    async def gateway_routes(request: Request):
        denied = _preflight(request)
        if denied is not None:
            return denied
        go_state = await asyncio.to_thread(read_go_state, usage_path, pace_max, time.time())
        effective = tables.nvidia_key if isinstance(tables.nvidia_key, str) else ""
        if not effective:
            effective = await read_nvidia_key(db_path) or ""
        keyed = RouteTables(
            go=tables.go,
            nvidia=tables.nvidia,
            fallback=tables.fallback,
            nvidia_key=effective,
        )
        # The table only: no keys, no tokens, no other secrets.
        return JSONResponse(
            status_code=200,
            content={"go_state": go_state, "routes": build_route_view(keyed)},
        )

    return router
