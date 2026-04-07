"""Tests for Agent42 sidecar Phase 35: Provider Model Discovery endpoints.

Coverage:
- GET /sidecar/models (D-05, UI-02)
- GET /sidecar/health enhanced with providers_detail (D-07, UI-04)
- SYNTHETIC_API_KEY in ADMIN_CONFIGURABLE_KEYS (D-08, UI-01)
- synthetic_api_key in Settings dataclass
"""

import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from core.config import Settings
from core.key_store import ADMIN_CONFIGURABLE_KEYS
from dashboard.sidecar import create_sidecar_app


@pytest.fixture
def sidecar_client():
    """Create a TestClient for the sidecar app (no dependencies needed)."""
    app = create_sidecar_app()
    return TestClient(app)


# ---------------------------------------------------------------------------
# GET /sidecar/models tests (D-05, UI-02)
# ---------------------------------------------------------------------------


class TestSidecarModelsEndpoint:
    """Tests for GET /sidecar/models endpoint."""

    def test_get_models_returns_provider_list(self, sidecar_client):
        """GET /sidecar/models returns 200 with JSON body containing models and providers arrays."""
        response = sidecar_client.get("/sidecar/models")
        assert response.status_code == 200
        data = response.json()
        assert "models" in data
        assert "providers" in data
        assert isinstance(data["models"], list)
        assert isinstance(data["providers"], list)

    def test_get_models_includes_all_providers(self, sidecar_client):
        """Response providers list includes zen, openrouter, anthropic, openai."""
        response = sidecar_client.get("/sidecar/models")
        assert response.status_code == 200
        providers = response.json()["providers"]
        for expected in ("zen", "openrouter", "anthropic", "openai"):
            assert expected in providers, f"Expected provider '{expected}' in {providers}"

    def test_get_models_no_auth_required(self, sidecar_client):
        """GET /sidecar/models without Authorization header returns 200, not 401/403."""
        response = sidecar_client.get("/sidecar/models")
        assert response.status_code == 200

    def test_get_models_model_item_schema(self, sidecar_client):
        """Each item in response.models has required schema keys."""
        response = sidecar_client.get("/sidecar/models")
        assert response.status_code == 200
        models = response.json()["models"]
        assert len(models) > 0, "Expected at least one model"
        for item in models:
            assert "model_id" in item, f"model_id missing from {item}"
            assert "display_name" in item, f"display_name missing from {item}"
            assert "provider" in item, f"provider missing from {item}"
            assert "categories" in item, f"categories missing from {item}"
            assert "available" in item, f"available missing from {item}"

    def test_get_models_categories_populated(self, sidecar_client):
        """At least one model has a non-empty categories list."""
        response = sidecar_client.get("/sidecar/models")
        assert response.status_code == 200
        models = response.json()["models"]
        models_with_categories = [m for m in models if m["categories"]]
        assert len(models_with_categories) > 0, (
            "Expected at least one model with non-empty categories"
        )

    def test_get_models_synthetic_stub_in_providers(self, sidecar_client):
        """Response providers list includes synthetic stub entry."""
        response = sidecar_client.get("/sidecar/models")
        assert response.status_code == 200
        providers = response.json()["providers"]
        assert "synthetic" in providers, f"Expected 'synthetic' stub in {providers}"


# ---------------------------------------------------------------------------
# GET /sidecar/health enhanced tests (D-07, UI-04)
# ---------------------------------------------------------------------------


class TestSidecarHealthEnhanced:
    """Tests for enhanced GET /sidecar/health with providers_detail."""

    def test_health_includes_providers_detail(self, sidecar_client):
        """GET /sidecar/health response JSON has providers_detail key."""
        response = sidecar_client.get("/sidecar/health")
        assert response.status_code == 200
        data = response.json()
        assert "providers_detail" in data, f"providers_detail missing from {list(data.keys())}"

    def test_health_providers_detail_schema(self, sidecar_client):
        """Each item in providers_detail has required schema keys."""
        response = sidecar_client.get("/sidecar/health")
        assert response.status_code == 200
        details = response.json()["providers_detail"]
        assert isinstance(details, list), "providers_detail should be a list"
        assert len(details) > 0, "providers_detail should have at least one entry"
        for item in details:
            assert "name" in item, f"name missing from {item}"
            assert "configured" in item, f"configured missing from {item}"
            assert "connected" in item, f"connected missing from {item}"
            assert "model_count" in item, f"model_count missing from {item}"
            assert "last_check" in item, f"last_check missing from {item}"

    def test_health_backward_compat(self, sidecar_client):
        """GET /sidecar/health response still has providers.configured dict with boolean values."""
        response = sidecar_client.get("/sidecar/health")
        assert response.status_code == 200
        data = response.json()
        assert "providers" in data, "providers key missing (backward compat broken)"
        providers = data["providers"]
        assert "configured" in providers, "providers.configured missing (backward compat broken)"
        configured = providers["configured"]
        assert isinstance(configured, dict), "providers.configured must be a dict"
        # All values must be booleans
        for key, val in configured.items():
            assert isinstance(val, bool), (
                f"providers.configured[{key!r}] must be bool, got {type(val)}"
            )


# ---------------------------------------------------------------------------
# SYNTHETIC_API_KEY config tests (D-08, UI-01)
# ---------------------------------------------------------------------------


class TestSyntheticApiKeyConfig:
    """Tests for SYNTHETIC_API_KEY admin configurability."""

    def test_synthetic_key_in_admin_configurable(self):
        """SYNTHETIC_API_KEY is in ADMIN_CONFIGURABLE_KEYS."""
        assert "SYNTHETIC_API_KEY" in ADMIN_CONFIGURABLE_KEYS

    def test_synthetic_key_in_settings_dataclass(self):
        """Settings dataclass has synthetic_api_key field."""
        s = Settings()
        assert hasattr(s, "synthetic_api_key"), "Settings missing synthetic_api_key field"

    def test_synthetic_key_default_is_empty_string(self):
        """synthetic_api_key defaults to empty string."""
        s = Settings()
        assert s.synthetic_api_key == ""

    def test_synthetic_key_from_env(self):
        """Settings.from_env() reads SYNTHETIC_API_KEY from environment."""
        with patch.dict(os.environ, {"SYNTHETIC_API_KEY": "sk-syn-test12345"}):
            s = Settings.from_env()
            assert s.synthetic_api_key == "sk-syn-test12345"
