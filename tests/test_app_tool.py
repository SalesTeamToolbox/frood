"""Tests for the App Tool — agent-facing app management interface."""

import pytest

from core.app_manager import AppManager
from tools.app_tool import AppTool


class TestAppTool:
    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.apps_dir = tmp_path / "apps"
        self.manager = AppManager(
            apps_dir=str(self.apps_dir),
            port_range_start=9100,
            port_range_end=9110,
            max_running=3,
        )
        self.tool = AppTool(self.manager)

    def test_name(self):
        assert self.tool.name == "app"

    def test_description(self):
        assert "Create and manage" in self.tool.description

    def test_parameters_schema(self):
        params = self.tool.parameters
        assert params["type"] == "object"
        assert "action" in params["properties"]
        actions = params["properties"]["action"]["enum"]
        assert "create" in actions
        assert "start" in actions
        assert "stop" in actions
        assert "list" in actions

    @pytest.mark.asyncio
    async def test_create_action(self):
        result = await self.tool.execute(
            action="create",
            name="Test App",
            app_description="A test app",
            runtime="python",
            tags="test,demo",
        )
        assert result.success
        assert "Test App" in result.output
        assert "ID:" in result.output
        assert "Path:" in result.output

    @pytest.mark.asyncio
    async def test_create_requires_name(self):
        result = await self.tool.execute(action="create")
        assert not result.success
        assert "required" in result.error.lower()

    @pytest.mark.asyncio
    async def test_scaffold_static(self):
        result = await self.tool.execute(action="scaffold", runtime="static")
        assert result.success
        assert "index.html" in result.output

    @pytest.mark.asyncio
    async def test_scaffold_python(self):
        result = await self.tool.execute(action="scaffold", runtime="python")
        assert result.success
        assert "Flask" in result.output or "flask" in result.output.lower()

    @pytest.mark.asyncio
    async def test_scaffold_node(self):
        result = await self.tool.execute(action="scaffold", runtime="node")
        assert result.success
        assert "Express" in result.output or "package.json" in result.output

    @pytest.mark.asyncio
    async def test_scaffold_docker(self):
        result = await self.tool.execute(action="scaffold", runtime="docker")
        assert result.success
        assert "docker-compose" in result.output.lower() or "Dockerfile" in result.output

    @pytest.mark.asyncio
    async def test_list_empty(self):
        result = await self.tool.execute(action="list")
        assert result.success
        assert "No apps" in result.output

    @pytest.mark.asyncio
    async def test_list_with_apps(self):
        await self.manager.create(name="App One", runtime="static")
        await self.manager.create(name="App Two", runtime="python")
        result = await self.tool.execute(action="list")
        assert result.success
        assert "App One" in result.output
        assert "App Two" in result.output
        assert "2 total" in result.output

    @pytest.mark.asyncio
    async def test_status_action(self):
        app = await self.manager.create(name="Status Test", runtime="python")
        result = await self.tool.execute(action="status", app_id=app.id)
        assert result.success
        assert "Status Test" in result.output
        assert "draft" in result.output.lower()

    @pytest.mark.asyncio
    async def test_status_requires_app_id(self):
        result = await self.tool.execute(action="status")
        assert not result.success
        assert "required" in result.error.lower()

    @pytest.mark.asyncio
    async def test_status_nonexistent(self):
        result = await self.tool.execute(action="status", app_id="nonexistent")
        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_mark_ready_action(self):
        app = await self.manager.create(name="Ready Test")
        result = await self.tool.execute(
            action="mark_ready", app_id=app.id, version="1.0.0"
        )
        assert result.success
        assert "ready" in result.output.lower()
        assert "1.0.0" in result.output

    @pytest.mark.asyncio
    async def test_start_static_app(self):
        app = await self.manager.create(name="Start Static", runtime="static")
        await self.manager.mark_ready(app.id)
        result = await self.tool.execute(action="start", app_id=app.id)
        assert result.success
        assert "started" in result.output.lower()
        assert "/apps/" in result.output

    @pytest.mark.asyncio
    async def test_stop_static_app(self):
        app = await self.manager.create(name="Stop Static", runtime="static")
        await self.manager.mark_ready(app.id)
        await self.manager.start(app.id)
        result = await self.tool.execute(action="stop", app_id=app.id)
        assert result.success
        assert "stopped" in result.output.lower()

    @pytest.mark.asyncio
    async def test_restart_action(self):
        app = await self.manager.create(name="Restart Me", runtime="static")
        await self.manager.mark_ready(app.id)
        await self.manager.start(app.id)
        result = await self.tool.execute(action="restart", app_id=app.id)
        assert result.success
        assert "restarted" in result.output.lower()

    @pytest.mark.asyncio
    async def test_logs_action(self):
        app = await self.manager.create(name="Log Me")
        result = await self.tool.execute(action="logs", app_id=app.id)
        assert result.success

    @pytest.mark.asyncio
    async def test_update_manifest_action(self):
        app = await self.manager.create(name="Update Me")
        result = await self.tool.execute(
            action="update_manifest",
            app_id=app.id,
            field="description",
            value="Updated description",
        )
        assert result.success
        assert "Updated" in result.output
        updated = await self.manager.get(app.id)
        assert updated.description == "Updated description"

    @pytest.mark.asyncio
    async def test_update_manifest_disallowed_field(self):
        app = await self.manager.create(name="Bad Update")
        result = await self.tool.execute(
            action="update_manifest",
            app_id=app.id,
            field="status",
            value="running",
        )
        assert not result.success
        assert "Cannot update" in result.error

    @pytest.mark.asyncio
    async def test_unknown_action(self):
        result = await self.tool.execute(action="explode")
        assert not result.success
        assert "Unknown action" in result.error

    @pytest.mark.asyncio
    async def test_start_requires_app_id(self):
        result = await self.tool.execute(action="start")
        assert not result.success

    @pytest.mark.asyncio
    async def test_stop_requires_app_id(self):
        result = await self.tool.execute(action="stop")
        assert not result.success

    @pytest.mark.asyncio
    async def test_error_handling(self):
        """Tool should catch exceptions and return ToolResult with error."""
        result = await self.tool.execute(action="start", app_id="nonexistent")
        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_install_deps_no_requirements(self):
        app = await self.manager.create(name="No Deps", runtime="python")
        result = await self.tool.execute(action="install_deps", app_id=app.id)
        assert result.success
        assert "nothing to install" in result.output.lower()

    @pytest.mark.asyncio
    async def test_install_deps_requires_app_id(self):
        result = await self.tool.execute(action="install_deps")
        assert not result.success

    @pytest.mark.asyncio
    async def test_to_schema(self):
        """Tool should produce valid OpenAI function schema."""
        schema = self.tool.to_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "app"
        assert "parameters" in schema["function"]
