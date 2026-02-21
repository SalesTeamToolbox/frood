"""
Model router — maps task types to the best model for the job.

Free-first strategy: uses free models (OpenRouter, NVIDIA, Groq) for bulk
agent work. Premium models only used when admin explicitly configures them
for specific task types or for final reviews.

Routing priority:
  1. Admin override (TASK_TYPE_MODEL env var) — always wins
  2. OpenRouter free models (single API key, broadest free catalog)
  3. NVIDIA / Groq free tier (dedicated free tier providers)
  4. Fallback to premium only if configured by admin
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
        "critic": "or-free-deepseek-r1",        # DeepSeek R1 — strong free reasoner
        "max_iterations": 8,
    },
    TaskType.DEBUGGING: {
        "primary": "or-free-deepseek-r1",       # DeepSeek R1 — reasoning for root cause
        "critic": "or-free-qwen-coder",         # Qwen coder to verify fix
        "max_iterations": 10,
    },
    TaskType.RESEARCH: {
        "primary": "or-free-llama-70b",         # Llama 70B — strong general
        "critic": "or-free-deepseek-chat",      # DeepSeek Chat for second opinion
        "max_iterations": 5,
    },
    TaskType.REFACTORING: {
        "primary": "or-free-qwen-coder",
        "critic": "or-free-deepseek-r1",
        "max_iterations": 8,
    },
    TaskType.DOCUMENTATION: {
        "primary": "or-free-llama-70b",
        "critic": "or-free-nemotron",
        "max_iterations": 4,
    },
    TaskType.MARKETING: {
        "primary": "or-free-llama-70b",
        "critic": "or-free-deepseek-chat",
        "max_iterations": 6,
    },
    TaskType.EMAIL: {
        "primary": "or-free-deepseek-chat",
        "critic": None,
        "max_iterations": 3,
    },
}

# Legacy routing using NVIDIA/Groq directly (for users with those API keys)
NVIDIA_GROQ_ROUTING: dict[TaskType, dict] = {
    TaskType.CODING: {
        "primary": "qwen-coder-32b",
        "critic": "deepseek-r1",
        "max_iterations": 8,
    },
    TaskType.DEBUGGING: {
        "primary": "deepseek-r1",
        "critic": "qwen-coder-32b",
        "max_iterations": 10,
    },
    TaskType.RESEARCH: {
        "primary": "llama-405b",
        "critic": "mistral-large",
        "max_iterations": 5,
    },
    TaskType.REFACTORING: {
        "primary": "qwen-coder-32b",
        "critic": "deepseek-r1",
        "max_iterations": 8,
    },
    TaskType.DOCUMENTATION: {
        "primary": "llama-70b",
        "critic": "groq-mixtral",
        "max_iterations": 4,
    },
    TaskType.MARKETING: {
        "primary": "llama-405b",
        "critic": "groq-mixtral",
        "max_iterations": 6,
    },
    TaskType.EMAIL: {
        "primary": "mistral-large",
        "critic": None,
        "max_iterations": 3,
    },
}


class ModelRouter:
    """Free-first model router with admin overrides.

    Resolution order:
    1. Admin env var override: AGENT42_CODING_MODEL, AGENT42_CODING_CRITIC, etc.
    2. OpenRouter free tier (if OPENROUTER_API_KEY is set)
    3. NVIDIA/Groq free tier (if their API keys are set)
    4. Whatever is available
    """

    def __init__(self):
        self.registry = ProviderRegistry()

    def get_routing(self, task_type: TaskType) -> dict:
        """Return the model routing config, applying free-first strategy."""
        # Check for admin override via env vars
        override = self._check_admin_override(task_type)
        if override:
            logger.info(f"Admin override for {task_type.value}: {override}")
            return override

        # Prefer OpenRouter free (single key, broadest free catalog)
        if os.getenv("OPENROUTER_API_KEY"):
            return FREE_ROUTING.get(task_type, FREE_ROUTING[TaskType.CODING])

        # Fall back to NVIDIA/Groq direct
        if os.getenv("NVIDIA_API_KEY") or os.getenv("GROQ_API_KEY"):
            return NVIDIA_GROQ_ROUTING.get(task_type, NVIDIA_GROQ_ROUTING[TaskType.CODING])

        # Last resort: OpenRouter free routing (will warn about missing key)
        return FREE_ROUTING.get(task_type, FREE_ROUTING[TaskType.CODING])

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

    def available_providers(self) -> list[dict]:
        """List all providers and their availability."""
        return self.registry.available_providers()

    def available_models(self) -> list[dict]:
        """List all registered models."""
        return self.registry.available_models()

    def free_models(self) -> list[dict]:
        """List all free ($0) models."""
        return self.registry.free_models()
