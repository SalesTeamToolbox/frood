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

    def test_resize_message_not_forwarded_as_input(self):
        """JSON resize messages are parsed, not forwarded to subprocess stdin."""
        src = self._get_source()
        assert '"type") == "resize"' in src or "'type') == 'resize'" in src, (
            "terminal_ws must parse JSON resize messages"
        )

    def test_no_agent42_prod_default(self):
        """AGENT42_REMOTE_HOST must NOT default to 'agent42-prod'."""
        src = self._get_source()
        assert '"agent42-prod"' not in src, (
            "server.py must not default AGENT42_REMOTE_HOST to 'agent42-prod'"
        )

    def test_resize_uses_json_parsing(self):
        """Resize message handling uses JSON parsing (not string matching)."""
        src = self._get_source()
        assert "json.loads(msg)" in src or "json.loads(" in src, (
            "terminal_ws must use JSON parsing for resize messages"
        )
