"""Tests for core.work_order — work order management for the cowork system."""


import pytest

from core.work_order import (
    WORK_ORDERS_DIR,
    WorkOrder,
    WorkOrderConstraints,
)


class TestWorkOrderCreate:
    def test_defaults(self):
        wo = WorkOrder(id="test-001")
        assert wo.status == "pending"
        assert wo.created_by == "laptop"
        assert wo.created != ""
        assert wo.updated != ""
        assert wo.constraints.max_turns == 30
        assert wo.constraints.max_sessions == 10

    def test_custom_fields(self):
        wo = WorkOrder(
            id="test-002",
            branch="feat/cache",
            prompt="Build caching layer",
            acceptance_criteria=["Tests pass", "Tool registered"],
            constraints=WorkOrderConstraints(max_turns=50, no_touch=["config.py"]),
        )
        assert wo.branch == "feat/cache"
        assert wo.prompt == "Build caching layer"
        assert len(wo.acceptance_criteria) == 2
        assert wo.constraints.max_turns == 50
        assert wo.constraints.no_touch == ["config.py"]


class TestWorkOrderTransitions:
    def test_pending_to_in_progress(self):
        wo = WorkOrder(id="test-003")
        wo.transition("in-progress")
        assert wo.status == "in-progress"

    def test_in_progress_to_completed(self):
        wo = WorkOrder(id="test-004", status="in-progress")
        wo.transition("completed")
        assert wo.status == "completed"

    def test_in_progress_to_recalled(self):
        wo = WorkOrder(id="test-005", status="in-progress")
        wo.transition("recalled")
        assert wo.status == "recalled"
        assert wo.recalled_at != ""

    def test_recalled_to_pending(self):
        wo = WorkOrder(id="test-006", status="recalled")
        wo.transition("pending")
        assert wo.status == "pending"

    def test_invalid_transition_raises(self):
        wo = WorkOrder(id="test-007")
        with pytest.raises(ValueError, match="Cannot transition"):
            wo.transition("completed")  # pending -> completed not allowed

    def test_completed_is_terminal(self):
        wo = WorkOrder(id="test-008", status="completed")
        with pytest.raises(ValueError):
            wo.transition("pending")

    def test_failed_to_pending(self):
        wo = WorkOrder(id="test-009", status="failed")
        wo.transition("pending")
        assert wo.status == "pending"


class TestWorkOrderSerialization:
    def test_to_dict(self):
        wo = WorkOrder(id="test-010", prompt="Do something")
        d = wo.to_dict()
        assert d["id"] == "test-010"
        assert d["prompt"] == "Do something"
        assert isinstance(d["constraints"], dict)
        assert isinstance(d["progress"], dict)

    def test_from_dict_roundtrip(self):
        wo = WorkOrder(
            id="test-011",
            branch="feat/x",
            prompt="Build feature X",
            constraints=WorkOrderConstraints(max_turns=50),
        )
        d = wo.to_dict()
        wo2 = WorkOrder.from_dict(d)
        assert wo2.id == "test-011"
        assert wo2.branch == "feat/x"
        assert wo2.constraints.max_turns == 50

    def test_save_and_load(self, tmp_path):
        wo = WorkOrder(id="test-012", prompt="Test save")
        wo.save(str(tmp_path))

        expected_path = tmp_path / WORK_ORDERS_DIR / "test-012.json"
        assert expected_path.exists()

        loaded = WorkOrder.load("test-012", str(tmp_path))
        assert loaded.id == "test-012"
        assert loaded.prompt == "Test save"

    def test_load_missing_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            WorkOrder.load("nonexistent", str(tmp_path))


class TestWorkOrderList:
    def test_list_all(self, tmp_path):
        for i in range(3):
            wo = WorkOrder(id=f"test-{i:03d}", prompt=f"Task {i}")
            wo.save(str(tmp_path))

        orders = WorkOrder.list_all(str(tmp_path))
        assert len(orders) == 3

    def test_list_filtered(self, tmp_path):
        wo1 = WorkOrder(id="test-100", prompt="A")
        wo1.save(str(tmp_path))

        wo2 = WorkOrder(id="test-101", prompt="B", status="in-progress")
        wo2.save(str(tmp_path))

        pending = WorkOrder.list_all(str(tmp_path), status_filter="pending")
        assert len(pending) == 1
        assert pending[0].id == "test-100"

    def test_list_empty_dir(self, tmp_path):
        orders = WorkOrder.list_all(str(tmp_path))
        assert orders == []


class TestWorkOrderPrompt:
    def test_prompt_from_text(self):
        wo = WorkOrder(id="test-200", prompt="Build the thing")
        prompt = wo.build_prompt()
        assert "Build the thing" in prompt
        assert "handoff-complete" in prompt

    def test_prompt_from_plan(self):
        wo = WorkOrder(id="test-201", plan_path=".planning/phases/14/14-01-PLAN.md")
        prompt = wo.build_prompt()
        assert "14-01-PLAN.md" in prompt

    def test_prompt_includes_criteria(self):
        wo = WorkOrder(
            id="test-202",
            prompt="Do work",
            acceptance_criteria=["Tests pass", "No lint errors"],
        )
        prompt = wo.build_prompt()
        assert "Tests pass" in prompt
        assert "No lint errors" in prompt

    def test_prompt_includes_no_touch(self):
        wo = WorkOrder(
            id="test-203",
            prompt="Do work",
            constraints=WorkOrderConstraints(no_touch=["agent42.py", "config.py"]),
        )
        prompt = wo.build_prompt()
        assert "agent42.py" in prompt
        assert "Do NOT modify" in prompt

    def test_prompt_includes_must_run(self):
        wo = WorkOrder(
            id="test-204",
            prompt="Do work",
            constraints=WorkOrderConstraints(must_run="make test"),
        )
        prompt = wo.build_prompt()
        assert "make test" in prompt


class TestWorkOrderProgress:
    def test_progress_tracking(self, tmp_path):
        wo = WorkOrder(id="test-300", prompt="Work")
        wo.save(str(tmp_path))

        loaded = WorkOrder.load("test-300", str(tmp_path))
        loaded.transition("in-progress")
        loaded.progress.sessions_completed = 3
        loaded.progress.files_modified = ["core/cache.py", "tests/test_cache.py"]
        loaded.progress.commits = ["abc1234", "def5678"]
        loaded.save(str(tmp_path))

        reloaded = WorkOrder.load("test-300", str(tmp_path))
        assert reloaded.status == "in-progress"
        assert reloaded.progress.sessions_completed == 3
        assert len(reloaded.progress.files_modified) == 2
        assert len(reloaded.progress.commits) == 2
