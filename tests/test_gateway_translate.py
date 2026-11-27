"""Tests for dashboard.gateway_translate — Anthropic <-> OpenAI translation.

Pure-function tests: no network, no provider keys. Golden SSE fixtures live in
tests/fixtures/gateway/. Every stream golden is asserted both whole-feed and
7-byte-chunk feed with identical output.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from dashboard.gateway_translate import (
    StreamTranslator,
    anthropic_to_openai,
    openai_error_to_anthropic,
    openai_to_anthropic,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "gateway"

_MESSAGE_ID_RE = re.compile(r'"id":"msg_[a-f0-9]+"')


def _norm(s: str) -> str:
    """Normalize dynamic message/tool ids so golden files stay deterministic."""
    return _MESSAGE_ID_RE.sub('"id":"msg_NORM"', s)


def _load(name: str) -> str:
    return (FIXTURES / name).read_text()


def _eq(actual: bytes, golden_text: str) -> bool:
    """Compare SSE output to a golden text, normalizing ids and trailing newline."""
    return _norm(actual.decode("utf-8")).rstrip("\n") == _norm(golden_text).rstrip("\n")


def _feed_all(translator: StreamTranslator, data: bytes) -> bytes:
    out = b""
    for i in range(0, len(data), 7):
        out += translator.feed(data[i : i + 7])
    return out


def _stream_case(sse_name: str, golden_name: str) -> None:
    """Feed a fixture whole and in 7-byte chunks; both must equal the golden."""
    sse = _load(sse_name).encode("utf-8")
    golden = _load(golden_name)

    tr = StreamTranslator("test-model")
    whole = tr.feed(sse)
    assert _eq(whole, golden), (sse_name, "whole")

    tr2 = StreamTranslator("test-model")
    chunked = _feed_all(tr2, sse)
    assert _eq(chunked, golden), (sse_name, "chunked")
    assert _norm(whole.decode()) == _norm(chunked.decode()), (sse_name, "whole == chunked")


# ---------------------------------------------------------------------------
# anthropic_to_openai
# ---------------------------------------------------------------------------


def test_anthropic_to_openai_request_golden():
    """G1: Claude-Code-shaped body -> exact OpenAI body + exact warnings."""
    body = {
        "model": "claude-sonnet-4",
        "system": [
            {"type": "text", "text": "You are helpful", "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": "Be concise"},
        ],
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": "image/png", "data": "ABCDEF"},
                    },
                    {"type": "text", "text": "Look at this"},
                ],
            },
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "I'll use a tool"},
                    {
                        "type": "tool_use",
                        "id": "toolu_1",
                        "name": "get_weather",
                        "input": {"city": "NYC"},
                    },
                    {"type": "thinking", "thinking": "..."},
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_call_id": "toolu_1", "content": "It is sunny"},
                    {
                        "type": "tool_result",
                        "tool_call_id": "toolu_2",
                        "content": "error happened",
                        "is_error": True,
                    },
                    {"type": "text", "text": "Thanks"},
                ],
            },
        ],
        "tools": [
            {
                "name": "get_weather",
                "description": "Get weather",
                "input_schema": {"type": "object", "properties": {"city": {"type": "string"}}},
            },
            {"name": "web_search", "type": "web_search_2025"},
            {"name": "calc", "description": "Calculate", "input_schema": {"type": "object"}},
        ],
        "tool_choice": "any",
        "max_tokens": 1024,
        "temperature": 0.7,
        "top_p": 0.9,
        "stop_sequences": ["STOP"],
        "metadata": {"key": "value"},
    }
    expected = json.loads(_load("request_golden.json"))
    openai_body, warnings = anthropic_to_openai(body, "nvidia/nemotron")
    assert openai_body == expected
    assert warnings == [
        "cache_control_dropped",
        "thinking_dropped",
        "server_tool_dropped",
        "param_dropped:metadata",
    ]


def test_tool_result_ordering():
    """G2: [tool_result A, tool_result B, text] -> tool A, tool B, then user text."""
    body = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_call_id": "call_A", "content": "result A"},
                    {
                        "type": "tool_result",
                        "tool_call_id": "call_B",
                        "content": "error B",
                        "is_error": True,
                    },
                    {"type": "text", "text": "thanks"},
                ],
            }
        ],
    }
    openai_body, _ = anthropic_to_openai(body, "m")
    msgs = openai_body["messages"]
    assert msgs == [
        {"role": "tool", "tool_call_id": "call_A", "content": "result A"},
        {"role": "tool", "tool_call_id": "call_B", "content": "ERROR: error B"},
        {"role": "user", "content": "thanks"},
    ]


# ---------------------------------------------------------------------------
# StreamTranslator (golden stream tests)
# ---------------------------------------------------------------------------


def test_stream_text_only():
    """G3: text-only reply golden, whole and chunked."""
    _stream_case("stream_text_only.sse", "stream_text_only.golden")


def test_stream_text_then_one_tool():
    """G4: text then one tool call in 5 fragments -> text block, one tool_use block."""
    _stream_case("stream_tool.sse", "stream_tool.golden")


def test_stream_two_parallel_tools():
    """G5: two parallel tools interleaved (0,1,0,1) -> two tool_use blocks in index order."""
    _stream_case("stream_two_tools.sse", "stream_two_tools.golden")


def test_stream_midstream_error():
    """G6: mid-stream error -> open block closed, then error, nothing after."""
    sse = _load("stream_error.sse").encode("utf-8")
    golden = _load("stream_error.golden")
    tr = StreamTranslator("test-model")
    whole = tr.feed(sse)
    assert _eq(whole, golden)
    # Nothing after the error, even with more input.
    assert tr.feed(b"data: [DONE]\n\n") == b""


def test_stream_no_done():
    """G7: upstream ends without [DONE] -> finish() emits message_delta + message_stop."""
    sse = _load("stream_nodone.sse").encode("utf-8")
    golden = _load("stream_nodone.golden")
    tr = StreamTranslator("test-model")
    part = tr.feed(sse)
    closing = tr.finish()
    assert _eq(part + closing, golden)
    # finish() after completion is idempotent/no-op.
    assert tr.finish() == b""


def test_stream_ping():
    """G9: ping emitted when >=10s passed since last output; not at 1s."""
    ticks = {"t": 0.0}

    def clock():
        return ticks["t"]

    tr = StreamTranslator("test-model", clock=clock, ping_interval=10.0)
    tr.feed(b'data: {"x":1}\n\n')  # emits message_start, last_output = 0
    ticks["t"] = 11.0
    out = tr.feed(b"")
    assert b"event: ping" in out
    assert b'"type":"ping"' in out

    # Fresh translator, 1s gap -> no ping.
    ticks2 = {"t": 0.0}
    tr2 = StreamTranslator("test-model", clock=lambda: ticks2["t"], ping_interval=10.0)
    tr2.feed(b'data: {"x":1}\n\n')
    ticks2["t"] = 1.0
    assert b"ping" not in tr2.feed(b"")


# ---------------------------------------------------------------------------
# openai_to_anthropic (non-streaming)
# ---------------------------------------------------------------------------


def test_openai_to_anthropic_tool_calls():
    """G10: tool_calls response -> tool_use content, stop_reason tool_use, usage mapped."""
    resp = {
        "id": "cmpl_abc",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "hi",
                    "tool_calls": [
                        {"id": "call_1", "function": {"name": "fn", "arguments": '{"a":1}'}}
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 2, "completion_tokens": 3},
    }
    result = openai_to_anthropic(resp, "req")
    assert result["id"] == "msg_cmpl_abc"
    assert result["type"] == "message"
    assert result["role"] == "assistant"
    assert result["model"] == "req"
    assert result["content"] == [
        {"type": "text", "text": "hi"},
        {"type": "tool_use", "id": "call_1", "name": "fn", "input": {"a": 1}},
    ]
    assert result["stop_reason"] == "tool_use"
    assert result["stop_sequence"] is None
    assert result["usage"] == {"input_tokens": 2, "output_tokens": 3}


def test_openai_to_anthropic_bad_json_args():
    """G10: unparsable tool arguments -> {"_raw": ...}."""
    resp = {
        "id": "x",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "working",
                    "tool_calls": [
                        {"id": "call_2", "function": {"name": "fn", "arguments": "{not json"}}
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {},
    }
    result = openai_to_anthropic(resp, "req")
    tool = result["content"][1]
    assert tool["type"] == "tool_use"
    assert tool["input"] == {"_raw": "{not json"}


def test_openai_to_anthropic_empty_content_no_tools():
    """G10: null/empty content and no tool calls -> content: []."""
    resp = {"id": "x", "choices": [{"message": {"role": "assistant", "content": ""}}]}
    result = openai_to_anthropic(resp, "req")
    assert result["content"] == []


def test_openai_to_anthropic_finish_reason_map():
    cases = [
        ("stop", "end_turn"),
        ("length", "max_tokens"),
        ("tool_calls", "tool_use"),
        ("function_call", "tool_use"),
        ("content_filter", "refusal"),
        ("other", "end_turn"),
        (None, "end_turn"),
    ]
    for fr, expected in cases:
        resp = {
            "id": "x",
            "choices": [{"message": {"role": "assistant", "content": "t"}, "finish_reason": fr}],
        }
        assert openai_to_anthropic(resp, "m")["stop_reason"] == expected, fr


# ---------------------------------------------------------------------------
# openai_error_to_anthropic
# ---------------------------------------------------------------------------


def test_openai_error_to_anthropic_429():
    """G11: 429 -> rate_limit_error with upstream message."""
    err = openai_error_to_anthropic(429, b'{"error":{"message":"rate limited"}}')
    assert err == {
        "type": "error",
        "error": {"type": "rate_limit_error", "message": "rate limited"},
    }


def test_openai_error_to_anthropic_non_json_502():
    """G11: non-JSON 502 body -> api_error with (truncated) body as message."""
    err = openai_error_to_anthropic(502, b"not json {{{")
    assert err["error"]["type"] == "api_error"
    assert err["error"]["message"] == "not json {{{"


def test_openai_error_to_anthropic_status_map():
    cases = [
        (400, "invalid_request_error"),
        (401, "authentication_error"),
        (403, "permission_error"),
        (404, "not_found_error"),
        (500, "api_error"),
        (503, "api_error"),
    ]
    for status, etype in cases:
        err = openai_error_to_anthropic(status, b'{"error":{"message":"m"}}')
        assert err["error"]["type"] == etype, status


def test_openai_error_to_anthropic_truncation():
    long_body = b'{"error":{"message":"' + b"x" * 1000 + b'"}}'
    err = openai_error_to_anthropic(500, long_body)
    assert len(err["error"]["message"]) == 500


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
