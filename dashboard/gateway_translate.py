"""Pure translation functions between Anthropic Messages and OpenAI Chat Completions.

No I/O, no logging of message content, stdlib only. Used by the gateway to route
Claude Code tiers to Nvidia (OpenAI-shaped). Nothing in this ticket calls it;
T3 wires it into ``dashboard/gateway.py``.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any


def _drop_once(warnings: list[str], code: str) -> None:
    """Append ``code`` to warnings only if not already present (cache_control etc.)."""
    if code not in warnings:
        warnings.append(code)


def _join_text_blocks(blocks: list[dict[str, Any]]) -> str:
    """Join consecutive text blocks with ``\\n\\n``."""
    parts: list[str] = []
    for b in blocks:
        if b.get("type") == "text":
            parts.append(b.get("text", ""))
    return "\n\n".join(parts)


def _extract_text_content(content: Any) -> str:
    """Return the joined text of a string or block-list content value."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return _join_text_blocks(content)
    return ""


def _content_has_image(blocks: list[dict[str, Any]]) -> bool:
    return any(b.get("type") == "image" for b in blocks)


def _openai_image_url_part(block: dict[str, Any]) -> dict[str, Any]:
    """Convert an Anthropic image block to an OpenAI ``image_url`` part."""
    source = block.get("source", {})
    stype = source.get("type")
    if stype == "base64":
        media_type = source.get("media_type", "image/jpeg")
        data = source.get("data", "")
        url = f"data:{media_type};base64,{data}"
    elif stype == "url":
        url = source.get("url", "")
    else:
        url = ""
    return {"type": "image_url", "image_url": {"url": url}}


def _tool_result_call_ids(content: Any) -> set[str]:
    """tool_call_id values from ``tool_result`` blocks in a user message content."""
    ids: set[str] = set()
    if isinstance(content, list):
        for b in content:
            if isinstance(b, dict) and b.get("type") == "tool_result":
                tid = b.get("tool_call_id")
                if tid:
                    ids.add(tid)
    return ids


def anthropic_to_openai(
    body: dict[str, Any], upstream_model: str
) -> tuple[dict[str, Any], list[str]]:
    """Convert an Anthropic Messages request body to OpenAI Chat Completions.

    Returns ``(openai_body, warnings)``. Pure: no I/O, no logging of content.
    """
    warnings: list[str] = []

    # --- system message ---
    system_raw = body.get("system")
    system_text = ""
    if isinstance(system_raw, str):
        system_text = system_raw
    elif isinstance(system_raw, list):
        # Drop cache_control blocks inside system, warn once.
        text_blocks = []
        for b in system_raw:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "text":
                text_blocks.append(b.get("text", ""))
            if b.get("cache_control"):
                _drop_once(warnings, "cache_control_dropped")
        system_text = "\n\n".join(t for t in text_blocks if t)

    openai_messages: list[dict[str, Any]] = []

    if system_text:
        openai_messages.append({"role": "system", "content": system_text})

    # --- messages ---
    messages = body.get("messages", []) or []
    for i, msg in enumerate(messages):
        role = msg.get("role")
        content = msg.get("content")

        if role == "assistant":
            oai_msg: dict[str, Any] = {"role": "assistant"}
            text_parts: list[str] = []
            tool_calls: list[dict[str, Any]] = []
            has_image = False

            if isinstance(content, list):
                for b in content:
                    if not isinstance(b, dict):
                        continue
                    btype = b.get("type")
                    if btype == "text":
                        text_parts.append(b.get("text", ""))
                    elif btype == "image":
                        has_image = True
                    elif btype == "thinking" or btype == "redacted_thinking":
                        _drop_once(warnings, "thinking_dropped")
                    elif btype == "tool_use":
                        tool_calls.append(
                            {
                                "id": b.get("id", ""),
                                "type": "function",
                                "function": {
                                    "name": b.get("name", ""),
                                    "arguments": json.dumps(b.get("input", {})),
                                },
                            }
                        )
                    else:
                        bt = b.get("type")
                        if isinstance(bt, str):
                            _drop_once(warnings, f"block_dropped:{bt}")
                    if b.get("cache_control"):
                        _drop_once(warnings, "cache_control_dropped")

            if tool_calls:
                oai_msg["tool_calls"] = tool_calls
                if text_parts:
                    oai_msg["content"] = "\n\n".join(text_parts)
                else:
                    oai_msg["content"] = None
            else:
                if has_image:
                    # Build content parts: text + image_url parts.
                    parts: list[dict[str, Any]] = []
                    if isinstance(content, list):
                        for b in content:
                            if not isinstance(b, dict):
                                continue
                            btype = b.get("type")
                            if btype == "text":
                                parts.append({"type": "text", "text": b.get("text", "")})
                            elif btype == "image":
                                parts.append(_openai_image_url_part(b))
                    oai_msg["content"] = parts
                else:
                    oai_msg["content"] = "\n\n".join(text_parts) if text_parts else ""

            openai_messages.append(oai_msg)

            # Orphaned tool_use: an assistant tool_call id with no matching
            # tool_result in the next user message gets a synthetic tool
            # message right after the assistant message, plus a warning.
            if tool_calls:
                result_ids: set[str] = set()
                if i + 1 < len(messages):
                    nxt = messages[i + 1]
                    if nxt.get("role") == "user":
                        result_ids = _tool_result_call_ids(nxt.get("content"))
                for tc in tool_calls:
                    tc_id = tc.get("id", "")
                    if tc_id and tc_id not in result_ids:
                        openai_messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc_id,
                                "content": "[no result: interrupted]",
                            }
                        )
                        _drop_once(warnings, "orphan_tool_use")

        elif role == "user":
            if isinstance(content, list):
                # Emit tool_results first (as separate tool messages), then remaining text.
                parts: list[dict[str, Any]] = []
                text_only_parts: list[str] = []
                has_image = False
                for b in content:
                    if not isinstance(b, dict):
                        continue
                    btype = b.get("type")
                    if btype == "tool_result":
                        tr_content = b.get("content", "")
                        tr_text: str
                        if isinstance(tr_content, str):
                            tr_text = tr_content
                        elif isinstance(tr_content, list):
                            joined = _join_text_blocks(tr_content)
                            if _content_has_image(tr_content):
                                joined = "[image omitted]" + (("\n\n" + joined) if joined else "")
                                _drop_once(warnings, "tool_result_image_dropped")
                            tr_text = joined
                        else:
                            tr_text = str(tr_content)
                        if b.get("is_error"):
                            tr_text = "ERROR: " + tr_text
                        openai_messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": b.get("tool_call_id", ""),
                                "content": tr_text,
                            }
                        )
                    elif btype == "text":
                        t = b.get("text", "")
                        text_only_parts.append(t)
                        parts.append({"type": "text", "text": t})
                    elif btype == "image":
                        has_image = True
                        parts.append(_openai_image_url_part(b))
                    elif btype == "thinking" or btype == "redacted_thinking":
                        _drop_once(warnings, "thinking_dropped")
                    else:
                        bt = b.get("type")
                        if isinstance(bt, str):
                            _drop_once(warnings, f"block_dropped:{bt}")
                    if b.get("cache_control"):
                        _drop_once(warnings, "cache_control_dropped")

                if has_image:
                    openai_messages.append({"role": "user", "content": parts})
                elif parts:
                    openai_messages.append(
                        {"role": "user", "content": "\n\n".join(text_only_parts)}
                    )
            else:
                openai_messages.append(
                    {"role": "user", "content": content if isinstance(content, str) else ""}
                )

        elif role == "tool":
            openai_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": msg.get("tool_call_id", ""),
                    "content": content if isinstance(content, str) else "",
                }
            )

    # --- tools ---
    openai_tools: list[dict[str, Any]] = []
    for t in body.get("tools", []) or []:
        if not t.get("input_schema"):
            _drop_once(warnings, "server_tool_dropped")
            continue
        if isinstance(t, dict) and t.get("cache_control"):
            _drop_once(warnings, "cache_control_dropped")
        openai_tools.append(
            {
                "type": "function",
                "function": {
                    "name": t.get("name", ""),
                    "description": t.get("description", ""),
                    "parameters": t.get("input_schema", {}),
                },
            }
        )

    oai_body_tools = openai_tools or None

    # --- tool_choice ---
    tool_choice = body.get("tool_choice")
    oai_tool_choice: Any = "auto"
    if tool_choice == "auto":
        oai_tool_choice = "auto"
    elif tool_choice == "any":
        oai_tool_choice = "required"
    elif tool_choice == "none":
        oai_tool_choice = "none"
    elif isinstance(tool_choice, dict) and tool_choice.get("type") == "tool":
        oai_tool_choice = {
            "type": "function",
            "function": {"name": tool_choice.get("name", "")},
        }

    # --- parameters ---
    openai_body: dict[str, Any] = {}
    openai_body["model"] = upstream_model
    openai_body["messages"] = openai_messages
    if oai_body_tools is not None:
        openai_body["tools"] = oai_body_tools
    openai_body["tool_choice"] = oai_tool_choice

    if isinstance(tool_choice, dict) and tool_choice.get("disable_parallel_tool_use"):
        openai_body["parallel_tool_calls"] = False

    if body.get("max_tokens") is not None:
        openai_body["max_tokens"] = body.get("max_tokens")
    if body.get("temperature") is not None:
        openai_body["temperature"] = body.get("temperature")
    if body.get("top_p") is not None:
        openai_body["top_p"] = body.get("top_p")
    if body.get("stop_sequences") is not None:
        openai_body["stop"] = body.get("stop_sequences")
    if "stream" in body:
        openai_body["stream"] = bool(body.get("stream"))
        if body.get("stream"):
            openai_body["stream_options"] = {"include_usage": True}

    # Consumed request keys; anything else present is dropped with a warning.
    _CONSUMED_KEYS = {
        "model",
        "system",
        "messages",
        "tools",
        "tool_choice",
        "max_tokens",
        "temperature",
        "top_p",
        "stop_sequences",
        "stream",
    }
    for key in body:
        if key not in _CONSUMED_KEYS:
            _drop_once(warnings, f"param_dropped:{key}")

    return openai_body, warnings


def _safe_json_loads(s: str) -> Any:
    """Parse JSON; return None on failure."""
    try:
        return json.loads(s)
    except (ValueError, TypeError):
        return None


def openai_to_anthropic(resp: dict[str, Any], requested_model: str) -> dict[str, Any]:
    """Convert a non-streaming OpenAI Chat Completions response to an Anthropic message.

    Pure: no I/O, no logging of content.
    """
    oai_id = resp.get("id") or uuid.uuid4().hex
    anthropic_id = f"msg_{oai_id}"

    choices = resp.get("choices") or []
    choice = choices[0] if choices else {}
    message = choice.get("message") or {}

    content_blocks: list[dict[str, Any]] = []
    text = message.get("content") or ""
    if isinstance(text, str) and text:
        content_blocks.append({"type": "text", "text": text})

    stop_reason = _map_finish_reason(choice.get("finish_reason"))

    tool_calls = message.get("tool_calls") or []
    if tool_calls:
        for tc in tool_calls:
            fn = tc.get("function") or {}
            args_raw = fn.get("arguments", "")
            # Empty or whitespace-only arguments ⇒ {} (non-streaming too), not _raw.
            if isinstance(args_raw, str) and not args_raw.strip():
                args = {}
            elif isinstance(args_raw, str):
                parsed = _safe_json_loads(args_raw)
                args = {"_raw": args_raw} if parsed is None else parsed
            elif isinstance(args_raw, dict):
                args = args_raw
            else:
                args = {"_raw": str(args_raw)}
            content_blocks.append(
                {
                    "type": "tool_use",
                    "id": tc.get("id") or f"toolu_{uuid.uuid4().hex}",
                    "name": fn.get("name", ""),
                    "input": args,
                }
            )

    # If nothing was emitted (empty content, no tools), content is [].
    if not content_blocks:
        content_blocks = []

    usage = resp.get("usage") or {}
    input_tokens = usage.get("prompt_tokens") or 0
    output_tokens = usage.get("completion_tokens") or 0

    return {
        "id": anthropic_id,
        "type": "message",
        "role": "assistant",
        "model": requested_model,
        "content": content_blocks,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        },
    }


def _map_finish_reason(fr: Any) -> str:
    """Map OpenAI finish_reason to Anthropic stop_reason."""
    if fr == "stop":
        return "end_turn"
    if fr == "length":
        return "max_tokens"
    if fr in ("tool_calls", "function_call"):
        return "tool_use"
    if fr == "content_filter":
        return "refusal"
    return "end_turn"


def openai_error_to_anthropic(status: int, body: bytes) -> dict[str, Any]:
    """Map an OpenAI-style error body to the Anthropic error shape."""
    message: str
    try:
        data = json.loads(body)
        err = data.get("error") if isinstance(data, dict) else None
        if isinstance(err, dict):
            message = err.get("message") or ""
        elif isinstance(err, str):
            message = err
        else:
            message = body.decode("utf-8", "replace")
        # error.message missing or empty ⇒ fall back to the raw body.
        if not message:
            message = body.decode("utf-8", "replace")
    except (ValueError, UnicodeDecodeError):
        message = body.decode("utf-8", "replace")

    message = message[:500]

    if status == 400:
        etype = "invalid_request_error"
    elif status == 401:
        etype = "authentication_error"
    elif status == 403:
        etype = "permission_error"
    elif status == 404:
        etype = "not_found_error"
    elif status == 429:
        etype = "rate_limit_error"
    elif 500 <= status < 600:
        etype = "api_error"
    else:
        etype = "api_error"

    return {
        "type": "error",
        "error": {
            "type": etype,
            "message": message,
        },
    }


def _compact(data: Any) -> str:
    return json.dumps(data, separators=(",", ":"))


class StreamTranslator:
    """Incremental OpenAI SSE ⇒ Anthropic SSE translation.

    Pure: no I/O, no logging of content. The clock is injectable for tests.
    """

    PING_INTERVAL = 10.0

    def __init__(
        self,
        requested_model: str,
        clock: Any = None,
        ping_interval: float = PING_INTERVAL,
    ) -> None:
        self.requested_model = requested_model
        self._clock = clock or time.monotonic
        self._ping_interval = ping_interval
        self._message_id = f"msg_{uuid.uuid4().hex}"

        self._out: list[bytes] = []
        self._buf = b""
        self._started = False
        self._finished = False
        self._errored = False
        self._last_output: float | None = None

        self._text_open = False
        self._text_emitted = False
        self._tools: dict[int, dict[str, Any]] = {}
        self._stop_reason: str | None = None
        self._usage: dict[str, int] = {"input_tokens": 0, "output_tokens": 0}

    # -- public API -----------------------------------------------------

    def feed(self, chunk: bytes) -> bytes:
        """Feed upstream SSE bytes; return Anthropic SSE bytes produced so far."""
        self._out = []
        if self._errored or self._finished:
            return b""

        now = self._clock()
        if self._last_output is not None and now - self._last_output >= self._ping_interval:
            self._emit_ping()

        if not self._started:
            self._emit_message_start()

        self._buf += chunk
        lines = self._buf.split(b"\n")
        self._buf = lines.pop()
        for line in lines:
            self._process_line(line)
        return b"".join(self._out)

    def finish(self) -> bytes:
        """Flush and emit closing events if upstream ended without [DONE]."""
        self._out = []
        if self._errored:
            return b""
        self._finish_stream()
        return b"".join(self._out)

    def error(self, message: str) -> bytes:
        """Close any open block and emit an error event; nothing after it."""
        self._out = []
        if self._errored:
            return b"".join(self._out)
        if self._text_open:
            self._emit_cb_stop(0)
            self._text_open = False
        self._errored = True
        self._emit("error", {"type": "error", "error": {"type": "api_error", "message": message}})
        return b"".join(self._out)

    # -- SSE line processing -------------------------------------------

    def _process_line(self, line: bytes) -> None:
        if self._errored:
            return  # nothing after an error, even within one feed() call
        text = line.decode("utf-8", "replace").rstrip("\r")
        if not text:
            return
        if text.startswith(":"):
            return  # comment line
        if text.startswith("event:"):
            return  # event type not needed; we key off data:
        if not text.startswith("data:"):
            return
        payload = text[5:]
        if payload.startswith(" "):
            payload = payload[1:]
        if payload.strip() == "[DONE]":
            self._finish_stream()
            return
        try:
            data = json.loads(payload)
        except ValueError:
            return
        if isinstance(data, dict) and "error" in data:
            err = data.get("error")
            msg = err.get("message") if isinstance(err, dict) else str(err)
            self._handle_error(msg or "")
            return
        self._process_chunk(data)

    def _process_chunk(self, data: dict[str, Any]) -> None:
        if self._errored:
            return
        usage = data.get("usage")
        if isinstance(usage, dict):
            self._usage["input_tokens"] = usage.get("prompt_tokens") or 0
            self._usage["output_tokens"] = usage.get("completion_tokens") or 0
        for choice in data.get("choices") or []:
            delta = choice.get("delta") or {}
            fr = choice.get("finish_reason")
            if fr is not None:
                self._stop_reason = _map_finish_reason(fr)
            content = delta.get("content")
            if isinstance(content, str) and content:
                self._emit_text_delta(content)
            for tc in delta.get("tool_calls") or []:
                self._buffer_tool_call(tc)

    def _buffer_tool_call(self, tc: dict[str, Any]) -> None:
        idx = tc.get("index", 0)
        entry = self._tools.setdefault(idx, {"id": None, "name": "", "args": []})
        if tc.get("id") and entry["id"] is None:
            entry["id"] = tc["id"]
        fn = tc.get("function") or {}
        if fn.get("name") and not entry["name"]:
            entry["name"] = fn["name"]
        arg = fn.get("arguments")
        if isinstance(arg, str) and arg:
            entry["args"].append(arg)

    def _handle_error(self, message: str) -> None:
        if self._text_open:
            self._emit_cb_stop(0)
            self._text_open = False
        self._errored = True
        self._emit("error", {"type": "error", "error": {"type": "api_error", "message": message}})

    # -- emission -------------------------------------------------------

    def _finish_stream(self) -> None:
        if self._finished or self._errored:
            return
        self._finished = True

        if self._text_open:
            self._emit_cb_stop(0)
            self._text_open = False

        block_index = 1 if self._text_emitted else 0
        for idx in sorted(self._tools.keys()):
            entry = self._tools[idx]
            tid = entry["id"] or f"toolu_{uuid.uuid4().hex}"
            name = entry["name"] or ""
            args = "".join(entry["args"])
            if not args or not args.strip():
                args = "{}"
            self._emit_cb_start_tool(block_index, tid, name)
            self._emit_cb_delta_tool(block_index, args)
            self._emit_cb_stop(block_index)
            block_index += 1

        self._emit(
            "message_delta",
            {
                "delta": {
                    "stop_reason": self._stop_reason or "end_turn",
                    "stop_sequence": None,
                },
                "usage": {
                    "input_tokens": self._usage["input_tokens"],
                    "output_tokens": self._usage["output_tokens"],
                },
            },
        )
        self._emit("message_stop", {})

    def _emit_text_delta(self, text: str) -> None:
        if not self._text_open:
            self._emit_cb_start_text(0)
            self._text_open = True
            self._text_emitted = True
        self._emit_cb_delta_text(0, text)

    def _emit_ping(self) -> None:
        self._emit("ping", {"type": "ping"})

    def _emit_message_start(self) -> None:
        self._emit(
            "message_start",
            {
                "message": {
                    "id": self._message_id,
                    "type": "message",
                    "role": "assistant",
                    "model": self.requested_model,
                    "content": [],
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": 0, "output_tokens": 0},
                }
            },
        )
        self._started = True

    def _emit_cb_start_text(self, index: int) -> None:
        self._emit(
            "content_block_start",
            {"index": index, "content_block": {"type": "text", "text": ""}},
        )

    def _emit_cb_delta_text(self, index: int, text: str) -> None:
        self._emit(
            "content_block_delta",
            {"index": index, "delta": {"type": "text_delta", "text": text}},
        )

    def _emit_cb_stop(self, index: int) -> None:
        self._emit("content_block_stop", {"index": index})

    def _emit_cb_start_tool(self, index: int, tid: str, name: str) -> None:
        self._emit(
            "content_block_start",
            {
                "index": index,
                "content_block": {
                    "type": "tool_use",
                    "id": tid,
                    "name": name,
                    "input": {},
                },
            },
        )

    def _emit_cb_delta_tool(self, index: int, partial_json: str) -> None:
        self._emit(
            "content_block_delta",
            {"index": index, "delta": {"type": "input_json_delta", "partial_json": partial_json}},
        )

    def _emit(self, event_type: str, data: Any) -> None:
        self._out.append(self._encode_event(event_type, data))
        self._last_output = self._clock()

    def _encode_event(self, event_type: str, data: Any) -> bytes:
        return f"event: {event_type}\ndata: {_compact(data)}\n\n".encode()
