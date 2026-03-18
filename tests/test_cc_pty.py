"""Wave 0 test scaffold for Phase 05: Streaming PTY Bridge.

All tests are xfail(AssertionError) -- Plan 05-02 and 05-03 flip them GREEN.
Source inspection tests verify patterns exist in dashboard/server.py.
Unit tests verify _parse_cc_event expansion for system events.
"""

import json
import re
from pathlib import Path

import pytest

SERVER_PY = Path(__file__).resolve().parent.parent / "dashboard" / "server.py"
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"


def _extract_function_source(full_source, func_name):
    """Extract a function body from source text by name."""
    pattern = rf"((?:async\s+)?def\s+{re.escape(func_name)}\s*\()"
    match = re.search(pattern, full_source)
    if not match:
        return ""
    start = match.start()
    rest = full_source[match.end() :]
    indent_match = re.search(r"\n    (async\s+)?def\s+\w+\s*\(", rest)
    if indent_match:
        end = match.end() + indent_match.start()
    else:
        end = len(full_source)
    return full_source[start:end]


# ---------------------------------------------------------------------------
# TestPTYSubprocess -- PTY-01
# ---------------------------------------------------------------------------


class TestPTYSubprocess:
    """Verify cc_chat_ws uses PTY subprocess (winpty on Windows, pty on Unix)."""

    def setup_method(self):
        self.server_src = SERVER_PY.read_text(encoding="utf-8")
        self.cc_chat_ws_src = _extract_function_source(self.server_src, "cc_chat_ws")

    @pytest.mark.xfail(
        raises=AssertionError, strict=False, reason="Phase 05 implementation pending"
    )
    def test_cc_chat_ws_imports_winpty(self):
        """cc_chat_ws should import PtyProcess from winpty for Windows PTY support (PTY-01)."""
        assert "from winpty import PtyProcess" in self.cc_chat_ws_src, (
            "cc_chat_ws function body must contain 'from winpty import PtyProcess' "
            "for Windows PTY subprocess support"
        )

    @pytest.mark.xfail(
        raises=AssertionError, strict=False, reason="Phase 05 implementation pending"
    )
    def test_cc_chat_ws_imports_pty_unix(self):
        """cc_chat_ws should import pty module for Unix PTY support (PTY-01)."""
        assert "import pty" in self.cc_chat_ws_src, (
            "cc_chat_ws function body must contain 'import pty' for Unix PTY subprocess support"
        )

    @pytest.mark.xfail(
        raises=AssertionError, strict=False, reason="Phase 05 implementation pending"
    )
    def test_pty_uses_readline(self):
        """PTY NDJSON read loop must use readline, not read(4096) (PTY-01)."""
        cc_chat_ws_start = self.server_src.find("async def cc_chat_ws")
        cc_chat_ws_region = self.server_src[cc_chat_ws_start:] if cc_chat_ws_start != -1 else ""
        assert "readline" in cc_chat_ws_region, (
            "PTY NDJSON read loop in cc_chat_ws must use readline to read complete lines; "
            "read(4096) may split NDJSON lines and corrupt JSON parsing"
        )

    @pytest.mark.xfail(
        raises=AssertionError, strict=False, reason="Phase 05 implementation pending"
    )
    def test_pty_dimensions_wide(self):
        """PTY must spawn with wide dimensions (>= 220 cols) to prevent NDJSON line wrap (PTY-01)."""
        assert "dimensions" in self.server_src and "220" in self.server_src, (
            "PTY spawn in cc_chat_ws must include dimensions=(24, 220) or wider "
            "to prevent NDJSON line wrapping at default 80-column terminal width"
        )


# ---------------------------------------------------------------------------
# TestInitProgress -- PTY-02
# ---------------------------------------------------------------------------


class TestInitProgress:
    """Verify _parse_cc_event handles system events for init progress relay."""

    def setup_method(self):
        self.server_src = SERVER_PY.read_text(encoding="utf-8")
        self.parse_event_src = _extract_function_source(self.server_src, "_parse_cc_event")

    @pytest.mark.xfail(
        raises=AssertionError, strict=False, reason="Phase 05 implementation pending"
    )
    def test_parse_cc_event_handles_hook_started(self):
        """_parse_cc_event must handle system/hook_started events (PTY-02)."""
        assert "hook_started" in self.parse_event_src, (
            "_parse_cc_event function body must handle 'hook_started' subtype "
            "to relay hook initialization status to frontend"
        )

    @pytest.mark.xfail(
        raises=AssertionError, strict=False, reason="Phase 05 implementation pending"
    )
    def test_parse_cc_event_handles_init_mcp_servers(self):
        """_parse_cc_event must parse mcp_servers array from system/init event (PTY-02)."""
        assert "mcp_servers" in self.parse_event_src, (
            "_parse_cc_event function body must parse the 'mcp_servers' array from "
            "system/init events to show per-server connection status"
        )

    @pytest.mark.xfail(
        raises=AssertionError, strict=False, reason="Phase 05 implementation pending"
    )
    def test_init_mcp_servers_unit(self):
        """_parse_cc_event must emit per-MCP-server status + 'Claude Code ready' (PTY-02)."""
        fixture_path = FIXTURE_DIR / "cc_init_event.ndjson"
        lines_data = [json.loads(ln) for ln in fixture_path.read_text().splitlines() if ln.strip()]
        init_event = lines_data[2]  # Line 3: system/init with mcp_servers
        assert init_event["subtype"] == "init"
        assert len(init_event["mcp_servers"]) == 2

        func_src = _extract_function_source(self.server_src, "_parse_cc_event")
        assert func_src, "_parse_cc_event function not found in server.py"

        import logging

        ns = {
            "logging": logging,
            "logger": logging.getLogger("test_cc_pty"),
            "json": json,
        }
        exec(func_src, ns)
        parse_fn = ns.get("_parse_cc_event")
        assert parse_fn is not None, "_parse_cc_event not defined after exec"

        envelopes = parse_fn(init_event, tool_id_map={}, session_state={})
        assert isinstance(envelopes, list), "Expected list of envelopes"

        messages = [e["data"]["message"] for e in envelopes if e.get("type") == "status"]
        jcodemunch_found = any("jcodemunch" in m for m in messages)
        agent42_found = any("agent42-remote" in m for m in messages)
        ready_found = any("Claude Code ready" in m for m in messages)

        assert jcodemunch_found, f"Expected status message mentioning 'jcodemunch' in {messages}"
        assert agent42_found, f"Expected status message mentioning 'agent42-remote' in {messages}"
        assert ready_found, f"Expected 'Claude Code ready' status message in {messages}"


# ---------------------------------------------------------------------------
# TestPreWarmPool -- PTY-03
# ---------------------------------------------------------------------------


class TestPreWarmPool:
    """Verify pre-warmed CC session pool exists in server.py."""

    def setup_method(self):
        self.server_src = SERVER_PY.read_text(encoding="utf-8")
        self.cc_chat_ws_src = _extract_function_source(self.server_src, "cc_chat_ws")

    @pytest.mark.xfail(
        raises=AssertionError, strict=False, reason="Phase 05 implementation pending"
    )
    def test_warm_pool_defined(self):
        """server.py must define _cc_warm_pool dict in create_app() closure scope (PTY-03)."""
        assert "_cc_warm_pool" in self.server_src, (
            "server.py must define '_cc_warm_pool' dict (scoped inside create_app()) "
            "to hold one warm CC process per user"
        )

    @pytest.mark.xfail(
        raises=AssertionError, strict=False, reason="Phase 05 implementation pending"
    )
    def test_warm_pool_idle_timeout(self):
        """Warm pool must have 5-minute idle timeout (PTY-03)."""
        warm_pool_idx = self.server_src.find("_cc_warm_pool")
        assert warm_pool_idx != -1, "_cc_warm_pool not found in server.py"

        context = self.server_src[max(0, warm_pool_idx - 500) : warm_pool_idx + 500]
        has_timeout = "300" in context or "5 * 60" in context or "5*60" in context
        assert has_timeout, (
            "Expected idle timeout constant (300 or 5*60) near '_cc_warm_pool' "
            "definition in server.py (within 500 chars)"
        )

    @pytest.mark.xfail(
        raises=AssertionError, strict=False, reason="Phase 05 implementation pending"
    )
    def test_warm_query_param(self):
        """cc_chat_ws must handle ?warm=true query parameter for pre-warm opt-in (PTY-03)."""
        assert "warm" in self.cc_chat_ws_src, (
            "cc_chat_ws function body must handle 'warm' query parameter "
            "(?warm=true triggers pre-spawn of CC process)"
        )


# ---------------------------------------------------------------------------
# TestKeepalive -- PTY-05
# ---------------------------------------------------------------------------


class TestKeepalive:
    """Verify cc_chat_ws sends periodic keepalive during CC subprocess init."""

    def setup_method(self):
        self.server_src = SERVER_PY.read_text(encoding="utf-8")
        self.cc_chat_ws_src = _extract_function_source(self.server_src, "cc_chat_ws")

    @pytest.mark.xfail(
        raises=AssertionError, strict=False, reason="Phase 05 implementation pending"
    )
    def test_keepalive_task_exists(self):
        """cc_chat_ws must create a keepalive asyncio task (PTY-05)."""
        assert "keepalive" in self.cc_chat_ws_src, (
            "cc_chat_ws function body must contain a 'keepalive' task "
            "to keep the WS alive during CC subprocess initialization"
        )

    @pytest.mark.xfail(
        raises=AssertionError, strict=False, reason="Phase 05 implementation pending"
    )
    def test_keepalive_interval(self):
        """Keepalive must use 15-second interval sleep(15) (PTY-05)."""
        assert "sleep(15)" in self.cc_chat_ws_src, (
            "cc_chat_ws function body must contain 'sleep(15)' for 15-second keepalive interval; "
            "shorter intervals create unnecessary WS traffic"
        )


# ---------------------------------------------------------------------------
# TestGracefulDegradation -- PTY-04
# ---------------------------------------------------------------------------


class TestGracefulDegradation:
    """Verify PIPE fallback is preserved when PTY is unavailable (PTY-04)."""

    def setup_method(self):
        self.server_src = SERVER_PY.read_text(encoding="utf-8")
        self.cc_chat_ws_src = _extract_function_source(self.server_src, "cc_chat_ws")

    def test_pipe_fallback_preserved(self):
        """cc_chat_ws must still contain create_subprocess_exec + PIPE as PTY-04 fallback.

        This test should PASS (not xfail) because the current code already has PIPE.
        PTY-04 requires preserving this path when winpty/pty import fails.
        """
        assert "create_subprocess_exec" in self.cc_chat_ws_src, (
            "cc_chat_ws function body must contain 'create_subprocess_exec' "
            "as the PIPE fallback path (PTY-04)"
        )
        assert "PIPE" in self.cc_chat_ws_src, (
            "cc_chat_ws function body must contain 'PIPE' "
            "as the subprocess stdout/stderr fallback (PTY-04)"
        )
