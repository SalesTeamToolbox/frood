"""Tests for per-task token usage tracking.

Covers:
- TokenAccumulator dataclass (record, to_dict)
- Task.token_usage field (default, serialization roundtrip)
- ProviderRegistry.complete() tuple return type
- IterationEngine token accumulation flow
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.iteration_engine import IterationEngine, TokenAccumulator
from core.task_queue import Task

# ---------------------------------------------------------------------------
# TokenAccumulator unit tests
# ---------------------------------------------------------------------------


class TestTokenAccumulator:
    def test_empty_state(self):
        acc = TokenAccumulator()
        assert acc.total_prompt_tokens == 0
        assert acc.total_completion_tokens == 0
        assert acc.by_model == {}

    def test_record_single_model(self):
        acc = TokenAccumulator()
        acc.record("model-a", 100, 50)
        assert acc.total_prompt_tokens == 100
        assert acc.total_completion_tokens == 50
        assert acc.by_model["model-a"]["prompt_tokens"] == 100
        assert acc.by_model["model-a"]["completion_tokens"] == 50
        assert acc.by_model["model-a"]["calls"] == 1

    def test_record_multiple_calls_same_model(self):
        acc = TokenAccumulator()
        acc.record("model-a", 100, 50)
        acc.record("model-a", 200, 75)
        assert acc.total_prompt_tokens == 300
        assert acc.total_completion_tokens == 125
        assert acc.by_model["model-a"]["prompt_tokens"] == 300
        assert acc.by_model["model-a"]["completion_tokens"] == 125
        assert acc.by_model["model-a"]["calls"] == 2

    def test_record_multiple_models(self):
        acc = TokenAccumulator()
        acc.record("model-a", 100, 50)
        acc.record("model-b", 200, 100)
        acc.record("model-a", 50, 25)
        assert acc.total_prompt_tokens == 350
        assert acc.total_completion_tokens == 175
        assert len(acc.by_model) == 2
        assert acc.by_model["model-a"]["calls"] == 2
        assert acc.by_model["model-b"]["calls"] == 1
        assert acc.by_model["model-b"]["prompt_tokens"] == 200

    def test_to_dict_format(self):
        acc = TokenAccumulator()
        acc.record("m1", 10, 20)
        d = acc.to_dict()
        assert d["total_prompt_tokens"] == 10
        assert d["total_completion_tokens"] == 20
        assert d["total_tokens"] == 30
        assert "by_model" in d
        assert d["by_model"]["m1"]["calls"] == 1

    def test_to_dict_empty(self):
        acc = TokenAccumulator()
        d = acc.to_dict()
        assert d["total_tokens"] == 0
        assert d["by_model"] == {}


# ---------------------------------------------------------------------------
# Task.token_usage field tests
# ---------------------------------------------------------------------------


class TestTaskTokenUsageField:
    def test_default_empty(self):
        task = Task(title="test", description="desc")
        assert task.token_usage == {}

    def test_roundtrip_via_dict(self):
        usage = {
            "total_prompt_tokens": 500,
            "total_completion_tokens": 200,
            "total_tokens": 700,
            "by_model": {
                "model-a": {"prompt_tokens": 500, "completion_tokens": 200, "calls": 3},
            },
        }
        task = Task(title="test", description="desc", token_usage=usage)
        d = task.to_dict()
        assert d["token_usage"]["total_tokens"] == 700
        assert d["token_usage"]["by_model"]["model-a"]["calls"] == 3

        restored = Task.from_dict(d)
        assert restored.token_usage["total_tokens"] == 700
        assert restored.token_usage["by_model"]["model-a"]["calls"] == 3

    def test_from_dict_missing_field_gets_default(self):
        """Old tasks without token_usage should load with empty dict."""
        data = {
            "title": "old task",
            "description": "from before token tracking",
            "status": "done",
            "task_type": "coding",
        }
        task = Task.from_dict(data)
        assert task.token_usage == {}


# ---------------------------------------------------------------------------
# ProviderRegistry.complete() return type test
# ---------------------------------------------------------------------------


class TestProviderCompleteReturnsUsage:
    @pytest.mark.asyncio
    async def test_complete_returns_tuple_with_usage(self):
        from providers.registry import ProviderRegistry

        registry = ProviderRegistry()

        # Mock the OpenAI client
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Hello world"
        mock_response.usage = MagicMock()
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 5

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with (
            patch.object(registry, "get_client", return_value=mock_client),
            patch.object(registry, "get_model") as mock_get_model,
            patch("providers.registry.spending_tracker"),
        ):
            mock_spec = MagicMock()
            mock_spec.model_id = "test-model"
            mock_spec.provider = "openrouter"
            mock_spec.temperature = 0.7
            mock_spec.max_tokens = 1000
            mock_get_model.return_value = mock_spec

            result = await registry.complete("test-key", [{"role": "user", "content": "hi"}])

            assert isinstance(result, tuple)
            assert len(result) == 2
            text, usage_dict = result
            assert text == "Hello world"
            assert usage_dict is not None
            assert usage_dict["model_key"] == "test-key"
            assert usage_dict["prompt_tokens"] == 10
            assert usage_dict["completion_tokens"] == 5

    @pytest.mark.asyncio
    async def test_complete_returns_none_usage_when_missing(self):
        from providers.registry import ProviderRegistry

        registry = ProviderRegistry()

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Hi"
        mock_response.usage = None

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with (
            patch.object(registry, "get_client", return_value=mock_client),
            patch.object(registry, "get_model") as mock_get_model,
            patch("providers.registry.spending_tracker"),
        ):
            mock_spec = MagicMock()
            mock_spec.model_id = "test-model"
            mock_spec.provider = "openrouter"
            mock_spec.temperature = 0.7
            mock_spec.max_tokens = 1000
            mock_get_model.return_value = mock_spec

            text, usage_dict = await registry.complete(
                "test-key", [{"role": "user", "content": "hi"}]
            )
            assert text == "Hi"
            assert usage_dict is None


# ---------------------------------------------------------------------------
# IterationEngine token accumulation test
# ---------------------------------------------------------------------------


class TestIterationEngineTokenAccumulation:
    @pytest.mark.asyncio
    async def test_tokens_accumulated_through_complete_with_retry(self):
        """Verify that _complete_with_retry records tokens in the accumulator."""
        mock_router = AsyncMock()
        mock_router.complete = AsyncMock(
            return_value=(
                "output text",
                {"model_key": "test-model", "prompt_tokens": 100, "completion_tokens": 50},
            )
        )

        engine = IterationEngine(router=mock_router)
        acc = TokenAccumulator()
        engine._token_acc = acc

        result = await engine._complete_with_retry(
            "test-model", [{"role": "user", "content": "hi"}]
        )

        assert result == "output text"
        assert acc.total_prompt_tokens == 100
        assert acc.total_completion_tokens == 50
        assert acc.by_model["test-model"]["calls"] == 1

    @pytest.mark.asyncio
    async def test_tokens_accumulated_in_full_run(self):
        """Verify tokens flow from router through engine.run() into history."""
        mock_router = AsyncMock()
        # complete() returns (text, usage_dict) — used for primary + critic
        mock_router.complete = AsyncMock(
            side_effect=[
                # Primary call
                (
                    "primary output",
                    {"model_key": "primary-model", "prompt_tokens": 200, "completion_tokens": 100},
                ),
                # Critic call (starts with APPROVED)
                (
                    "APPROVED - looks good",
                    {"model_key": "critic-model", "prompt_tokens": 50, "completion_tokens": 20},
                ),
            ]
        )

        engine = IterationEngine(router=mock_router)
        history = await engine.run(
            task_description="do something",
            primary_model="primary-model",
            critic_model="critic-model",
            max_iterations=3,
            task_type="coding",
        )

        assert history.total_iterations == 1
        usage = history.token_usage
        assert usage["total_tokens"] == 370  # 200+100+50+20
        assert usage["total_prompt_tokens"] == 250
        assert usage["total_completion_tokens"] == 120
        assert "primary-model" in usage["by_model"]
        assert "critic-model" in usage["by_model"]
        assert usage["by_model"]["primary-model"]["calls"] == 1
        assert usage["by_model"]["critic-model"]["calls"] == 1

    @pytest.mark.asyncio
    async def test_tokens_accumulated_without_critic(self):
        """Verify tokens work when no critic is configured."""
        mock_router = AsyncMock()
        mock_router.complete = AsyncMock(
            return_value=(
                "output",
                {"model_key": "model-a", "prompt_tokens": 50, "completion_tokens": 30},
            )
        )

        engine = IterationEngine(router=mock_router)
        history = await engine.run(
            task_description="do something",
            primary_model="model-a",
            critic_model=None,
            max_iterations=1,
        )

        usage = history.token_usage
        assert usage["total_tokens"] == 80
        assert usage["by_model"]["model-a"]["calls"] == 1

    @pytest.mark.asyncio
    async def test_tokens_none_usage_handled(self):
        """Verify None usage from router doesn't crash."""
        mock_router = AsyncMock()
        mock_router.complete = AsyncMock(return_value=("output", None))

        engine = IterationEngine(router=mock_router)
        history = await engine.run(
            task_description="do something",
            primary_model="model-a",
            critic_model=None,
            max_iterations=1,
        )

        usage = history.token_usage
        assert usage["total_tokens"] == 0
        assert usage["by_model"] == {}
