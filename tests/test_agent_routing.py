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

    def test_get_routing_with_profile_name(self, tmp_path):
        """Profile override primary is returned."""
        router = self._make_router_with_store(
            tmp_path,
            {"coder": {"primary": "gemini-2-flash"}},
        )
        routing = router.get_routing(TaskType.CODING, profile_name="coder")
        assert routing["primary"] == "gemini-2-flash"

    def test_admin_override_beats_profile(self, tmp_path, monkeypatch):
        """Env var override wins over profile."""
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
