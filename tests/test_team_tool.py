"""Tests for the TeamTool — multi-agent team orchestration."""

import json

import pytest

from core.plan_spec import PlanTask
from core.task_queue import TaskStatus
from tools.team_tool import BUILTIN_TEAMS, TeamTool


class MockTaskQueue:
    """Simplified task queue for testing team tool without full infrastructure."""

    def __init__(self):
        self._tasks = {}

    async def add(self, task):
        self._tasks[task.id] = task
        # Simulate immediate completion for testing
        task.status = TaskStatus.REVIEW
        task.result = f"Mock output for: {task.title}"
        return task

    def get(self, task_id):
        return self._tasks.get(task_id)


class TestTeamToolBasics:
    """Test team compose, list, delete operations."""

    def setup_method(self):
        self.queue = MockTaskQueue()
        self.tool = TeamTool(self.queue)

    @pytest.mark.asyncio
    async def test_list_includes_builtins(self):
        result = await self.tool.execute(action="list")
        assert result.success
        for name in BUILTIN_TEAMS:
            assert name in result.output

    @pytest.mark.asyncio
    async def test_compose_custom_team(self):
        result = await self.tool.execute(
            action="compose",
            name="my-team",
            description="Test team",
            workflow="sequential",
            roles=[
                {"name": "writer", "task_type": "content", "prompt": "Write something"},
                {"name": "editor", "task_type": "content", "prompt": "Edit it"},
            ],
        )
        assert result.success
        assert "my-team" in result.output
        assert "2 roles" in result.output

    @pytest.mark.asyncio
    async def test_compose_requires_name(self):
        result = await self.tool.execute(
            action="compose",
            roles=[{"name": "test", "task_type": "research", "prompt": "do"}],
        )
        assert not result.success
        assert "name" in result.error.lower()

    @pytest.mark.asyncio
    async def test_compose_requires_roles(self):
        result = await self.tool.execute(action="compose", name="empty-team")
        assert not result.success
        assert "role" in result.error.lower()

    @pytest.mark.asyncio
    async def test_delete_custom_team(self):
        await self.tool.execute(
            action="compose",
            name="temp-team",
            roles=[{"name": "a", "task_type": "research", "prompt": "x"}],
        )
        result = await self.tool.execute(action="delete", name="temp-team")
        assert result.success

    @pytest.mark.asyncio
    async def test_delete_builtin_fails(self):
        result = await self.tool.execute(action="delete", name="research-team")
        assert not result.success
        assert "built-in" in result.error.lower()

    @pytest.mark.asyncio
    async def test_delete_nonexistent_fails(self):
        result = await self.tool.execute(action="delete", name="nope")
        assert not result.success

    @pytest.mark.asyncio
    async def test_action_required(self):
        result = await self.tool.execute()
        assert not result.success


class TestTeamToolRun:
    """Test team execution workflows."""

    def setup_method(self):
        self.queue = MockTaskQueue()
        self.tool = TeamTool(self.queue)

    @pytest.mark.asyncio
    async def test_run_sequential_team(self):
        await self.tool.execute(
            action="compose",
            name="test-seq",
            workflow="sequential",
            roles=[
                {"name": "researcher", "task_type": "research", "prompt": "Research this"},
                {"name": "writer", "task_type": "content", "prompt": "Write about it"},
            ],
        )
        result = await self.tool.execute(
            action="run",
            name="test-seq",
            task="Investigate AI trends",
        )
        assert result.success
        assert "researcher" in result.output
        assert "writer" in result.output

    @pytest.mark.asyncio
    async def test_run_parallel_team(self):
        await self.tool.execute(
            action="compose",
            name="test-par",
            workflow="parallel",
            roles=[
                {"name": "agent-a", "task_type": "research", "prompt": "Research aspect A"},
                {"name": "agent-b", "task_type": "research", "prompt": "Research aspect B"},
            ],
        )
        result = await self.tool.execute(
            action="run",
            name="test-par",
            task="Compare cloud providers",
        )
        assert result.success
        assert "agent-a" in result.output
        assert "agent-b" in result.output

    @pytest.mark.asyncio
    async def test_run_requires_task(self):
        result = await self.tool.execute(action="run", name="research-team")
        assert not result.success
        assert "task" in result.error.lower()

    @pytest.mark.asyncio
    async def test_run_nonexistent_team_fails(self):
        result = await self.tool.execute(action="run", name="nope", task="something")
        assert not result.success

    @pytest.mark.asyncio
    async def test_run_builtin_team(self):
        result = await self.tool.execute(
            action="run",
            name="content-team",
            task="Write a blog post about productivity",
        )
        assert result.success
        assert "writer" in result.output
        assert "editor" in result.output
        assert "seo-optimizer" in result.output

    @pytest.mark.asyncio
    async def test_status_no_runs(self):
        result = await self.tool.execute(action="status")
        assert result.success
        assert "No team runs" in result.output

    @pytest.mark.asyncio
    async def test_status_after_run(self):
        await self.tool.execute(
            action="run",
            name="content-team",
            task="Write something",
        )
        result = await self.tool.execute(action="status")
        assert result.success
        assert "content-team" in result.output


class TestTeamToolBuiltins:
    """Test that all built-in teams have valid structure."""

    def test_all_builtins_have_roles(self):
        for name, team in BUILTIN_TEAMS.items():
            assert "roles" in team, f"{name} missing roles"
            assert len(team["roles"]) >= 2, f"{name} should have >= 2 roles"

    def test_all_builtins_have_workflow(self):
        valid_workflows = {"sequential", "parallel", "fan_out_fan_in", "pipeline"}
        for name, team in BUILTIN_TEAMS.items():
            assert team.get("workflow") in valid_workflows, f"{name} invalid workflow"

    def test_all_roles_have_required_fields(self):
        for team_name, team in BUILTIN_TEAMS.items():
            for role in team["roles"]:
                assert "name" in role, f"{team_name}: role missing name"
                assert "task_type" in role, f"{team_name}.{role.get('name')}: missing task_type"
                assert "prompt" in role, f"{team_name}.{role.get('name')}: missing prompt"

    def test_strategy_team_has_parallel_groups(self):
        team = BUILTIN_TEAMS["strategy-team"]
        parallel_roles = [r for r in team["roles"] if r.get("parallel_group")]
        assert len(parallel_roles) >= 2, "Strategy team should have parallel research roles"


class TestStructuredPlanParsing:
    """Test _parse_plan_json on TeamTool."""

    def setup_method(self):
        self.queue = MockTaskQueue()
        self.tool = TeamTool(self.queue)

    def test_parse_valid_json(self):
        plan_json = json.dumps(
            {
                "goal": "Build the thing",
                "observable_truths": ["It works"],
                "required_artifacts": ["output.py"],
                "required_wiring": [],
                "tasks": [
                    {
                        "id": "T1",
                        "title": "Code it",
                        "description": "Write code",
                        "role": "coder",
                        "task_type": "coding",
                        "files_to_read": [],
                        "files_to_modify": ["output.py"],
                        "verification_commands": ["pytest"],
                        "acceptance_criteria": ["Tests pass"],
                        "depends_on": [],
                    }
                ],
            }
        )
        spec = self.tool._parse_plan_json(plan_json)
        assert spec is not None
        assert spec.goal == "Build the thing"
        assert len(spec.tasks) == 1
        assert spec.tasks[0].id == "T1"

    def test_parse_json_with_code_fences(self):
        plan_json = '```json\n{"goal": "Test", "tasks": [{"id": "T1", "title": "X"}]}\n```'
        spec = self.tool._parse_plan_json(plan_json)
        assert spec is not None
        assert spec.goal == "Test"

    def test_parse_json_embedded_in_text(self):
        text = (
            "Here is the plan:\n\n"
            '{"goal": "Test", "tasks": [{"id": "T1", "title": "X"}]}\n\n'
            "That should work."
        )
        spec = self.tool._parse_plan_json(text)
        assert spec is not None
        assert spec.goal == "Test"

    def test_parse_invalid_json_returns_none(self):
        spec = self.tool._parse_plan_json("This is not JSON at all")
        assert spec is None

    def test_parse_json_without_tasks_returns_none(self):
        spec = self.tool._parse_plan_json('{"goal": "No tasks here"}')
        assert spec is None

    def test_parse_empty_string_returns_none(self):
        spec = self.tool._parse_plan_json("")
        assert spec is None


class TestBuildExecutorPrompt:
    """Test _build_executor_prompt on TeamTool."""

    def test_basic_prompt(self):
        from tools.team_tool import TeamContext

        task = PlanTask(
            id="T1",
            title="Build models",
            description="Create User and Post models",
            role="coder",
            files_to_read=["schema.sql"],
            files_to_modify=["models.py"],
            verification_commands=["pytest tests/test_models.py"],
            acceptance_criteria=["User model has email field"],
        )
        ctx = TeamContext(
            task_description="Build a blog",
            manager_plan="Plan here",
            project_id="proj1",
        )
        prompt = TeamTool._build_executor_prompt(task, ctx, {})
        assert "# Task: Build models" in prompt
        assert "Create User and Post models" in prompt
        assert "schema.sql" in prompt
        assert "models.py" in prompt
        assert "pytest tests/test_models.py" in prompt
        assert "User model has email field" in prompt

    def test_prompt_with_dependency_outputs(self):
        from tools.team_tool import TeamContext

        task = PlanTask(
            id="T2",
            title="Build API",
            description="Create endpoints",
            role="coder",
            depends_on=["T1"],
        )
        ctx = TeamContext(
            task_description="Build a blog",
            manager_plan="Plan",
        )
        prior_results = {
            "T1": {
                "output": "Models created successfully",
                "title": "Build models",
            }
        }
        prompt = TeamTool._build_executor_prompt(task, ctx, prior_results)
        assert "Prior Task Outputs" in prompt
        assert "Build models (completed)" in prompt
        assert "Models created successfully" in prompt
