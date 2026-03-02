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
    CEREBRAS = "cerebras"
    GROQ = "groq"
    MISTRAL = "mistral"
    MISTRAL_CODESTRAL = "mistral_codestral"
    SAMBANOVA = "sambanova"
    TOGETHER = "together"
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
    default_model: str = ""
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
        default_model="gemini-2.5-flash",
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
    ProviderType.CEREBRAS: ProviderSpec(
        provider_type=ProviderType.CEREBRAS,
        base_url="https://api.cerebras.ai/v1",
        api_key_env="CEREBRAS_API_KEY",
        display_name="Cerebras",
        default_model="llama3.1-8b",
    ),
    ProviderType.GROQ: ProviderSpec(
        provider_type=ProviderType.GROQ,
        base_url="https://api.groq.com/openai/v1",
        api_key_env="GROQ_API_KEY",
        display_name="Groq",
        supports_function_calling=True,
    ),
    ProviderType.MISTRAL: ProviderSpec(
        provider_type=ProviderType.MISTRAL,
        base_url="https://api.mistral.ai/v1",
        api_key_env="MISTRAL_API_KEY",
        display_name="Mistral La Plateforme",
        supports_function_calling=True,
    ),
    ProviderType.MISTRAL_CODESTRAL: ProviderSpec(
        provider_type=ProviderType.MISTRAL_CODESTRAL,
        base_url="https://codestral.mistral.ai/v1",
        api_key_env="CODESTRAL_API_KEY",
        display_name="Mistral Codestral (free)",
        supports_function_calling=True,
    ),
    ProviderType.SAMBANOVA: ProviderSpec(
        provider_type=ProviderType.SAMBANOVA,
        base_url="https://api.sambanova.ai/v1",
        api_key_env="SAMBANOVA_API_KEY",
        display_name="SambaNova",
        supports_function_calling=True,
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
    # Reasoning specialists
    "or-free-deepseek-chat": ModelSpec(
        "meta-llama/llama-3.3-70b-instruct:free",
        ProviderType.OPENROUTER,
        display_name="Llama 3.3 70B Chat (free)",
        tier=ModelTier.FREE,
    ),
    # General-purpose
    "or-free-llama-70b": ModelSpec(
        "meta-llama/llama-3.3-70b-instruct:free",
        ProviderType.OPENROUTER,
        display_name="Llama 3.3 70B (free)",
        tier=ModelTier.FREE,
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
    # Cerebras free models (OpenAI-compatible, ~1000-3000 tok/s inference)
    "cerebras-gpt-oss-120b": ModelSpec(
        "gpt-oss-120b",
        ProviderType.CEREBRAS,
        display_name="GPT-OSS 120B (Cerebras)",
        tier=ModelTier.FREE,
        max_context_tokens=65000,
    ),
    "cerebras-qwen3-235b": ModelSpec(
        "qwen-3-235b-a22b-instruct-2507",
        ProviderType.CEREBRAS,
        display_name="Qwen3 235B (Cerebras)",
        tier=ModelTier.FREE,
        max_context_tokens=65000,
    ),
    "cerebras-llama-8b": ModelSpec(
        "llama3.1-8b",
        ProviderType.CEREBRAS,
        display_name="Llama 3.1 8B (Cerebras)",
        tier=ModelTier.FREE,
        max_context_tokens=8000,
    ),
    "cerebras-zai-glm": ModelSpec(
        "zai-glm-4.7",
        ProviderType.CEREBRAS,
        display_name="ZAI-GLM 4.7 (Cerebras)",
        tier=ModelTier.FREE,
        max_context_tokens=65000,
    ),
    # Groq free models (OpenAI-compatible, 30 RPM free plan, no credit card required)
    "groq-llama-70b": ModelSpec(
        "llama-3.3-70b-versatile",
        ProviderType.GROQ,
        max_tokens=8192,
        display_name="Llama 3.3 70B (Groq)",
        tier=ModelTier.FREE,
        max_context_tokens=131000,   # 131,072 per official docs
    ),
    "groq-gpt-oss-120b": ModelSpec(
        "openai/gpt-oss-120b",       # IMPORTANT: includes "openai/" namespace prefix
        ProviderType.GROQ,
        max_tokens=8192,
        display_name="GPT-OSS 120B (Groq)",
        tier=ModelTier.FREE,
        max_context_tokens=131000,   # 131,072 per official docs
    ),
    "groq-llama-8b": ModelSpec(
        "llama-3.1-8b-instant",
        ProviderType.GROQ,
        max_tokens=4096,
        display_name="Llama 3.1 8B Instant (Groq)",
        tier=ModelTier.FREE,
        max_context_tokens=131000,   # 131,072 per official docs
    ),
    # Mistral Codestral free endpoint (codestral.mistral.ai -- genuinely free, 30 RPM)
    "mistral-codestral": ModelSpec(
        "codestral-latest",
        ProviderType.MISTRAL_CODESTRAL,
        max_tokens=8192,
        display_name="Codestral (Mistral free)",
        tier=ModelTier.FREE,
        max_context_tokens=32000,    # 32K per REQUIREMENTS.md spec (some sources report 256K)
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
        "gemini-2.5-flash",
        ProviderType.GEMINI,
        display_name="Gemini 2.5 Flash",
        tier=ModelTier.CHEAP,
        max_context_tokens=1000000,
    ),
    "deepseek-chat": ModelSpec(
        "deepseek-chat", ProviderType.DEEPSEEK, display_name="DeepSeek Chat", tier=ModelTier.CHEAP
    ),
    # Mistral La Plateforme (api.mistral.ai -- credits-based, 2 RPM on free experiment plan)
    "mistral-large": ModelSpec(
        "mistral-large-latest",
        ProviderType.MISTRAL,
        max_tokens=4096,
        display_name="Mistral Large (La Plateforme)",
        tier=ModelTier.CHEAP,
        max_context_tokens=128000,   # 128K context
    ),
    "mistral-small": ModelSpec(
        "mistral-small-latest",
        ProviderType.MISTRAL,
        max_tokens=4096,
        display_name="Mistral Small (La Plateforme)",
        tier=ModelTier.CHEAP,
        max_context_tokens=128000,   # 128K context
    ),
    # SambaNova (credits-based, funded account required — OpenAI-compatible endpoint)
    # NOTE: SambaNova uses mixed-case model IDs — these must match exactly
    # DeepSeek-V3-0324 is the dated release alias (more stable than DeepSeek-V3.1)
    "sambanova-llama-70b": ModelSpec(
        "Meta-Llama-3.3-70B-Instruct",
        ProviderType.SAMBANOVA,
        max_tokens=4096,
        temperature=0.3,
        display_name="Llama 3.3 70B (SambaNova)",
        tier=ModelTier.CHEAP,
        max_context_tokens=131072,   # 128K context window
    ),
    "sambanova-deepseek-v3": ModelSpec(
        "DeepSeek-V3-0324",
        ProviderType.SAMBANOVA,
        max_tokens=4096,
        temperature=0.3,
        display_name="DeepSeek V3 (SambaNova)",
        tier=ModelTier.CHEAP,
        max_context_tokens=131072,
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
        "gemini-2.5-pro",
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

    # Known per-token pricing for models not covered by the OR catalog.
    # Source: https://ai.google.dev/gemini-api/docs/pricing (March 2026)
    # Format: model_id -> (prompt_per_token, completion_per_token)
    _BUILTIN_PRICES: dict[str, tuple[float, float]] = {
        # Gemini 2.5 Flash — $0.15/M input, $0.60/M output (under 200K context)
        "gemini-2.5-flash": (0.15e-6, 0.60e-6),
        # Gemini 2.5 Pro — $1.25/M input, $10.00/M output (under 200K context)
        "gemini-2.5-pro": (1.25e-6, 10.00e-6),
        # GPT-4o Mini — $0.15/M input, $0.60/M output
        "gpt-4o-mini": (0.15e-6, 0.60e-6),
        # GPT-4o — $2.50/M input, $10.00/M output
        "gpt-4o": (2.50e-6, 10.00e-6),
        # DeepSeek Chat — $0.14/M input, $0.28/M output
        "deepseek-chat": (0.14e-6, 0.28e-6),
        # Cerebras free tier — $0 (1M tokens/day server-side limit)
        "gpt-oss-120b": (0.0, 0.0),
        "qwen-3-235b-a22b-instruct-2507": (0.0, 0.0),
        "llama3.1-8b": (0.0, 0.0),
        "zai-glm-4.7": (0.0, 0.0),
        # Groq free plan -- $0 (rate-limited by Groq, no credit card required)
        "llama-3.3-70b-versatile": (0.0, 0.0),
        "openai/gpt-oss-120b": (0.0, 0.0),    # includes "openai/" prefix -- must match ModelSpec.model_id exactly
        "llama-3.1-8b-instant": (0.0, 0.0),
        # Mistral Codestral free endpoint -- $0 (dedicated free API, 30 RPM)
        "codestral-latest": (0.0, 0.0),
        # Mistral La Plateforme -- actual pricing (CHEAP tier, credits required)
        # Conservative estimates: mistral-large-latest may alias to $2/$6 or $0.50/$1.50 version
        "mistral-large-latest": (2.0e-6, 6.0e-6),     # ~$2.00/M in, $6.00/M out
        "mistral-small-latest": (0.20e-6, 0.60e-6),    # ~$0.20/M in, $0.60/M out
        # SambaNova — credits-based (CHEAP tier), per-token pricing
        # CRITICAL: Keys are MIXED CASE — must match ModelSpec.model_id exactly
        "Meta-Llama-3.3-70B-Instruct": (0.60e-6, 1.20e-6),     # ~$0.60/M in, $1.20/M out
        "DeepSeek-V3-0324": (0.80e-6, 1.60e-6),                 # ~$0.80/M in, $1.60/M out
    }

    def __init__(self):
        self._daily_tokens: dict[str, int] = {}  # date -> total tokens
        self._daily_cost_usd: float = 0.0
        self._current_date: str = ""
        self._model_prices: dict[str, tuple[float, float]] = {}
        # model_id -> (prompt_per_token, completion_per_token)

    def update_model_prices(self, prices: dict[str, tuple[float, float]]) -> None:
        """Update per-model pricing from catalog data."""
        self._model_prices.update(prices)

    def _get_price(self, model_key: str, model_id: str) -> tuple[float, float] | None:
        """Look up per-token pricing for a model.

        Resolution order:
        1. Catalog prices (from OR API sync) — keyed by model_id
        2. Built-in prices — keyed by model_id
        3. Free model detection — model_key starts with "or-free-" or
           model_id ends with ":free" → $0
        4. None → caller decides (conservative fallback)
        """
        # 1. Catalog prices (populated by model_catalog.get_model_prices())
        if model_id and model_id in self._model_prices:
            return self._model_prices[model_id]

        # 2. Built-in prices for known models
        if model_id and model_id in self._BUILTIN_PRICES:
            return self._BUILTIN_PRICES[model_id]

        # 3. Free model detection — $0 cost
        if model_key.startswith("or-free-") or (model_id and model_id.endswith(":free")):
            return (0.0, 0.0)

        return None

    def record_usage(
        self,
        model_key: str,
        prompt_tokens: int,
        completion_tokens: int,
        model_id: str = "",
    ):
        """Record token usage for spending tracking.

        Uses actual per-model pricing when available.  Free models (OR free
        tier, `:free` suffix) are tracked at $0.  Falls back to a
        conservative estimate only for truly unknown models.
        """
        import datetime

        today = datetime.date.today().isoformat()
        if today != self._current_date:
            self._current_date = today
            self._daily_tokens.clear()
            self._daily_cost_usd = 0.0

        total = prompt_tokens + completion_tokens
        self._daily_tokens[today] = self._daily_tokens.get(today, 0) + total

        price = self._get_price(model_key, model_id)
        if price is not None:
            prompt_price, completion_price = price
            estimated_cost = prompt_tokens * prompt_price + completion_tokens * completion_price
        else:
            # Unknown model — conservative fallback ($5/$15 per M tokens)
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
    """Manages provider clients and model resolution.

    Clients are cached per provider but automatically rebuilt when the
    API key in os.environ changes (e.g. admin updates key via dashboard).
    """

    def __init__(self):
        self._clients: dict[ProviderType, AsyncOpenAI] = {}
        self._client_keys: dict[ProviderType, str] = {}  # key used when client was built

    def get_model(self, model_key: str) -> ModelSpec:
        """Look up a ModelSpec by key. Raises ValueError if not found."""
        spec = MODELS.get(model_key)
        if not spec:
            raise ValueError(f"Unknown model: {model_key!r}")
        return spec

    def get_client(self, provider_type: ProviderType) -> AsyncOpenAI:
        """Return a cached AsyncOpenAI client for a provider, rebuilding if the key changed."""
        spec = PROVIDERS.get(provider_type)
        current_key = os.getenv(spec.api_key_env, "") if spec else ""

        cached_key = self._client_keys.get(provider_type, "")
        if provider_type in self._clients and cached_key == current_key:
            return self._clients[provider_type]

        # Key changed or client not yet created — (re)build
        if provider_type in self._clients:
            logger.info(
                "API key changed for %s — rebuilding client",
                provider_type.value,
            )
        self._clients[provider_type] = self._build_client(provider_type)
        self._client_keys[provider_type] = current_key
        return self._clients[provider_type]

    def invalidate_client(self, provider_type: ProviderType) -> None:
        """Remove a cached client so it is rebuilt on next use."""
        self._clients.pop(provider_type, None)
        self._client_keys.pop(provider_type, None)

    def _build_client(self, provider_type: ProviderType) -> AsyncOpenAI:
        """Create an OpenAI-compatible client for a provider."""
        spec = PROVIDERS.get(provider_type)
        if not spec:
            raise ValueError(f"Unknown provider: {provider_type}")

        # Use os.getenv so both .env values (loaded at startup via load_dotenv) and
        # admin-configured keys (injected by KeyStore.inject_into_environ at startup,
        # or updated at runtime by KeyStore.set_key) are picked up correctly.
        # Reading from the `settings` frozen dataclass is wrong here because settings
        # is created at import time, before KeyStore.inject_into_environ() runs.
        api_key = os.getenv(spec.api_key_env, "")
        base_url = os.getenv(f"{provider_type.value.upper()}_BASE_URL", spec.base_url)

        logger.debug(f"Provider: {provider_type}, API Key: {api_key}, Base URL: {base_url}")

        if not api_key:
            logger.error(f"{spec.api_key_env} not set — {spec.display_name} models will fail")
            raise ValueError(f"{spec.api_key_env} not set — {spec.display_name} models will fail")

        return AsyncOpenAI(base_url=base_url, api_key=api_key, max_retries=0)

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

        resolved_temp = temperature if temperature is not None else spec.temperature
        # SAMB-03: SambaNova rejects temperature > 1.0
        if spec.provider == ProviderType.SAMBANOVA:
            resolved_temp = min(resolved_temp, 1.0)
        response = await client.chat.completions.create(
            model=spec.model_id,
            messages=messages,
            temperature=resolved_temp,
            max_tokens=max_tokens or spec.max_tokens,
        )

        content = response.choices[0].message.content or ""
        usage = response.usage
        usage_dict = None
        if usage:
            spending_tracker.record_usage(
                model_key, usage.prompt_tokens, usage.completion_tokens, model_id=spec.model_id
            )
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

        resolved_temp = temperature if temperature is not None else spec.temperature
        # SAMB-03: SambaNova rejects temperature > 1.0
        if spec.provider == ProviderType.SAMBANOVA:
            resolved_temp = min(resolved_temp, 1.0)

        kwargs = {
            "model": spec.model_id,
            "messages": messages,
            "temperature": resolved_temp,
            "max_tokens": max_tokens or spec.max_tokens,
        }
        if tools:
            # SAMB-05: SambaNova does not support strict: true in tool definitions
            if spec.provider == ProviderType.SAMBANOVA:
                import copy
                tools = copy.deepcopy(tools)
                for tool in tools:
                    fn = tool.get("function", {})
                    if fn.get("strict") is True:
                        fn["strict"] = False
            kwargs["tools"] = tools
            # SAMB-04: SambaNova streaming tool calls have broken index field
            if spec.provider == ProviderType.SAMBANOVA:
                kwargs["stream"] = False

        response = await client.chat.completions.create(**kwargs)

        usage = response.usage
        if usage:
            spending_tracker.record_usage(
                model_key, usage.prompt_tokens, usage.completion_tokens, model_id=spec.model_id
            )
            logger.info(
                f"[{model_key}] {usage.prompt_tokens}+{usage.completion_tokens} tokens "
                f"(daily: ${spending_tracker.daily_spend_usd:.4f})"
            )

        return response

    def available_providers(self) -> list[dict]:
        """List all providers and their availability status."""
        result = []
        for ptype, spec in PROVIDERS.items():
            api_key = os.getenv(spec.api_key_env, "")
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
            api_key = os.getenv(provider.api_key_env, "") if provider else ""
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
