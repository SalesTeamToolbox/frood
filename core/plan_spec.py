"""
Structured plan specifications for team/project execution.

Inspired by the GSD framework's "PLAN.md as prompt" concept: plans are
structured enough that any executor agent can work without asking questions.

Each PlanTask specifies: what to do, which files to touch, how to verify
success, and what must be true when done.  PlanSpecification groups tasks
with dependency tracking, wave computation, and goal-backward verification
fields (observable truths, required artifacts, required wiring).

Usage:
    spec = PlanSpecification(
        plan_id="p1",
        goal="Build auth module",
        tasks=[
            PlanTask(id="T1", title="Create models", ...),
            PlanTask(id="T2", title="Create API routes", depends_on=["T1"], ...),
        ],
        observable_truths=["User can register and log in"],
    )
    waves = spec.compute_waves()  # {0: [T1], 1: [T2]}
    md = spec.to_markdown()       # Structured markdown (the executor prompt)
    await spec.save(directory)    # Persist PLAN.md + plan.json
"""

import json
import logging
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path

import aiofiles

logger = logging.getLogger("agent42.plan_spec")


@dataclass
class PlanTask:
    """A single task within a structured plan.

    The description should be detailed enough that an executor agent can
    work without asking clarifying questions.  Files, verification commands,
    and acceptance criteria make expectations explicit.
    """

    id: str  # e.g. "T1", "T2"
    title: str
    description: str = ""
    role: str = ""  # Which team role executes this
    task_type: str = "research"  # TaskType value
    files_to_read: list[str] = field(default_factory=list)
    files_to_modify: list[str] = field(default_factory=list)
    verification_commands: list[str] = field(default_factory=list)
    acceptance_criteria: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)  # Prerequisite task IDs
    wave: int = 0  # Execution wave (computed from dependencies)
    estimated_context_pct: int = 30  # Expected context window utilisation

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "PlanTask":
        known = {k for k in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class PlanSpecification:
    """Complete execution plan — structured enough to BE the prompt.

    The plan includes goal-backward verification fields:
    - observable_truths: testable behaviours that must hold when the goal is met
    - required_artifacts: files / objects that must exist
    - required_wiring: connections between components that must be in place
    """

    plan_id: str
    project_id: str = ""
    goal: str = ""
    tasks: list[PlanTask] = field(default_factory=list)
    observable_truths: list[str] = field(default_factory=list)
    required_artifacts: list[str] = field(default_factory=list)
    required_wiring: list[str] = field(default_factory=list)
    context_budget_pct: int = 50  # Target max context utilisation per executor
    created_at: float = field(default_factory=time.time)
    reviewed: bool = False  # Has plan checker approved?
    reviewer_notes: str = ""

    # ------------------------------------------------------------------
    # Wave computation
    # ------------------------------------------------------------------

    def compute_waves(self) -> dict[int, list[PlanTask]]:
        """Compute execution waves from the dependency graph.

        Uses Kahn's algorithm (topological sort).  Tasks with no
        dependencies land in wave 0 and run first.  Each subsequent
        wave contains tasks whose dependencies are all in earlier waves.

        Raises ``ValueError`` if a dependency cycle is detected.
        Returns a dict mapping wave number → list of tasks in that wave.
        """
        task_map: dict[str, PlanTask] = {t.id: t for t in self.tasks}
        in_degree: dict[str, int] = {t.id: 0 for t in self.tasks}
        dependents: dict[str, list[str]] = {t.id: [] for t in self.tasks}

        for t in self.tasks:
            for dep_id in t.depends_on:
                if dep_id not in task_map:
                    logger.warning(
                        "Task %s depends on unknown task %s — ignoring dependency",
                        t.id,
                        dep_id,
                    )
                    continue
                in_degree[t.id] += 1
                dependents[dep_id].append(t.id)

        # Kahn's algorithm
        queue: deque[str] = deque()
        wave_of: dict[str, int] = {}

        for tid, deg in in_degree.items():
            if deg == 0:
                queue.append(tid)
                wave_of[tid] = 0

        processed = 0
        while queue:
            tid = queue.popleft()
            processed += 1
            for dep_tid in dependents[tid]:
                in_degree[dep_tid] -= 1
                candidate_wave = wave_of[tid] + 1
                wave_of[dep_tid] = max(wave_of.get(dep_tid, 0), candidate_wave)
                if in_degree[dep_tid] == 0:
                    queue.append(dep_tid)

        if processed != len(self.tasks):
            raise ValueError(
                "Circular dependency detected in plan tasks — "
                f"processed {processed}/{len(self.tasks)} tasks"
            )

        # Assign wave numbers back onto tasks and group
        waves: dict[int, list[PlanTask]] = {}
        for t in self.tasks:
            w = wave_of[t.id]
            t.wave = w
            waves.setdefault(w, []).append(t)

        return waves

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "plan_id": self.plan_id,
            "project_id": self.project_id,
            "goal": self.goal,
            "tasks": [t.to_dict() for t in self.tasks],
            "observable_truths": self.observable_truths,
            "required_artifacts": self.required_artifacts,
            "required_wiring": self.required_wiring,
            "context_budget_pct": self.context_budget_pct,
            "created_at": self.created_at,
            "reviewed": self.reviewed,
            "reviewer_notes": self.reviewer_notes,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PlanSpecification":
        tasks_raw = data.pop("tasks", [])
        known = {k for k in cls.__dataclass_fields__}
        filtered = {k: v for k, v in data.items() if k in known and k != "tasks"}
        spec = cls(tasks=[PlanTask.from_dict(t) for t in tasks_raw], **filtered)
        return spec

    # ------------------------------------------------------------------
    # Markdown rendering — the plan IS the prompt
    # ------------------------------------------------------------------

    def to_markdown(self) -> str:
        """Render the plan as structured markdown.

        The rendered markdown is designed to be fed directly to an executor
        agent as its prompt — no transformation needed.
        """
        lines = [f"# Execution Plan: {self.plan_id}\n"]

        if self.goal:
            lines.append(f"## Goal\n{self.goal}\n")

        if self.observable_truths:
            lines.append("## Observable Truths (must be TRUE when done)")
            for i, truth in enumerate(self.observable_truths, 1):
                lines.append(f"{i}. {truth}")
            lines.append("")

        if self.required_artifacts:
            lines.append("## Required Artifacts (must EXIST)")
            for artifact in self.required_artifacts:
                lines.append(f"- {artifact}")
            lines.append("")

        if self.required_wiring:
            lines.append("## Required Wiring (must be CONNECTED)")
            for wiring in self.required_wiring:
                lines.append(f"- {wiring}")
            lines.append("")

        lines.append(f"## Tasks ({len(self.tasks)} total)\n")

        for task in self.tasks:
            lines.append(f"### {task.id}: {task.title}")
            if task.role:
                lines.append(f"**Role:** {task.role}")
            if task.task_type:
                lines.append(f"**Type:** {task.task_type}")
            if task.depends_on:
                lines.append(f"**Depends on:** {', '.join(task.depends_on)}")
            lines.append(f"**Wave:** {task.wave}")
            lines.append("")

            if task.description:
                lines.append(task.description)
                lines.append("")

            if task.files_to_read:
                lines.append("**Files to read:**")
                for f in task.files_to_read:
                    lines.append(f"- `{f}`")
                lines.append("")

            if task.files_to_modify:
                lines.append("**Files to create/modify:**")
                for f in task.files_to_modify:
                    lines.append(f"- `{f}`")
                lines.append("")

            if task.verification_commands:
                lines.append("**Verification commands:**")
                for cmd in task.verification_commands:
                    lines.append(f"```\n{cmd}\n```")
                lines.append("")

            if task.acceptance_criteria:
                lines.append("**Acceptance criteria:**")
                for criterion in task.acceptance_criteria:
                    lines.append(f"- [ ] {criterion}")
                lines.append("")

            lines.append("---\n")

        if self.reviewer_notes:
            lines.append(f"## Reviewer Notes\n{self.reviewer_notes}\n")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def save(self, directory: Path):
        """Persist plan as PLAN.md + plan.json in the given directory."""
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)

        async with aiofiles.open(directory / "PLAN.md", "w") as f:
            await f.write(self.to_markdown())
        async with aiofiles.open(directory / "plan.json", "w") as f:
            await f.write(json.dumps(self.to_dict(), indent=2))

        logger.info("Saved plan %s to %s", self.plan_id, directory)

    @classmethod
    async def load(cls, directory: Path) -> "PlanSpecification":
        """Load plan from plan.json in the given directory."""
        json_path = Path(directory) / "plan.json"
        async with aiofiles.open(json_path) as f:
            data = json.loads(await f.read())
        return cls.from_dict(data)
