"""Tests for provider UI endpoints and structure."""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from dashboard.auth import AuthContext, get_current_user, require_admin
from dashboard.server import create_app


def _make_client(**kwargs) -> TestClient:
    """Create a TestClient with auth overrides for admin endpoints."""
    defaults = {
        "tool_registry": None,
        "skill_loader": None,
        "app_manager": MagicMock(),
    }
    defaults.update(kwargs)
    app = create_app(**defaults)
    app.dependency_overrides[get_current_user] = lambda: "test-user"
    app.dependency_overrides[require_admin] = lambda: AuthContext(user="test-admin")
    return TestClient(app)


class TestNoStrongwallArtifacts:
    """StrongWall references removed."""

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
    """UI restructure -- verify app.js contains required section headings."""

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


class TestProviderStatusEndpoint:
    """GET /api/settings/provider-status returns current provider connectivity."""

    def test_provider_status_no_keys(self):
        """All providers unconfigured when no env vars set."""
        env_overrides = {
            "ZEN_API_KEY": "",
            "OPENROUTER_API_KEY": "",
            "ANTHROPIC_API_KEY": "",
            "OPENAI_API_KEY": "",
        }
        with patch.dict(os.environ, env_overrides, clear=False):
            client = _make_client()
            resp = client.get("/api/settings/provider-status")
        assert resp.status_code == 200
        data = resp.json()
        assert "providers" in data
        assert "checked_at" in data
        providers = {p["name"]: p for p in data["providers"]}
        for name in ("zen", "openrouter", "anthropic", "openai"):
            assert providers[name]["status"] == "unconfigured"
            assert providers[name]["configured"] is False

    def test_provider_status_has_four_providers(self):
        """Response contains exactly 4 provider entries."""
        client = _make_client()
        resp = client.get("/api/settings/provider-status")
        data = resp.json()
        names = [p["name"] for p in data["providers"]]
        assert names == ["zen", "openrouter", "anthropic", "openai"]

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
