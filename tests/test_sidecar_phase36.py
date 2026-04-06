"""Tests for Phase 36 sidecar endpoints and dashboard gate (PAPERCLIP-01 through PAPERCLIP-05)."""

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from dashboard.auth import get_current_user
from dashboard.sidecar import create_sidecar_app


def _make_sidecar_client(**kwargs) -> TestClient:
    """Create a TestClient for sidecar app with auth override."""
    app = create_sidecar_app(**kwargs)
    # Override auth dependency for testing
    app.dependency_overrides[get_current_user] = lambda: "test-user"
    return TestClient(app)


class TestSidecarTools:
    """PAPERCLIP-03: Tools endpoint tests."""

    def test_list_sidecar_tools_empty(self):
        """GET /tools with no tool_registry returns empty list."""
        client = _make_sidecar_client()
        resp = client.get("/tools")
        assert resp.status_code == 200
        data = resp.json()
        assert "tools" in data
        assert data["tools"] == []

    def test_list_sidecar_tools_with_data(self):
        """GET /tools with mock tool_registry returns tools list with expected shape."""
        mock_registry = MagicMock()
        mock_registry.list_tools.return_value = [
            {
                "name": "test_tool",
                "display_name": "Test Tool",
                "description": "A test",
                "disabled": False,
                "source": "builtin",
            },
        ]
        client = _make_sidecar_client(tool_registry=mock_registry)
        resp = client.get("/tools")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["tools"]) == 1
        assert data["tools"][0]["name"] == "test_tool"
        assert data["tools"][0]["enabled"] is True

    def test_list_sidecar_tools_disabled_flag(self):
        """GET /tools maps disabled=True to enabled=False."""
        mock_registry = MagicMock()
        mock_registry.list_tools.return_value = [
            {
                "name": "disabled_tool",
                "display_name": "Disabled Tool",
                "description": "Off",
                "disabled": True,
                "source": "mcp",
            },
        ]
        client = _make_sidecar_client(tool_registry=mock_registry)
        resp = client.get("/tools")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["tools"]) == 1
        assert data["tools"][0]["enabled"] is False


class TestSidecarSkills:
    """PAPERCLIP-03: Skills endpoint tests."""

    def test_list_sidecar_skills_empty(self):
        """GET /skills with no skill_loader returns empty list."""
        client = _make_sidecar_client()
        resp = client.get("/skills")
        assert resp.status_code == 200
        data = resp.json()
        assert "skills" in data
        assert data["skills"] == []

    def test_list_sidecar_skills_with_data(self):
        """GET /skills with mock skill_loader returns skills list."""
        mock_loader = MagicMock()
        mock_loader.all_skills.return_value = [
            {
                "name": "code_review",
                "display_name": "Code Review",
                "description": "Reviews code",
                "disabled": False,
                "path": "/skills/code_review",
            },
        ]
        client = _make_sidecar_client(skill_loader=mock_loader)
        resp = client.get("/skills")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["skills"]) == 1
        assert data["skills"][0]["name"] == "code_review"
        assert data["skills"][0]["enabled"] is True

    def test_list_sidecar_skills_multiple(self):
        """GET /skills returns all skills from loader."""
        mock_loader = MagicMock()
        mock_loader.all_skills.return_value = [
            {
                "name": "skill_a",
                "display_name": "Skill A",
                "description": "",
                "disabled": False,
                "path": "",
            },
            {
                "name": "skill_b",
                "display_name": "Skill B",
                "description": "",
                "disabled": True,
                "path": "",
            },
        ]
        client = _make_sidecar_client(skill_loader=mock_loader)
        resp = client.get("/skills")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["skills"]) == 2
        assert data["skills"][1]["enabled"] is False


class TestSidecarApps:
    """PAPERCLIP-02: Apps endpoint tests."""

    def test_list_sidecar_apps_empty(self):
        """GET /apps with no app_manager returns empty list."""
        client = _make_sidecar_client()
        resp = client.get("/apps")
        assert resp.status_code == 200
        data = resp.json()
        assert "apps" in data
        assert data["apps"] == []

    def test_start_sidecar_app_no_manager(self):
        """POST /apps/{id}/start with no app_manager returns ok=false."""
        client = _make_sidecar_client()
        resp = client.post("/apps/test-id/start")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is False

    def test_stop_sidecar_app_no_manager(self):
        """POST /apps/{id}/stop with no app_manager returns ok=false."""
        client = _make_sidecar_client()
        resp = client.post("/apps/test-id/stop")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is False

    def test_start_sidecar_app_with_manager(self):
        """POST /apps/{id}/start with app_manager calls start_app and returns ok=true."""
        mock_manager = MagicMock()
        mock_manager.start_app = AsyncMock(return_value=None)
        client = _make_sidecar_client(app_manager=mock_manager)
        resp = client.post("/apps/my-app/start")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        mock_manager.start_app.assert_called_once_with("my-app")

    def test_stop_sidecar_app_with_manager(self):
        """POST /apps/{id}/stop with app_manager calls stop_app and returns ok=true."""
        mock_manager = MagicMock()
        mock_manager.stop_app = AsyncMock(return_value=None)
        client = _make_sidecar_client(app_manager=mock_manager)
        resp = client.post("/apps/my-app/stop")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        mock_manager.stop_app.assert_called_once_with("my-app")


class TestSidecarSettings:
    """PAPERCLIP-04: Settings endpoint tests."""

    def test_get_sidecar_settings_empty(self):
        """GET /settings with no key_store returns empty keys list."""
        client = _make_sidecar_client()
        resp = client.get("/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert "keys" in data
        assert data["keys"] == []

    def test_get_sidecar_settings_with_data(self):
        """GET /settings with mock key_store returns keys with masked values and is_set flags."""
        from core.key_store import ADMIN_CONFIGURABLE_KEYS

        mock_store = MagicMock()
        # get_masked_keys() returns dict[str, dict] per actual key_store implementation
        full_masked = {
            key: {"configured": False, "source": "none", "masked_value": ""}
            for key in ADMIN_CONFIGURABLE_KEYS
        }
        full_masked["OPENAI_API_KEY"] = {
            "configured": True,
            "source": "admin",
            "masked_value": "sk-...***",
        }
        mock_store.get_masked_keys.return_value = full_masked
        client = _make_sidecar_client(key_store=mock_store)
        resp = client.get("/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["keys"]) == len(ADMIN_CONFIGURABLE_KEYS)
        mock_store.get_masked_keys.assert_called_once()
        # Find the OPENAI key entry
        openai_entry = next((k for k in data["keys"] if k["name"] == "OPENAI_API_KEY"), None)
        assert openai_entry is not None
        assert openai_entry["is_set"] is True
        assert openai_entry["masked_value"] == "sk-...***"

    def test_update_sidecar_settings_invalid_key(self):
        """POST /settings with invalid key_name returns 400."""
        mock_store = MagicMock()
        client = _make_sidecar_client(key_store=mock_store)
        resp = client.post("/settings", json={"key_name": "INVALID_KEY", "value": "test"})
        assert resp.status_code == 400

    def test_update_sidecar_settings_valid(self):
        """POST /settings with valid ADMIN_CONFIGURABLE_KEYS entry returns ok=true."""
        mock_store = MagicMock()
        client = _make_sidecar_client(key_store=mock_store)
        resp = client.post("/settings", json={"key_name": "OPENAI_API_KEY", "value": "sk-new-key"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["key_name"] == "OPENAI_API_KEY"
        mock_store.set_key.assert_called_once_with("OPENAI_API_KEY", "sk-new-key")

    def test_update_sidecar_settings_no_store_returns_503(self):
        """POST /settings with no key_store raises 503."""
        client = _make_sidecar_client()
        resp = client.post("/settings", json={"key_name": "OPENAI_API_KEY", "value": "x"})
        assert resp.status_code == 503

    def test_update_sidecar_settings_all_known_keys(self):
        """Verify all ADMIN_CONFIGURABLE_KEYS are accepted by the settings endpoint."""
        from core.key_store import ADMIN_CONFIGURABLE_KEYS

        mock_store = MagicMock()
        client = _make_sidecar_client(key_store=mock_store)
        # Pick a few known keys and verify they all succeed
        for key in list(ADMIN_CONFIGURABLE_KEYS)[:3]:
            resp = client.post("/settings", json={"key_name": key, "value": "test-value"})
            assert resp.status_code == 200, f"Expected 200 for key {key}, got {resp.status_code}"
            data = resp.json()
            assert data["ok"] is True
            assert data["key_name"] == key


class TestDashboardGate:
    """PAPERCLIP-05: Dashboard gate when sidecar mode active."""

    def test_dashboard_gate_sidecar_mode(self):
        """When sidecar_enabled=True, dashboard root returns 503 with paperclip_mode."""
        from core.config import Settings
        from dashboard.server import create_app

        sidecar_settings = Settings(sidecar_enabled=True, paperclip_sidecar_port=8001)
        # The create_app() uses the global `settings` object — patch it
        with patch("dashboard.server.settings", sidecar_settings):
            app = create_app()
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get("/")
            assert resp.status_code == 503
            data = resp.json()
            assert data["status"] == "paperclip_mode"
            assert "sidecar_port" in data

    def test_dashboard_standalone_mode(self):
        """When sidecar_enabled=False, dashboard root does NOT return 503."""
        from core.config import Settings
        from dashboard.server import create_app

        standalone_settings = Settings(sidecar_enabled=False)
        with patch("dashboard.server.settings", standalone_settings):
            app = create_app()
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get("/")
            # In standalone mode, root should NOT be 503
            assert resp.status_code != 503

    def test_sidecar_enabled_config_flag(self):
        """Verify sidecar_enabled flag works in Settings dataclass."""
        from core.config import Settings

        s_on = Settings(sidecar_enabled=True)
        assert s_on.sidecar_enabled is True
        s_off = Settings(sidecar_enabled=False)
        assert s_off.sidecar_enabled is False

    def test_dashboard_gate_sidecar_port_in_response(self):
        """Verify sidecar_port value matches configured paperclip_sidecar_port."""
        from core.config import Settings
        from dashboard.server import create_app

        sidecar_settings = Settings(sidecar_enabled=True, paperclip_sidecar_port=9999)
        with patch("dashboard.server.settings", sidecar_settings):
            app = create_app()
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get("/")
            assert resp.status_code == 503
            data = resp.json()
            assert data["sidecar_port"] == 9999
