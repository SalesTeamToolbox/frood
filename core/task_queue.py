"""
Task queue with priority ordering and pluggable persistence.

Tasks flow through states:  pending -> running -> review -> done | failed

Supports optional Redis backend for faster incremental persistence and
pub/sub events.  Falls back to JSON file when Redis is not configured.
"""

import asyncio
import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

import aiofiles

if TYPE_CHECKING:
    from core.queue_backend import QueueBackend

logger = logging.getLogger("agent42.task_queue")


class TaskStatus(str, Enum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    RUNNING = "running"
    REVIEW = "review"
    BLOCKED = "blocked"
    DONE = "done"
    FAILED = "failed"
    ARCHIVED = "archived"


class TaskType(str, Enum):
    CODING = "coding"
    DEBUGGING = "debugging"
    RESEARCH = "research"
    REFACTORING = "refactoring"
    DOCUMENTATION = "documentation"
    MARKETING = "marketing"
    EMAIL = "email"
    DESIGN = "design"
    CONTENT = "content"
    STRATEGY = "strategy"
    DATA_ANALYSIS = "data_analysis"
    PROJECT_MANAGEMENT = "project_management"
    APP_CREATE = "app_create"
    APP_UPDATE = "app_update"
    PROJECT_SETUP = "project_setup"


# Keyword-based task type inference for channel messages
_TASK_TYPE_KEYWORDS: dict[TaskType, list[str]] = {
    TaskType.DEBUGGING: [
        "bug",
        "fix",
        "error",
        "crash",
        "broken",
        "debug",
        "issue",
        "traceback",
        "exception",
    ],
    TaskType.RESEARCH: [
        "research",
        "compare",
        "evaluate",
        "investigate",
        "analyze",
        "find out",
        "look into",
    ],
    TaskType.REFACTORING: [
        "refactor",
        "clean up",
        "reorganize",
        "restructure",
        "simplify",
        "extract",
    ],
    TaskType.DOCUMENTATION: ["document", "readme", "docstring", "wiki", "explain", "write docs"],
    TaskType.MARKETING: [
        "marketing",
        "copy",
        "landing page",
        "social media",
        "campaign",
        "blog post",
        "seo",
    ],
    TaskType.EMAIL: ["email", "draft email", "reply to", "send email", "write email", "compose"],
    TaskType.DESIGN: [
        "design",
        "mockup",
        "wireframe",
        "ui design",
        "ux design",
        "user interface",
        "layout",
        "visual",
        "logo",
        "brand identity",
        "creative brief",
        "graphic",
    ],
    TaskType.CONTENT: [
        "blog",
        "article",
        "write",
        "content",
        "post",
        "copywrite",
        "narrative",
        "story",
        "headline",
    ],
    TaskType.STRATEGY: [
        "strategy",
        "competitive",
        "swot",
        "market analysis",
        "business plan",
        "positioning",
        "go-to-market",
    ],
    TaskType.DATA_ANALYSIS: [
        "data",
        "chart",
        "graph",
        "csv",
        "spreadsheet",
        "analyze data",
        "visualization",
        "metrics",
        "dashboard",
        "statistics",
    ],
    TaskType.PROJECT_MANAGEMENT: [
        "project plan",
        "timeline",
        "milestone",
        "sprint",
        "roadmap",
        "status report",
        "task breakdown",
        "gantt",
    ],
    TaskType.APP_CREATE: [
        "build me an app",
        "build an app",
        "create an app",
        "make me an app",
        "build me a",
        "create a web app",
        "build a website",
        "build a tool",
        "make an application",
        "web application",
        "build a dashboard",
        "create a tracker",
        "build a calculator",
        "build a game",
        "build a chat",
        "build a form",
    ],
    TaskType.APP_UPDATE: [
        "update the app",
        "modify the app",
        "add to the app",
        "change the app",
        "improve the app",
        "add dark mode",
        "add a feature to",
        "fix the app",
        "redesign the app",
    ],
}


def infer_task_type(text: str) -> TaskType:
    """Infer task type from message content using keyword matching."""
    lower = text.lower()
    for task_type, words in _TASK_TYPE_KEYWORDS.items():
        if any(w in lower for w in words):
            return task_type
    return TaskType.CODING


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
    retry_count: int = 0
    max_retries: int = 3
    worktree_path: str = ""
    result: str = ""
    error: str = ""
    # Origin channel info for routing responses back
    origin_channel: str = ""  # "discord", "slack", "telegram", "email", ""
    origin_channel_id: str = ""  # Channel/chat ID to respond to
    origin_metadata: dict = field(default_factory=dict)  # Thread IDs, etc.
    # Device that created this task (empty = dashboard/channel)
    origin_device_id: str = ""

    # Mission Control / Kanban fields (OpenClaw feature)
    assigned_agent: str = ""
    priority: int = 0  # 0=normal, 1=high, 2=urgent
    tags: list = field(default_factory=list)
    comments: list = field(default_factory=list)  # [{author, text, timestamp}]
    pending_messages: list = field(
        default_factory=list
    )  # Buffered user messages before agent starts
    blocked_reason: str = ""
    parent_task_id: str = ""
    project_id: str = (
        ""  # Associated project (empty = standalone task); also links to project interview session
    )
    position: int = 0  # Kanban column ordering
    context_window: str = "default"  # default | large | max
    token_usage: dict = field(default_factory=dict)  # Per-task token tracking by model

    # Project interview fields
    project_spec_path: str = ""  # Path to PROJECT_SPEC.md for subtask context
    # Multi-repository support — which repo and branch the agent should work on
    repo_id: str = ""  # Repository ID from RepoManager (empty = default/legacy)
    branch: str = ""  # Target branch (empty = repo's default_branch)

    # Agent profile (Agent Zero-inspired) — which persona/mode the agent runs as
    profile: str = ""  # Profile name (empty = use AGENT_DEFAULT_PROFILE setting)

    def add_comment(self, author: str, text: str):
        self.comments.append(
            {
                "author": author,
                "text": text,
                "timestamp": time.time(),
            }
        )
        self.updated_at = time.time()

    def add_pending_message(self, content: str, sender: str = "user"):
        """Buffer a user message for delivery when the agent starts."""
        self.pending_messages.append(
            {
                "content": content,
                "sender": sender,
                "timestamp": time.time(),
            }
        )
        self.updated_at = time.time()

    def block(self, reason: str):
        self.status = TaskStatus.BLOCKED
        self.blocked_reason = reason
        self.updated_at = time.time()

    def unblock(self):
        self.status = TaskStatus.PENDING
        self.blocked_reason = ""
        self.updated_at = time.time()

    def archive(self):
        self.status = TaskStatus.ARCHIVED
        self.updated_at = time.time()

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


@dataclass(order=True)
class _PriorityEntry:
    """Wrapper for asyncio.PriorityQueue ordering.

    PriorityQueue pops the *smallest* item first.
    We negate priority so urgent (2) sorts before normal (0).
    Sequence number preserves FIFO order within the same priority level.
    """

    sort_key: tuple = field(compare=True)  # (-priority, sequence)
    task: Task = field(compare=False)


class TaskQueue:
    """Async task queue with priority ordering and pluggable persistence."""

    def __init__(self, tasks_json_path: str = "tasks.json", backend: "QueueBackend | None" = None):
        self._tasks: dict[str, Task] = {}
        self._queue: asyncio.PriorityQueue[_PriorityEntry] = asyncio.PriorityQueue()
        self._seq: int = 0
        self._json_path = Path(tasks_json_path)
        self._callbacks: list[Callable[[Task], Awaitable[None]]] = []
        self._last_mtime: float = 0.0
        self._backend = backend

    def on_update(self, callback: Callable[[Task], Awaitable[None]]):
        """Register a callback to fire on every task state change."""
        self._callbacks.append(callback)

    def _enqueue(self, task: Task):
        """Put a task into the priority queue with correct ordering."""
        self._seq += 1
        entry = _PriorityEntry(sort_key=(-task.priority, self._seq), task=task)
        self._queue.put_nowait(entry)

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
        self._enqueue(task)
        await self._notify(task)
        await self._persist(task)
        logger.info(f"Task added: {task.id} — {task.title}")
        return task

    async def next(self) -> Task:
        """Wait for and return the next pending task (highest priority first)."""
        entry = await self._queue.get()
        task = entry.task
        task.status = TaskStatus.RUNNING
        await self._notify(task)
        await self._persist(task)
        return task

    async def complete(self, task_id: str, result: str = ""):
        """Mark a task as ready for review."""
        task = self._tasks.get(task_id)
        if not task:
            return
        task.status = TaskStatus.REVIEW
        task.result = result
        await self._notify(task)
        await self._persist(task)

    async def fail(self, task_id: str, error: str):
        """Mark a task as failed."""
        task = self._tasks.get(task_id)
        if not task:
            return
        task.status = TaskStatus.FAILED
        task.error = error
        await self._notify(task)
        await self._persist(task)

    async def approve(self, task_id: str):
        """Approve a reviewed task — marks it done."""
        task = self._tasks.get(task_id)
        if not task:
            return
        task.status = TaskStatus.DONE
        await self._notify(task)
        await self._persist(task)

    async def cancel(self, task_id: str):
        """Cancel a pending or running task."""
        task = self._tasks.get(task_id)
        if not task:
            return
        if task.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
            task.status = TaskStatus.FAILED
            task.error = "Cancelled by user"
            await self._notify(task)
            await self._persist(task)
            logger.info(f"Task cancelled: {task_id}")

    async def retry(self, task_id: str):
        """Re-queue a failed task for another attempt."""
        task = self._tasks.get(task_id)
        if not task:
            return
        if task.status == TaskStatus.FAILED:
            if task.retry_count >= task.max_retries:
                logger.warning(f"Task {task_id} exceeded max retries ({task.max_retries})")
                return
            task.retry_count += 1
            task.status = TaskStatus.PENDING
            task.error = ""
            task.result = ""
            task.iterations = 0
            self._enqueue(task)
            await self._notify(task)
            await self._persist(task)
            logger.info(f"Task retried: {task_id} (attempt {task.retry_count}/{task.max_retries})")

    def get(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    def all_tasks(self) -> list[Task]:
        return sorted(self._tasks.values(), key=lambda t: t.created_at, reverse=True)

    def find_active_task(
        self,
        origin_channel: str = "",
        origin_channel_id: str = "",
        session_id: str = "",
    ) -> Task | None:
        """Find the most recent active task for a session or channel.

        Matches on session_id (via origin_metadata["chat_session_id"]) if provided,
        otherwise on origin_channel + origin_channel_id.
        Returns the most recently created active task, or None.
        """
        active_statuses = {TaskStatus.PENDING, TaskStatus.ASSIGNED, TaskStatus.RUNNING}
        candidates = []
        for t in self._tasks.values():
            if t.status not in active_statuses:
                continue
            if session_id:
                if t.origin_metadata.get("chat_session_id") == session_id:
                    candidates.append(t)
            elif t.origin_channel == origin_channel and t.origin_channel_id == origin_channel_id:
                candidates.append(t)
        if not candidates:
            return None
        return max(candidates, key=lambda t: t.created_at)

    async def route_message_to_task(
        self,
        task: Task,
        content: str,
        sender: str,
        intervention_queues: dict,
    ) -> None:
        """Route a follow-up message to an active task.

        If the task is RUNNING and has an intervention queue, inject directly.
        Otherwise (PENDING/ASSIGNED), buffer in pending_messages for delivery
        when the agent starts.
        """
        queue = intervention_queues.get(task.id)
        if queue is not None:
            await queue.put(content)
        else:
            task.add_pending_message(content, sender=sender)
            await self._persist(task)

    def board(self) -> dict[str, list[dict]]:
        """Group tasks by status for Kanban board view."""
        columns = {s.value: [] for s in TaskStatus}
        for task in self._tasks.values():
            columns[task.status.value].append(task.to_dict())
        # Sort each column by position, then priority (urgent first)
        for col in columns.values():
            col.sort(key=lambda t: (t.get("position", 0), -t.get("priority", 0)))
        return columns

    def stats(self) -> dict:
        """Task count statistics."""
        counts = {s.value: 0 for s in TaskStatus}
        for task in self._tasks.values():
            counts[task.status.value] = counts.get(task.status.value, 0) + 1
        return counts

    async def move_task(self, task_id: str, new_status: str, position: int = 0):
        """Move a task to a new status column with position (Kanban drag-and-drop)."""
        task = self._tasks.get(task_id)
        if not task:
            return
        task.status = TaskStatus(new_status)
        task.position = position
        await self._notify(task)
        await self._persist(task)

    async def _persist(self, task: Task | None = None):
        """Persist task state.

        With a backend: incremental save of the specific task.
        Without a backend: full JSON file write (original behavior).
        """
        if self._backend:
            if task:
                await self._backend.save_task(task.to_dict())
            else:
                for t in self._tasks.values():
                    await self._backend.save_task(t.to_dict())
            return

        data = [t.to_dict() for t in self._tasks.values()]
        try:
            async with aiofiles.open(self._json_path, "w") as f:
                await f.write(json.dumps(data, indent=2))
        except OSError as e:
            logger.error(f"Failed to persist tasks: {e}")

    async def load_from_file(self):
        """Load tasks from storage (backend if available, else JSON file).

        Tasks that were RUNNING when persisted are reset to PENDING so they
        get re-dispatched on restart.
        """
        data: list = []

        if self._backend:
            await self._backend.start()
            data = await self._backend.load_all()
            if data:
                logger.info(f"Loaded {len(data)} tasks from backend")

        if not data:
            if not self._json_path.exists():
                return
            try:
                async with aiofiles.open(self._json_path) as f:
                    raw = await f.read()
                data = json.loads(raw)
                logger.info(f"Loaded {len(data)} tasks from {self._json_path}")
            except (json.JSONDecodeError, OSError) as e:
                logger.error(f"Failed to load tasks file: {e}")
                return

        queued_ids: set[str] = set()
        for item in data:
            task = Task.from_dict(item)
            if task.status == TaskStatus.RUNNING:
                task.status = TaskStatus.PENDING
                logger.info(f"Reset interrupted task {task.id} to pending")
            self._tasks[task.id] = task
            if task.status == TaskStatus.PENDING and task.id not in queued_ids:
                self._enqueue(task)
                queued_ids.add(task.id)

        if not self._backend and self._json_path.exists():
            self._last_mtime = self._json_path.stat().st_mtime

    async def watch_file(self, interval: float = 30.0):
        """Poll the tasks JSON file for external changes.

        Skipped when using a Redis backend (Redis uses pub/sub instead).
        """
        if self._backend:
            logger.info("File watcher disabled — using queue backend")
            return
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

                async with aiofiles.open(self._json_path) as f:
                    raw = await f.read()

                try:
                    data = json.loads(raw)
                except json.JSONDecodeError as e:
                    logger.error(f"Invalid JSON in tasks file during reload: {e}")
                    continue

                if not isinstance(data, list):
                    logger.error(f"Tasks file must contain a JSON array, got {type(data).__name__}")
                    continue

                for item in data:
                    if not isinstance(item, dict):
                        logger.warning(f"Skipping non-dict task entry: {type(item).__name__}")
                        continue
                    task_id = item.get("id")
                    if task_id not in self._tasks:
                        try:
                            task = Task.from_dict(item)
                        except (TypeError, ValueError, KeyError) as e:
                            logger.warning(f"Skipping malformed task entry: {e}")
                            continue
                        if task.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
                            task.status = TaskStatus.PENDING
                            await self.add(task)
                        else:
                            # Non-pending tasks just get tracked, not queued
                            self._tasks[task.id] = task
            except Exception as e:
                logger.error(f"File watcher error: {e}", exc_info=True)
