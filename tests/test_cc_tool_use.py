"""Tests for Phase 3 Tool Use + Sessions — source inspection of server.py, app.js, style.css.

Strategy: identical to tests/test_cc_chat_ui.py — read source files as text and assert
required patterns are present. Tests run RED until implementation plans 03-02 through 03-05
complete.

Requirements covered: TOOL-01 through TOOL-06, SESS-01 through SESS-06.
"""

import json
from pathlib import Path

import pytest

APP_JS = Path(__file__).resolve().parent.parent / "dashboard" / "frontend" / "dist" / "app.js"
STYLE_CSS = Path(__file__).resolve().parent.parent / "dashboard" / "frontend" / "dist" / "style.css"
SERVER_PY = Path(__file__).resolve().parent.parent / "dashboard" / "server.py"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "cc_tool_result_sample.ndjson"


# ---------------------------------------------------------------------------
# Class 1: TestToolCards (TOOL-01, TOOL-02, TOOL-04, TOOL-05)
# ---------------------------------------------------------------------------


class TestToolCards:
    """Tool card rendering patterns in app.js (TOOL-01, TOOL-02, TOOL-04, TOOL-05)."""

    def setup_method(self):
        self.src = APP_JS.read_text(encoding="utf-8")

    @pytest.mark.xfail(
        raises=AssertionError,
        strict=False,
        reason="Unimplemented — Plan 03-03 GREEN flips",
    )
    def test_tool_card_created_on_tool_start(self):
        """TOOL-01: app.js must define ccCreateToolCard to render collapsed tool cards."""
        assert "ccCreateToolCard" in self.src, (
            "app.js must define ccCreateToolCard function for tool_start events"
        )

    @pytest.mark.xfail(
        raises=AssertionError,
        strict=False,
        reason="Unimplemented — Plan 03-03 GREEN flips",
    )
    def test_tool_card_collapsed_by_default(self):
        """TOOL-01: Tool cards use cc-tool-card and cc-tool-header classes."""
        assert "cc-tool-card" in self.src, (
            "app.js must use .cc-tool-card class for tool card container"
        )
        assert "cc-tool-header" in self.src, (
            "app.js must use .cc-tool-header class for clickable header"
        )

    @pytest.mark.xfail(
        raises=AssertionError,
        strict=False,
        reason="Unimplemented — Plan 03-03 GREEN flips",
    )
    def test_tool_card_toggle_expand(self):
        """TOOL-01: app.js must define ccToggleToolCard for expand/collapse."""
        assert "ccToggleToolCard" in self.src, (
            "app.js must define ccToggleToolCard function for expand/collapse toggle"
        )

    @pytest.mark.xfail(
        raises=AssertionError,
        strict=False,
        reason="Unimplemented — Plan 03-03 GREEN flips",
    )
    def test_tool_card_input_from_delta(self):
        """TOOL-02: tool_delta case accumulates input via inputBuf pattern."""
        assert "tool_delta" in self.src, "app.js WS handler must handle tool_delta message type"
        assert "inputBuf" in self.src, (
            "app.js must use inputBuf pattern to accumulate tool_delta partial JSON"
        )

    @pytest.mark.xfail(
        raises=AssertionError,
        strict=False,
        reason="Unimplemented — Plan 03-03 GREEN flips",
    )
    def test_file_tool_card_shows_path(self):
        """TOOL-04: File tool cards display target path via cc-tool-target class."""
        assert "cc-tool-target" in self.src, (
            "app.js must use .cc-tool-target class to display file path in tool card"
        )

    @pytest.mark.xfail(
        raises=AssertionError,
        strict=False,
        reason="Unimplemented — Plan 03-03 GREEN flips",
    )
    def test_bash_tool_card_shows_command(self):
        """TOOL-05: Bash tool cards render command distinctly via cc-tool-bash or ccToolType."""
        assert "cc-tool-bash" in self.src or "ccToolType" in self.src, (
            "app.js must distinguish Bash tool rendering via cc-tool-bash class or ccToolType"
        )

    @pytest.mark.xfail(
        raises=AssertionError,
        strict=False,
        reason="Unimplemented — Plan 03-03 GREEN flips",
    )
    def test_tool_card_error_state(self):
        """TOOL-01: Tool cards render error state via cc-tool-error class."""
        assert "cc-tool-error" in self.src, (
            "app.js must use .cc-tool-error class for failed tool card rendering"
        )


# ---------------------------------------------------------------------------
# Class 2: TestParseToolResult (TOOL-03) — server.py source inspection
# ---------------------------------------------------------------------------


class TestParseToolResult:
    """_parse_cc_event handles tool_result content blocks in server.py (TOOL-03)."""

    def setup_method(self):
        self.src = SERVER_PY.read_text(encoding="utf-8")

    @pytest.mark.xfail(
        raises=AssertionError,
        strict=False,
        reason="Unimplemented — Plan 03-02 GREEN flips",
    )
    def test_tool_result_emits_tool_output(self):
        """TOOL-03: _parse_cc_event must handle tool_result and emit tool_output envelope."""
        assert "tool_output" in self.src, (
            "server.py must emit 'tool_output' WS envelope type for tool_result content blocks"
        )
        assert "tool_result" in self.src, (
            "server.py _parse_cc_event must check for tool_result content block type"
        )

    @pytest.mark.xfail(
        raises=AssertionError,
        strict=False,
        reason="Unimplemented — Plan 03-02 GREEN flips",
    )
    def test_tool_output_has_tool_use_id(self):
        """TOOL-03: tool_output envelope must include tool_use_id to match tool_start."""
        assert "tool_use_id" in self.src, (
            "server.py tool_output envelope must include tool_use_id field"
        )


# ---------------------------------------------------------------------------
# Class 3: TestParseToolResultFixture (TOOL-03) — unit test of fixture parsing
# ---------------------------------------------------------------------------


class TestParseToolResultFixture:
    """Validate cc_tool_result_sample.ndjson fixture structure (TOOL-03)."""

    def setup_method(self):
        self.events = []
        with open(FIXTURE) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    self.events.append(json.loads(line))

    def test_fixture_has_tool_result_events(self):
        """TOOL-03: Fixture must contain at least 2 tool_result content block events."""
        tool_results = [
            e
            for e in self.events
            if e.get("type") == "stream_event"
            and e.get("event", {}).get("content_block", {}).get("type") == "tool_result"
        ]
        assert len(tool_results) >= 2, f"Expected >= 2 tool_result events, got {len(tool_results)}"

    def test_fixture_has_read_and_bash_tools(self):
        """TOOL-03: Fixture must include Read and Bash tool_use events."""
        tool_uses = [
            e
            for e in self.events
            if e.get("type") == "stream_event"
            and e.get("event", {}).get("content_block", {}).get("type") == "tool_use"
        ]
        names = {e["event"]["content_block"]["name"] for e in tool_uses}
        assert "Read" in names, "Fixture must contain a Read tool_use event"
        assert "Bash" in names, "Fixture must contain a Bash tool_use event"


# ---------------------------------------------------------------------------
# Class 4: TestPermissionRequest (TOOL-06)
# ---------------------------------------------------------------------------


class TestPermissionRequest:
    """Permission request flow in server.py and app.js (TOOL-06)."""

    def setup_method(self):
        self.server_src = SERVER_PY.read_text(encoding="utf-8")
        self.app_src = APP_JS.read_text(encoding="utf-8")

    @pytest.mark.xfail(
        raises=AssertionError,
        strict=False,
        reason="Unimplemented — Plan 03-04 GREEN flips",
    )
    def test_permission_tool_emits_permission_request(self):
        """TOOL-06: server.py must emit permission_request WS envelope type."""
        assert "permission_request" in self.server_src, (
            "server.py must emit 'permission_request' envelope for MCP permission tool calls"
        )

    @pytest.mark.xfail(
        raises=AssertionError,
        strict=False,
        reason="Unimplemented — Plan 03-04 GREEN flips",
    )
    def test_permission_tool_name_constant(self):
        """TOOL-06: server.py must define cc_permission constant for MCP tool name."""
        assert "cc_permission" in self.server_src, (
            "server.py must define 'cc_permission' constant for permission MCP tool name"
        )

    @pytest.mark.xfail(
        raises=AssertionError,
        strict=False,
        reason="Unimplemented — Plan 03-04 GREEN flips",
    )
    def test_permission_card_rendered(self):
        """TOOL-06: app.js must render permission card with cc-perm-card or permission_request."""
        assert "cc-perm-card" in self.app_src or "permission_request" in self.app_src, (
            "app.js must render permission card via cc-perm-card class or permission_request handler"
        )

    @pytest.mark.xfail(
        raises=AssertionError,
        strict=False,
        reason="Unimplemented — Plan 03-04 GREEN flips",
    )
    def test_permission_response_handled(self):
        """TOOL-06: server.py WS receive loop must handle permission_response messages."""
        assert "permission_response" in self.server_src, (
            "server.py must handle 'permission_response' in WS receive loop"
        )


# ---------------------------------------------------------------------------
# Class 5: TestSessionPersistence (SESS-01, SESS-02)
# ---------------------------------------------------------------------------


class TestSessionPersistence:
    """Session persistence patterns in app.js (SESS-01, SESS-02)."""

    def setup_method(self):
        self.src = APP_JS.read_text(encoding="utf-8")

    @pytest.mark.xfail(
        raises=AssertionError,
        strict=False,
        reason="Unimplemented — Plan 03-05 GREEN flips",
    )
    def test_session_id_stored_in_session_storage(self):
        """SESS-02: app.js must use sessionStorage for CC session ID persistence."""
        assert "sessionStorage" in self.src, (
            "app.js must use sessionStorage to persist CC session IDs across reconnects"
        )

    @pytest.mark.xfail(
        raises=AssertionError,
        strict=False,
        reason="Unimplemented — Plan 03-05 GREEN flips",
    )
    def test_session_resume_status_message(self):
        """SESS-02: app.js must show 'Session resumed' status when reconnecting."""
        assert "Session resumed" in self.src, (
            "app.js must display 'Session resumed' status message on reconnect"
        )


# ---------------------------------------------------------------------------
# Class 6: TestMultiSessionTabs (SESS-03)
# ---------------------------------------------------------------------------


class TestMultiSessionTabs:
    """Multi-session tab strip in app.js (SESS-03)."""

    def setup_method(self):
        self.src = APP_JS.read_text(encoding="utf-8")

    @pytest.mark.xfail(
        raises=AssertionError,
        strict=False,
        reason="Unimplemented — Plan 03-05 GREEN flips",
    )
    def test_tab_strip_rendered(self):
        """SESS-03: app.js must render cc-tab-strip or cc-session-tab for multi-session tabs."""
        assert "cc-tab-strip" in self.src or "cc-session-tab" in self.src, (
            "app.js must use cc-tab-strip or cc-session-tab class for multi-session tab UI"
        )

    @pytest.mark.xfail(
        raises=AssertionError,
        strict=False,
        reason="Unimplemented — Plan 03-05 GREEN flips",
    )
    def test_new_session_tab_button(self):
        """SESS-03: app.js must have cc-tab-new or cc-tab-add button for creating sessions."""
        assert "cc-tab-new" in self.src or "cc-tab-add" in self.src, (
            "app.js must use cc-tab-new or cc-tab-add class for new session tab button"
        )


# ---------------------------------------------------------------------------
# Class 7: TestSessionSidebar (SESS-04, SESS-05)
# ---------------------------------------------------------------------------


class TestSessionSidebar:
    """Session sidebar with history and resume in app.js (SESS-04, SESS-05)."""

    def setup_method(self):
        self.src = APP_JS.read_text(encoding="utf-8")

    @pytest.mark.xfail(
        raises=AssertionError,
        strict=False,
        reason="Unimplemented — Plan 03-05 GREEN flips",
    )
    def test_sidebar_loads_sessions(self):
        """SESS-04: app.js must fetch session list from /api/cc/sessions."""
        assert "/api/cc/sessions" in self.src, (
            "app.js must call /api/cc/sessions to populate session sidebar"
        )

    @pytest.mark.xfail(
        raises=AssertionError,
        strict=False,
        reason="Unimplemented — Plan 03-05 GREEN flips",
    )
    def test_sidebar_click_resumes(self):
        """SESS-05: app.js must handle session sidebar click to resume session."""
        assert "ccResumeSession" in self.src or "resume" in self.src, (
            "app.js must define ccResumeSession or resume handler for session sidebar clicks"
        )

    @pytest.mark.xfail(
        raises=AssertionError,
        strict=False,
        reason="Unimplemented — Plan 03-05 GREEN flips",
    )
    def test_sidebar_relative_time(self):
        """SESS-04: app.js must define ccRelativeTime for human-readable timestamps."""
        assert "ccRelativeTime" in self.src, (
            "app.js must define ccRelativeTime function for relative time display in sidebar"
        )


# ---------------------------------------------------------------------------
# Class 8: TestTokenBar (SESS-06)
# ---------------------------------------------------------------------------


class TestTokenBar:
    """Token usage bar display in app.js (SESS-06)."""

    def setup_method(self):
        self.src = APP_JS.read_text(encoding="utf-8")

    @pytest.mark.xfail(
        raises=AssertionError,
        strict=False,
        reason="Unimplemented — Plan 03-05 GREEN flips",
    )
    def test_token_bar_rendered(self):
        """SESS-06: app.js must render cc-token-bar for token usage display."""
        assert "cc-token-bar" in self.src, "app.js must use .cc-token-bar class for token usage bar"

    @pytest.mark.xfail(
        raises=AssertionError,
        strict=False,
        reason="Unimplemented — Plan 03-05 GREEN flips",
    )
    def test_token_bar_accumulates(self):
        """SESS-06: app.js must track totalInputTokens or totalOutputTokens for accumulation."""
        assert "totalInputTokens" in self.src or "totalOutputTokens" in self.src, (
            "app.js must accumulate token counts via totalInputTokens/totalOutputTokens"
        )


# ---------------------------------------------------------------------------
# Class 9: TestSaveSessionMetadata (SESS-04)
# ---------------------------------------------------------------------------


class TestSaveSessionMetadata:
    """_save_session metadata fields in server.py (SESS-04)."""

    def setup_method(self):
        self.src = SERVER_PY.read_text(encoding="utf-8")

    @pytest.mark.xfail(
        raises=AssertionError,
        strict=False,
        reason="Unimplemented — Plan 03-02 GREEN flips",
    )
    def test_save_session_has_preview_text(self):
        """SESS-04: _save_session must include preview_text field for sidebar display."""
        assert "preview_text" in self.src, (
            "server.py _save_session data must include preview_text field"
        )

    @pytest.mark.xfail(
        raises=AssertionError,
        strict=False,
        reason="Unimplemented — Plan 03-02 GREEN flips",
    )
    def test_save_session_has_message_count(self):
        """SESS-04: _save_session must include message_count field for sidebar display."""
        assert "message_count" in self.src, (
            "server.py _save_session data must include message_count field"
        )


# ---------------------------------------------------------------------------
# Class 10: TestToolCardCSS (TOOL-01)
# ---------------------------------------------------------------------------


class TestToolCardCSS:
    """Tool card CSS classes in style.css (TOOL-01)."""

    def setup_method(self):
        self.src = STYLE_CSS.read_text(encoding="utf-8")

    @pytest.mark.xfail(
        raises=AssertionError,
        strict=False,
        reason="Unimplemented — Plan 03-03 GREEN flips",
    )
    def test_tool_card_css_classes(self):
        """TOOL-01: style.css must define .cc-tool-card and .cc-tool-header classes."""
        assert ".cc-tool-card" in self.src, (
            "style.css must define .cc-tool-card class for tool card styling"
        )
        assert ".cc-tool-header" in self.src, (
            "style.css must define .cc-tool-header class for tool header styling"
        )

    @pytest.mark.xfail(
        raises=AssertionError,
        strict=False,
        reason="Unimplemented — Plan 03-03 GREEN flips",
    )
    def test_tool_card_status_css(self):
        """TOOL-01: style.css must define .cc-tool-running, .cc-tool-complete, .cc-tool-error."""
        assert ".cc-tool-running" in self.src, (
            "style.css must define .cc-tool-running class for in-progress tools"
        )
        assert ".cc-tool-complete" in self.src, (
            "style.css must define .cc-tool-complete class for finished tools"
        )
        assert ".cc-tool-error" in self.src, (
            "style.css must define .cc-tool-error class for failed tools"
        )
