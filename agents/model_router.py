"""
Model router — maps task types to the best model for the job.

Free-first strategy: uses OpenRouter free models for bulk agent work.
Premium models only used when admin explicitly configures them for
specific task types or for final reviews.

Routing priority:
  1. Admin override (TASK_TYPE_MODEL env var) — always wins
  2. OpenRouter free models (single API key, broadest free catalog)
  3. Fallback to premium only if configured by admin
"""

import logging
import os

from core.task_queue import TaskType
from providers.registry import ProviderRegistry, ModelTier

logger = logging.getLogger("agent42.router")


# -- Default routing: free models for everything ------------------------------
# These are the defaults when no admin override is set.
# OpenRouter free models are preferred as they need only one API key.

FREE_ROUTING: dict[TaskType, dict] = {
    TaskType.CODING: {
        "primary": "or-free-qwen-coder",       # Qwen3 Coder 480B — strongest free coder
        "critic": "or-free-deepseek-r1",        # DeepSeek R1 0528 — best free reasoner
        "max_iterations": 8,
    },
    TaskType.DEBUGGING: {
        "primary": "or-free-deepseek-r1",       # DeepSeek R1 — reasoning for root cause
        "critic": "or-free-devstral",            # Devstral 123B — multi-file awareness
        "max_iterations": 10,
    },
    TaskType.RESEARCH: {
        "primary": "or-free-llama4-maverick",   # Llama 4 Maverick — GPT-4+ level
        "critic": "or-free-deepseek-chat",      # DeepSeek Chat for second opinion
        "max_iterations": 5,
    },
    TaskType.REFACTORING: {
        "primary": "or-free-qwen-coder",        # Qwen3 Coder — best for code changes
        "critic": "or-free-devstral",            # Devstral — multi-file project awareness
        "max_iterations": 8,
    },
    TaskType.DOCUMENTATION: {
        "primary": "or-free-llama4-maverick",   # Llama 4 — strong writing
        "critic": "or-free-gemma-27b",           # Gemma 27B — fast verification
        "max_iterations": 4,
    },
    TaskType.MARKETING: {
        "primary": "or-free-llama4-maverick",   # Llama 4 — creative + general
        "critic": "or-free-deepseek-chat",      # DeepSeek Chat v3.1
        "max_iterations": 6,
    },
    TaskType.EMAIL: {
        "primary": "or-free-mistral-small",     # Mistral Small 3.1 — fast + precise
        "critic": None,
        "max_iterations": 3,
    },
    TaskType.DESIGN: {
        "primary": "or-free-llama4-maverick",   # Strong visual/creative reasoning
        "critic": "or-free-deepseek-chat",
        "max_iterations": 5,
    },
    TaskType.CONTENT: {
        "primary": "or-free-llama4-maverick",   # Best free model for writing
        "critic": "or-free-gemma-27b",          # Fast editorial check
        "max_iterations": 6,
    },
    TaskType.STRATEGY: {
        "primary": "or-free-deepseek-r1",       # Deep reasoning for strategy
        "critic": "or-free-llama4-maverick",
        "max_iterations": 5,
    },
    TaskType.DATA_ANALYSIS: {
        "primary": "or-free-qwen-coder",        # Good with data/code/tables
        "critic": "or-free-deepseek-chat",
        "max_iterations": 6,
    },
    TaskType.PROJECT_MANAGEMENT: {
        "primary": "or-free-llama4-maverick",
        "critic": "or-free-gemma-27b",
        "max_iterations": 4,
    },
}


class ModelRouter:
    """Free-first model router with admin overrides.

    Resolution order:
    1. Admin env var override: AGENT42_CODING_MODEL, AGENT42_CODING_CRITIC, etc.
    2. OpenRouter free tier (default — single API key covers everything)
    """

    def __init__(self):
        self.registry = ProviderRegistry()

    def get_routing(self, task_type: TaskType, context_window: str = "default") -> dict:
        """Return the model routing config, applying free-first strategy.

        When context_window is "large" or "max", prefer models with larger
        context windows (e.g. Gemini Flash 1M) over the default task-type model.
        """
        # Check for admin override via env vars
        override = self._check_admin_override(task_type)
        if override:
            logger.info(f"Admin override for {task_type.value}: {override}")
            return override

        routing = FREE_ROUTING.get(task_type, FREE_ROUTING[TaskType.CODING]).copy()

        # If task requests large/max context, prefer models with large context windows
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

    async def complete(
        self,
        model_key: str,
        messages: list[dict],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """Send a chat completion request and return the response text."""
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
        """
        spec = self.registry.get_model(model_key)
        client = self.registry.get_client(spec.provider)

        kwargs = {
            "model": spec.model_id,
            "messages": messages,
            "temperature": temperature if temperature is not None else spec.temperature,
            "max_tokens": max_tokens or spec.max_tokens,
        }
        if tools:
            kwargs["tools"] = tools

        response = await client.chat.completions.create(**kwargs)
        return response

    def available_providers(self) -> list[dict]:
        """List all providers and their availability."""
        return self.registry.available_providers()

    def available_models(self) -> list[dict]:
        """List all registered models."""
        return self.registry.available_models()

    def free_models(self) -> list[dict]:
        """List all free ($0) models."""
        return self.registry.free_models()
