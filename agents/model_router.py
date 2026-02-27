"""
Model router — maps task types to the best model for the job.

Free-first strategy: uses OpenRouter free models for bulk agent work.
Premium models only used when admin explicitly configures them for
specific task types or for final reviews.

Routing priority:
  1. Admin override (TASK_TYPE_MODEL env var) — always wins
  2. Dynamic routing (from outcome tracking + research) — data-driven
  3. Trial model injection (small % of tasks) — evaluates new models
  4. Policy routing (balanced/performance) — upgrades when credits available
  5. OpenRouter free models (hardcoded defaults) — fallback
"""

import json
import logging
import os
from pathlib import Path

from core.task_queue import TaskType
from providers.registry import PROVIDERS, ProviderRegistry

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


# Task types complex enough to justify paid models in "balanced" mode
_COMPLEX_TASK_TYPES = frozenset(
    {
        TaskType.CODING,
        TaskType.DEBUGGING,
        TaskType.APP_CREATE,
        TaskType.APP_UPDATE,
        TaskType.REFACTORING,
        TaskType.STRATEGY,
        TaskType.DATA_ANALYSIS,
    }
)
_VALID_POLICIES = frozenset({"free_only", "balanced", "performance"})


class ModelRouter:
    """Free-first model router with admin overrides and dynamic ranking.

    Resolution order:
    1. Admin env var override: AGENT42_CODING_MODEL, AGENT42_CODING_CRITIC, etc.
    2. Dynamic routing: data-driven rankings from task outcomes + research
    3. Trial injection: unproven models tested on a small % of tasks
    4. Policy routing: balanced/performance — upgrades when OR credits available
    5. Hardcoded FREE_ROUTING defaults (fallback)
    """

    def __init__(self, evaluator=None, routing_file: str = "", catalog=None):
        self.registry = ProviderRegistry()
        self._evaluator = evaluator
        self._catalog = catalog  # May be None; policy routing skips gracefully
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
        # 1. Admin env var override — always wins; skip API key validation for explicit overrides
        override = self._check_admin_override(task_type)
        is_admin_override = override is not None
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
                # 5. Hardcoded free defaults
                routing = FREE_ROUTING.get(task_type, FREE_ROUTING[TaskType.CODING]).copy()

        # 4. Policy routing — upgrade to paid models when credits are available
        if not is_admin_override and not dynamic:
            policy_routing = self._check_policy_routing(task_type)
            if policy_routing:
                routing = policy_routing

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

        # For known registry models (not admin overrides), verify the provider API key is set.
        # Use os.getenv() — not getattr(settings, ...) — so admin-configured keys are visible.
        # settings is a frozen dataclass set at import time, before KeyStore.inject_into_environ().
        # Unknown models (dynamic/catalog, not in MODELS dict) pass through without validation.
        primary_model = routing.get("primary")
        if primary_model and not is_admin_override:
            try:
                spec = self.registry.get_model(primary_model)
                # Model is known — check that its provider API key is actually set
                provider_spec = PROVIDERS.get(spec.provider)
                api_key = os.getenv(provider_spec.api_key_env, "") if provider_spec else ""
                if not api_key:
                    raise ValueError(
                        f"API key {provider_spec.api_key_env if provider_spec else '?'} "
                        f"not set for provider {spec.provider.value}"
                    )
            except ValueError as e:
                if "Unknown model" in str(e):
                    # Model not in registry (e.g. dynamic/catalog model) — pass through
                    pass
                else:
                    logger.warning(
                        f"Model {primary_model} is not available: {e}. "
                        "Attempting to find a fallback free model."
                    )
                    # Try to find any free model that is available
                    for model in self.registry.free_models():
                        try:
                            spec = self.registry.get_model(model["key"])
                            provider_spec = PROVIDERS.get(spec.provider)
                            api_key = (
                                os.getenv(provider_spec.api_key_env, "") if provider_spec else ""
                            )
                            if api_key:
                                routing["primary"] = model["key"]
                                logger.info(f"Fell back to free model {model['key']}")
                                break
                        except ValueError:
                            continue
                    else:
                        # No free model with API key found — use task-type default as last resort
                        fallback = FREE_ROUTING.get(task_type)
                        routing = (
                            fallback.copy() if fallback else FREE_ROUTING[TaskType.CODING].copy()
                        )
                        logger.error(
                            f"No available free model found for {task_type.value}. "
                            "Using fallback routing, but it may fail."
                        )

        return routing

    def _check_policy_routing(self, task_type: TaskType) -> dict | None:
        """Apply policy-based routing when OR credits are available.

        Returns a routing dict to use instead of FREE_ROUTING defaults,
        or None to keep the default.
        """
        try:
            from core.config import settings

            policy = settings.model_routing_policy
        except Exception:
            policy = os.getenv("MODEL_ROUTING_POLICY", "balanced")

        if policy not in _VALID_POLICIES:
            logger.warning("Unknown routing policy %r — treating as 'balanced'", policy)
            policy = "balanced"

        if policy == "free_only":
            return None

        if self._catalog is None:
            return None

        account = self._catalog.openrouter_account_status
        if account is None:
            return None

        if policy == "balanced":
            if task_type not in _COMPLEX_TASK_TYPES:
                return None
            if account.get("is_free_tier", True):
                return None
            limit_remaining = account.get("limit_remaining")
            if limit_remaining is not None and limit_remaining <= 0:
                return None
            return self._select_best_paid_model(task_type)

        if policy == "performance":
            if account.get("is_free_tier", True):
                return None
            limit_remaining = account.get("limit_remaining")
            if limit_remaining is not None and limit_remaining <= 0:
                return None
            return self._select_best_available_model(task_type)

        return None

    def _get_best_free_score(self, task_type: TaskType) -> float:
        """Get the best composite score among free models for a task type."""
        if not self._evaluator:
            return 0.5
        free_keys = {m["key"] for m in self.registry.free_models()}
        best = 0.5
        for (mk, tt), stats in self._evaluator._stats.items():
            if tt == task_type.value and mk in free_keys:
                score = stats.composite_score
                if score > best:
                    best = score
        return best

    def _select_best_paid_model(self, task_type: TaskType) -> dict | None:
        """Select the best paid OR model if it's significantly better than free."""
        from providers.registry import MODELS

        paid_keys = [k for k in MODELS if k.startswith("or-paid-")]
        if not paid_keys:
            return None

        best_key = None
        best_score = 0.0
        for key in paid_keys:
            spec = MODELS[key]
            score = self._get_model_score(key, task_type, spec.tier)
            if score > best_score:
                best_score = score
                best_key = key

        if not best_key:
            return None

        free_score = self._get_best_free_score(task_type)
        if best_score <= free_score + 0.1:
            return None  # Not significantly better — stay free

        free_default = FREE_ROUTING.get(task_type, FREE_ROUTING[TaskType.CODING])
        logger.info(
            "Policy routing (balanced): upgrading %s to %s (score=%.2f vs free=%.2f)",
            task_type.value,
            best_key,
            best_score,
            free_score,
        )
        return {
            "primary": best_key,
            "critic": free_default.get("critic"),
            "max_iterations": free_default.get("max_iterations", 8),
        }

    def _select_best_available_model(self, task_type: TaskType) -> dict | None:
        """Select the best model across all available providers."""
        from providers.registry import MODELS

        best_key = None
        best_score = 0.0
        for key, spec in MODELS.items():
            provider_spec = PROVIDERS.get(spec.provider)
            if not provider_spec:
                continue
            api_key = os.getenv(provider_spec.api_key_env, "")
            if not api_key:
                continue
            score = self._get_model_score(key, task_type, spec.tier)
            if score > best_score:
                best_score = score
                best_key = key

        if not best_key:
            return None

        free_default = FREE_ROUTING.get(task_type, FREE_ROUTING[TaskType.CODING])
        logger.info(
            "Policy routing (performance): %s → %s (score=%.2f)",
            task_type.value,
            best_key,
            best_score,
        )
        return {
            "primary": best_key,
            "critic": free_default.get("critic"),
            "max_iterations": free_default.get("max_iterations", 8),
        }

    def _get_model_score(self, key: str, task_type: TaskType, tier) -> float:
        """Get composite score for a model, falling back to tier-based estimate."""
        from providers.registry import ModelTier

        if self._evaluator:
            stats = self._evaluator._stats.get((key, task_type.value))
            if stats and stats.composite_score > 0:
                return stats.composite_score
        # Tier-based default scores
        return {ModelTier.PREMIUM: 0.7, ModelTier.CHEAP: 0.5, ModelTier.FREE: 0.3}.get(tier, 0.3)

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
