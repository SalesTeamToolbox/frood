"""Tests for task-type tool enforcement in the iteration engine.

Verifies that:
1. _execute_tool_calls blocks code-only tools for non-code tasks
2. _run_tool_loop uses schemas_for_task_type (not all_schemas) per round
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from agents.iteration_engine import IterationEngine
from agents.model_router import ModelRouter


class FakeToolCall:
    """Mimics an OpenAI tool_call object."""

    def __init__(self, name: str, arguments: dict):
        self.id = f"call_{name}"
        self.function = MagicMock()
        self.function.name = name
        self.function.arguments = json.dumps(arguments)


class TestExecuteToolCallsEnforcement:
    """Test that _execute_tool_calls enforces task-type restrictions."""

    def setup_method(self):
        router = ModelRouter()
        self.engine = IterationEngine(
            router,
            tool_registry=MagicMock(),
            approval_gate=None,
            agent_id="test-agent",
        )
        # Mock the registry execute to return success
        self.engine.tool_registry.execute = AsyncMock(
            return_value=MagicMock(content="ok", success=True)
        )

    @pytest.mark.asyncio
    async def test_blocks_shell_for_content_task(self):
        """Shell tool should be blocked for content tasks."""
        calls = [FakeToolCall("shell", {"command": "ls"})]
        records = await self.engine._execute_tool_calls(calls, task_id="t1", task_type="content")
        assert len(records) == 1
        assert records[0].success is False
        assert "not available" in records[0].result

    @pytest.mark.asyncio
    async def test_blocks_security_analyzer_for_email_task(self):
        """security_analyzer should be blocked for email tasks."""
        calls = [FakeToolCall("security_analyzer", {"target": "/app"})]
        records = await self.engine._execute_tool_calls(calls, task_id="t1", task_type="email")
        assert len(records) == 1
        assert records[0].success is False
        assert "not available" in records[0].result

    @pytest.mark.asyncio
    async def test_allows_shell_for_coding_task(self):
        """Shell tool should be allowed for coding tasks."""
        calls = [FakeToolCall("shell", {"command": "ls"})]
        records = await self.engine._execute_tool_calls(calls, task_id="t1", task_type="coding")
        assert len(records) == 1
        assert records[0].success is True

    @pytest.mark.asyncio
    async def test_allows_general_tool_for_any_task(self):
        """Non-code-only tools should work for any task type."""
        calls = [FakeToolCall("web_search", {"query": "test"})]
        records = await self.engine._execute_tool_calls(calls, task_id="t1", task_type="marketing")
        assert len(records) == 1
        assert records[0].success is True

    @pytest.mark.asyncio
    async def test_blocks_git_for_strategy_task(self):
        """git tool should be blocked for strategy tasks."""
        calls = [FakeToolCall("git", {"action": "status"})]
        records = await self.engine._execute_tool_calls(calls, task_id="t1", task_type="strategy")
        assert len(records) == 1
        assert records[0].success is False

    @pytest.mark.asyncio
    async def test_allows_shell_for_debugging_task(self):
        """Shell tool should be allowed for debugging tasks (code task type)."""
        calls = [FakeToolCall("shell", {"command": "ls"})]
        records = await self.engine._execute_tool_calls(calls, task_id="t1", task_type="debugging")
        assert len(records) == 1
        assert records[0].success is True

    @pytest.mark.asyncio
    async def test_mixed_tools_partial_block(self):
        """Mix of allowed and blocked tools — only blocked ones fail."""
        calls = [
            FakeToolCall("web_search", {"query": "test"}),  # allowed
            FakeToolCall("shell", {"command": "ls"}),  # blocked for content
        ]
        records = await self.engine._execute_tool_calls(calls, task_id="t1", task_type="content")
        assert len(records) == 2
        assert records[0].success is True  # web_search allowed
        assert records[1].success is False  # shell blocked


class TestTaskQueueAssignedResetOnLoad:
    """Test that ASSIGNED tasks are reset to PENDING on load."""

    @pytest.mark.asyncio
    async def test_assigned_task_reset_to_pending(self, tmp_path):
        """ASSIGNED tasks should be reset to PENDING when loaded from file."""
        import aiofiles

        from core.task_queue import Task, TaskQueue, TaskStatus

        # Create a tasks file with an ASSIGNED task
        task = Task(title="Assigned Task", description="Was assigned")
        task.status = TaskStatus.ASSIGNED
        tasks_data = [task.to_dict()]

        json_path = tmp_path / "tasks.json"
        async with aiofiles.open(json_path, "w") as f:
            await f.write(json.dumps(tasks_data))

        # Load it
        queue = TaskQueue(tasks_json_path=str(json_path))
        await queue.load_from_file()

        # The task should now be PENDING
        loaded = queue._tasks.get(task.id)
        assert loaded is not None
        assert loaded.status == TaskStatus.PENDING


class TestSessionManagerAsync:
    """Test that SessionManager write methods are async."""

    def test_add_message_is_coroutine(self):
        """add_message should be an async method."""
        import asyncio

        from memory.session import SessionManager

        mgr = SessionManager("/tmp/test-sessions-unused")
        assert asyncio.iscoroutinefunction(mgr.add_message)

    def test_set_active_scope_is_coroutine(self):
        """set_active_scope should be an async method."""
        import asyncio

        from memory.session import SessionManager

        mgr = SessionManager("/tmp/test-sessions-unused")
        assert asyncio.iscoroutinefunction(mgr.set_active_scope)

    @pytest.mark.asyncio
    async def test_add_message_writes_file(self, tmp_path):
        """add_message should persist to JSONL file asynchronously."""
        from memory.session import SessionManager, SessionMessage

        mgr = SessionManager(tmp_path / "sessions")
        msg = SessionMessage(role="user", content="hello")
        await mgr.add_message("test", "chan1", msg)

        # Verify file was created
        session_path = mgr._session_path("test_chan1")
        assert session_path.exists()
        content = session_path.read_text()
        assert "hello" in content
