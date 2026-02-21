"""
Heartbeat service — periodic health monitoring for agents and subsystems.

Inspired by Nanobot's heartbeat mechanism. Tracks agent liveness, detects
stalled tasks, and provides system health metrics for the dashboard.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger("agent42.heartbeat")

# How often to emit heartbeats (seconds)
DEFAULT_INTERVAL = 30

# Agent is considered stalled if no heartbeat for this many seconds
STALL_THRESHOLD = 300  # 5 minutes


@dataclass
class AgentHeartbeat:
    """Heartbeat record for a running agent."""
    task_id: str
    last_beat: float = field(default_factory=time.monotonic)
    iteration: int = 0
    status: str = "running"
    message: str = ""
    context_tokens_used: int = 0  # Context window tracking (OpenClaw feature)

    @property
    def age_seconds(self) -> float:
        return time.monotonic() - self.last_beat

    @property
    def is_stalled(self) -> bool:
        return self.age_seconds > STALL_THRESHOLD

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "last_beat_age_s": round(self.age_seconds, 1),
            "iteration": self.iteration,
            "status": self.status,
            "message": self.message,
            "stalled": self.is_stalled,
            "context_tokens_used": self.context_tokens_used,
        }


@dataclass
class SystemHealth:
    """Overall system health snapshot."""
    active_agents: int = 0
    stalled_agents: int = 0
    tasks_pending: int = 0
    tasks_completed: int = 0
    tasks_failed: int = 0
    uptime_seconds: float = 0
    memory_mb: float = 0
    tools_registered: int = 0

    def to_dict(self) -> dict:
        return {
            "active_agents": self.active_agents,
            "stalled_agents": self.stalled_agents,
            "tasks_pending": self.tasks_pending,
            "tasks_completed": self.tasks_completed,
            "tasks_failed": self.tasks_failed,
            "uptime_seconds": round(self.uptime_seconds, 1),
            "memory_mb": round(self.memory_mb, 1),
            "tools_registered": self.tools_registered,
        }


class HeartbeatService:
    """Monitors agent health and broadcasts system status."""

    def __init__(
        self,
        interval: float = DEFAULT_INTERVAL,
        on_stall=None,
        on_heartbeat=None,
        notification_service=None,
    ):
        self._interval = interval
        self._agents: dict[str, AgentHeartbeat] = {}
        self._on_stall = on_stall  # async callback(task_id)
        self._on_heartbeat = on_heartbeat  # async callback(SystemHealth)
        self._notification_service = notification_service  # NotificationService (OpenClaw feature)
        self._start_time = time.monotonic()
        self._running = False
        self._task: asyncio.Task | None = None

    def beat(self, task_id: str, iteration: int = 0, message: str = ""):
        """Record a heartbeat from an agent."""
        if task_id in self._agents:
            hb = self._agents[task_id]
            hb.last_beat = time.monotonic()
            hb.iteration = iteration
            hb.message = message
        else:
            self._agents[task_id] = AgentHeartbeat(
                task_id=task_id, iteration=iteration, message=message,
            )

    def register_agent(self, task_id: str):
        """Register a new agent for monitoring."""
        self._agents[task_id] = AgentHeartbeat(task_id=task_id)

    def unregister_agent(self, task_id: str):
        """Remove an agent from monitoring."""
        self._agents.pop(task_id, None)

    def mark_complete(self, task_id: str):
        """Mark an agent as completed."""
        if task_id in self._agents:
            self._agents[task_id].status = "completed"

    def mark_failed(self, task_id: str, error: str = ""):
        """Mark an agent as failed."""
        if task_id in self._agents:
            self._agents[task_id].status = "failed"
            self._agents[task_id].message = error

    @property
    def active_agents(self) -> list[AgentHeartbeat]:
        return [
            hb for hb in self._agents.values()
            if hb.status == "running"
        ]

    @property
    def stalled_agents(self) -> list[AgentHeartbeat]:
        return [
            hb for hb in self._agents.values()
            if hb.status == "running" and hb.is_stalled
        ]

    def get_health(self, task_queue=None, tool_registry=None) -> SystemHealth:
        """Get a snapshot of overall system health."""
        health = SystemHealth(
            active_agents=len(self.active_agents),
            stalled_agents=len(self.stalled_agents),
            uptime_seconds=time.monotonic() - self._start_time,
        )

        if task_queue:
            stats = task_queue.stats() if hasattr(task_queue, "stats") else {}
            health.tasks_pending = stats.get("pending", 0)
            health.tasks_completed = stats.get("completed", 0)
            health.tasks_failed = stats.get("failed", 0)

        if tool_registry:
            health.tools_registered = len(tool_registry.list_tools())

        # Get memory usage
        try:
            import resource
            usage = resource.getrusage(resource.RUSAGE_SELF)
            health.memory_mb = usage.ru_maxrss / 1024  # KB to MB on Linux
        except (ImportError, AttributeError):
            pass

        return health

    async def start(self):
        """Start the heartbeat monitoring loop."""
        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info(f"Heartbeat service started (interval: {self._interval}s)")

    def stop(self):
        """Stop the heartbeat monitoring loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None
        logger.info("Heartbeat service stopped")

    async def _monitor_loop(self):
        """Periodically check for stalled agents and broadcast health."""
        while self._running:
            try:
                await asyncio.sleep(self._interval)

                # Check for stalled agents
                for hb in self.stalled_agents:
                    logger.warning(
                        f"Agent stalled: task={hb.task_id}, "
                        f"last_beat={hb.age_seconds:.0f}s ago, "
                        f"iteration={hb.iteration}"
                    )
                    if self._on_stall:
                        await self._on_stall(hb.task_id)
                    # Send webhook notification for stalled agents
                    if self._notification_service:
                        try:
                            from core.notification_service import NotificationPayload, SEVERITY_CRITICAL
                            await self._notification_service.notify(NotificationPayload(
                                event="agent_stalled",
                                timestamp=time.time(),
                                task_id=hb.task_id,
                                title=f"Agent stalled (iteration {hb.iteration})",
                                details=f"No heartbeat for {hb.age_seconds:.0f}s. Last message: {hb.message}",
                                severity=SEVERITY_CRITICAL,
                            ))
                        except Exception as e:
                            logger.error(f"Failed to send stall notification: {e}")

                # Broadcast health
                if self._on_heartbeat:
                    health = self.get_health()
                    await self._on_heartbeat(health)

                # Clean up completed/failed agents older than 10 minutes
                cutoff = time.monotonic() - 600
                to_remove = [
                    tid for tid, hb in self._agents.items()
                    if hb.status in ("completed", "failed") and hb.last_beat < cutoff
                ]
                for tid in to_remove:
                    del self._agents[tid]

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Heartbeat monitor error: {e}", exc_info=True)
                await asyncio.sleep(5)
