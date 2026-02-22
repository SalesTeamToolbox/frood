"""Tests for agents/model_evaluator.py — outcome tracking and ranking."""


import pytest

from agents.model_evaluator import ModelEvaluator, ModelStats


class TestModelStats:
    """Unit tests for ModelStats composite scoring."""

    def test_empty_stats(self):
        stats = ModelStats(model_key="test", task_type="coding")
        assert stats.success_rate == 0.0
        assert stats.iteration_efficiency == 0.5
        assert stats.critic_avg == 0.5
        assert 0.0 <= stats.composite_score <= 1.0

    def test_perfect_model(self):
        stats = ModelStats(
            model_key="test",
            task_type="coding",
            total_tasks=10,
            successes=10,
            total_iterations=10,  # 1 iteration per task
            total_max_iterations=80,  # Max was 8 per task
            critic_scores=[1.0] * 10,
            research_score=1.0,
        )
        assert stats.success_rate == 1.0
        assert stats.iteration_efficiency > 0.8
        assert stats.critic_avg == 1.0
        assert stats.composite_score > 0.9

    def test_failing_model(self):
        stats = ModelStats(
            model_key="bad",
            task_type="coding",
            total_tasks=10,
            successes=2,
            total_iterations=80,
            total_max_iterations=80,
            critic_scores=[0.2] * 10,
            research_score=0.1,
        )
        assert stats.success_rate == pytest.approx(0.2)
        assert stats.iteration_efficiency == 0.0  # Used all iterations
        assert stats.critic_avg == pytest.approx(0.2)
        assert stats.composite_score < 0.3

    def test_to_dict(self):
        stats = ModelStats(model_key="m", task_type="coding", total_tasks=5, successes=3)
        d = stats.to_dict()
        assert d["model_key"] == "m"
        assert d["total_tasks"] == 5
        assert d["success_rate"] == 0.6


class TestModelEvaluator:
    """Tests for ModelEvaluator tracking and ranking."""

    def test_record_outcome(self, tmp_path):
        evaluator = ModelEvaluator(
            performance_path=tmp_path / "perf.json",
            routing_path=tmp_path / "routing.json",
            research_path=tmp_path / "research.json",
        )

        evaluator.record_outcome("model_a", "coding", True, 3, 8)
        evaluator.record_outcome("model_a", "coding", True, 2, 8)
        evaluator.record_outcome("model_a", "coding", False, 8, 8)

        ranking = evaluator.get_ranking("coding")
        assert len(ranking) == 1
        assert ranking[0].total_tasks == 3
        assert ranking[0].successes == 2

    def test_ranking_order(self, tmp_path):
        evaluator = ModelEvaluator(
            performance_path=tmp_path / "perf.json",
            routing_path=tmp_path / "routing.json",
            research_path=tmp_path / "research.json",
            min_trials=1,
        )

        # Good model: all successes, few iterations
        for _ in range(5):
            evaluator.record_outcome("good_model", "coding", True, 2, 8)

        # Bad model: all failures, max iterations
        for _ in range(5):
            evaluator.record_outcome("bad_model", "coding", False, 8, 8)

        ranking = evaluator.get_ranking("coding")
        assert len(ranking) == 2
        assert ranking[0].model_key == "good_model"
        assert ranking[1].model_key == "bad_model"

    def test_get_best_model_min_trials(self, tmp_path):
        evaluator = ModelEvaluator(
            performance_path=tmp_path / "perf.json",
            routing_path=tmp_path / "routing.json",
            research_path=tmp_path / "research.json",
            min_trials=5,
        )

        # Only 3 tasks — below min_trials
        for _ in range(3):
            evaluator.record_outcome("model_a", "coding", True, 2, 8)

        assert evaluator.get_best_model("coding") is None

        # Add 2 more to hit min_trials
        for _ in range(2):
            evaluator.record_outcome("model_a", "coding", True, 2, 8)

        assert evaluator.get_best_model("coding") == "model_a"

    def test_rerank_all(self, tmp_path):
        evaluator = ModelEvaluator(
            performance_path=tmp_path / "perf.json",
            routing_path=tmp_path / "routing.json",
            research_path=tmp_path / "research.json",
            min_trials=2,
        )

        for _ in range(5):
            evaluator.record_outcome("model_a", "coding", True, 2, 8)

        result = evaluator.rerank_all()
        assert "routing" in result
        assert "coding" in result["routing"]
        assert result["routing"]["coding"]["primary"] == "model_a"

        # Check file was written
        assert (tmp_path / "routing.json").exists()

    def test_persistence(self, tmp_path):
        """Performance data should survive save/load cycle."""
        perf_path = tmp_path / "perf.json"

        evaluator1 = ModelEvaluator(
            performance_path=perf_path,
            routing_path=tmp_path / "r.json",
            research_path=tmp_path / "res.json",
        )
        evaluator1.record_outcome("m1", "coding", True, 3, 8)
        evaluator1.record_outcome("m1", "coding", False, 8, 8)

        # Load fresh
        evaluator2 = ModelEvaluator(
            performance_path=perf_path,
            routing_path=tmp_path / "r.json",
            research_path=tmp_path / "res.json",
        )
        ranking = evaluator2.get_ranking("coding")
        assert len(ranking) == 1
        assert ranking[0].total_tasks == 2

    def test_trial_selection(self, tmp_path):
        evaluator = ModelEvaluator(
            performance_path=tmp_path / "perf.json",
            routing_path=tmp_path / "routing.json",
            research_path=tmp_path / "research.json",
            trial_percentage=100,  # Always trial
            min_trials=5,
        )

        # model_a has enough data, model_b is unproven
        for _ in range(5):
            evaluator.record_outcome("model_a", "coding", True, 2, 8)

        trial = evaluator.select_trial_model("coding", ["model_a", "model_b"])
        # model_b is unproven and should be selected (trial_percentage=100%)
        assert trial == "model_b"

    def test_trial_no_unproven(self, tmp_path):
        evaluator = ModelEvaluator(
            performance_path=tmp_path / "perf.json",
            routing_path=tmp_path / "routing.json",
            research_path=tmp_path / "research.json",
            trial_percentage=100,
            min_trials=2,
        )

        # All models have enough data
        for _ in range(3):
            evaluator.record_outcome("model_a", "coding", True, 2, 8)
            evaluator.record_outcome("model_b", "coding", True, 3, 8)

        trial = evaluator.select_trial_model("coding", ["model_a", "model_b"])
        assert trial is None  # No unproven models

    def test_trial_zero_percentage(self, tmp_path):
        evaluator = ModelEvaluator(
            performance_path=tmp_path / "perf.json",
            routing_path=tmp_path / "routing.json",
            research_path=tmp_path / "research.json",
            trial_percentage=0,  # Never trial
            min_trials=5,
        )

        trial = evaluator.select_trial_model("coding", ["model_a"])
        assert trial is None

    def test_critic_score_tracking(self, tmp_path):
        evaluator = ModelEvaluator(
            performance_path=tmp_path / "perf.json",
            routing_path=tmp_path / "routing.json",
            research_path=tmp_path / "research.json",
        )

        evaluator.record_outcome("m1", "coding", True, 2, 8, critic_score=0.9)
        evaluator.record_outcome("m1", "coding", True, 3, 8, critic_score=0.7)

        ranking = evaluator.get_ranking("coding")
        assert ranking[0].critic_avg == pytest.approx(0.8)
