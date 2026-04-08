"""Task lifecycle protocol using contextvars.

Usage:
    ctx = begin_task(TaskType.CODING)
    # ... all memory writes in this async context inherit task_id/task_type
    end_task(ctx)

ContextVar automatically copies to asyncio child tasks.
"""

import contextvars
import json
import os
import uuid
from pathlib import Path

from core.task_types import TaskType

# Cross-process bridge: Stop hooks (separate Python processes) read this file
# to discover the current task_id and task_type.
_TASK_FILE_DIR = os.environ.get("FROOD_DATA_DIR", ".frood")

_task_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("task_id", default=None)
_task_type_var: contextvars.ContextVar[TaskType | None] = contextvars.ContextVar(
    "task_type", default=None
)


class TaskContext:
    """Holds reset tokens for end_task() cleanup."""

    __slots__ = ("_id_token", "_type_token", "task_id", "task_type")

    def __init__(
        self,
        id_token: contextvars.Token,
        type_token: contextvars.Token,
        task_id: str,
        task_type: TaskType,
    ):
        self._id_token = id_token
        self._type_token = type_token
        self.task_id = task_id
        self.task_type = task_type


def _write_task_file(task_id: str, task_type: str) -> None:
    """Write current task info to a file for cross-process access (Stop hooks)."""
    try:
        task_dir = Path(_TASK_FILE_DIR)
        task_dir.mkdir(parents=True, exist_ok=True)
        task_file = task_dir / "current-task.json"
        task_file.write_text(
            json.dumps({"task_id": task_id, "task_type": task_type}),
            encoding="utf-8",
        )
    except Exception:
        pass  # Non-critical — hook will generate its own task_id


def _remove_task_file() -> None:
    """Remove the current task file after task ends."""
    try:
        task_file = Path(_TASK_FILE_DIR) / "current-task.json"
        if task_file.exists():
            task_file.unlink()
    except Exception:
        pass  # Non-critical


def begin_task(task_type: TaskType) -> TaskContext:
    """Start a task context. All memory writes inherit task_id and task_type.

    Args:
        task_type: The type of task being started.

    Returns:
        TaskContext to pass to end_task() when the task completes.
    """
    task_id = str(uuid.uuid4())
    id_token = _task_id_var.set(task_id)
    type_token = _task_type_var.set(task_type)
    # Write cross-process bridge file for Stop hook
    _write_task_file(task_id, task_type.value)
    return TaskContext(id_token, type_token, task_id, task_type)


def end_task(ctx: TaskContext) -> None:
    """End a task context. Clears task_id and task_type from the ContextVar.

    Phase 43: Also flushes accumulated tool names to EffectivenessStore
    for pattern detection via fire-and-forget asyncio.create_task().
    Always pops the accumulator entry to prevent memory leaks.
    """
    # Phase 43: Pop tool accumulator FIRST (always, even if flush fails)
    tool_names = pop_task_tools(ctx.task_id)

    # Phase 43: Fire-and-forget sequence flush
    if tool_names and len(tool_names) >= 2:
        try:
            import asyncio

            from memory.effectiveness import get_shared_store

            store = get_shared_store()
            if store:
                asyncio.create_task(
                    store.record_sequence(
                        agent_id="",
                        task_type=ctx.task_type.value if ctx.task_type else "general",
                        tool_names=tool_names,
                    )
                )
        except Exception:
            pass  # Non-critical — never block task cleanup for pattern tracking

    _task_id_var.reset(ctx._id_token)
    _task_type_var.reset(ctx._type_token)
    _remove_task_file()


def get_task_context() -> tuple[str | None, str | None]:
    """Read current task_id and task_type.

    Returns:
        (task_id, task_type_value) — both None when outside any task.
        task_type is returned as string value (e.g., "coding"), not the enum.
    """
    task_id = _task_id_var.get()
    task_type = _task_type_var.get()
    return task_id, (task_type.value if task_type is not None else None)


# Phase 43: Per-task tool accumulation for pattern detection
_current_task_tools: dict[str, list[str]] = {}


def append_tool_to_task(task_id: str, tool_name: str) -> None:
    """Add a tool name to the accumulator for the given task_id."""
    if task_id:
        if task_id not in _current_task_tools:
            _current_task_tools[task_id] = []
        _current_task_tools[task_id].append(tool_name)


def pop_task_tools(task_id: str) -> list[str]:
    """Remove and return the tool list for the given task_id."""
    return _current_task_tools.pop(task_id, [])
