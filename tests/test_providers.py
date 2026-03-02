"""Tests for Phase 5: Provider registry."""

import os
from unittest.mock import patch, MagicMock

import pytest

from providers.registry import (
    MODELS,
    PROVIDERS,
    ModelSpec,
    ModelTier,
    ProviderRegistry,
    ProviderSpec,
    ProviderType,
)


class TestProviderRegistry:
    def test_all_providers_registered(self):
        expected = {"openai", "anthropic", "deepseek", "gemini", "openrouter", "vllm", "cerebras", "groq", "mistral", "mistral_codestral", "sambanova", "together"}
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


class TestMistralRegistration:
    """Phase 3: Mistral dual-provider registration tests."""

    def test_mistral_provider_registered(self):
        """MIST-01: ProviderType.MISTRAL is in PROVIDERS with correct base_url and api_key_env."""
        spec = PROVIDERS[ProviderType.MISTRAL]
        assert spec.base_url == "https://api.mistral.ai/v1"
        assert spec.api_key_env == "MISTRAL_API_KEY"
        assert spec.display_name == "Mistral La Plateforme"

    def test_mistral_codestral_provider_registered(self):
        """MIST-02: ProviderType.MISTRAL_CODESTRAL is in PROVIDERS with correct base_url and api_key_env."""
        spec = PROVIDERS[ProviderType.MISTRAL_CODESTRAL]
        assert spec.base_url == "https://codestral.mistral.ai/v1"
        assert spec.api_key_env == "CODESTRAL_API_KEY"
        assert spec.display_name == "Mistral Codestral (free)"

    def test_codestral_model_registered(self):
        """MIST-03: codestral-latest is registered on MISTRAL_CODESTRAL provider as FREE."""
        from providers.registry import ModelTier

        spec = MODELS["mistral-codestral"]
        assert spec.model_id == "codestral-latest"
        assert spec.provider == ProviderType.MISTRAL_CODESTRAL
        assert spec.tier == ModelTier.FREE
        assert spec.max_context_tokens == 32000

    def test_la_plateforme_models_registered(self):
        """MIST-04: mistral-large and mistral-small are registered on MISTRAL provider as CHEAP."""
        from providers.registry import ModelTier

        for key, expected_id in [
            ("mistral-large", "mistral-large-latest"),
            ("mistral-small", "mistral-small-latest"),
        ]:
            spec = MODELS[key]
            assert spec.model_id == expected_id, f"{key} model_id mismatch"
            assert spec.provider == ProviderType.MISTRAL
            assert spec.tier == ModelTier.CHEAP, f"{key} should be CHEAP tier"
            assert spec.max_context_tokens == 128000

    def test_mistral_client_builds_with_key(self):
        """Client builds when MISTRAL_API_KEY is set."""
        registry = ProviderRegistry()
        with patch.dict(os.environ, {"MISTRAL_API_KEY": "test-key-1234"}):
            client = registry.get_client(ProviderType.MISTRAL)
            assert client is not None
            assert client.base_url == "https://api.mistral.ai/v1/"

    def test_codestral_client_builds_with_key(self):
        """Client builds when CODESTRAL_API_KEY is set."""
        registry = ProviderRegistry()
        with patch.dict(os.environ, {"CODESTRAL_API_KEY": "test-key-5678"}):
            client = registry.get_client(ProviderType.MISTRAL_CODESTRAL)
            assert client is not None
            assert client.base_url == "https://codestral.mistral.ai/v1/"

    def test_mistral_client_raises_without_key(self):
        """Client raises ValueError when MISTRAL_API_KEY is not set."""
        registry = ProviderRegistry()
        registry.invalidate_client(ProviderType.MISTRAL)
        with patch.dict(os.environ, {"MISTRAL_API_KEY": ""}, clear=False):
            with pytest.raises(ValueError, match="MISTRAL_API_KEY not set"):
                registry.get_client(ProviderType.MISTRAL)

    def test_codestral_client_raises_without_key(self):
        """Client raises ValueError when CODESTRAL_API_KEY is not set."""
        registry = ProviderRegistry()
        registry.invalidate_client(ProviderType.MISTRAL_CODESTRAL)
        with patch.dict(os.environ, {"CODESTRAL_API_KEY": ""}, clear=False):
            with pytest.raises(ValueError, match="CODESTRAL_API_KEY not set"):
                registry.get_client(ProviderType.MISTRAL_CODESTRAL)


class TestSambanovaRegistration:
    """Phase 4: SambaNova provider registration tests."""

    def test_sambanova_provider_registered(self):
        """SAMB-01: ProviderType.SAMBANOVA in PROVIDERS with correct base_url and api_key_env."""
        spec = PROVIDERS[ProviderType.SAMBANOVA]
        assert spec.base_url == "https://api.sambanova.ai/v1"
        assert spec.api_key_env == "SAMBANOVA_API_KEY"
        assert spec.display_name == "SambaNova"

    def test_sambanova_models_registered(self):
        """SAMB-02: Both SambaNova models registered with correct model_ids and CHEAP tier."""
        for key, expected_id in [
            ("sambanova-llama-70b", "Meta-Llama-3.3-70B-Instruct"),
            ("sambanova-deepseek-v3", "DeepSeek-V3-0324"),
        ]:
            spec = MODELS[key]
            assert spec.model_id == expected_id, f"{key} model_id mismatch"
            assert spec.provider == ProviderType.SAMBANOVA
            assert spec.tier == ModelTier.CHEAP, f"{key} should be CHEAP tier"

    def test_sambanova_models_all_cheap_tier(self):
        """All SambaNova models are CHEAP tier (credits required)."""
        samb_models = [k for k, v in MODELS.items() if v.provider == ProviderType.SAMBANOVA]
        assert len(samb_models) == 2
        for key in samb_models:
            assert MODELS[key].tier == ModelTier.CHEAP, f"{key} should be CHEAP"

    def test_sambanova_context_windows(self):
        """SAMB-02: Both SambaNova models have 128K context window."""
        for key in ["sambanova-llama-70b", "sambanova-deepseek-v3"]:
            assert MODELS[key].max_context_tokens == 131072, f"{key} wrong context"

    def test_sambanova_client_builds_with_key(self):
        """Client builds when SAMBANOVA_API_KEY is set."""
        registry = ProviderRegistry()
        with patch.dict(os.environ, {"SAMBANOVA_API_KEY": "test-key-1234"}):
            client = registry.get_client(ProviderType.SAMBANOVA)
            assert client is not None
            assert client.base_url == "https://api.sambanova.ai/v1/"

    def test_sambanova_client_raises_without_key(self):
        """INFR-05: Client raises ValueError when SAMBANOVA_API_KEY is not set."""
        registry = ProviderRegistry()
        registry.invalidate_client(ProviderType.SAMBANOVA)
        with patch.dict(os.environ, {"SAMBANOVA_API_KEY": ""}, clear=False):
            with pytest.raises(ValueError, match="SAMBANOVA_API_KEY not set"):
                registry.get_client(ProviderType.SAMBANOVA)


class TestSambanovaTransforms:
    """Phase 4: SambaNova request transform tests (SAMB-03, SAMB-04, SAMB-05 / INFR-03 / TEST-03)."""

    @pytest.mark.asyncio
    async def test_temperature_clamped_to_1_in_complete(self):
        """SAMB-03: Temperature > 1.0 is clamped to 1.0 for SambaNova in complete()."""
        registry = ProviderRegistry()
        captured_kwargs = {}

        async def mock_create(**kwargs):
            captured_kwargs.update(kwargs)
            mock_resp = MagicMock()
            mock_resp.choices = [MagicMock()]
            mock_resp.choices[0].message.content = "ok"
            mock_resp.usage = None
            return mock_resp

        with patch.dict(os.environ, {"SAMBANOVA_API_KEY": "test-key"}):
            client = registry.get_client(ProviderType.SAMBANOVA)
            with patch.object(client.chat.completions, "create", side_effect=mock_create):
                await registry.complete(
                    "sambanova-llama-70b",
                    messages=[{"role": "user", "content": "hi"}],
                    temperature=1.5,
                )
        assert captured_kwargs["temperature"] <= 1.0, (
            f"Expected temp <= 1.0, got {captured_kwargs['temperature']}"
        )

    @pytest.mark.asyncio
    async def test_temperature_not_clamped_for_other_providers(self):
        """SAMB-03 negative: Temperature > 1.0 is NOT clamped for non-SambaNova providers."""
        registry = ProviderRegistry()
        captured_kwargs = {}

        async def mock_create(**kwargs):
            captured_kwargs.update(kwargs)
            mock_resp = MagicMock()
            mock_resp.choices = [MagicMock()]
            mock_resp.choices[0].message.content = "ok"
            mock_resp.usage = None
            return mock_resp

        with patch.dict(os.environ, {"CEREBRAS_API_KEY": "test-key"}):
            client = registry.get_client(ProviderType.CEREBRAS)
            with patch.object(client.chat.completions, "create", side_effect=mock_create):
                await registry.complete(
                    "cerebras-llama-8b",
                    messages=[{"role": "user", "content": "hi"}],
                    temperature=1.5,
                )
        assert captured_kwargs["temperature"] == pytest.approx(1.5), (
            f"Non-SambaNova provider should not clamp temp, got {captured_kwargs['temperature']}"
        )

    @pytest.mark.asyncio
    async def test_stream_false_enforced_when_tools_present(self):
        """SAMB-04: stream=False is set when SambaNova receives tool-bearing requests."""
        registry = ProviderRegistry()
        captured_kwargs = {}

        async def mock_create(**kwargs):
            captured_kwargs.update(kwargs)
            mock_resp = MagicMock()
            mock_resp.choices = [MagicMock()]
            mock_resp.choices[0].message.content = "ok"
            mock_resp.choices[0].message.tool_calls = None
            mock_resp.usage = None
            return mock_resp

        tools = [{"type": "function", "function": {"name": "test_tool", "parameters": {}}}]
        with patch.dict(os.environ, {"SAMBANOVA_API_KEY": "test-key"}):
            client = registry.get_client(ProviderType.SAMBANOVA)
            with patch.object(client.chat.completions, "create", side_effect=mock_create):
                await registry.complete_with_tools(
                    "sambanova-llama-70b",
                    messages=[{"role": "user", "content": "hi"}],
                    tools=tools,
                )
        assert captured_kwargs.get("stream") is False, (
            f"Expected stream=False, got {captured_kwargs.get('stream')}"
        )

    @pytest.mark.asyncio
    async def test_strict_true_removed_from_tool_definitions(self):
        """SAMB-05: strict: true is set to false in tool definitions for SambaNova."""
        registry = ProviderRegistry()
        captured_kwargs = {}

        async def mock_create(**kwargs):
            captured_kwargs.update(kwargs)
            mock_resp = MagicMock()
            mock_resp.choices = [MagicMock()]
            mock_resp.choices[0].message.content = "ok"
            mock_resp.choices[0].message.tool_calls = None
            mock_resp.usage = None
            return mock_resp

        tools = [{"type": "function", "function": {"name": "test_tool", "strict": True, "parameters": {}}}]
        with patch.dict(os.environ, {"SAMBANOVA_API_KEY": "test-key"}):
            client = registry.get_client(ProviderType.SAMBANOVA)
            with patch.object(client.chat.completions, "create", side_effect=mock_create):
                await registry.complete_with_tools(
                    "sambanova-llama-70b",
                    messages=[{"role": "user", "content": "hi"}],
                    tools=tools,
                )
        sent_tools = captured_kwargs.get("tools", [])
        for tool in sent_tools:
            fn_strict = tool.get("function", {}).get("strict")
            assert fn_strict is not True, (
                f"strict should not be True in sent tools, got {fn_strict}"
            )

    @pytest.mark.asyncio
    async def test_caller_tool_list_not_mutated(self):
        """SAMB-05: The transform must not mutate the caller's original tool list."""
        registry = ProviderRegistry()

        async def mock_create(**kwargs):
            mock_resp = MagicMock()
            mock_resp.choices = [MagicMock()]
            mock_resp.choices[0].message.content = "ok"
            mock_resp.choices[0].message.tool_calls = None
            mock_resp.usage = None
            return mock_resp

        original_tools = [{"type": "function", "function": {"name": "my_tool", "strict": True, "parameters": {}}}]
        # Deep copy for comparison — original_tools must remain unchanged after the call
        import copy
        tools_snapshot = copy.deepcopy(original_tools)

        with patch.dict(os.environ, {"SAMBANOVA_API_KEY": "test-key"}):
            client = registry.get_client(ProviderType.SAMBANOVA)
            with patch.object(client.chat.completions, "create", side_effect=mock_create):
                await registry.complete_with_tools(
                    "sambanova-llama-70b",
                    messages=[{"role": "user", "content": "hi"}],
                    tools=original_tools,
                )
        # Original list must not be mutated
        assert original_tools == tools_snapshot, (
            "Caller's tool list was mutated by the SambaNova strict-removal transform"
        )


class TestTogetherRegistration:
    """Phase 5: Together AI provider registration tests."""

    def test_together_provider_registered(self):
        """TOGR-01: ProviderType.TOGETHER in PROVIDERS with correct base_url and api_key_env."""
        spec = PROVIDERS[ProviderType.TOGETHER]
        assert spec.base_url == "https://api.together.xyz/v1"
        assert spec.api_key_env == "TOGETHER_API_KEY"
        assert spec.display_name == "Together AI"

    def test_together_models_registered(self):
        """TOGR-02: Both Together AI models registered with correct model_ids and CHEAP tier."""
        for key, expected_id in [
            ("together-deepseek-v3", "deepseek-ai/DeepSeek-V3"),
            ("together-llama-70b", "meta-llama/Llama-3.3-70B-Instruct-Turbo"),
        ]:
            spec = MODELS[key]
            assert spec.model_id == expected_id, f"{key} model_id mismatch"
            assert spec.provider == ProviderType.TOGETHER
            assert spec.tier == ModelTier.CHEAP, f"{key} should be CHEAP tier"

    def test_together_models_all_cheap_tier(self):
        """All Together AI models are CHEAP tier (credits required)."""
        together_models = [k for k, v in MODELS.items() if v.provider == ProviderType.TOGETHER]
        assert len(together_models) == 2
        for key in together_models:
            assert MODELS[key].tier == ModelTier.CHEAP, f"{key} should be CHEAP"

    def test_together_context_windows(self):
        """TOGR-02: Together AI models have appropriate context windows."""
        assert MODELS["together-deepseek-v3"].max_context_tokens == 128000
        assert MODELS["together-llama-70b"].max_context_tokens == 131000

    def test_together_client_builds_with_key(self):
        """Client builds when TOGETHER_API_KEY is set."""
        registry = ProviderRegistry()
        with patch.dict(os.environ, {"TOGETHER_API_KEY": "test-key-1234"}):
            client = registry.get_client(ProviderType.TOGETHER)
            assert client is not None
            assert client.base_url == "https://api.together.xyz/v1/"

    def test_together_client_raises_without_key(self):
        """INFR-05: Client raises ValueError when TOGETHER_API_KEY is not set."""
        registry = ProviderRegistry()
        registry.invalidate_client(ProviderType.TOGETHER)
        with patch.dict(os.environ, {"TOGETHER_API_KEY": ""}, clear=False):
            with pytest.raises(ValueError, match="TOGETHER_API_KEY not set"):
                registry.get_client(ProviderType.TOGETHER)
