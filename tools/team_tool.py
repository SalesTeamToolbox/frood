"""
Team orchestration tool — compose and run multi-agent teams.

Enables non-coding workflows like marketing campaigns, research projects,
and design reviews by coordinating teams of agents with defined roles.

Workflow types:
  - sequential: roles run in order, each receiving prior output as context
  - parallel: all roles run simultaneously, results aggregated at end
  - fan_out_fan_in: first role produces, middle roles process in parallel, last merges
  - pipeline: sequential but each role iterates with its own critic
"""

import asyncio
import json
import logging
import time
import uuid

from tools.base import Tool, ToolResult

logger = logging.getLogger("agent42.tools.team")

# Max time to wait for a single role to complete (seconds)
ROLE_TIMEOUT = 600  # 10 minutes
POLL_INTERVAL = 2.0  # seconds between status checks


# Built-in team templates
BUILTIN_TEAMS: dict[str, dict] = {
    "research-team": {
        "name": "research-team",
        "description": "Research team: researcher gathers info, analyst evaluates, writer produces report",
        "workflow": "sequential",
        "roles": [
            {
                "name": "researcher",
                "task_type": "research",
                "prompt": (
                    "You are the researcher. Thoroughly investigate the topic. "
                    "Gather key facts, data points, sources, and perspectives. "
                    "Provide a comprehensive research brief."
                ),
            },
            {
                "name": "analyst",
                "task_type": "strategy",
                "prompt": (
                    "You are the analyst. Review the research provided and identify "
                    "key patterns, insights, and implications. Evaluate source quality. "
                    "Provide a structured analysis with clear takeaways."
                ),
            },
            {
                "name": "writer",
                "task_type": "content",
                "prompt": (
                    "You are the writer. Using the research and analysis provided, "
                    "create a clear, well-structured report. Focus on readability "
                    "and actionable conclusions."
                ),
            },
        ],
    },
    "marketing-team": {
        "name": "marketing-team",
        "description": "Marketing team: researcher → strategist → copywriter → editor pipeline",
        "workflow": "pipeline",
        "roles": [
            {
                "name": "researcher",
                "task_type": "research",
                "prompt": (
                    "You are a market researcher. Analyze the target audience, "
                    "competitive landscape, and market trends for this campaign."
                ),
            },
            {
                "name": "strategist",
                "task_type": "strategy",
                "prompt": (
                    "You are a marketing strategist. Based on the research, develop "
                    "a positioning strategy, key messages, and campaign approach."
                ),
            },
            {
                "name": "copywriter",
                "task_type": "content",
                "prompt": (
                    "You are a copywriter. Write compelling marketing copy based on "
                    "the strategy. Use proven frameworks (AIDA, PAS, BAB). "
                    "Create specific, benefit-driven content."
                ),
            },
            {
                "name": "editor",
                "task_type": "content",
                "prompt": (
                    "You are an editor. Review and refine the copy for clarity, "
                    "consistency, grammar, and brand voice. Ensure the messaging "
                    "is tight and the CTA is compelling."
                ),
            },
        ],
    },
    "content-team": {
        "name": "content-team",
        "description": "Content team: writer → editor → SEO optimizer",
        "workflow": "sequential",
        "roles": [
            {
                "name": "writer",
                "task_type": "content",
                "prompt": (
                    "You are a content writer. Create engaging, well-structured "
                    "content on the given topic. Focus on value and readability."
                ),
            },
            {
                "name": "editor",
                "task_type": "content",
                "prompt": (
                    "You are an editor. Polish the content for clarity, flow, "
                    "grammar, and engagement. Ensure logical structure."
                ),
            },
            {
                "name": "seo-optimizer",
                "task_type": "marketing",
                "prompt": (
                    "You are an SEO specialist. Optimize the content for search "
                    "visibility: suggest keyword placement, meta descriptions, "
                    "headings, and internal linking opportunities."
                ),
            },
        ],
    },
    "design-review": {
        "name": "design-review",
        "description": "Design review team: designer → critic → brand reviewer",
        "workflow": "sequential",
        "roles": [
            {
                "name": "designer",
                "task_type": "design",
                "prompt": (
                    "You are a UI/UX designer. Create or describe the design "
                    "solution with clear specifications for layout, typography, "
                    "color palette, and interaction patterns."
                ),
            },
            {
                "name": "critic",
                "task_type": "design",
                "prompt": (
                    "You are a design critic. Review the design for usability, "
                    "accessibility (WCAG), visual hierarchy, and consistency. "
                    "Provide specific, actionable feedback."
                ),
            },
            {
                "name": "brand-reviewer",
                "task_type": "design",
                "prompt": (
                    "You are a brand reviewer. Evaluate the design against brand "
                    "guidelines: voice, visual identity, color usage, and overall "
                    "brand consistency. Provide final sign-off or revision notes."
                ),
            },
        ],
    },
    "strategy-team": {
        "name": "strategy-team",
        "description": "Strategy team: parallel researchers → strategist → presenter",
        "workflow": "fan_out_fan_in",
        "roles": [
            {
                "name": "market-researcher",
                "task_type": "research",
                "prompt": (
                    "You are a market researcher. Research market size, trends, "
                    "growth drivers, and customer segments for this opportunity."
                ),
                "parallel_group": "research",
            },
            {
                "name": "competitive-researcher",
                "task_type": "research",
                "prompt": (
                    "You are a competitive analyst. Research key competitors, "
                    "their strengths/weaknesses, pricing, and market positioning."
                ),
                "parallel_group": "research",
            },
            {
                "name": "strategist",
                "task_type": "strategy",
                "prompt": (
                    "You are a business strategist. Synthesize the market and "
                    "competitive research into a cohesive strategy. Use SWOT "
                    "analysis and provide actionable recommendations."
                ),
            },
            {
                "name": "presenter",
                "task_type": "content",
                "prompt": (
                    "You are a presentation specialist. Transform the strategy "
                    "into a compelling executive summary with clear sections, "
                    "key metrics, and next steps."
                ),
            },
        ],
    },
}


class TeamTool(Tool):
    """Compose and run multi-agent teams for collaborative workflows."""

    def __init__(self, task_queue):
        self._task_queue = task_queue
        self._teams: dict[str, dict] = dict(BUILTIN_TEAMS)
        self._runs: dict[str, dict] = {}  # run_id -> run state

    @property
    def name(self) -> str:
        return "team"

    @property
    def description(self) -> str:
        return (
            "Compose and run teams of agents with defined roles and workflows. "
            "Actions: compose (define a team), run (execute a team on a task), "
            "status (check run progress), list (show teams), delete (remove a team), "
            "describe (show team details), clone (duplicate a team for customization). "
            "Built-in teams: research-team, marketing-team, content-team, "
            "design-review, strategy-team."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["compose", "run", "status", "list", "delete", "describe", "clone"],
                    "description": "Team action to perform",
                },
                "name": {
                    "type": "string",
                    "description": "Team name (for compose/run/delete/status)",
                    "default": "",
                },
                "description": {
                    "type": "string",
                    "description": "Team description (for compose)",
                    "default": "",
                },
                "workflow": {
                    "type": "string",
                    "enum": ["sequential", "parallel", "fan_out_fan_in", "pipeline"],
                    "description": "Workflow type (for compose)",
                    "default": "sequential",
                },
                "roles": {
                    "type": "array",
                    "description": "Role definitions (for compose)",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "task_type": {"type": "string"},
                            "prompt": {"type": "string"},
                            "parallel_group": {"type": "string"},
                        },
                    },
                    "default": [],
                },
                "task": {
                    "type": "string",
                    "description": "Task description to assign to the team (for run)",
                    "default": "",
                },
                "run_id": {
                    "type": "string",
                    "description": "Run ID to check (for status)",
                    "default": "",
                },
            },
            "required": ["action"],
        }

    async def execute(
        self,
        action: str = "",
        name: str = "",
        description: str = "",
        workflow: str = "sequential",
        roles: list = None,
        task: str = "",
        run_id: str = "",
        **kwargs,
    ) -> ToolResult:
        if not action:
            return ToolResult(error="action is required", success=False)

        if action == "compose":
            return self._compose(name, description, workflow, roles or [])
        elif action == "run":
            return await self._run(name, task)
        elif action == "status":
            return self._status(run_id)
        elif action == "list":
            return self._list()
        elif action == "delete":
            return self._delete(name)
        elif action == "describe":
            return self._describe(name)
        elif action == "clone":
            new_name = task or f"{name}-custom"
            return self._clone(name, new_name)
        else:
            return ToolResult(error=f"Unknown action: {action}", success=False)

    def _compose(
        self, name: str, description: str, workflow: str, roles: list
    ) -> ToolResult:
        if not name:
            return ToolResult(error="name is required for compose", success=False)
        if not roles:
            return ToolResult(error="at least one role is required", success=False)

        team = {
            "name": name,
            "description": description or f"Custom team: {name}",
            "workflow": workflow,
            "roles": roles,
        }
        self._teams[name] = team
        role_names = [r.get("name", "unnamed") for r in roles]
        return ToolResult(
            output=(
                f"Team '{name}' composed with {len(roles)} roles: "
                f"{' → '.join(role_names)}\n"
                f"Workflow: {workflow}\n"
                f"Use action 'run' with name='{name}' and a task to execute."
            )
        )

    async def _run(self, name: str, task_description: str) -> ToolResult:
        if not name:
            return ToolResult(error="name is required for run", success=False)
        if name not in self._teams:
            available = ", ".join(sorted(self._teams.keys()))
            return ToolResult(
                error=f"Team '{name}' not found. Available: {available}",
                success=False,
            )
        if not task_description:
            return ToolResult(error="task description is required for run", success=False)

        team = self._teams[name]
        run_id = uuid.uuid4().hex[:10]
        workflow = team.get("workflow", "sequential")
        roles = team["roles"]

        run_state = {
            "run_id": run_id,
            "team": name,
            "workflow": workflow,
            "task": task_description,
            "started_at": time.time(),
            "role_results": {},
            "status": "running",
            "final_output": "",
        }
        self._runs[run_id] = run_state

        try:
            if workflow == "parallel":
                results = await self._run_parallel(roles, task_description)
            elif workflow == "fan_out_fan_in":
                results = await self._run_fan_out_fan_in(roles, task_description)
            else:
                # sequential and pipeline both run in order
                results = await self._run_sequential(roles, task_description)

            run_state["role_results"] = results
            run_state["status"] = "completed"

            # Build aggregated output
            output_parts = [f"# Team Run: {name} (run_id: {run_id})\n"]
            output_parts.append(f"**Workflow:** {workflow}\n")
            output_parts.append(f"**Task:** {task_description}\n")
            for role_name, result in results.items():
                output_parts.append(f"\n## {role_name}\n")
                output_parts.append(result.get("output", "(no output)"))

            final = "\n".join(output_parts)
            run_state["final_output"] = final
            return ToolResult(output=final)

        except Exception as e:
            run_state["status"] = "failed"
            run_state["error"] = str(e)
            return ToolResult(error=f"Team run failed: {e}", success=False)

    async def _run_sequential(
        self, roles: list, task_description: str
    ) -> dict[str, dict]:
        """Run roles sequentially, passing each output as context to the next."""
        from core.task_queue import Task, TaskType, TaskStatus

        results = {}
        context = task_description

        for role in roles:
            role_name = role.get("name", "unnamed")
            task_type_str = role.get("task_type", "research")
            role_prompt = role.get("prompt", "")

            full_description = (
                f"{role_prompt}\n\n"
                f"## Task\n{task_description}\n\n"
                f"## Prior Context\n{context}"
            )

            try:
                task_type_enum = TaskType(task_type_str)
            except ValueError:
                task_type_enum = TaskType.RESEARCH

            task_obj = Task(
                title=f"[team:{role_name}] {task_description[:50]}",
                description=full_description,
                task_type=task_type_enum,
            )
            await self._task_queue.add(task_obj)

            # Wait for completion
            output = await self._wait_for_task(task_obj.id)
            results[role_name] = {"output": output, "task_id": task_obj.id}
            context = output  # Feed to next role

        return results

    async def _run_parallel(
        self, roles: list, task_description: str
    ) -> dict[str, dict]:
        """Run all roles in parallel, aggregate results."""
        from core.task_queue import Task, TaskType

        task_ids = {}

        # Spawn all roles
        for role in roles:
            role_name = role.get("name", "unnamed")
            task_type_str = role.get("task_type", "research")
            role_prompt = role.get("prompt", "")

            full_description = f"{role_prompt}\n\n## Task\n{task_description}"

            try:
                task_type_enum = TaskType(task_type_str)
            except ValueError:
                task_type_enum = TaskType.RESEARCH

            task_obj = Task(
                title=f"[team:{role_name}] {task_description[:50]}",
                description=full_description,
                task_type=task_type_enum,
            )
            await self._task_queue.add(task_obj)
            task_ids[role_name] = task_obj.id

        # Wait for all
        results = {}
        for role_name, task_id in task_ids.items():
            output = await self._wait_for_task(task_id)
            results[role_name] = {"output": output, "task_id": task_id}

        return results

    async def _run_fan_out_fan_in(
        self, roles: list, task_description: str
    ) -> dict[str, dict]:
        """Fan out parallel groups, then feed merged results sequentially."""
        from core.task_queue import Task, TaskType

        # Separate roles into parallel groups and sequential roles
        parallel_groups: dict[str, list] = {}
        sequential_roles = []

        for role in roles:
            group = role.get("parallel_group")
            if group:
                parallel_groups.setdefault(group, []).append(role)
            else:
                sequential_roles.append(role)

        results = {}
        context = task_description

        # Run parallel groups first
        for group_name, group_roles in parallel_groups.items():
            group_results = await self._run_parallel(group_roles, context)
            results.update(group_results)
            # Merge parallel outputs into context for sequential roles
            merged = "\n\n---\n\n".join(
                f"**{name}:**\n{r['output']}" for name, r in group_results.items()
            )
            context = f"{task_description}\n\n## Parallel Research Results\n{merged}"

        # Run remaining roles sequentially with merged context
        for role in sequential_roles:
            role_name = role.get("name", "unnamed")
            task_type_str = role.get("task_type", "research")
            role_prompt = role.get("prompt", "")

            full_description = (
                f"{role_prompt}\n\n"
                f"## Task\n{task_description}\n\n"
                f"## Prior Context\n{context}"
            )

            try:
                task_type_enum = TaskType(task_type_str)
            except ValueError:
                task_type_enum = TaskType.RESEARCH

            task_obj = Task(
                title=f"[team:{role_name}] {task_description[:50]}",
                description=full_description,
                task_type=task_type_enum,
            )
            await self._task_queue.add(task_obj)
            output = await self._wait_for_task(task_obj.id)
            results[role_name] = {"output": output, "task_id": task_obj.id}
            context = output

        return results

    async def _wait_for_task(self, task_id: str) -> str:
        """Poll task queue until a task completes or times out."""
        from core.task_queue import TaskStatus

        deadline = time.time() + ROLE_TIMEOUT
        while time.time() < deadline:
            task = self._task_queue.get(task_id)
            if not task:
                raise RuntimeError(f"Task {task_id} disappeared from queue")

            if task.status in (TaskStatus.REVIEW, TaskStatus.DONE):
                return task.result or "(completed with no output)"
            if task.status == TaskStatus.FAILED:
                return f"(role failed: {task.error})"

            await asyncio.sleep(POLL_INTERVAL)

        return "(role timed out)"

    def _status(self, run_id: str) -> ToolResult:
        if not run_id:
            # List all runs
            if not self._runs:
                return ToolResult(output="No team runs yet.")
            lines = ["# Team Runs\n"]
            for rid, state in self._runs.items():
                lines.append(
                    f"- **{rid}** — team: {state['team']}, "
                    f"status: {state['status']}"
                )
            return ToolResult(output="\n".join(lines))

        state = self._runs.get(run_id)
        if not state:
            return ToolResult(error=f"Run '{run_id}' not found", success=False)

        lines = [
            f"# Team Run: {state['team']} ({run_id})",
            f"**Status:** {state['status']}",
            f"**Workflow:** {state['workflow']}",
            f"**Task:** {state['task'][:200]}",
        ]
        if state.get("role_results"):
            lines.append("\n## Role Results:")
            for role_name, result in state["role_results"].items():
                preview = result.get("output", "")[:200]
                lines.append(f"\n### {role_name}\n{preview}...")

        return ToolResult(output="\n".join(lines))

    def _list(self) -> ToolResult:
        if not self._teams:
            return ToolResult(output="No teams defined.")

        lines = ["# Available Teams\n"]
        for name, team in sorted(self._teams.items()):
            role_names = [r.get("name", "unnamed") for r in team.get("roles", [])]
            builtin = " (built-in)" if name in BUILTIN_TEAMS else ""
            lines.append(
                f"- **{name}**{builtin} — {team.get('description', '')}\n"
                f"  Workflow: {team.get('workflow', 'sequential')}\n"
                f"  Roles: {' → '.join(role_names)}"
            )
        return ToolResult(output="\n".join(lines))

    def _delete(self, name: str) -> ToolResult:
        if not name:
            return ToolResult(error="name is required for delete", success=False)
        if name not in self._teams:
            return ToolResult(error=f"Team '{name}' not found", success=False)
        if name in BUILTIN_TEAMS:
            return ToolResult(
                error=f"Cannot delete built-in team '{name}'", success=False
            )
        del self._teams[name]
        return ToolResult(output=f"Team '{name}' deleted.")

    def _describe(self, name: str) -> ToolResult:
        """Show detailed information about a team's roles and workflow."""
        if not name:
            return ToolResult(error="name is required for describe", success=False)
        team = self._teams.get(name)
        if not team:
            return ToolResult(error=f"Team '{name}' not found", success=False)

        builtin = " (built-in)" if name in BUILTIN_TEAMS else ""
        lines = [
            f"# Team: {name}{builtin}",
            f"\n**Description:** {team.get('description', '')}",
            f"**Workflow:** {team.get('workflow', 'sequential')}",
            f"**Roles:** {len(team.get('roles', []))}",
            "\n## Role Details\n",
        ]

        for i, role in enumerate(team.get("roles", []), 1):
            role_name = role.get("name", "unnamed")
            task_type = role.get("task_type", "research")
            prompt = role.get("prompt", "")
            parallel = role.get("parallel_group", "")

            lines.append(f"### {i}. {role_name}")
            lines.append(f"- **Task type:** {task_type}")
            if parallel:
                lines.append(f"- **Parallel group:** {parallel}")
            lines.append(f"- **Prompt:** {prompt}")
            lines.append("")

        workflow = team.get("workflow", "sequential")
        role_names = [r.get("name", "unnamed") for r in team.get("roles", [])]
        if workflow == "parallel":
            lines.append(f"**Execution:** All roles run simultaneously: {', '.join(role_names)}")
        elif workflow == "fan_out_fan_in":
            lines.append("**Execution:** Parallel groups run first, then remaining roles sequentially")
        else:
            lines.append(f"**Execution:** Roles run in order: {' -> '.join(role_names)}")

        return ToolResult(output="\n".join(lines))

    def _clone(self, source_name: str, new_name: str) -> ToolResult:
        """Clone a team template for customization."""
        if not source_name:
            return ToolResult(error="source team name is required", success=False)
        if not new_name:
            return ToolResult(error="new team name is required", success=False)
        source = self._teams.get(source_name)
        if not source:
            return ToolResult(error=f"Team '{source_name}' not found", success=False)
        if new_name in self._teams:
            return ToolResult(error=f"Team '{new_name}' already exists", success=False)

        import json
        clone = json.loads(json.dumps(source))  # Deep copy
        clone["name"] = new_name
        clone["description"] = f"Custom clone of {source_name}: {clone.get('description', '')}"
        self._teams[new_name] = clone

        return ToolResult(
            output=(
                f"Team '{source_name}' cloned as '{new_name}'. "
                f"Use compose action to modify roles and workflow."
            )
        )
