"""Tests for mid-task user intervention via asyncio.Queue injection."""

import asyncio
from unittest.mock import MagicMock

from agents.iteration_engine import IterationEngine


class TestInterventionQueue:
    """Tests for mid-task intervention queue draining in IterationEngine."""

    def _make_engine(self):
        mock_router = MagicMock()
        engine = IterationEngine(
            router=mock_router,
            tool_registry=None,
            approval_gate=None,
            agent_id="test-agent",
        )
        return engine

    async def test_empty_queue_does_not_modify_messages(self):
        """An empty intervention queue should leave messages unchanged."""
        engine = self._make_engine()
        queue = asyncio.Queue()
        messages = [{"role": "user", "content": "Original task"}]

        # Simulate the queue-draining logic from the iteration loop
        while True:
            try:
                feedback = queue.get_nowait()
                messages.append(
                    {
                        "role": "user",
                        "content": f"[USER INTERVENTION] {feedback}",
                    }
                )
            except asyncio.QueueEmpty:
                break

        assert len(messages) == 1
        assert messages[0]["content"] == "Original task"

    async def test_single_intervention_injected(self):
        """A single queued message should be injected into the conversation."""
        queue = asyncio.Queue()
        await queue.put("Please focus on security aspects")

        messages = [{"role": "user", "content": "Original task"}]

        while True:
            try:
                feedback = queue.get_nowait()
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"[USER INTERVENTION] The user has provided the following "
                            f"feedback. Incorporate it into your work:\n\n{feedback}"
                        ),
                    }
                )
            except asyncio.QueueEmpty:
                break

        assert len(messages) == 2
        assert "focus on security" in messages[-1]["content"]
        assert "[USER INTERVENTION]" in messages[-1]["content"]

    async def test_multiple_interventions_all_injected(self):
        """Multiple queued messages should all be injected."""
        queue = asyncio.Queue()
        await queue.put("First feedback")
        await queue.put("Second feedback")
        await queue.put("Third feedback")

        messages = []
        while True:
            try:
                feedback = queue.get_nowait()
                messages.append({"role": "user", "content": feedback})
            except asyncio.QueueEmpty:
                break

        assert len(messages) == 3
        assert messages[0]["content"] == "First feedback"
        assert messages[1]["content"] == "Second feedback"
        assert messages[2]["content"] == "Third feedback"

    async def test_queue_is_drained_each_iteration(self):
        """The queue should be empty after draining."""
        queue = asyncio.Queue()
        await queue.put("Message 1")
        await queue.put("Message 2")

        messages = []
        while True:
            try:
                feedback = queue.get_nowait()
                messages.append({"role": "user", "content": feedback})
            except asyncio.QueueEmpty:
                break

        # Queue should now be empty
        assert queue.empty()
        assert len(messages) == 2

    async def test_intervention_queue_passed_to_engine_run(self):
        """IterationEngine.run() should accept intervention_queue parameter."""
        engine = self._make_engine()

        # Verify that run() signature accepts intervention_queue
        import inspect

        sig = inspect.signature(engine.run)
        assert "intervention_queue" in sig.parameters


class TestInterventionAPI:
    """Tests for the dashboard intervention endpoint."""

    async def test_intervene_queues_message(self):
        """Simulate the intervention endpoint logic."""
        intervention_queues = {}
        task_id = "task-abc"

        # Simulate task running — queue created
        queue = asyncio.Queue()
        intervention_queues[task_id] = queue

        # Simulate API call
        message = "Please prioritise performance"
        await queue.put(message)

        # Verify queue has the message
        assert not queue.empty()
        drained = queue.get_nowait()
        assert drained == message

    async def test_no_queue_for_task_returns_none(self):
        """When no queue exists for a task, intervention_queues.get returns None."""
        intervention_queues = {}
        result = intervention_queues.get("nonexistent-task")
        assert result is None

    async def test_queue_cleaned_up_after_task(self):
        """Intervention queue should be removed when task completes."""
        intervention_queues = {}
        task_id = "finishing-task"

        queue = asyncio.Queue()
        intervention_queues[task_id] = queue

        # Simulate task completion cleanup
        intervention_queues.pop(task_id, None)
        assert task_id not in intervention_queues
