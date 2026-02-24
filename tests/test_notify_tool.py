"""Tests for NotifyUserTool — real-time mid-task user notifications."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from tools.notify_tool import NotifyUserTool, resolve_input


class TestNotifyUserTool:
    def setup_method(self):
        self.mock_ws = MagicMock()
        self.mock_ws.broadcast = AsyncMock()
        self.tool = NotifyUserTool(ws_manager=self.mock_ws, task_id="test-task-001")

    def test_tool_name(self):
        assert self.tool.name == "notify_user"

    def test_tool_has_parameters(self):
        params = self.tool.parameters
        assert params["type"] == "object"
        assert "operation" in params["properties"]
        assert "message" in params["properties"]
        assert "level" in params["properties"]
        assert "progress" in params["properties"]
        assert "question" in params["properties"]

    async def test_notify_broadcasts_event(self):
        result = await self.tool.execute(
            operation="notify",
            message="Starting analysis...",
            level="info",
        )
        assert result.success
        assert "Starting analysis" in result.output
        self.mock_ws.broadcast.assert_called_once()
        call_args = self.mock_ws.broadcast.call_args
        assert call_args[0][0] == "agent_notification"
        data = call_args[0][1]
        assert data["level"] == "info"
        assert data["message"] == "Starting analysis..."

    async def test_notify_invalid_level_defaults_to_info(self):
        result = await self.tool.execute(
            operation="notify",
            message="Test message",
            level="invalid_level",
        )
        assert result.success
        call_args = self.mock_ws.broadcast.call_args
        data = call_args[0][1]
        assert data["level"] == "info"

    async def test_notify_missing_message_fails(self):
        result = await self.tool.execute(operation="notify", message="")
        assert not result.success

    async def test_progress_broadcasts_event(self):
        result = await self.tool.execute(operation="progress", progress=42)
        assert result.success
        assert "42%" in result.output
        self.mock_ws.broadcast.assert_called_once()
        call_args = self.mock_ws.broadcast.call_args
        assert call_args[0][0] == "agent_progress"
        data = call_args[0][1]
        assert data["progress"] == 42

    async def test_progress_clamped_to_range(self):
        result = await self.tool.execute(operation="progress", progress=150)
        assert result.success
        data = self.mock_ws.broadcast.call_args[0][1]
        assert data["progress"] == 100

        self.mock_ws.broadcast.reset_mock()
        result = await self.tool.execute(operation="progress", progress=-10)
        assert result.success
        data = self.mock_ws.broadcast.call_args[0][1]
        assert data["progress"] == 0

    async def test_progress_missing_value_fails(self):
        result = await self.tool.execute(operation="progress")
        assert not result.success

    async def test_notify_without_ws_manager(self):
        tool = NotifyUserTool(ws_manager=None, task_id="task-x")
        result = await tool.execute(operation="notify", message="Hello", level="warning")
        assert result.success  # Logs but doesn't crash

    async def test_unknown_operation_fails(self):
        result = await self.tool.execute(operation="unknown_op")
        assert not result.success

    async def test_request_input_timeout(self):
        """request_input should time out gracefully when no response arrives."""
        tool = NotifyUserTool(ws_manager=self.mock_ws, task_id="timeout-task")
        tool.INPUT_TIMEOUT = 0.1  # Very short timeout for testing

        result = await tool.execute(
            operation="request_input",
            question="What is your preferred language?",
        )
        # Should succeed but indicate timeout
        assert result.success
        assert "No response" in result.output or "Continuing" in result.output

    async def test_resolve_input_resolves_future(self):
        """resolve_input() should unblock a pending request_input call."""
        tool = NotifyUserTool(ws_manager=self.mock_ws, task_id="resolve-task")

        # Start request_input in background
        async def provide_response():
            await asyncio.sleep(0.05)
            resolve_input("resolve-task", "Python")

        task = asyncio.create_task(provide_response())
        result = await tool.execute(
            operation="request_input",
            question="Preferred language?",
        )
        await task
        assert result.success
        assert "Python" in result.output

    async def test_task_id_from_kwargs(self):
        """Tool should fall back to agent_id from kwargs when task_id not set."""
        tool = NotifyUserTool(ws_manager=self.mock_ws, task_id="")
        result = await tool.execute(
            operation="notify",
            message="Hello",
            level="info",
            agent_id="inferred-task-id",
        )
        assert result.success
        data = self.mock_ws.broadcast.call_args[0][1]
        assert data["task_id"] == "inferred-task-id"
