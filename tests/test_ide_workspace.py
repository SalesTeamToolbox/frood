"""
Tests for workspace_id wiring in IDE surface — terminal_ws, cc_chat_ws, and
CC session filtering.

These tests use a combination of source-scan patterns (grep the server source to
verify structural wiring) and TestClient integration tests for the REST endpoints.
"""

import asyncio
import json
import re
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Source-scan helpers
# ---------------------------------------------------------------------------

_SERVER_PY = Path(__file__).parent.parent / "dashboard" / "server.py"


def _read_server():
    return _SERVER_PY.read_text(encoding="utf-8")


def _find_function_body(source: str, func_name: str) -> str:
    """Extract the source text of an async def function by name.

    Returns the text from the 'async def func_name' line until the next
    top-level 'async def' or '@app.' decorator at the same indent level.
    This is a heuristic scan — sufficient for structural wiring tests.
    """
    lines = source.splitlines()
    start = None
    for i, line in enumerate(lines):
        if re.search(r"async def " + re.escape(func_name) + r"\s*\(", line):
            start = i
            break
    if start is None:
        return ""
    # Collect lines until next top-level function/decorator at same or lower indent
    indent = len(lines[start]) - len(lines[start].lstrip())
    body_lines = [lines[start]]
    for line in lines[start + 1 :]:
        stripped = line.lstrip()
        if not stripped:
            body_lines.append(line)
            continue
        cur_indent = len(line) - len(stripped)
        # Stop at a new decorator or function at the same or outer indent level
        if cur_indent <= indent and (
            stripped.startswith("@")
            or stripped.startswith("async def")
            or stripped.startswith("def ")
        ):
            break
        body_lines.append(line)
    return "\n".join(body_lines)


# ---------------------------------------------------------------------------
# Source-scan tests
# ---------------------------------------------------------------------------


class TestTerminalWsWorkspaceWiring:
    """Verify that terminal_ws reads workspace_id and uses _resolve_workspace."""

    def test_terminal_ws_reads_workspace_id_query_param(self):
        """terminal_ws must read workspace_id from query_params."""
        source = _read_server()
        body = _find_function_body(source, "terminal_ws")
        assert body, "terminal_ws function not found in server.py"
        assert "workspace_id" in body and "query_params" in body, (
            "terminal_ws should read workspace_id from websocket.query_params"
        )

    def test_terminal_ws_calls_resolve_workspace(self):
        """terminal_ws must call _resolve_workspace(ws_workspace_id)."""
        source = _read_server()
        body = _find_function_body(source, "terminal_ws")
        assert "_resolve_workspace(ws_workspace_id)" in body, (
            "terminal_ws should call _resolve_workspace(ws_workspace_id)"
        )

    def test_terminal_ws_uses_workspace_path_for_cwd(self):
        """terminal_ws must use workspace_path (not workspace) for cwd."""
        source = _read_server()
        body = _find_function_body(source, "terminal_ws")
        # All cwd assignments should use workspace_path, not raw workspace
        assert "cwd=str(workspace_path)" in body, "terminal_ws should use workspace_path for cwd"
        # Ensure the raw `workspace` global is NOT used as cwd in terminal_ws
        raw_cwd_uses = re.findall(r"cwd=str\(workspace\)", body)
        assert not raw_cwd_uses, f"terminal_ws still uses raw workspace for cwd: {raw_cwd_uses}"


class TestCcChatWsWorkspaceWiring:
    """Verify that cc_chat_ws reads workspace_id and uses _resolve_workspace."""

    def test_cc_chat_ws_reads_workspace_id_query_param(self):
        """cc_chat_ws must read workspace_id from query_params."""
        source = _read_server()
        body = _find_function_body(source, "cc_chat_ws")
        assert body, "cc_chat_ws function not found in server.py"
        assert "workspace_id" in body and "query_params" in body, (
            "cc_chat_ws should read workspace_id from websocket.query_params"
        )

    def test_cc_chat_ws_calls_resolve_workspace(self):
        """cc_chat_ws must call _resolve_workspace(ws_workspace_id)."""
        source = _read_server()
        body = _find_function_body(source, "cc_chat_ws")
        assert "_resolve_workspace(ws_workspace_id)" in body, (
            "cc_chat_ws should call _resolve_workspace(ws_workspace_id)"
        )

    def test_cc_chat_ws_save_session_includes_workspace_id(self):
        """cc_chat_ws _save_session call must include workspace_id field."""
        source = _read_server()
        body = _find_function_body(source, "cc_chat_ws")
        assert "workspace_id" in body and "_save_session" in body, (
            "cc_chat_ws _save_session call should include workspace_id"
        )
        # Specifically look for the ws_workspace_id assignment to the key
        assert re.search(r'"workspace_id".*ws_workspace_id', body), (
            'cc_chat_ws should save "workspace_id": ws_workspace_id or "" in _save_session'
        )


# ---------------------------------------------------------------------------
# Integration tests — cc_sessions REST endpoint
# ---------------------------------------------------------------------------


class TestCcSessionsWorkspaceFilter:
    """Integration tests for GET /api/cc/sessions?workspace_id= filtering."""

    @pytest.fixture
    def client_with_sessions(self, tmp_path, monkeypatch):

        from core.workspace_registry import WorkspaceRegistry
        from dashboard.auth import get_current_user
        from dashboard.server import create_app
        from dashboard.websocket_manager import WebSocketManager

        # Set AGENT42_WORKSPACE to tmp_path so cc_sessions reads from our test dir
        monkeypatch.setenv("AGENT42_WORKSPACE", str(tmp_path))

        registry = WorkspaceRegistry(tmp_path / "workspaces.json")
        asyncio.run(registry.seed_default(str(tmp_path)))

        app = create_app(
            ws_manager=WebSocketManager(),
            workspace_registry=registry,
        )
        app.dependency_overrides[get_current_user] = lambda: "test_user"

        # Create cc-sessions directory and seed test sessions
        cc_dir = tmp_path / ".agent42" / "cc-sessions"
        cc_dir.mkdir(parents=True, exist_ok=True)

        # Session A: belongs to workspace ws_abc
        session_a = {
            "ws_session_id": "session-a",
            "title": "Session A",
            "workspace_id": "ws_abc",
            "message_count": 1,
        }
        (cc_dir / "session-a.json").write_text(json.dumps(session_a))

        # Session B: belongs to workspace ws_xyz
        session_b = {
            "ws_session_id": "session-b",
            "title": "Session B",
            "workspace_id": "ws_xyz",
            "message_count": 2,
        }
        (cc_dir / "session-b.json").write_text(json.dumps(session_b))

        # Session C: legacy session (no workspace_id field)
        session_c = {
            "ws_session_id": "session-c",
            "title": "Session C (legacy)",
            "message_count": 3,
        }
        (cc_dir / "session-c.json").write_text(json.dumps(session_c))

        from fastapi.testclient import TestClient

        with TestClient(app) as c:
            yield c, {"a": session_a, "b": session_b, "c": session_c}

    def test_no_filter_returns_all_sessions(self, client_with_sessions):
        """GET /api/cc/sessions without filter returns all sessions."""
        c, sessions = client_with_sessions
        res = c.get("/api/cc/sessions")
        assert res.status_code == 200
        data = res.json()
        assert "sessions" in data
        ids = {s["ws_session_id"] for s in data["sessions"]}
        assert "session-a" in ids
        assert "session-b" in ids
        assert "session-c" in ids

    def test_workspace_filter_returns_matching_and_legacy(self, client_with_sessions):
        """GET /api/cc/sessions?workspace_id=ws_abc returns ws_abc + legacy sessions."""
        c, sessions = client_with_sessions
        res = c.get("/api/cc/sessions?workspace_id=ws_abc")
        assert res.status_code == 200
        data = res.json()
        ids = {s["ws_session_id"] for s in data["sessions"]}
        assert "session-a" in ids, "session-a (workspace ws_abc) should be included"
        assert "session-c" in ids, "session-c (legacy, no workspace_id) should be included"
        assert "session-b" not in ids, "session-b (workspace ws_xyz) should be excluded"

    def test_workspace_filter_excludes_other_workspace(self, client_with_sessions):
        """GET /api/cc/sessions?workspace_id=ws_xyz excludes ws_abc sessions."""
        c, sessions = client_with_sessions
        res = c.get("/api/cc/sessions?workspace_id=ws_xyz")
        assert res.status_code == 200
        data = res.json()
        ids = {s["ws_session_id"] for s in data["sessions"]}
        assert "session-b" in ids
        assert "session-c" in ids, "Legacy session should always be included"
        assert "session-a" not in ids

    def test_unknown_workspace_filter_returns_only_legacy(self, client_with_sessions):
        """GET /api/cc/sessions?workspace_id=ws_unknown returns only legacy sessions."""
        c, sessions = client_with_sessions
        res = c.get("/api/cc/sessions?workspace_id=ws_unknown")
        assert res.status_code == 200
        data = res.json()
        ids = {s["ws_session_id"] for s in data["sessions"]}
        assert "session-c" in ids, "Legacy sessions should always be included"
        assert "session-a" not in ids
        assert "session-b" not in ids
