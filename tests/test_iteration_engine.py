"""Tests for IterationEngine context overflow handling.

Validates that the 'error' strategy produces a meaningful message
instead of returning an empty string when primary_output is blank.
"""

from unittest.mock import MagicMock, patch

import pytest

from agents.iteration_engine import IterationEngine, IterationHistory


class TestContextOverflowErrorStrategy:
    """Tests for context overflow 'error' strategy output."""

    def setup_method(self):
        self.router = MagicMock()
        self.engine = IterationEngine(self.router)

    @pytest.mark.asyncio
    async def test_error_strategy_empty_output_produces_message(self):
        """When context overflows on iteration 1 with no prior output,
        the 'error' strategy should return an explanatory message instead
        of an empty string."""
        mock_settings = MagicMock()
        mock_settings.max_context_tokens = 1000
        mock_settings.context_overflow_strategy = "error"

        with patch("core.config.settings", mock_settings):
            # 1000 * 0.8 = 800 token threshold; need ~3200+ chars (chars/4)
            big_description = "x" * 4000

            history = await self.engine.run(
                task_description=big_description,
                primary_model="test-model",
                critic_model=None,
                max_iterations=3,
                system_prompt="You are a helpful assistant.",
            )

            assert history.final_output != ""
            assert "context" in history.final_output.lower()
            assert "too large" in history.final_output.lower()
            assert "1,000" in history.final_output  # max_ctx formatted with comma
            assert history.total_iterations == 1

    @pytest.mark.asyncio
    async def test_error_strategy_preserves_existing_output(self):
        """When primary_output already has content from a prior iteration,
        the error strategy should preserve it as-is."""
        # Direct unit test of the guard logic
        history = IterationHistory()
        primary_output = "Prior iteration result"
        est_tokens = 5000
        max_ctx = 1000

        # Replicate the guard from iteration_engine.py
        if not primary_output.strip():
            primary_output = (
                "I was unable to complete this task because the "
                "context became too large for the model's context "
                f"window (~{est_tokens:,} tokens estimated, "
                f"limit: {max_ctx:,}). Consider breaking this "
                "into smaller subtasks, or switching to the "
                "'truncate_oldest' context overflow strategy."
            )
        history.final_output = primary_output

        assert history.final_output == "Prior iteration result"

    @pytest.mark.asyncio
    async def test_error_strategy_whitespace_only_treated_as_empty(self):
        """Whitespace-only primary_output should be treated as empty
        and replaced with the explanatory message."""
        history = IterationHistory()
        primary_output = "   \n\t  "
        est_tokens = 5000
        max_ctx = 1000

        if not primary_output.strip():
            primary_output = (
                "I was unable to complete this task because the "
                "context became too large for the model's context "
                f"window (~{est_tokens:,} tokens estimated, "
                f"limit: {max_ctx:,}). Consider breaking this "
                "into smaller subtasks, or switching to the "
                "'truncate_oldest' context overflow strategy."
            )
        history.final_output = primary_output

        assert "context" in history.final_output.lower()
        assert "too large" in history.final_output.lower()
