"""Tests for coding team definitions and execution."""

import pytest

from core.task_queue import TaskStatus
from tools.team_tool import BUILTIN_TEAMS, TeamTool

# ---------------------------------------------------------------------------
# Mock task queue (same pattern as test_team_tool.py)
# ---------------------------------------------------------------------------


class MockTaskQueue:
    """Simplified task queue for testing team tool without full infrastructure."""

    def __init__(self):
        self._tasks = {}

    async def add(self, task):
        self._tasks[task.id] = task
        task.status = TaskStatus.REVIEW
        if "[manager:plan]" in task.title:
            task.result = "## Plan\n1. Execute coding roles in order."
        elif "[manager:review]" in task.title:
            task.result = (
                "## Review\nAll outputs are consistent.\nQUALITY_SCORE: 8\nSUMMARY: Good work."
            )
        else:
            role_name = "unknown"
            if "[team:" in task.title:
                role_name = task.title.split("[team:")[1].split("]")[0]
            task.result = f"Mock output for role: {role_name}"
        return task

    def get(self, task_id):
        return self._tasks.get(task_id)


# ---------------------------------------------------------------------------
# Structural tests — validate team definitions
# ---------------------------------------------------------------------------


class TestCodingTeamStructure:
    """Validate structure of the 3 new coding team definitions."""

    _CODING_TEAMS = ["code-review-team", "dev-team", "qa-team"]
    _VALID_WORKFLOWS = {"sequential", "parallel", "fan_out_fan_in", "pipeline"}

    def test_coding_teams_exist_in_builtins(self):
        for name in self._CODING_TEAMS:
            assert name in BUILTIN_TEAMS, f"{name} missing from BUILTIN_TEAMS"

    def test_code_review_team_has_valid_structure(self):
        team = BUILTIN_TEAMS["code-review-team"]
        assert team["name"] == "code-review-team"
        assert team["workflow"] in self._VALID_WORKFLOWS
        assert len(team["roles"]) >= 2

    def test_dev_team_has_valid_structure(self):
        team = BUILTIN_TEAMS["dev-team"]
        assert team["name"] == "dev-team"
        assert team["workflow"] in self._VALID_WORKFLOWS
        assert len(team["roles"]) >= 3

    def test_qa_team_has_valid_structure(self):
        team = BUILTIN_TEAMS["qa-team"]
        assert team["name"] == "qa-team"
        assert team["workflow"] in self._VALID_WORKFLOWS
        assert len(team["roles"]) >= 2

    def test_dev_team_has_parallel_groups(self):
        team = BUILTIN_TEAMS["dev-team"]
        parallel_roles = [r for r in team["roles"] if r.get("parallel_group")]
        assert len(parallel_roles) >= 2, "dev-team should have parallel implementation roles"

    def test_all_coding_team_roles_have_required_fields(self):
        for team_name in self._CODING_TEAMS:
            team = BUILTIN_TEAMS[team_name]
            for role in team["roles"]:
                assert "name" in role, f"{team_name}: role missing name"
                assert "task_type" in role, f"{team_name}.{role.get('name')}: missing task_type"
                assert "prompt" in role, f"{team_name}.{role.get('name')}: missing prompt"

    def test_coding_teams_use_code_task_types(self):
        """Coding teams should only use code-related task types."""
        code_types = {"coding", "debugging", "refactoring"}
        for team_name in self._CODING_TEAMS:
            team = BUILTIN_TEAMS[team_name]
            for role in team["roles"]:
                assert role["task_type"] in code_types, (
                    f"{team_name}.{role['name']} uses non-code task_type: {role['task_type']}"
                )

    def test_code_review_team_role_names(self):
        team = BUILTIN_TEAMS["code-review-team"]
        role_names = [r["name"] for r in team["roles"]]
        assert "developer" in role_names
        assert "reviewer" in role_names
        assert "tester" in role_names

    def test_dev_team_role_names(self):
        team = BUILTIN_TEAMS["dev-team"]
        role_names = [r["name"] for r in team["roles"]]
        assert "architect" in role_names
        assert "backend-dev" in role_names
        assert "frontend-dev" in role_names
        assert "integrator" in role_names

    def test_qa_team_role_names(self):
        team = BUILTIN_TEAMS["qa-team"]
        role_names = [r["name"] for r in team["roles"]]
        assert "analyzer" in role_names
        assert "test-writer" in role_names
        assert "security-auditor" in role_names


# ---------------------------------------------------------------------------
# Execution tests — run coding teams with mock queue
# ---------------------------------------------------------------------------


class TestCodingTeamExecution:
    """Test coding team execution with MockTaskQueue."""

    def setup_method(self):
        self.queue = MockTaskQueue()
        self.tool = TeamTool(self.queue)

    @pytest.mark.asyncio
    async def test_run_code_review_team(self):
        result = await self.tool.execute(
            action="run",
            name="code-review-team",
            task="Review the authentication module for security issues",
        )
        assert result.success
        assert "developer" in result.output
        assert "reviewer" in result.output
        assert "tester" in result.output

    @pytest.mark.asyncio
    async def test_run_dev_team(self):
        result = await self.tool.execute(
            action="run",
            name="dev-team",
            task="Implement a user authentication module with login and signup",
        )
        assert result.success
        assert "architect" in result.output
        assert "backend-dev" in result.output
        assert "frontend-dev" in result.output
        assert "integrator" in result.output

    @pytest.mark.asyncio
    async def test_run_qa_team(self):
        result = await self.tool.execute(
            action="run",
            name="qa-team",
            task="Audit the payment processing module for bugs and vulnerabilities",
        )
        assert result.success
        assert "analyzer" in result.output
        assert "test-writer" in result.output
        assert "security-auditor" in result.output

    @pytest.mark.asyncio
    async def test_list_includes_coding_teams(self):
        result = await self.tool.execute(action="list")
        assert result.success
        assert "code-review-team" in result.output
        assert "dev-team" in result.output
        assert "qa-team" in result.output

    @pytest.mark.asyncio
    async def test_describe_code_review_team(self):
        result = await self.tool.execute(action="describe", name="code-review-team")
        assert result.success
        assert "developer" in result.output
        assert "reviewer" in result.output

    @pytest.mark.asyncio
    async def test_describe_dev_team(self):
        result = await self.tool.execute(action="describe", name="dev-team")
        assert result.success
        assert "architect" in result.output

    @pytest.mark.asyncio
    async def test_cannot_delete_coding_builtin_teams(self):
        for name in ["code-review-team", "dev-team", "qa-team"]:
            result = await self.tool.execute(action="delete", name=name)
            assert not result.success
            assert "built-in" in result.error.lower()
