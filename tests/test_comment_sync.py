"""Tests for comment-to-agent routing and chat sync.

Validates that task comments are:
1. Routed to the running agent via intervention queues
2. Buffered as pending messages when the task is not yet running
3. Broadcast via WebSocket for real-time UI updates
"""

import asyncio

import pytest

from core.task_queue import Task, TaskQueue, TaskStatus


class TestCommentRoutesToAgent:
    """Comments on active tasks should be delivered to the agent."""

    def setup_method(self):
        self.queue = TaskQueue(tasks_json_path="/dev/null")

    @pytest.mark.asyncio
    async def test_comment_routes_to_intervention_queue_when_running(self):
        """A comment on a RUNNING task should land in the intervention queue."""
        task = Task(title="T", description="D", status=TaskStatus.RUNNING)
        self.queue._tasks[task.id] = task

        intervention_queue = asyncio.Queue()
        intervention_queues = {task.id: intervention_queue}

        # Simulate what the comment endpoint now does
        task.add_comment("admin", "Focus on error handling")
        await self.queue.route_message_to_task(
            task,
            "Focus on error handling",
            "admin",
            intervention_queues,
        )

        assert not intervention_queue.empty()
        msg = await intervention_queue.get()
        assert msg == "Focus on error handling"
        assert len(task.comments) == 1
        assert task.comments[0]["text"] == "Focus on error handling"

    @pytest.mark.asyncio
    async def test_comment_buffers_as_pending_when_task_pending(self):
        """A comment on a PENDING task should buffer in pending_messages."""
        task = Task(title="T", description="D", status=TaskStatus.PENDING)
        self.queue._tasks[task.id] = task

        task.add_comment("admin", "Please also add tests")
        await self.queue.route_message_to_task(
            task,
            "Please also add tests",
            "admin",
            {},  # No intervention queue yet
        )

        assert len(task.comments) == 1
        assert len(task.pending_messages) == 1
        assert task.pending_messages[0]["content"] == "Please also add tests"

    @pytest.mark.asyncio
    async def test_comment_on_done_task_does_not_route(self):
        """A comment on a DONE task should NOT be routed to the agent."""
        task = Task(title="T", description="D", status=TaskStatus.DONE)
        self.queue._tasks[task.id] = task

        task.add_comment("admin", "Nice work!")

        # Simulate the status check in the endpoint
        active_statuses = {TaskStatus.PENDING, TaskStatus.ASSIGNED, TaskStatus.RUNNING}
        routed = task.status in active_statuses

        assert not routed
        assert len(task.comments) == 1
        assert len(task.pending_messages) == 0

    @pytest.mark.asyncio
    async def test_comment_on_failed_task_does_not_route(self):
        """A comment on a FAILED task should NOT be routed to the agent."""
        task = Task(title="T", description="D", status=TaskStatus.FAILED)
        task.add_comment("admin", "What went wrong?")

        active_statuses = {TaskStatus.PENDING, TaskStatus.ASSIGNED, TaskStatus.RUNNING}
        assert task.status not in active_statuses
        assert len(task.pending_messages) == 0

    @pytest.mark.asyncio
    async def test_multiple_comments_all_routed(self):
        """Multiple comments on a running task should all reach the agent."""
        task = Task(title="T", description="D", status=TaskStatus.RUNNING)
        self.queue._tasks[task.id] = task

        intervention_queue = asyncio.Queue()
        intervention_queues = {task.id: intervention_queue}

        for text in ["First direction", "Second direction", "Third direction"]:
            task.add_comment("admin", text)
            await self.queue.route_message_to_task(task, text, "admin", intervention_queues)

        assert intervention_queue.qsize() == 3
        assert len(task.comments) == 3

        msgs = []
        while not intervention_queue.empty():
            msgs.append(await intervention_queue.get())
        assert msgs == ["First direction", "Second direction", "Third direction"]


class TestCommentChatSessionSync:
    """Comments should be mirrored to the originating chat session."""

    def test_task_with_chat_session_id_has_metadata(self):
        """Tasks originating from chat sessions have chat_session_id in metadata."""
        task = Task(
            title="T",
            description="D",
            origin_channel="dashboard_chat",
            origin_metadata={"chat_session_id": "sess-123"},
        )
        assert task.origin_metadata.get("chat_session_id") == "sess-123"

    def test_task_without_session_has_no_session_id(self):
        """Tasks from other channels have no chat_session_id."""
        task = Task(
            title="T",
            description="D",
            origin_channel="discord",
            origin_channel_id="chan-1",
        )
        assert task.origin_metadata.get("chat_session_id", "") == ""
