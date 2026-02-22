"""
Tool execution rate limiter — sliding-window per-tool per-agent limits.

Prevents resource exhaustion by capping how many times each tool can be called
within a configurable time window. Limits are applied per-agent so one runaway
agent cannot starve others.
"""

import logging
import time
from collections import defaultdict
from dataclasses import dataclass

logger = logging.getLogger("agent42.rate_limiter")


@dataclass(frozen=True)
class ToolLimit:
    """Rate limit specification for a single tool."""

    max_calls: int
    window_seconds: float


# Default per-tool rate limits (per agent, per window).
# These are generous defaults — tighten via TOOL_RATE_LIMIT_OVERRIDES for production.
DEFAULT_TOOL_LIMITS: dict[str, ToolLimit] = {
    "web_search": ToolLimit(max_calls=60, window_seconds=3600),  # 60/hour
    "web_fetch": ToolLimit(max_calls=60, window_seconds=3600),  # 60/hour
    "http_request": ToolLimit(max_calls=120, window_seconds=3600),  # 120/hour
    "browser": ToolLimit(max_calls=30, window_seconds=3600),  # 30/hour
    "shell": ToolLimit(max_calls=200, window_seconds=3600),  # 200/hour
    "docker": ToolLimit(max_calls=20, window_seconds=3600),  # 20/hour
}


class ToolRateLimiter:
    """Sliding-window rate limiter for tool execution.

    Tracks call timestamps per (agent_id, tool_name) key and enforces
    configurable limits. Expired timestamps are pruned on each check.
    """

    def __init__(self, limits: dict[str, ToolLimit] | None = None):
        self._limits = dict(limits) if limits else dict(DEFAULT_TOOL_LIMITS)
        self._calls: dict[str, list[float]] = defaultdict(list)

    def check(self, tool_name: str, agent_id: str = "default") -> tuple[bool, str]:
        """Check if a tool call is within rate limits.

        Returns:
            (True, "") if allowed, (False, reason) if rate-limited.
        """
        limit = self._limits.get(tool_name)
        if not limit:
            return True, ""  # No limit configured for this tool

        key = f"{agent_id}:{tool_name}"
        now = time.monotonic()

        # Prune expired timestamps
        cutoff = now - limit.window_seconds
        timestamps = self._calls[key]
        self._calls[key] = [t for t in timestamps if t > cutoff]

        if len(self._calls[key]) >= limit.max_calls:
            remaining = limit.window_seconds - (now - self._calls[key][0])
            msg = (
                f"Rate limit exceeded for '{tool_name}': "
                f"{limit.max_calls} calls per {int(limit.window_seconds)}s window. "
                f"Try again in {int(remaining)}s."
            )
            logger.warning(f"[{agent_id}] {msg}")
            return False, msg

        return True, ""

    def record(self, tool_name: str, agent_id: str = "default"):
        """Record a tool call timestamp."""
        key = f"{agent_id}:{tool_name}"
        self._calls[key].append(time.monotonic())

    def update_limits(self, overrides: dict[str, ToolLimit]):
        """Merge custom limits into the current configuration."""
        self._limits.update(overrides)

    def reset(self, agent_id: str | None = None):
        """Clear call history. If agent_id given, only clear that agent's history."""
        if agent_id:
            keys_to_remove = [k for k in self._calls if k.startswith(f"{agent_id}:")]
            for k in keys_to_remove:
                del self._calls[k]
        else:
            self._calls.clear()
