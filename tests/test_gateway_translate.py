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


def _stream_case(sse_name: str, golden_name: str, finish: bool = False) -> None:
    """Feed a fixture whole and in 7-byte chunks; both must equal the golden.

    When ``finish`` is True, ``finish()`` is called after the feed so closing
    events (e.g. for an upstream that ends without ``[DONE]``) are included.
    """
    sse = _load(sse_name).encode("utf-8")
    golden = _load(golden_name)

    tr = StreamTranslator("test-model")
    whole = tr.feed(sse)
    if finish:
        whole = whole + tr.finish()
    assert _eq(whole, golden), (sse_name, "whole")

    tr2 = StreamTranslator("test-model")
    chunked = _feed_all(tr2, sse)
    if finish:
        chunked = chunked + tr2.finish()
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
                    {"type": "tool_result", "tool_use_id": "toolu_1", "content": "It is sunny"},
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_2",
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


def test_disable_parallel_tool_use():
    """#1: tool_choice dict with disable_parallel_tool_use -> parallel_tool_calls: false."""
    body = {
        "messages": [{"role": "user", "content": "hi"}],
        "tools": [
            {
                "name": "fn",
                "description": "d",
                "input_schema": {"type": "object"},
            }
        ],
        "tool_choice": {"type": "tool", "name": "fn", "disable_parallel_tool_use": True},
    }
    openai_body, warnings = anthropic_to_openai(body, "m")
    assert openai_body["parallel_tool_calls"] is False
    assert openai_body["tool_choice"] == {"type": "function", "function": {"name": "fn"}}


def test_tool_choice_dict_forms():
    """#2: dict tool_choice forms auto/any/none/tool map correctly."""
    cases = [
        ({"type": "auto"}, "auto"),
        ({"type": "any"}, "required"),
        ({"type": "none"}, "none"),
        ({"type": "tool", "name": "fn"}, {"type": "function", "function": {"name": "fn"}}),
    ]
    for tc, expected in cases:
        body = {
            "messages": [{"role": "user", "content": "hi"}],
            "tools": [{"name": "fn", "description": "d", "input_schema": {"type": "object"}}],
            "tool_choice": tc,
        }
        openai_body, _ = anthropic_to_openai(body, "m")
        assert openai_body["tool_choice"] == expected, tc


def test_unknown_param_warning():
    """#7: any unknown request key is dropped with param_dropped:<key>."""
    body = {
        "messages": [{"role": "user", "content": "hi"}],
        "foo": 1,
        "bar": {"x": 2},
    }
    _, warnings = anthropic_to_openai(body, "m")
    assert "param_dropped:foo" in warnings
    assert "param_dropped:bar" in warnings


def test_stream_false_copied():
    """#8: stream: false is copied into the OpenAI body."""
    body = {"messages": [{"role": "user", "content": "hi"}], "stream": False}
    openai_body, _ = anthropic_to_openai(body, "m")
    assert openai_body["stream"] is False
    assert "stream_options" not in openai_body


def test_block_dropped_warning():
    """#4: unknown request block types are dropped with block_dropped:<type>."""
    body = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "document", "source": {"type": "base64", "data": "x"}},
                    {"type": "search_result", "text": "s"},
                    {"type": "text", "text": "hello"},
                ],
            }
        ],
    }
    _, warnings = anthropic_to_openai(body, "m")
    assert "block_dropped:document" in warnings
    assert "block_dropped:search_result" in warnings


def test_cache_control_dropped_in_tools():
    """#10: cache_control inside a tools[] entry warns cache_control_dropped once."""
    body = {
        "messages": [{"role": "user", "content": "hi"}],
        "tools": [
            {
                "name": "fn",
                "description": "d",
                "input_schema": {"type": "object"},
                "cache_control": {"type": "ephemeral"},
            }
        ],
    }
    openai_body, warnings = anthropic_to_openai(body, "m")
    assert "cache_control_dropped" in warnings
    # The tool still has input_schema so it is kept.
    assert len(openai_body["tools"]) == 1


def test_orphan_tool_use():
    """#2: assistant tool_use with no tool_result in next user message -> synthetic tool + warning."""
    body = {
        "messages": [
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "I'll call a tool"},
                    {"type": "tool_use", "id": "toolu_x", "name": "fn", "input": {}},
                ],
            },
            {"role": "user", "content": "next turn"},
        ],
    }
    openai_body, warnings = anthropic_to_openai(body, "m")
    msgs = openai_body["messages"]
    assert msgs == [
        {
            "role": "assistant",
            "content": "I'll call a tool",
            "tool_calls": [
                {
                    "id": "toolu_x",
                    "type": "function",
                    "function": {"name": "fn", "arguments": "{}"},
                },
            ],
        },
        {"role": "tool", "tool_call_id": "toolu_x", "content": "[no result: interrupted]"},
        {"role": "user", "content": "next turn"},
    ]
    assert "orphan_tool_use" in warnings


def test_tool_result_ordering():
    """G2: [tool_result A, tool_result B, text] -> tool A, tool B, then user text."""
    body = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "call_A", "content": "result A"},
                    {
                        "type": "tool_result",
                        "tool_use_id": "call_B",
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


def test_tool_result_tool_use_id_and_tool_call_id():
    """#1: tool_result accepts both tool_use_id (Anthropic) and tool_call_id (OpenAI) spellings."""
    body = {
        "messages": [
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "calling"},
                    {"type": "tool_use", "id": "toolu_A", "name": "fn", "input": {}},
                    {"type": "tool_use", "id": "toolu_B", "name": "fn", "input": {}},
                ],
            },
            {
                "role": "user",
                "content": [
                    # first result uses Anthropic's real field name
                    {"type": "tool_result", "tool_use_id": "toolu_A", "content": "A ok"},
                    # second uses the OpenAI-shaped output field name (accepted as input)
                    {"type": "tool_result", "tool_call_id": "toolu_B", "content": "B ok"},
                ],
            },
        ],
    }
    openai_body, warnings = anthropic_to_openai(body, "m")
    msgs = openai_body["messages"]
    # No orphan synthetic results: both tool_use ids matched a tool_result.
    tool_msgs = [m for m in msgs if m["role"] == "tool"]
    assert tool_msgs == [
        {"role": "tool", "tool_call_id": "toolu_A", "content": "A ok"},
        {"role": "tool", "tool_call_id": "toolu_B", "content": "B ok"},
    ]
    assert "orphan_tool_use" not in warnings


def test_assistant_string_content_preserved():
    """Round-3 #1: assistant with string content round-trips; text is not blanked."""
    body = {
        "messages": [
            {"role": "user", "content": "What is the weather?"},
            {"role": "assistant", "content": "It is sunny in NYC."},
            {"role": "user", "content": "And tomorrow?"},
        ],
    }
    openai_body, warnings = anthropic_to_openai(body, "m")
    assert openai_body["messages"] == [
        {"role": "user", "content": "What is the weather?"},
        {"role": "assistant", "content": "It is sunny in NYC."},
        {"role": "user", "content": "And tomorrow?"},
    ]
    assert warnings == []


def test_tool_choice_emitted_only_when_set_or_tools():
    """Round-3 #2: no tool_choice and no tools => tool_choice key absent."""
    body = {"messages": [{"role": "user", "content": "hi"}]}
    openai_body, _ = anthropic_to_openai(body, "m")
    assert "tool_choice" not in openai_body
    assert "tools" not in openai_body


def test_tool_result_image_dropped():
    """Round-3 #3a: tool_result containing an image => "[image omitted]" + tool_result_image_dropped."""
    body = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "t1",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": "X",
                                },
                            },
                            {"type": "text", "text": "here"},
                        ],
                    },
                ],
            }
        ],
    }
    openai_body, warnings = anthropic_to_openai(body, "m")
    tool = openai_body["messages"][0]
    assert tool["content"] == "[image omitted]\n\nhere"
    assert "tool_result_image_dropped" in warnings


def test_tool_result_empty_content():
    """Round-3 #3b: empty tool_result content => content: ""."""
    body = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "t1", "content": ""},
                ],
            }
        ],
    }
    openai_body, _ = anthropic_to_openai(body, "m")
    assert openai_body["messages"] == [
        {"role": "tool", "tool_call_id": "t1", "content": ""},
    ]


def test_streamed_tool_call_no_id():
    """Round-3 #3c: streamed tool call with no id => toolu_<uuid hex>."""
    chunk = {
        "id": "cmpl_1",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": "m",
        "choices": [
            {
                "index": 0,
                "delta": {
                    "tool_calls": [
                        {
                            "index": 0,
                            "type": "function",
                            "function": {"name": "fn", "arguments": "{}"},
                        }
                    ]
                },
            }
        ],
    }
    sse = ("data: " + json.dumps(chunk, separators=(",", ":")) + "\n\n").encode("utf-8")
    tr = StreamTranslator("test-model", clock=lambda: 0.0)
    out = tr.feed(sse) + tr.finish()
    # The tool_use block must carry a generated toolu_ id (never empty).
    assert b"event: content_block_start" in out
    assert b'"type":"tool_use"' in out
    assert b'"id":"toolu_' in out
    assert b'"id":""' not in out


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
    """G6: mid-stream error -> open block closed, then error, nothing after.

    The error case is fed whole, in 7-byte chunks, and with a trailing data
    line in the same fixture/feed (nothing may be emitted after the error
    event).
    """
    _stream_case("stream_error.sse", "stream_error.golden")
    # Trailing data in a separate feed after the error must produce nothing.
    tr = StreamTranslator("test-model")
    tr.feed(_load("stream_error.sse").encode("utf-8"))
    assert tr.feed(b'data: {"choices":[{"delta":{"content":"AFTER"}}]}\n\n') == b""


def test_stream_no_done():
    """G7: upstream ends without [DONE] -> finish() emits message_delta + message_stop."""
    _stream_case("stream_nodone.sse", "stream_nodone.golden", finish=True)
    tr = StreamTranslator("test-model")
    sse = _load("stream_nodone.sse").encode("utf-8")
    out = tr.feed(sse) + tr.finish()
    assert _eq(out, _load("stream_nodone.golden"))
    # A second finish() on the same translator is a no-op (already finished).
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


def test_openai_to_anthropic_empty_args_becomes_dict():
    """G3 finding: empty/whitespace-only tool arguments -> {}, not {"_raw": ...}."""
    resp = {
        "id": "x",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "t",
                    "tool_calls": [
                        {"id": "c1", "function": {"name": "fn", "arguments": ""}},
                        {"id": "c2", "function": {"name": "fn2", "arguments": "   "}},
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {},
    }
    result = openai_to_anthropic(resp, "req")
    inputs = [b["input"] for b in result["content"] if b["type"] == "tool_use"]
    assert inputs == [{}, {}]


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


def test_openai_error_to_anthropic_missing_message():
    """G6 finding: error object without message falls back to the raw body."""
    err = openai_error_to_anthropic(500, b'{"error":{"type":"x"}}')
    assert err["error"]["type"] == "api_error"
    assert err["error"]["message"] == '{"error":{"type":"x"}}'


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


# ---------------------------------------------------------------------------
# gw-t3 carry-over (d): finish()/error() with an empty feed
# ---------------------------------------------------------------------------


def test_finish_before_feed_emits_message_start():
    """GW-T3-d: finish() with no feed still opens with message_start."""
    out = StreamTranslator("m").finish()
    assert out.startswith(b"event: message_start")
    assert b"event: message_stop" in out


def test_error_before_feed_emits_message_start():
    """GW-T3-d: error() with no feed still opens with message_start."""
    out = StreamTranslator("m").error("x")
    assert out.startswith(b"event: message_start")
    assert b"event: error" in out


def test_error_after_finish_emits_nothing():
    """GW-T3-d: error() after finish() emits nothing (stream already closed)."""
    tr = StreamTranslator("m")
    tr.feed(b'data: {"choices": []}\n\n')
    assert b"event: message_stop" in tr.finish()
    assert tr.error("late") == b""


def test_crlf_comment_matches_lf():
    """GW-T3-d: CRLF-terminated SSE with a : comment line translates like LF."""
    payload = {
        "id": "a",
        "choices": [{"index": 0, "delta": {"content": "Hi"}, "finish_reason": None}],
    }
    lf = ("data: " + json.dumps(payload) + "\n\n").encode() + b"data: [DONE]\n\n"
    crlf = b": keep-alive\r\n" + lf.replace(b"\n", b"\r\n")
    tr_lf = StreamTranslator("m")
    out_lf = tr_lf.feed(lf) + tr_lf.finish()
    tr_crlf = StreamTranslator("m")
    out_crlf = tr_crlf.feed(crlf) + tr_crlf.finish()
    assert _norm(out_crlf.decode()) == _norm(out_lf.decode())


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
