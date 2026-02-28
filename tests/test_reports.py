"""Tests for the Reports page API endpoint data aggregation."""

import pytest

from agents.model_evaluator import ModelEvaluator
from core.task_queue import Task, TaskStatus, TaskType


class TestReportsModelPerformance:
    """Test that ModelEvaluator data is suitable for reports."""

    def setup_method(self):
        import uuid

        tag = uuid.uuid4().hex[:8]
        self.evaluator = ModelEvaluator(
            performance_path=f"/tmp/test_reports_perf_{tag}.json",
            routing_path=f"/tmp/test_reports_route_{tag}.json",
            research_path=f"/tmp/test_reports_research_{tag}.json",
        )

    def test_model_stats_to_dict_has_report_keys(self):
        """ModelStats.to_dict() must contain all keys the frontend expects."""
        self.evaluator.record_outcome("test-model", "coding", True, 3, 8, 0.85)
        stats = self.evaluator._stats.get(("test-model", "coding"))
        assert stats is not None
        d = stats.to_dict()
        required_keys = [
            "model_key",
            "task_type",
            "total_tasks",
            "success_rate",
            "iteration_efficiency",
            "critic_avg",
            "composite_score",
        ]
        for key in required_keys:
            assert key in d, f"Missing key: {key}"

    def test_empty_evaluator_returns_no_stats(self):
        """Empty evaluator should produce empty performance list."""
        perf = [s.to_dict() for s in self.evaluator._stats.values()]
        assert perf == []

    def test_multiple_outcomes_aggregate(self):
        """Multiple outcomes for the same model+type should aggregate."""
        self.evaluator.record_outcome("m1", "coding", True, 3, 8, 0.9)
        self.evaluator.record_outcome("m1", "coding", False, 8, 8, 0.2)
        self.evaluator.record_outcome("m1", "coding", True, 2, 8, 0.8)
        stats = self.evaluator._stats[("m1", "coding")]
        assert stats.total_tasks == 3
        assert stats.successes == 2
        assert stats.success_rate == pytest.approx(2 / 3, abs=0.01)

    def test_different_task_types_tracked_separately(self):
        """Model stats are keyed by (model, task_type)."""
        self.evaluator.record_outcome("m1", "coding", True, 3, 8)
        self.evaluator.record_outcome("m1", "research", False, 5, 8)
        assert ("m1", "coding") in self.evaluator._stats
        assert ("m1", "research") in self.evaluator._stats
        assert self.evaluator._stats[("m1", "coding")].total_tasks == 1
        assert self.evaluator._stats[("m1", "research")].total_tasks == 1


class TestReportsTaskAggregation:
    """Test the task counting and aggregation logic used by /api/reports."""

    def _make_tasks(self):
        """Create a representative set of tasks for testing."""
        return [
            Task(
                title="Fix login",
                description="d",
                task_type=TaskType.CODING,
                status=TaskStatus.DONE,
                iterations=3,
                token_usage={
                    "total_tokens": 1500,
                    "total_prompt_tokens": 900,
                    "total_completion_tokens": 600,
                    "by_model": {
                        "gemini-2-flash": {
                            "prompt_tokens": 900,
                            "completion_tokens": 600,
                            "calls": 4,
                        }
                    },
                },
            ),
            Task(
                title="Fix crash",
                description="d",
                task_type=TaskType.DEBUGGING,
                status=TaskStatus.FAILED,
                iterations=8,
                token_usage={
                    "total_tokens": 3000,
                    "total_prompt_tokens": 2000,
                    "total_completion_tokens": 1000,
                    "by_model": {
                        "gemini-2-flash": {
                            "prompt_tokens": 1200,
                            "completion_tokens": 600,
                            "calls": 3,
                        },
                        "or-free-qwen": {
                            "prompt_tokens": 800,
                            "completion_tokens": 400,
                            "calls": 2,
                        },
                    },
                },
            ),
            Task(
                title="Research API",
                description="d",
                task_type=TaskType.RESEARCH,
                status=TaskStatus.DONE,
                iterations=2,
            ),
            Task(
                title="Pending task",
                description="d",
                task_type=TaskType.CODING,
                status=TaskStatus.PENDING,
            ),
        ]

    def test_status_counts(self):
        """Aggregate status counts across all tasks."""
        tasks = self._make_tasks()
        status_counts = {}
        for task in tasks:
            s = task.status.value
            status_counts[s] = status_counts.get(s, 0) + 1
        assert status_counts == {"done": 2, "failed": 1, "pending": 1}

    def test_type_counts(self):
        """Aggregate task type counts."""
        tasks = self._make_tasks()
        type_counts = {}
        for task in tasks:
            tt = task.task_type.value
            type_counts[tt] = type_counts.get(tt, 0) + 1
        assert type_counts == {"coding": 2, "debugging": 1, "research": 1}

    def test_token_aggregation_totals(self):
        """Total token counts should sum across all tasks."""
        tasks = self._make_tasks()
        total_tokens = 0
        total_prompt = 0
        total_completion = 0
        for task in tasks:
            usage = task.token_usage
            if usage and isinstance(usage, dict):
                total_tokens += usage.get("total_tokens", 0)
                total_prompt += usage.get("total_prompt_tokens", 0)
                total_completion += usage.get("total_completion_tokens", 0)
        assert total_tokens == 4500  # 1500 + 3000
        assert total_prompt == 2900  # 900 + 2000
        assert total_completion == 1600  # 600 + 1000

    def test_token_aggregation_by_model(self):
        """Per-model token breakdown should aggregate across tasks."""
        tasks = self._make_tasks()
        by_model = {}
        for task in tasks:
            usage = task.token_usage
            if not usage or not isinstance(usage, dict):
                continue
            for model_key, mdata in usage.get("by_model", {}).items():
                if model_key not in by_model:
                    by_model[model_key] = {
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "calls": 0,
                    }
                by_model[model_key]["prompt_tokens"] += mdata.get("prompt_tokens", 0)
                by_model[model_key]["completion_tokens"] += mdata.get("completion_tokens", 0)
                by_model[model_key]["calls"] += mdata.get("calls", 0)

        assert "gemini-2-flash" in by_model
        assert by_model["gemini-2-flash"]["prompt_tokens"] == 2100  # 900 + 1200
        assert by_model["gemini-2-flash"]["completion_tokens"] == 1200  # 600 + 600
        assert by_model["gemini-2-flash"]["calls"] == 7  # 4 + 3
        assert "or-free-qwen" in by_model
        assert by_model["or-free-qwen"]["calls"] == 2

    def test_success_rate_calculation(self):
        """Success rate should be done/(done+failed)."""
        tasks = self._make_tasks()
        done = sum(1 for t in tasks if t.status == TaskStatus.DONE)
        failed = sum(1 for t in tasks if t.status == TaskStatus.FAILED)
        completed = done + failed
        rate = done / completed if completed > 0 else 0.0
        assert rate == pytest.approx(2 / 3, abs=0.01)

    def test_tasks_without_token_usage_handled(self):
        """Tasks with no token_usage should not cause errors."""
        tasks = [
            Task(title="t1", description="d", task_type=TaskType.CODING),
            Task(title="t2", description="d", task_type=TaskType.CODING, token_usage={}),
        ]
        total = 0
        for task in tasks:
            usage = task.token_usage
            if usage and isinstance(usage, dict):
                total += usage.get("total_tokens", 0)
        assert total == 0  # No crash, graceful zero


class TestReportsCostEstimation:
    """Test cost estimation logic."""

    def test_fallback_cost_estimate(self):
        """Without model pricing, fallback to $5/$15 per million."""
        prompt = 1000
        completion = 500
        cost = (prompt * 5.0 + completion * 15.0) / 1_000_000
        assert cost == pytest.approx(0.0125, abs=0.0001)

    def test_actual_pricing_used_when_available(self):
        """With known pricing, use exact per-token rates."""
        # Gemini Flash: roughly $0.075/M prompt, $0.30/M completion
        prompt_price = 0.075 / 1_000_000
        completion_price = 0.30 / 1_000_000
        prompt = 100_000
        completion = 50_000
        cost = prompt * prompt_price + completion * completion_price
        assert cost == pytest.approx(0.0225, abs=0.001)
