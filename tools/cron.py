"""
Cron scheduling tool — persistent task scheduling for Agent42.

Supports cron expressions, intervals, one-shot schedules, and planned
multi-step task sequences. Schedules persist to a JSON file and survive
restarts.

Task types:
- recurring: Standard cron/interval-based jobs (default)
- once: One-time jobs that run at a specific time and auto-remove
- planned: Multi-step sequences where tasks run in dependency order
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

from tools.base import Tool, ToolResult

logger = logging.getLogger("agent42.tools.cron")


class JobType(str, Enum):
    RECURRING = "recurring"
    ONCE = "once"
    PLANNED = "planned"


class JobState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class CronJob:
    """A scheduled task."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    name: str = ""
    description: str = ""
    schedule: str = ""  # Cron expression or interval (e.g., "every 1h", "0 9 * * *")
    task_title: str = ""  # Task title to create when triggered
    task_description: str = ""
    task_type: str = "coding"
    enabled: bool = True
    last_run: float = 0.0
    next_run: float = 0.0
    created_at: float = field(default_factory=time.time)
    stagger_seconds: int = 0  # Manual stagger override (0 = auto)
    jitter_seconds: int = 0  # Random jitter within stagger window

    # Enhanced scheduling fields
    job_type: str = "recurring"  # recurring | once | planned
    state: str = "pending"  # pending | running | completed | failed
    run_count: int = 0
    timeout_seconds: int = 300  # Per-execution timeout
    error_history: list = field(default_factory=list)  # Last N errors
    depends_on: str = ""  # Job ID this depends on (for planned sequences)
    plan_id: str = ""  # Group ID for planned sequences

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
        import random
        from collections import defaultdict

        self._load()
        self._running = True
        logger.info(f"Cron scheduler started with {len(self._jobs)} jobs")

        # Auto-stagger: compute offsets for jobs sharing the same schedule
        schedule_groups: dict[str, list[str]] = defaultdict(list)
        for job in self._jobs.values():
            schedule_groups[job.schedule].append(job.id)

        stagger_offsets: dict[str, float] = {}
        for schedule_expr, job_ids in schedule_groups.items():
            if len(job_ids) <= 1:
                for jid in job_ids:
                    stagger_offsets[jid] = 0.0
                continue
            # Spread jobs evenly over a 60-second window (or use manual override)
            auto_gap = 60.0 / len(job_ids)
            for idx, jid in enumerate(job_ids):
                job = self._jobs[jid]
                if job.stagger_seconds > 0:
                    stagger_offsets[jid] = float(job.stagger_seconds)
                else:
                    stagger_offsets[jid] = idx * auto_gap
                # Add random jitter if configured
                if job.jitter_seconds > 0:
                    stagger_offsets[jid] += random.uniform(0, job.jitter_seconds)

        logger.info(f"Computed stagger offsets for {len(stagger_offsets)} jobs")

        while self._running:
            now = time.time()
            for job in self._jobs.values():
                effective_next = job.next_run + stagger_offsets.get(job.id, 0.0)
                if not job.enabled or effective_next > now:
                    continue

                # Check dependency for planned jobs
                if job.job_type == JobType.PLANNED and job.depends_on:
                    dep = self._jobs.get(job.depends_on)
                    if dep and dep.state != JobState.COMPLETED:
                        continue  # Dependency not yet completed

                logger.info(f"Cron trigger: {job.id} — {job.name}")
                job.last_run = now
                job.state = JobState.RUNNING
                job.run_count += 1

                if self._task_callback:
                    try:
                        await self._task_callback(
                            job.task_title or job.name,
                            job.task_description or job.description,
                            job.task_type,
                        )
                        job.state = JobState.COMPLETED
                    except Exception as e:
                        logger.error(f"Cron callback error: {e}")
                        job.state = JobState.FAILED
                        job.error_history.append(
                            {"time": now, "error": str(e)}
                        )
                        # Keep only last 10 errors
                        job.error_history = job.error_history[-10:]

                # Handle one-time jobs: disable after execution
                if job.job_type == JobType.ONCE:
                    job.enabled = False
                    job.state = JobState.COMPLETED
                elif job.job_type == JobType.RECURRING:
                    job.next_run = self._compute_next_run(job.schedule, now)
                    job.state = JobState.PENDING

            # Clean up completed one-time jobs
            completed_once = [
                jid for jid, j in self._jobs.items()
                if j.job_type == JobType.ONCE and not j.enabled
            ]
            for jid in completed_once:
                del self._jobs[jid]
                logger.info(f"Removed completed one-time job: {jid}")

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
    """Manage scheduled tasks including recurring, one-time, and planned sequences."""

    def __init__(self, scheduler: CronScheduler):
        self._scheduler = scheduler

    @property
    def name(self) -> str:
        return "cron"

    @property
    def description(self) -> str:
        return (
            "Manage scheduled tasks. "
            "Actions: list, add, schedule_once, schedule_plan, remove, enable, disable, task_status."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "add", "schedule_once", "schedule_plan",
                             "remove", "enable", "disable", "task_status"],
                    "description": "Action to perform",
                },
                "name": {"type": "string", "description": "Job name (for add/schedule_once)"},
                "schedule": {
                    "type": "string",
                    "description": "Schedule: 'every 30m', 'every 1h', cron expression (for add)",
                },
                "task_title": {
                    "type": "string",
                    "description": "Task title when triggered",
                },
                "task_description": {"type": "string", "description": "Task description"},
                "task_type": {
                    "type": "string",
                    "description": "Task type (default: coding)",
                    "default": "coding",
                },
                "job_id": {"type": "string", "description": "Job ID (for remove/enable/disable/task_status)"},
                "run_at": {
                    "type": "number",
                    "description": "Unix timestamp to run at (for schedule_once)",
                },
                "delay_seconds": {
                    "type": "integer",
                    "description": "Seconds from now to run (for schedule_once, alternative to run_at)",
                },
                "steps": {
                    "type": "array",
                    "description": "Array of {name, task_title, task_description, task_type} for schedule_plan",
                    "items": {"type": "object"},
                },
                "timeout_seconds": {
                    "type": "integer",
                    "description": "Per-task timeout in seconds (default: 300)",
                },
            },
            "required": ["action"],
        }

    async def execute(self, action: str = "", **kwargs) -> ToolResult:
        if action == "list":
            return self._list_jobs()
        elif action == "add":
            return self._add_recurring(**kwargs)
        elif action == "schedule_once":
            return self._schedule_once(**kwargs)
        elif action == "schedule_plan":
            return self._schedule_plan(**kwargs)
        elif action == "remove":
            return self._remove(**kwargs)
        elif action in ("enable", "disable"):
            return self._toggle(action, **kwargs)
        elif action == "task_status":
            return self._task_status(**kwargs)
        return ToolResult(error=f"Unknown action: {action}", success=False)

    def _list_jobs(self) -> ToolResult:
        jobs = self._scheduler.list_jobs()
        if not jobs:
            return ToolResult(output="No scheduled jobs.")
        lines = [f"{'ID':<10} {'Name':<20} {'Type':<10} {'Schedule':<15} {'State':<10} {'Runs':<5}"]
        for j in jobs:
            lines.append(
                f"{j.id:<10} {j.name:<20} {j.job_type:<10} "
                f"{j.schedule:<15} {j.state:<10} {j.run_count:<5}"
            )
        return ToolResult(output="\n".join(lines))

    def _add_recurring(self, **kwargs) -> ToolResult:
        job = CronJob(
            name=kwargs.get("name", "Unnamed"),
            schedule=kwargs.get("schedule", "every 1h"),
            task_title=kwargs.get("task_title", ""),
            task_description=kwargs.get("task_description", ""),
            task_type=kwargs.get("task_type", "coding"),
            job_type=JobType.RECURRING,
            timeout_seconds=kwargs.get("timeout_seconds", 300),
        )
        self._scheduler.add_job(job)
        return ToolResult(output=f"Created recurring job: {job.id} — {job.name}")

    def _schedule_once(self, **kwargs) -> ToolResult:
        run_at = kwargs.get("run_at", 0)
        delay = kwargs.get("delay_seconds", 0)

        if not run_at and not delay:
            return ToolResult(
                error="Either run_at (unix timestamp) or delay_seconds is required",
                success=False,
            )

        if delay and not run_at:
            run_at = time.time() + delay

        job = CronJob(
            name=kwargs.get("name", "One-time task"),
            schedule="once",
            task_title=kwargs.get("task_title", ""),
            task_description=kwargs.get("task_description", ""),
            task_type=kwargs.get("task_type", "coding"),
            job_type=JobType.ONCE,
            next_run=run_at,
            timeout_seconds=kwargs.get("timeout_seconds", 300),
        )
        self._scheduler.add_job(job)
        import datetime
        run_str = datetime.datetime.fromtimestamp(run_at).strftime("%Y-%m-%d %H:%M:%S")
        return ToolResult(output=f"Scheduled one-time task: {job.id} — {job.name} (runs at {run_str})")

    def _schedule_plan(self, **kwargs) -> ToolResult:
        steps = kwargs.get("steps", [])
        if not steps or not isinstance(steps, list):
            return ToolResult(
                error="steps array is required for schedule_plan",
                success=False,
            )

        plan_id = uuid.uuid4().hex[:8]
        created_jobs = []
        prev_job_id = ""

        for i, step in enumerate(steps):
            job = CronJob(
                name=step.get("name", f"Step {i + 1}"),
                schedule="planned",
                task_title=step.get("task_title", ""),
                task_description=step.get("task_description", ""),
                task_type=step.get("task_type", "coding"),
                job_type=JobType.PLANNED,
                plan_id=plan_id,
                depends_on=prev_job_id,
                next_run=time.time() if i == 0 else 0,  # First step runs immediately
                timeout_seconds=kwargs.get("timeout_seconds", 300),
            )
            self._scheduler.add_job(job)
            created_jobs.append(job)
            prev_job_id = job.id

        lines = [f"Created plan {plan_id} with {len(created_jobs)} steps:"]
        for i, j in enumerate(created_jobs):
            dep = f" (after {j.depends_on})" if j.depends_on else " (first)"
            lines.append(f"  {i + 1}. {j.id} — {j.name}{dep}")

        return ToolResult(output="\n".join(lines))

    def _remove(self, **kwargs) -> ToolResult:
        job_id = kwargs.get("job_id", "")
        if self._scheduler.remove_job(job_id):
            return ToolResult(output=f"Removed job: {job_id}")
        return ToolResult(error=f"Job not found: {job_id}", success=False)

    def _toggle(self, action: str, **kwargs) -> ToolResult:
        job_id = kwargs.get("job_id", "")
        jobs = {j.id: j for j in self._scheduler.list_jobs()}
        if job_id in jobs:
            jobs[job_id].enabled = action == "enable"
            return ToolResult(
                output=f"Job {job_id} {'enabled' if action == 'enable' else 'disabled'}"
            )
        return ToolResult(error=f"Job not found: {job_id}", success=False)

    def _task_status(self, **kwargs) -> ToolResult:
        job_id = kwargs.get("job_id", "")
        if not job_id:
            return ToolResult(error="job_id is required for task_status", success=False)

        jobs = {j.id: j for j in self._scheduler.list_jobs()}
        job = jobs.get(job_id)
        if not job:
            return ToolResult(error=f"Job not found: {job_id}", success=False)

        import datetime
        created = datetime.datetime.fromtimestamp(job.created_at).strftime("%Y-%m-%d %H:%M")
        last_run = (
            datetime.datetime.fromtimestamp(job.last_run).strftime("%Y-%m-%d %H:%M")
            if job.last_run
            else "never"
        )

        lines = [
            f"Job: {job.id} — {job.name}",
            f"  Type: {job.job_type}",
            f"  State: {job.state}",
            f"  Schedule: {job.schedule}",
            f"  Run count: {job.run_count}",
            f"  Created: {created}",
            f"  Last run: {last_run}",
            f"  Enabled: {job.enabled}",
            f"  Timeout: {job.timeout_seconds}s",
        ]

        if job.depends_on:
            lines.append(f"  Depends on: {job.depends_on}")
        if job.plan_id:
            lines.append(f"  Plan ID: {job.plan_id}")
        if job.error_history:
            lines.append(f"  Recent errors: {len(job.error_history)}")
            for err in job.error_history[-3:]:
                err_time = datetime.datetime.fromtimestamp(err["time"]).strftime("%H:%M:%S")
                lines.append(f"    [{err_time}] {err['error'][:100]}")

        return ToolResult(output="\n".join(lines))
