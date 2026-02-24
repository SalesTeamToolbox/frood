"""Tests for the self-learning agent (Learner)."""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from agents.learner import Learner
from memory.store import MemoryStore


class TestLearnerReflection:
    """Post-task reflection and memory update tests."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.memory = MemoryStore(self.tmpdir)
        self.router = MagicMock()

    @pytest.mark.asyncio
    async def test_reflection_updates_memory(self):
        """Reflection should parse [Section] bullets and update memory."""
        self.router.complete = AsyncMock(
            return_value=(
                "## What Worked\n"
                "- Used structured prompts\n\n"
                "## What Didn't Work\n"
                "- Nothing major\n\n"
                "## Lesson Learned\n"
                "Always check the test suite before committing.\n\n"
                "## Memory Update\n"
                "- [Project Conventions] - Run pytest with --strict-markers\n"
                "- [Common Patterns] - API uses /api/v1/{resource} format\n",
                None,
            )
        )

        learner = Learner(self.router, self.memory)
        result = await learner.reflect_on_task(
            title="Fix login bug",
            task_type="debugging",
            iterations=3,
            max_iterations=10,
            iteration_summary="Iteration 1...",
            succeeded=True,
        )

        assert result["succeeded"] is True
        assert result["memory_updates"] == 2
        assert result["lesson"] == "Always check the test suite before committing."

        # Verify memory was actually updated
        memory_content = self.memory.read_memory()
        assert "pytest with --strict-markers" in memory_content
        assert "API uses /api/v1/{resource} format" in memory_content

    @pytest.mark.asyncio
    async def test_reflection_on_failure(self):
        """Failure reflection should still extract lessons."""
        self.router.complete = AsyncMock(
            return_value=(
                "## What Worked\n"
                "- Nothing — task failed immediately\n\n"
                "## What Didn't Work\n"
                "- Missing dependency: pandas not installed\n\n"
                "## Lesson Learned\n"
                "Check requirements.txt before running data processing tasks.\n\n"
                "## Memory Update\n"
                "- [Common Patterns] - This project requires pandas for data tasks\n",
                None,
            )
        )

        learner = Learner(self.router, self.memory)
        result = await learner.reflect_on_task(
            title="Process CSV data",
            task_type="coding",
            iterations=0,
            max_iterations=8,
            iteration_summary="(failed)",
            succeeded=False,
            error="ModuleNotFoundError: No module named 'pandas'",
        )

        assert result["succeeded"] is False
        assert result["memory_updates"] == 1

    @pytest.mark.asyncio
    async def test_reflection_no_memory_updates(self):
        """When reflection says NONE, no memory updates should happen."""
        self.router.complete = AsyncMock(
            return_value=(
                "## What Worked\n- Everything\n\n"
                "## What Didn't Work\n- Nothing\n\n"
                "## Lesson Learned\nNothing new.\n\n"
                "## Memory Update\nNONE\n",
                None,
            )
        )

        learner = Learner(self.router, self.memory)
        result = await learner.reflect_on_task(
            title="Simple task",
            task_type="coding",
            iterations=1,
            max_iterations=8,
            iteration_summary="Done in 1 iteration",
            succeeded=True,
        )

        assert result["memory_updates"] == 0

    @pytest.mark.asyncio
    async def test_reflection_logs_event(self):
        """Reflection should log an event to history."""
        self.router.complete = AsyncMock(
            return_value=(
                "## What Worked\n- Good\n\n"
                "## What Didn't Work\n- Nothing\n\n"
                "## Lesson Learned\nA lesson.\n\n"
                "## Memory Update\nNONE\n",
                None,
            )
        )

        learner = Learner(self.router, self.memory)
        await learner.reflect_on_task(
            title="Test task",
            task_type="coding",
            iterations=2,
            max_iterations=8,
            iteration_summary="Done",
            succeeded=True,
        )

        history = self.memory.read_history()
        assert "reflection" in history
        assert "Test task" in history

    @pytest.mark.asyncio
    async def test_reflection_handles_api_failure(self):
        """If the reflection model call fails, it should not crash."""
        self.router.complete = AsyncMock(side_effect=Exception("API timeout"))

        learner = Learner(self.router, self.memory)
        result = await learner.reflect_on_task(
            title="Broken task",
            task_type="coding",
            iterations=1,
            max_iterations=8,
            iteration_summary="Done",
            succeeded=True,
        )

        assert result["skipped"] is True


class TestLearnerReviewerFeedback:
    """Tests for recording human reviewer feedback."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.memory = MemoryStore(self.tmpdir)
        self.router = MagicMock()

    async def test_approved_feedback_logs_event(self):
        learner = Learner(self.router, self.memory)
        await learner.record_reviewer_feedback(
            task_id="task-123",
            task_title="Add login page",
            feedback="Looks great, ship it!",
            approved=True,
        )

        history = self.memory.read_history()
        assert "APPROVED" in history
        assert "Add login page" in history

    async def test_rejected_feedback_updates_memory(self):
        learner = Learner(self.router, self.memory)
        await learner.record_reviewer_feedback(
            task_id="task-456",
            task_title="Fix API endpoint",
            feedback="Missing input validation on the email field",
            approved=False,
        )

        # Should be in history
        history = self.memory.read_history()
        assert "REJECTED" in history

        # Should be in memory under Reviewer Feedback section
        memory = self.memory.read_memory()
        assert "Reviewer Feedback" in memory
        assert "Missing input validation" in memory

    async def test_rejected_with_empty_feedback_doesnt_update_memory(self):
        learner = Learner(self.router, self.memory)
        await learner.record_reviewer_feedback(
            task_id="task-789",
            task_title="Some task",
            feedback="",
            approved=False,
        )

        # History gets logged regardless
        history = self.memory.read_history()
        assert "REJECTED" in history

        # But empty feedback shouldn't create a memory entry
        memory = self.memory.read_memory()
        assert "Reviewer Feedback" not in memory


class TestLearnerSkillCreation:
    """Tests for automatic skill creation."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.skills_dir = Path(self.tmpdir) / "skills" / "workspace"
        self.memory = MemoryStore(self.tmpdir)
        self.router = MagicMock()

    @pytest.mark.asyncio
    async def test_creates_skill_from_pattern(self):
        self.router.complete = AsyncMock(
            return_value=(
                "CREATE_SKILL\n"
                "name: api-testing\n"
                "description: Standard API testing patterns for this project\n"
                "task_types: [coding, debugging]\n"
                "---\n"
                "# API Testing Skill\n\n"
                "Always use pytest with the --asyncio-mode=auto flag.\n"
                "Check response status codes AND body content.\n",
                None,
            )
        )

        learner = Learner(self.router, self.memory, skills_dir=self.skills_dir)
        result = await learner.check_for_skill_creation(existing_skill_names=["github"])

        assert result is not None
        assert result["name"] == "api-testing"
        assert (self.skills_dir / "api-testing" / "SKILL.md").exists()

        content = (self.skills_dir / "api-testing" / "SKILL.md").read_text()
        assert "api-testing" in content
        assert "pytest" in content

    @pytest.mark.asyncio
    async def test_no_skill_needed(self):
        self.router.complete = AsyncMock(return_value=("NO_SKILL_NEEDED", None))

        learner = Learner(self.router, self.memory, skills_dir=self.skills_dir)
        result = await learner.check_for_skill_creation(existing_skill_names=[])

        assert result is None

    @pytest.mark.asyncio
    async def test_no_skill_creation_without_skills_dir(self):
        """Without a skills_dir, skill creation is disabled."""
        learner = Learner(self.router, self.memory, skills_dir=None)
        result = await learner.check_for_skill_creation(existing_skill_names=[])
        assert result is None

    @pytest.mark.asyncio
    async def test_skill_creation_logs_event(self):
        self.router.complete = AsyncMock(
            return_value=(
                "CREATE_SKILL\n"
                "name: test-skill\n"
                "description: A test skill\n"
                "task_types: [coding]\n"
                "---\n"
                "# Test\nDo the thing.\n",
                None,
            )
        )

        learner = Learner(self.router, self.memory, skills_dir=self.skills_dir)
        await learner.check_for_skill_creation(existing_skill_names=[])

        history = self.memory.read_history()
        assert "skill_created" in history
        assert "test-skill" in history


class TestLearnerMemoryParsing:
    """Unit tests for internal parsing methods."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.memory = MemoryStore(self.tmpdir)
        self.router = MagicMock()
        self.learner = Learner(self.router, self.memory)

    def test_parse_memory_updates_basic(self):
        text = (
            "## Memory Update\n"
            "- [Project Conventions] - Use black for formatting\n"
            "- [Common Patterns] - Models go in app/models/\n"
        )
        updates = self.learner._parse_memory_updates(text)
        assert len(updates) == 2
        assert updates[0] == ("Project Conventions", "Use black for formatting")
        assert updates[1] == ("Common Patterns", "Models go in app/models/")

    def test_parse_memory_updates_none(self):
        text = "## Memory Update\nNONE\n"
        updates = self.learner._parse_memory_updates(text)
        assert len(updates) == 0

    def test_parse_memory_updates_empty(self):
        text = "No memory updates here."
        updates = self.learner._parse_memory_updates(text)
        assert len(updates) == 0

    def test_extract_lesson(self):
        text = (
            "## Lesson Learned\nAlways validate user input before processing.\n\n## Memory Update\n"
        )
        lesson = self.learner._extract_lesson(text)
        assert lesson == "Always validate user input before processing."

    def test_extract_lesson_not_found(self):
        text = "No lesson section here."
        lesson = self.learner._extract_lesson(text)
        assert lesson == ""
