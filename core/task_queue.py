"""
Task queue with persistent JSON backing and file-watch hot-reload.

Tasks flow through states:  pending -> running -> review -> done | failed
"""

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Callable, Awaitable

import aiofiles

logger = logging.getLogger("agent42.task_queue")


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    REVIEW = "review"
    DONE = "done"
    FAILED = "failed"


class TaskType(str, Enum):
    CODING = "coding"
    DEBUGGING = "debugging"
    RESEARCH = "research"
    REFACTORING = "refactoring"
    DOCUMENTATION = "documentation"
    MARKETING = "marketing"
    EMAIL = "email"


@dataclass
class Task:
    title: str
    description: str
    task_type: TaskType = TaskType.CODING
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    status: TaskStatus = TaskStatus.PENDING
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    iterations: int = 0
    max_iterations: int = 8
    worktree_path: str = ""
    result: str = ""
    error: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        d["task_type"] = self.task_type.value
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "Task":
        data = data.copy()
        data["status"] = TaskStatus(data.get("status", "pending"))
        data["task_type"] = TaskType(data.get("task_type", "coding"))
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class TaskQueue:
    """Async task queue backed by a JSON file."""

    def __init__(self, tasks_json_path: str = "tasks.json"):
        self._tasks: dict[str, Task] = {}
        self._queue: asyncio.Queue[Task] = asyncio.Queue()
        self._json_path = Path(tasks_json_path)
        self._callbacks: list[Callable[[Task], Awaitable[None]]] = []
        self._last_mtime: float = 0.0

    def on_update(self, callback: Callable[[Task], Awaitable[None]]):
        """Register a callback to fire on every task state change."""
        self._callbacks.append(callback)

    async def _notify(self, task: Task):
        task.updated_at = time.time()
        for cb in self._callbacks:
            try:
                await cb(task)
            except Exception as e:
                logger.error(f"Callback error: {e}", exc_info=True)

    async def add(self, task: Task) -> Task:
        """Add a task to the queue."""
        self._tasks[task.id] = task
        await self._queue.put(task)
        await self._notify(task)
        await self._persist()
        logger.info(f"Task added: {task.id} — {task.title}")
        return task

    async def next(self) -> Task:
        """Wait for and return the next pending task."""
        task = await self._queue.get()
        task.status = TaskStatus.RUNNING
        await self._notify(task)
        await self._persist()
        return task

    async def complete(self, task_id: str, result: str = ""):
        """Mark a task as ready for review."""
        task = self._tasks.get(task_id)
        if not task:
            return
        task.status = TaskStatus.REVIEW
        task.result = result
        await self._notify(task)
        await self._persist()

    async def fail(self, task_id: str, error: str):
        """Mark a task as failed."""
        task = self._tasks.get(task_id)
        if not task:
            return
        task.status = TaskStatus.FAILED
        task.error = error
        await self._notify(task)
        await self._persist()

    async def approve(self, task_id: str):
        """Approve a reviewed task — marks it done."""
        task = self._tasks.get(task_id)
        if not task:
            return
        task.status = TaskStatus.DONE
        await self._notify(task)
        await self._persist()

    def get(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    def all_tasks(self) -> list[Task]:
        return sorted(self._tasks.values(), key=lambda t: t.created_at, reverse=True)

    async def _persist(self):
        """Write current state to JSON file."""
        data = [t.to_dict() for t in self._tasks.values()]
        try:
            async with aiofiles.open(self._json_path, "w") as f:
                await f.write(json.dumps(data, indent=2))
        except OSError as e:
            logger.error(f"Failed to persist tasks: {e}")

    async def load_from_file(self):
        """Load tasks from JSON file if it exists."""
        if not self._json_path.exists():
            return

        try:
            async with aiofiles.open(self._json_path, "r") as f:
                raw = await f.read()

            data = json.loads(raw)
            for item in data:
                task = Task.from_dict(item)
                self._tasks[task.id] = task
                if task.status == TaskStatus.PENDING:
                    await self._queue.put(task)

            logger.info(f"Loaded {len(data)} tasks from {self._json_path}")
            self._last_mtime = self._json_path.stat().st_mtime
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"Failed to load tasks file: {e}")

    async def watch_file(self, interval: float = 30.0):
        """Poll the tasks JSON file for external changes."""
        while True:
            await asyncio.sleep(interval)
            try:
                if not self._json_path.exists():
                    continue

                mtime = self._json_path.stat().st_mtime
                if mtime <= self._last_mtime:
                    continue

                self._last_mtime = mtime
                logger.info("Tasks file changed — reloading")

                async with aiofiles.open(self._json_path, "r") as f:
                    raw = await f.read()

                for item in json.loads(raw):
                    if item.get("id") not in self._tasks:
                        task = Task.from_dict(item)
                        await self.add(task)
            except Exception as e:
                logger.error(f"File watcher error: {e}", exc_info=True)
