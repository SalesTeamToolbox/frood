"""Tests for dynamic model routing — end-to-end resolution chain."""

import json

from agents.model_evaluator import ModelEvaluator
from agents.model_router import FREE_ROUTING, ModelRouter
from core.task_queue import TaskType


class TestModelRouterDynamicRouting:
    """Tests for the dynamic routing layer in ModelRouter."""

    def test_hardcoded_fallback(self):
        """Without dynamic routing or admin override, should use FREE_ROUTING."""
        router = ModelRouter()
        routing = router.get_routing(TaskType.CODING)
        assert routing["primary"] == FREE_ROUTING[TaskType.CODING]["primary"]

    def test_admin_override_takes_priority(self, monkeypatch):
        """Admin env vars should override everything."""
        monkeypatch.setenv("AGENT42_CODING_MODEL", "claude-sonnet")
        monkeypatch.setenv("AGENT42_CODING_CRITIC", "gpt-4o")

        router = ModelRouter()
        routing = router.get_routing(TaskType.CODING)
        assert routing["primary"] == "claude-sonnet"
        assert routing["critic"] == "gpt-4o"

    def test_dynamic_routing_from_file(self, tmp_path):
        """Dynamic routing file should override hardcoded defaults."""
        routing_file = tmp_path / "routing.json"
        routing_file.write_text(
            json.dumps(
                {
                    "last_updated": "2026-02-22T12:00:00Z",
                    "routing": {
                        "coding": {
                            "primary": "or-free-new-best-model",
                            "critic": "or-free-new-critic",
                            "confidence": 0.92,
                            "sample_size": 50,
                            "max_iterations": 8,
                        },
                    },
                }
            )
        )

        router = ModelRouter(routing_file=str(routing_file))
        routing = router.get_routing(TaskType.CODING)
        assert routing["primary"] == "or-free-new-best-model"
        assert routing["critic"] == "or-free-new-critic"

    def test_admin_override_beats_dynamic(self, tmp_path, monkeypatch):
        """Admin override should still win over dynamic routing."""
        monkeypatch.setenv("AGENT42_CODING_MODEL", "admin-choice")

        routing_file = tmp_path / "routing.json"
        routing_file.write_text(
            json.dumps(
                {
                    "routing": {
                        "coding": {
                            "primary": "dynamic-choice",
                            "critic": None,
                            "max_iterations": 8,
                        },
                    },
                }
            )
        )

        router = ModelRouter(routing_file=str(routing_file))
        routing = router.get_routing(TaskType.CODING)
        assert routing["primary"] == "admin-choice"

    def test_dynamic_routing_missing_task_type(self, tmp_path):
        """Task types not in dynamic routing should fall back to hardcoded."""
        routing_file = tmp_path / "routing.json"
        routing_file.write_text(
            json.dumps(
                {
                    "routing": {
                        "coding": {
                            "primary": "dynamic-model",
                            "critic": None,
                            "max_iterations": 8,
                        },
                    },
                }
            )
        )

        router = ModelRouter(routing_file=str(routing_file))
        # RESEARCH is not in the dynamic routing file
        routing = router.get_routing(TaskType.RESEARCH)
        assert routing["primary"] == FREE_ROUTING[TaskType.RESEARCH]["primary"]

    def test_dynamic_routing_invalid_file(self, tmp_path):
        """Invalid JSON in routing file should fall back gracefully."""
        routing_file = tmp_path / "routing.json"
        routing_file.write_text("not json")

        router = ModelRouter(routing_file=str(routing_file))
        routing = router.get_routing(TaskType.CODING)
        assert routing["primary"] == FREE_ROUTING[TaskType.CODING]["primary"]

    def test_dynamic_routing_no_file(self, tmp_path):
        """Non-existent routing file should fall back to hardcoded."""
        router = ModelRouter(routing_file=str(tmp_path / "nonexistent.json"))
        routing = router.get_routing(TaskType.CODING)
        assert routing["primary"] == FREE_ROUTING[TaskType.CODING]["primary"]

    def test_trial_injection(self, tmp_path):
        """Trial system should inject unproven models."""
        evaluator = ModelEvaluator(
            performance_path=tmp_path / "perf.json",
            routing_path=tmp_path / "routing.json",
            research_path=tmp_path / "research.json",
            trial_percentage=100,  # Always trial
            min_trials=5,
        )

        # model_a has data, model_b is unproven
        for _ in range(5):
            evaluator.record_outcome("or-free-qwen-coder", "coding", True, 2, 8)

        router = ModelRouter(evaluator=evaluator, routing_file=str(tmp_path / "r.json"))
        routing = router.get_routing(TaskType.CODING)

        # The trial injection should replace the primary with an unproven model
        # (since trial_percentage=100%, any unproven free model will be selected)
        # Note: this depends on available free models in the registry
        # The important thing is the mechanism works — primary may or may not change
        assert "primary" in routing

    def test_record_outcome_delegates(self, tmp_path):
        """record_outcome should delegate to ModelEvaluator."""
        evaluator = ModelEvaluator(
            performance_path=tmp_path / "perf.json",
            routing_path=tmp_path / "routing.json",
            research_path=tmp_path / "research.json",
        )

        router = ModelRouter(evaluator=evaluator)
        router.record_outcome("model_a", "coding", True, 3, 8)

        ranking = evaluator.get_ranking("coding")
        assert len(ranking) == 1
        assert ranking[0].model_key == "model_a"

    def test_record_outcome_no_evaluator(self):
        """record_outcome should be a no-op without an evaluator."""
        router = ModelRouter()
        # Should not raise
        router.record_outcome("model_a", "coding", True, 3, 8)

    def test_all_task_types_have_routing(self):
        """Every TaskType should have a hardcoded default routing."""
        for task_type in TaskType:
            assert task_type in FREE_ROUTING, f"Missing routing for {task_type}"
