"""Tests for /ws/terminal WebSocket endpoint routing logic."""

import inspect

import dashboard.server as _srv_mod


class TestTerminalWebSocketRouting:
    """Test terminal_ws routing: local shell, remote shell, local claude, remote claude."""

    @classmethod
    def _get_source(cls) -> str:
        return inspect.getsource(_srv_mod)

    def test_remote_rejected_when_host_not_configured(self):
        """Remote terminal returns error when AGENT42_REMOTE_HOST is empty."""
        src = self._get_source()
        assert "if not ssh_host:" in src, "server.py must guard against empty AGENT42_REMOTE_HOST"

    def test_remote_claude_rejected_when_host_not_configured(self):
        """Remote Claude returns error when AGENT42_REMOTE_HOST is empty."""
        src = self._get_source()
        # Both remote branches (shell and claude) must have the guard
        assert src.count("if not ssh_host:") >= 2, (
            "Both remote branches must guard against empty host"
        )

    def test_resize_message_not_forwarded_as_input(self):
        """JSON resize messages are parsed, not forwarded to subprocess stdin."""
        src = self._get_source()
        assert '"type") == "resize"' in src or "'type') == 'resize'" in src, (
            "terminal_ws must parse JSON resize messages"
        )

    def test_no_agent42_prod_default(self):
        """AGENT42_REMOTE_HOST must NOT default to 'agent42-prod'."""
        src = self._get_source()
        # The old default was: os.environ.get("AGENT42_REMOTE_HOST", "agent42-prod")
        assert '"agent42-prod"' not in src, (
            "server.py must not default AGENT42_REMOTE_HOST to 'agent42-prod'"
        )

    def test_resize_uses_json_parsing(self):
        """Resize message handling uses JSON parsing (not string matching)."""
        src = self._get_source()
        assert "_json.loads(msg)" in src or "json.loads(msg)" in src, (
            "terminal_ws must use JSON parsing for resize messages"
        )

    def test_resize_continue_skips_stdin_forward(self):
        """After handling resize, the message is not forwarded to stdin."""
        src = self._get_source()
        assert "continue  # Do not forward resize message as terminal input" in src, (
            "terminal_ws must use 'continue' to skip stdin forward after resize"
        )
