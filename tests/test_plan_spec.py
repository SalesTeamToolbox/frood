"""Tests for core.plan_spec — PlanSpecification and PlanTask."""

import json

import pytest

from core.plan_spec import PlanSpecification, PlanTask


class TestPlanTask:
    """Test PlanTask dataclass."""

    def test_from_dict_basic(self):
        data = {"id": "T1", "title": "Do thing", "role": "coder"}
        task = PlanTask.from_dict(data)
        assert task.id == "T1"
        assert task.title == "Do thing"
        assert task.role == "coder"
        assert task.depends_on == []

    def test_from_dict_ignores_unknown_fields(self):
        data = {"id": "T1", "title": "X", "unknown_field": 123}
        task = PlanTask.from_dict(data)
        assert task.id == "T1"
        assert not hasattr(task, "unknown_field")

    def test_roundtrip(self):
        task = PlanTask(
            id="T1",
            title="Build auth",
            description="Create login endpoint",
            files_to_read=["models/user.py"],
            files_to_modify=["api/auth.py"],
            verification_commands=["pytest tests/test_auth.py"],
            acceptance_criteria=["POST /login returns 200 with valid credentials"],
            depends_on=["T0"],
            estimated_context_pct=40,
        )
        data = task.to_dict()
        restored = PlanTask.from_dict(data)
        assert restored.id == task.id
        assert restored.files_to_read == task.files_to_read
        assert restored.depends_on == ["T0"]
        assert restored.estimated_context_pct == 40


class TestPlanSpecification:
    """Test PlanSpecification dataclass and wave computation."""

    def _make_spec(self, tasks):
        return PlanSpecification(plan_id="test", tasks=tasks)

    def test_compute_waves_no_deps(self):
        """All tasks with no dependencies land in wave 0."""
        tasks = [
            PlanTask(id="T1", title="A"),
            PlanTask(id="T2", title="B"),
            PlanTask(id="T3", title="C"),
        ]
        spec = self._make_spec(tasks)
        waves = spec.compute_waves()
        assert len(waves) == 1
        assert len(waves[0]) == 3

    def test_compute_waves_linear_chain(self):
        """T1 -> T2 -> T3 produces 3 waves."""
        tasks = [
            PlanTask(id="T1", title="A"),
            PlanTask(id="T2", title="B", depends_on=["T1"]),
            PlanTask(id="T3", title="C", depends_on=["T2"]),
        ]
        spec = self._make_spec(tasks)
        waves = spec.compute_waves()
        assert len(waves) == 3
        assert waves[0][0].id == "T1"
        assert waves[1][0].id == "T2"
        assert waves[2][0].id == "T3"

    def test_compute_waves_diamond(self):
        """T1 fans out to T2+T3, then T4 depends on both."""
        tasks = [
            PlanTask(id="T1", title="A"),
            PlanTask(id="T2", title="B", depends_on=["T1"]),
            PlanTask(id="T3", title="C", depends_on=["T1"]),
            PlanTask(id="T4", title="D", depends_on=["T2", "T3"]),
        ]
        spec = self._make_spec(tasks)
        waves = spec.compute_waves()
        assert len(waves) == 3
        # Wave 0: T1
        assert [t.id for t in waves[0]] == ["T1"]
        # Wave 1: T2, T3 (parallel)
        wave1_ids = sorted(t.id for t in waves[1])
        assert wave1_ids == ["T2", "T3"]
        # Wave 2: T4
        assert [t.id for t in waves[2]] == ["T4"]

    def test_compute_waves_cycle_detection(self):
        """Circular dependencies raise ValueError."""
        tasks = [
            PlanTask(id="T1", title="A", depends_on=["T2"]),
            PlanTask(id="T2", title="B", depends_on=["T1"]),
        ]
        spec = self._make_spec(tasks)
        with pytest.raises(ValueError, match="Circular dependency"):
            spec.compute_waves()

    def test_compute_waves_unknown_dep_ignored(self):
        """Dependencies on non-existent tasks are ignored with a warning."""
        tasks = [
            PlanTask(id="T1", title="A", depends_on=["NONEXISTENT"]),
        ]
        spec = self._make_spec(tasks)
        waves = spec.compute_waves()
        assert len(waves) == 1
        assert waves[0][0].id == "T1"

    def test_to_markdown_contains_sections(self):
        spec = PlanSpecification(
            plan_id="p1",
            goal="Build the thing",
            tasks=[
                PlanTask(
                    id="T1",
                    title="Create models",
                    description="Build data models",
                    files_to_read=["schema.sql"],
                    files_to_modify=["models.py"],
                    verification_commands=["pytest tests/"],
                    acceptance_criteria=["Models can be instantiated"],
                ),
            ],
            observable_truths=["User can log in"],
            required_artifacts=["models.py"],
            required_wiring=["API connects to DB"],
        )
        md = spec.to_markdown()
        assert "# Execution Plan: p1" in md
        assert "## Goal" in md
        assert "Build the thing" in md
        assert "## Observable Truths" in md
        assert "User can log in" in md
        assert "## Required Artifacts" in md
        assert "models.py" in md
        assert "## Required Wiring" in md
        assert "API connects to DB" in md
        assert "### T1: Create models" in md
        assert "schema.sql" in md
        assert "Acceptance criteria" in md

    def test_to_dict_from_dict_roundtrip(self):
        spec = PlanSpecification(
            plan_id="p1",
            project_id="proj42",
            goal="Ship it",
            tasks=[
                PlanTask(id="T1", title="Do A", depends_on=[]),
                PlanTask(id="T2", title="Do B", depends_on=["T1"]),
            ],
            observable_truths=["Feature works"],
            required_artifacts=["output.txt"],
            context_budget_pct=40,
        )
        data = spec.to_dict()
        json_str = json.dumps(data)
        restored = PlanSpecification.from_dict(json.loads(json_str))
        assert restored.plan_id == "p1"
        assert restored.project_id == "proj42"
        assert restored.goal == "Ship it"
        assert len(restored.tasks) == 2
        assert restored.tasks[1].depends_on == ["T1"]
        assert restored.observable_truths == ["Feature works"]
        assert restored.context_budget_pct == 40

    @pytest.mark.asyncio
    async def test_save_load_roundtrip(self, tmp_path):
        spec = PlanSpecification(
            plan_id="p1",
            goal="Test persistence",
            tasks=[PlanTask(id="T1", title="Task one")],
            observable_truths=["It works"],
        )
        await spec.save(tmp_path)

        # Verify files were created
        assert (tmp_path / "PLAN.md").exists()
        assert (tmp_path / "plan.json").exists()

        # Load and verify
        loaded = await PlanSpecification.load(tmp_path)
        assert loaded.plan_id == "p1"
        assert loaded.goal == "Test persistence"
        assert len(loaded.tasks) == 1
        assert loaded.tasks[0].id == "T1"
        assert loaded.observable_truths == ["It works"]

    def test_from_dict_missing_tasks(self):
        """Gracefully handles missing tasks key."""
        data = {"plan_id": "p1", "goal": "Test"}
        spec = PlanSpecification.from_dict(data)
        assert spec.plan_id == "p1"
        assert spec.tasks == []

    def test_compute_waves_assigns_wave_numbers(self):
        """Wave numbers are assigned back onto task objects."""
        tasks = [
            PlanTask(id="T1", title="A"),
            PlanTask(id="T2", title="B", depends_on=["T1"]),
        ]
        spec = self._make_spec(tasks)
        spec.compute_waves()
        assert spec.tasks[0].wave == 0
        assert spec.tasks[1].wave == 1
