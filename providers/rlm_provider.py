"""
Agent42 RLM Provider — Recursive Language Model integration.

Wraps the official ``rlms`` library (MIT CSAIL, arXiv:2512.24601) to enable
processing of inputs far beyond model context windows.  RLMs treat the prompt
as an external variable in a REPL environment rather than cramming it into
context, allowing recursive decomposition and programmatic inspection.

Drop-in enhancement: when context exceeds ``RLM_THRESHOLD_TOKENS`` the provider
routes through ``rlm.completion()``; below that threshold it returns ``None``
so the caller can fall back to standard completion.

The rlms package is an optional dependency — all imports are conditional.
"""

import asyncio
import logging
import os
import time

from core.rlm_config import RLMConfig

logger = logging.getLogger("agent42.rlm")

# RLM-capable model tiers — models that can generate Python code to navigate
# the REPL environment effectively.  Used by the router to pick appropriate
# root/sub models.
RLM_TIER_1 = frozenset(
    {
        "claude-sonnet",
        "or-claude-sonnet",
        "or-free-qwen-coder",
        "gpt-4o",
        "or-gpt-4o",
    }
)
RLM_TIER_2 = frozenset(
    {
        "gpt-4o-mini",
        "gemini-2-flash",
        "deepseek-chat",
        "or-free-deepseek-chat",
        "or-free-gemini-flash",
    }
)
RLM_NOT_RECOMMENDED = frozenset(
    {
        "or-free-llama-70b",
        "or-free-gemma-27b",
        "or-free-nemotron",
        "or-free-mistral-small",
    }
)

# Task types that benefit most from RLM processing
RLM_TASK_TYPES = frozenset(
    {
        "coding",
        "debugging",
        "research",
        "refactoring",
        "data_analysis",
    }
)


class RLMProvider:
    """Wraps the official rlms library for Agent42 integration.

    Lazily initialises the RLM instance on first use so that the ``rlms``
    package is only imported when actually needed.
    """

    def __init__(self, config: RLMConfig | None = None):
        self.config = config or RLMConfig.from_env()
        self._rlm_instance = None
        self._total_cost_usd: float = 0.0
        self._total_calls: int = 0

    # -- Backend mapping -------------------------------------------------------

    def _get_backend_config(self) -> tuple[str, dict]:
        """Determine RLM backend from Agent42's available API keys."""
        root_model = self.config.root_model

        if os.getenv("OPENROUTER_API_KEY"):
            return "openrouter", {
                "model_name": root_model or "qwen/qwen3-coder",
            }
        if os.getenv("OPENAI_API_KEY"):
            return "openai", {
                "model_name": root_model or "gpt-4o-mini",
            }
        if os.getenv("ANTHROPIC_API_KEY"):
            return "anthropic", {
                "model_name": root_model or "claude-sonnet-4-20250514",
            }
        # Universal fallback via LiteLLM
        return "litellm", {
            "model_name": root_model or "gpt-4o-mini",
        }

    # -- Lazy init -------------------------------------------------------------

    def _get_or_create_rlm(self):
        """Lazy-initialize the RLM instance."""
        if self._rlm_instance is not None:
            return self._rlm_instance

        try:
            from rlm import RLM
            from rlm.logger import RLMLogger
        except ImportError:
            raise ImportError("rlms package not installed. Run: pip install rlms")

        backend, backend_kwargs = self._get_backend_config()
        os.makedirs(self.config.log_dir, exist_ok=True)

        env_kwargs = {}
        if self.config.environment == "docker":
            env_kwargs["image"] = self.config.docker_image

        self._rlm_instance = RLM(
            backend=backend,
            backend_kwargs=backend_kwargs,
            environment=self.config.environment,
            environment_kwargs=env_kwargs,
            verbose=self.config.verbose,
            logger=RLMLogger(log_dir=self.config.log_dir),
        )
        logger.info(
            "RLM initialised: backend=%s, env=%s, model=%s",
            backend,
            self.config.environment,
            backend_kwargs.get("model_name", "?"),
        )
        return self._rlm_instance

    # -- Threshold detection ---------------------------------------------------

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """Rough token estimate: ~4 chars per token."""
        return len(text) // 4

    def should_use_rlm(self, context: str, task_type: str = "") -> bool:
        """Determine if RLM should be used based on context size and task type."""
        if not self.config.enabled:
            return False
        estimated_tokens = self.estimate_tokens(context)
        if estimated_tokens <= self.config.threshold_tokens:
            return False
        # For non-RLM-friendly task types, raise the bar (2x threshold)
        if task_type and task_type not in RLM_TASK_TYPES:
            return estimated_tokens > self.config.threshold_tokens * 2
        return True

    # -- Cost tracking ---------------------------------------------------------

    @property
    def total_cost_usd(self) -> float:
        return round(self._total_cost_usd, 4)

    @property
    def total_calls(self) -> int:
        return self._total_calls

    def _check_cost_limit(self) -> bool:
        """Return True if within cost limit."""
        if self.config.cost_limit <= 0:
            return True
        return self._total_cost_usd < self.config.cost_limit

    # -- Completion ------------------------------------------------------------

    async def complete(
        self,
        query: str,
        context: str,
        task_type: str = "",
        **kwargs,
    ) -> dict | None:
        """Route through RLM if context is large enough.

        Returns a dict with ``response``, ``metadata``, and ``used_rlm`` keys,
        or ``None`` if the context is too small (caller should use standard
        completion).
        """
        if not self.should_use_rlm(context, task_type=task_type):
            return None

        if not self._check_cost_limit():
            logger.warning(
                "RLM cost limit reached ($%.2f / $%.2f) — falling back to standard",
                self._total_cost_usd,
                self.config.cost_limit,
            )
            return None

        # Also respect the global daily spending limit
        try:
            from core.config import settings
            from providers.registry import spending_tracker

            if not spending_tracker.check_limit(settings.max_daily_api_spend_usd):
                logger.warning("Global daily spending limit reached — RLM skipped")
                return None
        except Exception:
            pass  # Non-fatal

        est_tokens = self.estimate_tokens(context)

        logger.info(
            "RLM activated: context ~%dk tokens, env=%s, task_type=%s",
            est_tokens // 1000,
            self.config.environment,
            task_type or "unknown",
        )

        start_time = time.monotonic()
        try:
            rlm = self._get_or_create_rlm()
            # rlm.completion() is synchronous — run in executor to avoid
            # blocking the event loop
            loop = asyncio.get_running_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: rlm.completion(query=query, context=context),
                ),
                timeout=self.config.timeout_seconds,
            )

            elapsed = time.monotonic() - start_time
            metadata = getattr(result, "metadata", {}) or {}
            response_text = getattr(result, "response", str(result))

            # Track cost if available in metadata
            cost = metadata.get("total_cost_usd", 0.0)
            if cost:
                self._total_cost_usd += cost
            self._total_calls += 1

            # Report to global spending tracker so RLM costs count toward
            # the daily API spending limit.
            try:
                from providers.registry import spending_tracker

                prompt_est = est_tokens
                completion_est = self.estimate_tokens(response_text)
                spending_tracker.record_usage(
                    "rlm",
                    prompt_est,
                    completion_est,
                    model_id="rlm-completion",
                )
            except Exception:
                pass  # Non-fatal — spending tracker is a safety net

            logger.info(
                "RLM complete: %.1fs, iterations=%s, cost=$%.4f",
                elapsed,
                metadata.get("iterations", "?"),
                cost,
            )

            return {
                "response": response_text,
                "metadata": metadata,
                "used_rlm": True,
                "elapsed_seconds": round(elapsed, 2),
                "estimated_context_tokens": est_tokens,
            }

        except TimeoutError:
            elapsed = time.monotonic() - start_time
            logger.error(
                "RLM timed out after %.1fs (limit: %ds)",
                elapsed,
                self.config.timeout_seconds,
            )
            return None
        except ImportError:
            logger.error("rlms package not installed — RLM unavailable")
            return None
        except Exception as e:
            elapsed = time.monotonic() - start_time
            logger.error("RLM completion failed after %.1fs: %s", elapsed, e)
            return None

    # -- Model suitability helpers ---------------------------------------------

    @staticmethod
    def is_rlm_capable(model_key: str) -> bool:
        """Check if a model is suitable for RLM root processing."""
        return model_key in RLM_TIER_1 or model_key in RLM_TIER_2

    @staticmethod
    def get_rlm_tier(model_key: str) -> int:
        """Return tier (1=best, 2=good, 3=not recommended, 0=unknown)."""
        if model_key in RLM_TIER_1:
            return 1
        if model_key in RLM_TIER_2:
            return 2
        if model_key in RLM_NOT_RECOMMENDED:
            return 3
        return 0

    def get_status(self) -> dict:
        """Return current RLM provider status for dashboard display."""
        return {
            "enabled": self.config.enabled,
            "environment": self.config.environment,
            "threshold_tokens": self.config.threshold_tokens,
            "max_depth": self.config.max_depth,
            "max_iterations": self.config.max_iterations,
            "cost_limit": self.config.cost_limit,
            "total_cost_usd": self.total_cost_usd,
            "total_calls": self.total_calls,
            "rlms_installed": _is_rlms_installed(),
        }


def _is_rlms_installed() -> bool:
    """Check if the rlms package is available."""
    try:
        import rlm  # noqa: F401

        return True
    except ImportError:
        return False
