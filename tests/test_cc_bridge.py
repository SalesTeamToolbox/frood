"""Tests for /ws/cc-chat WebSocket bridge and CC session management.

Strategy:
- TestCCBridgeRouting / TestMultiTurn / TestFallback / TestAuthStatus:
  source inspection via inspect.getsource() — no subprocess spawning needed.
  Pattern: identical to tests/test_websocket_terminal.py.
- TestNDJSONParser: pure-function unit tests against the _parse_cc_event()
  helper that will be extracted in Plan 02. Uses cc_stream_sample.ndjson fixture.
- TestSessionRegistry: async file I/O tests using tmp_path fixture.
"""

import inspect
import json
from pathlib import Path

import pytest

import dashboard.server as _srv_mod

# ---------------------------------------------------------------------------
# Fixture: NDJSON sample lines
# ---------------------------------------------------------------------------
FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_ndjson_fixture(name: str) -> list[dict]:
    path = FIXTURES_DIR / name
    lines = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                lines.append(json.loads(line))
    return lines


# ---------------------------------------------------------------------------
# TestCCBridgeRouting — source inspection
# ---------------------------------------------------------------------------
class TestCCBridgeRouting:
    @classmethod
    def _src(cls) -> str:
        return inspect.getsource(_srv_mod)

    def test_ws_endpoint_defined(self):
        assert '"/ws/cc-chat"' in self._src() or "'/ws/cc-chat'" in self._src(), (
            "server.py must define /ws/cc-chat WebSocket endpoint"
        )

    def test_subprocess_args_contain_stream_json(self):
        src = self._src()
        assert "stream-json" in src, "CC subprocess args must include --output-format stream-json"
        assert "--verbose" in src, "CC subprocess args must include --verbose"
        assert "--include-partial-messages" in src, (
            "CC subprocess args must include --include-partial-messages"
        )

    def test_subprocess_args_contain_p_flag(self):
        src = self._src()
        assert '"-p"' in src or "'-p'" in src, "CC subprocess args must include -p (print mode)"


# ---------------------------------------------------------------------------
# TestNDJSONParser — pure-function unit tests
# ---------------------------------------------------------------------------
class TestNDJSONParser:
    """Tests for _parse_cc_event(event_dict, tool_id_map, session_state) -> list[dict] | None.

    _parse_cc_event is a pure function extracted in Plan 02 implementation.
    It receives one parsed NDJSON dict and returns a list of WS envelope dicts to emit,
    or an empty list if the event produces no output. It mutates tool_id_map and session_state.

    Signature: _parse_cc_event(event: dict, tool_id_map: dict, session_state: dict) -> list[dict]
    """

    def _parse(self, event: dict, tool_id_map=None, session_state=None):
        from dashboard.server import _parse_cc_event  # type: ignore[attr-defined]

        if tool_id_map is None:
            tool_id_map = {}
        if session_state is None:
            session_state = {}
        return _parse_cc_event(event, tool_id_map, session_state)

    @pytest.mark.xfail(
        reason="_parse_cc_event not yet implemented", raises=ImportError, strict=False
    )
    def test_text_delta_from_stream_event(self):
        event = {
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "hello"},
            },
        }
        result = self._parse(event)
        assert len(result) == 1
        assert result[0] == {"type": "text_delta", "data": {"text": "hello"}}

    @pytest.mark.xfail(
        reason="_parse_cc_event not yet implemented", raises=ImportError, strict=False
    )
    def test_tool_start_from_content_block_start(self):
        event = {
            "type": "stream_event",
            "event": {
                "type": "content_block_start",
                "index": 1,
                "content_block": {"type": "tool_use", "id": "tu_1", "name": "read_file"},
            },
        }
        result = self._parse(event)
        assert len(result) == 1
        assert result[0]["type"] == "tool_start"
        assert result[0]["data"]["id"] == "tu_1"
        assert result[0]["data"]["name"] == "read_file"
        assert result[0]["data"]["input"] == {}

    @pytest.mark.xfail(
        reason="_parse_cc_event not yet implemented", raises=ImportError, strict=False
    )
    def test_tool_delta_from_input_json_delta(self):
        tool_id_map = {1: {"id": "tu_1", "name": "read_file"}}
        event = {
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "index": 1,
                "delta": {"type": "input_json_delta", "partial_json": '{"path":'},
            },
        }
        result = self._parse(event, tool_id_map=tool_id_map)
        assert len(result) == 1
        assert result[0]["type"] == "tool_delta"
        assert result[0]["data"]["id"] == "tu_1"
        assert result[0]["data"]["partial"] == '{"path":'

    @pytest.mark.xfail(
        reason="_parse_cc_event not yet implemented", raises=ImportError, strict=False
    )
    def test_turn_complete_from_result(self):
        event = {
            "type": "result",
            "session_id": "sess_abc",
            "cost_usd": 0.01,
            "usage": {"input_tokens": 100, "output_tokens": 50},
        }
        result = self._parse(event)
        assert len(result) == 1
        assert result[0]["type"] == "turn_complete"
        d = result[0]["data"]
        assert d["session_id"] == "sess_abc"
        assert d["cost_usd"] == 0.01
        assert d["input_tokens"] == 100
        assert d["output_tokens"] == 50

    @pytest.mark.xfail(
        reason="_parse_cc_event not yet implemented", raises=ImportError, strict=False
    )
    def test_session_id_extracted_from_result(self):
        event = {
            "type": "result",
            "session_id": "sess_abc",
            "cost_usd": 0.005,
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
        session_state = {}
        self._parse(event, session_state=session_state)
        assert session_state.get("cc_session_id") == "sess_abc"

    @pytest.mark.xfail(
        reason="_parse_cc_event not yet implemented", raises=ImportError, strict=False
    )
    def test_unknown_lines_skipped(self):
        """Non-JSON producing events return empty list — no exception."""
        event = {"type": "system", "subtype": "init", "session_id": "s1"}
        result = self._parse(event)
        assert isinstance(result, list)  # empty list is fine

    @pytest.mark.xfail(
        reason="_parse_cc_event not yet implemented", raises=ImportError, strict=False
    )
    def test_empty_event_no_crash(self):
        result = self._parse({})
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# TestSessionRegistry — async file I/O
# ---------------------------------------------------------------------------
class TestSessionRegistry:
    """Tests for _save_session / _load_session helpers and REST endpoint definitions."""

    @classmethod
    def _src(cls) -> str:
        return inspect.getsource(_srv_mod)

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="_save_session not yet implemented", raises=ImportError, strict=False)
    async def test_session_file_written_on_save(self, tmp_path):
        from dashboard.server import _save_session  # type: ignore[attr-defined]

        data = {
            "ws_session_id": "ws_123",
            "cc_session_id": "cc_abc",
            "created_at": "2026-03-17T00:00:00",
            "last_active_at": "2026-03-17T00:00:00",
            "title": "Hello world",
        }
        await _save_session("ws_123", data, sessions_dir=tmp_path)
        written = json.loads((tmp_path / "ws_123.json").read_text())
        assert written["cc_session_id"] == "cc_abc"

    @pytest.mark.asyncio
    @pytest.mark.xfail(
        reason="_save_session/_load_session not yet implemented", raises=ImportError, strict=False
    )
    async def test_session_file_loaded_on_resume(self, tmp_path):
        from dashboard.server import _load_session, _save_session  # type: ignore[attr-defined]

        data = {"ws_session_id": "ws_456", "cc_session_id": "cc_xyz"}
        await _save_session("ws_456", data, sessions_dir=tmp_path)
        loaded = await _load_session("ws_456", sessions_dir=tmp_path)
        assert loaded["cc_session_id"] == "cc_xyz"

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="_load_session not yet implemented", raises=ImportError, strict=False)
    async def test_load_nonexistent_session_returns_empty(self, tmp_path):
        from dashboard.server import _load_session  # type: ignore[attr-defined]

        result = await _load_session("no_such_id", sessions_dir=tmp_path)
        assert result == {}

    def test_get_sessions_endpoint_defined(self):
        src = self._src()
        assert '"/api/cc/sessions"' in src or "'/api/cc/sessions'" in src, (
            "server.py must define GET /api/cc/sessions"
        )

    def test_delete_session_endpoint_defined(self):
        src = self._src()
        assert "/api/cc/sessions/{session_id}" in src, (
            "server.py must define DELETE /api/cc/sessions/{session_id}"
        )


# ---------------------------------------------------------------------------
# TestMultiTurn — source inspection
# ---------------------------------------------------------------------------
class TestMultiTurn:
    @classmethod
    def _src(cls) -> str:
        return inspect.getsource(_srv_mod)

    def test_resume_flag_used_for_subsequent_turns(self):
        assert '"--resume"' in self._src() or "'--resume'" in self._src(), (
            "server.py must use --resume flag for multi-turn CC sessions"
        )

    def test_first_turn_no_resume(self):
        src = self._src()
        assert "cc_session_id" in src, (
            "server.py must track cc_session_id to determine whether to pass --resume"
        )


# ---------------------------------------------------------------------------
# TestFallback — source inspection
# ---------------------------------------------------------------------------
class TestFallback:
    @classmethod
    def _src(cls) -> str:
        return inspect.getsource(_srv_mod)

    def test_fallback_triggered_when_no_cli(self):
        src = self._src()
        assert '_shutil.which("claude")' in src or 'shutil.which("claude")' in src, (
            "server.py must detect claude CLI absence via shutil.which"
        )

    def test_fallback_status_event_emitted(self):
        src = self._src()
        assert '"status"' in src, "server.py must emit a status event when falling back to API mode"


# ---------------------------------------------------------------------------
# TestAuthStatus — source inspection
# ---------------------------------------------------------------------------
class TestAuthStatus:
    @classmethod
    def _src(cls) -> str:
        return inspect.getsource(_srv_mod)

    def test_auth_check_uses_exit_code(self):
        src = self._src()
        assert "returncode == 0" in src, "server.py must gate CC subscription status on exit code 0"

    def test_auth_check_endpoint_defined(self):
        src = self._src()
        assert "/api/cc/auth-status" in src, (
            "server.py must define GET /api/cc/auth-status endpoint"
        )
