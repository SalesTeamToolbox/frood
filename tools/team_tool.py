"""
Team orchestration tool — compose and run multi-agent teams.

Enables non-coding workflows like marketing campaigns, research projects,
and design reviews by coordinating teams of agents with defined roles.

Workflow types:
  - sequential: roles run in order, each receiving prior output as context
  - parallel: all roles run simultaneously, results aggregated at end
  - fan_out_fan_in: first role produces, middle roles process in parallel, last merges
  - pipeline: sequential but each role iterates with its own critic

Features:
  - Manager/coordinator: every team run is wrapped by a Manager that plans
    before execution and reviews/synthesizes after all roles complete
  - Shared TeamContext: roles see the manager's plan and all prior outputs,
    not just the immediate predecessor
  - Revision handling: if the manager flags a role's output as insufficient,
    that role is re-run once with manager feedback
"""

import asyncio
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from tools.base import Tool, ToolResult

if TYPE_CHECKING:
    from core.plan_spec import PlanSpecification, PlanTask

logger = logging.getLogger("agent42.tools.team")

# Max time to wait for a single role to complete (seconds)
ROLE_TIMEOUT = 600  # 10 minutes
POLL_INTERVAL = 2.0  # seconds between status checks
MAX_REVISIONS_PER_ROLE = 1  # prevent infinite loops


# ---------------------------------------------------------------------------
# Manager prompts
# ---------------------------------------------------------------------------

MANAGER_PLAN_PROMPT = """\
You are the Team Manager / Project Coordinator.

Your job in this PLANNING phase is to produce a STRUCTURED EXECUTION PLAN.
The plan must be detailed enough that any agent could execute it without
asking clarifying questions.

For each task in the plan, specify ALL of the following:
1. **Title and description** — clear, unambiguous instructions
2. **Files to read** — exact file paths the executor needs as input
3. **Files to modify/create** — expected output artifacts
4. **Verification steps** — concrete commands or checks to verify the task succeeded
5. **Acceptance criteria** — observable conditions that prove correctness
6. **Dependencies** — which other tasks must complete first (by task ID)

CONSTRAINTS:
- Maximum 2-3 tasks per role per wave (keep tasks small and focused)
- Each task should target <= {context_budget}% context window utilisation
- Include goal-backward verification: what must be TRUE for the overall goal?

Test your plan: "Could a different agent execute each task without asking questions?"
If not, add more specificity.

Team roles:
{role_descriptions}

Respond with ONLY a JSON object matching this schema:
{{
  "goal": "<what overall success looks like>",
  "observable_truths": ["<testable behaviour that must hold>", ...],
  "required_artifacts": ["<file or object that must exist>", ...],
  "required_wiring": ["<component A connects to component B>", ...],
  "tasks": [
    {{
      "id": "T1",
      "title": "<short title>",
      "description": "<detailed instructions>",
      "role": "<role name>",
      "task_type": "<coding|research|content|etc>",
      "files_to_read": ["path/to/file"],
      "files_to_modify": ["path/to/output"],
      "verification_commands": ["pytest tests/test_x.py -v"],
      "acceptance_criteria": ["File X exists and contains Y"],
      "depends_on": [],
      "estimated_context_pct": 30
    }}
  ]
}}
"""

# Default context budget percentage for structured plans
_DEFAULT_CONTEXT_BUDGET = 50

PLAN_CHECKER_PROMPT = """\
You are a Plan Reviewer. Your job is to peer-review an execution plan
BEFORE agents start working. Catch problems early to avoid wasted effort.

Check for:
1. AMBIGUITY: Could any task be interpreted two different ways?
2. MISSING FILES: Are all input files listed? Do output paths make sense?
3. GAP ANALYSIS: Does the plan actually achieve the stated goal?
4. DEPENDENCY ERRORS: Are dependencies correct? Could more tasks be parallel?
5. CONTEXT BUDGET: Will any task likely exceed 50% context utilisation?
6. VERIFICATION GAPS: Can every acceptance criterion actually be tested?
7. OBSERVABLE TRUTHS: Do the listed truths cover the goal adequately?

Plan to review:
{plan_json}

Original task:
{task_description}

Respond with:
PLAN_STATUS: APPROVED | NEEDS_REVISION
ISSUES: (list each issue on its own line, if any)
SUGGESTIONS: (list improvements, if any)
"""

MANAGER_REVIEW_PROMPT = """\
You are the Team Manager / Project Coordinator.

Your job in this REVIEW phase is to:
1. Review all role outputs against the original task requirements
2. Check for: completeness, consistency between roles, quality, gaps
3. Provide a synthesized final deliverable that integrates all role work
4. If any role's output is significantly lacking, flag it on its own line:
   REVISION_NEEDED: <role_name> — <specific feedback for improvement>
   (only flag roles that truly need revision; most runs should have zero flags)
5. End with:
   QUALITY_SCORE: <1-10>
   SUMMARY: <one paragraph overall assessment>

Original task:
{task_description}

Manager's plan:
{manager_plan}

Role outputs:
{role_outputs}
"""


# ---------------------------------------------------------------------------
# Shared team context
# ---------------------------------------------------------------------------


@dataclass
class TeamContext:
    """Shared context for a team run — enables inter-role communication.

    Instead of passing only the previous role's output as a raw string,
    TeamContext gives every role visibility into:
    - The original task description
    - The manager's execution plan
    - All prior role outputs (for sequential; none for parallel)
    - Manager-directed feedback (for revision runs)
    - Shared team notes
    """

    task_description: str
    manager_plan: str = ""
    role_outputs: dict[str, str] = field(default_factory=dict)
    role_feedback: dict[str, str] = field(default_factory=dict)
    team_notes: list[str] = field(default_factory=list)
    project_id: str = ""
    tier: str = "L1"  # Default tier for team roles — prevents accidental premium spend

    def build_role_context(self, current_role: str) -> str:
        """Build context string for a specific role."""
        parts = [f"## Task\n{self.task_description}"]

        if self.project_id:
            parts.append(f"## Project\nThis task is part of project: {self.project_id}")

        if self.manager_plan:
            parts.append(f"## Manager's Execution Plan\n{self.manager_plan}")

        if self.role_outputs:
            prior_parts = []
            for role_name, output in self.role_outputs.items():
                if role_name != current_role:
                    prior_parts.append(f"### {role_name}\n{output}")
            if prior_parts:
                parts.append("## Prior Team Outputs\n" + "\n\n".join(prior_parts))

        if self.role_feedback.get(current_role):
            parts.append(f"## Manager Feedback for You\n{self.role_feedback[current_role]}")

        if self.team_notes:
            notes = "\n".join(f"- {n}" for n in self.team_notes)
            parts.append(f"## Team Notes\n{notes}")

        return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Built-in team templates
# ---------------------------------------------------------------------------

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
    "code-review-team": {
        "name": "code-review-team",
        "description": "Code review team: developer → reviewer → tester (sequential)",
        "workflow": "sequential",
        "roles": [
            {
                "name": "developer",
                "task_type": "coding",
                "prompt": (
                    "You are the lead developer. Implement the requested changes "
                    "following existing project patterns. Write clean, well-structured "
                    "code with proper error handling and type hints."
                ),
            },
            {
                "name": "reviewer",
                "task_type": "coding",
                "prompt": (
                    "You are the code reviewer. Review the implementation for "
                    "correctness, security vulnerabilities, code smells, and "
                    "adherence to project conventions. Use severity levels: "
                    "critical, major, minor, nit. Provide specific line "
                    "references and fix suggestions."
                ),
            },
            {
                "name": "tester",
                "task_type": "coding",
                "prompt": (
                    "You are the QA engineer. Write comprehensive tests covering "
                    "happy paths, edge cases, and error paths. Run the existing "
                    "test suite to verify no regressions. Report coverage gaps."
                ),
            },
        ],
    },
    "dev-team": {
        "name": "dev-team",
        "description": "Development team: architect → parallel backend + frontend devs → integrator",
        "workflow": "fan_out_fan_in",
        "roles": [
            {
                "name": "architect",
                "task_type": "coding",
                "prompt": (
                    "You are the software architect. Analyze the requirements and "
                    "create a technical design: component breakdown, data flow, "
                    "API contracts, and file structure. Specify what backend-dev "
                    "and frontend-dev should build."
                ),
            },
            {
                "name": "backend-dev",
                "task_type": "coding",
                "prompt": (
                    "You are the backend developer. Implement server-side logic, "
                    "API endpoints, data models, and business rules per the "
                    "architect's design."
                ),
                "parallel_group": "implementation",
            },
            {
                "name": "frontend-dev",
                "task_type": "coding",
                "prompt": (
                    "You are the frontend developer. Implement UI components, "
                    "client-side logic, and API integration per the architect's "
                    "design."
                ),
                "parallel_group": "implementation",
            },
            {
                "name": "integrator",
                "task_type": "coding",
                "prompt": (
                    "You are the integration engineer. Merge backend and frontend "
                    "work, resolve conflicts, write integration tests, and verify "
                    "the full system works end-to-end."
                ),
            },
        ],
    },
    "qa-team": {
        "name": "qa-team",
        "description": "QA team: analyzer → test-writer → security-auditor (sequential)",
        "workflow": "sequential",
        "roles": [
            {
                "name": "analyzer",
                "task_type": "debugging",
                "prompt": (
                    "You are the code analyzer. Examine the codebase for bugs, "
                    "code smells, performance issues, and technical debt. "
                    "Prioritize findings by severity and impact."
                ),
            },
            {
                "name": "test-writer",
                "task_type": "coding",
                "prompt": (
                    "You are the test engineer. Based on the analysis, write "
                    "targeted tests that cover identified issues, edge cases, "
                    "and regression scenarios. Aim for high coverage of critical "
                    "paths."
                ),
            },
            {
                "name": "security-auditor",
                "task_type": "coding",
                "prompt": (
                    "You are the security auditor. Review code for OWASP Top 10 "
                    "vulnerabilities, insecure dependencies, secret exposure, "
                    "and injection risks. Provide remediation steps for each "
                    "finding."
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
            "A Manager agent automatically coordinates each team run — planning "
            "before execution, reviewing after, and requesting revisions if needed. "
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
        project_id: str = "",
        **kwargs,
    ) -> ToolResult:
        if not action:
            return ToolResult(error="action is required", success=False)

        if action == "compose":
            return self._compose(name, description, workflow, roles or [])
        elif action == "run":
            return await self._run(name, task, project_id=project_id)
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

    def _compose(self, name: str, description: str, workflow: str, roles: list) -> ToolResult:
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

    # ------------------------------------------------------------------
    # Team execution — Manager-coordinated
    # ------------------------------------------------------------------

    async def _run(self, name: str, task_description: str, project_id: str = "") -> ToolResult:
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
            "manager_plan": "",
            "manager_review": "",
            "revisions": [],
            "quality_score": 0,
        }
        self._runs[run_id] = run_state

        try:
            # -- Phase 1: Manager plans the execution --
            manager_plan = await self._manager_plan(task_description, roles, project_id)
            run_state["manager_plan"] = manager_plan

            # Build shared team context
            team_ctx = TeamContext(
                task_description=task_description,
                manager_plan=manager_plan,
                project_id=project_id,
            )

            # -- Phase 1.5: Try structured plan path (GSD-inspired) --
            plan_spec = self._parse_plan_json(manager_plan)
            used_structured_path = False

            if plan_spec:
                plan_spec.project_id = project_id

                # Plan checker — skip for small teams (1-2 roles)
                if len(roles) > 2:
                    approved, notes = await self._check_plan(
                        plan_spec, task_description, project_id
                    )
                    plan_spec.reviewed = approved
                    plan_spec.reviewer_notes = notes

                    if not approved:
                        # Re-plan once with checker feedback
                        logger.info("Plan checker requested revision — re-planning")
                        revision_prompt = (
                            f"Your previous plan was reviewed and needs revision.\n\n"
                            f"Reviewer feedback:\n{notes}\n\n"
                            f"Please produce a revised plan addressing the issues above."
                        )
                        team_ctx.shared_notes = revision_prompt
                        manager_plan = await self._manager_plan(
                            f"{task_description}\n\n{revision_prompt}",
                            roles,
                            project_id,
                        )
                        run_state["manager_plan"] = manager_plan
                        team_ctx.manager_plan = manager_plan
                        plan_spec = self._parse_plan_json(manager_plan)
                        if plan_spec:
                            plan_spec.project_id = project_id
                            plan_spec.reviewed = True
                            plan_spec.reviewer_notes = "Re-planned after checker feedback"

                if plan_spec:
                    # -- Phase 2 (structured): Wave-based execution --
                    results = await self._run_waves(plan_spec, team_ctx)
                    used_structured_path = True

                    # Remap results to role-keyed dict for manager review
                    role_results: dict[str, dict] = {}
                    for task_id, result_data in results.items():
                        role = result_data.get("role", task_id)
                        key = f"{role}:{task_id}"
                        role_results[key] = result_data
                    results = role_results

            if not used_structured_path:
                # -- Phase 2 (legacy): Execute team workflow --
                if workflow == "parallel":
                    results = await self._run_parallel(roles, task_description, team_ctx)
                elif workflow == "fan_out_fan_in":
                    results = await self._run_fan_out_fan_in(roles, task_description, team_ctx)
                else:
                    # sequential and pipeline both run in order
                    results = await self._run_sequential(roles, task_description, team_ctx)

            run_state["role_results"] = results

            # -- Phase 3: Manager reviews all outputs --
            manager_review = await self._manager_review(
                task_description, manager_plan, results, project_id
            )
            run_state["manager_review"] = manager_review

            # -- Phase 4: Handle revision requests --
            revision_requests = self._parse_revision_requests(manager_review)
            if revision_requests:
                run_state["revisions"] = [r[0] for r in revision_requests]
                results = await self._handle_revisions(revision_requests, roles, results, team_ctx)
                run_state["role_results"] = results

                # Re-review after revisions
                manager_review = await self._manager_review(
                    task_description, manager_plan, results, project_id
                )
                run_state["manager_review"] = manager_review

            # Extract quality score
            quality_match = re.search(r"QUALITY_SCORE:\s*(\d+)", manager_review)
            if quality_match:
                run_state["quality_score"] = int(quality_match.group(1))

            run_state["status"] = "completed"
            if plan_spec:
                run_state["structured_plan"] = True

            # -- Build final aggregated output --
            output_parts = [f"# Team Run: {name} (run_id: {run_id})\n"]
            output_parts.append(f"**Workflow:** {workflow}\n")
            if used_structured_path:
                output_parts.append("**Execution mode:** Structured (wave-based)\n")
            output_parts.append(f"**Task:** {task_description}\n")
            output_parts.append(f"\n## Manager's Plan\n{manager_plan}\n")

            for role_name, result in results.items():
                output_parts.append(f"\n## {role_name}\n")
                output_parts.append(result.get("output", "(no output)"))

            if run_state["revisions"]:
                output_parts.append(
                    f"\n## Revisions\nRoles revised: {', '.join(run_state['revisions'])}\n"
                )

            output_parts.append(f"\n## Manager's Review\n{manager_review}")

            final = "\n".join(output_parts)
            run_state["final_output"] = final
            return ToolResult(output=final)

        except Exception as e:
            run_state["status"] = "failed"
            run_state["error"] = str(e)
            return ToolResult(error=f"Team run failed: {e}", success=False)

    # ------------------------------------------------------------------
    # Manager phases
    # ------------------------------------------------------------------

    async def _manager_plan(self, task_description: str, roles: list, project_id: str = "") -> str:
        """Manager creates an execution plan before team roles run.

        The prompt asks for structured JSON output.  If the model fails to
        produce valid JSON the raw text is returned and the caller falls
        back to the legacy unstructured path.
        """
        from core.task_queue import Task, TaskType

        role_desc_parts = []
        for i, role in enumerate(roles, 1):
            role_desc_parts.append(
                f"{i}. **{role.get('name', 'unnamed')}** "
                f"(type: {role.get('task_type', 'research')}): "
                f"{role.get('prompt', '')[:200]}"
            )
        role_descriptions = "\n".join(role_desc_parts)

        plan_prompt = MANAGER_PLAN_PROMPT.format(
            role_descriptions=role_descriptions,
            context_budget=_DEFAULT_CONTEXT_BUDGET,
        )

        full_description = f"{plan_prompt}\n\n## Task to Plan\n{task_description}"

        task_obj = Task(
            title=f"[manager:plan] {task_description[:50]}",
            description=full_description,
            task_type=TaskType.PROJECT_MANAGEMENT,
            project_id=project_id,
        )
        await self._task_queue.add(task_obj)
        output = await self._wait_for_task(task_obj.id)
        return output

    async def _manager_review(
        self, task_description: str, manager_plan: str, results: dict, project_id: str = ""
    ) -> str:
        """Manager reviews all role outputs and synthesizes a final deliverable."""
        from core.task_queue import Task, TaskType

        role_output_parts = []
        for role_name, result in results.items():
            output = result.get("output", "(no output)")
            role_output_parts.append(f"### {role_name}\n{output}")
        role_outputs_text = "\n\n".join(role_output_parts)

        review_prompt = MANAGER_REVIEW_PROMPT.format(
            task_description=task_description,
            manager_plan=manager_plan,
            role_outputs=role_outputs_text,
        )

        task_obj = Task(
            title=f"[manager:review] {task_description[:50]}",
            description=review_prompt,
            task_type=TaskType.PROJECT_MANAGEMENT,
            project_id=project_id,
        )
        await self._task_queue.add(task_obj)
        output = await self._wait_for_task(task_obj.id)
        return output

    @staticmethod
    def _parse_revision_requests(manager_review: str) -> list[tuple[str, str]]:
        """Extract REVISION_NEEDED lines from manager review.

        Returns list of (role_name, feedback) tuples.
        """
        pattern = r"REVISION_NEEDED:\s*(\S+)\s*[—\-–]\s*(.+)"
        matches = re.findall(pattern, manager_review)
        return [(name.strip(), feedback.strip()) for name, feedback in matches]

    async def _handle_revisions(
        self,
        revision_requests: list[tuple[str, str]],
        roles: list,
        results: dict,
        team_ctx: TeamContext,
    ) -> dict:
        """Re-run flagged roles with manager feedback, max 1 re-run per role."""
        from core.task_queue import Task, TaskType

        role_lookup = {r.get("name", ""): r for r in roles}

        for role_name, feedback in revision_requests:
            if role_name not in role_lookup:
                logger.warning(f"Manager requested revision for unknown role: {role_name}")
                continue

            role = role_lookup[role_name]
            role_prompt = role.get("prompt", "")
            task_type_str = role.get("task_type", "research")

            # Add feedback to team context
            team_ctx.role_feedback[role_name] = feedback

            context = team_ctx.build_role_context(role_name)
            full_description = (
                f"{role_prompt}\n\n"
                f"## REVISION REQUESTED\n"
                f"The Manager has reviewed your previous output and requests improvements:\n"
                f"{feedback}\n\n"
                f"Please revise your output addressing this feedback.\n\n"
                f"{context}"
            )

            try:
                task_type_enum = TaskType(task_type_str)
            except ValueError:
                task_type_enum = TaskType.RESEARCH

            task_obj = Task(
                title=f"[team:{role_name}:revision] {team_ctx.task_description[:40]}",
                description=full_description,
                task_type=task_type_enum,
                project_id=team_ctx.project_id,
                tier=role.get("tier", team_ctx.tier),
            )
            await self._task_queue.add(task_obj)
            output = await self._wait_for_task(task_obj.id)
            results[role_name] = {
                "output": output,
                "task_id": task_obj.id,
                "revised": True,
            }
            team_ctx.role_outputs[role_name] = output

            logger.info(f"Revised role '{role_name}' for team run")

        return results

    # ------------------------------------------------------------------
    # Workflow execution methods (now using TeamContext)
    # ------------------------------------------------------------------

    async def _run_sequential(
        self, roles: list, task_description: str, team_ctx: TeamContext
    ) -> dict[str, dict]:
        """Run roles sequentially, each receiving full team context."""
        from core.task_queue import Task, TaskType

        results = {}

        for role in roles:
            role_name = role.get("name", "unnamed")
            task_type_str = role.get("task_type", "research")
            role_prompt = role.get("prompt", "")

            context = team_ctx.build_role_context(role_name)
            full_description = f"{role_prompt}\n\n{context}"

            try:
                task_type_enum = TaskType(task_type_str)
            except ValueError:
                task_type_enum = TaskType.RESEARCH

            task_obj = Task(
                title=f"[team:{role_name}] {task_description[:50]}",
                description=full_description,
                task_type=task_type_enum,
                project_id=team_ctx.project_id,
                tier=role.get("tier", team_ctx.tier),
            )
            await self._task_queue.add(task_obj)

            # Wait for completion
            output = await self._wait_for_task(task_obj.id)
            results[role_name] = {"output": output, "task_id": task_obj.id}

            # Update team context so next role sees this output
            team_ctx.role_outputs[role_name] = output

        return results

    async def _run_parallel(
        self, roles: list, task_description: str, team_ctx: TeamContext
    ) -> dict[str, dict]:
        """Run all roles in parallel, aggregate results."""
        from core.task_queue import Task, TaskType

        task_ids = {}

        # Spawn all roles — each gets manager plan but no peer outputs
        for role in roles:
            role_name = role.get("name", "unnamed")
            task_type_str = role.get("task_type", "research")
            role_prompt = role.get("prompt", "")

            context = team_ctx.build_role_context(role_name)
            full_description = f"{role_prompt}\n\n{context}"

            try:
                task_type_enum = TaskType(task_type_str)
            except ValueError:
                task_type_enum = TaskType.RESEARCH

            task_obj = Task(
                title=f"[team:{role_name}] {task_description[:50]}",
                description=full_description,
                task_type=task_type_enum,
                project_id=team_ctx.project_id,
                tier=role.get("tier", team_ctx.tier),
            )
            await self._task_queue.add(task_obj)
            task_ids[role_name] = task_obj.id

        # Wait for all
        results = {}
        for role_name, task_id in task_ids.items():
            output = await self._wait_for_task(task_id)
            results[role_name] = {"output": output, "task_id": task_id}
            team_ctx.role_outputs[role_name] = output

        return results

    async def _run_fan_out_fan_in(
        self, roles: list, task_description: str, team_ctx: TeamContext
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

        # Run parallel groups first
        for group_name, group_roles in parallel_groups.items():
            group_results = await self._run_parallel(group_roles, task_description, team_ctx)
            results.update(group_results)

        # Run remaining roles sequentially with accumulated context
        for role in sequential_roles:
            role_name = role.get("name", "unnamed")
            task_type_str = role.get("task_type", "research")
            role_prompt = role.get("prompt", "")

            context = team_ctx.build_role_context(role_name)
            full_description = f"{role_prompt}\n\n{context}"

            try:
                task_type_enum = TaskType(task_type_str)
            except ValueError:
                task_type_enum = TaskType.RESEARCH

            task_obj = Task(
                title=f"[team:{role_name}] {task_description[:50]}",
                description=full_description,
                task_type=task_type_enum,
                project_id=team_ctx.project_id,
                tier=role.get("tier", team_ctx.tier),
            )
            await self._task_queue.add(task_obj)
            output = await self._wait_for_task(task_obj.id)
            results[role_name] = {"output": output, "task_id": task_obj.id}
            team_ctx.role_outputs[role_name] = output

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

    # ------------------------------------------------------------------
    # Structured plan parsing and checking
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_plan_json(manager_output: str) -> "PlanSpecification | None":
        """Try to parse the manager's output as a structured PlanSpecification.

        Returns None if parsing fails (caller should fall back to legacy path).
        """
        from core.plan_spec import PlanSpecification

        # Strip markdown code fences if present
        text = manager_output.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            # Remove first and last fence lines
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # Try to extract JSON from mixed text
            start = text.find("{")
            end = text.rfind("}")
            if start == -1 or end == -1:
                return None
            try:
                data = json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return None

        if not isinstance(data, dict) or "tasks" not in data:
            return None

        try:
            data["plan_id"] = data.get("plan_id", uuid.uuid4().hex[:10])
            return PlanSpecification.from_dict(data)
        except Exception as e:
            logger.warning("Failed to parse structured plan: %s", e)
            return None

    async def _check_plan(
        self,
        plan_spec: "PlanSpecification",
        task_description: str,
        project_id: str = "",
    ) -> tuple[bool, str]:
        """Have a plan checker review the plan before execution.

        Returns (approved, reviewer_notes).
        """
        from core.task_queue import Task, TaskType

        prompt = PLAN_CHECKER_PROMPT.format(
            plan_json=json.dumps(plan_spec.to_dict(), indent=2),
            task_description=task_description,
        )
        task_obj = Task(
            title=f"[plan-checker] {task_description[:50]}",
            description=prompt,
            task_type=TaskType.PROJECT_MANAGEMENT,
            project_id=project_id,
        )
        await self._task_queue.add(task_obj)
        output = await self._wait_for_task(task_obj.id)

        approved = "PLAN_STATUS: APPROVED" in output
        return approved, output

    # ------------------------------------------------------------------
    # Wave-based execution
    # ------------------------------------------------------------------

    async def _run_waves(
        self,
        plan: "PlanSpecification",
        team_ctx: "TeamContext",
    ) -> dict[str, dict]:
        """Execute plan tasks in dependency-ordered waves.

        Within each wave: tasks run in parallel.
        Between waves: sequential (each wave waits for the previous).
        """
        from core.task_queue import Task, TaskType

        waves = plan.compute_waves()
        results: dict[str, dict] = {}

        for wave_num in sorted(waves.keys()):
            wave_tasks = waves[wave_num]
            logger.info("Starting wave %d with %d tasks", wave_num, len(wave_tasks))

            # Submit all tasks in this wave in parallel
            task_ids: dict[str, tuple[str, PlanTask]] = {}
            for plan_task in wave_tasks:
                executor_prompt = self._build_executor_prompt(plan_task, team_ctx, results)

                try:
                    task_type_enum = TaskType(plan_task.task_type)
                except ValueError:
                    task_type_enum = TaskType.RESEARCH

                task_obj = Task(
                    title=f"[wave:{wave_num}:{plan_task.role}] {plan_task.title}",
                    description=executor_prompt,
                    task_type=task_type_enum,
                    project_id=team_ctx.project_id,
                )
                await self._task_queue.add(task_obj)
                task_ids[plan_task.id] = (task_obj.id, plan_task)

            # Wait for all tasks in this wave
            for plan_task_id, (queue_task_id, plan_task) in task_ids.items():
                output = await self._wait_for_task(queue_task_id)
                results[plan_task_id] = {
                    "output": output,
                    "task_id": queue_task_id,
                    "role": plan_task.role,
                    "title": plan_task.title,
                }
                team_ctx.role_outputs[plan_task.role] = output

        return results

    @staticmethod
    def _build_executor_prompt(
        plan_task: "PlanTask",
        team_ctx: "TeamContext",
        prior_results: dict,
    ) -> str:
        """Build an executor prompt from a plan task.

        The plan IS the prompt — structured enough that the executor
        doesn't need to ask clarifying questions.
        """
        parts = [
            f"# Task: {plan_task.title}\n",
            plan_task.description,
        ]

        if plan_task.files_to_read:
            parts.append(
                "\n## Files to Read\n" + "\n".join(f"- `{f}`" for f in plan_task.files_to_read)
            )

        if plan_task.files_to_modify:
            parts.append(
                "\n## Files to Create/Modify\n"
                + "\n".join(f"- `{f}`" for f in plan_task.files_to_modify)
            )

        if plan_task.verification_commands:
            parts.append(
                "\n## Verification Commands\nRun these to verify your work:\n"
                + "\n".join(f"```\n{cmd}\n```" for cmd in plan_task.verification_commands)
            )

        if plan_task.acceptance_criteria:
            parts.append(
                "\n## Acceptance Criteria\n"
                + "\n".join(f"- [ ] {c}" for c in plan_task.acceptance_criteria)
            )

        # Include outputs from dependency tasks
        if plan_task.depends_on and prior_results:
            dep_parts = []
            for dep_id in plan_task.depends_on:
                if dep_id in prior_results:
                    dep = prior_results[dep_id]
                    dep_parts.append(f"### {dep['title']} (completed)\n{dep['output'][:2000]}")
            if dep_parts:
                parts.append("\n## Prior Task Outputs (dependencies)\n" + "\n\n".join(dep_parts))

        # Include team context
        if plan_task.role:
            ctx = team_ctx.build_role_context(plan_task.role)
            if ctx:
                parts.append(f"\n## Team Context\n{ctx}")

        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # Utility actions (unchanged from original)
    # ------------------------------------------------------------------

    def _status(self, run_id: str) -> ToolResult:
        if not run_id:
            # List all runs
            if not self._runs:
                return ToolResult(output="No team runs yet.")
            lines = ["# Team Runs\n"]
            for rid, state in self._runs.items():
                quality = state.get("quality_score", 0)
                quality_str = f", quality: {quality}/10" if quality else ""
                lines.append(
                    f"- **{rid}** — team: {state['team']}, status: {state['status']}{quality_str}"
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

        if state.get("manager_plan"):
            lines.append(f"\n## Manager's Plan\n{state['manager_plan'][:500]}...")

        if state.get("role_results"):
            lines.append("\n## Role Results:")
            for role_name, result in state["role_results"].items():
                preview = result.get("output", "")[:200]
                revised = " (revised)" if result.get("revised") else ""
                lines.append(f"\n### {role_name}{revised}\n{preview}...")

        if state.get("revisions"):
            lines.append(f"\n**Revisions:** {', '.join(state['revisions'])}")

        if state.get("quality_score"):
            lines.append(f"\n**Quality Score:** {state['quality_score']}/10")

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
            return ToolResult(error=f"Cannot delete built-in team '{name}'", success=False)
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
            "**Manager:** Automatic (plans before, reviews after, can request revisions)",
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
            lines.append(
                "**Execution:** Parallel groups run first, then remaining roles sequentially"
            )
        else:
            lines.append(f"**Execution:** Roles run in order: {' -> '.join(role_names)}")

        lines.append(
            "\n**Manager Flow:** Plan → Team Execution → Review → "
            "Revisions (if needed) → Final Synthesis"
        )

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
