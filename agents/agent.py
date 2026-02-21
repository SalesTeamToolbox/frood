"""
Agent — per-task orchestration.

Each agent gets a git worktree, runs the iteration engine, generates
a REVIEW.md, and transitions the task to the review state.

Integrates skills (Phase 3), tools (Phase 4), memory (Phase 6),
and self-learning (post-task reflection + failure analysis).
"""

import logging
import textwrap
from pathlib import Path
from typing import Callable, Awaitable

from agents.model_router import ModelRouter
from agents.iteration_engine import IterationEngine, IterationResult
from agents.learner import Learner
from core.task_queue import Task, TaskQueue, TaskStatus, TaskType
from core.worktree_manager import WorktreeManager
from core.approval_gate import ApprovalGate
from skills.loader import SkillLoader
from memory.store import MemoryStore

logger = logging.getLogger("agent42.agent")

# Default system prompts (used when no skill overrides)
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
    "design": (
        "You are a creative design consultant. Provide detailed design feedback, "
        "suggest improvements for visual hierarchy, accessibility, and brand consistency. "
        "When creating, describe layouts, color choices, and typography with precision."
    ),
    "content": (
        "You are an expert content creator. Write engaging, well-structured content "
        "tailored to the target audience. Focus on clarity, narrative flow, and "
        "a strong call to action."
    ),
    "strategy": (
        "You are a strategic business analyst. Conduct thorough analysis using "
        "frameworks (SWOT, Porter's Five Forces, etc.), provide data-backed insights, "
        "and deliver actionable recommendations."
    ),
    "data_analysis": (
        "You are a data analyst. Process data methodically, create clear visualizations "
        "(described as ASCII/markdown tables when tools unavailable), identify patterns, "
        "and provide actionable insights with statistical backing."
    ),
    "project_management": (
        "You are a project manager. Create clear project plans with milestones, "
        "timelines, resource allocation, risk assessment, and status tracking. "
        "Use structured formats (tables, checklists, Gantt descriptions)."
    ),
}

# Task types that require git worktrees — all others use output directories
_CODE_TASK_TYPES = {TaskType.CODING, TaskType.DEBUGGING, TaskType.REFACTORING}


class Agent:
    """Runs a single task through the full agent pipeline."""

    def __init__(
        self,
        task: Task,
        task_queue: TaskQueue,
        worktree_manager: WorktreeManager,
        approval_gate: ApprovalGate,
        emit: Callable[[str, dict], Awaitable[None]],
        skill_loader: SkillLoader | None = None,
        memory_store: MemoryStore | None = None,
        workspace_skills_dir: Path | None = None,
        tool_registry=None,
    ):
        self.task = task
        self.task_queue = task_queue
        self.worktree_manager = worktree_manager
        self.approval_gate = approval_gate
        self.emit = emit
        self.router = ModelRouter()
        self.tool_registry = tool_registry
        self.engine = IterationEngine(
            self.router,
            tool_registry=tool_registry,
            approval_gate=approval_gate,
            agent_id=task.id,
        )
        self.skill_loader = skill_loader
        self.memory_store = memory_store
        self.learner = (
            Learner(self.router, memory_store, skills_dir=workspace_skills_dir)
            if memory_store
            else None
        )

    async def run(self):
        """Execute the full agent pipeline for this task."""
        task = self.task
        logger.info(f"Agent starting: {task.id} — {task.title}")
        needs_worktree = task.task_type in _CODE_TASK_TYPES

        try:
            # Set up workspace — worktree for code tasks, output dir for others
            if needs_worktree:
                worktree_path = await self.worktree_manager.create(task.id)
            else:
                from core.config import settings
                output_dir = Path(settings.outputs_dir) / task.id
                output_dir.mkdir(parents=True, exist_ok=True)
                worktree_path = output_dir

            task.worktree_path = str(worktree_path)

            await self.emit("agent_start", {
                "task_id": task.id,
                "title": task.title,
                "worktree": str(worktree_path),
            })

            # Get model routing for this task type
            routing = self.router.get_routing(task.task_type)

            # Build system prompt (with skill overrides)
            system_prompt = self._build_system_prompt(task)

            # Build task context with file contents, skills, and memory
            task_context = self._build_context(task, worktree_path)

            # Run iteration engine with task-type-aware critic
            history = await self.engine.run(
                task_description=task_context,
                primary_model=routing["primary"],
                critic_model=routing["critic"],
                max_iterations=routing["max_iterations"],
                system_prompt=system_prompt,
                on_iteration=self._on_iteration,
                task_type=task.task_type.value,
                task_id=task.id,
            )

            if needs_worktree:
                # Generate REVIEW.md and commit for code tasks
                diff = await self.worktree_manager.diff(task.id)
                review_md = self._generate_review(task, history, diff)
                review_path = worktree_path / "REVIEW.md"
                review_path.write_text(review_md)

                await self.worktree_manager.commit(
                    task.id, f"agent42: {task.title} — iteration complete"
                )
            else:
                # Save output as markdown for non-code tasks
                output_path = worktree_path / "output.md"
                review_md = self._generate_review(task, history, "")
                output_path.write_text(review_md)

            # Transition task to review
            await self.task_queue.complete(task.id, result=history.final_output)

            # Post-task learning: reflect on what worked + check for skill creation
            if self.learner:
                # Extract tool call records for tool effectiveness learning
                tool_calls_data = []
                for it_result in history.iterations:
                    for tc in it_result.tool_calls:
                        tool_calls_data.append({
                            "name": tc.tool_name,
                            "success": tc.success,
                        })

                await self.learner.reflect_on_task(
                    title=task.title,
                    task_type=task.task_type.value,
                    iterations=history.total_iterations,
                    max_iterations=routing["max_iterations"],
                    iteration_summary=history.summary(),
                    succeeded=True,
                    tool_calls=tool_calls_data,
                )
                # Check if this task's pattern should be saved as a reusable skill
                existing_names = (
                    [s.name for s in self.skill_loader.all_skills()]
                    if self.skill_loader else []
                )
                await self.learner.check_for_skill_creation(
                    existing_skill_names=existing_names,
                )

            await self.emit("agent_complete", {
                "task_id": task.id,
                "iterations": history.total_iterations,
                "worktree": str(worktree_path),
            })

            # Clean up worktree for code tasks to prevent disk space leaks
            if needs_worktree:
                try:
                    await self.worktree_manager.remove(task.id)
                except Exception as cleanup_err:
                    logger.warning(f"Worktree cleanup failed for {task.id}: {cleanup_err}")

            logger.info(
                f"Agent done: {task.id} — {history.total_iterations} iterations"
            )

        except Exception as e:
            logger.error(f"Agent failed: {task.id} — {e}", exc_info=True)
            await self.task_queue.fail(task.id, str(e))
            await self.emit("agent_error", {"task_id": task.id, "error": str(e)})

            # Clean up orphaned worktree for code tasks to prevent disk bloat
            if needs_worktree:
                try:
                    await self.worktree_manager.remove(task.id)
                except Exception as cleanup_err:
                    logger.warning(f"Worktree cleanup failed for {task.id}: {cleanup_err}")

            # Post-task learning: analyze the failure
            if self.learner:
                await self.learner.reflect_on_task(
                    title=task.title,
                    task_type=task.task_type.value,
                    iterations=0,
                    max_iterations=routing.get("max_iterations", 8),
                    iteration_summary="(task failed before completing iterations)",
                    succeeded=False,
                    error=str(e),
                )

    async def _on_iteration(self, result: IterationResult):
        """Broadcast iteration progress to the dashboard."""
        await self.emit("iteration", {
            "task_id": self.task.id,
            "iteration": result.iteration,
            "approved": result.approved,
            "preview": result.primary_output[:500],
        })

    def _build_system_prompt(self, task: Task) -> str:
        """Build the system prompt, incorporating skill overrides if available."""
        task_type_str = task.task_type.value

        # Check if any skill overrides the system prompt
        if self.skill_loader:
            skills = self.skill_loader.get_for_task_type(task_type_str)
            for skill in skills:
                if skill.system_prompt_override:
                    return skill.system_prompt_override

        return SYSTEM_PROMPTS.get(task_type_str, SYSTEM_PROMPTS["coding"])

    # Max bytes of file content to include in context
    _MAX_FILE_SIZE = 30_000  # ~30KB per file
    _MAX_CONTEXT_FILES = 15  # At most this many files read into context
    _MAX_TOTAL_CONTEXT = 200_000  # Total context budget in characters

    # File extensions for code tasks
    _CODE_EXTENSIONS = (".py", ".js", ".ts", ".jsx", ".tsx", ".json", ".yaml", ".yml", ".md")
    # File extensions for non-code tasks (reference documents)
    _NONCODE_EXTENSIONS = (".md", ".txt", ".json", ".yaml", ".yml", ".csv", ".html", ".xml")

    def _build_context(self, task: Task, worktree_path: Path) -> str:
        """Build the full task context including file contents, skills, and memory.

        For code tasks: reads source files from the worktree.
        For non-code tasks: reads reference documents and prior outputs.
        """
        is_code_task = task.task_type in _CODE_TASK_TYPES
        parts = [
            f"# Task: {task.title}\n",
            task.description,
            f"\nWorking directory: {worktree_path}",
        ]

        extensions = self._CODE_EXTENSIONS if is_code_task else self._NONCODE_EXTENSIONS

        # Include project/reference file structure
        project_files = sorted(worktree_path.rglob("*"))
        relevant = [
            f for f in project_files
            if f.is_file()
            and f.suffix in extensions
            and ".git" not in f.parts
            and "node_modules" not in str(f)
            and "__pycache__" not in str(f)
        ]

        if relevant:
            label = "Project files" if is_code_task else "Reference documents"
            parts.append(f"\n## {label}:")
            for f in relevant[:50]:
                parts.append(f"- {f.relative_to(worktree_path)}")

        # Read file contents
        if relevant:
            label = "File Contents" if is_code_task else "Reference Contents"
            parts.append(f"\n## {label}:\n")
            total_chars = 0
            files_read = 0
            for f in relevant[:self._MAX_CONTEXT_FILES]:
                if total_chars >= self._MAX_TOTAL_CONTEXT:
                    parts.append(f"... ({len(relevant) - files_read} more files not shown)")
                    break
                try:
                    content = f.read_text(encoding="utf-8", errors="replace")
                    if len(content) > self._MAX_FILE_SIZE:
                        content = content[:self._MAX_FILE_SIZE] + "\n... (file truncated)"
                    rel_path = f.relative_to(worktree_path)
                    parts.append(f"### {rel_path}\n```\n{content}\n```\n")
                    total_chars += len(content)
                    files_read += 1
                except Exception:
                    continue

        # Include skill context (Phase 3)
        if self.skill_loader:
            skill_context = self.skill_loader.build_skill_context(task.task_type.value)
            if skill_context:
                parts.append(f"\n{skill_context}")

        # Include memory context (Phase 6)
        if self.memory_store:
            memory_context = self.memory_store.build_context()
            if memory_context.strip():
                parts.append(f"\n{memory_context}")

        # Include tool usage recommendations from prior learning (Phase 9)
        if self.learner:
            tool_recs = self.learner.get_tool_recommendations(task.task_type.value)
            if tool_recs:
                parts.append(f"\n{tool_recs}")

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
