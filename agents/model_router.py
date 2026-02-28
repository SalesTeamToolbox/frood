"""
Model router — maps task types to the best model for the job.

Free-first strategy: uses Gemini free tier as the base LLM (generous
free quota), with OpenRouter free models as secondary and paid models
as optional upgrades when the admin configures them.

Routing priority:
  1. Admin override (TASK_TYPE_MODEL env var) — always wins
  2. Dynamic routing (from outcome tracking + research) — data-driven
  3. Trial model injection (small % of tasks) — evaluates new models
  4. Policy routing (balanced/performance) — upgrades when OR credits available
  5. Hardcoded defaults: Gemini free → OR free models (fallback)
"""

import json
import logging
import os
from pathlib import Path

from core.task_queue import TaskType
from providers.registry import PROVIDERS, ProviderRegistry

logger = logging.getLogger("agent42.router")


# -- Default routing: free models for everything ------------------------------
# Uses Gemini free tier as the base (generous free quota: 1500 RPD for Flash,
# 50 RPD for Pro). OpenRouter free models serve as critic / secondary to
# distribute load across providers. The get_routing() validation automatically
# falls back to OR free models if GEMINI_API_KEY is not set.

FREE_ROUTING: dict[TaskType, dict] = {
    TaskType.CODING: {
        "primary": "gemini-2-flash",  # Gemini Flash — fast, 1M context, generous free tier
        "critic": "or-free-qwen-coder",  # Qwen3 Coder 480B — code-aware second opinion
        "max_iterations": 8,
    },
    TaskType.DEBUGGING: {
        "primary": "gemini-2-flash",  # Gemini Flash — fast reasoning + 1M context for large codebases
        "critic": "or-free-qwen-coder",  # Qwen3 Coder — multi-file awareness
        "max_iterations": 10,
    },
    TaskType.RESEARCH: {
        "primary": "gemini-2-flash",  # Gemini Flash — strong general-purpose
        "critic": "or-free-llama-70b",  # Llama 3.3 70B — second opinion
        "max_iterations": 5,
    },
    TaskType.REFACTORING: {
        "primary": "gemini-2-flash",  # Gemini Flash — code-capable + 1M context
        "critic": "or-free-qwen-coder",  # Qwen3 Coder — multi-file project awareness
        "max_iterations": 8,
    },
    TaskType.DOCUMENTATION: {
        "primary": "gemini-2-flash",  # Gemini Flash — reliable general-purpose writing
        "critic": "or-free-gemma-27b",  # Gemma 27B — fast verification
        "max_iterations": 4,
    },
    TaskType.MARKETING: {
        "primary": "gemini-2-flash",  # Gemini Flash — creative + general
        "critic": "or-free-llama-70b",  # Llama 3.3 70B — second opinion
        "max_iterations": 6,
    },
    TaskType.EMAIL: {
        "primary": "gemini-2-flash",  # Gemini Flash — fast + precise
        "critic": None,
        "max_iterations": 3,
    },
    TaskType.DESIGN: {
        "primary": "gemini-2-flash",  # Gemini Flash — visual/creative reasoning
        "critic": "or-free-llama-70b",
        "max_iterations": 5,
    },
    TaskType.CONTENT: {
        "primary": "gemini-2-flash",  # Gemini Flash — reliable writing
        "critic": "or-free-gemma-27b",  # Fast editorial check
        "max_iterations": 6,
    },
    TaskType.STRATEGY: {
        "primary": "gemini-2-flash",  # Gemini Flash — strong reasoning
        "critic": "or-free-llama-70b",  # Alternative perspective on strategy
        "max_iterations": 5,
    },
    TaskType.DATA_ANALYSIS: {
        "primary": "gemini-2-flash",  # Gemini Flash — good with data/code/tables
        "critic": "or-free-qwen-coder",  # Qwen Coder — data-aware reviewer
        "max_iterations": 6,
    },
    TaskType.PROJECT_MANAGEMENT: {
        "primary": "gemini-2-flash",  # Gemini Flash — reliable general-purpose
        "critic": "or-free-gemma-27b",
        "max_iterations": 4,
    },
    TaskType.APP_CREATE: {
        "primary": "gemini-2-flash",  # Gemini Flash — fast code generation + 1M context
        "critic": "or-free-qwen-coder",  # Qwen3 Coder — thorough code review
        "max_iterations": 12,  # Apps need more iterations to build fully
    },
    TaskType.APP_UPDATE: {
        "primary": "gemini-2-flash",  # Gemini Flash — 1M context for existing codebases
        "critic": "or-free-qwen-coder",  # Qwen3 Coder — multi-file awareness for updates
        "max_iterations": 8,
    },
    TaskType.PROJECT_SETUP: {
        "primary": "gemini-2-flash",  # Gemini Flash — conversational + structured output
        "critic": "or-free-llama-70b",  # Second opinion on spec completeness
        "max_iterations": 3,  # Low — mostly conversation, not iteration-heavy
    },
}


# -- L2 routing: premium models for senior review (suggested defaults) --------
# These are the suggested premium models for L2 review tasks. Admins can
# override per-task-type via AGENT42_L2_CODING_MODEL etc., or globally
# via L2_DEFAULT_MODEL. L2 runs review-and-refine passes, not full execution,
# so max_iterations are low. No critic needed — L2 IS the final reviewer.
# If the premium model's API key is not set, get_l2_routing() returns None
# and L2 escalation is disabled for that task type.

L2_ROUTING: dict[TaskType, dict] = {
    TaskType.CODING: {
        "primary": "claude-sonnet",  # Strong at code review and refinement
        "critic": None,
        "max_iterations": 3,
    },
    TaskType.DEBUGGING: {
        "primary": "claude-sonnet",  # Good at reasoning about subtle bugs
        "critic": None,
        "max_iterations": 3,
    },
    TaskType.RESEARCH: {
        "primary": "gpt-4o",  # Strong general reasoning
        "critic": None,
        "max_iterations": 2,
    },
    TaskType.REFACTORING: {
        "primary": "claude-sonnet",  # Careful about preserving behavior
        "critic": None,
        "max_iterations": 3,
    },
    TaskType.DOCUMENTATION: {
        "primary": "gpt-4o",  # Clear technical writing
        "critic": None,
        "max_iterations": 2,
    },
    TaskType.MARKETING: {
        "primary": "gpt-4o",  # Creative + persuasive
        "critic": None,
        "max_iterations": 2,
    },
    TaskType.EMAIL: {
        "primary": "gpt-4o",  # Concise professional writing
        "critic": None,
        "max_iterations": 2,
    },
    TaskType.DESIGN: {
        "primary": "gpt-4o",  # Visual reasoning
        "critic": None,
        "max_iterations": 2,
    },
    TaskType.CONTENT: {
        "primary": "gpt-4o",  # Strong writing
        "critic": None,
        "max_iterations": 2,
    },
    TaskType.STRATEGY: {
        "primary": "gpt-4o",  # Strategic analysis
        "critic": None,
        "max_iterations": 2,
    },
    TaskType.DATA_ANALYSIS: {
        "primary": "gpt-4o",  # Data reasoning
        "critic": None,
        "max_iterations": 2,
    },
    TaskType.PROJECT_MANAGEMENT: {
        "primary": "gpt-4o",  # Structured planning
        "critic": None,
        "max_iterations": 2,
    },
    TaskType.APP_CREATE: {
        "primary": "claude-sonnet",  # Strong at code generation review
        "critic": None,
        "max_iterations": 3,
    },
    TaskType.APP_UPDATE: {
        "primary": "claude-sonnet",  # Careful with existing codebases
        "critic": None,
        "max_iterations": 3,
    },
    TaskType.PROJECT_SETUP: {
        "primary": "gpt-4o",  # Conversational + structured
        "critic": None,
        "max_iterations": 2,
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

        # For known registry models (not admin overrides), verify the provider API key is set
        # and the model is healthy (not recently marked as 404/unavailable by health check).
        # Use os.getenv() — not getattr(settings, ...) — so admin-configured keys are visible.
        # settings is a frozen dataclass set at import time, before KeyStore.inject_into_environ().
        # Unknown models (dynamic/catalog, not in MODELS dict) pass through without validation.
        primary_model = routing.get("primary")
        if primary_model and not is_admin_override:
            # Health check gate: if the catalog knows this model is down, swap proactively
            if self._catalog and not self._catalog.is_model_healthy(primary_model):
                logger.warning(
                    "Model %s is unhealthy (health check), finding healthy alternative",
                    primary_model,
                )
                replacement = self._find_healthy_free_model(exclude={primary_model})
                if replacement:
                    routing["primary"] = replacement
                    primary_model = replacement

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
                    replacement = self._find_healthy_free_model(exclude={primary_model})
                    if replacement:
                        routing["primary"] = replacement
                        logger.info(f"Fell back to free model {replacement}")
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

    def _find_healthy_free_model(self, exclude: set[str] | None = None) -> str | None:
        """Find a free model that is both API-key-configured and health-check-healthy."""
        exclude = exclude or set()
        for model in self.registry.free_models():
            key = model["key"]
            if key in exclude:
                continue
            # Check health if catalog is available
            if self._catalog and not self._catalog.is_model_healthy(key):
                continue
            try:
                spec = self.registry.get_model(key)
                provider_spec = PROVIDERS.get(spec.provider)
                api_key = os.getenv(provider_spec.api_key_env, "") if provider_spec else ""
                if api_key:
                    return key
            except ValueError:
                continue
        return None

    def get_l2_routing(self, task_type: TaskType) -> dict | None:
        """Return L2 premium routing, or None if L2 is not configured/available.

        Resolution order:
        1. Per-task-type admin override: AGENT42_L2_CODING_MODEL, etc.
        2. Global admin override: L2_DEFAULT_MODEL
        3. Suggested L2 defaults from L2_ROUTING dict
        4. None — if the selected model's API key is not set

        Returns None if L2 is disabled or the premium model's API key is missing,
        which signals callers to hide L2 escalation options.
        """
        from core.config import settings

        if not settings.l2_enabled:
            return None

        # Check if this task type is eligible for L2
        if settings.l2_task_types:
            eligible = {t.strip() for t in settings.l2_task_types.split(",") if t.strip()}
            if task_type.value not in eligible:
                return None

        # 1. Per-task-type L2 admin override: AGENT42_L2_CODING_MODEL, etc.
        env_key = f"AGENT42_L2_{task_type.value.upper()}_MODEL"
        per_type_model = os.getenv(env_key, "")
        if per_type_model:
            logger.info(
                "L2 admin override for %s: %s (via %s)", task_type.value, per_type_model, env_key
            )
            return {
                "primary": per_type_model,
                "critic": None,
                "max_iterations": 3,
            }

        # 2. Global L2 admin override
        global_l2 = os.getenv("AGENT42_L2_MODEL", "") or settings.l2_default_model
        if global_l2:
            logger.info("L2 global override: %s", global_l2)
            return {
                "primary": global_l2,
                "critic": None,
                "max_iterations": 3,
            }

        # 3. Suggested L2 defaults
        routing = L2_ROUTING.get(task_type, L2_ROUTING[TaskType.CODING]).copy()

        # Verify the L2 model's API key is available
        primary = routing.get("primary")
        try:
            spec = self.registry.get_model(primary)
            provider_spec = PROVIDERS.get(spec.provider)
            if not os.getenv(provider_spec.api_key_env, ""):
                logger.debug(
                    "L2 model %s unavailable — API key %s not set",
                    primary,
                    provider_spec.api_key_env if provider_spec else "?",
                )
                return None  # Premium key not configured
        except ValueError:
            logger.debug("L2 model %s not in registry — skipping", primary)
            return None

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

    def get_rlm_models(self, task_type: TaskType) -> dict:
        """Return recommended root and sub models for RLM processing.

        RLM works best with code-capable models that can navigate the REPL
        environment.  Returns ``{"root": model_key, "sub": model_key}``.
        """
        from providers.rlm_provider import RLM_TIER_1, RLM_TIER_2

        routing = self.get_routing(task_type)
        primary = routing.get("primary", "")

        # If primary is already RLM-capable, use it as root
        if primary in RLM_TIER_1 or primary in RLM_TIER_2:
            root = primary
        else:
            # Select the best available RLM-capable model
            root = primary
            for candidate in ("or-free-qwen-coder", "gemini-2-flash", "gpt-4o-mini"):
                try:
                    spec = self.registry.get_model(candidate)
                    provider_spec = PROVIDERS.get(spec.provider)
                    if provider_spec and os.getenv(provider_spec.api_key_env, ""):
                        root = candidate
                        break
                except ValueError:
                    continue

        # Sub-model for recursive calls — prefer cheaper/faster
        sub = root
        for candidate in ("gemini-2-flash", "gpt-4o-mini", "or-free-qwen-coder"):
            if candidate == root:
                continue
            try:
                spec = self.registry.get_model(candidate)
                provider_spec = PROVIDERS.get(spec.provider)
                if provider_spec and os.getenv(provider_spec.api_key_env, ""):
                    sub = candidate
                    break
            except ValueError:
                continue

        return {"root": root, "sub": sub}

    def available_providers(self) -> list[dict]:
        """List all providers and their availability."""
        return self.registry.available_providers()

    def available_models(self) -> list[dict]:
        """List all registered models."""
        return self.registry.available_models()

    def free_models(self) -> list[dict]:
        """List all free ($0) models."""
        return self.registry.free_models()
