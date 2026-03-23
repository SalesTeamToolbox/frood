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


def _get_multiplier(tier: str) -> float:
    """Return the rate limit multiplier for a given reward tier.

    Args:
        tier: Reward tier string ("gold", "silver", "bronze", "provisional", or "").

    Returns:
        Float multiplier to scale max_calls:
        - gold → 2.0x (from settings.rewards_gold_rate_limit_multiplier)
        - silver → 1.5x (from settings.rewards_silver_rate_limit_multiplier)
        - bronze → 1.0x (from settings.rewards_bronze_rate_limit_multiplier)
        - "" / "provisional" / unknown → 1.0 (no change — D-06)

    Uses deferred import of settings to avoid circular-import risk at module load.
    """
    from core.config import settings  # Deferred import — avoids circular at load time

    multiplier_map = {
        "gold": settings.rewards_gold_rate_limit_multiplier,
        "silver": settings.rewards_silver_rate_limit_multiplier,
        "bronze": settings.rewards_bronze_rate_limit_multiplier,
    }
    return multiplier_map.get(tier, 1.0)


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

    def check(self, tool_name: str, agent_id: str = "default", tier: str = "") -> tuple[bool, str]:
        """Check if a tool call is within rate limits.

        Args:
            tool_name: Name of the tool to check.
            agent_id: Agent identifier (used as part of the _calls key — D-05).
            tier: Reward tier for rate limit scaling ("gold", "silver", "bronze", or "").
                Gold agents get 2x effective max_calls, silver 1.5x, empty/provisional 1.0x.

        Returns:
            (True, "") if allowed, (False, reason) if rate-limited.

        Note: The _calls dict key is always "{agent_id}:{tool_name}" regardless of tier
        (D-05). Only the effective max_calls threshold changes per tier.
        """
        limit = self._limits.get(tool_name)
        if not limit:
            return True, ""  # No limit configured for this tool

        key = f"{agent_id}:{tool_name}"  # D-05: key structure unchanged
        now = time.monotonic()

        # Apply tier multiplier to the effective call ceiling
        multiplier = _get_multiplier(tier)
        effective_max = int(limit.max_calls * multiplier)

        # Prune expired timestamps
        cutoff = now - limit.window_seconds
        timestamps = self._calls[key]
        self._calls[key] = [t for t in timestamps if t > cutoff]

        if len(self._calls[key]) >= effective_max:
            remaining = limit.window_seconds - (now - self._calls[key][0])
            msg = (
                f"Rate limit exceeded for '{tool_name}' (tier={tier or 'none'}): "
                f"{effective_max} calls per {int(limit.window_seconds)}s window. "
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
