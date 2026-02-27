"""
Subagent spawning tool — delegates background tasks to isolated agents.

Subagents run with restricted toolsets (no messaging, no spawning) and
report results back to the parent agent.
"""

import asyncio
import logging

from tools.base import Tool, ToolResult

logger = logging.getLogger("agent42.tools.subagent")

MAX_SUBAGENT_ITERATIONS = 15


class SubagentTool(Tool):
    """Spawn a background agent for a subtask."""

    def __init__(self, task_queue):
        self._task_queue = task_queue
        self._results: dict[str, asyncio.Future] = {}

    @property
    def name(self) -> str:
        return "spawn_subagent"

    @property
    def description(self) -> str:
        return (
            "Spawn a background agent to work on a subtask independently. "
            "The subagent has restricted access (no messaging, no spawning). "
            "Returns a task ID to check results later."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short title for the subtask"},
                "description": {
                    "type": "string",
                    "description": "Detailed description of what the subagent should do",
                },
                "task_type": {
                    "type": "string",
                    "description": "Task type (coding, research, etc.)",
                    "default": "coding",
                },
            },
            "required": ["title", "description"],
        }

    async def execute(
        self,
        title: str = "",
        description: str = "",
        task_type: str = "coding",
        project_id: str = "",
        **kwargs,
    ) -> ToolResult:
        if not title or not description:
            return ToolResult(error="title and description are required", success=False)

        # Import here to avoid circular dependency
        from core.task_queue import Task, TaskType

        try:
            task_type_enum = TaskType(task_type)
        except ValueError:
            task_type_enum = TaskType.CODING

        task = Task(
            title=f"[subagent] {title}",
            description=description,
            task_type=task_type_enum,
            max_iterations=MAX_SUBAGENT_ITERATIONS,
            project_id=project_id,
        )

        await self._task_queue.add(task)

        return ToolResult(
            output=f"Subagent spawned: {task.id}\nTitle: {task.title}\nType: {task_type}"
        )
