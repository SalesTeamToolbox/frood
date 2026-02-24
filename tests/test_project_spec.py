"""Tests for core/project_spec.py — ProjectSpecGenerator."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.project_spec import ProjectSpecGenerator

# Minimal project data used across multiple tests
MINIMAL_PROJECT_DATA = {
    "project_type": "new_project",
    "complexity": "moderate",
    "description": "A todo list app",
    "rounds": [
        {
            "theme": "discovery",
            "extracted_answers": {
                "goals": "Manage daily tasks",
                "target_users": "Individual users",
            },
            "key_insights": ["Simple CRUD app"],
        }
    ],
}


class TestProjectSpecGeneratorNoRouter:
    """Tests for template-based generation (no LLM router)."""

    def setup_method(self):
        self.generator = ProjectSpecGenerator(router=None)

    @pytest.mark.asyncio
    async def test_generate_falls_back_to_template(self):
        """generate() returns a non-empty string when no router is set."""
        result = await self.generator.generate(MINIMAL_PROJECT_DATA)
        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_generate_includes_project_type(self):
        """Template output contains the project type."""
        result = await self.generator.generate(MINIMAL_PROJECT_DATA)
        assert "new_project" in result or "Project Specification" in result

    @pytest.mark.asyncio
    async def test_generate_subtasks_fallback(self):
        """generate_subtasks() returns a list when no router is set."""
        subtasks = await self.generator.generate_subtasks("# Spec\nA todo app.", "new_project")
        assert isinstance(subtasks, list)
        assert len(subtasks) > 0

    @pytest.mark.asyncio
    async def test_generate_subtasks_fallback_feature(self):
        """generate_subtasks() uses feature template for new_feature type."""
        subtasks = await self.generator.generate_subtasks("# Spec\nAdd dark mode.", "new_feature")
        assert isinstance(subtasks, list)
        assert len(subtasks) > 0

    def test_validate_completeness_empty_rounds(self):
        """validate_completeness() handles empty rounds gracefully."""
        result = self.generator.validate_completeness({"rounds": []})
        assert isinstance(result, dict)
        assert "complete" in result
        assert "coverage" in result

    def test_validate_completeness_with_answers(self):
        """validate_completeness() reports higher coverage when answers present."""
        data = {
            "rounds": [
                {
                    "extracted_answers": {
                        "goals": "Do something useful",
                        "users": "Developers",
                    }
                }
            ]
        }
        result = self.generator.validate_completeness(data)
        assert result["coverage"] > 0.0

    def test_parse_json_response_valid(self):
        """_parse_json_response() parses valid JSON strings."""
        result = self.generator._parse_json_response('{"key": "value"}')
        assert result == {"key": "value"}

    def test_parse_json_response_json_block(self):
        """_parse_json_response() strips markdown code fences."""
        raw = '```json\n{"key": "value"}\n```'
        result = self.generator._parse_json_response(raw)
        assert result == {"key": "value"}

    def test_parse_json_response_invalid(self):
        """_parse_json_response() returns None for non-JSON input."""
        result = self.generator._parse_json_response("not json at all")
        assert result is None


class TestProjectSpecGeneratorWithRouter:
    """Tests for LLM-backed generation (mocked router)."""

    def setup_method(self):
        self.mock_router = MagicMock()
        self.generator = ProjectSpecGenerator(router=self.mock_router)

    @pytest.mark.asyncio
    async def test_generate_uses_router_complete_tuple(self):
        """generate() correctly unpacks the (str, dict) tuple from router.complete()."""
        spec_json = '{"project_name": "Test", "problem_statement": "x", "goals": "y", "target_users": "z", "in_scope": "a", "out_of_scope": "b", "mvp_definition": "c", "functional_requirements": [], "non_functional_requirements": "d", "architecture": "e", "tech_stack": "f", "data_model": "g", "file_structure": "h", "milestones": [], "risks": [], "assumptions": "i", "acceptance_criteria": "j"}'
        self.mock_router.complete = AsyncMock(return_value=(spec_json, {"tokens": 100}))

        result = await self.generator.generate(MINIMAL_PROJECT_DATA)
        assert isinstance(result, str)
        assert len(result) > 0
        # router.complete was called once for spec generation
        self.mock_router.complete.assert_called_once()

    @pytest.mark.asyncio
    async def test_generate_falls_back_on_bad_json(self):
        """generate() falls back to template if LLM returns invalid JSON."""
        self.mock_router.complete = AsyncMock(return_value=("not valid json", None))

        result = await self.generator.generate(MINIMAL_PROJECT_DATA)
        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_generate_falls_back_on_router_error(self):
        """generate() falls back to template if router.complete() raises."""
        self.mock_router.complete = AsyncMock(side_effect=RuntimeError("network error"))

        result = await self.generator.generate(MINIMAL_PROJECT_DATA)
        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_generate_subtasks_uses_router_complete_tuple(self):
        """generate_subtasks() correctly unpacks the (str, dict) tuple."""
        subtask_json = '[{"title": "Setup", "description": "Init project", "task_type": "coding", "depends_on": [], "estimated_iterations": 3, "acceptance_criteria": ["works"]}]'
        self.mock_router.complete = AsyncMock(return_value=(subtask_json, None))

        subtasks = await self.generator.generate_subtasks("# Spec", "new_project")
        assert isinstance(subtasks, list)
        assert len(subtasks) == 1
        assert subtasks[0]["title"] == "Setup"
        self.mock_router.complete.assert_called_once()

    @pytest.mark.asyncio
    async def test_generate_subtasks_falls_back_on_error(self):
        """generate_subtasks() falls back to default subtasks on router error."""
        self.mock_router.complete = AsyncMock(side_effect=RuntimeError("timeout"))

        subtasks = await self.generator.generate_subtasks("# Spec", "new_project")
        assert isinstance(subtasks, list)
        assert len(subtasks) > 0
