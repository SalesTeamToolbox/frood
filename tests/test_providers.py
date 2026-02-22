"""Tests for Phase 5: Provider registry."""

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
        expected = {"openai", "anthropic", "deepseek", "gemini", "openrouter", "vllm"}
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
