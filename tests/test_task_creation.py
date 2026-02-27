"""Tests for task creation fixes — pending_messages, find_active_task, route_message_to_task."""

import asyncio
import time

import pytest

from core.task_queue import Task, TaskQueue, TaskStatus, TaskType


class TestPendingMessages:
    """Test the pending_messages field on Task."""

    def test_default_empty(self):
        task = Task(title="T", description="D")
        assert task.pending_messages == []

    def test_add_pending_message(self):
        task = Task(title="T", description="D")
        task.add_pending_message("Hello", sender="alice")
        assert len(task.pending_messages) == 1
        assert task.pending_messages[0]["content"] == "Hello"
        assert task.pending_messages[0]["sender"] == "alice"
        assert "timestamp" in task.pending_messages[0]

    def test_add_multiple_pending_messages(self):
        task = Task(title="T", description="D")
        task.add_pending_message("First")
        task.add_pending_message("Second")
        assert len(task.pending_messages) == 2
        assert task.pending_messages[0]["content"] == "First"
        assert task.pending_messages[1]["content"] == "Second"

    def test_add_pending_message_updates_timestamp(self):
        task = Task(title="T", description="D")
        old = task.updated_at
        # Ensure time advances
        time.sleep(0.01)
        task.add_pending_message("msg")
        assert task.updated_at >= old

    def test_pending_messages_roundtrip(self):
        """pending_messages survive to_dict/from_dict serialization."""
        task = Task(title="T", description="D")
        task.add_pending_message("Buffered", sender="bob")
        d = task.to_dict()
        assert "pending_messages" in d
        assert len(d["pending_messages"]) == 1

        restored = Task.from_dict(d)
        assert len(restored.pending_messages) == 1
        assert restored.pending_messages[0]["content"] == "Buffered"
        assert restored.pending_messages[0]["sender"] == "bob"


class TestFindActiveTask:
    """Test TaskQueue.find_active_task()."""

    def setup_method(self):
        self.queue = TaskQueue(tasks_json_path="/dev/null")

    def _add_task(self, **kwargs):
        """Add a task directly to the queue's internal dict (bypassing async add)."""
        task = Task(**kwargs)
        self.queue._tasks[task.id] = task
        return task

    def test_no_tasks_returns_none(self):
        result = self.queue.find_active_task(origin_channel="discord", origin_channel_id="chan1")
        assert result is None

    def test_finds_pending_task_by_channel(self):
        task = self._add_task(
            title="T",
            description="D",
            status=TaskStatus.PENDING,
            origin_channel="discord",
            origin_channel_id="chan1",
        )
        result = self.queue.find_active_task(origin_channel="discord", origin_channel_id="chan1")
        assert result is not None
        assert result.id == task.id

    def test_finds_running_task_by_channel(self):
        task = self._add_task(
            title="T",
            description="D",
            status=TaskStatus.RUNNING,
            origin_channel="slack",
            origin_channel_id="chan2",
        )
        result = self.queue.find_active_task(origin_channel="slack", origin_channel_id="chan2")
        assert result is not None
        assert result.id == task.id

    def test_ignores_done_tasks(self):
        self._add_task(
            title="T",
            description="D",
            status=TaskStatus.DONE,
            origin_channel="discord",
            origin_channel_id="chan1",
        )
        result = self.queue.find_active_task(origin_channel="discord", origin_channel_id="chan1")
        assert result is None

    def test_ignores_failed_tasks(self):
        self._add_task(
            title="T",
            description="D",
            status=TaskStatus.FAILED,
            origin_channel="discord",
            origin_channel_id="chan1",
        )
        result = self.queue.find_active_task(origin_channel="discord", origin_channel_id="chan1")
        assert result is None

    def test_finds_most_recent_active_task(self):
        t1 = self._add_task(
            title="Old",
            description="D",
            status=TaskStatus.PENDING,
            origin_channel="discord",
            origin_channel_id="chan1",
            created_at=1000.0,
        )
        t2 = self._add_task(
            title="New",
            description="D",
            status=TaskStatus.RUNNING,
            origin_channel="discord",
            origin_channel_id="chan1",
            created_at=2000.0,
        )
        result = self.queue.find_active_task(origin_channel="discord", origin_channel_id="chan1")
        assert result.id == t2.id

    def test_finds_by_session_id(self):
        task = self._add_task(
            title="T",
            description="D",
            status=TaskStatus.RUNNING,
            origin_channel="dashboard_chat",
            origin_channel_id="chat",
            origin_metadata={"chat_session_id": "sess-abc"},
        )
        result = self.queue.find_active_task(session_id="sess-abc")
        assert result is not None
        assert result.id == task.id

    def test_session_id_takes_priority(self):
        """When session_id is provided, channel match is ignored."""
        self._add_task(
            title="Channel match",
            description="D",
            status=TaskStatus.RUNNING,
            origin_channel="dashboard_chat",
            origin_channel_id="chat",
        )
        task = self._add_task(
            title="Session match",
            description="D",
            status=TaskStatus.RUNNING,
            origin_channel="dashboard_chat",
            origin_channel_id="chat",
            origin_metadata={"chat_session_id": "sess-xyz"},
        )
        result = self.queue.find_active_task(session_id="sess-xyz")
        assert result.id == task.id

    def test_no_match_different_channel(self):
        self._add_task(
            title="T",
            description="D",
            status=TaskStatus.RUNNING,
            origin_channel="discord",
            origin_channel_id="chan1",
        )
        result = self.queue.find_active_task(origin_channel="slack", origin_channel_id="chan2")
        assert result is None


class TestRouteMessageToTask:
    """Test TaskQueue.route_message_to_task()."""

    def setup_method(self):
        self.queue = TaskQueue(tasks_json_path="/dev/null")

    @pytest.mark.asyncio
    async def test_routes_to_intervention_queue_when_running(self):
        task = Task(title="T", description="D", status=TaskStatus.RUNNING)
        intervention_queue = asyncio.Queue()
        intervention_queues = {task.id: intervention_queue}

        await self.queue.route_message_to_task(
            task,
            "Follow-up",
            "alice",
            intervention_queues,
        )

        assert not intervention_queue.empty()
        msg = await intervention_queue.get()
        assert msg == "Follow-up"

    @pytest.mark.asyncio
    async def test_buffers_to_pending_when_no_intervention_queue(self):
        task = Task(title="T", description="D", status=TaskStatus.PENDING)
        intervention_queues = {}  # No queue for this task

        await self.queue.route_message_to_task(
            task,
            "Buffered msg",
            "bob",
            intervention_queues,
        )

        assert len(task.pending_messages) == 1
        assert task.pending_messages[0]["content"] == "Buffered msg"
        assert task.pending_messages[0]["sender"] == "bob"

    @pytest.mark.asyncio
    async def test_multiple_messages_buffered_in_order(self):
        task = Task(title="T", description="D", status=TaskStatus.PENDING)

        await self.queue.route_message_to_task(task, "First", "u", {})
        await self.queue.route_message_to_task(task, "Second", "u", {})
        await self.queue.route_message_to_task(task, "Third", "u", {})

        assert len(task.pending_messages) == 3
        assert task.pending_messages[0]["content"] == "First"
        assert task.pending_messages[1]["content"] == "Second"
        assert task.pending_messages[2]["content"] == "Third"


class TestClassificationNeedsProject:
    """Test that needs_project field exists on ClassificationResult."""

    def test_needs_project_default_false(self):
        from core.intent_classifier import ClassificationResult

        result = ClassificationResult(task_type=TaskType.CODING)
        assert result.needs_project is False

    def test_needs_project_can_be_set(self):
        from core.intent_classifier import ClassificationResult

        result = ClassificationResult(task_type=TaskType.CODING, needs_project=True)
        assert result.needs_project is True

    def test_needs_project_setup_implies_needs_project(self):
        """If needs_project_setup is True, needs_project should also be True."""
        from core.intent_classifier import ClassificationResult

        result = ClassificationResult(
            task_type=TaskType.CODING,
            needs_project_setup=True,
            needs_project=True,
        )
        assert result.needs_project is True
        assert result.needs_project_setup is True
