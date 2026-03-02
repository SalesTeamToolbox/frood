"""Tests for Phase 5: Provider registry."""

import os
from unittest.mock import patch

import pytest

from providers.registry import (
    MODELS,
    PROVIDERS,
    ModelSpec,
    ProviderRegistry,
    ProviderSpec,
    ProviderType,
)


class TestProviderRegistry:
    def test_all_providers_registered(self):
        expected = {"openai", "anthropic", "deepseek", "gemini", "openrouter", "vllm", "cerebras", "groq"}
        actual = {p.value for p in PROVIDERS.keys()}
        assert expected.issubset(actual)

    def test_model_catalog_not_empty(self):
        assert len(MODELS) >= 11

    def test_each_model_has_valid_provider(self):
        for key, spec in MODELS.items():
            assert spec.provider in ProviderType, (
                f"Model {key} has invalid provider {spec.provider}"
            )

    def test_get_model(self):
        registry = ProviderRegistry()
        spec = registry.get_model("or-free-qwen-coder")
        assert spec.model_id == "qwen/qwen3-coder:free"
        assert spec.provider == ProviderType.OPENROUTER

    def test_get_unknown_model_raises(self):
        registry = ProviderRegistry()
        with pytest.raises(ValueError, match="Unknown model"):
            registry.get_model("nonexistent-model")

    def test_available_providers(self):
        registry = ProviderRegistry()
        providers = registry.available_providers()
        assert len(providers) == len(PROVIDERS)
        for p in providers:
            assert "provider" in p
            assert "display_name" in p
            assert "configured" in p

    def test_available_models(self):
        registry = ProviderRegistry()
        models = registry.available_models()
        assert len(models) == len(MODELS)
        for m in models:
            assert "key" in m
            assert "model_id" in m
            assert "provider" in m

    def test_register_custom_provider(self):
        custom = ProviderSpec(
            provider_type=ProviderType.CUSTOM,
            base_url="http://localhost:1234/v1",
            api_key_env="CUSTOM_API_KEY",
            display_name="My Custom Provider",
        )
        ProviderRegistry.register_provider(ProviderType.CUSTOM, custom)
        assert ProviderType.CUSTOM in PROVIDERS
        assert PROVIDERS[ProviderType.CUSTOM].display_name == "My Custom Provider"

    def test_register_custom_model(self):
        custom_model = ModelSpec(
            model_id="my-custom/model-v1",
            provider=ProviderType.CUSTOM,
            display_name="Custom Model v1",
        )
        ProviderRegistry.register_model("custom-v1", custom_model)
        assert "custom-v1" in MODELS
        assert MODELS["custom-v1"].display_name == "Custom Model v1"

    def test_openai_models_exist(self):
        openai_models = [k for k, v in MODELS.items() if v.provider == ProviderType.OPENAI]
        assert len(openai_models) >= 2

    def test_anthropic_models_exist(self):
        claude_models = [k for k, v in MODELS.items() if v.provider == ProviderType.ANTHROPIC]
        assert len(claude_models) >= 2

    def test_openrouter_models_exist(self):
        or_models = [k for k, v in MODELS.items() if v.provider == ProviderType.OPENROUTER]
        assert len(or_models) >= 3

    def test_client_cache_rebuilds_on_key_change(self):
        """Cached client is rebuilt when the API key changes in os.environ."""
        registry = ProviderRegistry()
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-old-key-1234"}):
            client1 = registry.get_client(ProviderType.OPENROUTER)
            # Same key — should return the cached client
            client2 = registry.get_client(ProviderType.OPENROUTER)
            assert client1 is client2

        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-new-key-5678"}):
            # Key changed — should rebuild
            client3 = registry.get_client(ProviderType.OPENROUTER)
            assert client3 is not client1

    def test_invalidate_client_forces_rebuild(self):
        """invalidate_client() clears the cache so next get_client() rebuilds."""
        registry = ProviderRegistry()
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-test-key-9999"}):
            client1 = registry.get_client(ProviderType.OPENROUTER)
            registry.invalidate_client(ProviderType.OPENROUTER)
            client2 = registry.get_client(ProviderType.OPENROUTER)
            assert client2 is not client1


class TestCerebrasRegistration:
    """Phase 1: Cerebras provider registration tests."""

    def test_cerebras_provider_registered(self):
        """Cerebras ProviderSpec is in PROVIDERS with correct base_url and api_key_env."""
        spec = PROVIDERS[ProviderType.CEREBRAS]
        assert spec.base_url == "https://api.cerebras.ai/v1"
        assert spec.api_key_env == "CEREBRAS_API_KEY"
        assert spec.display_name == "Cerebras"

    def test_cerebras_models_registered(self):
        """All 4 Cerebras models are registered with correct model_ids."""
        expected = {
            "cerebras-gpt-oss-120b": "gpt-oss-120b",
            "cerebras-qwen3-235b": "qwen-3-235b-a22b-instruct-2507",
            "cerebras-llama-8b": "llama3.1-8b",
            "cerebras-zai-glm": "zai-glm-4.7",
        }
        for model_key, expected_id in expected.items():
            spec = MODELS[model_key]
            assert spec.model_id == expected_id, f"{model_key} model_id mismatch"
            assert spec.provider == ProviderType.CEREBRAS

    def test_cerebras_models_all_free_tier(self):
        """All Cerebras models are classified as FREE tier."""
        from providers.registry import ModelTier

        cerebras_models = [k for k, v in MODELS.items() if v.provider == ProviderType.CEREBRAS]
        assert len(cerebras_models) == 4
        for key in cerebras_models:
            assert MODELS[key].tier == ModelTier.FREE, f"{key} is not FREE tier"

    def test_cerebras_client_builds_with_key(self):
        """Client builds successfully when CEREBRAS_API_KEY is set."""
        registry = ProviderRegistry()
        with patch.dict(os.environ, {"CEREBRAS_API_KEY": "csk-test-key-1234"}):
            client = registry.get_client(ProviderType.CEREBRAS)
            assert client is not None
            assert client.base_url == "https://api.cerebras.ai/v1/"

    def test_cerebras_client_raises_without_key(self):
        """Client raises ValueError when CEREBRAS_API_KEY is not set."""
        registry = ProviderRegistry()
        registry.invalidate_client(ProviderType.CEREBRAS)
        with patch.dict(os.environ, {"CEREBRAS_API_KEY": ""}, clear=False):
            with pytest.raises(ValueError, match="CEREBRAS_API_KEY not set"):
                registry.get_client(ProviderType.CEREBRAS)


class TestGroqRegistration:
    """Phase 2: Groq provider registration tests."""

    def test_groq_provider_registered(self):
        """GROQ-01: ProviderSpec is in PROVIDERS with correct base_url and api_key_env."""
        spec = PROVIDERS[ProviderType.GROQ]
        assert spec.base_url == "https://api.groq.com/openai/v1"
        assert spec.api_key_env == "GROQ_API_KEY"
        assert spec.display_name == "Groq"

    def test_groq_models_registered(self):
        """GROQ-02: All 3 Groq models are registered with correct model_ids."""
        expected = {
            "groq-llama-70b": "llama-3.3-70b-versatile",
            "groq-gpt-oss-120b": "openai/gpt-oss-120b",
            "groq-llama-8b": "llama-3.1-8b-instant",
        }
        for model_key, expected_id in expected.items():
            spec = MODELS[model_key]
            assert spec.model_id == expected_id, f"{model_key} model_id mismatch"
            assert spec.provider == ProviderType.GROQ

    def test_groq_models_all_free_tier(self):
        """GROQ-03: All Groq models are classified as FREE tier."""
        from providers.registry import ModelTier

        groq_models = [k for k, v in MODELS.items() if v.provider == ProviderType.GROQ]
        assert len(groq_models) == 3
        for key in groq_models:
            assert MODELS[key].tier == ModelTier.FREE, f"{key} is not FREE tier"

    def test_groq_context_windows(self):
        """GROQ-02: All Groq models have 131K context window."""
        for key in ["groq-llama-70b", "groq-gpt-oss-120b", "groq-llama-8b"]:
            assert MODELS[key].max_context_tokens == 131000, f"{key} wrong context"

    def test_groq_client_builds_with_key(self):
        """Client builds successfully when GROQ_API_KEY is set."""
        registry = ProviderRegistry()
        with patch.dict(os.environ, {"GROQ_API_KEY": "gsk-test-key-1234"}):
            client = registry.get_client(ProviderType.GROQ)
            assert client is not None
            assert client.base_url == "https://api.groq.com/openai/v1/"

    def test_groq_client_raises_without_key(self):
        """Client raises ValueError when GROQ_API_KEY is not set."""
        registry = ProviderRegistry()
        registry.invalidate_client(ProviderType.GROQ)
        with patch.dict(os.environ, {"GROQ_API_KEY": ""}, clear=False):
            with pytest.raises(ValueError, match="GROQ_API_KEY not set"):
                registry.get_client(ProviderType.GROQ)
