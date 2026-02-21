"""
Provider registry — declarative LLM provider management.

Inspired by Nanobot's ProviderSpec pattern: adding a new provider is a 2-step
process (register spec + add config field). No if-elif chains needed.
"""

import logging
import os
from dataclasses import dataclass, field
from enum import Enum

from openai import AsyncOpenAI

from core.config import settings

logger = logging.getLogger("agent42.providers")


class ProviderType(str, Enum):
    NVIDIA = "nvidia"
    GROQ = "groq"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    DEEPSEEK = "deepseek"
    GEMINI = "gemini"
    OPENROUTER = "openrouter"
    VLLM = "vllm"
    CUSTOM = "custom"


@dataclass(frozen=True)
class ProviderSpec:
    """Declarative provider specification."""
    provider_type: ProviderType
    base_url: str
    api_key_env: str              # Environment variable name for the API key
    display_name: str = ""
    default_model: str = ""
    supports_streaming: bool = True
    supports_function_calling: bool = True
    max_tokens_default: int = 4096
    requires_model_prefix: bool = False  # Some gateways need provider/ prefix
    model_prefix: str = ""               # e.g. "anthropic/" for OpenRouter


class ModelTier(str, Enum):
    """Cost tier for model selection strategy."""
    FREE = "free"           # $0 models (OpenRouter free, NVIDIA free, Groq free)
    CHEAP = "cheap"         # Low-cost models (GPT-4o-mini, Haiku, etc.)
    PREMIUM = "premium"     # Full-price frontier models (GPT-4o, Sonnet, etc.)


@dataclass(frozen=True)
class ModelSpec:
    """A specific model on a specific provider."""
    model_id: str
    provider: ProviderType
    max_tokens: int = 4096
    temperature: float = 0.3
    display_name: str = ""
    tier: ModelTier = ModelTier.FREE  # Default to free for cost-conscious routing


# -- Provider catalog ---------------------------------------------------------
PROVIDERS: dict[ProviderType, ProviderSpec] = {
    ProviderType.NVIDIA: ProviderSpec(
        provider_type=ProviderType.NVIDIA,
        base_url="https://integrate.api.nvidia.com/v1",
        api_key_env="NVIDIA_API_KEY",
        display_name="NVIDIA Build",
        default_model="qwen/qwen2.5-coder-32b-instruct",
    ),
    ProviderType.GROQ: ProviderSpec(
        provider_type=ProviderType.GROQ,
        base_url="https://api.groq.com/openai/v1",
        api_key_env="GROQ_API_KEY",
        display_name="Groq",
        default_model="llama-3.3-70b-versatile",
    ),
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

# -- Model catalog ------------------------------------------------------------
MODELS: dict[str, ModelSpec] = {
    # ═══════════════════════════════════════════════════════════════════════════
    # FREE TIER — $0 models for bulk agent work (default for all task types)
    # ═══════════════════════════════════════════════════════════════════════════

    # OpenRouter free models (single API key, no credit card needed)
    "or-free-auto": ModelSpec("openrouter/free", ProviderType.OPENROUTER, display_name="OR Free Auto-Router", tier=ModelTier.FREE),
    "or-free-deepseek-r1": ModelSpec("deepseek/deepseek-r1:free", ProviderType.OPENROUTER, temperature=0.2, display_name="DeepSeek R1 (free)", tier=ModelTier.FREE),
    "or-free-deepseek-chat": ModelSpec("deepseek/deepseek-chat-v3.1:free", ProviderType.OPENROUTER, display_name="DeepSeek Chat v3.1 (free)", tier=ModelTier.FREE),
    "or-free-llama-70b": ModelSpec("meta-llama/llama-3.3-70b-instruct:free", ProviderType.OPENROUTER, display_name="Llama 3.3 70B (free)", tier=ModelTier.FREE),
    "or-free-qwen-coder": ModelSpec("qwen/qwen3-coder-480b:free", ProviderType.OPENROUTER, display_name="Qwen3 Coder 480B (free)", tier=ModelTier.FREE),
    "or-free-qwen-thinking": ModelSpec("qwen/qwen3-235b-a22b-thinking-2507:free", ProviderType.OPENROUTER, temperature=0.2, display_name="Qwen3 235B Thinking (free)", tier=ModelTier.FREE),
    "or-free-nemotron": ModelSpec("nvidia/nemotron-3-nano-30b:free", ProviderType.OPENROUTER, display_name="NVIDIA Nemotron 30B (free)", tier=ModelTier.FREE),

    # NVIDIA hosted (free tier with API key)
    "qwen-coder-32b": ModelSpec("qwen/qwen2.5-coder-32b-instruct", ProviderType.NVIDIA, display_name="Qwen 2.5 Coder 32B", tier=ModelTier.FREE),
    "deepseek-r1": ModelSpec("deepseek/deepseek-r1", ProviderType.NVIDIA, temperature=0.2, display_name="DeepSeek R1", tier=ModelTier.FREE),
    "llama-405b": ModelSpec("meta/llama-3.1-405b-instruct", ProviderType.NVIDIA, display_name="Llama 3.1 405B", tier=ModelTier.FREE),
    "llama-70b": ModelSpec("meta/llama-3.3-70b-instruct", ProviderType.NVIDIA, display_name="Llama 3.3 70B", tier=ModelTier.FREE),
    "mistral-large": ModelSpec("mistralai/mistral-large-2-instruct", ProviderType.NVIDIA, display_name="Mistral Large 2", tier=ModelTier.FREE),

    # Groq hosted (free tier, fast inference)
    "groq-llama-70b": ModelSpec("llama-3.3-70b-versatile", ProviderType.GROQ, display_name="Groq Llama 70B", tier=ModelTier.FREE),
    "groq-mixtral": ModelSpec("mixtral-8x7b-32768", ProviderType.GROQ, display_name="Groq Mixtral", tier=ModelTier.FREE),

    # ═══════════════════════════════════════════════════════════════════════════
    # CHEAP TIER — low-cost models for when free isn't enough
    # ═══════════════════════════════════════════════════════════════════════════

    "gpt-4o-mini": ModelSpec("gpt-4o-mini", ProviderType.OPENAI, display_name="GPT-4o Mini", tier=ModelTier.CHEAP),
    "claude-haiku": ModelSpec("claude-haiku-4-5-20251001", ProviderType.ANTHROPIC, display_name="Claude Haiku 4.5", tier=ModelTier.CHEAP),
    "gemini-2-flash": ModelSpec("gemini-2.0-flash", ProviderType.GEMINI, display_name="Gemini 2.0 Flash", tier=ModelTier.CHEAP),
    "deepseek-chat": ModelSpec("deepseek-chat", ProviderType.DEEPSEEK, display_name="DeepSeek Chat", tier=ModelTier.CHEAP),

    # ═══════════════════════════════════════════════════════════════════════════
    # PREMIUM TIER — frontier models for final reviews, complex tasks, admin-selected
    # ═══════════════════════════════════════════════════════════════════════════

    "gpt-4o": ModelSpec("gpt-4o", ProviderType.OPENAI, display_name="GPT-4o", tier=ModelTier.PREMIUM),
    "o1": ModelSpec("o1", ProviderType.OPENAI, temperature=1.0, display_name="o1", tier=ModelTier.PREMIUM),
    "claude-sonnet": ModelSpec("claude-sonnet-4-20250514", ProviderType.ANTHROPIC, display_name="Claude Sonnet 4", tier=ModelTier.PREMIUM),
    "gemini-2-pro": ModelSpec("gemini-2.5-pro-preview-05-06", ProviderType.GEMINI, display_name="Gemini 2.5 Pro", tier=ModelTier.PREMIUM),
    "deepseek-reasoner": ModelSpec("deepseek-reasoner", ProviderType.DEEPSEEK, temperature=0.2, display_name="DeepSeek Reasoner", tier=ModelTier.PREMIUM),

    # OpenRouter paid pass-through (use any model via single key)
    "or-claude-sonnet": ModelSpec("anthropic/claude-sonnet-4-20250514", ProviderType.OPENROUTER, display_name="Claude Sonnet via OR", tier=ModelTier.PREMIUM),
    "or-gpt-4o": ModelSpec("openai/gpt-4o", ProviderType.OPENROUTER, display_name="GPT-4o via OR", tier=ModelTier.PREMIUM),
    "or-llama-405b": ModelSpec("meta-llama/llama-3.1-405b-instruct", ProviderType.OPENROUTER, display_name="Llama 405B via OR", tier=ModelTier.PREMIUM),
}


class ProviderRegistry:
    """Manages provider clients and model resolution."""

    def __init__(self):
        self._clients: dict[ProviderType, AsyncOpenAI] = {}

    def _build_client(self, provider_type: ProviderType) -> AsyncOpenAI:
        """Create an OpenAI-compatible client for a provider."""
        spec = PROVIDERS.get(provider_type)
        if not spec:
            raise ValueError(f"Unknown provider: {provider_type}")

        api_key = os.getenv(spec.api_key_env, "")
        base_url = os.getenv(
            f"{provider_type.value.upper()}_BASE_URL", spec.base_url
        )

        if not api_key:
            logger.warning(f"{spec.api_key_env} not set — {spec.display_name} models will fail")

        return AsyncOpenAI(base_url=base_url, api_key=api_key or "not-set")

    def get_client(self, provider_type: ProviderType) -> AsyncOpenAI:
        """Get or create a client for a provider."""
        if provider_type not in self._clients:
            self._clients[provider_type] = self._build_client(provider_type)
        return self._clients[provider_type]

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
    ) -> str:
        """Send a chat completion and return the response text."""
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
        if usage:
            logger.info(
                f"[{model_key}] {usage.prompt_tokens}+{usage.completion_tokens} tokens"
            )
        return content

    def available_providers(self) -> list[dict]:
        """List all providers and their availability status."""
        result = []
        for ptype, spec in PROVIDERS.items():
            api_key = os.getenv(spec.api_key_env, "")
            result.append({
                "provider": ptype.value,
                "display_name": spec.display_name,
                "configured": bool(api_key),
                "base_url": spec.base_url,
            })
        return result

    def available_models(self) -> list[dict]:
        """List all registered models."""
        result = []
        for key, spec in MODELS.items():
            provider = PROVIDERS.get(spec.provider)
            result.append({
                "key": key,
                "model_id": spec.model_id,
                "provider": spec.provider.value,
                "display_name": spec.display_name or key,
                "configured": bool(os.getenv(provider.api_key_env, "")) if provider else False,
            })
        return result

    def models_by_tier(self, tier: ModelTier) -> list[dict]:
        """List models filtered by cost tier."""
        return [
            {"key": k, "model_id": s.model_id, "provider": s.provider.value,
             "display_name": s.display_name or k, "tier": s.tier.value}
            for k, s in MODELS.items() if s.tier == tier
        ]

    def free_models(self) -> list[dict]:
        """List all free ($0) models."""
        return self.models_by_tier(ModelTier.FREE)

    @staticmethod
    def register_provider(provider_type: ProviderType, spec: ProviderSpec):
        """Register a new provider at runtime (2-step pattern: register + set env var)."""
        PROVIDERS[provider_type] = spec

    @staticmethod
    def register_model(key: str, spec: ModelSpec):
        """Register a new model at runtime."""
        MODELS[key] = spec
