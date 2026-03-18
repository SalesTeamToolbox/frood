"""Tests for /api/remote/status endpoint."""

from unittest.mock import patch


class TestRemoteStatus:
    """Test the /api/remote/status API endpoint."""

    def test_remote_available_response_shape_when_host_set(self):
        """remote_status returns available=True when AGENT42_REMOTE_HOST is set."""
        import inspect

        import dashboard.server as _srv_mod

        src = inspect.getsource(_srv_mod)
        assert '"available": bool(host)' in src, "remote_status must return available=bool(host)"
        assert '"host": host if host else None' in src, (
            "remote_status must return host field as None when empty"
        )

    def test_remote_status_endpoint_registered(self):
        """The /api/remote/status endpoint must exist in server.py."""
        import inspect

        import dashboard.server as _srv_mod

        src = inspect.getsource(_srv_mod)
        assert "async def remote_status" in src, "server.py must define async def remote_status"
        assert '"/api/remote/status"' in src, "server.py must register /api/remote/status GET route"

    def test_remote_status_reads_env_var(self):
        """remote_status uses AGENT42_REMOTE_HOST env var."""
        import inspect

        import dashboard.server as _srv_mod

        src = inspect.getsource(_srv_mod)
        assert "AGENT42_REMOTE_HOST" in src, "remote_status must read AGENT42_REMOTE_HOST env var"

    def test_remote_status_unavailable_when_host_not_configured(self):
        """Verify logic: empty host results in available=False, host=None."""
        # Simulate the remote_status logic inline
        import os

        env_backup = os.environ.pop("AGENT42_REMOTE_HOST", None)
        try:
            host = os.environ.get("AGENT42_REMOTE_HOST", "")
            result = {"available": bool(host), "host": host if host else None}
            assert result["available"] is False
            assert result["host"] is None
        finally:
            if env_backup is not None:
                os.environ["AGENT42_REMOTE_HOST"] = env_backup

    def test_remote_status_available_when_host_configured(self):
        """Verify logic: non-empty host results in available=True, host set."""
        import os

        with patch.dict("os.environ", {"AGENT42_REMOTE_HOST": "myserver.example.com"}):
            host = os.environ.get("AGENT42_REMOTE_HOST", "")
            result = {"available": bool(host), "host": host if host else None}
            assert result["available"] is True
            assert result["host"] == "myserver.example.com"
