"""
Provider registry — declarative LLM provider management.

Inspired by Nanobot's ProviderSpec pattern: adding a new provider is a 2-step
process (register spec + add config field). No if-elif chains needed.
"""

import logging
import os
from dataclasses import dataclass
from enum import Enum

from openai import AsyncOpenAI

from core.config import settings

logger = logging.getLogger("agent42.providers")


class SpendingLimitExceeded(RuntimeError):
    """Raised when the daily API spending limit is reached."""

    pass


class ProviderType(str, Enum):
    """Provider type enumeration."""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    DEEPSEEK = "deepseek"
    GEMINI = "gemini"
    OPENROUTER = "openrouter"
    VLLM = "vllm"
    CUSTOM = "custom"


class ModelTier(str, Enum):
    """Cost tier for model selection strategy."""

    FREE = "free"
    CHEAP = "cheap"
    PREMIUM = "premium"


@dataclass(frozen=True)
class ModelSpec:
    """A specific model on a specific provider."""

    model_id: str
    provider: ProviderType
    max_tokens: int = 4096
    temperature: float = 0.3
    display_name: str = ""
    tier: ModelTier = ModelTier.FREE  # Default to free for cost-conscious routing
    max_context_tokens: int = 128000


@dataclass(frozen=True)
class ProviderSpec:
    """Provider configuration specification."""

    provider_type: ProviderType
    base_url: str
    api_key_env: str
    display_name: str
    default_model: str
    requires_model_prefix: bool = False
    supports_function_calling: bool = True


PROVIDERS: dict[ProviderType, ProviderSpec] = {
    ProviderType.OPENAI: ProviderSpec(
        provider_type=ProviderType.OPENAI,
        base_url="https://api.openai.com/v1",
        api_key_env="OPENAI_API_KEY",
        display_name="OpenAI",
        default_model="gpt-4o",
    ),
    ProviderType.ANTHROPIC: ProviderSpec(
        provider_type=ProviderType.ANTHROPIC,
        base_url="https://api.anthropic.com/v1",
        api_key_env="ANTHROPIC_API_KEY",
        display_name="Anthropic",
        default_model="claude-sonnet-4-20250514",
        supports_function_calling=True,
    ),
    ProviderType.DEEPSEEK: ProviderSpec(
        provider_type=ProviderType.DEEPSEEK,
        base_url="https://api.deepseek.com/v1",
        api_key_env="DEEPSEEK_API_KEY",
        display_name="DeepSeek",
        default_model="deepseek-chat",
    ),
    ProviderType.GEMINI: ProviderSpec(
        provider_type=ProviderType.GEMINI,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        api_key_env="GEMINI_API_KEY",
        display_name="Google Gemini",
        default_model="gemini-2.0-flash",
    ),
    ProviderType.OPENROUTER: ProviderSpec(
        provider_type=ProviderType.OPENROUTER,
        base_url="https://openrouter.ai/api/v1",
        api_key_env="OPENROUTER_API_KEY",
        display_name="OpenRouter (200+ models)",
        default_model="anthropic/claude-sonnet-4-20250514",
        requires_model_prefix=True,
    ),
    ProviderType.VLLM: ProviderSpec(
        provider_type=ProviderType.VLLM,
        base_url="http://localhost:8000/v1",
        api_key_env="VLLM_API_KEY",
        display_name="vLLM (local)",
        default_model="local-model",
        supports_function_calling=False,
    ),
}


MODELS: dict[str, ModelSpec] = {
    # ═══════════════════════════════════════════════════════════════════════════
    # FREE TIER — $0 models for bulk agent work (default for all task types)
    # ═══════════════════════════════════════════════════════════════════════════
    # OpenRouter free models (single API key, no credit card needed)
    # ~30 free models available — these are the best for agent work
    "or-free-auto": ModelSpec(
        "openrouter/free",
        ProviderType.OPENROUTER,
        display_name="OR Free Auto-Router",
        tier=ModelTier.FREE,
    ),
    # Coding specialists
    "or-free-qwen-coder": ModelSpec(
        "qwen/qwen3-coder:free",
        ProviderType.OPENROUTER,
        max_tokens=8192,
        display_name="Qwen3 Coder 480B (free)",
        tier=ModelTier.FREE,
    ),
    "or-free-devstral": ModelSpec(
        "mistralai/devstral-2512:free",
        ProviderType.OPENROUTER,
        max_tokens=8192,
        display_name="Devstral 123B (free)",
        tier=ModelTier.FREE,
    ),
    # Reasoning specialists
    "or-free-deepseek-r1": ModelSpec(
        "deepseek/deepseek-r1-0528:free",
        ProviderType.OPENROUTER,
        temperature=0.2,
        display_name="DeepSeek R1 0528 (free)",
        tier=ModelTier.FREE,
    ),
    "or-free-deepseek-chat": ModelSpec(
        "deepseek/deepseek-chat-v3.1:free",
        ProviderType.OPENROUTER,
        display_name="DeepSeek Chat v3.1 (free)",
        tier=ModelTier.FREE,
    ),
    # General-purpose
    "or-free-llama4-maverick": ModelSpec(
        "meta-llama/llama-4-maverick:free",
        ProviderType.OPENROUTER,
        display_name="Llama 4 Maverick (free)",
        tier=ModelTier.FREE,
    ),
    "or-free-llama-70b": ModelSpec(
        "meta-llama/llama-3.3-70b-instruct:free",
        ProviderType.OPENROUTER,
        display_name="Llama 3.3 70B (free)",
        tier=ModelTier.FREE,
    ),
    "or-free-gemini-flash": ModelSpec(
        "google/gemini-2.0-flash-exp:free",
        ProviderType.OPENROUTER,
        max_tokens=8192,
        display_name="Gemini 2.0 Flash (free, 1M ctx)",
        tier=ModelTier.FREE,
        max_context_tokens=1000000,
    ),
    "or-free-gemini-pro": ModelSpec(
        "google/gemini-2.5-pro-exp-03-25:free",
        ProviderType.OPENROUTER,
        max_tokens=8192,
        display_name="Gemini 2.5 Pro (free)",
        tier=ModelTier.FREE,
        max_context_tokens=1000000,
    ),
    "or-free-mistral-small": ModelSpec(
        "mistralai/mistral-small-3.1-24b-instruct:free",
        ProviderType.OPENROUTER,
        display_name="Mistral Small 3.1 (free)",
        tier=ModelTier.FREE,
    ),
    # Lightweight / fast
    "or-free-nemotron": ModelSpec(
        "nvidia/nemotron-3-nano-30b-a3b:free",
        ProviderType.OPENROUTER,
        display_name="NVIDIA Nemotron 30B (free)",
        tier=ModelTier.FREE,
    ),
    "or-free-gemma-27b": ModelSpec(
        "google/gemma-3-27b-it:free",
        ProviderType.OPENROUTER,
        display_name="Gemma 3 27B (free)",
        tier=ModelTier.FREE,
    ),
    # ═══════════════════════════════════════════════════════════════════════════
    # CHEAP TIER — low-cost models for when free isn't enough
    # ═══════════════════════════════════════════════════════════════════════════
    "gpt-4o-mini": ModelSpec(
        "gpt-4o-mini", ProviderType.OPENAI, display_name="GPT-4o Mini", tier=ModelTier.CHEAP
    ),
    "claude-haiku": ModelSpec(
        "claude-haiku-4-5-20251001",
        ProviderType.ANTHROPIC,
        display_name="Claude Haiku 4.5",
        tier=ModelTier.CHEAP,
    ),
    "gemini-2-flash": ModelSpec(
        "gemini-2.0-flash",
        ProviderType.GEMINI,
        display_name="Gemini 2.0 Flash",
        tier=ModelTier.CHEAP,
        max_context_tokens=1000000,
    ),
    "deepseek-chat": ModelSpec(
        "deepseek-chat", ProviderType.DEEPSEEK, display_name="DeepSeek Chat", tier=ModelTier.CHEAP
    ),
    # ═══════════════════════════════════════════════════════════════════════════
    # PREMIUM TIER — frontier models for final reviews, complex tasks, admin-selected
    # ═══════════════════════════════════════════════════════════════════════════
    "gpt-4o": ModelSpec(
        "gpt-4o", ProviderType.OPENAI, display_name="GPT-4o", tier=ModelTier.PREMIUM
    ),
    "o1": ModelSpec(
        "o1", ProviderType.OPENAI, temperature=1.0, display_name="o1", tier=ModelTier.PREMIUM
    ),
    "claude-sonnet": ModelSpec(
        "claude-sonnet-4-20250514",
        ProviderType.ANTHROPIC,
        display_name="Claude Sonnet 4",
        tier=ModelTier.PREMIUM,
    ),
    "gemini-2-pro": ModelSpec(
        "gemini-2.5-pro-preview-05-06",
        ProviderType.GEMINI,
        display_name="Gemini 2.5 Pro",
        tier=ModelTier.PREMIUM,
        max_context_tokens=1000000,
    ),
    "deepseek-reasoner": ModelSpec(
        "deepseek-reasoner",
        ProviderType.DEEPSEEK,
        temperature=0.2,
        display_name="DeepSeek Reasoner",
        tier=ModelTier.PREMIUM,
    ),
    # OpenRouter paid pass-through (use any model via single key)
    "or-claude-sonnet": ModelSpec(
        "anthropic/claude-sonnet-4-20250514",
        ProviderType.OPENROUTER,
        display_name="Claude Sonnet via OR",
        tier=ModelTier.PREMIUM,
    ),
    "or-gpt-4o": ModelSpec(
        "openai/gpt-4o",
        ProviderType.OPENROUTER,
        display_name="GPT-4o via OR",
        tier=ModelTier.PREMIUM,
    ),
    "or-llama-405b": ModelSpec(
        "meta-llama/llama-3.1-405b-instruct",
        ProviderType.OPENROUTER,
        display_name="Llama 405B via OR",
        tier=ModelTier.PREMIUM,
    ),
}


class SpendingTracker:
    """Tracks API spending to enforce daily limits."""

    def __init__(self):
        self._daily_tokens: dict[str, int] = {}  # date -> total tokens
        self._daily_cost_usd: float = 0.0
        self._current_date: str = ""

    def record_usage(self, model_key: str, prompt_tokens: int, completion_tokens: int):
        """Record token usage for spending tracking."""
        import datetime

        today = datetime.date.today().isoformat()
        if today != self._current_date:
            self._current_date = today
            self._daily_tokens.clear()
            self._daily_cost_usd = 0.0

        total = prompt_tokens + completion_tokens
        self._daily_tokens[today] = self._daily_tokens.get(today, 0) + total

        # Rough cost estimation (conservative — uses premium pricing)
        # Actual cost depends on model, but this provides a safety ceiling
        estimated_cost = (prompt_tokens * 5.0 + completion_tokens * 15.0) / 1_000_000
        self._daily_cost_usd += estimated_cost

    def check_limit(self, limit_usd: float) -> bool:
        """Check if daily spending is within limits. Returns True if OK."""
        if limit_usd <= 0:
            return True  # No limit set
        return self._daily_cost_usd < limit_usd

    @property
    def daily_spend_usd(self) -> float:
        return round(self._daily_cost_usd, 4)

    @property
    def daily_tokens(self) -> int:
        return sum(self._daily_tokens.values())


spending_tracker = SpendingTracker()


class ProviderRegistry:
    """Manages provider clients and model resolution."""

    def __init__(self):
        self._clients: dict[ProviderType, AsyncOpenAI] = {}

    def _build_client(self, provider_type: ProviderType) -> AsyncOpenAI:
        """Create an OpenAI-compatible client for a provider."""
        spec = PROVIDERS.get(provider_type)
        if not spec:
            raise ValueError(f"Unknown provider: {provider_type}")

        # Use settings object instead of os.getenv to respect runtime updates
        api_key = getattr(settings, f"{provider_type.value.lower()}_api_key", "")
        base_url = os.getenv(f"{provider_type.value.upper()}_BASE_URL", spec.base_url)

        if not api_key:
            logger.warning(f"{spec.api_key_env} not set — {spec.display_name} models will fail")

        return AsyncOpenAI(base_url=base_url, api_key=api_key or "not-set")

    def get_client(self, provider_type: ProviderType) -> AsyncOpenAI:
        """Get or create a client for a provider."""
        if provider_type not in self._clients:
            self._clients[provider_type] = self._build_client(provider_type)
        return self._clients[provider_type]

    def clear_cache(self):
        """Clear cached clients so they rebuild with fresh API keys on next use."""
        self._clients.clear()

    def get_model(self, model_key: str) -> ModelSpec:
        """Resolve a model key to its spec."""
        spec = MODELS.get(model_key)
        if not spec:
            raise ValueError(f"Unknown model: {model_key}. Available: {list(MODELS.keys())}")
        return spec

    async def complete(
        self,
        model_key: str,
        messages: list[dict],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> tuple[str, dict | None]:
        """Send a chat completion and return (response_text, usage_dict).

        The usage_dict contains model_key, prompt_tokens, and completion_tokens
        when available, or None if the API did not return usage data.
        """
        if not spending_tracker.check_limit(settings.max_daily_api_spend_usd):
            raise SpendingLimitExceeded(
                f"Daily API spending limit reached "
                f"(${spending_tracker.daily_spend_usd:.2f} / "
                f"${settings.max_daily_api_spend_usd:.2f})"
            )

        spec = self.get_model(model_key)
        client = self.get_client(spec.provider)

        response = await client.chat.completions.create(
            model=spec.model_id,
            messages=messages,
            temperature=temperature if temperature is not None else spec.temperature,
            max_tokens=max_tokens or spec.max_tokens,
        )

        content = response.choices[0].message.content or ""
        usage = response.usage
        usage_dict = None
        if usage:
            spending_tracker.record_usage(model_key, usage.prompt_tokens, usage.completion_tokens)
            usage_dict = {
                "model_key": model_key,
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
            }
            logger.info(
                f"[{model_key}] {usage.prompt_tokens}+{usage.completion_tokens} tokens "
                f"(daily: ${spending_tracker.daily_spend_usd:.4f})"
            )
        return content, usage_dict

    async def complete_with_tools(
        self,
        model_key: str,
        messages: list[dict],
        tools: list[dict],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ):
        """Send a chat completion with tool schemas, tracking spending.

        Returns the full response object so callers can inspect tool_calls.
        """
        if not spending_tracker.check_limit(settings.max_daily_api_spend_usd):
            raise SpendingLimitExceeded(
                f"Daily API spending limit reached "
                f"(${spending_tracker.daily_spend_usd:.2f} / "
                f"${settings.max_daily_api_spend_usd:.2f})"
            )

        spec = self.get_model(model_key)
        client = self.get_client(spec.provider)

        kwargs = {
            "model": spec.model_id,
            "messages": messages,
            "temperature": temperature if temperature is not None else spec.temperature,
            "max_tokens": max_tokens or spec.max_tokens,
        }
        if tools:
            kwargs["tools"] = tools

        response = await client.chat.completions.create(**kwargs)

        usage = response.usage
        if usage:
            spending_tracker.record_usage(model_key, usage.prompt_tokens, usage.completion_tokens)
            logger.info(
                f"[{model_key}] {usage.prompt_tokens}+{usage.completion_tokens} tokens "
                f"(daily: ${spending_tracker.daily_spend_usd:.4f})"
            )

        return response

    def available_providers(self) -> list[dict]:
        """List all providers and their availability status."""
        result = []
        for ptype, spec in PROVIDERS.items():
            api_key = getattr(settings, f"{ptype.value.lower()}_api_key", "")
            result.append(
                {
                    "provider": ptype.value,
                    "display_name": spec.display_name,
                    "configured": bool(api_key),
                    "base_url": spec.base_url,
                }
            )
        return result

    def available_models(self) -> list[dict]:
        """List all registered models."""
        result = []
        for key, spec in MODELS.items():
            provider = PROVIDERS.get(spec.provider)
            api_key = (
                getattr(settings, f"{spec.provider.value.lower()}_api_key", "")
                if provider
                else ""
            )
            result.append(
                {
                    "key": key,
                    "model_id": spec.model_id,
                    "provider": spec.provider.value,
                    "display_name": spec.display_name or key,
                    "configured": bool(api_key),
                }
            )
        return result

    def models_by_tier(self, tier: ModelTier) -> list[dict]:
        """List models filtered by cost tier."""
        return [
            {
                "key": k,
                "model_id": s.model_id,
                "provider": s.provider.value,
                "display_name": s.display_name or k,
                "tier": s.tier.value,
            }
            for k, s in MODELS.items()
            if s.tier == tier
        ]

    def free_models(self) -> list[dict]:
        """List all free ($0) models."""
        return self.models_by_tier(ModelTier.FREE)

    def models_by_min_context(self, min_tokens: int) -> list[dict]:
        """List models with at least *min_tokens* context window."""
        return [
            {
                "key": k,
                "model_id": s.model_id,
                "provider": s.provider.value,
                "display_name": s.display_name or k,
                "tier": s.tier.value,
                "max_context_tokens": s.max_context_tokens,
            }
            for k, s in MODELS.items()
            if s.max_context_tokens >= min_tokens
        ]

    @staticmethod
    def register_provider(provider_type: ProviderType, spec: ProviderSpec):
        """Register a new provider at runtime (2-step pattern: register + set env var)."""
        PROVIDERS[provider_type] = spec

    @staticmethod
    def register_model(key: str, spec: ModelSpec):
        """Register a new model at runtime."""
        MODELS[key] = spec

    @staticmethod
    def register_models_bulk(specs: dict[str, ModelSpec]) -> int:
        """Register multiple models at once. Returns count of new registrations."""
        added = 0
        for key, spec in specs.items():
            if key not in MODELS:
                MODELS[key] = spec
                added += 1
        return added
