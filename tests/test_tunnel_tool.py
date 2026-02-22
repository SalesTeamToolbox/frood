"""Tests for tunnel manager tool."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.approval_gate import ApprovalGate
from tools.tunnel_tool import TunnelInfo, TunnelTool


@pytest.fixture
def approval_gate():
    gate = MagicMock(spec=ApprovalGate)
    gate.request = AsyncMock(return_value=True)
    return gate


@pytest.fixture
def tunnel_tool(approval_gate):
    return TunnelTool(approval_gate)


class TestTunnelTool:
    def test_tool_properties(self, tunnel_tool):
        assert tunnel_tool.name == "tunnel"
        assert "expose" in tunnel_tool.description.lower()
        params = tunnel_tool.parameters
        assert params["type"] == "object"
        assert "action" in params["properties"]

    @pytest.mark.asyncio
    async def test_unknown_action(self, tunnel_tool):
        result = await tunnel_tool.execute(action="invalid")
        assert not result.success
        assert "Unknown action" in result.error

    @pytest.mark.asyncio
    async def test_start_missing_port(self, tunnel_tool):
        result = await tunnel_tool.execute(action="start")
        assert not result.success
        assert "Port is required" in result.error

    @pytest.mark.asyncio
    async def test_start_blocked_port(self, tunnel_tool):
        with patch("tools.tunnel_tool.settings") as mock_settings:
            mock_settings.get_tunnel_allowed_ports.return_value = [8000, 3000]
            result = await tunnel_tool.execute(action="start", port=9999)
        assert not result.success
        assert "not in the allowed" in result.error

    @pytest.mark.asyncio
    async def test_start_approval_denied(self, tunnel_tool, approval_gate):
        approval_gate.request = AsyncMock(return_value=False)
        with patch("tools.tunnel_tool.settings") as mock_settings:
            mock_settings.get_tunnel_allowed_ports.return_value = []
            result = await tunnel_tool.execute(action="start", port=8000)
        assert not result.success
        assert "denied by approval gate" in result.error

    @pytest.mark.asyncio
    async def test_start_no_provider(self, tunnel_tool):
        with patch("tools.tunnel_tool.settings") as mock_settings:
            mock_settings.get_tunnel_allowed_ports.return_value = []
            mock_settings.tunnel_provider = "auto"
            mock_settings.tunnel_ttl_minutes = 60
            with patch("shutil.which", return_value=None):
                result = await tunnel_tool.execute(action="start", port=8000)
        assert not result.success
        assert "No tunnel provider" in result.error

    @pytest.mark.asyncio
    async def test_stop_missing_id(self, tunnel_tool):
        result = await tunnel_tool.execute(action="stop")
        assert not result.success
        assert "tunnel_id is required" in result.error

    @pytest.mark.asyncio
    async def test_stop_not_found(self, tunnel_tool):
        result = await tunnel_tool.execute(action="stop", tunnel_id="nonexistent")
        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_stop_existing_tunnel(self, tunnel_tool):
        mock_proc = MagicMock()
        mock_proc.terminate = MagicMock()
        mock_proc.wait = AsyncMock()
        mock_proc.returncode = None

        tunnel = TunnelInfo(
            id="test123",
            port=8000,
            provider="serveo",
            url="https://abc.serveo.net",
            process=mock_proc,
        )
        tunnel_tool._tunnels["test123"] = tunnel

        result = await tunnel_tool.execute(action="stop", tunnel_id="test123")
        assert result.success
        assert "stopped" in result.output.lower()

    @pytest.mark.asyncio
    async def test_status_missing_id(self, tunnel_tool):
        result = await tunnel_tool.execute(action="status")
        assert not result.success

    @pytest.mark.asyncio
    async def test_status_existing_tunnel(self, tunnel_tool):
        mock_proc = MagicMock()
        mock_proc.returncode = None

        tunnel = TunnelInfo(
            id="test456",
            port=3000,
            provider="cloudflared",
            url="https://xyz.trycloudflare.com",
            process=mock_proc,
        )
        tunnel_tool._tunnels["test456"] = tunnel

        result = await tunnel_tool.execute(action="status", tunnel_id="test456")
        assert result.success
        assert "xyz.trycloudflare.com" in result.output
        assert "Running: True" in result.output

    @pytest.mark.asyncio
    async def test_list_empty(self, tunnel_tool):
        result = await tunnel_tool.execute(action="list")
        assert result.success
        assert "No active" in result.output

    @pytest.mark.asyncio
    async def test_list_with_tunnels(self, tunnel_tool):
        tunnel = TunnelInfo(
            id="abc", port=8000, provider="serveo", url="https://abc.serveo.net"
        )
        tunnel_tool._tunnels["abc"] = tunnel

        result = await tunnel_tool.execute(action="list")
        assert result.success
        assert "abc" in result.output
        assert "8000" in result.output

    @pytest.mark.asyncio
    async def test_cleanup(self, tunnel_tool):
        mock_proc = MagicMock()
        mock_proc.terminate = MagicMock()
        mock_proc.wait = AsyncMock()
        mock_proc.kill = MagicMock()
        mock_proc.returncode = None

        tunnel = TunnelInfo(id="t1", port=8000, process=mock_proc)
        tunnel_tool._tunnels["t1"] = tunnel

        await tunnel_tool.cleanup()
        assert len(tunnel_tool._tunnels) == 0
        mock_proc.terminate.assert_called_once()
