"""
Model router — maps task types to the best model for the job.

Free-first strategy: uses OpenRouter free models for bulk agent work.
Premium models only used when admin explicitly configures them for
specific task types or for final reviews.

Routing priority:
  1. Admin override (TASK_TYPE_MODEL env var) — always wins
  2. Dynamic routing (from outcome tracking + research) — data-driven
  3. Trial model injection (small % of tasks) — evaluates new models
  4. OpenRouter free models (hardcoded defaults) — fallback
"""

import json
import logging
import os
from pathlib import Path

from core.task_queue import TaskType
from providers.registry import ProviderRegistry

logger = logging.getLogger("agent42.router")


# -- Default routing: free models for everything ------------------------------
# These are the defaults when no admin override is set.
# OpenRouter free models are preferred as they need only one API key.

FREE_ROUTING: dict[TaskType, dict] = {
    TaskType.CODING: {
        "primary": "or-free-qwen-coder",  # Qwen3 Coder 480B — strongest free coder
        "critic": "or-free-deepseek-r1",  # DeepSeek R1 0528 — best free reasoner
        "max_iterations": 8,
    },
    TaskType.DEBUGGING: {
        "primary": "or-free-deepseek-r1",  # DeepSeek R1 — reasoning for root cause
        "critic": "or-free-devstral",  # Devstral 123B — multi-file awareness
        "max_iterations": 10,
    },
    TaskType.RESEARCH: {
        "primary": "or-free-llama4-maverick",  # Llama 4 Maverick — GPT-4+ level
        "critic": "or-free-deepseek-chat",  # DeepSeek Chat for second opinion
        "max_iterations": 5,
    },
    TaskType.REFACTORING: {
        "primary": "or-free-qwen-coder",  # Qwen3 Coder — best for code changes
        "critic": "or-free-devstral",  # Devstral — multi-file project awareness
        "max_iterations": 8,
    },
    TaskType.DOCUMENTATION: {
        "primary": "or-free-llama4-maverick",  # Llama 4 — strong writing
        "critic": "or-free-gemma-27b",  # Gemma 27B — fast verification
        "max_iterations": 4,
    },
    TaskType.MARKETING: {
        "primary": "or-free-llama4-maverick",  # Llama 4 — creative + general
        "critic": "or-free-deepseek-chat",  # DeepSeek Chat v3.1
        "max_iterations": 6,
    },
    TaskType.EMAIL: {
        "primary": "or-free-mistral-small",  # Mistral Small 3.1 — fast + precise
        "critic": None,
        "max_iterations": 3,
    },
    TaskType.DESIGN: {
        "primary": "or-free-llama4-maverick",  # Strong visual/creative reasoning
        "critic": "or-free-deepseek-chat",
        "max_iterations": 5,
    },
    TaskType.CONTENT: {
        "primary": "or-free-llama4-maverick",  # Best free model for writing
        "critic": "or-free-gemma-27b",  # Fast editorial check
        "max_iterations": 6,
    },
    TaskType.STRATEGY: {
        "primary": "or-free-deepseek-r1",  # Deep reasoning for strategy
        "critic": "or-free-llama4-maverick",
        "max_iterations": 5,
    },
    TaskType.DATA_ANALYSIS: {
        "primary": "or-free-qwen-coder",  # Good with data/code/tables
        "critic": "or-free-deepseek-chat",
        "max_iterations": 6,
    },
    TaskType.PROJECT_MANAGEMENT: {
        "primary": "or-free-llama4-maverick",
        "critic": "or-free-gemma-27b",
        "max_iterations": 4,
    },
    TaskType.APP_CREATE: {
        "primary": "or-free-qwen-coder",  # Qwen3 Coder — best for full-stack app generation
        "critic": "or-free-deepseek-r1",  # DeepSeek R1 — thorough code review
        "max_iterations": 12,  # Apps need more iterations to build fully
    },
    TaskType.APP_UPDATE: {
        "primary": "or-free-qwen-coder",
        "critic": "or-free-devstral",  # Devstral — multi-file awareness for updates
        "max_iterations": 8,
    },
    TaskType.PROJECT_SETUP: {
        "primary": "or-free-llama4-maverick",  # Strong conversational + structured output
        "critic": "or-free-deepseek-chat",  # Second opinion on spec completeness
        "max_iterations": 3,  # Low — mostly conversation, not iteration-heavy
    },
}


class ModelRouter:
    """Free-first model router with admin overrides and dynamic ranking.

    Resolution order:
    1. Admin env var override: AGENT42_CODING_MODEL, AGENT42_CODING_CRITIC, etc.
    2. Dynamic routing: data-driven rankings from task outcomes + research
    3. Trial injection: unproven models tested on a small % of tasks
    4. Hardcoded FREE_ROUTING defaults (fallback)
    """

    def __init__(self, evaluator=None, routing_file: str = ""):
        self.registry = ProviderRegistry()
        self._evaluator = evaluator
        self._routing_file = routing_file or self._default_routing_file()
        self._dynamic_cache: dict | None = None
        self._dynamic_cache_mtime: float = 0.0

    @staticmethod
    def _default_routing_file() -> str:
        """Resolve default routing file path from config."""
        try:
            from core.config import settings

            return str(Path(settings.model_routing_file))
        except Exception:
            return "data/dynamic_routing.json"

    def get_routing(self, task_type: TaskType, context_window: str = "default") -> dict:
        """Return the model routing config, applying the full resolution chain.

        When context_window is "large" or "max", prefer models with larger
        context windows (e.g. Gemini Flash 1M) over the default task-type model.
        """
        # 1. Admin env var override — always wins
        override = self._check_admin_override(task_type)
        if override:
            logger.info("Admin override for %s: %s", task_type.value, override)
            return override

        # 2. Dynamic routing from outcome tracking + research
        dynamic = self._check_dynamic_routing(task_type)
        if dynamic:
            logger.info(
                "Dynamic routing for %s: primary=%s (confidence=%.2f, n=%d)",
                task_type.value,
                dynamic.get("primary", "?"),
                dynamic.get("confidence", 0),
                dynamic.get("sample_size", 0),
            )
            routing = dynamic.copy()
        else:
            # 4. Hardcoded free defaults
            routing = FREE_ROUTING.get(task_type, FREE_ROUTING[TaskType.CODING]).copy()

        # 3. Trial injection — maybe swap primary for an unproven model
        trial_model = self._check_trial(task_type)
        if trial_model:
            logger.info(
                "Trial model injected for %s: %s (replacing %s)",
                task_type.value,
                trial_model,
                routing.get("primary", "?"),
            )
            routing["primary"] = trial_model

        # Context window adaptation
        if context_window == "max":
            large_models = self.registry.models_by_min_context(500_000)
            free_large = [m for m in large_models if m["tier"] == "free"]
            if free_large:
                routing["primary"] = free_large[0]["key"]
        elif context_window == "large":
            large_models = self.registry.models_by_min_context(200_000)
            free_large = [m for m in large_models if m["tier"] == "free"]
            if free_large:
                routing["primary"] = free_large[0]["key"]

        return routing

    def record_outcome(
        self,
        model_key: str,
        task_type: str,
        success: bool,
        iterations: int,
        max_iterations: int,
        critic_score: float | None = None,
    ):
        """Record a task outcome for model evaluation.

        Delegates to the ModelEvaluator if one is configured.
        """
        if self._evaluator:
            self._evaluator.record_outcome(
                model_key=model_key,
                task_type=task_type,
                success=success,
                iterations=iterations,
                max_iterations=max_iterations,
                critic_score=critic_score,
            )

    def _check_admin_override(self, task_type: TaskType) -> dict | None:
        """Check if the admin has set env vars to override model routing.

        Env var pattern:
            AGENT42_CODING_MODEL=claude-sonnet
            AGENT42_CODING_CRITIC=gpt-4o
            AGENT42_CODING_MAX_ITER=5
        """
        prefix = f"AGENT42_{task_type.value.upper()}"
        primary = os.getenv(f"{prefix}_MODEL")
        if not primary:
            return None

        return {
            "primary": primary,
            "critic": os.getenv(f"{prefix}_CRITIC"),
            "max_iterations": int(os.getenv(f"{prefix}_MAX_ITER", "8")),
        }

    def _check_dynamic_routing(self, task_type: TaskType) -> dict | None:
        """Load dynamic routing from the routing file if it exists.

        Caches the file contents and only re-reads when mtime changes.
        """
        routing_path = Path(self._routing_file)
        if not routing_path.exists():
            return None

        try:
            mtime = routing_path.stat().st_mtime
            if mtime != self._dynamic_cache_mtime or self._dynamic_cache is None:
                self._dynamic_cache = json.loads(routing_path.read_text())
                self._dynamic_cache_mtime = mtime
        except Exception as e:
            logger.debug("Failed to read dynamic routing file: %s", e)
            return None

        routing = self._dynamic_cache.get("routing", {})
        task_routing = routing.get(task_type.value)
        if task_routing and task_routing.get("primary"):
            return task_routing

        return None

    def _check_trial(self, task_type: TaskType) -> str | None:
        """Maybe inject a trial model for evaluation."""
        if not self._evaluator:
            return None

        free_keys = [m["key"] for m in self.registry.free_models()]
        return self._evaluator.select_trial_model(task_type.value, free_keys)

    async def complete(
        self,
        model_key: str,
        messages: list[dict],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> tuple[str, dict | None]:
        """Send a chat completion request and return (response_text, usage_dict)."""
        return await self.registry.complete(
            model_key, messages, temperature=temperature, max_tokens=max_tokens
        )

    async def complete_with_tools(
        self,
        model_key: str,
        messages: list[dict],
        tools: list[dict],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ):
        """Send a chat completion with tool schemas and return the full response.

        Returns the raw response object so the caller can inspect tool_calls.
        Spending limits are enforced by the registry.
        """
        return await self.registry.complete_with_tools(
            model_key,
            messages,
            tools,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def available_providers(self) -> list[dict]:
        """List all providers and their availability."""
        return self.registry.available_providers()

    def available_models(self) -> list[dict]:
        """List all registered models."""
        return self.registry.available_models()

    def free_models(self) -> list[dict]:
        """List all free ($0) models."""
        return self.registry.free_models()
