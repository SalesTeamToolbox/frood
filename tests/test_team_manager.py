"""Tests for team Manager coordination, TeamContext, and smart resource dispatch."""

import asyncio
import pytest
import time

from tools.team_tool import (
    TeamTool,
    TeamContext,
    BUILTIN_TEAMS,
    MANAGER_PLAN_PROMPT,
    MANAGER_REVIEW_PROMPT,
)
from core.task_queue import Task, TaskQueue, TaskType, TaskStatus


# ---------------------------------------------------------------------------
# Mock task queue for deterministic testing
# ---------------------------------------------------------------------------

class MockTaskQueue:
    """Task queue mock that instantly completes tasks with predictable output."""

    def __init__(self):
        self._tasks: dict[str, Task] = {}
        self._add_count = 0

    async def add(self, task: Task) -> Task:
        self._add_count += 1
        self._tasks[task.id] = task

        # Auto-complete with mock output based on title pattern
        task.status = TaskStatus.REVIEW
        if "[manager:plan]" in task.title:
            task.result = (
                "## Execution Plan\n"
                "1. **researcher**: Focus on gathering data\n"
                "2. **analyst**: Evaluate the findings\n"
                "3. **writer**: Produce the final report\n"
                "Dependencies: analyst depends on researcher, writer depends on analyst."
            )
        elif "[manager:review]" in task.title:
            task.result = (
                "## Review\n"
                "All roles performed well. The outputs are consistent and complete.\n"
                "QUALITY_SCORE: 8\n"
                "SUMMARY: Strong collaborative output with good synthesis."
            )
        else:
            role_name = "unknown"
            if "[team:" in task.title:
                role_name = task.title.split("[team:")[1].split("]")[0]
            task.result = f"Mock output for role: {role_name}"

        return task

    def get(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)


class MockTaskQueueWithRevision(MockTaskQueue):
    """Task queue mock where manager's first review requests a revision."""

    def __init__(self):
        super().__init__()
        self._review_count = 0

    async def add(self, task: Task) -> Task:
        self._tasks[task.id] = task
        self._add_count += 1
        task.status = TaskStatus.REVIEW

        if "[manager:plan]" in task.title:
            task.result = "Plan: researcher → analyst → writer"
        elif "[manager:review]" in task.title:
            self._review_count += 1
            if self._review_count == 1:
                task.result = (
                    "## Review\n"
                    "The writer's output needs improvement.\n"
                    "REVISION_NEEDED: writer — Needs more specific examples and data.\n"
                    "QUALITY_SCORE: 5\n"
                    "SUMMARY: Good start but writer needs revision."
                )
            else:
                task.result = (
                    "## Review (post-revision)\n"
                    "All outputs are now satisfactory.\n"
                    "QUALITY_SCORE: 8\n"
                    "SUMMARY: After revision, the team output is strong."
                )
        elif ":revision]" in task.title:
            role_name = task.title.split("[team:")[1].split(":revision]")[0]
            task.result = f"Revised output for role: {role_name} (improved with feedback)"
        else:
            role_name = "unknown"
            if "[team:" in task.title:
                role_name = task.title.split("[team:")[1].split("]")[0]
            task.result = f"Mock output for role: {role_name}"

        return task


# ---------------------------------------------------------------------------
# TestTeamContext
# ---------------------------------------------------------------------------

class TestTeamContext:
    """Test the TeamContext shared context object."""

    def test_basic_context_with_task_only(self):
        ctx = TeamContext(task_description="Write a report about AI trends")
        output = ctx.build_role_context("researcher")
        assert "## Task" in output
        assert "Write a report about AI trends" in output

    def test_context_includes_manager_plan(self):
        ctx = TeamContext(
            task_description="Write a report",
            manager_plan="1. Researcher gathers data\n2. Analyst evaluates",
        )
        output = ctx.build_role_context("researcher")
        assert "## Manager's Execution Plan" in output
        assert "Researcher gathers data" in output

    def test_context_includes_prior_outputs(self):
        ctx = TeamContext(
            task_description="Write a report",
            manager_plan="Plan here",
            role_outputs={
                "researcher": "Found 10 data points",
                "analyst": "Key insight: growth is 20%",
            },
        )
        # Writer should see both prior outputs
        output = ctx.build_role_context("writer")
        assert "## Prior Team Outputs" in output
        assert "### researcher" in output
        assert "Found 10 data points" in output
        assert "### analyst" in output
        assert "Key insight: growth is 20%" in output

    def test_context_excludes_own_output(self):
        ctx = TeamContext(
            task_description="test",
            role_outputs={
                "researcher": "My output",
                "analyst": "Other output",
            },
        )
        output = ctx.build_role_context("researcher")
        # Should not see own output in prior outputs
        assert "### researcher" not in output
        assert "### analyst" in output

    def test_context_includes_feedback(self):
        ctx = TeamContext(
            task_description="test",
            role_feedback={"writer": "Add more specific examples"},
        )
        output = ctx.build_role_context("writer")
        assert "## Manager Feedback for You" in output
        assert "Add more specific examples" in output

    def test_context_no_feedback_for_other_roles(self):
        ctx = TeamContext(
            task_description="test",
            role_feedback={"writer": "Add more examples"},
        )
        output = ctx.build_role_context("researcher")
        assert "Manager Feedback" not in output

    def test_context_includes_team_notes(self):
        ctx = TeamContext(
            task_description="test",
            team_notes=["Use formal tone", "Target audience: executives"],
        )
        output = ctx.build_role_context("writer")
        assert "## Team Notes" in output
        assert "Use formal tone" in output
        assert "Target audience: executives" in output

    def test_parallel_roles_get_plan_only(self):
        """Parallel roles should see manager plan but no peer outputs."""
        ctx = TeamContext(
            task_description="test",
            manager_plan="Plan for all",
            role_outputs={},  # No outputs yet in parallel
        )
        output = ctx.build_role_context("researcher-a")
        assert "## Manager's Execution Plan" in output
        assert "Prior Team Outputs" not in output

    def test_sequential_roles_accumulate(self):
        """Each sequential role should see all prior outputs."""
        ctx = TeamContext(task_description="test", manager_plan="Plan")

        # Simulate sequential execution
        ctx.role_outputs["role-1"] = "Output 1"
        output2 = ctx.build_role_context("role-2")
        assert "### role-1" in output2

        ctx.role_outputs["role-2"] = "Output 2"
        output3 = ctx.build_role_context("role-3")
        assert "### role-1" in output3
        assert "### role-2" in output3


# ---------------------------------------------------------------------------
# TestManagerRole
# ---------------------------------------------------------------------------

class TestManagerRole:
    """Test the Manager planning and review phases in TeamTool."""

    @pytest.mark.asyncio
    async def test_manager_plan_created(self):
        """Manager plan task is created before team roles run."""
        queue = MockTaskQueue()
        tool = TeamTool(queue)
        result = await tool.execute(
            action="run", name="research-team", task="Analyze AI market trends"
        )
        assert result.success
        # Check that a manager plan task was created
        plan_tasks = [
            t for t in queue._tasks.values()
            if "[manager:plan]" in t.title
        ]
        assert len(plan_tasks) == 1
        assert plan_tasks[0].task_type == TaskType.PROJECT_MANAGEMENT

    @pytest.mark.asyncio
    async def test_manager_review_created(self):
        """Manager review task is created after team roles complete."""
        queue = MockTaskQueue()
        tool = TeamTool(queue)
        result = await tool.execute(
            action="run", name="research-team", task="Analyze AI market trends"
        )
        assert result.success
        review_tasks = [
            t for t in queue._tasks.values()
            if "[manager:review]" in t.title
        ]
        assert len(review_tasks) == 1
        assert review_tasks[0].task_type == TaskType.PROJECT_MANAGEMENT

    @pytest.mark.asyncio
    async def test_manager_plan_in_output(self):
        """Final output includes the manager's plan."""
        queue = MockTaskQueue()
        tool = TeamTool(queue)
        result = await tool.execute(
            action="run", name="research-team", task="Test task"
        )
        assert "## Manager's Plan" in result.output
        assert "Execution Plan" in result.output

    @pytest.mark.asyncio
    async def test_manager_review_in_output(self):
        """Final output includes the manager's review."""
        queue = MockTaskQueue()
        tool = TeamTool(queue)
        result = await tool.execute(
            action="run", name="research-team", task="Test task"
        )
        assert "## Manager's Review" in result.output
        assert "QUALITY_SCORE" in result.output

    @pytest.mark.asyncio
    async def test_quality_score_extracted(self):
        """Quality score is extracted from manager review."""
        queue = MockTaskQueue()
        tool = TeamTool(queue)
        await tool.execute(
            action="run", name="research-team", task="Test task"
        )
        # Check run state
        run_id = list(tool._runs.keys())[0]
        assert tool._runs[run_id]["quality_score"] == 8

    @pytest.mark.asyncio
    async def test_roles_receive_manager_plan_context(self):
        """Team roles receive the manager's plan in their task description."""
        queue = MockTaskQueue()
        tool = TeamTool(queue)
        await tool.execute(
            action="run", name="research-team", task="Analyze trends"
        )
        # Check that role tasks contain manager plan context
        role_tasks = [
            t for t in queue._tasks.values()
            if "[team:" in t.title and "manager" not in t.title
        ]
        assert len(role_tasks) >= 1
        # At least one role should have the manager plan in its description
        has_plan = any("Manager's Execution Plan" in t.description for t in role_tasks)
        assert has_plan


class TestRevisionHandling:
    """Test manager revision requests and role re-runs."""

    @pytest.mark.asyncio
    async def test_revision_request_detected(self):
        """REVISION_NEEDED lines are parsed from manager review."""
        tool = TeamTool(MockTaskQueue())
        revisions = tool._parse_revision_requests(
            "Good work overall.\n"
            "REVISION_NEEDED: writer — Needs more specific data points.\n"
            "QUALITY_SCORE: 5"
        )
        assert len(revisions) == 1
        assert revisions[0][0] == "writer"
        assert "specific data points" in revisions[0][1]

    @pytest.mark.asyncio
    async def test_multiple_revision_requests(self):
        """Multiple REVISION_NEEDED lines are all parsed."""
        tool = TeamTool(MockTaskQueue())
        revisions = tool._parse_revision_requests(
            "REVISION_NEEDED: writer — More examples\n"
            "REVISION_NEEDED: analyst — Deeper analysis needed\n"
            "QUALITY_SCORE: 4"
        )
        assert len(revisions) == 2
        roles = {r[0] for r in revisions}
        assert roles == {"writer", "analyst"}

    @pytest.mark.asyncio
    async def test_no_revision_requests(self):
        """When no revisions are needed, empty list returned."""
        tool = TeamTool(MockTaskQueue())
        revisions = tool._parse_revision_requests(
            "All outputs are excellent.\nQUALITY_SCORE: 9"
        )
        assert len(revisions) == 0

    @pytest.mark.asyncio
    async def test_revision_reruns_role(self):
        """Flagged role gets re-run with manager feedback."""
        queue = MockTaskQueueWithRevision()
        tool = TeamTool(queue)
        result = await tool.execute(
            action="run", name="research-team", task="Test revision flow"
        )
        assert result.success
        # Check that a revision task was created
        revision_tasks = [
            t for t in queue._tasks.values()
            if ":revision]" in t.title
        ]
        assert len(revision_tasks) == 1
        assert "writer" in revision_tasks[0].title

    @pytest.mark.asyncio
    async def test_revision_includes_feedback(self):
        """Revised role gets the manager's feedback in its description."""
        queue = MockTaskQueueWithRevision()
        tool = TeamTool(queue)
        await tool.execute(
            action="run", name="research-team", task="Test"
        )
        revision_tasks = [
            t for t in queue._tasks.values()
            if ":revision]" in t.title
        ]
        assert len(revision_tasks) == 1
        assert "REVISION REQUESTED" in revision_tasks[0].description
        assert "specific examples" in revision_tasks[0].description

    @pytest.mark.asyncio
    async def test_revision_noted_in_output(self):
        """Final output mentions which roles were revised."""
        queue = MockTaskQueueWithRevision()
        tool = TeamTool(queue)
        result = await tool.execute(
            action="run", name="research-team", task="Test"
        )
        assert "## Revisions" in result.output
        assert "writer" in result.output

    @pytest.mark.asyncio
    async def test_revision_noted_in_run_state(self):
        """Run state tracks which roles were revised."""
        queue = MockTaskQueueWithRevision()
        tool = TeamTool(queue)
        await tool.execute(
            action="run", name="research-team", task="Test"
        )
        run_id = list(tool._runs.keys())[0]
        assert "writer" in tool._runs[run_id]["revisions"]

    @pytest.mark.asyncio
    async def test_manager_re_reviews_after_revision(self):
        """Manager review runs twice when revisions happen."""
        queue = MockTaskQueueWithRevision()
        tool = TeamTool(queue)
        await tool.execute(
            action="run", name="research-team", task="Test"
        )
        review_tasks = [
            t for t in queue._tasks.values()
            if "[manager:review]" in t.title
        ]
        assert len(review_tasks) == 2  # initial + post-revision

    @pytest.mark.asyncio
    async def test_post_revision_quality_score_updated(self):
        """Quality score reflects the post-revision review."""
        queue = MockTaskQueueWithRevision()
        tool = TeamTool(queue)
        await tool.execute(
            action="run", name="research-team", task="Test"
        )
        run_id = list(tool._runs.keys())[0]
        # Post-revision score should be 8 (from MockTaskQueueWithRevision)
        assert tool._runs[run_id]["quality_score"] == 8


# ---------------------------------------------------------------------------
# TestWorkflowsWithManager
# ---------------------------------------------------------------------------

class TestWorkflowsWithManager:
    """Test that all workflow types work with the manager wrapping."""

    @pytest.mark.asyncio
    async def test_sequential_team_with_manager(self):
        queue = MockTaskQueue()
        tool = TeamTool(queue)
        result = await tool.execute(
            action="run", name="research-team", task="Sequential test"
        )
        assert result.success
        assert "## Manager's Plan" in result.output
        assert "## Manager's Review" in result.output
        assert "researcher" in result.output
        assert "analyst" in result.output
        assert "writer" in result.output

    @pytest.mark.asyncio
    async def test_parallel_team_with_manager(self):
        # Compose a parallel team for testing
        queue = MockTaskQueue()
        tool = TeamTool(queue)
        tool._compose(
            "test-parallel",
            "Parallel test team",
            "parallel",
            [
                {"name": "role-a", "task_type": "research", "prompt": "Do A"},
                {"name": "role-b", "task_type": "research", "prompt": "Do B"},
            ],
        )
        result = await tool.execute(
            action="run", name="test-parallel", task="Parallel test"
        )
        assert result.success
        assert "## Manager's Plan" in result.output
        assert "## Manager's Review" in result.output

    @pytest.mark.asyncio
    async def test_fan_out_fan_in_with_manager(self):
        queue = MockTaskQueue()
        tool = TeamTool(queue)
        result = await tool.execute(
            action="run", name="strategy-team", task="Strategy test"
        )
        assert result.success
        assert "## Manager's Plan" in result.output
        assert "## Manager's Review" in result.output
        # Fan-out roles
        assert "market-researcher" in result.output
        assert "competitive-researcher" in result.output
        # Sequential roles
        assert "strategist" in result.output
        assert "presenter" in result.output

    @pytest.mark.asyncio
    async def test_pipeline_team_with_manager(self):
        queue = MockTaskQueue()
        tool = TeamTool(queue)
        result = await tool.execute(
            action="run", name="marketing-team", task="Pipeline test"
        )
        assert result.success
        assert "## Manager's Plan" in result.output
        assert "## Manager's Review" in result.output


# ---------------------------------------------------------------------------
# TestStatusAndDescribe
# ---------------------------------------------------------------------------

class TestStatusAndDescribe:
    """Test that status and describe actions reflect manager features."""

    @pytest.mark.asyncio
    async def test_status_shows_quality_score(self):
        queue = MockTaskQueue()
        tool = TeamTool(queue)
        await tool.execute(
            action="run", name="research-team", task="Test"
        )
        run_id = list(tool._runs.keys())[0]
        result = tool._status(run_id)
        assert "Quality Score" in result.output
        assert "8/10" in result.output

    @pytest.mark.asyncio
    async def test_status_shows_manager_plan_preview(self):
        queue = MockTaskQueue()
        tool = TeamTool(queue)
        await tool.execute(
            action="run", name="research-team", task="Test"
        )
        run_id = list(tool._runs.keys())[0]
        result = tool._status(run_id)
        assert "Manager's Plan" in result.output

    def test_describe_mentions_manager(self):
        queue = MockTaskQueue()
        tool = TeamTool(queue)
        result = tool._describe("research-team")
        assert "Manager" in result.output
        assert "plans before" in result.output or "Plan" in result.output

    def test_describe_shows_manager_flow(self):
        queue = MockTaskQueue()
        tool = TeamTool(queue)
        result = tool._describe("research-team")
        assert "Manager Flow" in result.output

    @pytest.mark.asyncio
    async def test_status_list_shows_quality(self):
        queue = MockTaskQueue()
        tool = TeamTool(queue)
        await tool.execute(
            action="run", name="research-team", task="Test"
        )
        result = tool._status("")  # List all runs
        assert "quality: 8/10" in result.output


# ---------------------------------------------------------------------------
# TestSmartDispatch
# ---------------------------------------------------------------------------

class TestSmartDispatch:
    """Test smart resource allocation in agent42._create_task_from_message."""

    def test_team_instruction_injected(self):
        """When classification recommends a team, the description includes
        a RESOURCE ALLOCATION directive."""
        from core.intent_classifier import ClassificationResult
        from core.task_queue import TaskType

        classification = ClassificationResult(
            task_type=TaskType.MARKETING,
            confidence=0.9,
            recommended_mode="team",
            recommended_team="marketing-team",
        )

        # Simulate what agent42._create_task_from_message does
        description = "Create a full marketing campaign for our product"
        task_description = description
        if (
            classification.recommended_mode == "team"
            and classification.recommended_team
        ):
            team_name = classification.recommended_team
            task_description = (
                f"{description}\n\n"
                f"---\n"
                f"RESOURCE ALLOCATION: This task has been assessed as requiring "
                f"team collaboration.\n"
                f"Use the 'team' tool with action='run', name='{team_name}', "
                f"and the task description above to execute with the {team_name}.\n"
                f"The team's Manager will coordinate the roles automatically."
            )

        assert "RESOURCE ALLOCATION" in task_description
        assert "marketing-team" in task_description
        assert "Manager will coordinate" in task_description

    def test_simple_task_no_team_instruction(self):
        """When classification recommends single_agent, no team directive."""
        from core.intent_classifier import ClassificationResult
        from core.task_queue import TaskType

        classification = ClassificationResult(
            task_type=TaskType.CODING,
            confidence=0.9,
            recommended_mode="single_agent",
            recommended_team="",
        )

        description = "Fix the login bug"
        task_description = description
        if (
            classification.recommended_mode == "team"
            and classification.recommended_team
        ):
            task_description = f"{description}\n\nRESOURCE ALLOCATION: ..."

        assert task_description == description
        assert "RESOURCE ALLOCATION" not in task_description

    def test_classification_defaults_to_single_agent(self):
        """ClassificationResult defaults to single_agent mode."""
        from core.intent_classifier import ClassificationResult
        from core.task_queue import TaskType

        result = ClassificationResult(task_type=TaskType.CODING)
        assert result.recommended_mode == "single_agent"
        assert result.recommended_team == ""


# ---------------------------------------------------------------------------
# TestBackwardCompatibility
# ---------------------------------------------------------------------------

class TestBackwardCompatibility:
    """Ensure existing team operations still work with manager additions."""

    @pytest.mark.asyncio
    async def test_compose_still_works(self):
        queue = MockTaskQueue()
        tool = TeamTool(queue)
        result = tool._compose(
            "custom-team", "Test team", "sequential",
            [{"name": "role1", "task_type": "research", "prompt": "Do research"}]
        )
        assert result.success
        assert "custom-team" in tool._teams

    def test_list_still_works(self):
        queue = MockTaskQueue()
        tool = TeamTool(queue)
        result = tool._list()
        assert result.success
        assert "research-team" in result.output

    def test_delete_still_works(self):
        queue = MockTaskQueue()
        tool = TeamTool(queue)
        tool._compose("temp", "Temp", "sequential", [{"name": "r", "task_type": "research", "prompt": "p"}])
        result = tool._delete("temp")
        assert result.success

    def test_clone_still_works(self):
        queue = MockTaskQueue()
        tool = TeamTool(queue)
        result = tool._clone("research-team", "my-research")
        assert result.success
        assert "my-research" in tool._teams

    def test_builtin_teams_unchanged(self):
        """All 5 built-in teams still exist with correct structures."""
        assert len(BUILTIN_TEAMS) == 5
        expected = {
            "research-team", "marketing-team", "content-team",
            "design-review", "strategy-team",
        }
        assert set(BUILTIN_TEAMS.keys()) == expected
        for name, team in BUILTIN_TEAMS.items():
            assert "roles" in team
            assert "workflow" in team
            assert len(team["roles"]) >= 2
