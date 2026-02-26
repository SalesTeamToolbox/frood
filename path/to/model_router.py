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

from core.config import settings  # Added import
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
        "primary": "or-free-llama-70b",  # Llama 3.3 70B — reliable general-purpose
        "critic": "or-free-deepseek-chat",  # DeepSeek Chat for second opinion
        "max_iterations": 5,
    },
    TaskType.REFACTORING: {
        "primary": "or-free-qwen-coder",  # Qwen3 Coder — best for code changes
        "critic": "or-free-devstral",  # Devstral — multi-file project awareness
        "max_iterations": 8,
    },
    TaskType.DOCUMENTATION: {
        "primary": "or-free-llama-70b",  # Llama 3.3 70B — reliable general-purpose writing
        "critic": "or-free-gemma-27b",  # Gemma 27B — fast verification
        "max_iterations": 4,
    },
    TaskType.MARKETING: {
        "primary": "or-free-llama-70b",  # Llama 3.3 70B — creative + general
        "critic": "or-free-deepseek-chat",  # DeepSeek Chat v3.1
        "max_iterations": 6,
    },
    TaskType.EMAIL: {
        "primary": "or-free-mistral-small",  # Mistral Small 3.1 — fast + precise
        "critic": None,
        "max_iterations": 3,
    },
    TaskType.DESIGN: {
        "primary": "or-free-llama-70b",  # Llama 3.3 70B — strong visual/creative reasoning
        "critic": "or-free-deepseek-chat",
        "max_iterations": 5,
    },
    TaskType.CONTENT: {
        "primary": "or-free-llama-70b",  # Llama 3.3 70B — reliable general-purpose writing
        "critic": "or-free-gemma-27b",  # Fast editorial check
        "max_iterations": 6,
    },
    TaskType.STRATEGY: {
        "primary": "or-free-deepseek-r1",  # Deep reasoning for strategy
        "critic": "or-free-deepseek-chat",  # Alternative perspective on strategy
        "max_iterations": 5,
    },
    TaskType.DATA_ANALYSIS: {
        "primary": "or-free-qwen-coder",  # Good with data/code/tables
        "critic": "or-free-deepseek-chat",
        "max_iterations": 6,
    },
    TaskType.PROJECT_MANAGEMENT: {
        "primary": "or-free-llama-70b",  # Llama 3.3 70B — reliable general-purpose
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
        "primary": "or-free-llama-70b",  # Llama 3.3 70B — conversational + structured output
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
            routing = override
        else:
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
                # 4. Hardcoded free defaults (fallback)
                fallback = FREE_ROUTING.get(task_type)
                routing = fallback.copy() if fallback else FREE_ROUTING[TaskType.CODING].copy()

                # Ensure provider API key is set for this model
                primary_model = routing.get("primary")
                if primary_model:
                    try:
                        spec = self.registry.get_model(primary_model)
                        provider = spec.provider
                        api_key_field = f"{provider.value.lower()}_api_key"
                        api_key = getattr(settings, api_key_field, "")
                        if not api_key:
                            # Try to find any free model that has provider API key set
                            for model in self.registry.free_models():
                                try:
                                    spec = self.registry.get_model(model["key"])
                                    provider = spec.provider
                                    api_key_field = f"{provider.value.lower()}_api_key"
                                    api_key = getattr(settings, api_key_field, "")
                                    if api_key:
                                        routing["primary"] = model["key"]
                                        logger.info(f"Fell back to free model {model['key']}")
                                        break
                                except ValueError:
                                    continue
                            else:
                                raise ValueError(
                                    f"No available free model found for {task_type.value}. "
                                    "Please configure API keys for providers."
                                )
                    except ValueError:
                        # Model not found in registry, try to find any free model with API key
                        for model in self.registry.free_models():
                            try:
                                spec = self.registry.get_model(model["key"])
                                provider = spec.provider
                                api_key_field = f"{provider.value.lower()}_api_key"
                                api_key = getattr(settings, api_key_field, "")
                                if api_key:
                                    routing["primary"] = model["key"]
                                    logger.info(f"Fell back to free model {model['key']}")
                                    break
                            except ValueError:
                                continue
                        else:
                            raise ValueError(
                                f"No available free model found for {task_type.value}. "
                                "Please configure API keys for providers."
                            )

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

        # After all modifications, ensure the primary model is available (in registry and API key set)
        primary_model = routing.get("primary")
        if primary_model:
            try:
                spec = self.registry.get_model(primary_model)
                provider = spec.provider
                api_key_field = f"{provider.value.lower()}_api_key"
                api_key = getattr(settings, api_key_field, "")
                if not api_key:
                    raise ValueError(f"API key {api_key_field} not set for provider {provider.value}")
            except ValueError as e:
                logger.warning(
                    f"Model {primary_model} is not available: {e}. "
                    "Attempting to find a fallback free model."
                )
                # Try to find any free model that is available
                for model in self.registry.free_models():
                    try:
                        spec = self.registry.get_model(model["key"])
                        provider = spec.provider
                        api_key_field = f"{provider.value.lower()}_api_key"
                        api_key = getattr(settings, api_key_field, "")
                        if api_key:
                            routing["primary"] = model["key"]
                            logger.info(f"Fell back to free model {model['key']}")
                            break
                    except ValueError:
                        continue
                else:
                    # No free model with API key found, use the task type's free routing as last resort
                    fallback = FREE_ROUTING.get(task_type)
                    routing = (
                        fallback.copy()
                        if fallback
                        else FREE_ROUTING[TaskType.CODING].copy()
                    )
                    logger.error(
                        f"No available free model found for {task_type.value}. "
                        "Using fallback routing, but it may fail."
                    )

        return routing

    # ... (rest of the class remains unchanged)
