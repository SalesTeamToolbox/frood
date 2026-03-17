"""Task lifecycle protocol using contextvars.

Usage:
    ctx = begin_task(TaskType.CODING)
    # ... all memory writes in this async context inherit task_id/task_type
    end_task(ctx)

ContextVar automatically copies to asyncio child tasks.
"""

import contextvars
import uuid

from core.task_types import TaskType

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
    return TaskContext(id_token, type_token, task_id, task_type)


def end_task(ctx: TaskContext) -> None:
    """End a task context. Clears task_id and task_type from the ContextVar."""
    _task_id_var.reset(ctx._id_token)
    _task_type_var.reset(ctx._type_token)


def get_task_context() -> tuple[str | None, str | None]:
    """Read current task_id and task_type.

    Returns:
        (task_id, task_type_value) — both None when outside any task.
        task_type is returned as string value (e.g., "coding"), not the enum.
    """
    task_id = _task_id_var.get()
    task_type = _task_type_var.get()
    return task_id, (task_type.value if task_type is not None else None)
