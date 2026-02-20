"""
Agent — per-task orchestration.

Each agent gets a git worktree, runs the iteration engine, generates
a REVIEW.md, and transitions the task to the review state.
"""

import logging
import textwrap
from pathlib import Path
from typing import Callable, Awaitable

from agents.model_router import ModelRouter
from agents.iteration_engine import IterationEngine, IterationResult
from core.task_queue import Task, TaskQueue, TaskStatus
from core.worktree_manager import WorktreeManager
from core.approval_gate import ApprovalGate

logger = logging.getLogger("agent42.agent")

SYSTEM_PROMPTS = {
    "coding": (
        "You are an expert software engineer. Write clean, well-tested, production-ready "
        "code. Follow the existing project conventions. Include error handling and type hints."
    ),
    "debugging": (
        "You are an expert debugger. Analyze the issue systematically: reproduce, isolate, "
        "identify root cause, and provide a minimal fix. Explain your reasoning."
    ),
    "research": (
        "You are a thorough technical researcher. Gather information, compare options, "
        "and provide a clear recommendation with pros/cons."
    ),
    "refactoring": (
        "You are a refactoring specialist. Improve code structure without changing behavior. "
        "Preserve all existing tests. Explain each change."
    ),
    "documentation": (
        "You are a technical writer. Write clear, concise documentation that helps developers "
        "understand and use the code effectively."
    ),
    "marketing": (
        "You are a marketing strategist. Create compelling copy that resonates with the target "
        "audience. Be specific, avoid buzzwords, focus on value."
    ),
    "email": (
        "You are a professional communicator. Draft clear, concise emails that achieve their "
        "purpose. Match the tone to the context."
    ),
}


class Agent:
    """Runs a single task through the full agent pipeline."""

    def __init__(
        self,
        task: Task,
        task_queue: TaskQueue,
        worktree_manager: WorktreeManager,
        approval_gate: ApprovalGate,
        emit: Callable[[str, dict], Awaitable[None]],
    ):
        self.task = task
        self.task_queue = task_queue
        self.worktree_manager = worktree_manager
        self.approval_gate = approval_gate
        self.emit = emit
        self.router = ModelRouter()
        self.engine = IterationEngine(self.router)

    async def run(self):
        """Execute the full agent pipeline for this task."""
        task = self.task
        logger.info(f"Agent starting: {task.id} — {task.title}")

        try:
            # Set up worktree
            worktree_path = await self.worktree_manager.create(task.id)
            task.worktree_path = str(worktree_path)

            await self.emit("agent_start", {
                "task_id": task.id,
                "title": task.title,
                "worktree": str(worktree_path),
            })

            # Get model routing for this task type
            routing = self.router.get_routing(task.task_type)
            system_prompt = SYSTEM_PROMPTS.get(task.task_type.value, SYSTEM_PROMPTS["coding"])

            # Build task context with file contents if in a worktree
            task_context = self._build_context(task, worktree_path)

            # Run iteration engine
            history = await self.engine.run(
                task_description=task_context,
                primary_model=routing["primary"],
                critic_model=routing["critic"],
                max_iterations=routing["max_iterations"],
                system_prompt=system_prompt,
                on_iteration=self._on_iteration,
            )

            # Generate REVIEW.md
            diff = await self.worktree_manager.diff(task.id)
            review_md = self._generate_review(task, history, diff)
            review_path = worktree_path / "REVIEW.md"
            review_path.write_text(review_md)

            # Commit the review
            await self.worktree_manager.commit(
                task.id, f"agent42: {task.title} — iteration complete"
            )

            # Transition task to review
            await self.task_queue.complete(task.id, result=history.final_output)

            await self.emit("agent_complete", {
                "task_id": task.id,
                "iterations": history.total_iterations,
                "worktree": str(worktree_path),
            })

            logger.info(
                f"Agent done: {task.id} — {history.total_iterations} iterations"
            )

        except Exception as e:
            logger.error(f"Agent failed: {task.id} — {e}", exc_info=True)
            await self.task_queue.fail(task.id, str(e))
            await self.emit("agent_error", {"task_id": task.id, "error": str(e)})

    async def _on_iteration(self, result: IterationResult):
        """Broadcast iteration progress to the dashboard."""
        await self.emit("iteration", {
            "task_id": self.task.id,
            "iteration": result.iteration,
            "approved": result.approved,
            "preview": result.primary_output[:500],
        })

    def _build_context(self, task: Task, worktree_path: Path) -> str:
        """Build the full task context including relevant file contents."""
        parts = [
            f"# Task: {task.title}\n",
            task.description,
            f"\nWorking directory: {worktree_path}",
        ]

        # Include project structure for context
        project_files = sorted(worktree_path.rglob("*"))
        relevant = [
            f for f in project_files
            if f.is_file()
            and f.suffix in (".py", ".js", ".ts", ".jsx", ".tsx", ".json", ".yaml", ".yml", ".md")
            and ".git" not in f.parts
            and "node_modules" not in str(f)
            and "__pycache__" not in str(f)
        ]

        if relevant:
            parts.append("\n## Project files:")
            for f in relevant[:20]:
                parts.append(f"- {f.relative_to(worktree_path)}")

        return "\n".join(parts)

    @staticmethod
    def _generate_review(task: Task, history, diff: str) -> str:
        """Generate REVIEW.md for human + Claude Code review."""
        return textwrap.dedent(f"""\
            # Review: {task.title}

            **Task ID:** {task.id}
            **Type:** {task.task_type.value}
            **Iterations:** {history.total_iterations}

            ## Task Description

            {task.description}

            ## Iteration History

            {history.summary()}

            ## Final Output

            {history.final_output}

            ## Git Diff

            ```diff
            {diff}
            ```

            ## Claude Code Review Prompt

            Review the changes in this worktree. Check for:
            1. Correctness — does it do what the task asked?
            2. Security — any injection, XSS, or data exposure risks?
            3. Tests — are edge cases covered?
            4. Style — does it match the existing codebase?

            If approved, merge to dev. If not, explain what needs to change.
        """)
