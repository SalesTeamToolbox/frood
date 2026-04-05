"""
Tests for Abacus AI RouteLLM provider integration.

Covers:
- Config field and key store registration (ABACUS-03)
- PROVIDER_MODELS entry and model mappings (ABACUS-02)
- Tiered routing selection (ABACUS-02)
- Agent runtime _build_env for Abacus (ABACUS-01)
- AbacusApiClient initialization and error handling (ABACUS-01)
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# TestAbacusConfig
# ---------------------------------------------------------------------------


class TestAbacusConfig:
    """Verify ABACUS_API_KEY is wired into Settings and key store."""

    def test_settings_has_abacus_api_key(self):
        from core.config import Settings

        s = Settings()
        assert hasattr(s, "abacus_api_key"), "Settings must have abacus_api_key field"
        assert isinstance(s.abacus_api_key, str)

    def test_abacus_key_in_admin_configurable(self):
        from core.key_store import ADMIN_CONFIGURABLE_KEYS

        assert "ABACUS_API_KEY" in ADMIN_CONFIGURABLE_KEYS, (
            "ABACUS_API_KEY must be in ADMIN_CONFIGURABLE_KEYS for dashboard config"
        )

    def test_abacus_api_key_loads_from_env(self, monkeypatch):
        monkeypatch.setenv("ABACUS_API_KEY", "test-abacus-key-12345")
        from core.config import Settings

        s = Settings.from_env()
        assert s.abacus_api_key == "test-abacus-key-12345"

    def test_abacus_api_key_defaults_to_empty(self, monkeypatch):
        monkeypatch.delenv("ABACUS_API_KEY", raising=False)
        from core.config import Settings

        s = Settings.from_env()
        assert s.abacus_api_key == ""


# ---------------------------------------------------------------------------
# TestAbacusProviderModels
# ---------------------------------------------------------------------------


class TestAbacusProviderModels:
    """Verify PROVIDER_MODELS has correct Abacus entries."""

    def test_abacus_in_provider_models(self):
        from core.agent_manager import PROVIDER_MODELS

        assert "abacus" in PROVIDER_MODELS, "PROVIDER_MODELS must include 'abacus'"

    def test_abacus_has_required_categories(self):
        from core.agent_manager import PROVIDER_MODELS

        required = ["fast", "general", "reasoning", "coding", "content", "research", "lightweight"]
        abacus = PROVIDER_MODELS["abacus"]
        for category in required:
            assert category in abacus, f"PROVIDER_MODELS['abacus'] missing category: {category}"

    def test_abacus_free_tier_models(self):
        from core.agent_manager import PROVIDER_MODELS

        abacus = PROVIDER_MODELS["abacus"]
        assert abacus["fast"] == "gemini-3-flash", "fast should map to gemini-3-flash (free tier)"
        assert abacus["general"] == "gpt-5-mini", "general should map to gpt-5-mini (free tier)"
        assert abacus["lightweight"] == "llama-4", "lightweight should map to llama-4 (free tier)"

    def test_abacus_premium_models(self):
        from core.agent_manager import PROVIDER_MODELS

        abacus = PROVIDER_MODELS["abacus"]
        assert abacus["reasoning"] == "claude-opus-4-6", "reasoning should map to claude-opus-4-6"
        assert abacus["coding"] == "claude-sonnet-4-6", "coding should map to claude-sonnet-4-6"

    def test_resolve_model_abacus_coding(self):
        from core.agent_manager import resolve_model

        assert resolve_model("abacus", "coding") == "claude-sonnet-4-6"

    def test_resolve_model_abacus_fast(self):
        from core.agent_manager import resolve_model

        assert resolve_model("abacus", "fast") == "gemini-3-flash"

    def test_resolve_model_abacus_lightweight(self):
        from core.agent_manager import resolve_model

        assert resolve_model("abacus", "lightweight") == "llama-4"

    def test_resolve_model_abacus_unknown_category_falls_back_to_general(self):
        from core.agent_manager import resolve_model

        # Unknown category should fall back to "general" mapping
        result = resolve_model("abacus", "nonexistent-category")
        assert result == "gpt-5-mini"  # "general" mapping for abacus


# ---------------------------------------------------------------------------
# TestAbacusRouting (async)
# ---------------------------------------------------------------------------


class TestAbacusRouting:
    """Verify tiered routing selects Abacus when ABACUS_API_KEY is set."""

    @pytest.mark.asyncio
    async def test_abacus_provider_selected_when_key_set(self, monkeypatch):
        monkeypatch.delenv("CLAUDECODE_SUBSCRIPTION_TOKEN", raising=False)
        monkeypatch.delenv("SYNTHETIC_API_KEY", raising=False)
        monkeypatch.setenv("ABACUS_API_KEY", "test-abacus-key")

        from core.tiered_routing_bridge import TieredRoutingBridge

        bridge = TieredRoutingBridge(reward_system=None)
        decision = await bridge.resolve(role="engineer", agent_id="test-agent")
        assert decision.provider == "abacus", (
            f"Expected 'abacus' provider, got '{decision.provider}'"
        )

    @pytest.mark.asyncio
    async def test_abacus_not_selected_when_synthetic_key_set(self, monkeypatch):
        monkeypatch.delenv("CLAUDECODE_SUBSCRIPTION_TOKEN", raising=False)
        monkeypatch.setenv("SYNTHETIC_API_KEY", "syn-test-key")
        monkeypatch.setenv("ABACUS_API_KEY", "test-abacus-key")

        from core.tiered_routing_bridge import TieredRoutingBridge

        bridge = TieredRoutingBridge(reward_system=None)
        decision = await bridge.resolve(role="engineer", agent_id="test-agent")
        assert decision.provider == "synthetic", (
            f"Synthetic should take priority over Abacus, got '{decision.provider}'"
        )

    @pytest.mark.asyncio
    async def test_abacus_not_selected_when_claudecode_token_set(self, monkeypatch):
        monkeypatch.setenv("CLAUDECODE_SUBSCRIPTION_TOKEN", "ccst-test-token")
        monkeypatch.delenv("SYNTHETIC_API_KEY", raising=False)
        monkeypatch.setenv("ABACUS_API_KEY", "test-abacus-key")

        from core.tiered_routing_bridge import TieredRoutingBridge

        bridge = TieredRoutingBridge(reward_system=None)
        decision = await bridge.resolve(role="engineer", agent_id="test-agent")
        assert decision.provider == "claudecode", (
            f"ClaudeCode should take priority over Abacus, got '{decision.provider}'"
        )

    @pytest.mark.asyncio
    async def test_abacus_falls_back_to_anthropic_when_no_key(self, monkeypatch):
        monkeypatch.delenv("CLAUDECODE_SUBSCRIPTION_TOKEN", raising=False)
        monkeypatch.delenv("SYNTHETIC_API_KEY", raising=False)
        monkeypatch.delenv("ABACUS_API_KEY", raising=False)

        from core.tiered_routing_bridge import TieredRoutingBridge

        bridge = TieredRoutingBridge(reward_system=None)
        decision = await bridge.resolve(role="engineer", agent_id="test-agent")
        assert decision.provider == "anthropic", (
            f"Should fall back to anthropic, got '{decision.provider}'"
        )

    @pytest.mark.asyncio
    async def test_abacus_routing_returns_correct_model(self, monkeypatch):
        monkeypatch.delenv("CLAUDECODE_SUBSCRIPTION_TOKEN", raising=False)
        monkeypatch.delenv("SYNTHETIC_API_KEY", raising=False)
        monkeypatch.setenv("ABACUS_API_KEY", "test-abacus-key")

        from core.tiered_routing_bridge import TieredRoutingBridge

        bridge = TieredRoutingBridge(reward_system=None)
        # engineer role maps to "coding" category
        decision = await bridge.resolve(role="engineer", agent_id="test-agent")
        assert decision.provider == "abacus"
        assert decision.model == "claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# TestAbacusRuntime
# ---------------------------------------------------------------------------


class TestAbacusRuntime:
    """Verify _build_env sets correct env vars for Abacus provider."""

    def test_build_env_abacus_provider(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ABACUS_API_KEY", "abacus-key-12345")

        from core.agent_runtime import AgentRuntime

        runtime = AgentRuntime(workspace=str(tmp_path))
        env = runtime._build_env({"provider": "abacus", "model": "gemini-3-flash"})

        assert env["ANTHROPIC_BASE_URL"] == "https://routellm.abacus.ai/v1"
        assert env["ANTHROPIC_MODEL"] == "gemini-3-flash"
        assert env["ANTHROPIC_API_KEY"] == "abacus-key-12345"

    def test_build_env_abacus_uses_provider_url_override(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ABACUS_API_KEY", "abacus-key-12345")

        from core.agent_runtime import AgentRuntime

        runtime = AgentRuntime(workspace=str(tmp_path))
        env = runtime._build_env(
            {
                "provider": "abacus",
                "model": "gpt-5-mini",
                "provider_url": "https://custom.abacus.ai/v1",
            }
        )

        assert env["ANTHROPIC_BASE_URL"] == "https://custom.abacus.ai/v1"
        assert env["ANTHROPIC_MODEL"] == "gpt-5-mini"

    def test_build_env_abacus_no_model_skips_model_env(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ABACUS_API_KEY", "abacus-key-12345")

        from core.agent_runtime import AgentRuntime

        runtime = AgentRuntime(workspace=str(tmp_path))
        env = runtime._build_env({"provider": "abacus"})

        assert env["ANTHROPIC_BASE_URL"] == "https://routellm.abacus.ai/v1"
        assert "routellm.abacus.ai" in env["ANTHROPIC_BASE_URL"]


# ---------------------------------------------------------------------------
# TestAbacusApiClient
# ---------------------------------------------------------------------------


class TestAbacusApiClient:
    """Verify AbacusApiClient initialization and error behavior."""

    def test_client_init(self):
        from providers.abacus_api import AbacusApiClient

        c = AbacusApiClient()
        assert c._base_url == "https://routellm.abacus.ai/v1"
        assert "routellm.abacus.ai" in c._base_url

    def test_get_api_key_from_env(self, monkeypatch):
        monkeypatch.setenv("ABACUS_API_KEY", "env-abacus-key")

        from providers.abacus_api import AbacusApiClient

        c = AbacusApiClient()
        key = c._get_api_key()
        assert key == "env-abacus-key"

    def test_get_api_key_empty_when_not_set(self, monkeypatch):
        monkeypatch.delenv("ABACUS_API_KEY", raising=False)

        from providers.abacus_api import AbacusApiClient

        c = AbacusApiClient()
        key = c._get_api_key()
        assert key == ""

    @pytest.mark.asyncio
    async def test_chat_completion_no_key(self, monkeypatch):
        """Without API key, chat_completion returns error dict."""
        monkeypatch.delenv("ABACUS_API_KEY", raising=False)

        from providers.abacus_api import AbacusApiClient

        c = AbacusApiClient()
        result = await c.chat_completion(
            model="gemini-3-flash",
            messages=[{"role": "user", "content": "Hello"}],
        )
        assert "error" in result
        assert "ABACUS_API_KEY" in result["error"] or "No" in result["error"]

    @pytest.mark.asyncio
    async def test_chat_completion_with_mock_http(self, monkeypatch):
        """With API key and mocked HTTP, chat_completion returns parsed JSON."""
        monkeypatch.setenv("ABACUS_API_KEY", "mock-abacus-key")

        mock_response = {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "choices": [{"message": {"role": "assistant", "content": "Hello!"}}],
        }

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json = MagicMock(return_value=mock_response)

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("providers.abacus_api.httpx.AsyncClient", return_value=mock_client):
            from providers.abacus_api import AbacusApiClient

            c = AbacusApiClient()
            result = await c.chat_completion(
                model="gemini-3-flash",
                messages=[{"role": "user", "content": "Hello"}],
            )

        assert "error" not in result
        assert result.get("id") == "chatcmpl-test"

    @pytest.mark.asyncio
    async def test_list_models_no_key(self, monkeypatch):
        """Without API key, list_models returns empty list."""
        monkeypatch.delenv("ABACUS_API_KEY", raising=False)

        from providers.abacus_api import AbacusApiClient

        c = AbacusApiClient()
        result = await c.list_models()
        assert result == []

    @pytest.mark.asyncio
    async def test_chat_completion_http_error_returns_error_dict(self, monkeypatch):
        """HTTP status error from Abacus API is caught and returned as error dict."""
        monkeypatch.setenv("ABACUS_API_KEY", "mock-abacus-key")

        import httpx as _httpx

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock(
            side_effect=_httpx.HTTPStatusError(
                message="Unauthorized",
                request=MagicMock(),
                response=MagicMock(status_code=401),
            )
        )

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("providers.abacus_api.httpx.AsyncClient", return_value=mock_client):
            from providers.abacus_api import AbacusApiClient

            c = AbacusApiClient()
            result = await c.chat_completion(
                model="gemini-3-flash",
                messages=[{"role": "user", "content": "Hello"}],
            )

        assert "error" in result
        assert "401" in result["error"] or "Unauthorized" in result["error"]
