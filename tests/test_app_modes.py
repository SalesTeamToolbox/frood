"""Tests for dual-mode app platform — modes, visibility, auth, and app_api."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.app_manager import App, AppManager, AppStatus
from tools.app_tool import AppTool

# =============================================================================
# App dataclass fields
# =============================================================================


class TestAppModeFields:
    """Test that mode/visibility/auth fields exist and serialize correctly."""

    def test_defaults(self):
        app = App()
        assert app.app_mode == "internal"
        assert app.require_auth is False
        assert app.visibility == "private"

    def test_to_dict_includes_mode_fields(self):
        app = App(
            name="Test",
            app_mode="external",
            require_auth=True,
            visibility="public",
        )
        d = app.to_dict()
        assert d["app_mode"] == "external"
        assert d["require_auth"] is True
        assert d["visibility"] == "public"

    def test_from_dict_with_mode_fields(self):
        data = {
            "id": "abc",
            "name": "Test",
            "slug": "test",
            "app_mode": "external",
            "require_auth": True,
            "visibility": "unlisted",
        }
        app = App.from_dict(data)
        assert app.app_mode == "external"
        assert app.require_auth is True
        assert app.visibility == "unlisted"

    def test_from_dict_without_mode_fields(self):
        """Backward compat: old apps without mode fields get defaults."""
        data = {"id": "old", "name": "Old App", "slug": "old-app"}
        app = App.from_dict(data)
        assert app.app_mode == "internal"
        assert app.require_auth is False
        assert app.visibility == "private"

    def test_round_trip(self):
        """to_dict -> from_dict preserves mode fields."""
        original = App(
            name="Round Trip",
            slug="round-trip",
            app_mode="external",
            require_auth=True,
            visibility="public",
        )
        restored = App.from_dict(original.to_dict())
        assert restored.app_mode == original.app_mode
        assert restored.require_auth == original.require_auth
        assert restored.visibility == original.visibility


# =============================================================================
# AppManager mode operations
# =============================================================================


class TestAppManagerModes:
    """Test mode-aware creation, filtering, and setter methods."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.apps_dir = tmp_path / "apps"
        self.manager = AppManager(
            apps_dir=str(self.apps_dir),
            port_range_start=9100,
            port_range_end=9110,
            max_running=3,
            default_mode="internal",
            require_auth_default=False,
        )

    @pytest.mark.asyncio
    async def test_create_default_mode(self):
        app = await self.manager.create(name="Default App")
        assert app.app_mode == "internal"
        assert app.visibility == "private"
        assert app.require_auth is False

    @pytest.mark.asyncio
    async def test_create_internal_mode(self):
        app = await self.manager.create(name="System Tool", app_mode="internal")
        assert app.app_mode == "internal"
        assert app.visibility == "private"

    @pytest.mark.asyncio
    async def test_create_external_mode(self):
        app = await self.manager.create(name="Public App", app_mode="external")
        assert app.app_mode == "external"
        assert app.visibility == "unlisted"

    @pytest.mark.asyncio
    async def test_create_invalid_mode_uses_default(self):
        app = await self.manager.create(name="Bad Mode", app_mode="invalid")
        assert app.app_mode == "internal"

    @pytest.mark.asyncio
    async def test_create_respects_default_mode_setting(self):
        manager = AppManager(
            apps_dir=str(self.apps_dir / "ext_default"),
            default_mode="external",
        )
        app = await manager.create(name="Ext Default")
        assert app.app_mode == "external"
        assert app.visibility == "unlisted"

    @pytest.mark.asyncio
    async def test_create_respects_require_auth_default(self):
        manager = AppManager(
            apps_dir=str(self.apps_dir / "auth_default"),
            require_auth_default=True,
        )
        app = await manager.create(name="Auth Default")
        assert app.require_auth is True

    @pytest.mark.asyncio
    async def test_manifest_includes_mode_fields(self):
        app = await self.manager.create(name="Manifest Test", app_mode="external")
        manifest_path = Path(app.path) / "APP.json"
        assert manifest_path.exists()
        with open(manifest_path) as f:
            manifest = json.load(f)
        assert manifest["app_mode"] == "external"
        assert manifest["require_auth"] is False
        assert manifest["visibility"] == "unlisted"

    @pytest.mark.asyncio
    async def test_list_apps_by_mode(self):
        await self.manager.create(name="Internal 1", app_mode="internal")
        await self.manager.create(name="Internal 2", app_mode="internal")
        await self.manager.create(name="External 1", app_mode="external")

        internal = self.manager.list_apps_by_mode("internal")
        external = self.manager.list_apps_by_mode("external")
        assert len(internal) == 2
        assert len(external) == 1
        assert all(a.app_mode == "internal" for a in internal)
        assert all(a.app_mode == "external" for a in external)

    @pytest.mark.asyncio
    async def test_list_apps_by_mode_excludes_archived(self):
        app = await self.manager.create(name="Archived App", app_mode="internal")
        app.status = AppStatus.ARCHIVED.value
        assert len(self.manager.list_apps_by_mode("internal")) == 0


class TestAppManagerVisibility:
    """Test visibility setter and validation."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.apps_dir = tmp_path / "apps"
        self.manager = AppManager(apps_dir=str(self.apps_dir))

    @pytest.mark.asyncio
    async def test_set_visibility_private(self):
        app = await self.manager.create(name="Vis App", app_mode="external")
        assert app.visibility == "unlisted"
        result = await self.manager.set_app_visibility(app.id, "private")
        assert result.visibility == "private"

    @pytest.mark.asyncio
    async def test_set_visibility_public(self):
        app = await self.manager.create(name="Public App")
        result = await self.manager.set_app_visibility(app.id, "public")
        assert result.visibility == "public"

    @pytest.mark.asyncio
    async def test_set_visibility_unlisted(self):
        app = await self.manager.create(name="Unlisted App")
        result = await self.manager.set_app_visibility(app.id, "unlisted")
        assert result.visibility == "unlisted"

    @pytest.mark.asyncio
    async def test_set_visibility_invalid(self):
        app = await self.manager.create(name="Invalid Vis")
        with pytest.raises(ValueError, match="Invalid visibility"):
            await self.manager.set_app_visibility(app.id, "secret")

    @pytest.mark.asyncio
    async def test_set_visibility_not_found(self):
        with pytest.raises(ValueError, match="App not found"):
            await self.manager.set_app_visibility("nonexistent", "public")


class TestAppManagerAuth:
    """Test auth setter and persistence."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.apps_dir = tmp_path / "apps"
        self.manager = AppManager(apps_dir=str(self.apps_dir))

    @pytest.mark.asyncio
    async def test_set_auth_enable(self):
        app = await self.manager.create(name="Auth App")
        assert app.require_auth is False
        result = await self.manager.set_app_auth(app.id, True)
        assert result.require_auth is True

    @pytest.mark.asyncio
    async def test_set_auth_disable(self):
        app = await self.manager.create(name="Auth App 2")
        await self.manager.set_app_auth(app.id, True)
        result = await self.manager.set_app_auth(app.id, False)
        assert result.require_auth is False

    @pytest.mark.asyncio
    async def test_set_auth_not_found(self):
        with pytest.raises(ValueError, match="App not found"):
            await self.manager.set_app_auth("nonexistent", True)

    @pytest.mark.asyncio
    async def test_set_auth_persists(self):
        app = await self.manager.create(name="Persist Auth")
        await self.manager.set_app_auth(app.id, True)
        # Reload from disk
        manager2 = AppManager(apps_dir=str(self.apps_dir))
        await manager2.load()
        reloaded = await manager2.get(app.id)
        assert reloaded is not None
        assert reloaded.require_auth is True


class TestAppManagerSetMode:
    """Test set_app_mode."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.apps_dir = tmp_path / "apps"
        self.manager = AppManager(apps_dir=str(self.apps_dir))

    @pytest.mark.asyncio
    async def test_set_mode_to_external(self):
        app = await self.manager.create(name="Mode App")
        assert app.app_mode == "internal"
        result = await self.manager.set_app_mode(app.id, "external")
        assert result.app_mode == "external"

    @pytest.mark.asyncio
    async def test_set_mode_to_internal(self):
        app = await self.manager.create(name="Mode App 2", app_mode="external")
        result = await self.manager.set_app_mode(app.id, "internal")
        assert result.app_mode == "internal"

    @pytest.mark.asyncio
    async def test_set_mode_invalid(self):
        app = await self.manager.create(name="Invalid Mode")
        with pytest.raises(ValueError, match="Invalid mode"):
            await self.manager.set_app_mode(app.id, "unknown")

    @pytest.mark.asyncio
    async def test_set_mode_not_found(self):
        with pytest.raises(ValueError, match="App not found"):
            await self.manager.set_app_mode("nonexistent", "internal")

    @pytest.mark.asyncio
    async def test_set_mode_updates_timestamp(self):
        app = await self.manager.create(name="Timestamp App")
        old_ts = app.updated_at
        import time

        time.sleep(0.01)
        result = await self.manager.set_app_mode(app.id, "external")
        assert result.updated_at > old_ts


class TestAppManagerGetAppUrl:
    """Test get_app_url method."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.apps_dir = tmp_path / "apps"
        self.manager = AppManager(apps_dir=str(self.apps_dir))

    @pytest.mark.asyncio
    async def test_get_app_url_running_python(self):
        app = await self.manager.create(name="URL App", runtime="python")
        app.status = AppStatus.RUNNING.value
        app.port = 9100
        url = await self.manager.get_app_url(app.id)
        assert url == "http://127.0.0.1:9100"

    @pytest.mark.asyncio
    async def test_get_app_url_static_returns_none(self):
        app = await self.manager.create(name="Static App", runtime="static")
        app.status = AppStatus.RUNNING.value
        url = await self.manager.get_app_url(app.id)
        assert url is None

    @pytest.mark.asyncio
    async def test_get_app_url_stopped_returns_none(self):
        app = await self.manager.create(name="Stopped App", runtime="python")
        app.status = AppStatus.STOPPED.value
        url = await self.manager.get_app_url(app.id)
        assert url is None

    @pytest.mark.asyncio
    async def test_get_app_url_not_found_returns_none(self):
        url = await self.manager.get_app_url("nonexistent")
        assert url is None


# =============================================================================
# AppTool mode actions
# =============================================================================


class TestAppToolModes:
    """Test set_mode, set_visibility, set_auth actions via AppTool."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.apps_dir = tmp_path / "apps"
        self.manager = AppManager(apps_dir=str(self.apps_dir))
        self.tool = AppTool(app_manager=self.manager)

    @pytest.mark.asyncio
    async def test_set_mode_action(self):
        app = await self.manager.create(name="Tool Mode App")
        result = await self.tool.execute(action="set_mode", app_id=app.id, app_mode="external")
        assert result.success is not False
        assert "external" in result.output

    @pytest.mark.asyncio
    async def test_set_mode_missing_app_id(self):
        result = await self.tool.execute(action="set_mode", app_mode="external")
        assert result.success is False
        assert "app_id" in result.error.lower()

    @pytest.mark.asyncio
    async def test_set_mode_missing_mode(self):
        app = await self.manager.create(name="No Mode")
        result = await self.tool.execute(action="set_mode", app_id=app.id)
        assert result.success is False
        assert "app_mode" in result.error.lower()

    @pytest.mark.asyncio
    async def test_set_visibility_action(self):
        app = await self.manager.create(name="Tool Vis App")
        result = await self.tool.execute(
            action="set_visibility", app_id=app.id, visibility="public"
        )
        assert result.success is not False
        assert "public" in result.output

    @pytest.mark.asyncio
    async def test_set_visibility_missing_visibility(self):
        app = await self.manager.create(name="No Vis")
        result = await self.tool.execute(action="set_visibility", app_id=app.id)
        assert result.success is False

    @pytest.mark.asyncio
    async def test_set_auth_action_enable(self):
        app = await self.manager.create(name="Tool Auth App")
        result = await self.tool.execute(action="set_auth", app_id=app.id, require_auth=True)
        assert result.success is not False
        assert "enabled" in result.output.lower()

    @pytest.mark.asyncio
    async def test_set_auth_action_disable(self):
        app = await self.manager.create(name="Tool Auth App 2")
        await self.manager.set_app_auth(app.id, True)
        result = await self.tool.execute(action="set_auth", app_id=app.id, require_auth=False)
        assert result.success is not False
        assert "disabled" in result.output.lower()

    @pytest.mark.asyncio
    async def test_set_auth_string_true(self):
        """Test that string 'true' is handled correctly."""
        app = await self.manager.create(name="String Auth")
        result = await self.tool.execute(action="set_auth", app_id=app.id, require_auth="true")
        assert result.success is not False
        reloaded = await self.manager.get(app.id)
        assert reloaded.require_auth is True


class TestAppToolModeDisplay:
    """Test that status and list show mode information."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.apps_dir = tmp_path / "apps"
        self.manager = AppManager(apps_dir=str(self.apps_dir))
        self.tool = AppTool(app_manager=self.manager)

    @pytest.mark.asyncio
    async def test_status_shows_mode(self):
        app = await self.manager.create(name="Status Mode App", app_mode="external")
        result = await self.tool.execute(action="status", app_id=app.id)
        assert "external" in result.output
        assert "Visibility:" in result.output or "visibility" in result.output.lower()
        assert "Auth required:" in result.output or "auth" in result.output.lower()

    @pytest.mark.asyncio
    async def test_list_shows_mode_tag(self):
        await self.manager.create(name="Internal Tool", app_mode="internal")
        await self.manager.create(name="External Dev", app_mode="external")
        result = await self.tool.execute(action="list")
        assert "[internal]" in result.output
        assert "[external]" in result.output

    @pytest.mark.asyncio
    async def test_create_shows_mode_info(self):
        result = await self.tool.execute(
            action="create", name="Mode Create Test", app_mode="external"
        )
        assert "external" in result.output
        assert "unlisted" in result.output


# =============================================================================
# AppTool app_api action
# =============================================================================


class TestAppToolAppApi:
    """Test agent-to-app API interaction via app_api action."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.apps_dir = tmp_path / "apps"
        self.manager = AppManager(apps_dir=str(self.apps_dir))
        self.tool = AppTool(app_manager=self.manager)

    @pytest.mark.asyncio
    async def test_app_api_missing_app_id(self):
        result = await self.tool.execute(action="app_api")
        assert result.success is False
        assert "app_id" in result.error.lower()

    @pytest.mark.asyncio
    async def test_app_api_not_found(self):
        result = await self.tool.execute(action="app_api", app_id="nonexistent")
        assert result.success is False
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_app_api_not_running(self):
        app = await self.manager.create(name="Stopped API App", runtime="python")
        result = await self.tool.execute(action="app_api", app_id=app.id)
        assert result.success is False
        assert "not running" in result.error.lower()

    @pytest.mark.asyncio
    async def test_app_api_static_rejected(self):
        app = await self.manager.create(name="Static API App", runtime="static")
        app.status = AppStatus.RUNNING.value
        result = await self.tool.execute(action="app_api", app_id=app.id)
        assert result.success is False
        assert "static" in result.error.lower()

    @pytest.mark.asyncio
    async def test_app_api_get_success(self):
        """Test GET request to a running app (mocked httpx)."""
        app = await self.manager.create(name="API App", runtime="python")
        app.status = AppStatus.RUNNING.value
        app.port = 9100

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": "test"}
        mock_response.text = '{"data": "test"}'

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await self.tool.execute(
                action="app_api", app_id=app.id, method="GET", endpoint="/api/status"
            )

        assert result.success is not False
        assert "200" in result.output
        assert "test" in result.output

    @pytest.mark.asyncio
    async def test_app_api_post_with_body(self):
        """Test POST request with JSON body."""
        app = await self.manager.create(name="POST App", runtime="python")
        app.status = AppStatus.RUNNING.value
        app.port = 9101

        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {"id": 1, "created": True}
        mock_response.text = '{"id": 1, "created": true}'

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await self.tool.execute(
                action="app_api",
                app_id=app.id,
                method="POST",
                endpoint="/api/items",
                body='{"name": "test item"}',
            )

        assert result.success is not False
        assert "201" in result.output
        mock_client.request.assert_called_once()
        call_kwargs = mock_client.request.call_args
        assert call_kwargs.kwargs.get("method") == "POST" or call_kwargs[1].get("method") == "POST"

    @pytest.mark.asyncio
    async def test_app_api_with_headers(self):
        """Test request with custom headers."""
        app = await self.manager.create(name="Headers App", runtime="python")
        app.status = AppStatus.RUNNING.value
        app.port = 9102

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True}
        mock_response.text = '{"ok": true}'

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await self.tool.execute(
                action="app_api",
                app_id=app.id,
                endpoint="/api/data",
                api_headers="Content-Type: application/json, X-Custom: test",
            )

        assert result.success is not False
        call_kwargs = mock_client.request.call_args
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers", {})
        assert headers.get("Content-Type") == "application/json"
        assert headers.get("X-Custom") == "test"

    @pytest.mark.asyncio
    async def test_app_api_connect_error(self):
        """Test handling of connection errors."""
        import httpx

        app = await self.manager.create(name="Down App", runtime="python")
        app.status = AppStatus.RUNNING.value
        app.port = 9103

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(side_effect=httpx.ConnectError("refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await self.tool.execute(
                action="app_api", app_id=app.id, endpoint="/api/health"
            )

        assert result.success is False
        assert "not responding" in result.error.lower()

    @pytest.mark.asyncio
    async def test_app_api_timeout(self):
        """Test handling of timeout."""
        import httpx

        app = await self.manager.create(name="Slow App", runtime="python")
        app.status = AppStatus.RUNNING.value
        app.port = 9104

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(side_effect=httpx.TimeoutException("timed out"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await self.tool.execute(action="app_api", app_id=app.id, endpoint="/api/slow")

        assert result.success is False
        assert "timed out" in result.error.lower()

    @pytest.mark.asyncio
    async def test_app_api_non_json_response(self):
        """Test handling of non-JSON response body."""
        app = await self.manager.create(name="HTML App", runtime="python")
        app.status = AppStatus.RUNNING.value
        app.port = 9105

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("not json")
        mock_response.text = "<html><body>Hello</body></html>"

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await self.tool.execute(action="app_api", app_id=app.id, endpoint="/")

        assert result.success is not False
        assert "Hello" in result.output

    @pytest.mark.asyncio
    async def test_app_api_node_runtime(self):
        """Test that node runtime works with app_api."""
        app = await self.manager.create(name="Node API App", runtime="node")
        app.status = AppStatus.RUNNING.value
        app.port = 9106

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"runtime": "node"}
        mock_response.text = '{"runtime": "node"}'

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await self.tool.execute(action="app_api", app_id=app.id, endpoint="/api/info")

        assert result.success is not False
        assert "node" in result.output


# =============================================================================
# Proxy auth gating (unit test of logic)
# =============================================================================


class TestProxyAuthGating:
    """Test the auth gating logic for app proxy access."""

    def test_app_require_auth_flag(self):
        """Verify the flag correctly reflects on the dataclass."""
        app_no_auth = App(name="Open", require_auth=False)
        app_with_auth = App(name="Protected", require_auth=True)
        assert app_no_auth.require_auth is False
        assert app_with_auth.require_auth is True

    @pytest.mark.asyncio
    async def test_auth_gating_preserves_after_persist(self):
        """Auth setting survives save/load cycle."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            manager = AppManager(apps_dir=tmp)
            app = await manager.create(name="Gate Test")
            await manager.set_app_auth(app.id, True)

            # Reload
            manager2 = AppManager(apps_dir=tmp)
            await manager2.load()
            reloaded = await manager2.get(app.id)
            assert reloaded.require_auth is True


# =============================================================================
# Config integration
# =============================================================================


class TestConfigModeSettings:
    """Test that config settings affect AppManager defaults."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.apps_dir = tmp_path / "apps"

    def test_default_mode_internal(self):
        manager = AppManager(
            apps_dir=str(self.apps_dir / "a"),
            default_mode="internal",
        )
        assert manager._default_mode == "internal"

    def test_default_mode_external(self):
        manager = AppManager(
            apps_dir=str(self.apps_dir / "b"),
            default_mode="external",
        )
        assert manager._default_mode == "external"

    def test_require_auth_default(self):
        manager = AppManager(
            apps_dir=str(self.apps_dir / "c"),
            require_auth_default=True,
        )
        assert manager._require_auth_default is True

    @pytest.mark.asyncio
    async def test_config_affects_create(self):
        manager = AppManager(
            apps_dir=str(self.apps_dir / "d"),
            default_mode="external",
            require_auth_default=True,
        )
        app = await manager.create(name="Config App")
        assert app.app_mode == "external"
        assert app.require_auth is True
        assert app.visibility == "unlisted"
