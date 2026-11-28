"""tests/test_gateway.py — Frood gateway (/gw) passthrough tests (gw-t1).

Every test here must fail without the gateway change it covers. Tests never
touch the real opencode.ai endpoint or the real opencode.db: the upstream is
an httpx.MockTransport and the credential db is a temp sqlite file.
"""

import json
import logging
import sqlite3
from unittest.mock import MagicMock, patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.config import Settings
from dashboard import gateway as gw_module
from dashboard.gateway import DEFAULT_GO_MODELS, build_gateway_router, parse_routed_models
from dashboard.server import create_app

TOKEN = "test-gateway-token-abc123"
GO_KEY = "go-test-key-xyz-999"
DB_KEY = "go-key-from-sqlite-db"
MODELS = "deepseek-v4.1-flash,glm-5.3-flash"
BASE_URL = "https://opencode.ai/zen/go/v1"

AUTH_BEARER = {"Authorization": f"Bearer {TOKEN}"}
AUTH_KEY = {"x-api-key": TOKEN}

# Genuine client class, pinned at import: _client_for may run twice in one
# test while the name is still patched, so the factory must not resolve it
# through the (patched) module attribute.
_REAL_ASYNC_CLIENT = httpx.AsyncClient

SSE_CHUNKS = [
    b'event: message_start\ndata: {"type": "message_start", "message": {"id": "msg_1"}}\n\n',
    b'event: ping\ndata: {"type": "ping"}\n\n',
    b"event: content_block_start\n"
    b'data: {"type": "content_block_start", "index": 0, '
    b'"content_block": {"type": "tool_use", "id": "toolu_1", "name": "Edit"}}\n\n',
    b"event: content_block_delta\n"
    b'data: {"type": "content_block_delta", "index": 0, '
    b'"delta": {"type": "input_json_delta", "partial_json": "{\\"a\\":"}}}\n\n',
    b'event: content_block_stop\ndata: {"type": "content_block_stop", "index": 0}\n\n',
    b"event: message_delta\n"
    b'data: {"type": "message_delta", "delta": {"stop_reason": "tool_use"}, '
    b'"usage": {"output_tokens": 12}}\n\n',
    b'event: message_stop\ndata: {"type": "message_stop"}\n\n',
]


def _settings(**overrides) -> Settings:
    kw = {
        "frood_gateway_token": TOKEN,
        "gateway_go_base_url": BASE_URL,
        "gateway_go_models": MODELS,
    }
    kw.update(overrides)
    return Settings(**kw)


def _client_for(
    monkeypatch, settings_obj, handler, go_key=GO_KEY, db_path=None, test_client_host="testclient"
):
    """Build a real create_app TestClient whose upstream is a MockTransport.

    The synthetic TestClient host is allow-listed explicitly (production
    create_app enforces strict loopback); pass test_client_host=None to
    exercise the strict default.
    """
    monkeypatch.setattr("dashboard.server.settings", settings_obj)
    transport = httpx.MockTransport(handler)

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return _REAL_ASYNC_CLIENT(*args, **kwargs)

    monkeypatch.setattr("dashboard.gateway.httpx.AsyncClient", factory)
    if test_client_host is not None:
        original = gw_module.build_gateway_router
        monkeypatch.setattr(
            "dashboard.server.build_gateway_router",
            lambda **kw: original(test_client_host=test_client_host, **kw),
        )
    if go_key is None:
        monkeypatch.delenv("OPENCODE_GO_KEY", raising=False)
    else:
        monkeypatch.setenv("OPENCODE_GO_KEY", go_key)
    if db_path is None:
        monkeypatch.delenv("OPENCODE_DB", raising=False)
    else:
        monkeypatch.setenv("OPENCODE_DB", str(db_path))
    gw_module._go_key_cache.clear()
    gw_module._crit_logged_hosts.clear()
    return TestClient(create_app())


def _msg_body(model="deepseek-v4.1-flash", stream=False, **extra):
    body = {
        "model": model,
        "max_tokens": 64,
        "messages": [{"role": "user", "content": "hello"}],
    }
    if stream:
        body["stream"] = True
    body.update(extra)
    return body


def _streaming_handler(seen, chunks=SSE_CHUNKS):
    async def _achunks():
        for chunk in chunks:
            yield chunk

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_achunks(),
        )

    return handler


# -- bar 1: streaming passthrough -------------------------------------------


def test_streaming_passthrough_bytes_in_order(monkeypatch):
    """GW-01: SSE chunks arrive identical and in order through create_app."""
    seen: list = []
    client = _client_for(monkeypatch, _settings(), _streaming_handler(seen))
    resp = client.post("/gw/v1/messages", json=_msg_body(stream=True), headers=AUTH_BEARER)
    assert resp.status_code == 200
    assert resp.content == b"".join(SSE_CHUNKS)
    assert "text/event-stream" in resp.headers["content-type"]
    assert resp.headers["cache-control"] == "no-cache"
    assert resp.headers["x-accel-buffering"] == "no"


# -- bar 2: upstream request shape -------------------------------------------


def test_upstream_request_shape(monkeypatch):
    """GW-02: URL, headers and rewritten body seen by the mock upstream."""
    seen: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={"id": "msg_1", "type": "message", "usage": {"input_tokens": 3}},
        )

    client = _client_for(monkeypatch, _settings(), handler)
    body = _msg_body()
    resp = client.post(
        "/gw/v1/messages",
        json=body,
        headers={**AUTH_BEARER, "anthropic-beta": "beta-2024"},
    )
    assert resp.status_code == 200
    assert len(seen) == 1
    upstream = seen[0]
    assert str(upstream.url) == BASE_URL + "/messages"
    assert upstream.headers["x-api-key"] == GO_KEY
    assert "authorization" not in upstream.headers
    assert "cookie" not in upstream.headers
    assert upstream.headers["user-agent"].startswith("frood-gateway/")
    assert upstream.headers["x-opencode-session"].startswith("ses_")
    assert upstream.headers["anthropic-beta"] == "beta-2024"
    assert upstream.headers["anthropic-version"] == "2023-06-01"
    sent = json.loads(upstream.content.decode())
    assert sent["model"] == "deepseek-v4.1-flash"
    expected = dict(body)
    assert sent == expected


# -- bar 3: stable session ids -----------------------------------------------


def test_session_id_stable_per_conversation(monkeypatch):
    """GW-03: same header/user_id => same x-opencode-session, else different."""
    seen: list = []
    client = _client_for(monkeypatch, _settings(), _streaming_handler(seen))

    def post(extra_headers=None, extra_body=None):
        body = _msg_body(stream=True)
        if extra_body:
            body.update(extra_body)
        return client.post(
            "/gw/v1/messages", json=body, headers={**AUTH_BEARER, **(extra_headers or {})}
        )

    post({"x-claude-code-session-id": "sess-AAA"})
    post({"x-claude-code-session-id": "sess-AAA"})
    post({"x-claude-code-session-id": "sess-BBB"})
    sids = [r.headers["x-opencode-session"] for r in seen]
    assert sids[0] == sids[1]
    assert sids[0] != sids[2]

    seen.clear()
    uid = "claude_code_session_11112222-3333-4444-5555-666677778888"
    post(extra_body={"metadata": {"user_id": uid}})
    post(extra_body={"metadata": {"user_id": uid}})
    post(
        extra_body={
            "metadata": {"user_id": "claude_code_session_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"}
        }
    )
    sids = [r.headers["x-opencode-session"] for r in seen]
    assert sids[0] == sids[1]
    assert sids[0] != sids[2]


# -- bar 4: auth ---------------------------------------------------------------


def test_auth_missing_token_401(monkeypatch):
    """GW-04a: no credential => 401 Anthropic authentication_error."""
    seen: list = []
    client = _client_for(monkeypatch, _settings(), _streaming_handler(seen))
    resp = client.post("/gw/v1/messages", json=_msg_body())
    assert resp.status_code == 401
    assert resp.json()["error"]["type"] == "authentication_error"
    assert seen == []


def test_auth_wrong_token_401(monkeypatch):
    """GW-04b: wrong credential => 401, upstream never called."""
    seen: list = []
    client = _client_for(monkeypatch, _settings(), _streaming_handler(seen))
    resp = client.post(
        "/gw/v1/messages", json=_msg_body(), headers={"Authorization": "Bearer nope"}
    )
    assert resp.status_code == 401
    assert resp.json()["type"] == "error"
    assert seen == []


def test_auth_bearer_and_key_ok(monkeypatch):
    """GW-04c: Bearer and x-api-key both authorize."""
    seen: list = []
    client = _client_for(monkeypatch, _settings(), _streaming_handler(seen))
    assert client.post("/gw/v1/messages", json=_msg_body(), headers=AUTH_BEARER).status_code == 200
    assert client.post("/gw/v1/messages", json=_msg_body(), headers=AUTH_KEY).status_code == 200
    assert client.get("/gw/v1/models", headers=AUTH_KEY).status_code == 200
    assert len(seen) == 2


def test_auth_empty_configured_token_503(monkeypatch):
    """GW-04d: empty FROOD_GATEWAY_TOKEN => 503 for every route."""
    seen: list = []
    client = _client_for(monkeypatch, _settings(frood_gateway_token=""), _streaming_handler(seen))
    for resp in (
        client.post("/gw/v1/messages", json=_msg_body(), headers=AUTH_BEARER),
        client.get("/gw/v1/models", headers=AUTH_BEARER),
        client.post("/gw/v1/messages/count_tokens", headers=AUTH_BEARER),
    ):
        assert resp.status_code == 503
        assert "FROOD_GATEWAY_TOKEN" in resp.json()["error"]["message"]
    assert seen == []


# -- bar 5: loopback ----------------------------------------------------------


def test_non_loopback_host_503_and_critical(monkeypatch, caplog):
    """GW-05a: DASHBOARD_HOST=0.0.0.0 => 503 plus one critical log."""
    seen: list = []
    client = _client_for(
        monkeypatch,
        _settings(dashboard_host="0.0.0.0"),  # noqa: S104 — loopback-gate test target, never bound
        _streaming_handler(seen),
    )
    with caplog.at_level(logging.CRITICAL, logger="frood.gateway"):
        resp = client.post("/gw/v1/messages", json=_msg_body(), headers=AUTH_BEARER)
    assert resp.status_code == 503
    assert "not loopback" in resp.json()["error"]["message"]
    assert seen == []
    criticals = [r for r in caplog.records if r.levelno >= logging.CRITICAL]
    assert len(criticals) == 1
    assert "0.0.0.0" in criticals[0].getMessage()  # noqa: S104 — asserts the logged test value


def test_non_loopback_client_403(monkeypatch):
    """GW-05b: a non-loopback client host is refused with 403."""
    seen: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, headers={"content-type": "application/json"}, json={})

    monkeypatch.setenv("OPENCODE_GO_KEY", GO_KEY)
    monkeypatch.delenv("OPENCODE_DB", raising=False)
    gw_module._go_key_cache.clear()
    app = FastAPI()
    app.include_router(
        build_gateway_router(
            token=TOKEN,
            host="127.0.0.1",
            go_base_url=BASE_URL,
            models=MODELS,
            transport=httpx.MockTransport(handler),
            test_client_host=None,
        )
    )
    resp = TestClient(app).post("/gw/v1/messages", json=_msg_body(), headers=AUTH_BEARER)
    assert resp.status_code == 403
    assert seen == []


# -- bar 6: model routing -----------------------------------------------------


def test_claude_models_refused(monkeypatch):
    """GW-06a: claude-* ids => 403 and the upstream is never called."""
    seen: list = []
    client = _client_for(
        monkeypatch,
        _settings(gateway_go_models="claude-sonnet-4-6," + MODELS),
        _streaming_handler(seen),
    )
    for model in ("claude-sonnet-4-6", "CLAUDE-x", "Claude-Opus-4-1"):
        resp = client.post("/gw/v1/messages", json=_msg_body(model=model), headers=AUTH_BEARER)
        assert resp.status_code == 403, model
        assert resp.json()["error"]["type"] == "permission_error"
    assert seen == []


def test_unknown_model_404(monkeypatch):
    """GW-06b: unrouted id => 404 not_found_error, upstream never called."""
    seen: list = []
    client = _client_for(monkeypatch, _settings(), _streaming_handler(seen))
    resp = client.post("/gw/v1/messages", json=_msg_body(model="gpt-zzz"), headers=AUTH_BEARER)
    assert resp.status_code == 404
    assert resp.json()["error"]["type"] == "not_found_error"
    assert "gpt-zzz" in resp.json()["error"]["message"]
    assert seen == []


def test_count_tokens_404(monkeypatch):
    """GW-06c: count_tokens falls back to estimating (404 not_found_error)."""
    seen: list = []
    client = _client_for(monkeypatch, _settings(), _streaming_handler(seen))
    resp = client.post("/gw/v1/messages/count_tokens", json=_msg_body(), headers=AUTH_BEARER)
    assert resp.status_code == 404
    assert resp.json()["error"]["type"] == "not_found_error"
    assert seen == []


def _error_handler(seen, status, payload):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            status,
            headers={"content-type": "application/json"},
            content=json.dumps(payload).encode(),
        )

    return handler


# -- bar 7: upstream errors ----------------------------------------------------


def test_upstream_400_500_forwarded_unchanged(monkeypatch):
    """GW-07a: upstream 4xx/5xx status and body forwarded unchanged."""
    bodies = [
        (400, {"type": "error", "error": {"type": "invalid_request_error", "message": "bad"}}),
        (500, {"type": "error", "error": {"type": "api_error", "message": "boom"}}),
    ]
    for status, payload in bodies:
        seen: list = []
        client = _client_for(monkeypatch, _settings(), _error_handler(seen, status, payload))
        resp = client.post("/gw/v1/messages", json=_msg_body(), headers=AUTH_BEARER)
        assert resp.status_code == status
        assert resp.content == json.dumps(payload).encode()
        assert len(seen) == 1


def test_upstream_streaming_error_status(monkeypatch):
    """GW-07b: streaming request with error status returns the body as JSON."""
    payload = {"type": "error", "error": {"type": "invalid_request_error", "message": "nope"}}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400, headers={"content-type": "application/json"}, content=json.dumps(payload).encode()
        )

    client = _client_for(monkeypatch, _settings(), handler)
    resp = client.post("/gw/v1/messages", json=_msg_body(stream=True), headers=AUTH_BEARER)
    assert resp.status_code == 400
    assert resp.json() == payload


def test_upstream_429_headers(monkeypatch):
    """GW-07c: 429 adds x-should-retry:false and keeps retry-after."""
    payload = {"type": "error", "error": {"type": "rate_limit_error", "message": "slow"}}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            headers={"content-type": "application/json", "retry-after": "7"},
            content=json.dumps(payload).encode(),
        )

    client = _client_for(monkeypatch, _settings(), handler)
    resp = client.post("/gw/v1/messages", json=_msg_body(), headers=AUTH_BEARER)
    assert resp.status_code == 429
    assert resp.headers["x-should-retry"] == "false"
    assert resp.headers["retry-after"] == "7"
    assert resp.json() == payload


def test_upstream_connect_error_502(monkeypatch):
    """GW-07d: upstream connect error => 502 naming the host, no key."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    client = _client_for(monkeypatch, _settings(), handler)
    resp = client.post("/gw/v1/messages", json=_msg_body(), headers=AUTH_BEARER)
    assert resp.status_code == 502
    body_text = resp.text
    assert "opencode.ai" in body_text
    assert GO_KEY not in body_text
    assert TOKEN not in body_text
    assert resp.json()["error"]["type"] == "api_error"


def test_upstream_timeout_504(monkeypatch):
    """GW-07e: upstream timeout => 504 Anthropic api_error."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    client = _client_for(monkeypatch, _settings(), handler)
    resp = client.post("/gw/v1/messages", json=_msg_body(), headers=AUTH_BEARER)
    assert resp.status_code == 504
    assert resp.json()["error"]["type"] == "api_error"


# -- bar 8: non-streaming passthrough ------------------------------------------


def test_upstream_accept_encoding_identity(monkeypatch):
    """GW-16: upstream sees accept-encoding: identity (aiter_raw stays raw)."""
    seen: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, headers={"content-type": "application/json"}, json={})

    client = _client_for(monkeypatch, _settings(), handler)
    assert client.post("/gw/v1/messages", json=_msg_body(), headers=AUTH_BEARER).status_code == 200
    assert seen[0].headers["accept-encoding"] == "identity"


def test_non_ascii_credentials_401(monkeypatch):
    """GW-17: non-ASCII credential bytes => 401, never a 500."""
    seen: list = []
    client = _client_for(monkeypatch, _settings(), _streaming_handler(seen))
    for headers in (
        {b"authorization": b"Bearer \xff\xfe"},
        {b"x-api-key": b"\xff"},
    ):
        resp = client.post("/gw/v1/messages", json=_msg_body(), headers=headers)
        assert resp.status_code == 401
        assert resp.json()["error"]["type"] == "authentication_error"
    assert seen == []


def test_create_app_strict_loopback_by_default(monkeypatch):
    """GW-18: create_app without the test override refuses TestClient host."""
    seen: list = []
    client = _client_for(monkeypatch, _settings(), _streaming_handler(seen), test_client_host=None)
    resp = client.post("/gw/v1/messages", json=_msg_body(), headers=AUTH_BEARER)
    assert resp.status_code == 403
    assert seen == []


def test_empty_models_routes_nothing(monkeypatch, caplog):
    """GW-19: explicit empty GATEWAY_GO_MODELS => empty table + warning."""
    seen: list = []
    with caplog.at_level(logging.WARNING, logger="frood.gateway"):
        client = _client_for(monkeypatch, _settings(gateway_go_models=""), _streaming_handler(seen))
    assert any("no Go models routed" in r.getMessage() for r in caplog.records)
    resp = client.post("/gw/v1/messages", json=_msg_body(), headers=AUTH_BEARER)
    assert resp.status_code == 404
    models = client.get("/gw/v1/models", headers=AUTH_BEARER).json()
    assert models["data"] == []
    assert models["first_id"] is None
    assert models["last_id"] is None
    assert seen == []


def test_parse_routed_models_empty_vs_non_str():
    """GW-20: empty string routes nothing; non-str falls back to defaults."""
    assert parse_routed_models("") == []
    assert parse_routed_models("  , ,") == []
    assert parse_routed_models(" a ,,b,a ") == ["a", "b"]
    assert parse_routed_models(None) == DEFAULT_GO_MODELS.split(",")
    assert parse_routed_models(MagicMock()) == DEFAULT_GO_MODELS.split(",")


def test_non_streaming_json_passthrough(monkeypatch):
    """GW-08: non-streaming upstream JSON (incl. usage) returned unchanged."""
    seen: list = []
    payload = {
        "id": "msg_9",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": "hi"}],
        "model": "deepseek-v4.1-flash",
        "usage": {"input_tokens": 5, "output_tokens": 2},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, headers={"content-type": "application/json"}, json=payload)

    client = _client_for(monkeypatch, _settings(), handler)
    resp = client.post("/gw/v1/messages", json=_msg_body(), headers=AUTH_BEARER)
    assert resp.status_code == 200
    assert "application/json" in resp.headers["content-type"]
    assert resp.json() == payload


# -- bar 9: models list ---------------------------------------------------------


def test_models_list(monkeypatch):
    """GW-09: GET /gw/v1/models lists exactly the routed ids; auth required."""
    seen: list = []
    client = _client_for(monkeypatch, _settings(), _streaming_handler(seen))
    assert client.get("/gw/v1/models").status_code == 401
    resp = client.get("/gw/v1/models", headers=AUTH_BEARER)
    assert resp.status_code == 200
    data = resp.json()
    assert [m["id"] for m in data["data"]] == ["deepseek-v4.1-flash", "glm-5.3-flash"]
    assert all(m["type"] == "model" for m in data["data"])
    assert data["has_more"] is False
    assert data["first_id"] == "deepseek-v4.1-flash"
    assert data["last_id"] == "glm-5.3-flash"
    assert seen == []


# -- bar 10: Go key source -------------------------------------------------------


def _write_credential_db(path, key):
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE credential (integration_id TEXT, active INTEGER, value TEXT)")
        conn.execute(
            "INSERT INTO credential (integration_id, active, value) VALUES (?, ?, ?)",
            ("opencode-go", 1, json.dumps({"key": key})),
        )
        conn.commit()
    finally:
        conn.close()


def test_key_env_wins_over_db(monkeypatch, tmp_path):
    """GW-10a: OPENCODE_GO_KEY wins over the sqlite credential row."""
    seen: list = []
    db = tmp_path / "opencode.db"
    _write_credential_db(db, DB_KEY)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, headers={"content-type": "application/json"}, json={})

    client = _client_for(monkeypatch, _settings(), handler, go_key=GO_KEY, db_path=db)
    assert client.get("/gw/v1/models", headers=AUTH_BEARER).status_code == 200
    assert client.post("/gw/v1/messages", json=_msg_body(), headers=AUTH_BEARER).status_code == 200
    assert seen[0].headers["x-api-key"] == GO_KEY


def test_key_from_sqlite_db(monkeypatch, tmp_path):
    """GW-10b: credential row read (read-only) when no env key is set."""
    seen: list = []
    db = tmp_path / "opencode.db"
    _write_credential_db(db, DB_KEY)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, headers={"content-type": "application/json"}, json={})

    client = _client_for(monkeypatch, _settings(), handler, go_key=None, db_path=db)
    resp = client.post("/gw/v1/messages", json=_msg_body(), headers=AUTH_BEARER)
    assert resp.status_code == 200
    assert seen[0].headers["x-api-key"] == DB_KEY


def test_key_missing_503_without_key_text(monkeypatch, tmp_path):
    """GW-10c: missing db/row => 503 with no key material."""
    seen: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, headers={"content-type": "application/json"}, json={})

    client = _client_for(
        monkeypatch, _settings(), handler, go_key=None, db_path=tmp_path / "nope.db"
    )
    resp = client.post("/gw/v1/messages", json=_msg_body(), headers=AUTH_BEARER)
    assert resp.status_code == 503
    assert resp.json()["error"]["message"] == "gateway: no OpenCode Go key"
    assert seen == []


def test_key_cached_after_first_db_success(monkeypatch, tmp_path):
    """GW-10d: a successful db read is cached (db deletable afterwards)."""
    seen: list = []
    db = tmp_path / "opencode.db"
    _write_credential_db(db, DB_KEY)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, headers={"content-type": "application/json"}, json={})

    client = _client_for(monkeypatch, _settings(), handler, go_key=None, db_path=db)
    assert client.post("/gw/v1/messages", json=_msg_body(), headers=AUTH_BEARER).status_code == 200
    db.unlink()
    assert client.post("/gw/v1/messages", json=_msg_body(), headers=AUTH_BEARER).status_code == 200
    assert all(r.headers["x-api-key"] == DB_KEY for r in seen)


# -- bar 11: no secrets in logs --------------------------------------------------


def test_no_secrets_in_logs(monkeypatch, caplog):
    """GW-11: DEBUG logging of a streaming + 401-upstream run leaks nothing.

    GW-T3-b: the streaming leg carries real SSE chunks (not zero chunks).
    """

    def handler_401(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            headers={"content-type": "application/json"},
            content=json.dumps(
                {"type": "error", "error": {"type": "authentication_error", "message": "bad key"}}
            ).encode(),
        )

    client = _client_for(monkeypatch, _settings(), _streaming_handler([], SSE_CHUNKS))
    with caplog.at_level(logging.DEBUG):
        client.post("/gw/v1/messages", json=_msg_body(stream=True), headers=AUTH_BEARER)
        client2 = _client_for(monkeypatch, _settings(), handler_401)
        client2.post("/gw/v1/messages", json=_msg_body(), headers=AUTH_BEARER)
    for record in caplog.records:
        text = record.getMessage()
        try:
            args_text = str(record.args)
        except Exception:
            args_text = ""
        assert GO_KEY not in text and GO_KEY not in args_text
        assert TOKEN not in text and TOKEN not in args_text


# -- gw-t3 carry-overs ---------------------------------------------------------


def test_no_is_disconnected_in_relay():
    """GW-T3-a: the manual receive()/is_disconnected check is gone.

    A receive() failure must not end the stream as a silent success; the
    relay now ends only on upstream end (GW-01 streams real chunks through
    create_app and asserts identical bytes in order).
    """
    from pathlib import Path

    src = Path(gw_module.__file__).read_text(encoding="utf-8")
    assert "is_disconnected" not in src


def test_shared_client_closed_on_app_exit(monkeypatch):
    """GW-T3-b: exiting TestClient(app) closes the shared upstream client."""
    closed: list[bool] = []
    original_aclose = httpx.AsyncClient.aclose

    async def spy_aclose(self):
        closed.append(True)
        await original_aclose(self)

    monkeypatch.setattr(httpx.AsyncClient, "aclose", spy_aclose)
    client = _client_for(monkeypatch, _settings(), _streaming_handler([]))
    with client:
        resp = client.post("/gw/v1/messages", json=_msg_body(stream=True), headers=AUTH_BEARER)
        assert resp.status_code == 200
    assert closed, "router on_shutdown must close the shared httpx client"


def test_upstream_content_type_params_preserved(monkeypatch):
    """GW-T3-c: the upstream content-type passes through unchanged (parameters kept)."""
    payload = {"id": "msg_1", "type": "message"}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/json; charset=utf-8"},
            json=payload,
        )

    client = _client_for(monkeypatch, _settings(), handler)
    resp = client.post("/gw/v1/messages", json=_msg_body(), headers=AUTH_BEARER)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/json; charset=utf-8"


def test_streaming_content_type_params_preserved(monkeypatch):
    """GW-T3-c: streaming content-type parameters also pass through unchanged."""

    async def _achunks():
        for chunk in SSE_CHUNKS:
            yield chunk

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream; charset=utf-8"},
            content=_achunks(),
        )

    client = _client_for(monkeypatch, _settings(), handler)
    resp = client.post("/gw/v1/messages", json=_msg_body(stream=True), headers=AUTH_BEARER)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "text/event-stream; charset=utf-8"
    assert resp.content == b"".join(SSE_CHUNKS)


# -- bar 12: security headers ------------------------------------------------------


def test_security_headers_same_on_gw(monkeypatch):
    """GW-12: /gw responses carry the exact middleware header set."""
    client = _client_for(monkeypatch, _settings(), _streaming_handler([]))
    plain = client.get("/health")
    gw = client.get("/gw/v1/models", headers=AUTH_BEARER)
    names = [
        "X-Content-Type-Options",
        "X-Frame-Options",
        "X-XSS-Protection",
        "Referrer-Policy",
        "Content-Security-Policy",
        "Permissions-Policy",
    ]
    for name in names:
        assert gw.headers.get(name) == plain.headers.get(name), name
    assert plain.headers["X-Content-Type-Options"] == "nosniff"
    assert plain.headers["X-Frame-Options"] == "DENY"
    assert plain.headers["X-XSS-Protection"] == "1; mode=block"
    assert plain.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert "default-src 'self'" in plain.headers["Content-Security-Policy"]
    assert "camera=()" in plain.headers["Permissions-Policy"]


# -- bar 13: config ---------------------------------------------------------------


def test_config_gateway_fields_from_env(monkeypatch):
    """GW-13: the four gateway fields read from env; token never generated."""
    monkeypatch.delenv("FROOD_GATEWAY_TOKEN", raising=False)
    monkeypatch.setenv("GATEWAY_GO_BASE_URL", "https://example.invalid/go/v1")
    monkeypatch.setenv("GATEWAY_GO_MODELS", "a,b")
    monkeypatch.setenv("GATEWAY_UPSTREAM_TIMEOUT_S", "42")
    settings_obj = Settings.from_env()
    assert settings_obj.frood_gateway_token == ""
    assert settings_obj.gateway_go_base_url == "https://example.invalid/go/v1"
    assert settings_obj.gateway_go_models == "a,b"
    assert settings_obj.gateway_upstream_timeout_s == 42.0


def test_config_gateway_defaults():
    """GW-13b: defaults match the mandate (fail-closed token, Go base/models)."""
    settings_obj = Settings()
    assert settings_obj.frood_gateway_token == ""
    assert settings_obj.gateway_go_base_url == "https://opencode.ai/zen/go/v1"
    assert (
        settings_obj.gateway_go_models == "deepseek-v4.1-flash,glm-5.3-flash,kimi-k3,minimax-m3,"
        "qwen3.8-flash,kimi-k2.7-code,glm-5.3"
    )
    assert settings_obj.gateway_upstream_timeout_s == 600


# -- EGM: mocked-settings safety + input validation ----------------------------------


def test_mocked_dashboard_settings_gateway_fails_closed():
    """EGM: building create_app under patched (MagicMock) settings never 500s."""
    with patch("dashboard.server.settings") as mock_settings:
        mock_settings.get_cors_origins.return_value = []
        mock_settings.max_websocket_connections = 50
        app = create_app(MagicMock(), MagicMock())
        client = TestClient(app)
        assert client.get("/health").status_code == 200
        resp = client.post("/gw/v1/messages", json=_msg_body(), headers=AUTH_BEARER)
        assert resp.status_code == 503


def test_invalid_json_and_missing_model(monkeypatch):
    """Bad input => 400 invalid_request_error, upstream never called."""
    seen: list = []
    client = _client_for(monkeypatch, _settings(), _streaming_handler(seen))
    resp = client.post(
        "/gw/v1/messages",
        content=b"not json",
        headers={**AUTH_BEARER, "content-type": "application/json"},
    )
    assert resp.status_code == 400
    resp = client.post(
        "/gw/v1/messages",
        json={"messages": [{"role": "user", "content": "hi"}]},
        headers=AUTH_BEARER,
    )
    assert resp.status_code == 400
    assert seen == []
