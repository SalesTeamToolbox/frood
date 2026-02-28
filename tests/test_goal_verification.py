"""Tests for goal-backward verification in IterationEngine."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from agents.iteration_engine import IterationEngine


class TestGoalVerification:
    """Test the verify_goal() method on IterationEngine."""

    def setup_method(self):
        self.router = MagicMock()
        self.engine = IterationEngine(self.router)

    @pytest.mark.asyncio
    async def test_goal_achieved(self):
        """When all truths are verified, goal is ACHIEVED."""
        self.router.complete = AsyncMock(
            return_value=(
                "All items verified.\n"
                "1. User can log in — VERIFIED\n"
                "2. auth.py exists — VERIFIED\n"
                "GOAL_STATUS: ACHIEVED",
                {"total_tokens": 100},
            )
        )
        achieved, response, gaps = await self.engine.verify_goal(
            goal="Build auth module",
            observable_truths=["User can log in"],
            required_artifacts=["auth.py"],
            required_wiring=["API connects to DB"],
            outputs={"auth_task": "Implemented login endpoint"},
            model="test-model",
        )
        assert achieved is True
        assert gaps == []

    @pytest.mark.asyncio
    async def test_gaps_found(self):
        """When truths are missing, gaps are extracted."""
        self.router.complete = AsyncMock(
            return_value=(
                "Review complete.\n"
                "1. User can log in — VERIFIED\n"
                "2. Password reset — MISSING\n"
                "GOAL_STATUS: GAPS_FOUND\n"
                "GAPS:\n"
                "- Password reset flow not implemented\n"
                "- Email notification not wired",
                {"total_tokens": 100},
            )
        )
        achieved, response, gaps = await self.engine.verify_goal(
            goal="Build auth module",
            observable_truths=["User can log in", "User can reset password"],
            required_artifacts=["auth.py"],
            required_wiring=[],
            outputs={"auth_task": "Implemented login only"},
            model="test-model",
        )
        assert achieved is False
        assert len(gaps) == 2
        assert "Password reset" in gaps[0]
        assert "Email notification" in gaps[1]

    @pytest.mark.asyncio
    async def test_verification_error_returns_true(self):
        """On LLM error, verification is skipped gracefully."""
        self.router.complete = AsyncMock(side_effect=RuntimeError("API down"))

        achieved, response, gaps = await self.engine.verify_goal(
            goal="Build something",
            observable_truths=["It works"],
            required_artifacts=[],
            required_wiring=[],
            outputs={"task": "output"},
            model="test-model",
        )
        assert achieved is True  # Fail-open
        assert "verification skipped" in response
        assert gaps == []

    @pytest.mark.asyncio
    async def test_empty_truths(self):
        """Works with empty verification lists."""
        self.router.complete = AsyncMock(
            return_value=(
                "No specific truths to verify.\nGOAL_STATUS: ACHIEVED",
                {"total_tokens": 50},
            )
        )
        achieved, response, gaps = await self.engine.verify_goal(
            goal="Simple task",
            observable_truths=[],
            required_artifacts=[],
            required_wiring=[],
            outputs={"task": "Done"},
            model="test-model",
        )
        assert achieved is True


class TestContextBudgetAwareness:
    """Test context budget estimation and conversation compaction."""

    def test_estimate_context_utilization(self):
        messages = [
            {"role": "system", "content": "x" * 4000},  # ~1000 tokens
            {"role": "user", "content": "x" * 4000},  # ~1000 tokens
        ]
        pct = IterationEngine._estimate_context_utilization(messages, max_tokens=10_000)
        assert 15 < pct < 25  # ~2000/10000 = 20%

    def test_estimate_context_utilization_zero_max(self):
        messages = [{"role": "user", "content": "hello"}]
        pct = IterationEngine._estimate_context_utilization(messages, max_tokens=0)
        assert pct == 0.0

    def test_compact_conversation_messages_short(self):
        """Short conversations are not compacted."""
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "task"},
            {"role": "assistant", "content": "response"},
        ]
        IterationEngine._compact_conversation_messages(messages)
        assert messages[2]["content"] == "response"  # unchanged

    def test_compact_conversation_messages_long(self):
        """Long conversations have middle messages truncated."""
        messages = [
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": "original task"},
        ]
        # Add 10 exchanges (20 messages)
        for i in range(10):
            messages.append({"role": "user", "content": f"question {i} " + "x" * 500})
            messages.append({"role": "assistant", "content": f"answer {i} " + "y" * 500})

        original_len = len(messages)
        IterationEngine._compact_conversation_messages(messages)
        assert len(messages) == original_len  # Length unchanged, content truncated

        # First 2 messages (system + task) should be intact
        assert messages[0]["content"] == "system prompt"
        assert messages[1]["content"] == "original task"

        # Last 6 messages should be intact
        assert "y" * 500 in messages[-1]["content"]

        # Middle messages should be truncated
        assert "truncated" in messages[3]["content"]
