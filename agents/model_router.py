"""
Model router — maps task types to the best free model for the job.

Primary models do the iterative work. Critic models provide independent
second-opinion passes. All models are accessed via OpenAI-compatible APIs.
"""

import logging
from dataclasses import dataclass
from enum import Enum

from openai import AsyncOpenAI

from core.config import settings
from core.task_queue import TaskType

logger = logging.getLogger("agent42.router")


class Provider(str, Enum):
    NVIDIA = "nvidia"
    GROQ = "groq"


@dataclass(frozen=True)
class ModelSpec:
    """A specific model on a specific provider."""
    model_id: str
    provider: Provider
    max_tokens: int = 4096
    temperature: float = 0.3


# -- Model catalog -------------------------------------------------------------
MODELS = {
    # NVIDIA hosted
    "qwen-coder-32b": ModelSpec("qwen/qwen2.5-coder-32b-instruct", Provider.NVIDIA),
    "deepseek-r1": ModelSpec("deepseek/deepseek-r1", Provider.NVIDIA, temperature=0.2),
    "llama-405b": ModelSpec("meta/llama-3.1-405b-instruct", Provider.NVIDIA),
    "llama-70b": ModelSpec("meta/llama-3.3-70b-instruct", Provider.NVIDIA),
    "mistral-large": ModelSpec("mistralai/mistral-large-2-instruct", Provider.NVIDIA),
    # Groq hosted (faster inference)
    "groq-llama-70b": ModelSpec("llama-3.3-70b-versatile", Provider.GROQ),
    "groq-mixtral": ModelSpec("mixtral-8x7b-32768", Provider.GROQ),
}


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


def _build_client(provider: Provider) -> AsyncOpenAI:
    """Create an OpenAI-compatible async client for the given provider."""
    if provider == Provider.NVIDIA:
        return AsyncOpenAI(
            base_url=settings.nvidia_base_url,
            api_key=settings.nvidia_api_key,
        )
    elif provider == Provider.GROQ:
        return AsyncOpenAI(
            base_url=settings.groq_base_url,
            api_key=settings.groq_api_key,
        )
    raise ValueError(f"Unknown provider: {provider}")


class ModelRouter:
    """Resolves task types to model clients and handles completion calls."""

    def __init__(self):
        self._clients: dict[Provider, AsyncOpenAI] = {}

    def _get_client(self, provider: Provider) -> AsyncOpenAI:
        if provider not in self._clients:
            self._clients[provider] = _build_client(provider)
        return self._clients[provider]

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
        spec = MODELS.get(model_key)
        if not spec:
            raise ValueError(f"Unknown model: {model_key}")

        client = self._get_client(spec.provider)

        response = await client.chat.completions.create(
            model=spec.model_id,
            messages=messages,
            temperature=temperature if temperature is not None else spec.temperature,
            max_tokens=max_tokens or spec.max_tokens,
        )

        content = response.choices[0].message.content or ""
        logger.info(
            f"Completion from {model_key}: "
            f"{response.usage.prompt_tokens}+{response.usage.completion_tokens} tokens"
        )
        return content
