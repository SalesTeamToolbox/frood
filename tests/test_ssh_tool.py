"""Tests for SSH remote shell tool."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.approval_gate import ApprovalGate, ProtectedAction
from core.command_filter import CommandFilter
from core.sandbox import WorkspaceSandbox
from tools.ssh_tool import SSHTool, _sanitize_output


@pytest.fixture
def sandbox(tmp_path):
    return WorkspaceSandbox(tmp_path, enabled=True)


@pytest.fixture
def command_filter():
    return CommandFilter()


@pytest.fixture
def approval_gate():
    gate = MagicMock(spec=ApprovalGate)
    gate.request = AsyncMock(return_value=True)
    return gate


@pytest.fixture
def ssh_tool(sandbox, command_filter, approval_gate):
    return SSHTool(sandbox, command_filter, approval_gate)


class TestSSHTool:
    def test_tool_properties(self, ssh_tool):
        assert ssh_tool.name == "ssh"
        assert "SSH" in ssh_tool.description or "ssh" in ssh_tool.description.lower()
        params = ssh_tool.parameters
        assert params["type"] == "object"
        assert "action" in params["properties"]

    @pytest.mark.asyncio
    async def test_unknown_action(self, ssh_tool):
        result = await ssh_tool.execute(action="invalid")
        assert not result.success
        assert "Unknown action" in result.error

    @pytest.mark.asyncio
    async def test_connect_missing_host(self, ssh_tool):
        result = await ssh_tool.execute(action="connect", username="user")
        assert not result.success
        assert "Host is required" in result.error

    @pytest.mark.asyncio
    async def test_connect_missing_username(self, ssh_tool):
        result = await ssh_tool.execute(action="connect", host="example.com")
        assert not result.success
        assert "Username is required" in result.error

    @pytest.mark.asyncio
    async def test_connect_blocked_by_allowlist(self, ssh_tool):
        with patch("tools.ssh_tool.settings") as mock_settings:
            mock_settings.get_ssh_allowed_hosts.return_value = ["*.allowed.com"]
            result = await ssh_tool.execute(
                action="connect", host="blocked.evil.com", username="user"
            )
        assert not result.success
        assert "not in the SSH allowed hosts" in result.error

    @pytest.mark.asyncio
    async def test_connect_approval_denied(self, ssh_tool, approval_gate):
        approval_gate.request = AsyncMock(return_value=False)
        with patch("tools.ssh_tool.settings") as mock_settings:
            mock_settings.get_ssh_allowed_hosts.return_value = []
            result = await ssh_tool.execute(
                action="connect", host="example.com", username="user"
            )
        assert not result.success
        assert "denied by approval gate" in result.error

    @pytest.mark.asyncio
    async def test_connect_asyncssh_not_installed(self, ssh_tool):
        with patch("tools.ssh_tool.settings") as mock_settings:
            mock_settings.get_ssh_allowed_hosts.return_value = []
            with patch.dict("sys.modules", {"asyncssh": None}):
                result = await ssh_tool.execute(
                    action="connect", host="example.com", username="user"
                )
        # Should fail with import error or connection error
        assert not result.success

    @pytest.mark.asyncio
    async def test_execute_not_connected(self, ssh_tool):
        result = await ssh_tool.execute(
            action="execute", host="example.com", command="ls"
        )
        assert not result.success
        assert "Not connected" in result.error

    @pytest.mark.asyncio
    async def test_execute_command_filter_blocks(self, ssh_tool):
        """Dangerous commands should be blocked even for remote execution."""
        # First simulate a connection
        from tools.ssh_tool import SSHConnection
        import time

        mock_conn = MagicMock()
        ssh_tool._connections["example.com:22"] = SSHConnection(
            host="example.com",
            port=22,
            username="user",
            conn=mock_conn,
            approved=True,
            connected_at=time.time(),
        )

        result = await ssh_tool.execute(
            action="execute", host="example.com", command="rm -rf /"
        )
        assert not result.success
        assert "blocked" in result.error.lower() or "filter" in result.error.lower()

    @pytest.mark.asyncio
    async def test_execute_command_success(self, ssh_tool):
        """Test successful command execution."""
        from tools.ssh_tool import SSHConnection
        import time

        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.stdout = "hello world\n"
        mock_result.stderr = ""
        mock_result.exit_status = 0
        mock_conn.run = AsyncMock(return_value=mock_result)

        ssh_tool._connections["example.com:22"] = SSHConnection(
            host="example.com",
            port=22,
            username="user",
            conn=mock_conn,
            approved=True,
            connected_at=time.time(),
        )

        with patch("tools.ssh_tool.settings") as mock_settings:
            mock_settings.ssh_command_timeout = 120
            result = await ssh_tool.execute(
                action="execute", host="example.com", command="echo hello world"
            )

        assert result.success
        assert "hello world" in result.output

    @pytest.mark.asyncio
    async def test_disconnect(self, ssh_tool):
        from tools.ssh_tool import SSHConnection
        import time

        mock_conn = MagicMock()
        ssh_tool._connections["example.com:22"] = SSHConnection(
            host="example.com",
            port=22,
            username="user",
            conn=mock_conn,
            approved=True,
            connected_at=time.time(),
        )

        result = await ssh_tool.execute(action="disconnect", host="example.com")
        assert result.success
        assert "Disconnected" in result.output
        assert "example.com:22" not in ssh_tool._connections

    @pytest.mark.asyncio
    async def test_disconnect_not_connected(self, ssh_tool):
        result = await ssh_tool.execute(action="disconnect", host="example.com")
        assert result.success
        assert "No active connection" in result.output

    @pytest.mark.asyncio
    async def test_list_connections_empty(self, ssh_tool):
        result = await ssh_tool.execute(action="list_connections")
        assert result.success
        assert "No active" in result.output

    @pytest.mark.asyncio
    async def test_list_connections_with_active(self, ssh_tool):
        from tools.ssh_tool import SSHConnection
        import time

        mock_conn = MagicMock()
        ssh_tool._connections["example.com:22"] = SSHConnection(
            host="example.com",
            port=22,
            username="user",
            conn=mock_conn,
            approved=True,
            connected_at=time.time(),
        )

        result = await ssh_tool.execute(action="list_connections")
        assert result.success
        assert "example.com" in result.output

    @pytest.mark.asyncio
    async def test_upload_missing_params(self, ssh_tool):
        result = await ssh_tool.execute(action="upload", host="example.com")
        assert not result.success
        assert "required" in result.error.lower()

    @pytest.mark.asyncio
    async def test_download_missing_params(self, ssh_tool):
        result = await ssh_tool.execute(action="download", host="example.com")
        assert not result.success
        assert "required" in result.error.lower()


class TestSanitizeOutput:
    def test_redacts_password(self):
        text = "password=mysecret123"
        sanitized = _sanitize_output(text)
        assert "mysecret123" not in sanitized
        assert "REDACTED" in sanitized

    def test_redacts_api_key(self):
        text = "api_key=sk-1234567890abcdef"
        sanitized = _sanitize_output(text)
        assert "sk-1234567890abcdef" not in sanitized

    def test_redacts_aws_key(self):
        text = "found key AKIAIOSFODNN7EXAMPLE"
        sanitized = _sanitize_output(text)
        assert "AKIAIOSFODNN7EXAMPLE" not in sanitized

    def test_redacts_github_token(self):
        text = "token: ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij"
        sanitized = _sanitize_output(text)
        assert "ghp_ABCDEF" not in sanitized

    def test_preserves_normal_text(self):
        text = "hello world\nthis is fine"
        assert _sanitize_output(text) == text

    @pytest.mark.asyncio
    async def test_cleanup(self, ssh_tool):
        from tools.ssh_tool import SSHConnection
        import time

        mock_conn = MagicMock()
        ssh_tool._connections["host1:22"] = SSHConnection(
            host="host1", port=22, username="u",
            conn=mock_conn, approved=True, connected_at=time.time(),
        )
        ssh_tool._approved_hosts.add("host1:22")

        await ssh_tool.cleanup()
        assert len(ssh_tool._connections) == 0
        assert len(ssh_tool._approved_hosts) == 0
        mock_conn.close.assert_called_once()
