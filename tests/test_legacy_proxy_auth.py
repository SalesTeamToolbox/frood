"""tests/test_legacy_proxy_auth.py — gateway token on legacy Anthropic-style routes.

Module T5 of plan-desktop-3p-gateway: POST /v1/messages, POST /llm/v1/messages
and GET /llm/models + /llm/v1/models require FROOD_GATEWAY_TOKEN via
dashboard.gateway.check_gateway_auth (bearer or x-api-key; empty token => 503
fail closed). The provider call is faked at httpx.AsyncClient so no network is
used, and the tests assert it is never reached on 401/503.
"""

import json
import logging

import httpx
import pytest
from fastapi.testclient import TestClient

from core.config import Settings
from dashboard.server import create_app

TOKEN = "test-legacy-gateway-token-xyz"
AUTH_BEARER = {"Authorization": f"Bearer {TOKEN}"}
AUTH_KEY = {"x-api-key": TOKEN}
WRONG_BEARER = {"Authorization": "Bearer wrong-token-value"}
WRONG_KEY = {"x-api-key": "wrong-token-value"}
FAKE_UPSTREAM_KEY = "fake-anthropic-key"

MODEL = "claude-sonnet-4-6-20260217"

_PROVIDER_KEYS = (
    "ANTHROPIC_API_KEY",
    "OPENROUTER_API_KEY",
    "NVIDIA_API_KEY",
    "ZEN_API_KEY",
    "OPENAI_API_KEY",
)

MESSAGE_ROUTES = ["/llm/v1/messages", "/v1/messages"]
MODEL_ROUTES = ["/llm/models", "/llm/v1/models"]
ALL_ROUTES = MESSAGE_ROUTES + MODEL_ROUTES


def _msg_body():
    return {
        "model": MODEL,
        "max_tokens": 64,
        "messages": [{"role": "user", "content": "hello"}],
    }


class _FakeAnthropicResp:
    """Minimal stand-in for the httpx response _chat_complete parses."""

    status_code = 200

    def __init__(self, calls, url):
        calls.append(url)
        self.text = json.dumps({"content": [{"type": "text", "text": "hello from provider"}]})

    def json(self):
        return json.loads(self.text)


class _FakeAsyncClient:
    """Records upstream POST urls; never touches the network."""

    def __init__(self, calls, *args, **kwargs):
        self._calls = calls

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, **kwargs):
        return _FakeAnthropicResp(self._calls, str(url))


def _make_client(monkeypatch, token):
    for key in _PROVIDER_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_UPSTREAM_KEY)
    monkeypatch.setattr("dashboard.server.settings", Settings(frood_gateway_token=token))
    calls: list = []

    def factory(*args, **kwargs):
        return _FakeAsyncClient(calls, *args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    return TestClient(create_app()), calls


@pytest.fixture
def authed(monkeypatch):
    """Real create_app with a configured token and a faked provider."""
    return _make_client(monkeypatch, TOKEN)


@pytest.fixture
def no_token(monkeypatch):
    """Real create_app with an empty token (fail closed) and a faked provider."""
    return _make_client(monkeypatch, "")


def _request(client, path, headers=None):
    if path in MESSAGE_ROUTES:
        return client.post(path, json=_msg_body(), headers=headers)
    return client.get(path, headers=headers)


@pytest.mark.parametrize("path", ALL_ROUTES)
def test_no_credentials_401(authed, path):
    client, calls = authed
    resp = _request(client, path)
    assert resp.status_code == 401
    assert resp.json()["error"]["type"] == "authentication_error"
    assert TOKEN not in resp.text
    assert calls == []


@pytest.mark.parametrize("path", ALL_ROUTES)
def test_wrong_bearer_401(authed, path):
    client, calls = authed
    resp = _request(client, path, headers=WRONG_BEARER)
    assert resp.status_code == 401
    assert resp.json()["type"] == "error"
    assert TOKEN not in resp.text
    assert "wrong-token-value" not in resp.text
    assert calls == []


@pytest.mark.parametrize("path", ALL_ROUTES)
def test_wrong_key_401(authed, path):
    client, calls = authed
    resp = _request(client, path, headers=WRONG_KEY)
    assert resp.status_code == 401
    assert resp.json()["error"]["type"] == "authentication_error"
    assert TOKEN not in resp.text
    assert "wrong-token-value" not in resp.text
    assert calls == []


@pytest.mark.parametrize("path", ALL_ROUTES)
def test_empty_token_503_even_with_header(no_token, path):
    client, calls = no_token
    resp = _request(client, path, headers=AUTH_BEARER)
    assert resp.status_code == 503
    assert "FROOD_GATEWAY_TOKEN" in resp.json()["error"]["message"]
    assert TOKEN not in resp.text
    assert calls == []


@pytest.mark.parametrize("headers", [AUTH_BEARER, AUTH_KEY])
@pytest.mark.parametrize("path", MODEL_ROUTES)
def test_models_ok_with_token(authed, path, headers):
    client, calls = authed
    resp = _request(client, path, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["object"] == "list"
    assert len(data["data"]) > 0
    assert TOKEN not in resp.text
    assert calls == []


@pytest.mark.parametrize("headers", [AUTH_BEARER, AUTH_KEY])
@pytest.mark.parametrize("path", MESSAGE_ROUTES)
def test_messages_ok_with_token(authed, path, headers):
    client, calls = authed
    resp = _request(client, path, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "message"
    assert data["role"] == "assistant"
    assert data["content"][0]["text"] == "hello from provider"
    assert data["model"] == MODEL
    assert data["stop_reason"] == "end_turn"
    assert "usage" in data
    assert TOKEN not in resp.text
    assert FAKE_UPSTREAM_KEY not in resp.text
    assert len(calls) == 1
    assert "api.anthropic.com" in calls[0]


@pytest.mark.parametrize("path", MESSAGE_ROUTES)
def test_auth_before_json_parsing(authed, path):
    """Auth is the first statement: bad JSON without creds is 401, not 400."""
    client, calls = authed
    resp = client.post(path, content=b"not json", headers={"content-type": "application/json"})
    assert resp.status_code == 401
    resp = client.post(
        path, content=b"not json", headers={**AUTH_BEARER, "content-type": "application/json"}
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["type"] == "invalid_request_error"
    assert calls == []


def test_no_token_in_logs_or_bodies(authed, no_token, caplog):
    """The configured and provided tokens never appear in logs or error bodies."""
    authed_client, _ = authed
    empty_client, _ = no_token
    bodies: list[str] = []
    with caplog.at_level(logging.DEBUG):
        for path in ALL_ROUTES:
            bodies.append(_request(authed_client, path).text)
            bodies.append(_request(authed_client, path, headers=WRONG_KEY).text)
            bodies.append(_request(empty_client, path, headers=AUTH_BEARER).text)
        for path in MESSAGE_ROUTES:
            bodies.append(_request(authed_client, path, headers=AUTH_BEARER).text)
    for record in caplog.records:
        text = record.getMessage()
        try:
            args_text = str(record.args)
        except Exception:
            args_text = ""
        for secret in (TOKEN, "wrong-token-value", FAKE_UPSTREAM_KEY):
            assert secret not in text, record.name
            assert secret not in args_text, record.name
    for body in bodies:
        for secret in (TOKEN, "wrong-token-value", FAKE_UPSTREAM_KEY):
            assert secret not in body
