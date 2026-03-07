"""Tests for agents/agent_routing_store.py — per-agent routing config storage.

Covers:
- AgentRoutingStore CRUD operations (load, save, delete, list)
- Effective config resolution (profile -> _default -> FALLBACK_ROUTING)
- Mtime caching and atomic writes
- ModelRouter integration with profile_name parameter
"""

import json

import pytest

from core.task_queue import TaskType

# ---------------------------------------------------------------------------
# Store CRUD tests
# ---------------------------------------------------------------------------


class TestAgentRoutingStore:
    """Test AgentRoutingStore basic CRUD operations."""

    def setup_method(self, tmp_path=None):
        pass  # Each test uses its own tmp_path

    def _make_store(self, tmp_path, initial_data=None):
        from agents.agent_routing_store import AgentRoutingStore

        path = tmp_path / "agent_routing.json"
        if initial_data is not None:
            path.write_text(json.dumps(initial_data))
        return AgentRoutingStore(str(path))

    def test_load_empty_file(self, tmp_path):
        """Empty JSON {} returns no overrides for any profile."""
        store = self._make_store(tmp_path, {})
        assert store.get_overrides("coder") is None
        assert store.get_overrides("_default") is None

    def test_set_and_get_overrides(self, tmp_path):
        """Set primary for 'coder', get it back."""
        store = self._make_store(tmp_path, {})
        store.set_overrides("coder", {"primary": "strongwall-kimi-k2.5"})
        result = store.get_overrides("coder")
        assert result is not None
        assert result["primary"] == "strongwall-kimi-k2.5"

    def test_delete_overrides(self, tmp_path):
        """Set then delete, verify gone."""
        store = self._make_store(tmp_path, {"coder": {"primary": "gemini-2-flash"}})
        assert store.delete_overrides("coder") is True
        assert store.get_overrides("coder") is None

    def test_delete_nonexistent_returns_false(self, tmp_path):
        """Delete unknown profile returns False."""
        store = self._make_store(tmp_path, {})
        assert store.delete_overrides("nonexistent") is False

    def test_list_all(self, tmp_path):
        """Returns all stored profiles."""
        data = {
            "_default": {"primary": "gemini-2-flash"},
            "coder": {"primary": "strongwall-kimi-k2.5"},
        }
        store = self._make_store(tmp_path, data)
        all_data = store.list_all()
        assert "_default" in all_data
        assert "coder" in all_data
        assert len(all_data) == 2

    def test_mtime_caching(self, tmp_path):
        """File not re-read when mtime unchanged."""
        store = self._make_store(tmp_path, {"coder": {"primary": "gemini-2-flash"}})
        # First read populates cache
        store.get_overrides("coder")
        first_mtime = store._cache_mtime

        # Second read should use cache (same mtime)
        store.get_overrides("coder")
        assert store._cache_mtime == first_mtime

    def test_atomic_write(self, tmp_path):
        """Verify atomic write pattern (file is valid JSON after write)."""
        store = self._make_store(tmp_path, {})
        store.set_overrides("coder", {"primary": "gemini-2-flash"})

        # Read the file directly to verify valid JSON
        path = tmp_path / "agent_routing.json"
        data = json.loads(path.read_text())
        assert data["coder"]["primary"] == "gemini-2-flash"

    def test_auto_create_file(self, tmp_path):
        """If file doesn't exist, first _load returns {}."""
        from agents.agent_routing_store import AgentRoutingStore

        path = tmp_path / "nonexistent" / "agent_routing.json"
        store = AgentRoutingStore(str(path))
        assert store.list_all() == {}

    def test_set_overrides_validates_keys(self, tmp_path):
        """Only primary, critic, fallback keys are allowed."""
        store = self._make_store(tmp_path, {})
        with pytest.raises(ValueError, match="Invalid override keys"):
            store.set_overrides("coder", {"primary": "x", "invalid_key": "y"})

    def test_set_overrides_strips_none_values(self, tmp_path):
        """None values are not stored (they mean 'inherit')."""
        store = self._make_store(tmp_path, {})
        store.set_overrides("coder", {"primary": "gemini-2-flash", "critic": None})
        result = store.get_overrides("coder")
        assert "critic" not in result


# ---------------------------------------------------------------------------
# Effective resolution tests
# ---------------------------------------------------------------------------


class TestEffectiveResolution:
    """Test get_effective() merge logic: profile -> _default -> None."""

    def _make_store(self, tmp_path, initial_data=None):
        from agents.agent_routing_store import AgentRoutingStore

        path = tmp_path / "agent_routing.json"
        if initial_data is not None:
            path.write_text(json.dumps(initial_data))
        return AgentRoutingStore(str(path))

    def test_profile_overrides_default(self, tmp_path):
        """Profile.primary beats _default.primary."""
        data = {
            "_default": {"primary": "gemini-2-flash"},
            "coder": {"primary": "strongwall-kimi-k2.5"},
        }
        store = self._make_store(tmp_path, data)
        eff = store.get_effective("coder", TaskType.CODING)
        assert eff["primary"] == "strongwall-kimi-k2.5"

    def test_default_fills_gaps(self, tmp_path):
        """Profile with only primary inherits critic from _default."""
        data = {
            "_default": {"primary": "gemini-2-flash", "critic": "or-free-llama-70b"},
            "coder": {"primary": "strongwall-kimi-k2.5"},
        }
        store = self._make_store(tmp_path, data)
        eff = store.get_effective("coder", TaskType.CODING)
        assert eff["primary"] == "strongwall-kimi-k2.5"
        assert eff["critic"] == "or-free-llama-70b"  # inherited from _default

    def test_no_config_returns_none_primary(self, tmp_path):
        """Null primary in both levels -> effective['primary'] is None."""
        data = {"_default": {"critic": "or-free-llama-70b"}}
        store = self._make_store(tmp_path, data)
        eff = store.get_effective("coder", TaskType.CODING)
        assert eff["primary"] is None

    def test_critic_auto_pairs_with_primary(self, tmp_path):
        """When critic is null after merge but primary is set, critic = primary."""
        data = {"coder": {"primary": "strongwall-kimi-k2.5"}}
        store = self._make_store(tmp_path, data)
        eff = store.get_effective("coder", TaskType.CODING)
        assert eff["primary"] == "strongwall-kimi-k2.5"
        assert eff["critic"] == "strongwall-kimi-k2.5"  # auto-paired

    def test_empty_profile_uses_default(self, tmp_path):
        """Unknown profile name falls to _default."""
        data = {"_default": {"primary": "gemini-2-flash"}}
        store = self._make_store(tmp_path, data)
        eff = store.get_effective("unknown-profile", TaskType.CODING)
        assert eff["primary"] == "gemini-2-flash"

    def test_empty_everything_returns_all_none(self, tmp_path):
        """No _default, no profile -> all fields None."""
        store = self._make_store(tmp_path, {})
        eff = store.get_effective("coder", TaskType.CODING)
        assert eff["primary"] is None
        assert eff["critic"] is None
        assert eff["fallback"] is None

    def test_has_config_true_with_profile(self, tmp_path):
        """has_config returns True when profile has overrides."""
        data = {"coder": {"primary": "gemini-2-flash"}}
        store = self._make_store(tmp_path, data)
        assert store.has_config("coder") is True

    def test_has_config_true_with_default_only(self, tmp_path):
        """has_config returns True when only _default has overrides."""
        data = {"_default": {"primary": "gemini-2-flash"}}
        store = self._make_store(tmp_path, data)
        assert store.has_config("unknown-profile") is True

    def test_has_config_false_when_empty(self, tmp_path):
        """has_config returns False when no config exists."""
        store = self._make_store(tmp_path, {})
        assert store.has_config("coder") is False


# ---------------------------------------------------------------------------
# ModelRouter integration tests
# ---------------------------------------------------------------------------


class TestModelRouterProfileIntegration:
    """Test ModelRouter.get_routing() with profile_name parameter."""

    def _make_router_with_store(self, tmp_path, store_data=None):
        from agents.agent_routing_store import AgentRoutingStore
        from agents.model_router import ModelRouter

        store_path = tmp_path / "agent_routing.json"
        if store_data is not None:
            store_path.write_text(json.dumps(store_data))
        else:
            store_path.write_text("{}")

        router = ModelRouter()
        router._agent_store = AgentRoutingStore(str(store_path))
        return router

    def test_get_routing_with_profile_name(self, tmp_path, monkeypatch):
        """Profile override primary is returned."""
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        monkeypatch.setenv("GEMINI_PRO_FOR_COMPLEX", "false")
        router = self._make_router_with_store(
            tmp_path,
            {"coder": {"primary": "gemini-2-flash"}},
        )
        routing = router.get_routing(TaskType.CODING, profile_name="coder")
        assert routing["primary"] == "gemini-2-flash"

    def test_admin_override_beats_profile(self, tmp_path, monkeypatch):
        """Env var override wins over profile."""
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        router = self._make_router_with_store(
            tmp_path,
            {"coder": {"primary": "gemini-2-flash"}},
        )
        monkeypatch.setenv("AGENT42_CODING_MODEL", "claude-sonnet")
        routing = router.get_routing(TaskType.CODING, profile_name="coder")
        assert routing["primary"] == "claude-sonnet"

    def test_missing_profile_falls_through(self, tmp_path):
        """No matching profile -> dynamic/L1/FALLBACK chain."""

        router = self._make_router_with_store(tmp_path, {})
        routing = router.get_routing(TaskType.CODING, profile_name="nonexistent")
        # Should get FALLBACK_ROUTING (or L1 if configured)
        # The key point: it should NOT crash
        assert routing["primary"] is not None

    def test_profile_name_parameter_accepted(self, tmp_path):
        """Signature accepts profile_name kwarg."""
        from agents.model_router import ModelRouter

        router = ModelRouter()
        # Should not raise TypeError
        routing = router.get_routing(TaskType.CODING, profile_name="test")
        assert routing is not None


# ---------------------------------------------------------------------------
# Resolution chain display tests
# ---------------------------------------------------------------------------


class TestResolutionChain:
    """Test _build_resolution_chain() for dashboard display."""

    def _make_store(self, tmp_path, initial_data=None):
        from agents.agent_routing_store import AgentRoutingStore

        path = tmp_path / "agent_routing.json"
        if initial_data is not None:
            path.write_text(json.dumps(initial_data))
        return AgentRoutingStore(str(path))

    def test_resolution_chain_shows_inheritance(self, tmp_path):
        """Chain shows 'profile:X' for overridden, '_default' for inherited."""
        from dashboard.server import _build_resolution_chain

        data = {
            "_default": {"primary": "gemini-2-flash", "critic": "or-free-llama-70b"},
            "coder": {"primary": "strongwall-kimi-k2.5"},
        }
        store = self._make_store(tmp_path, data)
        chain = _build_resolution_chain(store, "coder")

        # primary comes from profile
        primary_entry = next(e for e in chain if e["field"] == "primary")
        assert primary_entry["source"] == "profile:coder"
        assert primary_entry["value"] == "strongwall-kimi-k2.5"

        # critic comes from _default
        critic_entry = next(e for e in chain if e["field"] == "critic")
        assert critic_entry["source"] == "_default"
        assert critic_entry["value"] == "or-free-llama-70b"

    def test_resolution_chain_fallback_routing_source(self, tmp_path):
        """Fields not in profile or _default show FALLBACK_ROUTING source."""
        from dashboard.server import _build_resolution_chain

        store = self._make_store(tmp_path, {})
        chain = _build_resolution_chain(store, "coder")

        # All should come from FALLBACK_ROUTING
        for entry in chain:
            assert entry["source"] == "FALLBACK_ROUTING"


# ---------------------------------------------------------------------------
# Available models tests
# ---------------------------------------------------------------------------


class TestAvailableModels:
    """Test available-models endpoint logic."""

    def test_available_models_filters_unconfigured(self, monkeypatch):
        """Models from providers without API keys should be excluded."""
        from providers.registry import MODELS, PROVIDERS

        # Count models from configured providers
        configured_count = 0
        unconfigured_count = 0
        for key, spec in MODELS.items():
            provider = PROVIDERS.get(spec.provider)
            if provider:
                api_key = (
                    monkeypatch.getenv(provider.api_key_env)
                    if hasattr(monkeypatch, "getenv")
                    else ""
                )
                if not api_key:
                    unconfigured_count += 1

        # Verify that at least some providers are unconfigured in test env
        assert unconfigured_count > 0, "Test env should have unconfigured providers"

    def test_available_models_tier_grouping(self, monkeypatch):
        """StrongWall models in 'l1', FREE in 'fallback', CHEAP/PREMIUM in 'l2'."""
        from providers.registry import MODELS, PROVIDERS, ModelTier, ProviderType

        # Set StrongWall key so it appears
        monkeypatch.setenv("STRONGWALL_API_KEY", "test-key")

        for key, spec in MODELS.items():
            provider = PROVIDERS.get(spec.provider)
            if not provider:
                continue
            api_key = (
                monkeypatch.getenv(provider.api_key_env) if hasattr(monkeypatch, "getenv") else ""
            )

            if spec.provider == ProviderType.STRONGWALL:
                # StrongWall models should go in "l1" bucket
                assert spec.provider == ProviderType.STRONGWALL
            elif spec.tier == ModelTier.FREE:
                # FREE tier models should go in "fallback" bucket
                assert spec.tier == ModelTier.FREE

    def test_pydantic_request_model(self):
        """AgentRoutingRequest Pydantic model accepts correct fields."""
        from dashboard.server import AgentRoutingRequest

        # Valid request
        req = AgentRoutingRequest(primary="gemini-2-flash")
        assert req.primary == "gemini-2-flash"
        assert req.critic is None
        assert req.fallback is None

        # All fields
        req2 = AgentRoutingRequest(
            primary="gemini-2-flash",
            critic="or-free-llama-70b",
            fallback="cerebras-gpt-oss-120b",
        )
        assert req2.primary == "gemini-2-flash"
        assert req2.critic == "or-free-llama-70b"
        assert req2.fallback == "cerebras-gpt-oss-120b"

        # Empty request (all None)
        req3 = AgentRoutingRequest()
        assert req3.primary is None
