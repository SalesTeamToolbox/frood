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
_APP_JS = Path(__file__).parent.parent / "dashboard" / "frontend" / "dist" / "app.js"


def _read_server():
    return _SERVER_PY.read_text(encoding="utf-8")


def _read_app_js():
    return _APP_JS.read_text(encoding="utf-8")


def _find_js_function_body(source: str, func_name: str) -> str:
    """Extract JS function body by searching for 'function func_name' and collecting until brace depth 0."""
    lines = source.splitlines()
    start = None
    for i, line in enumerate(lines):
        if re.search(r"function\s+" + re.escape(func_name) + r"\s*\(", line):
            start = i
            break
    if start is None:
        return ""
    body_lines = [lines[start]]
    brace_depth = lines[start].count("{") - lines[start].count("}")
    for line in lines[start + 1 :]:
        body_lines.append(line)
        brace_depth += line.count("{") - line.count("}")
        if brace_depth <= 0:
            break
    return "\n".join(body_lines)


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


# ---------------------------------------------------------------------------
# Source-scan + integration tests — ide_write_file workspace_id wiring
# ---------------------------------------------------------------------------


class TestIdeWriteFileWorkspaceWiring:
    """Verify that IDEWriteRequest includes workspace_id and ide_write_file reads from req."""

    def test_ide_write_request_has_workspace_id_field(self):
        """IDEWriteRequest Pydantic model must include workspace_id field."""
        source = _read_server()
        # Find the class body between 'class IDEWriteRequest' and the next class/decorator
        lines = source.splitlines()
        start = None
        for i, line in enumerate(lines):
            if re.search(r"class IDEWriteRequest\b", line):
                start = i
                break
        assert start is not None, "IDEWriteRequest class not found in server.py"
        # Collect class body lines (until next class/decorator at same or outer indent)
        indent = len(lines[start]) - len(lines[start].lstrip())
        class_lines = [lines[start]]
        for line in lines[start + 1 :]:
            stripped = line.lstrip()
            if not stripped:
                class_lines.append(line)
                continue
            cur_indent = len(line) - len(stripped)
            if cur_indent <= indent and (
                stripped.startswith("class ")
                or stripped.startswith("@")
                or stripped.startswith("async def")
                or stripped.startswith("def ")
            ):
                break
            class_lines.append(line)
        class_body = "\n".join(class_lines)
        assert "workspace_id" in class_body, "IDEWriteRequest must have a workspace_id field"

    def test_ide_write_file_reads_workspace_id_from_req(self):
        """ide_write_file must read workspace_id from req.workspace_id, not a standalone param."""
        source = _read_server()
        body = _find_function_body(source, "ide_write_file")
        assert body, "ide_write_file function not found in server.py"
        assert "req.workspace_id" in body, (
            "ide_write_file should call _resolve_workspace(req.workspace_id)"
        )
        # Ensure no standalone workspace_id parameter in the function signature
        # (the signature is the first few lines of the body)
        sig_lines = "\n".join(body.splitlines()[:6])
        assert "workspace_id: str" not in sig_lines, (
            "ide_write_file should not have a standalone workspace_id parameter"
        )

    def test_ide_write_file_routes_to_correct_workspace(self, tmp_path, monkeypatch):
        """POST /api/ide/file with workspace_id=B writes file to workspace B's root."""
        from fastapi.testclient import TestClient

        from core.workspace_registry import WorkspaceRegistry
        from dashboard.auth import get_current_user
        from dashboard.server import create_app
        from dashboard.websocket_manager import WebSocketManager

        monkeypatch.setenv("AGENT42_WORKSPACE", str(tmp_path))

        registry = WorkspaceRegistry(tmp_path / "workspaces.json")
        asyncio.run(registry.seed_default(str(tmp_path)))

        # Create a second workspace directory
        ws_b_path = tmp_path / "workspace_b"
        ws_b_path.mkdir()
        ws_b = asyncio.run(registry.create(name="Workspace B", root_path=str(ws_b_path)))

        app = create_app(
            ws_manager=WebSocketManager(),
            workspace_registry=registry,
        )
        app.dependency_overrides[get_current_user] = lambda: "test_user"

        with TestClient(app) as c:
            res = c.post(
                "/api/ide/file",
                json={"path": "test.txt", "content": "hello", "workspace_id": ws_b.id},
                headers={"Content-Type": "application/json"},
            )
            assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
            data = res.json()
            assert data["status"] == "ok"

        # File must exist in workspace B's root, not tmp_path root
        assert (ws_b_path / "test.txt").exists(), "File should be written to workspace B"
        assert (ws_b_path / "test.txt").read_text() == "hello"
        assert not (tmp_path / "test.txt").exists(), (
            "File should NOT be written to default workspace"
        )


# ---------------------------------------------------------------------------
# Source-scan + integration tests — ide_search workspace_id wiring
# ---------------------------------------------------------------------------


class TestIdeSearchWorkspaceWiring:
    """Verify that ideDoSearch appends workspace_id and server-side search respects it."""

    def test_ide_do_search_sends_workspace_id(self):
        """ideDoSearch function body must contain workspace_id query param."""
        source = _read_app_js()
        body = _find_js_function_body(source, "ideDoSearch")
        assert body, "ideDoSearch function not found in app.js"
        assert "workspace_id" in body, "ideDoSearch should append workspace_id to the search URL"

    def test_ide_search_routes_to_correct_workspace(self, tmp_path, monkeypatch):
        """GET /api/ide/search?workspace_id=B returns results from workspace B only."""
        from fastapi.testclient import TestClient

        from core.workspace_registry import WorkspaceRegistry
        from dashboard.auth import get_current_user
        from dashboard.server import create_app
        from dashboard.websocket_manager import WebSocketManager

        # Use separate sibling directories so workspace B is NOT nested inside workspace A
        ws_a_path = tmp_path / "workspace_a"
        ws_a_path.mkdir()
        ws_b_path = tmp_path / "workspace_b"
        ws_b_path.mkdir()

        monkeypatch.setenv("AGENT42_WORKSPACE", str(ws_a_path))

        registry = WorkspaceRegistry(tmp_path / "workspaces.json")
        asyncio.run(registry.seed_default(str(ws_a_path)))
        default_ws = registry.get_default()

        # Create a second workspace
        ws_b = asyncio.run(registry.create(name="Workspace B", root_path=str(ws_b_path)))

        # Write a file with unique content to workspace B only (not in workspace A)
        (ws_b_path / "searchable.txt").write_text("UNIQUE_MARKER_XYZ", encoding="utf-8")

        app = create_app(
            ws_manager=WebSocketManager(),
            workspace_registry=registry,
        )
        app.dependency_overrides[get_current_user] = lambda: "test_user"

        with TestClient(app) as c:
            # Search in workspace B — should find the file
            res_b = c.get(
                f"/api/ide/search?q=UNIQUE_MARKER_XYZ&workspace_id={ws_b.id}",
                headers={"Authorization": "Bearer test"},
            )
            assert res_b.status_code == 200, f"Expected 200, got {res_b.status_code}: {res_b.text}"
            data_b = res_b.json()
            assert len(data_b["results"]) > 0, "Search in workspace B should find the file"
            assert any("searchable.txt" in r["file"] for r in data_b["results"])

            # Search in default workspace (workspace A) — should not find the file
            res_a = c.get(
                f"/api/ide/search?q=UNIQUE_MARKER_XYZ&workspace_id={default_ws.id}",
                headers={"Authorization": "Bearer test"},
            )
            assert res_a.status_code == 200, f"Expected 200, got {res_a.status_code}: {res_a.text}"
            data_a = res_a.json()
            assert len(data_a["results"]) == 0, (
                "Search in default workspace should not find file that only exists in workspace B"
            )
