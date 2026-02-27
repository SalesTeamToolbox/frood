"""Tests for audit fixes: retry, convergence, approval timeout, task inference, dedup."""

import asyncio
import tempfile
from unittest.mock import AsyncMock, MagicMock

import pytest

from agents.iteration_engine import SIMILARITY_THRESHOLD, IterationEngine
from core.approval_gate import ApprovalGate, ProtectedAction
from core.task_queue import TaskQueue, TaskStatus, TaskType, infer_task_type

# -- Iteration Engine: Retry + Convergence -----------------------------------


class TestIterationRetry:
    """Tests for API call retry with exponential backoff."""

    def setup_method(self):
        self.router = MagicMock()
        self.engine = IterationEngine(self.router)

    @pytest.mark.asyncio
    async def test_retry_succeeds_on_second_attempt(self):
        """Should retry on failure and succeed."""
        self.router.complete = AsyncMock(
            side_effect=[Exception("timeout"), ("success output", None)]
        )
        result = await self.engine._complete_with_retry("test-model", [], retries=2)
        assert result == "success output"
        assert self.router.complete.call_count == 2

    @pytest.mark.asyncio
    async def test_retry_falls_back_to_fallback_model(self):
        """After all retries fail, should try fallback model."""
        self.router.complete = AsyncMock(
            side_effect=[
                Exception("fail 1"),
                Exception("fail 2"),
                ("fallback output", None),  # This is the fallback call
            ]
        )
        result = await self.engine._complete_with_retry("test-model", [], retries=2)
        assert result == "fallback output"
        # 2 retries on test-model + 1 fallback call
        assert self.router.complete.call_count == 3

    @pytest.mark.asyncio
    async def test_retry_raises_after_all_attempts_fail(self):
        """If all retries AND fallback fail, should raise RuntimeError."""
        self.router.complete = AsyncMock(side_effect=Exception("always fails"))
        with pytest.raises(RuntimeError, match="API call failed"):
            await self.engine._complete_with_retry("or-free-llama-70b", [], retries=2)

    @pytest.mark.asyncio
    async def test_full_iteration_uses_retry(self):
        """The full iteration loop should survive a transient API failure."""
        call_count = 0

        async def flaky_complete(model, messages, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("transient error")
            return ("APPROVED: Looks good", None)

        self.router.complete = flaky_complete
        history = await self.engine.run(
            task_description="test task",
            primary_model="test-model",
            critic_model="test-critic",
            max_iterations=3,
        )
        assert history.total_iterations == 1
        assert history.final_output is not None


class TestPaymentErrorDetection:
    """Tests for 402 Payment Required / spending-limit error handling."""

    def setup_method(self):
        self.router = MagicMock()
        self.engine = IterationEngine(self.router)

    def test_detects_402_status_code(self):
        """Should detect 402 status code as payment error."""
        err = Exception("Error code: 402 - Provider returned error")
        assert self.engine._is_payment_error(err) is True

    def test_detects_spending_limit_message(self):
        """Should detect spending limit keywords."""
        err = Exception("API key USD spend limit exceeded")
        assert self.engine._is_payment_error(err) is True

    def test_detects_payment_required_message(self):
        """Should detect 'payment required' phrasing."""
        err = Exception("Payment required: insufficient credits")
        assert self.engine._is_payment_error(err) is True

    def test_normal_error_is_not_payment(self):
        """Normal errors should not be detected as payment errors."""
        err = Exception("Connection timeout")
        assert self.engine._is_payment_error(err) is False

    def test_429_is_not_payment(self):
        """429 rate limit should not be detected as payment error."""
        err = Exception("Error code: 429 - rate limited")
        assert self.engine._is_payment_error(err) is False

    @pytest.mark.asyncio
    async def test_402_skips_retries_and_falls_to_fallback(self):
        """A 402 error should immediately skip retries and use fallback."""
        call_models = []

        async def mock_complete(model, messages, **kwargs):
            call_models.append(model)
            if model == "test-model":
                raise Exception(
                    "Error code: 402 - {'error': {'message': 'Provider returned error', "
                    "'code': 402, 'metadata': {'raw': 'API key USD spend limit exceeded'}}}"
                )
            return ("fallback success", None)

        self.router.complete = mock_complete
        result = await self.engine._complete_with_retry("test-model", [], retries=3)
        assert result == "fallback success"
        # Should only try test-model once (no retries), then fallback
        assert call_models.count("test-model") == 1
        assert "test-model" in self.engine._failed_models

    @pytest.mark.asyncio
    async def test_402_model_tracked_in_failed_models(self):
        """A 402 failure should add the model to _failed_models for this task."""
        self.router.complete = AsyncMock(
            side_effect=[
                Exception("Error code: 402 - spend limit exceeded"),
                ("ok", None),
            ]
        )
        await self.engine._complete_with_retry("test-model", [], retries=3)
        assert "test-model" in self.engine._failed_models

    @pytest.mark.asyncio
    async def test_402_model_skipped_on_subsequent_iterations(self):
        """A model that got 402 should be skipped immediately in later calls."""
        self.engine._failed_models.add("test-model")

        call_models = []

        async def mock_complete(model, messages, **kwargs):
            call_models.append(model)
            return ("ok", None)

        self.router.complete = mock_complete
        result = await self.engine._complete_with_retry("test-model", [], retries=3)
        assert result == "ok"
        # test-model should NOT appear in call_models — it was skipped
        assert "test-model" not in call_models


class TestConvergenceDetection:
    """Tests for stuck loop detection."""

    def test_identical_feedback_is_convergent(self):
        engine = IterationEngine(MagicMock())
        score = engine._feedback_similarity(
            "Missing error handling for the edge case",
            "Missing error handling for the edge case",
        )
        assert score == 1.0
        assert score > SIMILARITY_THRESHOLD

    def test_similar_feedback_is_convergent(self):
        engine = IterationEngine(MagicMock())
        score = engine._feedback_similarity(
            "Add error handling for null input and validate the response format",
            "Add error handling for null input and validate the response format please",
        )
        assert score > SIMILARITY_THRESHOLD

    def test_different_feedback_is_not_convergent(self):
        engine = IterationEngine(MagicMock())
        score = engine._feedback_similarity(
            "Missing error handling for edge cases",
            "The code style doesn't match the project conventions",
        )
        assert score < SIMILARITY_THRESHOLD

    def test_empty_feedback_returns_zero(self):
        engine = IterationEngine(MagicMock())
        assert engine._feedback_similarity("", "some feedback") == 0.0
        assert engine._feedback_similarity("some feedback", "") == 0.0

    @pytest.mark.asyncio
    async def test_convergence_stops_loop_early(self):
        """When critic repeats the same feedback, loop should accept and stop."""
        router = MagicMock()
        call_num = 0

        async def mock_complete(model, messages, **kwargs):
            nonlocal call_num
            call_num += 1
            if "reviewer" in str(model) or "critic" in str(model).lower():
                # Critic always gives same feedback
                return ("NEEDS WORK: Add error handling for null inputs", None)
            return (f"Here is my output v{call_num}", None)

        router.complete = mock_complete
        engine = IterationEngine(router)
        history = await engine.run(
            task_description="test",
            primary_model="primary",
            critic_model="critic",
            max_iterations=10,
        )
        # Should converge well before 10 iterations (iteration 2 detects repeat)
        assert history.total_iterations <= 3


# -- Approval Gate: Timeout --------------------------------------------------


class TestApprovalTimeout:
    """Tests for approval gate timeout."""

    @pytest.mark.asyncio
    async def test_timeout_auto_denies(self):
        """Approval request should auto-deny after timeout."""
        gate = ApprovalGate(task_queue=MagicMock(), timeout=0.1)
        result = await gate.request("task-1", ProtectedAction.GIT_PUSH, "Push to remote")
        assert result is False

    @pytest.mark.asyncio
    async def test_approval_before_timeout(self):
        """Manual approval before timeout should return True."""
        gate = ApprovalGate(task_queue=MagicMock(), timeout=5)

        async def approve_later():
            await asyncio.sleep(0.05)
            gate.approve("task-1", "git_push")

        asyncio.create_task(approve_later())
        result = await gate.request("task-1", ProtectedAction.GIT_PUSH, "Push to remote")
        assert result is True

    @pytest.mark.asyncio
    async def test_deny_before_timeout(self):
        """Manual denial before timeout should return False."""
        gate = ApprovalGate(task_queue=MagicMock(), timeout=5)

        async def deny_later():
            await asyncio.sleep(0.05)
            gate.deny("task-1", "git_push")

        asyncio.create_task(deny_later())
        result = await gate.request("task-1", ProtectedAction.GIT_PUSH, "Push to remote")
        assert result is False

    @pytest.mark.asyncio
    async def test_pending_cleaned_after_timeout(self):
        """After timeout, the pending request should be cleaned up."""
        gate = ApprovalGate(task_queue=MagicMock(), timeout=0.1)
        await gate.request("task-1", ProtectedAction.GIT_PUSH, "Push")
        assert len(gate.pending_requests()) == 0


# -- Task Type Inference ------------------------------------------------------


class TestTaskTypeInference:
    """Tests for automatic task type inference from message content."""

    def test_infer_debugging(self):
        assert infer_task_type("Fix the login bug") == TaskType.DEBUGGING
        assert infer_task_type("There's an error in the API") == TaskType.DEBUGGING
        assert infer_task_type("The app is crashing on startup") == TaskType.DEBUGGING

    def test_infer_research(self):
        assert infer_task_type("Research the best database options") == TaskType.RESEARCH
        assert infer_task_type("Compare React vs Vue") == TaskType.RESEARCH

    def test_infer_refactoring(self):
        assert infer_task_type("Refactor the auth module") == TaskType.REFACTORING
        assert infer_task_type("Clean up the legacy code") == TaskType.REFACTORING

    def test_infer_documentation(self):
        assert infer_task_type("Write docs for the API") == TaskType.DOCUMENTATION
        assert infer_task_type("Update the readme") == TaskType.DOCUMENTATION

    def test_infer_marketing(self):
        assert infer_task_type("Write marketing copy for the launch") == TaskType.MARKETING
        assert infer_task_type("Create a landing page design") == TaskType.MARKETING

    def test_infer_email(self):
        assert infer_task_type("Draft email to the team") == TaskType.EMAIL
        assert infer_task_type("Write email to client about deadline") == TaskType.EMAIL

    def test_default_to_coding(self):
        assert infer_task_type("Build a REST API") == TaskType.CODING
        assert infer_task_type("Add pagination to the list view") == TaskType.CODING


# -- Task Queue: Deduplication -----------------------------------------------


class TestTaskDeduplication:
    """Tests for task dedup on file reload."""

    @pytest.mark.asyncio
    async def test_running_tasks_reset_to_pending(self):
        """Tasks that were RUNNING on disk should become PENDING on load."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            import json

            json.dump(
                [
                    {
                        "id": "abc123",
                        "title": "Test",
                        "description": "Test",
                        "status": "running",
                        "task_type": "coding",
                        "created_at": 1.0,
                        "updated_at": 1.0,
                        "iterations": 0,
                        "max_iterations": 8,
                        "worktree_path": "",
                        "result": "",
                        "error": "",
                    }
                ],
                f,
            )
            f.flush()

            queue = TaskQueue(tasks_json_path=f.name)
            await queue.load_from_file()

            task = queue.get("abc123")
            assert task is not None
            assert task.status == TaskStatus.PENDING

    @pytest.mark.asyncio
    async def test_no_duplicate_enqueue(self):
        """Same pending task ID should not be queued twice."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            import json

            json.dump(
                [
                    {
                        "id": "dup1",
                        "title": "Task A",
                        "description": "A",
                        "status": "pending",
                        "task_type": "coding",
                        "created_at": 1.0,
                        "updated_at": 1.0,
                        "iterations": 0,
                        "max_iterations": 8,
                        "worktree_path": "",
                        "result": "",
                        "error": "",
                    },
                ],
                f,
            )
            f.flush()

            queue = TaskQueue(tasks_json_path=f.name)
            await queue.load_from_file()

            # Queue should have exactly 1 item
            assert queue._queue.qsize() == 1
