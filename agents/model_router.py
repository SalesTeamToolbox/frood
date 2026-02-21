"""
Model router — maps task types to the best model for the job.

Primary models do the iterative work. Critic models provide independent
second-opinion passes. Now delegates to the ProviderRegistry (Phase 5)
for client management and supports 8 providers with 20+ models.
"""

import logging

from core.task_queue import TaskType
from providers.registry import ProviderRegistry

logger = logging.getLogger("agent42.router")


# -- Task type -> model mapping ------------------------------------------------
TASK_ROUTING: dict[TaskType, dict] = {
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
    """Resolves task types to model clients and handles completion calls.

    Delegates to ProviderRegistry for client management and completion.
    Supports NVIDIA, Groq, OpenAI, Anthropic, DeepSeek, Gemini, OpenRouter, vLLM.
    """

    def __init__(self):
        self.registry = ProviderRegistry()

    def get_routing(self, task_type: TaskType) -> dict:
        """Return the model routing config for a task type."""
        return TASK_ROUTING.get(task_type, TASK_ROUTING[TaskType.CODING])

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
