"""Tests for Phase 38 provider UI endpoints and structure (PROVIDER-01 through PROVIDER-05)."""

import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from dashboard.auth import AuthContext, get_current_user, require_admin
from dashboard.server import create_app


def _make_client(**kwargs) -> TestClient:
    """Create a TestClient with auth overrides for admin endpoints."""
    defaults = {
        "tool_registry": None,
        "skill_loader": None,
        "app_manager": MagicMock(),
        "project_manager": MagicMock(),
        "repo_manager": MagicMock(),
    }
    defaults.update(kwargs)
    app = create_app(**defaults)
    app.dependency_overrides[get_current_user] = lambda: "test-user"
    app.dependency_overrides[require_admin] = lambda: AuthContext(user="test-admin")
    return TestClient(app)


class TestNoStrongwallArtifacts:
    """PROVIDER-01: StrongWall references removed."""

    def test_no_strongwall_in_server(self):
        """server.py must not contain 'StrongWall'."""
        server_path = Path("dashboard/server.py")
        content = server_path.read_text()
        assert "StrongWall" not in content, "StrongWall reference still in server.py"

    def test_no_app_js_backup(self):
        """app.js.backup must not exist."""
        backup = Path("dashboard/frontend/dist/app.js.backup")
        assert not backup.exists(), "app.js.backup still exists"


class TestProvidersTabStructure:
    """PROVIDER-02: UI restructure -- verify app.js contains required section headings
    and does NOT contain old removed labels."""

    def test_has_cc_subscription_section(self):
        """app.js must contain 'Claude Code Subscription' section heading."""
        content = Path("dashboard/frontend/dist/app.js").read_text()
        assert "Claude Code Subscription" in content, "Missing 'Claude Code Subscription' section"

    def test_has_api_key_providers_section(self):
        """app.js must contain 'API Key Providers' section heading."""
        content = Path("dashboard/frontend/dist/app.js").read_text()
        assert "API Key Providers" in content, "Missing 'API Key Providers' section"

    def test_has_media_search_section(self):
        """app.js must contain 'Media' and 'Search' in a section heading."""
        content = Path("dashboard/frontend/dist/app.js").read_text()
        assert "Media" in content and "Search" in content, "Missing 'Media & Search' section"

    def test_has_provider_connectivity_section(self):
        """app.js must contain 'Provider Connectivity' section heading."""
        content = Path("dashboard/frontend/dist/app.js").read_text()
        assert "Provider Connectivity" in content, "Missing 'Provider Connectivity' section"

    def test_has_provider_routing_section(self):
        """app.js must contain 'Provider Routing' info box."""
        content = Path("dashboard/frontend/dist/app.js").read_text()
        assert "Provider Routing" in content, "Missing 'Provider Routing' info box"

    def test_no_old_primary_providers_label(self):
        """app.js must NOT contain old 'Primary Providers' section label."""
        content = Path("dashboard/frontend/dist/app.js").read_text()
        assert "Primary Providers" not in content, "Old 'Primary Providers' label still present"

    def test_no_old_premium_providers_label(self):
        """app.js must NOT contain old 'Premium Providers' section label."""
        content = Path("dashboard/frontend/dist/app.js").read_text()
        assert "Premium Providers" not in content, "Old 'Premium Providers' label still present"

    def test_no_old_model_routing_v2_box(self):
        """app.js must NOT contain old 'Model Routing (v2.0)' info box."""
        content = Path("dashboard/frontend/dist/app.js").read_text()
        assert "Model Routing (v2.0)" not in content, (
            "Old 'Model Routing (v2.0)' info box still present"
        )


class TestSyntheticModelsEndpoint:
    """PROVIDER-03: GET /api/providers/synthetic/models."""

    def test_synthetic_models_no_client(self):
        """When _synthetic_client is None, returns empty model list."""
        with patch("core.agent_manager._synthetic_client", None):
            client = _make_client()
            resp = client.get("/api/providers/synthetic/models")
        assert resp.status_code == 200
        data = resp.json()
        assert data["models"] == []
        assert data["count"] == 0
        assert data["free_count"] == 0
        assert data["cached_at"] is None
        assert data["capability_mapping"] == {}

    def test_synthetic_models_with_client(self):
        """When _synthetic_client exists, returns model catalog."""
        mock_model = MagicMock()
        mock_model.id = "test-model-1"
        mock_model.name = "Test Model"
        mock_model.description = "A test model"
        mock_model.capabilities = ["fast", "general"]
        mock_model.max_context_length = 128000
        mock_model.is_free = True

        mock_client = AsyncMock()
        mock_client.refresh_models = AsyncMock(return_value=[mock_model])
        mock_client.update_provider_models_mapping = MagicMock(
            return_value={"fast": "test-model-1"}
        )
        mock_client._last_refresh = 1712200000.0

        with patch("core.agent_manager._synthetic_client", mock_client):
            client = _make_client()
            resp = client.get("/api/providers/synthetic/models")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["free_count"] == 1
        assert data["cached_at"] == 1712200000.0
        assert data["capability_mapping"] == {"fast": "test-model-1"}
        assert data["models"][0]["id"] == "test-model-1"
        assert data["models"][0]["name"] == "Test Model"
        assert "fast" in data["models"][0]["capabilities"]

    def test_synthetic_models_force_refresh(self):
        """force=true parameter is passed through to refresh_models."""
        mock_client = AsyncMock()
        mock_client.refresh_models = AsyncMock(return_value=[])
        mock_client.update_provider_models_mapping = MagicMock(return_value={})
        mock_client._last_refresh = 0.0

        with patch("core.agent_manager._synthetic_client", mock_client):
            client = _make_client()
            resp = client.get("/api/providers/synthetic/models?force=true")
        assert resp.status_code == 200
        mock_client.refresh_models.assert_called_once_with(force=True)


class TestProviderStatusEndpoint:
    """PROVIDER-04: GET /api/settings/provider-status."""

    def test_provider_status_no_keys(self):
        """All providers unconfigured when no env vars set."""
        env_overrides = {
            "CLAUDECODE_SUBSCRIPTION_TOKEN": "",
            "SYNTHETIC_API_KEY": "",
            "ANTHROPIC_API_KEY": "",
            "OPENROUTER_API_KEY": "",
        }
        with patch.dict(os.environ, env_overrides, clear=False):
            client = _make_client()
            resp = client.get("/api/settings/provider-status")
        assert resp.status_code == 200
        data = resp.json()
        assert "providers" in data
        assert "checked_at" in data
        providers = {p["name"]: p for p in data["providers"]}
        assert providers["claudecode"]["status"] == "unconfigured"
        assert providers["claudecode"]["configured"] is False
        assert providers["synthetic"]["status"] == "unconfigured"
        assert providers["anthropic"]["status"] == "unconfigured"
        assert providers["openrouter"]["status"] == "unconfigured"

    def test_provider_status_cc_token_present(self):
        """CC Subscription shows ok when token is set (no live ping)."""
        with patch.dict(os.environ, {"CLAUDECODE_SUBSCRIPTION_TOKEN": "fake-token"}, clear=False):
            client = _make_client()
            resp = client.get("/api/settings/provider-status")
        data = resp.json()
        cc = next(p for p in data["providers"] if p["name"] == "claudecode")
        assert cc["configured"] is True
        assert cc["status"] == "ok"
        assert cc["label"] == "Claude Code Subscription"

    def test_provider_status_has_four_providers(self):
        """Response contains exactly 4 provider entries."""
        client = _make_client()
        resp = client.get("/api/settings/provider-status")
        data = resp.json()
        names = [p["name"] for p in data["providers"]]
        assert names == ["claudecode", "synthetic", "anthropic", "openrouter"]

    def test_provider_status_each_has_required_fields(self):
        """Each provider entry has name, label, configured, status."""
        client = _make_client()
        resp = client.get("/api/settings/provider-status")
        data = resp.json()
        for p in data["providers"]:
            assert "name" in p
            assert "label" in p
            assert "configured" in p
            assert "status" in p
            assert p["status"] in ("unconfigured", "ok", "auth_error", "unreachable", "timeout")


class TestAgentsModelsEndpoint:
    """PROVIDER-05: GET /api/agents/models returns PROVIDER_MODELS dict."""

    def test_agents_models_has_provider_keys(self):
        """Endpoint returns dict with claudecode, anthropic, synthetic, openrouter."""
        client = _make_client()
        resp = client.get("/api/agents/models")
        assert resp.status_code == 200
        data = resp.json()
        assert "claudecode" in data
        assert "anthropic" in data
        assert "synthetic" in data
        assert "openrouter" in data

    def test_agents_models_has_categories(self):
        """Each provider has task category keys (fast, general, etc.)."""
        client = _make_client()
        resp = client.get("/api/agents/models")
        data = resp.json()
        # claudecode should have at least fast, general, reasoning
        assert "fast" in data["claudecode"]
        assert "general" in data["claudecode"]
        assert "reasoning" in data["claudecode"]
