"""tests/test_gateway_routing.py — Frood gateway tier routing (gw-t3).

Go ids are forwarded to OpenCode Go; Nvidia ids are translated to OpenAI
Chat Completions and served from Nvidia; a Go request falls back to Nvidia
when the pace guard reads "over" or the Go attempt fails before any
response byte reaches the client.

No network and no real keys: the upstream is one httpx.MockTransport that
dispatches on the request host, the pace snapshot is a temp go-usage.jsonl,
and the Nvidia key is fake.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time as _time
from unittest.mock import MagicMock

import httpx
from fastapi.testclient import TestClient

from core.config import Settings
from dashboard import gateway as gw_module
from dashboard.gateway import (
    RouteTables,
    is_claude_model,
    parse_go_fallback,
    plan_route,
    read_go_state,
)
from dashboard.server import create_app

TOKEN = "test-gateway-token-abc123"
GO_KEY = "go-test-key-xyz-999"
NVIDIA_KEY = "nv-test-key-aaa-111"
GO_MODELS = "deepseek-v4.1-flash,glm-5.3-flash,kimi-k3"
NVIDIA_MODELS = (
    "minimaxai/minimax-m3.1-flash,nvidia/nemotron-3.5-lightning-30b-a3b,"
    "nvidia/nemotron-3.5-super-vl-120b-a12b"
)
GO_BASE = "https://opencode.ai/zen/go/v1"
NVIDIA_BASE = "https://integrate.api.nvidia.com/v1"
FALLBACK = (
    "kimi-k3=minimaxai/minimax-m3.1-flash,"
    "glm-5.3-flash=minimaxai/minimax-m3.1-flash,"
    "deepseek-v4.1-flash=nvidia/nemotron-3.5-lightning-30b-a3b"
)

AUTH = {"Authorization": f"Bearer {TOKEN}"}

_REAL_ASYNC_CLIENT = httpx.AsyncClient

NV_UPSTREAM = "minimaxai/minimax-m3.1-flash"
LITE_UPSTREAM = "nvidia/nemotron-3.5-lightning-30b-a3b"
SUPER_UPSTREAM = "nvidia/nemotron-3.5-super-vl-120b-a12b"


def _settings(**overrides) -> Settings:
    kw = {
        "frood_gateway_token": TOKEN,
        "gateway_go_base_url": GO_BASE,
        "gateway_go_models": GO_MODELS,
        "gateway_nvidia_base_url": NVIDIA_BASE,
        "gateway_nvidia_models": NVIDIA_MODELS,
        "gateway_go_fallback": FALLBACK,
        "gateway_go_pace_max_pct": 90.0,
        "nvidia_api_key": NVIDIA_KEY,
    }
    kw.update(overrides)
    return Settings(**kw)


def _client_for(
    monkeypatch, settings_obj, handler, go_key=GO_KEY, usage_path=None, db_path=None, sleeper=None
):
    """create_app TestClient with a host-dispatching mock upstream.

    ``usage_path`` pins the pace snapshot; when None a missing temp path is
    used so the pace guard reads "unknown" (allowed) deterministically.
    ``db_path`` pins the Go-key sqlite lookup; when None the real XDG default
    applies (pass a missing path to force "no Go key" deterministically).
    """
    monkeypatch.setattr("dashboard.server.settings", settings_obj)
    if usage_path is None:
        usage_path = "/tmp/opencode/gw-t3-no-such-usage.jsonl"
    original = gw_module.build_gateway_router

    def _router_with_test_host(**kw):
        kw.pop("test_client_host", None)
        kw.pop("go_usage_path", None)
        if sleeper is not None:
            kw["sleeper"] = sleeper
        return original(test_client_host="testclient", go_usage_path=usage_path, **kw)

    monkeypatch.setattr("dashboard.server.build_gateway_router", _router_with_test_host)
    transport = httpx.MockTransport(handler)

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return _REAL_ASYNC_CLIENT(*args, **kwargs)

    monkeypatch.setattr("dashboard.gateway.httpx.AsyncClient", factory)
    if go_key is None:
        monkeypatch.delenv("OPENCODE_GO_KEY", raising=False)
    else:
        monkeypatch.setenv("OPENCODE_GO_KEY", go_key)
    # Tests never read a real NVIDIA_API_KEY from the environment; opt in
    # explicitly in the precedence tests below.
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    if db_path is None:
        monkeypatch.delenv("OPENCODE_DB", raising=False)
    else:
        monkeypatch.setenv("OPENCODE_DB", str(db_path))
    gw_module._go_key_cache.clear()
    gw_module._go_state_cache.clear()
    gw_module._crit_logged_hosts.clear()
    return TestClient(create_app())


def _msg_body(model="kimi-k3", stream=False, **extra):
    body = {
        "model": model,
        "max_tokens": 64,
        "messages": [{"role": "user", "content": "hello"}],
    }
    if stream:
        body["stream"] = True
    body.update(extra)
    return body


def _tables(**overrides) -> RouteTables:
    kw = {
        "go": {"kimi-k3": "kimi-k3", "glm-5.3-flash": "glm-5.3-flash"},
        "nvidia": {
            NV_UPSTREAM: NV_UPSTREAM,
            LITE_UPSTREAM: LITE_UPSTREAM,
            SUPER_UPSTREAM: SUPER_UPSTREAM,
        },
        "fallback": {"kimi-k3": NV_UPSTREAM},
        "nvidia_key": NVIDIA_KEY,
    }
    kw.update(overrides)
    return RouteTables(**kw)


def _make_sleeper():
    """A recording sleeper for the gateway's Nvidia 429 waits: (calls, sleep)."""
    calls: list[float] = []

    async def _sleep(delay):
        calls.append(float(delay))

    return calls, _sleep


def _nvidia_sse_chunks():
    def chunk(payload):
        return ("data: " + json.dumps(payload) + "\n\n").encode()

    return [
        chunk(
            {
                "id": "chatcmpl-1",
                "choices": [
                    {
                        "index": 0,
                        "delta": {"role": "assistant", "content": "Hi"},
                        "finish_reason": None,
                    }
                ],
            }
        ),
        chunk(
            {
                "id": "chatcmpl-1",
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "Edit",
                                        "arguments": '{"path":',
                                    },
                                }
                            ]
                        },
                        "finish_reason": None,
                    }
                ],
            }
        ),
        chunk(
            {
                "id": "chatcmpl-1",
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "function": {"arguments": '"a"}'},
                                }
                            ]
                        },
                        "finish_reason": None,
                    }
                ],
            }
        ),
        chunk(
            {
                "id": "chatcmpl-1",
                "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 12},
            }
        ),
        b"data: [DONE]\n\n",
    ]


def _nvidia_stream_handler(seen):
    async def _achunks():
        for chunk in _nvidia_sse_chunks():
            yield chunk

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_achunks(),
        )

    return handler


def _nvidia_json_payload():
    return {
        "id": "chatcmpl-9",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "done",
                    "tool_calls": [
                        {
                            "id": "call_9",
                            "type": "function",
                            "function": {"name": "Bash", "arguments": '{"cmd":"ls"}'},
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 4, "completion_tokens": 7},
    }


def _split_handler(go_handler, nvidia_handler):
    """Route mock requests to the Go or Nvidia handler by request host."""

    def handler(request: httpx.Request) -> httpx.Response:
        if "integrate.api.nvidia.com" in str(request.url):
            return nvidia_handler(request)
        return go_handler(request)

    return handler


def _write_nvidia_credential_db(path, key):
    """Write a temp credential db with one active ``nvidia`` row holding ``key``."""
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS credential (integration_id TEXT, active INTEGER, value TEXT)"
        )
        conn.execute(
            "INSERT INTO credential (integration_id, active, value) VALUES (?, ?, ?)",
            ("nvidia", 1, json.dumps({"key": key})),
        )
        conn.commit()
    finally:
        conn.close()


# -- bar 1: plan_route table tests --------------------------------------------


def test_plan_go_ok_then_nvidia():
    """GW-T3-01a: Go id with pace ok => [go, nvidia]."""
    candidates, error = plan_route("kimi-k3", _tables(), "ok")
    assert error is None
    assert candidates == [("go", "kimi-k3"), ("nvidia", NV_UPSTREAM)]


def test_plan_go_unknown_state_still_go_first():
    """GW-T3-01b: unknown pace counts as allowed => Go first."""
    candidates, error = plan_route("kimi-k3", _tables(), "unknown")
    assert error is None
    assert candidates[0] == ("go", "kimi-k3")


def test_plan_go_over_drops_go():
    """GW-T3-01c: pace over => Nvidia only."""
    candidates, error = plan_route("kimi-k3", _tables(), "over")
    assert error is None
    assert candidates == [("nvidia", NV_UPSTREAM)]


def test_plan_go_over_unmapped_uses_first_nvidia():
    """GW-T3-01d: Go id with no fallback entry uses the first Nvidia id."""
    candidates, error = plan_route("glm-5.3-flash", _tables(), "over")
    assert error is None
    assert candidates == [("nvidia", NV_UPSTREAM)]


def test_plan_nvidia_id():
    """GW-T3-01e: Nvidia id => [nvidia]."""
    candidates, error = plan_route(NV_UPSTREAM, _tables(), "ok")
    assert error is None
    assert candidates == [("nvidia", NV_UPSTREAM)]


def test_plan_claude_refused_in_either_table():
    """GW-T3-01f: claude-* refused for an id in either table."""
    tables = _tables(
        go={"claude-sonnet-4-6": "claude-sonnet-4-6"},
        nvidia={"nvidia/claude-x": "nvidia/claude-x"},
    )
    for model in ("claude-sonnet-4-6", "nvidia/claude-x", "CLAUDE-y"):
        candidates, error = plan_route(model, tables, "ok")
        assert candidates == []
        assert error is not None and error.status == 403


def test_plan_claude_segments():
    """GW-T3-01g: any /-separated segment starting with claude refuses."""
    assert is_claude_model("anthropic/claude-x")
    assert is_claude_model("nvidia/Claude-y")
    assert not is_claude_model("kimi-k3")
    assert not is_claude_model("myclaude-ish")
    candidates, error = plan_route("anthropic/claude-x", _tables(), "ok")
    assert candidates == [] and error is not None and error.status == 403


def test_plan_unknown_404():
    """GW-T3-01h: unknown id => 404."""
    candidates, error = plan_route("gpt-zzz", _tables(), "ok")
    assert candidates == []
    assert error is not None and error.status == 404
    assert error.kind == "not_found_error"


def test_plan_no_nvidia_key_no_nvidia_candidate():
    """GW-T3-01i: empty key => Go id has no Nvidia candidate."""
    candidates, error = plan_route("kimi-k3", _tables(nvidia_key=""), "ok")
    assert error is None
    assert candidates == [("go", "kimi-k3")]


def test_plan_no_nvidia_key_nvidia_id_503():
    """GW-T3-01j: Nvidia id with an empty key => 503."""
    candidates, error = plan_route(NV_UPSTREAM, _tables(nvidia_key=""), "ok")
    assert candidates == []
    assert error is not None and error.status == 503
    assert "NVIDIA_API_KEY" in error.message


def test_plan_non_str_key_counts_as_empty():
    """GW-T3-01k: a non-str key counts as empty."""
    candidates, error = plan_route(NV_UPSTREAM, _tables(nvidia_key=MagicMock()), "ok")
    assert candidates == [] and error is not None and error.status == 503


def test_plan_over_no_fallback_429():
    """GW-T3-01l: pace over with no fallback => 429 with x-should-retry."""
    tables = _tables(nvidia={}, fallback={}, nvidia_key=NVIDIA_KEY)
    candidates, error = plan_route("kimi-k3", tables, "over")
    assert candidates == []
    assert error is not None and error.status == 429
    assert error.kind == "rate_limit_error"
    assert error.headers.get("x-should-retry") == "false"
    # Same when the key is missing entirely.
    tables = _tables(nvidia_key="")
    candidates, error = plan_route("kimi-k3", tables, "over")
    assert candidates == [] and error is not None and error.status == 429


def test_plan_empty_fallback_map_means_no_fallback():
    """GW-T3-01o: GATEWAY_GO_FALLBACK= opts out even with Nvidia ids routed."""
    tables = _tables(fallback={})
    candidates, error = plan_route("kimi-k3", tables, "ok")
    assert error is None
    assert candidates == [("go", "kimi-k3")]
    candidates, error = plan_route("kimi-k3", tables, "over")
    assert candidates == []
    assert error is not None and error.status == 429
    assert error.headers.get("x-should-retry") == "false"


def test_plan_unmapped_id_uses_first_nvidia_when_map_set():
    """GW-T3-01p: a non-empty map without this id still uses the first Nvidia id."""
    tables = _tables(fallback={"other": LITE_UPSTREAM})
    candidates, error = plan_route("kimi-k3", tables, "ok")
    assert error is None
    assert candidates == [("go", "kimi-k3"), ("nvidia", NV_UPSTREAM)]


def test_plan_go_wins_when_in_both_tables():
    """GW-T3-01m: an id in both tables routes Go first."""
    tables = _tables(
        go={"shared": "shared"},
        nvidia={"shared": "shared", NV_UPSTREAM: NV_UPSTREAM},
    )
    candidates, error = plan_route("shared", tables, "ok")
    assert error is None
    assert candidates[0] == ("go", "shared")


def test_parse_go_fallback_rules():
    """GW-T3-01n: empty string means none; non-str means defaults."""
    assert parse_go_fallback("") == {}
    assert parse_go_fallback("  , ,") == {}
    assert parse_go_fallback("a=nv-a,b=nv-b") == {"a": "nv-a", "b": "nv-b"}
    assert parse_go_fallback("a=nv-a,a=nv-x") == {"a": "nv-a"}
    assert parse_go_fallback("noequals") == {}
    assert parse_go_fallback(None) == parse_go_fallback(FALLBACK)
    assert parse_go_fallback(MagicMock()) == parse_go_fallback(FALLBACK)


# -- bar 2: read_go_state ------------------------------------------------------


def _write_snapshot(tmp_path, name="go-usage.jsonl", **windows):
    """Write one snapshot line; windows map name -> dict or None.

    ``at`` defaults to the current time so the snapshot is fresh unless the
    caller pins an explicit ``at`` (e.g. the staleness test).
    """
    at = windows.pop("at", None)
    if at is None:
        at = _time.time()
    snapshot = {"at": at}
    for window in ("rolling", "weekly", "monthly"):
        snapshot[window] = windows.get(window)
    path = tmp_path / name
    path.write_text(json.dumps(snapshot) + "\n")
    return str(path)


def _window(pct=10, status="ok", resets_at=2000.0):
    return {"pct": pct, "status": status, "resets_at": resets_at}


def test_go_state_weekly_95_over(tmp_path):
    """GW-T3-02a: weekly 95 with limit 90 => over."""
    gw_module._go_state_cache.clear()
    path = _write_snapshot(tmp_path, weekly=_window(pct=95))
    assert read_go_state(path, 90, 1000.0) == "over"


def test_go_state_all_under_ok(tmp_path):
    """GW-T3-02b: every window under the limit => ok."""
    gw_module._go_state_cache.clear()
    path = _write_snapshot(
        tmp_path,
        rolling=_window(pct=10),
        weekly=_window(pct=20),
        monthly=_window(pct=30),
    )
    assert read_go_state(path, 90, 1000.0) == "ok"


def test_go_state_limited_future_reset_over(tmp_path):
    """GW-T3-02c: non-ok status with a future reset => over."""
    gw_module._go_state_cache.clear()
    path = _write_snapshot(tmp_path, weekly={"pct": 10, "status": "limited", "resets_at": 2000.0})
    assert read_go_state(path, 90, 1000.0) == "over"


def test_go_state_limited_past_reset_ok(tmp_path):
    """GW-T3-02d: non-ok status with a past reset => ok."""
    gw_module._go_state_cache.clear()
    path = _write_snapshot(tmp_path, weekly={"pct": 10, "status": "limited", "resets_at": 500.0})
    assert read_go_state(path, 90, 1000.0) == "ok"


def test_go_state_stale_unknown(tmp_path):
    """GW-T3-02e: a 7 h old snapshot => unknown."""
    gw_module._go_state_cache.clear()
    path = _write_snapshot(tmp_path, at=1000.0, weekly=_window(pct=95))
    assert read_go_state(path, 90, 1000.0 + 7 * 3600) == "unknown"


def test_go_state_missing_or_bad_unknown(tmp_path):
    """GW-T3-02f: missing, empty or unparsable file => unknown."""
    gw_module._go_state_cache.clear()
    assert read_go_state(str(tmp_path / "nope.jsonl"), 90, 1000.0) == "unknown"
    bad = tmp_path / "bad.jsonl"
    bad.write_text("not json\n")
    gw_module._go_state_cache.clear()
    assert read_go_state(str(bad), 90, 1000.0) == "unknown"
    empty = tmp_path / "empty.jsonl"
    empty.write_text("\n")
    gw_module._go_state_cache.clear()
    assert read_go_state(str(empty), 90, 1000.0) == "unknown"
    noval = tmp_path / "noval.jsonl"
    noval.write_text("[1,2]\n")
    gw_module._go_state_cache.clear()
    assert read_go_state(str(noval), 90, 1000.0) == "unknown"


def test_go_state_iso_at_and_resets(tmp_path):
    """GW-T3-02g: ISO timestamps parse for staleness and resets."""
    gw_module._go_state_cache.clear()
    snap = {
        "at": "2026-11-28T01:00:00Z",
        "rolling": None,
        "weekly": {"pct": 10, "status": "limited", "resets_at": "2026-11-28T05:00:00Z"},
        "monthly": None,
    }
    path = tmp_path / "iso.jsonl"
    path.write_text(json.dumps(snap) + "\n")
    assert read_go_state(str(path), 90, 1793652000.0) == "over"


def test_go_state_bad_window_skipped(tmp_path):
    """GW-T3-02h: a window with missing/non-number pct is skipped."""
    gw_module._go_state_cache.clear()
    path = _write_snapshot(
        tmp_path,
        weekly={"status": "limited", "resets_at": 2000.0},
        monthly={"pct": "high", "status": "limited", "resets_at": 2000.0},
    )
    assert read_go_state(str(path), 90, 1000.0) == "ok"


def test_go_state_cached_60s(tmp_path, monkeypatch):
    """GW-T3-02i: two calls within 60 s read the file once (injected clock)."""
    gw_module._go_state_cache.clear()
    path = _write_snapshot(tmp_path, weekly=_window(pct=10))
    calls: list[str] = []
    original = gw_module._read_last_snapshot

    def spy(path_str: str):
        calls.append(path_str)
        return original(path_str)

    monkeypatch.setattr(gw_module, "_read_last_snapshot", spy)
    assert read_go_state(path, 90, 1000.0) == "ok"
    assert read_go_state(path, 90, 1030.0) == "ok"
    assert len(calls) == 1
    assert read_go_state(path, 90, 1070.0) == "ok"
    assert len(calls) == 2


# -- bar 3: Nvidia streaming end to end ----------------------------------------


def test_nvidia_streaming_end_to_end(monkeypatch):
    """GW-T3-03: routed Nvidia id streams translated SSE with the requested model."""
    seen: list[httpx.Request] = []
    client = _client_for(monkeypatch, _settings(), _nvidia_stream_handler(seen))
    resp = client.post(
        "/gw/v1/messages",
        json=_msg_body(model=NV_UPSTREAM, stream=True),
        headers=AUTH,
    )
    assert resp.status_code == 200
    assert resp.headers["x-frood-route"] == f"nvidia:{NV_UPSTREAM}"
    text = resp.text
    assert "event: message_start" in text
    assert '"type":"tool_use"' in text
    assert '"name":"Edit"' in text
    assert "event: message_stop" in text
    assert f'"model":"{NV_UPSTREAM}"' in text
    # The mock saw the OpenAI shape, the fake key, and no Go/session headers.
    assert len(seen) == 1
    upstream = seen[0]
    assert upstream.url.path == "/v1/chat/completions"
    assert upstream.headers["authorization"] == f"Bearer {NVIDIA_KEY}"
    assert "x-opencode-session" not in upstream.headers
    assert not any(name.startswith("anthropic-") for name in upstream.headers)
    sent = json.loads(upstream.content.decode())
    assert sent["model"] == NV_UPSTREAM
    assert sent["stream"] is True
    assert "tools" not in sent  # this body carries none; tools ride along when set
    assert upstream.headers["accept-encoding"] == "identity"
    assert upstream.headers["user-agent"].startswith("frood-gateway/")


def test_nvidia_streaming_carries_tools(monkeypatch):
    """GW-T3-03b: request tools reach the OpenAI body."""
    seen: list[httpx.Request] = []
    client = _client_for(monkeypatch, _settings(), _nvidia_stream_handler(seen))
    body = _msg_body(model=NV_UPSTREAM, stream=True)
    body["tools"] = [{"name": "Edit", "description": "d", "input_schema": {"type": "object"}}]
    resp = client.post("/gw/v1/messages", json=body, headers=AUTH)
    assert resp.status_code == 200
    sent = json.loads(seen[0].content.decode())
    assert sent["tools"][0]["function"]["name"] == "Edit"


# -- bar 4: Nvidia non-streaming ------------------------------------------------


def test_nvidia_non_streaming(monkeypatch):
    """GW-T3-04: non-streaming Nvidia maps to an Anthropic message."""

    def handler(request: httpx.Request) -> httpx.Response:
        if "integrate.api.nvidia.com" in str(request.url):
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json=_nvidia_json_payload(),
            )
        raise AssertionError("Go must not be called for an Nvidia id")

    client = _client_for(monkeypatch, _settings(), handler)
    resp = client.post("/gw/v1/messages", json=_msg_body(model=NV_UPSTREAM), headers=AUTH)
    assert resp.status_code == 200
    assert resp.headers["x-frood-route"] == f"nvidia:{NV_UPSTREAM}"
    data = resp.json()
    assert data["model"] == NV_UPSTREAM
    assert data["stop_reason"] == "tool_use"
    tool = next(b for b in data["content"] if b["type"] == "tool_use")
    assert tool == {"type": "tool_use", "id": "call_9", "name": "Bash", "input": {"cmd": "ls"}}
    assert data["usage"] == {"input_tokens": 4, "output_tokens": 7}


def test_nvidia_non_streaming_error_key_502(monkeypatch):
    """GW-T3-04b: a 200 body carrying error maps to 502, not an empty message."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={"error": {"message": "bad request", "type": "invalid_request_error"}},
        )

    client = _client_for(monkeypatch, _settings(), handler)
    resp = client.post("/gw/v1/messages", json=_msg_body(model=NV_UPSTREAM), headers=AUTH)
    assert resp.status_code == 502
    assert resp.json()["error"]["type"] == "api_error"


# -- bar 5: fallback ------------------------------------------------------------


def _go_then_nvidia_client(monkeypatch, tmp_path, go_behavior):
    """Mock Go fails per go_behavior; Nvidia answers non-streaming JSON."""
    go_seen: list[httpx.Request] = []
    nv_seen: list[httpx.Request] = []

    def go_handler(request: httpx.Request) -> httpx.Response:
        go_seen.append(request)
        return go_behavior(request)

    def nvidia_handler(request: httpx.Request) -> httpx.Response:
        nv_seen.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json=_nvidia_json_payload(),
        )

    missing = str(tmp_path / "missing.jsonl")
    client = _client_for(
        monkeypatch,
        _settings(),
        _split_handler(go_handler, nvidia_handler),
        usage_path=missing,
    )
    return client, go_seen, nv_seen


def test_fallback_go_429_serves_nvidia_streaming(monkeypatch, tmp_path, caplog):
    """GW-T3-05a: Go 429 pre-stream falls back; one INFO line; Go called once."""
    go_seen: list[httpx.Request] = []
    nv_seen: list[httpx.Request] = []

    def go_handler(request: httpx.Request) -> httpx.Response:
        go_seen.append(request)
        return httpx.Response(
            429,
            headers={"content-type": "application/json"},
            json={"type": "error", "error": {"type": "rate_limit_error", "message": "slow"}},
        )

    client = _client_for(
        monkeypatch,
        _settings(),
        _split_handler(go_handler, _nvidia_stream_handler(nv_seen)),
        usage_path=str(tmp_path / "missing.jsonl"),
    )
    with caplog.at_level(logging.INFO, logger="frood.gateway"):
        resp = client.post(
            "/gw/v1/messages", json=_msg_body(model="kimi-k3", stream=True), headers=AUTH
        )
    assert resp.status_code == 200
    assert resp.headers["x-frood-route"] == f"nvidia:{NV_UPSTREAM}"
    assert "event: message_start" in resp.text
    assert len(go_seen) == 1
    assert len(nv_seen) == 1
    fallbacks = [r for r in caplog.records if "gateway fallback" in r.getMessage()]
    assert len(fallbacks) == 1
    assert "provider=go" in fallbacks[0].getMessage()
    assert "status=429" in fallbacks[0].getMessage()


def test_fallback_go_connect_error_serves_nvidia(monkeypatch, tmp_path, caplog):
    """GW-T3-05b: Go connect error falls back to Nvidia."""
    client, go_seen, nv_seen = _go_then_nvidia_client(
        monkeypatch, tmp_path, lambda request: (_ for _ in ()).throw(httpx.ConnectError("down"))
    )
    with caplog.at_level(logging.INFO, logger="frood.gateway"):
        resp = client.post("/gw/v1/messages", json=_msg_body(model="kimi-k3"), headers=AUTH)
    assert resp.status_code == 200
    assert resp.headers["x-frood-route"] == f"nvidia:{NV_UPSTREAM}"
    assert resp.json()["model"] == "kimi-k3"
    assert len(go_seen) == 1
    assert len(nv_seen) == 1
    fallbacks = [r for r in caplog.records if "gateway fallback" in r.getMessage()]
    assert len(fallbacks) == 1


def test_fallback_go_400_no_fallback(monkeypatch, tmp_path):
    """GW-T3-05c: Go 400 is terminal — 400 passed through, Nvidia untouched."""
    seen_nv: list[httpx.Request] = []

    def go_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            headers={"content-type": "application/json"},
            json={"type": "error", "error": {"type": "invalid_request_error", "message": "bad"}},
        )

    def nv_handler(request: httpx.Request) -> httpx.Response:
        seen_nv.append(request)
        raise AssertionError("Nvidia must not be called on Go 400")

    client = _client_for(
        monkeypatch,
        _settings(),
        _split_handler(go_handler, nv_handler),
        usage_path=str(tmp_path / "missing.jsonl"),
    )
    resp = client.post("/gw/v1/messages", json=_msg_body(model="kimi-k3"), headers=AUTH)
    assert resp.status_code == 400
    assert resp.json()["error"]["type"] == "invalid_request_error"
    assert seen_nv == []


def test_missing_go_key_serves_nvidia_when_mapped(monkeypatch, tmp_path):
    """GW-T3-05d: no Go key drops the Go candidate; mapped Nvidia serves."""
    go_seen: list[httpx.Request] = []

    def go_handler(request: httpx.Request) -> httpx.Response:
        go_seen.append(request)
        raise AssertionError("Go must not be called with no Go key")

    client = _client_for(
        monkeypatch,
        _settings(),
        _split_handler(go_handler, _nvidia_stream_handler([])),
        go_key=None,
        db_path=str(tmp_path / "no-such.db"),
        usage_path=str(tmp_path / "missing.jsonl"),
    )
    resp = client.post(
        "/gw/v1/messages", json=_msg_body(model="kimi-k3", stream=True), headers=AUTH
    )
    assert resp.status_code == 200
    assert resp.headers["x-frood-route"] == f"nvidia:{NV_UPSTREAM}"
    assert "event: message_start" in resp.text
    assert go_seen == []


def test_fallback_go_error_body_unreadable(monkeypatch, tmp_path, caplog):
    """GW-T3-05e: a failing error-body read falls back to Nvidia."""
    go_seen: list[httpx.Request] = []
    nv_seen: list[httpx.Request] = []

    async def _boom():
        raise httpx.ReadError("unreadable")
        yield b""  # pragma: no cover - makes this an async generator

    def go_handler(request: httpx.Request) -> httpx.Response:
        go_seen.append(request)
        return httpx.Response(
            429,
            headers={"content-type": "application/json"},
            content=_boom(),
        )

    client = _client_for(
        monkeypatch,
        _settings(),
        _split_handler(go_handler, _nvidia_stream_handler(nv_seen)),
        usage_path=str(tmp_path / "missing.jsonl"),
    )
    with caplog.at_level(logging.INFO, logger="frood.gateway"):
        resp = client.post(
            "/gw/v1/messages", json=_msg_body(model="kimi-k3", stream=True), headers=AUTH
        )
    assert resp.status_code == 200
    assert resp.headers["x-frood-route"] == f"nvidia:{NV_UPSTREAM}"
    assert len(go_seen) == 1
    assert len(nv_seen) == 1
    fallbacks = [r for r in caplog.records if "gateway fallback" in r.getMessage()]
    assert len(fallbacks) == 1
    assert "provider=go" in fallbacks[0].getMessage()
    assert "status=read-error" in fallbacks[0].getMessage()


def test_pace_over_empty_fallback_map_429(monkeypatch, tmp_path):
    """GW-T3-06c: pace over with GATEWAY_GO_FALLBACK= => 429, upstream untouched."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        raise AssertionError("no upstream may be called")

    client = _client_for(
        monkeypatch,
        _settings(gateway_go_fallback=""),
        handler,
        usage_path=_write_snapshot(tmp_path, weekly=_window(pct=95)),
    )
    resp = client.post("/gw/v1/messages", json=_msg_body(model="kimi-k3"), headers=AUTH)
    assert resp.status_code == 429
    assert resp.json()["error"]["type"] == "rate_limit_error"
    assert resp.headers["x-should-retry"] == "false"
    assert seen == []


# -- bar 6: pace over -----------------------------------------------------------


def test_pace_over_go_never_called(monkeypatch, tmp_path):
    """GW-T3-06: pace over routes straight to Nvidia; Go untouched."""
    go_seen: list[httpx.Request] = []
    nv_seen: list[httpx.Request] = []

    def go_handler(request: httpx.Request) -> httpx.Response:
        go_seen.append(request)
        raise AssertionError("Go must not be called when pace is over")

    client = _client_for(
        monkeypatch,
        _settings(),
        _split_handler(go_handler, _nvidia_stream_handler(nv_seen)),
        usage_path=_write_snapshot(tmp_path, weekly=_window(pct=95)),
    )
    resp = client.post(
        "/gw/v1/messages",
        json=_msg_body(model="kimi-k3", stream=True),
        headers=AUTH,
    )
    assert resp.status_code == 200
    assert resp.headers["x-frood-route"] == f"nvidia:{NV_UPSTREAM}"
    assert go_seen == []
    assert len(nv_seen) == 1


def test_pace_over_no_fallback_429(monkeypatch, tmp_path):
    """GW-T3-06b: pace over with no Nvidia key => 429, upstream untouched."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        raise AssertionError("no upstream may be called")

    client = _client_for(
        monkeypatch,
        _settings(nvidia_api_key=""),
        handler,
        db_path=str(tmp_path / "nope-nvidia.db"),
        usage_path=_write_snapshot(tmp_path, weekly=_window(pct=95)),
    )
    resp = client.post("/gw/v1/messages", json=_msg_body(model="kimi-k3"), headers=AUTH)
    assert resp.status_code == 429
    assert resp.json()["error"]["type"] == "rate_limit_error"
    assert resp.headers["x-should-retry"] == "false"
    assert resp.headers["x-frood-route"] == "none"
    assert seen == []


# -- bar 7: Nvidia 429 ----------------------------------------------------------


def test_nvidia_429_mapped(monkeypatch, caplog):
    """GW-T3-07 (gw-nv-models): a surviving Nvidia 429 maps to rate_limit_error.

    The gateway retries the same model first (retry-after 11 s, twice, then
    the 30 s cap stops the third wait); the survivor keeps ``retry-after``
    but never carries ``x-should-retry``, so Claude Code's own backoff takes
    over.
    """
    seen: list[httpx.Request] = []
    calls, fake_sleep = _make_sleeper()

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            429,
            headers={"content-type": "application/json", "retry-after": "11"},
            json={"error": {"message": "nvidia busy", "type": "rate_limit_exceeded"}},
        )

    client = _client_for(monkeypatch, _settings(), handler, sleeper=fake_sleep)
    with caplog.at_level(logging.INFO, logger="frood.gateway"):
        resp = client.post("/gw/v1/messages", json=_msg_body(model=NV_UPSTREAM), headers=AUTH)
    assert resp.status_code == 429
    assert "x-should-retry" not in resp.headers
    assert resp.headers["retry-after"] == "11"
    data = resp.json()
    assert data["type"] == "error"
    assert data["error"]["type"] == "rate_limit_error"
    assert data["error"]["message"] == "nvidia busy"
    assert resp.headers["x-frood-route"] == f"nvidia:{NV_UPSTREAM}"
    # 11 + 11 = 22 s waited; a third 11 s wait would pass the 30 s cap.
    assert calls == [11.0, 11.0]
    assert len(seen) == 3
    retries = [r for r in caplog.records if "gateway nvidia retry" in r.getMessage()]
    assert len(retries) == 2
    assert "attempt=1" in retries[0].getMessage()
    assert "attempt=2" in retries[1].getMessage()


def test_nvidia_429_then_200_streaming(monkeypatch, caplog):
    """gw-nv-models: Nvidia 429 (retry-after 3) then 200 => 200 SSE stream, one 3 s wait."""
    attempts = {"n": 0}
    calls, fake_sleep = _make_sleeper()
    stream_200 = _nvidia_stream_handler([])

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] == 1:
            return httpx.Response(
                429,
                headers={"content-type": "application/json", "retry-after": "3"},
                json={"error": {"message": "nvidia busy", "type": "rate_limit_exceeded"}},
            )
        return stream_200(request)

    client = _client_for(monkeypatch, _settings(), handler, sleeper=fake_sleep)
    with caplog.at_level(logging.INFO, logger="frood.gateway"):
        resp = client.post(
            "/gw/v1/messages", json=_msg_body(model=NV_UPSTREAM, stream=True), headers=AUTH
        )
    assert resp.status_code == 200
    assert resp.headers["x-frood-route"] == f"nvidia:{NV_UPSTREAM}"
    assert "event: message_start" in resp.text
    assert f'"model":"{NV_UPSTREAM}"' in resp.text
    assert calls == [3.0]
    assert attempts["n"] == 2
    retries = [r for r in caplog.records if "gateway nvidia retry" in r.getMessage()]
    assert len(retries) == 1
    assert "status=429" in retries[0].getMessage()
    assert "provider=nvidia" in retries[0].getMessage()
    assert "attempt=1" in retries[0].getMessage()


def test_nvidia_429_then_200_no_retry_after(monkeypatch):
    """gw-nv-models: Nvidia 429 without retry-after then 200 => 200 JSON, one 2 s wait."""
    attempts = {"n": 0}
    calls, fake_sleep = _make_sleeper()

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] == 1:
            return httpx.Response(
                429,
                headers={"content-type": "application/json"},
                json={"error": {"message": "nvidia busy", "type": "rate_limit_exceeded"}},
            )
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json=_nvidia_json_payload(),
        )

    client = _client_for(monkeypatch, _settings(), handler, sleeper=fake_sleep)
    resp = client.post("/gw/v1/messages", json=_msg_body(model=NV_UPSTREAM), headers=AUTH)
    assert resp.status_code == 200
    assert resp.headers["x-frood-route"] == f"nvidia:{NV_UPSTREAM}"
    assert resp.json()["model"] == NV_UPSTREAM
    assert calls == [2.0]
    assert attempts["n"] == 2


def test_nvidia_429_four_times_drops_should_retry(monkeypatch, caplog):
    """gw-nv-models: four Nvidia 429s => 429 with no x-should-retry; 2/4/8 s waits (14 s)."""
    seen: list[httpx.Request] = []
    calls, fake_sleep = _make_sleeper()

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            429,
            headers={"content-type": "application/json"},
            json={"error": {"message": "nvidia busy", "type": "rate_limit_exceeded"}},
        )

    client = _client_for(monkeypatch, _settings(), handler, sleeper=fake_sleep)
    with caplog.at_level(logging.INFO, logger="frood.gateway"):
        resp = client.post(
            "/gw/v1/messages", json=_msg_body(model=NV_UPSTREAM, stream=True), headers=AUTH
        )
    assert resp.status_code == 429
    assert "x-should-retry" not in resp.headers
    assert "retry-after" not in resp.headers
    data = resp.json()
    assert data["error"]["type"] == "rate_limit_error"
    assert resp.headers["x-frood-route"] == f"nvidia:{NV_UPSTREAM}"
    assert calls == [2.0, 4.0, 8.0]
    assert sum(calls) <= 30.0
    assert len(seen) == 4
    retries = [r for r in caplog.records if "gateway nvidia retry" in r.getMessage()]
    assert len(retries) == 3


def test_go_429_last_candidate_keeps_should_retry(monkeypatch, tmp_path, caplog):
    """gw-nv-models: a Go-only 429 on the last candidate keeps x-should-retry: false."""
    go_seen: list[httpx.Request] = []

    def go_handler(request: httpx.Request) -> httpx.Response:
        go_seen.append(request)
        return httpx.Response(
            429,
            headers={"content-type": "application/json", "retry-after": "7"},
            json={"type": "error", "error": {"type": "rate_limit_error", "message": "slow"}},
        )

    client = _client_for(
        monkeypatch,
        _settings(gateway_go_fallback=""),
        _split_handler(go_handler, _nvidia_stream_handler([])),
        usage_path=str(tmp_path / "missing.jsonl"),
    )
    with caplog.at_level(logging.INFO, logger="frood.gateway"):
        resp = client.post("/gw/v1/messages", json=_msg_body(model="kimi-k3"), headers=AUTH)
    assert resp.status_code == 429
    assert resp.headers["x-should-retry"] == "false"
    assert resp.headers["retry-after"] == "7"
    assert resp.headers["x-frood-route"] == "go:kimi-k3"
    assert len(go_seen) == 1
    fallbacks = [r for r in caplog.records if "gateway fallback" in r.getMessage()]
    assert fallbacks == []


# -- gw-nv-models: config/gateway default parity --------------------------------


def test_gateway_defaults_match_config_defaults(monkeypatch):
    """gw-nv-models: the Settings defaults and the gateway DEFAULTs are identical."""
    field_defaults = Settings()
    assert field_defaults.gateway_nvidia_models == gw_module.DEFAULT_NVIDIA_MODELS
    assert field_defaults.gateway_go_fallback == gw_module.DEFAULT_GO_FALLBACK
    monkeypatch.delenv("GATEWAY_NVIDIA_MODELS", raising=False)
    monkeypatch.delenv("GATEWAY_GO_FALLBACK", raising=False)
    from_env = Settings.from_env()
    assert from_env.gateway_nvidia_models == gw_module.DEFAULT_NVIDIA_MODELS
    assert from_env.gateway_go_fallback == gw_module.DEFAULT_GO_FALLBACK


# -- bar 8: routes + models ------------------------------------------------------


def test_routes_table_and_state(monkeypatch, tmp_path):
    """GW-T3-08a: /gw/v1/routes needs auth; returns the table and go_state."""
    client = _client_for(
        monkeypatch,
        _settings(),
        _nvidia_stream_handler([]),
        usage_path=_write_snapshot(tmp_path, weekly=_window(pct=10)),
    )
    assert client.get("/gw/v1/routes").status_code == 401
    resp = client.get("/gw/v1/routes", headers=AUTH)
    assert resp.status_code == 200
    data = resp.json()
    assert data["go_state"] == "ok"
    assert data["routes"]["kimi-k3"] == ["go:kimi-k3", f"nvidia:{NV_UPSTREAM}"]
    assert data["routes"][NV_UPSTREAM] == [f"nvidia:{NV_UPSTREAM}"]
    assert TOKEN not in resp.text and GO_KEY not in resp.text
    assert NVIDIA_KEY not in resp.text


def test_models_lists_nvidia_only_with_key(monkeypatch, tmp_path):
    """GW-T3-08b: Nvidia ids appear in /gw/v1/models only when the key is set."""
    client = _client_for(monkeypatch, _settings(), _nvidia_stream_handler([]))
    ids = [m["id"] for m in client.get("/gw/v1/models", headers=AUTH).json()["data"]]
    assert NV_UPSTREAM in ids and LITE_UPSTREAM in ids and SUPER_UPSTREAM in ids
    assert "deepseek-v4.1-flash" in ids

    client = _client_for(
        monkeypatch,
        _settings(nvidia_api_key=""),
        _nvidia_stream_handler([]),
        db_path=str(tmp_path / "nope-nvidia.db"),
    )
    ids = [m["id"] for m in client.get("/gw/v1/models", headers=AUTH).json()["data"]]
    assert NV_UPSTREAM not in ids and LITE_UPSTREAM not in ids and SUPER_UPSTREAM not in ids
    assert "deepseek-v4.1-flash" in ids


# -- bar 9: no secrets in logs ----------------------------------------------------


def test_no_secrets_in_logs_routing(monkeypatch, tmp_path, caplog):
    """GW-T3-09: DEBUG across an Nvidia stream, a fallback and an error leaks nothing."""
    go_seen: list[httpx.Request] = []

    def go_handler(request: httpx.Request) -> httpx.Response:
        go_seen.append(request)
        return httpx.Response(
            429,
            headers={"content-type": "application/json"},
            json={"type": "error", "error": {"type": "rate_limit_error", "message": "slow"}},
        )

    client = _client_for(
        monkeypatch,
        _settings(),
        _split_handler(go_handler, _nvidia_stream_handler([])),
        usage_path=str(tmp_path / "missing.jsonl"),
    )
    with caplog.at_level(logging.DEBUG):
        client.post(
            "/gw/v1/messages",
            json=_msg_body(model=NV_UPSTREAM, stream=True),
            headers=AUTH,
        )
        client.post("/gw/v1/messages", json=_msg_body(model="kimi-k3"), headers=AUTH)

        def err_500(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                500,
                headers={"content-type": "application/json"},
                json={"error": {"message": "boom"}},
            )

        client2 = _client_for(monkeypatch, _settings(), _split_handler(err_500, err_500))
        client2.post("/gw/v1/messages", json=_msg_body(model=NV_UPSTREAM), headers=AUTH)
    assert go_seen != []
    for record in caplog.records:
        text = record.getMessage()
        try:
            args_text = str(record.args)
        except Exception:
            args_text = ""
        for secret in (GO_KEY, TOKEN, NVIDIA_KEY):
            assert secret not in text, record
            assert secret not in args_text, record


# -- bar 10: Nvidia key source (configured > env NVIDIA_API_KEY > credential db) --


def test_nvidia_key_from_sqlite_db(monkeypatch, tmp_path, caplog):
    """Bar 1: no configured/env key, temp db with active nvidia row => serves; mock sees Bearer <fake>.

    The resolved key is never logged (DEBUG caplog).
    """
    seen: list[httpx.Request] = []
    db = tmp_path / "opencode.db"
    _write_nvidia_credential_db(db, "nv-db-key-111")
    gw_module._go_key_cache.clear()

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json=_nvidia_json_payload(),
        )

    client = _client_for(
        monkeypatch,
        _settings(nvidia_api_key=""),
        handler,
        go_key=None,
        db_path=db,
        usage_path=str(tmp_path / "missing.jsonl"),
    )
    with caplog.at_level(logging.DEBUG):
        resp = client.post("/gw/v1/messages", json=_msg_body(model=NV_UPSTREAM), headers=AUTH)
    assert resp.status_code == 200
    assert resp.headers["x-frood-route"] == f"nvidia:{NV_UPSTREAM}"
    assert len(seen) == 1
    assert seen[0].headers["authorization"] == "Bearer nv-db-key-111"
    assert "x-opencode-session" not in seen[0].headers
    for record in caplog.records:
        text = record.getMessage()
        try:
            args_text = str(record.args)
        except Exception:
            args_text = ""
        assert "nv-db-key-111" not in text and "nv-db-key-111" not in args_text


def test_nvidia_key_precedence(monkeypatch, tmp_path):
    """Bar 2: configured key beats env, env beats db."""
    db = tmp_path / "opencode.db"
    _write_nvidia_credential_db(db, "nv-db-key-111")

    def post_nvidia(client, seen):
        client.post("/gw/v1/messages", json=_msg_body(model=NV_UPSTREAM), headers=AUTH)
        return seen[0].headers["authorization"]

    # 1. configured key wins over env (and db).
    seen: list[httpx.Request] = []
    client = _client_for(
        monkeypatch,
        _settings(nvidia_api_key=NVIDIA_KEY),
        _nvidia_stream_handler(seen),
        go_key=None,
        db_path=db,
        usage_path=str(tmp_path / "missing.jsonl"),
    )
    monkeypatch.setenv("NVIDIA_API_KEY", "nv-env-key-222")
    assert post_nvidia(client, seen) == f"Bearer {NVIDIA_KEY}"

    # 2. env wins over db (no configured key). _client_for delenvs NVIDIA_API_KEY,
    # so re-set it after building the client.
    seen = []
    client = _client_for(
        monkeypatch,
        _settings(nvidia_api_key=""),
        _nvidia_stream_handler(seen),
        go_key=None,
        db_path=db,
        usage_path=str(tmp_path / "missing.jsonl"),
    )
    monkeypatch.setenv("NVIDIA_API_KEY", "nv-env-key-222")
    assert post_nvidia(client, seen) == "Bearer nv-env-key-222"

    # 3. db only (no configured key, no env).
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    seen = []
    client = _client_for(
        monkeypatch,
        _settings(nvidia_api_key=""),
        _nvidia_stream_handler(seen),
        go_key=None,
        db_path=db,
        usage_path=str(tmp_path / "missing.jsonl"),
    )
    assert post_nvidia(client, seen) == "Bearer nv-db-key-111"


def test_nvidia_key_missing_bad_db_no_candidates(monkeypatch, tmp_path, caplog):
    """Bar 3: missing db / missing row / bad JSON => no Nvidia candidates, no crash, no key logged."""
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    seen: list[httpx.Request] = []

    def nvidia_handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        raise AssertionError("Nvidia must not be called without a key")

    def client_for_db(db_path):
        return _client_for(
            monkeypatch,
            _settings(nvidia_api_key=""),
            nvidia_handler,
            go_key=None,
            db_path=db_path,
            usage_path=str(tmp_path / "missing.jsonl"),
        )

    # 1. missing db.
    gw_module._go_key_cache.clear()
    client = client_for_db(str(tmp_path / "nope.db"))
    resp = client.post("/gw/v1/messages", json=_msg_body(model=NV_UPSTREAM), headers=AUTH)
    assert resp.status_code == 503
    assert resp.json()["error"]["message"] == "gateway: no NVIDIA_API_KEY"
    assert resp.headers["x-frood-route"] == "none"

    # 2. bad JSON value for the nvidia row.
    db = tmp_path / "opencode.db"
    conn = sqlite3.connect(db)
    try:
        conn.execute("CREATE TABLE credential (integration_id TEXT, active INTEGER, value TEXT)")
        conn.execute(
            "INSERT INTO credential (integration_id, active, value) VALUES (?, ?, ?)",
            ("nvidia", 1, "{not json"),
        )
        conn.commit()
    finally:
        conn.close()
    gw_module._go_key_cache.clear()
    client = client_for_db(db)
    resp = client.post("/gw/v1/messages", json=_msg_body(model=NV_UPSTREAM), headers=AUTH)
    assert resp.status_code == 503
    assert resp.headers["x-frood-route"] == "none"

    # 3. row present but key missing / non-str.
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "UPDATE credential SET value=? WHERE integration_id=?",
            (json.dumps({"other": 1}), "nvidia"),
        )
        conn.commit()
    finally:
        conn.close()
    gw_module._go_key_cache.clear()
    client = client_for_db(db)
    resp = client.post("/gw/v1/messages", json=_msg_body(model=NV_UPSTREAM), headers=AUTH)
    assert resp.status_code == 503
    assert resp.headers["x-frood-route"] == "none"

    assert seen == []
    for record in caplog.records:
        text = record.getMessage()
        try:
            args_text = str(record.args)
        except Exception:
            args_text = ""
        assert NVIDIA_KEY not in text and NVIDIA_KEY not in args_text


def test_models_lists_nvidia_lazily_from_db(monkeypatch, tmp_path):
    """Bar 4: /gw/v1/models lists Nvidia ids once the db key exists, no router rebuild."""
    seen: list[httpx.Request] = []
    db = tmp_path / "opencode.db"
    conn = sqlite3.connect(db)
    try:
        conn.execute("CREATE TABLE credential (integration_id TEXT, active INTEGER, value TEXT)")
        conn.commit()
    finally:
        conn.close()
    gw_module._go_key_cache.clear()
    client = _client_for(
        monkeypatch,
        _settings(nvidia_api_key=""),
        _nvidia_stream_handler(seen),
        go_key=None,
        db_path=db,
        usage_path=str(tmp_path / "missing.jsonl"),
    )
    ids = [m["id"] for m in client.get("/gw/v1/models", headers=AUTH).json()["data"]]
    assert NV_UPSTREAM not in ids and LITE_UPSTREAM not in ids and SUPER_UPSTREAM not in ids

    # Same router (no rebuild): add the row, clear the per-process cache, lazy
    # resolution picks it up on the next request.
    _write_nvidia_credential_db(db, "nv-db-key-111")
    gw_module._go_key_cache.clear()
    ids = [m["id"] for m in client.get("/gw/v1/models", headers=AUTH).json()["data"]]
    assert NV_UPSTREAM in ids and LITE_UPSTREAM in ids and SUPER_UPSTREAM in ids


# -- gw-t3 carry-overs (critic r2 / senior r2) ---------------------------------


def test_nvidia_read_error_502(monkeypatch, tmp_path):
    """(a) Nvidia aread() failure => 502 "upstream error body unreadable"."""
    seen: list[httpx.Request] = []

    async def _unreadable():
        raise httpx.ReadError("unreadable")
        yield b""  # pragma: no cover - makes content an async generator

    def nvidia_handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            500,
            headers={"content-type": "application/json"},
            content=_unreadable(),
        )

    client = _client_for(
        monkeypatch,
        _settings(),
        nvidia_handler,
        usage_path=str(tmp_path / "missing.jsonl"),
    )
    resp = client.post(
        "/gw/v1/messages", json=_msg_body(model=NV_UPSTREAM, stream=True), headers=AUTH
    )
    assert resp.status_code == 502
    assert "upstream error body unreadable" in resp.json()["error"]["message"]
    assert "integrate.api.nvidia.com" in resp.text
    assert resp.headers["x-frood-route"] == f"nvidia:{NV_UPSTREAM}"
    assert len(seen) == 1


def test_pre_route_refusals_carry_route_none(monkeypatch, tmp_path):
    """(b) claude 403, unknown 404, pace-over 429, no-key 503 => x-frood-route: none."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        raise AssertionError("no upstream may be called for a pre-route refusal")

    # claude 403.
    client = _client_for(
        monkeypatch,
        _settings(gateway_go_models="claude-sonnet-4-6," + GO_MODELS),
        handler,
    )
    resp = client.post("/gw/v1/messages", json=_msg_body(model="claude-sonnet-4-6"), headers=AUTH)
    assert resp.status_code == 403
    assert resp.headers["x-frood-route"] == "none"

    # unknown 404.
    client = _client_for(monkeypatch, _settings(), handler)
    resp = client.post("/gw/v1/messages", json=_msg_body(model="gpt-zzz"), headers=AUTH)
    assert resp.status_code == 404
    assert resp.headers["x-frood-route"] == "none"

    # pace-over 429 (no Nvidia key => no fallback).
    client = _client_for(
        monkeypatch,
        _settings(nvidia_api_key=""),
        handler,
        db_path=str(tmp_path / "nope-nvidia.db"),
        usage_path=_write_snapshot(tmp_path, weekly=_window(pct=95)),
    )
    resp = client.post("/gw/v1/messages", json=_msg_body(model="kimi-k3"), headers=AUTH)
    assert resp.status_code == 429
    assert resp.headers["x-frood-route"] == "none"

    # no-key 503 (nvidia id, no key anywhere).
    client = _client_for(
        monkeypatch,
        _settings(nvidia_api_key=""),
        handler,
        db_path=str(tmp_path / "nope-nvidia.db"),
    )
    resp = client.post("/gw/v1/messages", json=_msg_body(model=NV_UPSTREAM), headers=AUTH)
    assert resp.status_code == 503
    assert resp.headers["x-frood-route"] == "none"

    assert seen == []


def test_no_fallback_log_when_last_candidate_fails(monkeypatch, tmp_path, caplog):
    """(c) when the last (only) candidate fails, no "gateway fallback" INFO line is written."""
    go_seen: list[httpx.Request] = []

    def go_handler(request: httpx.Request) -> httpx.Response:
        go_seen.append(request)
        return httpx.Response(
            400,
            headers={"content-type": "application/json"},
            json={"type": "error", "error": {"type": "invalid_request_error", "message": "bad"}},
        )

    client = _client_for(
        monkeypatch,
        _settings(gateway_go_fallback=""),
        _split_handler(go_handler, _nvidia_stream_handler([])),
        usage_path=str(tmp_path / "missing.jsonl"),
    )
    with caplog.at_level(logging.INFO, logger="frood.gateway"):
        resp = client.post("/gw/v1/messages", json=_msg_body(model="kimi-k3"), headers=AUTH)
    assert resp.status_code == 400
    assert len(go_seen) == 1
    fallbacks = [r for r in caplog.records if "gateway fallback" in r.getMessage()]
    assert fallbacks == []
