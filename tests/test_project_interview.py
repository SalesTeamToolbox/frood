"""
Tests for the project interview system.

Covers:
- Interview question banks
- Spec generator
- ProjectInterviewTool lifecycle
- Complexity gating for project setup
- Intent classifier project setup detection
"""

import json
from pathlib import Path

import pytest

from core.interview_questions import (
    ROUND_DISPLAY_NAMES,
    ROUND_THEMES,
    format_question_batch,
    get_questions,
    get_round_sequence,
)
from core.project_spec import ProjectSpecGenerator
from tools.project_interview import ProjectInterviewTool

# ── Interview Questions Tests ────────────────────────────────────────────────


class TestInterviewQuestions:
    """Tests for core/interview_questions.py."""

    def test_question_banks_have_all_themes_for_new_project(self):
        """Every theme should have questions for new_project."""
        for theme in ROUND_THEMES:
            questions = get_questions("new_project", theme)
            assert len(questions) >= 2, f"new_project/{theme} has < 2 questions"

    def test_question_banks_have_all_themes_for_new_feature(self):
        """Every theme should have questions for new_feature."""
        for theme in ROUND_THEMES:
            questions = get_questions("new_feature", theme)
            assert len(questions) >= 2, f"new_feature/{theme} has < 2 questions"

    def test_get_questions_returns_list(self):
        questions = get_questions("new_project", "overview")
        assert isinstance(questions, list)
        assert all(isinstance(q, str) for q in questions)

    def test_get_questions_unknown_type_returns_empty(self):
        questions = get_questions("unknown_type", "overview")
        assert questions == []

    def test_get_questions_unknown_theme_returns_empty(self):
        questions = get_questions("new_project", "nonexistent_theme")
        assert questions == []

    def test_round_sequence_complex(self):
        seq = get_round_sequence("complex")
        assert len(seq) == 4
        assert seq == ROUND_THEMES

    def test_round_sequence_moderate(self):
        seq = get_round_sequence("moderate")
        assert len(seq) == 3
        assert "constraints" not in seq

    def test_round_sequence_simple(self):
        seq = get_round_sequence("simple")
        assert len(seq) == 2

    def test_format_question_batch(self):
        questions = ["Question 1?", "Question 2?"]
        formatted = format_question_batch(questions, "overview")
        assert "Overview & Goals" in formatted
        assert "1. Question 1?" in formatted
        assert "2. Question 2?" in formatted

    def test_all_themes_have_display_names(self):
        for theme in ROUND_THEMES:
            assert theme in ROUND_DISPLAY_NAMES

    def test_question_banks_return_copies(self):
        """get_questions should return a copy, not a reference."""
        q1 = get_questions("new_project", "overview")
        q2 = get_questions("new_project", "overview")
        assert q1 == q2
        q1.append("extra")
        assert len(q2) != len(q1)  # Original shouldn't be mutated


# ── Project Spec Generator Tests ─────────────────────────────────────────────


class TestProjectSpecGenerator:
    """Tests for core/project_spec.py."""

    def setup_method(self):
        self.generator = ProjectSpecGenerator(router=None)

    def test_validate_completeness_all_answered(self):
        project_data = {
            "rounds": [
                {
                    "theme": "overview",
                    "extracted_answers": {"q1": "answer", "q2": "answer", "q3": "answer"},
                },
                {
                    "theme": "requirements",
                    "extracted_answers": {"q1": "answer", "q2": "answer", "q3": "answer"},
                },
            ]
        }
        result = self.generator.validate_completeness(project_data)
        assert result["complete"] is True
        assert result["coverage"] == 1.0
        assert len(result["missing"]) == 0

    def test_validate_completeness_partial(self):
        project_data = {
            "rounds": [
                {
                    "theme": "overview",
                    "extracted_answers": {"q1": "answer", "q2": "not addressed", "q3": ""},
                },
            ]
        }
        result = self.generator.validate_completeness(project_data)
        assert result["complete"] is False
        assert result["coverage"] < 0.7
        assert len(result["missing"]) == 2

    def test_validate_completeness_empty(self):
        result = self.generator.validate_completeness({"rounds": []})
        assert result["coverage"] == 0.0
        assert result["total_questions"] == 0

    @pytest.mark.asyncio
    async def test_template_generate_without_llm(self):
        """Fallback template generation should produce valid markdown."""
        project_data = {
            "project_type": "new_project",
            "complexity": "complex",
            "description": "Build a task management app",
            "rounds": [
                {
                    "theme": "overview",
                    "extracted_answers": {
                        "q1": "A task tracker for small teams",
                        "q2": "Track daily progress",
                    },
                    "key_insights": ["Small team focus"],
                },
            ],
        }
        spec = await self.generator.generate(project_data)
        assert "# Project Specification:" in spec
        assert "New Project" in spec
        assert "complex" in spec
        assert "Acceptance Criteria" in spec
        assert "Change Log" in spec

    def test_fallback_subtasks_new_project(self):
        subtasks = self.generator._fallback_subtasks("new_project")
        assert len(subtasks) >= 3
        assert subtasks[0]["depends_on"] == []
        assert all("title" in s for s in subtasks)
        assert all("task_type" in s for s in subtasks)

    def test_fallback_subtasks_new_feature(self):
        subtasks = self.generator._fallback_subtasks("new_feature")
        assert len(subtasks) >= 2
        # First task should have no dependencies
        assert subtasks[0]["depends_on"] == []
        # Later tasks should depend on earlier ones
        assert len(subtasks[-1]["depends_on"]) > 0


# ── Project Interview Tool Tests ─────────────────────────────────────────────


class TestProjectInterviewTool:
    """Tests for tools/project_interview.py."""

    def setup_method(self, tmp_path=None):
        # Use a temp dir for outputs — will be set per-test
        pass

    @pytest.fixture
    def tool(self, tmp_path):
        outputs_dir = str(tmp_path / "outputs")
        return ProjectInterviewTool(
            workspace_path=str(tmp_path),
            router=None,
            outputs_dir=outputs_dir,
        )

    @pytest.mark.asyncio
    async def test_start_creates_session(self, tool, tmp_path):
        result = await tool.execute(
            action="start",
            task_id="task_001",
            description="Build a task management app",
            project_type="new_project",
            complexity="complex",
        )
        assert result.success
        assert "Project Interview Started" in result.output
        assert "proj_" in result.output
        assert "Overview & Goals" in result.output

    @pytest.mark.asyncio
    async def test_start_requires_description(self, tool):
        result = await tool.execute(action="start", task_id="task_001", description="")
        assert not result.success
        assert "required" in result.error.lower()

    @pytest.mark.asyncio
    async def test_start_defaults_to_new_project(self, tool):
        result = await tool.execute(
            action="start",
            task_id="task_001",
            description="Build something",
            project_type="invalid_type",
        )
        assert result.success
        assert "new project" in result.output.lower()

    @pytest.mark.asyncio
    async def test_respond_processes_answer(self, tool, tmp_path):
        # Start interview
        start_result = await tool.execute(
            action="start",
            task_id="task_001",
            description="Build a task tracker",
            project_type="new_project",
            complexity="moderate",
        )
        assert start_result.success

        # Extract project_id from output
        project_id = self._extract_project_id(start_result.output)

        # Respond to first round
        result = await tool.execute(
            action="respond",
            project_id=project_id,
            response="It's for my team of 8 people. We need to track tasks and deadlines.",
        )
        assert result.success
        assert "Round 1 recorded" in result.output

    @pytest.mark.asyncio
    async def test_respond_requires_project_id(self, tool):
        result = await tool.execute(action="respond", project_id="", response="test")
        assert not result.success

    @pytest.mark.asyncio
    async def test_respond_requires_response(self, tool):
        result = await tool.execute(action="respond", project_id="proj_fake", response="")
        assert not result.success

    @pytest.mark.asyncio
    async def test_full_interview_lifecycle(self, tool, tmp_path):
        """Test complete flow: start → respond to all rounds → generate spec."""
        # Start
        start_result = await tool.execute(
            action="start",
            task_id="task_full",
            description="Build an e-commerce platform",
            project_type="new_project",
            complexity="moderate",  # 3 rounds
        )
        project_id = self._extract_project_id(start_result.output)

        # Round 1: Overview
        r1 = await tool.execute(
            action="respond",
            project_id=project_id,
            response="Online store for handmade jewelry. Target: women 25-45. Success = 100 orders/month.",
        )
        assert r1.success

        # Round 2: Requirements
        r2 = await tool.execute(
            action="respond",
            project_id=project_id,
            response="Product catalog, shopping cart, checkout with Stripe. Search and filters. User accounts.",
        )
        assert r2.success

        # Round 3: Technical (last round for moderate)
        r3 = await tool.execute(
            action="respond",
            project_id=project_id,
            response="Python/Flask is fine. Deploy on a VPS. SQLite for now, Postgres later.",
        )
        assert r3.success
        assert "interview rounds complete" in r3.output.lower()
        assert "PROJECT_SPEC.md" in r3.output

        # Check spec was generated
        spec_result = await tool.execute(action="get_spec", project_id=project_id)
        assert spec_result.success
        assert "Project Specification" in spec_result.output

    @pytest.mark.asyncio
    async def test_status_shows_progress(self, tool, tmp_path):
        start_result = await tool.execute(
            action="start",
            task_id="task_status",
            description="A project",
            project_type="new_project",
            complexity="simple",
        )
        project_id = self._extract_project_id(start_result.output)

        status = await tool.execute(action="status", project_id=project_id)
        assert status.success
        assert "discovery" in status.output.lower()
        assert "0/" in status.output  # 0 rounds completed

    @pytest.mark.asyncio
    async def test_get_spec_before_generation_fails(self, tool):
        result = await tool.execute(action="get_spec", project_id="proj_nonexistent")
        assert not result.success

    @pytest.mark.asyncio
    async def test_approve_generates_subtasks(self, tool, tmp_path):
        """Test that approve creates subtask decomposition."""
        # Run through a full interview first (moderate = 3 rounds)
        start = await tool.execute(
            action="start",
            task_id="task_approve",
            description="Build a chat app",
            project_type="new_project",
            complexity="moderate",
        )
        project_id = self._extract_project_id(start.output)

        for _ in range(3):
            await tool.execute(
                action="respond",
                project_id=project_id,
                response="Detailed answer covering all the questions asked.",
            )

        # Now approve
        approve_result = await tool.execute(action="approve", project_id=project_id)
        assert approve_result.success
        assert "Subtasks Generated" in approve_result.output

        # Verify subtasks.json was created
        subtasks_path = Path(tool._outputs_dir) / project_id / "subtasks.json"
        assert subtasks_path.exists()
        subtasks = json.loads(subtasks_path.read_text())
        assert len(subtasks) >= 2

    @pytest.mark.asyncio
    async def test_approve_wrong_state_fails(self, tool, tmp_path):
        start = await tool.execute(
            action="start",
            task_id="task_state",
            description="Test project",
            project_type="new_project",
            complexity="simple",
        )
        project_id = self._extract_project_id(start.output)

        # Try to approve while still in discovery state
        result = await tool.execute(action="approve", project_id=project_id)
        assert not result.success
        assert "state" in result.error.lower()

    @pytest.mark.asyncio
    async def test_list_empty(self, tool):
        result = await tool.execute(action="list")
        assert result.success
        assert "No interview sessions" in result.output

    @pytest.mark.asyncio
    async def test_list_shows_sessions(self, tool, tmp_path):
        await tool.execute(
            action="start",
            task_id="task_list1",
            description="Project Alpha",
            project_type="new_project",
            complexity="simple",
        )
        await tool.execute(
            action="start",
            task_id="task_list2",
            description="Feature Beta",
            project_type="new_feature",
            complexity="moderate",
        )

        result = await tool.execute(action="list")
        assert result.success
        assert "proj_" in result.output

    @pytest.mark.asyncio
    async def test_unknown_action_fails(self, tool):
        result = await tool.execute(action="invalid")
        assert not result.success
        assert "Unknown action" in result.error

    @pytest.mark.asyncio
    async def test_missing_action_fails(self, tool):
        result = await tool.execute()
        assert not result.success

    @staticmethod
    def _extract_project_id(output: str) -> str:
        """Extract project ID from tool output."""
        for line in output.split("\n"):
            if "proj_" in line:
                # Find proj_ followed by hex chars
                import re

                match = re.search(r"proj_[a-f0-9]+", line)
                if match:
                    return match.group(0)
        raise ValueError(f"Could not find project ID in output: {output[:200]}")


# ── Complexity Gating Tests ──────────────────────────────────────────────────


class TestComplexityProjectSetup:
    """Tests for project-level detection in the complexity estimator."""

    def test_project_scope_markers_boost_complexity(self):
        from core.complexity import ComplexityAssessor
        from core.task_queue import TaskType

        assessor = ComplexityAssessor(router=None)

        # A message with project scope markers should be detected
        result = assessor._keyword_assess(
            "Build me a full-stack e-commerce platform from scratch",
            TaskType.CODING,
        )
        assert result.needs_project_setup is True
        assert result.score >= 0.3

    def test_simple_task_no_project_setup(self):
        from core.complexity import ComplexityAssessor
        from core.task_queue import TaskType

        assessor = ComplexityAssessor(router=None)

        # Use a truly simple task that won't trigger cross-domain keywords
        result = assessor._keyword_assess(
            "rename the variable foo to bar",
            TaskType.CODING,
        )
        assert result.needs_project_setup is False
        assert result.level == "simple"

    def test_moderate_coding_task_triggers_project_setup(self):
        from core.complexity import ComplexityAssessor
        from core.task_queue import TaskType

        assessor = ComplexityAssessor(router=None)

        # "build me a" triggers project scope, plus other markers
        result = assessor._keyword_assess(
            "build me a task tracking application with user accounts",
            TaskType.APP_CREATE,
        )
        assert result.needs_project_setup is True

    def test_non_coding_task_no_project_setup(self):
        from core.complexity import ComplexityAssessor
        from core.task_queue import TaskType

        assessor = ComplexityAssessor(router=None)

        result = assessor._keyword_assess(
            "Write a blog post about AI trends",
            TaskType.CONTENT,
        )
        # Content tasks don't trigger project setup
        assert result.needs_project_setup is False


# ── Intent Classifier Project Setup Tests ────────────────────────────────────


class TestIntentClassifierProjectSetup:
    """Tests for needs_project_setup field in ClassificationResult."""

    def test_classification_result_has_project_setup_field(self):
        from core.intent_classifier import ClassificationResult
        from core.task_queue import TaskType

        result = ClassificationResult(
            task_type=TaskType.CODING,
            needs_project_setup=True,
        )
        assert result.needs_project_setup is True

    def test_classification_result_defaults_false(self):
        from core.intent_classifier import ClassificationResult
        from core.task_queue import TaskType

        result = ClassificationResult(task_type=TaskType.CODING)
        assert result.needs_project_setup is False


# ── TaskType Tests ───────────────────────────────────────────────────────────


class TestProjectSetupTaskType:
    """Tests for the PROJECT_SETUP TaskType."""

    def test_project_setup_exists(self):
        from core.task_queue import TaskType

        assert hasattr(TaskType, "PROJECT_SETUP")
        assert TaskType.PROJECT_SETUP.value == "project_setup"

    def test_task_has_project_fields(self):
        from core.task_queue import Task, TaskType

        task = Task(
            title="Test",
            description="Test",
            task_type=TaskType.PROJECT_SETUP,
            project_id="proj_123",
            project_spec_path="/path/to/spec.md",
        )
        assert task.project_id == "proj_123"
        assert task.project_spec_path == "/path/to/spec.md"

    def test_task_project_fields_default_empty(self):
        from core.task_queue import Task

        task = Task(title="Test", description="Test")
        assert task.project_id == ""
        assert task.project_spec_path == ""

    def test_task_serialization_includes_project_fields(self):
        from core.task_queue import Task, TaskType

        task = Task(
            title="Test",
            description="Test",
            task_type=TaskType.PROJECT_SETUP,
            project_id="proj_abc",
            project_spec_path="/some/path",
        )
        d = task.to_dict()
        assert d["project_id"] == "proj_abc"
        assert d["project_spec_path"] == "/some/path"

    def test_task_deserialization_includes_project_fields(self):
        from core.task_queue import Task, TaskType

        data = {
            "title": "Test",
            "description": "Test",
            "task_type": "project_setup",
            "status": "pending",
            "project_id": "proj_xyz",
            "project_spec_path": "/path/spec.md",
        }
        task = Task.from_dict(data)
        assert task.task_type == TaskType.PROJECT_SETUP
        assert task.project_id == "proj_xyz"
        assert task.project_spec_path == "/path/spec.md"


# ── Model Router Tests ───────────────────────────────────────────────────────


class TestProjectSetupRouting:
    """Tests for PROJECT_SETUP model routing."""

    def test_free_routing_has_project_setup(self):
        # Import FREE_ROUTING dict directly to avoid the ProviderRegistry
        # import chain which requires openai (not always installed in test env)
        try:
            from agents.model_router import FREE_ROUTING
            from core.task_queue import TaskType

            assert TaskType.PROJECT_SETUP in FREE_ROUTING
            routing = FREE_ROUTING[TaskType.PROJECT_SETUP]
            assert "primary" in routing
            assert "critic" in routing
            assert "max_iterations" in routing
            # Should have low iterations — mostly conversational
            assert routing["max_iterations"] <= 5
        except ImportError:
            # openai not installed — verify TaskType exists at least
            from core.task_queue import TaskType

            assert TaskType.PROJECT_SETUP.value == "project_setup"


# ── Config Tests ─────────────────────────────────────────────────────────────


class TestProjectInterviewConfig:
    """Tests for project interview configuration settings."""

    def test_default_config_values(self):
        from core.config import Settings

        s = Settings()
        assert s.project_interview_enabled is True
        assert s.project_interview_mode == "auto"
        assert s.project_interview_max_rounds == 4
        assert s.project_interview_min_complexity == "moderate"
