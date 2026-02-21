"""
Cron scheduling tool — persistent task scheduling for Agent42.

Supports cron expressions, intervals, and one-shot schedules.
Schedules persist to a JSON file and survive restarts.
"""

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Callable, Awaitable

from tools.base import Tool, ToolResult

logger = logging.getLogger("agent42.tools.cron")


@dataclass
class CronJob:
    """A scheduled task."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    name: str = ""
    description: str = ""
    schedule: str = ""        # Cron expression or interval (e.g., "every 1h", "0 9 * * *")
    task_title: str = ""      # Task title to create when triggered
    task_description: str = ""
    task_type: str = "coding"
    enabled: bool = True
    last_run: float = 0.0
    next_run: float = 0.0
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "CronJob":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class CronScheduler:
    """Persistent cron scheduler with heartbeat loop."""

    def __init__(self, data_path: str = "cron_jobs.json"):
        self._jobs: dict[str, CronJob] = {}
        self._data_path = Path(data_path)
        self._task_callback: Callable[[str, str, str], Awaitable[None]] | None = None
        self._running = False

    def on_trigger(self, callback: Callable[[str, str, str], Awaitable[None]]):
        """Set callback(title, description, task_type) for when a job triggers."""
        self._task_callback = callback

    def add_job(self, job: CronJob) -> CronJob:
        """Add a scheduled job."""
        if not job.next_run:
            job.next_run = self._compute_next_run(job.schedule)
        self._jobs[job.id] = job
        self._persist()
        logger.info(f"Cron job added: {job.id} — {job.name}")
        return job

    def remove_job(self, job_id: str) -> bool:
        """Remove a scheduled job."""
        if job_id in self._jobs:
            del self._jobs[job_id]
            self._persist()
            return True
        return False

    def list_jobs(self) -> list[CronJob]:
        """List all scheduled jobs."""
        return list(self._jobs.values())

    async def start(self):
        """Start the scheduler heartbeat loop."""
        self._load()
        self._running = True
        logger.info(f"Cron scheduler started with {len(self._jobs)} jobs")

        while self._running:
            now = time.time()
            for job in self._jobs.values():
                if not job.enabled or job.next_run > now:
                    continue

                logger.info(f"Cron trigger: {job.id} — {job.name}")
                job.last_run = now
                job.next_run = self._compute_next_run(job.schedule, now)

                if self._task_callback:
                    try:
                        await self._task_callback(
                            job.task_title or job.name,
                            job.task_description or job.description,
                            job.task_type,
                        )
                    except Exception as e:
                        logger.error(f"Cron callback error: {e}")

            self._persist()
            await asyncio.sleep(30)  # Check every 30 seconds

    def stop(self):
        self._running = False

    def _compute_next_run(self, schedule: str, from_time: float = 0.0) -> float:
        """Compute the next run time from a schedule string.

        Supports:
        - Simple intervals: "every 30m", "every 1h", "every 24h"
        - Cron expressions: "0 9 * * *" (minute hour day month weekday)
        """
        import datetime

        base = from_time or time.time()

        schedule = schedule.strip().lower()

        # Simple interval format: "every 30m", "every 1h"
        if schedule.startswith("every "):
            interval_str = schedule[6:].strip()
            multiplier = 1.0
            if interval_str.endswith("m"):
                multiplier = 60.0
                interval_str = interval_str[:-1]
            elif interval_str.endswith("h"):
                multiplier = 3600.0
                interval_str = interval_str[:-1]
            elif interval_str.endswith("d"):
                multiplier = 86400.0
                interval_str = interval_str[:-1]
            elif interval_str.endswith("s"):
                interval_str = interval_str[:-1]

            try:
                seconds = float(interval_str) * multiplier
                return base + seconds
            except ValueError:
                pass

        # Cron expression: "minute hour day month weekday"
        parts = schedule.split()
        if len(parts) == 5:
            try:
                return self._next_cron_time(parts, base)
            except Exception as e:
                logger.warning(f"Failed to parse cron expression '{schedule}': {e}")

        # Default: 1 hour from now
        return base + 3600

    @staticmethod
    def _next_cron_time(parts: list[str], from_time: float) -> float:
        """Compute the next matching time for a 5-field cron expression.

        Fields: minute hour day-of-month month day-of-week
        Supports: numbers, *, */N (step), and comma-separated values.
        """
        import datetime

        def parse_field(field: str, min_val: int, max_val: int) -> set[int]:
            values = set()
            for part in field.split(","):
                part = part.strip()
                if part == "*":
                    values.update(range(min_val, max_val + 1))
                elif part.startswith("*/"):
                    step = int(part[2:])
                    values.update(range(min_val, max_val + 1, step))
                elif "-" in part:
                    start, end = part.split("-", 1)
                    values.update(range(int(start), int(end) + 1))
                else:
                    values.add(int(part))
            return values

        minutes = parse_field(parts[0], 0, 59)
        hours = parse_field(parts[1], 0, 23)
        days = parse_field(parts[2], 1, 31)
        months = parse_field(parts[3], 1, 12)
        weekdays = parse_field(parts[4], 0, 6)  # 0=Monday in Python

        dt = datetime.datetime.fromtimestamp(from_time) + datetime.timedelta(minutes=1)
        dt = dt.replace(second=0, microsecond=0)

        # Search up to 366 days ahead
        for _ in range(366 * 24 * 60):
            if (
                dt.month in months
                and dt.day in days
                and dt.weekday() in weekdays
                and dt.hour in hours
                and dt.minute in minutes
            ):
                return dt.timestamp()
            dt += datetime.timedelta(minutes=1)

        # Fallback: 1 hour from now
        return from_time + 3600

    def _persist(self):
        """Save jobs to disk."""
        try:
            data = [j.to_dict() for j in self._jobs.values()]
            self._data_path.write_text(json.dumps(data, indent=2))
        except Exception as e:
            logger.error(f"Failed to persist cron jobs: {e}")

    def _load(self):
        """Load jobs from disk."""
        if not self._data_path.exists():
            return
        try:
            data = json.loads(self._data_path.read_text())
            for item in data:
                job = CronJob.from_dict(item)
                self._jobs[job.id] = job
            logger.info(f"Loaded {len(self._jobs)} cron jobs")
        except Exception as e:
            logger.error(f"Failed to load cron jobs: {e}")


class CronTool(Tool):
    """Manage scheduled tasks."""

    def __init__(self, scheduler: CronScheduler):
        self._scheduler = scheduler

    @property
    def name(self) -> str:
        return "cron"

    @property
    def description(self) -> str:
        return "Manage scheduled tasks. Actions: list, add, remove, enable, disable."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "add", "remove", "enable", "disable"],
                    "description": "Action to perform",
                },
                "name": {"type": "string", "description": "Job name (for add)"},
                "schedule": {
                    "type": "string",
                    "description": "Schedule: 'every 30m', 'every 1h', 'every 24h' (for add)",
                },
                "task_title": {"type": "string", "description": "Task title when triggered (for add)"},
                "task_description": {"type": "string", "description": "Task description (for add)"},
                "task_type": {"type": "string", "description": "Task type (for add)", "default": "coding"},
                "job_id": {"type": "string", "description": "Job ID (for remove/enable/disable)"},
            },
            "required": ["action"],
        }

    async def execute(self, action: str = "", **kwargs) -> ToolResult:
        if action == "list":
            jobs = self._scheduler.list_jobs()
            if not jobs:
                return ToolResult(output="No scheduled jobs.")
            lines = [f"{'ID':<10} {'Name':<20} {'Schedule':<15} {'Enabled':<8}"]
            for j in jobs:
                lines.append(f"{j.id:<10} {j.name:<20} {j.schedule:<15} {j.enabled!s:<8}")
            return ToolResult(output="\n".join(lines))

        elif action == "add":
            job = CronJob(
                name=kwargs.get("name", "Unnamed"),
                schedule=kwargs.get("schedule", "every 1h"),
                task_title=kwargs.get("task_title", ""),
                task_description=kwargs.get("task_description", ""),
                task_type=kwargs.get("task_type", "coding"),
            )
            self._scheduler.add_job(job)
            return ToolResult(output=f"Created cron job: {job.id} — {job.name}")

        elif action == "remove":
            job_id = kwargs.get("job_id", "")
            if self._scheduler.remove_job(job_id):
                return ToolResult(output=f"Removed job: {job_id}")
            return ToolResult(error=f"Job not found: {job_id}", success=False)

        elif action in ("enable", "disable"):
            job_id = kwargs.get("job_id", "")
            jobs = {j.id: j for j in self._scheduler.list_jobs()}
            if job_id in jobs:
                jobs[job_id].enabled = (action == "enable")
                return ToolResult(output=f"Job {job_id} {'enabled' if action == 'enable' else 'disabled'}")
            return ToolResult(error=f"Job not found: {job_id}", success=False)

        return ToolResult(error=f"Unknown action: {action}", success=False)
