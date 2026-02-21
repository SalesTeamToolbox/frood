"""Tests for Phase 5: Provider registry."""

import os
import pytest
from providers.registry import (
    ProviderRegistry,
    ProviderSpec,
    ProviderType,
    ModelSpec,
    PROVIDERS,
    MODELS,
)


class TestProviderRegistry:
    def test_all_providers_registered(self):
        expected = {"nvidia", "groq", "openai", "anthropic", "deepseek", "gemini", "openrouter", "vllm"}
        actual = {p.value for p in PROVIDERS.keys()}
        assert expected == actual

    def test_model_catalog_not_empty(self):
        assert len(MODELS) >= 18

    def test_each_model_has_valid_provider(self):
        for key, spec in MODELS.items():
            assert spec.provider in ProviderType, f"Model {key} has invalid provider {spec.provider}"

    def test_get_model(self):
        registry = ProviderRegistry()
        spec = registry.get_model("qwen-coder-32b")
        assert spec.model_id == "qwen/qwen2.5-coder-32b-instruct"
        assert spec.provider == ProviderType.NVIDIA

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

    def test_nvidia_models_exist(self):
        nvidia_models = [k for k, v in MODELS.items() if v.provider == ProviderType.NVIDIA]
        assert len(nvidia_models) >= 5

    def test_openai_models_exist(self):
        openai_models = [k for k, v in MODELS.items() if v.provider == ProviderType.OPENAI]
        assert len(openai_models) >= 2

    def test_anthropic_models_exist(self):
        claude_models = [k for k, v in MODELS.items() if v.provider == ProviderType.ANTHROPIC]
        assert len(claude_models) >= 2

    def test_openrouter_models_exist(self):
        or_models = [k for k, v in MODELS.items() if v.provider == ProviderType.OPENROUTER]
        assert len(or_models) >= 3
