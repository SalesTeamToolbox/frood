"""
Tool execution rate limiter — sliding-window per-tool per-agent limits.

Prevents resource exhaustion by capping how many times each tool can be called
within a configurable time window. Limits are applied per-agent so one runaway
agent cannot starve others.
"""

import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field

logger = logging.getLogger("frood.rate_limiter")


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


# ── Adaptive Rate Limiter (LLM API) ─────────────────────────────────────────


@dataclass(frozen=True)
class ModelRateConfig:
    """Per-vendor rate limit configuration for Zen API free models.

    Different upstream providers behind Zen have different tolerance for
    bursty traffic. These defaults are based on observed behavior:

    - Qwen (Alibaba): strictest — "scale requests more smoothly" error on bursts
    - MiniMax: moderate — similar to Qwen but slightly more tolerant
    - Nemotron (NVIDIA): moderate — generous but still rejects hard bursts

    Configs are matched by vendor prefix in the model ID, not exact model name.
    This means new models from the same vendor auto-inherit the right limits.
    """

    initial_delay: float  # Starting inter-request delay (seconds)
    min_delay: float  # Floor — fastest sustainable rate
    max_delay: float  # Ceiling — backoff on repeated rate limits
    decrease_step: float  # How much to speed up after each success
    increase_factor: float  # Multiplier on rate-limit hit


# Per-vendor defaults based on observed Zen API behavior.
# Matched by prefix — new models from the same vendor auto-inherit these limits.
# Qwen triggered the "scale requests more smoothly" error during tool calls.
ZEN_VENDOR_RATE_LIMITS: list[tuple[str, ModelRateConfig]] = [
    # Qwen (Alibaba) — strictest, complained about burst acceleration
    (
        "qwen",
        ModelRateConfig(
            initial_delay=3.0,
            min_delay=1.0,
            max_delay=15.0,
            decrease_step=0.05,
            increase_factor=2.5,
        ),
    ),
    # MiniMax — similar to Qwen, slightly more tolerant
    (
        "minimax",
        ModelRateConfig(
            initial_delay=2.5,
            min_delay=0.8,
            max_delay=12.0,
            decrease_step=0.05,
            increase_factor=2.0,
        ),
    ),
    # Nemotron (NVIDIA) — moderate tolerance
    (
        "nemotron",
        ModelRateConfig(
            initial_delay=2.0,
            min_delay=0.7,
            max_delay=10.0,
            decrease_step=0.1,
            increase_factor=2.0,
        ),
    ),
]

# Fallback for any Zen model not matching a known vendor prefix.
# Conservative — assumes strictest upstream until proven otherwise.
ZEN_DEFAULT_RATE_CONFIG = ModelRateConfig(
    initial_delay=3.0,
    min_delay=1.0,
    max_delay=15.0,
    decrease_step=0.05,
    increase_factor=2.5,
)


def resolve_model_rate_config(model_id: str) -> ModelRateConfig:
    """Find the rate config for a model by vendor prefix matching.

    Model IDs are matched case-insensitively against vendor prefixes.
    First match wins, so order ZEN_VENDOR_RATE_LIMITS from most-specific
    to least-specific.

    Args:
        model_id: Full model ID string (e.g. "qwen3.6-plus-free").

    Returns:
        ModelRateConfig for the matching vendor, or the conservative default.
    """
    model_lower = model_id.lower()
    for prefix, config in ZEN_VENDOR_RATE_LIMITS:
        if prefix.lower() in model_lower:
            return config
    return ZEN_DEFAULT_RATE_CONFIG


class AdaptiveRateLimiter:
    """TCP-style congestion control for LLM API requests.

    Starts conservative, ramps up on success, backs off on rate-limit errors.
    Designed for free-tier APIs (OpenCode Zen) that reject bursty traffic.

    Supports per-model rate limiting — each model tracks its own state
    independently so a rate-limited Qwen doesn't penalize MiniMax calls.

    Algorithm:
    - Initial delay: model-specific (Qwen=3s, MiniMax=2.5s, etc.)
    - On success: decrease delay by small step (additive increase)
    - On rate limit: multiply delay by factor (multiplicative decrease)
    - Bounds: never below min_delay or above max_delay
    """

    def __init__(
        self,
        initial_delay: float = 2.0,
        min_delay: float = 0.5,
        max_delay: float = 10.0,
        decrease_step: float = 0.1,
        increase_factor: float = 2.0,
    ):
        self._min_delay = min_delay
        self._max_delay = max_delay
        self._decrease_step = decrease_step
        self._increase_factor = increase_factor
        self._current_delay = initial_delay
        self._last_request_time: float = 0.0
        self._consecutive_failures: int = 0
        self._total_requests: int = 0
        self._total_rate_limits: int = 0
        self._lock = asyncio.Lock()

    @property
    def current_delay(self) -> float:
        """Current inter-request delay in seconds."""
        return self._current_delay

    @property
    def stats(self) -> dict:
        """Return rate limiter statistics."""
        return {
            "current_delay": round(self._current_delay, 2),
            "min_delay": self._min_delay,
            "max_delay": self._max_delay,
            "total_requests": self._total_requests,
            "total_rate_limits": self._total_rate_limits,
            "consecutive_failures": self._consecutive_failures,
        }

    async def wait_if_needed(self) -> None:
        """Sleep if we haven't waited long enough since the last request."""
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_request_time
            if elapsed < self._current_delay and self._last_request_time > 0:
                wait_time = self._current_delay - elapsed
                logger.debug(
                    "AdaptiveRateLimiter: waiting %.2fs (delay=%.2fs)",
                    wait_time,
                    self._current_delay,
                )
                await asyncio.sleep(wait_time)
            self._last_request_time = time.monotonic()
            self._total_requests += 1

    def record_success(self) -> None:
        """Call after a successful API response — slightly reduce delay."""
        self._consecutive_failures = 0
        new_delay = max(self._min_delay, self._current_delay - self._decrease_step)
        if new_delay != self._current_delay:
            logger.debug(
                "AdaptiveRateLimiter: success, delay %.2f -> %.2f",
                self._current_delay,
                new_delay,
            )
        self._current_delay = new_delay

    def record_rate_limit(self, retry_after: float | None = None) -> None:
        """Call after a rate-limit response — back off aggressively.

        Args:
            retry_after: Seconds suggested by API (Retry-After header or
                error message). If provided, uses this as floor for new delay.
        """
        self._consecutive_failures += 1
        self._total_rate_limits += 1

        new_delay = min(self._max_delay, self._current_delay * self._increase_factor)

        if retry_after is not None:
            new_delay = max(new_delay, retry_after)

        logger.warning(
            "AdaptiveRateLimiter: rate limit hit (failures=%d), delay %.2f -> %.2f",
            self._consecutive_failures,
            self._current_delay,
            new_delay,
        )
        self._current_delay = new_delay

    def record_error(self) -> None:
        """Call after a non-rate-limit error — mild backoff."""
        self._consecutive_failures += 1
        new_delay = min(self._max_delay, self._current_delay * 1.2)
        if new_delay != self._current_delay:
            logger.debug(
                "AdaptiveRateLimiter: error, delay %.2f -> %.2f",
                self._current_delay,
                new_delay,
            )
        self._current_delay = new_delay

    def reset(self) -> None:
        """Reset to initial state."""
        self._consecutive_failures = 0
        self._last_request_time = 0.0


class PerModelRateLimiter:
    """Manages independent AdaptiveRateLimiters per Zen model.

    Each model gets its own rate limiter with vendor-specific defaults
    resolved by prefix matching (e.g. any "qwen*" model inherits Qwen
    limits). New models from known vendors auto-inherit the right config.

    Also tracks usage exhaustion (free tier quota used up).

    Usage:
        limiter = PerModelRateLimiter()
        await limiter.wait("qwen3.6-plus-free")
        resp = await api_call()
        limiter.record_success("qwen3.6-plus-free")
    """

    def __init__(
        self,
        default_config: ModelRateConfig | None = None,
    ):
        self._default_config = default_config or ZEN_DEFAULT_RATE_CONFIG
        self._limiters: dict[str, AdaptiveRateLimiter] = {}
        self._exhausted: dict[str, float] = {}  # model -> timestamp when exhausted

    def _get_limiter(self, model: str) -> AdaptiveRateLimiter:
        """Get or create the rate limiter for a model."""
        if model not in self._limiters:
            config = resolve_model_rate_config(model)
            self._limiters[model] = AdaptiveRateLimiter(
                initial_delay=config.initial_delay,
                min_delay=config.min_delay,
                max_delay=config.max_delay,
                decrease_step=config.decrease_step,
                increase_factor=config.increase_factor,
            )
            logger.info(
                "PerModelRateLimiter: created limiter for '%s' (initial_delay=%.1fs, min=%.1fs)",
                model,
                config.initial_delay,
                config.min_delay,
            )
        return self._limiters[model]

    async def wait(self, model: str) -> None:
        """Wait if needed before making a request for the given model."""
        limiter = self._get_limiter(model)
        await limiter.wait_if_needed()

    def record_success(self, model: str) -> None:
        """Record a successful response for the given model."""
        limiter = self._get_limiter(model)
        limiter.record_success()

    def record_rate_limit(self, model: str, retry_after: float | None = None) -> None:
        """Record a rate-limit response for the given model."""
        limiter = self._get_limiter(model)
        limiter.record_rate_limit(retry_after)

    def record_error(self, model: str) -> None:
        """Record a non-rate-limit error for the given model."""
        limiter = self._get_limiter(model)
        limiter.record_error()

    def get_stats(self, model: str | None = None) -> dict:
        """Get rate limiter stats.

        Args:
            model: If provided, return stats for that model only.
                   If None, return stats for all tracked models.
        """
        if model:
            limiter = self._limiters.get(model)
            if limiter:
                return limiter.stats
            return {"error": f"No limiter tracked for model '{model}'"}

        return {m: limiter.stats for m, limiter in self._limiters.items()}

    def reset(self, model: str | None = None) -> None:
        """Reset rate limiter state.

        Args:
            model: If provided, reset only that model. If None, reset all.
        """
        if model:
            limiter = self._limiters.get(model)
            if limiter:
                limiter.reset()
            self._exhausted.pop(model, None)
        else:
            for limiter in self._limiters.values():
                limiter.reset()
            self._exhausted.clear()

    def get_exhausted_models(self) -> list[str]:
        """Return list of models that are currently exhausted."""
        return [m for m in self._exhausted if self.is_exhausted(m)]

    def mark_exhausted(self, model: str) -> None:
        """Mark a model as exhausted (free tier quota used up) with timestamp."""
        import time

        self._exhausted[model] = time.time()
        logger.info("PerModelRateLimiter: marked '%s' as exhausted (free tier)", model)

    def is_exhausted(self, model: str) -> bool:
        """Check if a model is marked as exhausted and reset period hasn't passed."""
        from core.config import settings

        if model not in self._exhausted:
            return False
        exhausted_at = self._exhausted[model]
        import time

        reset_seconds = settings.zen_exhaustion_reset_hours * 3600
        if time.time() - exhausted_at > reset_seconds:
            del self._exhausted[model]
            logger.info("PerModelRateLimiter: '%s' exhaustion auto-reset (period expired)", model)
            return False
        return True

    def get_exhaustion_reset_time(self, model: str) -> float | None:
        """Return seconds until exhaustion resets, or None if not exhausted."""
        if model not in self._exhausted:
            return None
        from core.config import settings
        import time

        exhausted_at = self._exhausted[model]
        reset_seconds = settings.zen_exhaustion_reset_hours * 3600
        remaining = reset_seconds - (time.time() - exhausted_at)
        return max(0.0, remaining)
