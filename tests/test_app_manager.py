"""Tests for the App Manager — app lifecycle, port allocation, state transitions."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.app_manager import App, AppManager, AppRuntime, AppStatus, _make_slug


class TestMakeSlug:
    def test_basic_name(self):
        assert _make_slug("Fitness Tracker") == "fitness-tracker"

    def test_special_characters(self):
        assert _make_slug("My App! (v2.0)") == "my-app-v2-0"

    def test_long_name_truncated(self):
        slug = _make_slug("a" * 100)
        assert len(slug) <= 50

    def test_empty_name_fallback(self):
        assert _make_slug("") == "app"
        assert _make_slug("!!!") == "app"


class TestAppDataclass:
    def test_defaults(self):
        app = App()
        assert app.status == "draft"
        assert app.runtime == "static"
        assert app.version == "0.1.0"
        assert app.port == 0
        assert app.tags == []

    def test_to_dict(self):
        app = App(name="Test", slug="test", runtime="python")
        d = app.to_dict()
        assert d["name"] == "Test"
        assert d["slug"] == "test"
        assert d["runtime"] == "python"
        assert "id" in d
        assert "created_at" in d

    def test_from_dict(self):
        data = {
            "id": "abc123",
            "name": "Test App",
            "slug": "test-app",
            "runtime": "python",
            "status": "ready",
            "port": 9101,
            "unknown_field": "ignored",
        }
        app = App.from_dict(data)
        assert app.id == "abc123"
        assert app.name == "Test App"
        assert app.runtime == "python"

    def test_from_dict_ignores_unknown(self):
        data = {"id": "x", "name": "Y", "slug": "y", "extra_field": "dropped"}
        app = App.from_dict(data)
        assert app.id == "x"
        assert not hasattr(app, "extra_field")


class TestAppStatus:
    def test_enum_values(self):
        assert AppStatus.DRAFT.value == "draft"
        assert AppStatus.BUILDING.value == "building"
        assert AppStatus.READY.value == "ready"
        assert AppStatus.RUNNING.value == "running"
        assert AppStatus.STOPPED.value == "stopped"
        assert AppStatus.ERROR.value == "error"
        assert AppStatus.ARCHIVED.value == "archived"


class TestAppRuntime:
    def test_enum_values(self):
        assert AppRuntime.STATIC.value == "static"
        assert AppRuntime.PYTHON.value == "python"
        assert AppRuntime.NODE.value == "node"
        assert AppRuntime.DOCKER.value == "docker"


class TestAppManager:
    def setup_method(self, tmp_path=None):
        """Common setup — called by pytest with tmp_path fixture."""
        pass

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.apps_dir = tmp_path / "apps"
        self.manager = AppManager(
            apps_dir=str(self.apps_dir),
            port_range_start=9100,
            port_range_end=9110,
            max_running=3,
        )

    @pytest.mark.asyncio
    async def test_create_app(self):
        app = await self.manager.create(
            name="Test App",
            description="A test application",
            runtime="python",
            tags=["test"],
        )
        assert app.name == "Test App"
        assert app.slug == "test-app"
        assert app.runtime == "python"
        assert app.status == AppStatus.DRAFT.value
        assert app.tags == ["test"]
        assert (self.apps_dir / app.id / "APP.json").exists()
        assert (self.apps_dir / app.id / "src").exists()

    @pytest.mark.asyncio
    async def test_create_static_app(self):
        app = await self.manager.create(name="Static Site", runtime="static")
        assert app.entry_point == "public/index.html"
        assert (self.apps_dir / app.id / "public").exists()

    @pytest.mark.asyncio
    async def test_create_python_app(self):
        app = await self.manager.create(name="Flask App", runtime="python")
        assert app.entry_point == "src/app.py"

    @pytest.mark.asyncio
    async def test_create_node_app(self):
        app = await self.manager.create(name="Node App", runtime="node")
        assert app.entry_point == "src/index.js"

    @pytest.mark.asyncio
    async def test_create_docker_app(self):
        app = await self.manager.create(name="Docker App", runtime="docker")
        assert app.entry_point == "docker-compose.yml"

    @pytest.mark.asyncio
    async def test_unique_slugs(self):
        app1 = await self.manager.create(name="My App")
        app2 = await self.manager.create(name="My App")
        assert app1.slug != app2.slug
        assert app2.slug == "my-app-1"

    @pytest.mark.asyncio
    async def test_get_app(self):
        app = await self.manager.create(name="Find Me")
        found = await self.manager.get(app.id)
        assert found is not None
        assert found.name == "Find Me"

    @pytest.mark.asyncio
    async def test_get_nonexistent(self):
        found = await self.manager.get("nonexistent")
        assert found is None

    @pytest.mark.asyncio
    async def test_get_by_slug(self):
        app = await self.manager.create(name="Slug Test")
        found = self.manager.get_by_slug("slug-test")
        assert found is not None
        assert found.id == app.id

    @pytest.mark.asyncio
    async def test_list_apps(self):
        await self.manager.create(name="App 1")
        await self.manager.create(name="App 2")
        apps = self.manager.list_apps()
        assert len(apps) == 2

    @pytest.mark.asyncio
    async def test_list_excludes_archived(self):
        app = await self.manager.create(name="Archive Me")
        await self.manager.mark_ready(app.id)
        await self.manager.delete(app.id)
        apps = self.manager.list_apps()
        assert len(apps) == 0
        assert len(self.manager.all_apps()) == 1

    @pytest.mark.asyncio
    async def test_mark_building(self):
        app = await self.manager.create(name="Build Me")
        updated = await self.manager.mark_building(app.id, "task-123")
        assert updated.status == AppStatus.BUILDING.value
        assert updated.build_task_id == "task-123"

    @pytest.mark.asyncio
    async def test_mark_ready(self):
        app = await self.manager.create(name="Ready App")
        updated = await self.manager.mark_ready(app.id, version="1.0.0")
        assert updated.status == AppStatus.READY.value
        assert updated.version == "1.0.0"

    @pytest.mark.asyncio
    async def test_mark_error(self):
        app = await self.manager.create(name="Error App")
        updated = await self.manager.mark_error(app.id, "Build failed")
        assert updated.status == AppStatus.ERROR.value
        assert updated.error == "Build failed"

    @pytest.mark.asyncio
    async def test_start_static_app(self):
        app = await self.manager.create(name="Static", runtime="static")
        await self.manager.mark_ready(app.id)
        started = await self.manager.start(app.id)
        assert started.status == AppStatus.RUNNING.value
        assert started.url == "/apps/static/"

    @pytest.mark.asyncio
    async def test_start_requires_ready_or_stopped(self):
        app = await self.manager.create(name="Draft App")
        with pytest.raises(ValueError, match="must be ready or stopped"):
            await self.manager.start(app.id)

    @pytest.mark.asyncio
    async def test_start_nonexistent(self):
        with pytest.raises(ValueError, match="not found"):
            await self.manager.start("nonexistent")

    @pytest.mark.asyncio
    async def test_stop_static_app(self):
        app = await self.manager.create(name="Static Stop", runtime="static")
        await self.manager.mark_ready(app.id)
        await self.manager.start(app.id)
        stopped = await self.manager.stop(app.id)
        assert stopped.status == AppStatus.STOPPED.value
        assert stopped.url == ""

    @pytest.mark.asyncio
    async def test_stop_not_running(self):
        app = await self.manager.create(name="Not Running")
        await self.manager.mark_ready(app.id)
        with pytest.raises(ValueError, match="not running"):
            await self.manager.stop(app.id)

    @pytest.mark.asyncio
    async def test_delete_archives(self):
        app = await self.manager.create(name="Delete Me")
        await self.manager.delete(app.id)
        found = await self.manager.get(app.id)
        assert found.status == AppStatus.ARCHIVED.value

    @pytest.mark.asyncio
    async def test_delete_stops_running(self):
        app = await self.manager.create(name="Running Delete", runtime="static")
        await self.manager.mark_ready(app.id)
        await self.manager.start(app.id)
        await self.manager.delete(app.id)
        found = await self.manager.get(app.id)
        assert found.status == AppStatus.ARCHIVED.value

    @pytest.mark.asyncio
    async def test_permanent_delete(self):
        app = await self.manager.create(name="Perm Delete")
        app_path = self.apps_dir / app.id
        assert app_path.exists()
        await self.manager.delete_permanently(app.id)
        assert not app_path.exists()
        assert await self.manager.get(app.id) is None

    @pytest.mark.asyncio
    async def test_max_running_limit(self):
        manager = AppManager(
            apps_dir=str(self.apps_dir / "limited"),
            max_running=1,
        )
        app1 = await manager.create(name="App 1", runtime="static")
        app2 = await manager.create(name="App 2", runtime="static")
        await manager.mark_ready(app1.id)
        await manager.mark_ready(app2.id)
        await manager.start(app1.id)
        with pytest.raises(ValueError, match="Max running"):
            await manager.start(app2.id)

    @pytest.mark.asyncio
    async def test_port_allocation(self):
        # Static apps don't consume ports
        app = await self.manager.create(name="Static", runtime="static")
        await self.manager.mark_ready(app.id)
        started = await self.manager.start(app.id)
        assert started.port == 0  # Static apps don't use ports

    @pytest.mark.asyncio
    async def test_health_check_static(self):
        app = await self.manager.create(name="Health Static", runtime="static")
        # Create the entry point file
        from pathlib import Path

        public_dir = Path(app.path) / "public"
        public_dir.mkdir(parents=True, exist_ok=True)
        (public_dir / "index.html").write_text("<html></html>")

        await self.manager.mark_ready(app.id)
        await self.manager.start(app.id)
        health = await self.manager.health_check(app.id)
        assert health["healthy"] is True
        assert health["runtime"] == "static"

    @pytest.mark.asyncio
    async def test_health_check_not_running(self):
        app = await self.manager.create(name="Not Running Health")
        health = await self.manager.health_check(app.id)
        assert health["healthy"] is False

    @pytest.mark.asyncio
    async def test_health_check_nonexistent(self):
        health = await self.manager.health_check("nonexistent")
        assert health["healthy"] is False

    @pytest.mark.asyncio
    async def test_manifest_written(self):
        app = await self.manager.create(
            name="Manifest Test",
            description="Testing manifest",
            runtime="python",
            tags=["test", "manifest"],
        )
        manifest_path = self.apps_dir / app.id / "APP.json"
        manifest = json.loads(manifest_path.read_text())
        assert manifest["name"] == "Manifest Test"
        assert manifest["description"] == "Testing manifest"
        assert manifest["runtime"] == "python"
        assert manifest["tags"] == ["test", "manifest"]

    @pytest.mark.asyncio
    async def test_persistence(self):
        app = await self.manager.create(name="Persist Test")
        await self.manager.mark_ready(app.id)

        # Create a new manager instance (simulates restart)
        manager2 = AppManager(apps_dir=str(self.apps_dir))
        await manager2.load()
        found = await manager2.get(app.id)
        assert found is not None
        assert found.name == "Persist Test"
        assert found.status == AppStatus.READY.value

    @pytest.mark.asyncio
    async def test_persistence_running_becomes_stopped(self):
        """Running apps should be marked stopped after reload (process is gone)."""
        app = await self.manager.create(name="Running Persist", runtime="static")
        await self.manager.mark_ready(app.id)
        await self.manager.start(app.id)
        assert (await self.manager.get(app.id)).status == AppStatus.RUNNING.value

        # Reload
        manager2 = AppManager(apps_dir=str(self.apps_dir))
        await manager2.load()
        found = await manager2.get(app.id)
        assert found.status == AppStatus.STOPPED.value

    @pytest.mark.asyncio
    async def test_logs_no_process(self):
        app = await self.manager.create(name="No Logs")
        logs = await self.manager.logs(app.id)
        assert "no logs" in logs.lower() or "not running" in logs.lower()

    @pytest.mark.asyncio
    async def test_export_app(self):
        app = await self.manager.create(name="Export Me")
        from pathlib import Path

        # Write a file so the archive isn't empty
        (Path(app.path) / "test.txt").write_text("hello")
        archive = await self.manager.export_app(app.id)
        assert archive.exists()
        assert archive.suffix == ".zip"

    @pytest.mark.asyncio
    async def test_export_nonexistent(self):
        with pytest.raises(ValueError, match="not found"):
            await self.manager.export_app("nonexistent")

    @pytest.mark.asyncio
    async def test_shutdown_stops_running(self):
        app = await self.manager.create(name="Shutdown", runtime="static")
        await self.manager.mark_ready(app.id)
        await self.manager.start(app.id)
        await self.manager.shutdown()
        found = await self.manager.get(app.id)
        assert found.status == AppStatus.STOPPED.value


class TestAppMonitor:
    """Tests for the background health-check monitor."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.apps_dir = tmp_path / "apps"
        self.manager = AppManager(
            apps_dir=str(self.apps_dir),
            port_range_start=9100,
            port_range_end=9110,
            max_running=3,
            auto_restart=True,
        )

    @pytest.mark.asyncio
    async def test_start_and_stop_monitor(self):
        """Monitor task starts and stops cleanly."""
        await self.manager.start_monitor(interval=1.0)
        assert self.manager._monitor_task is not None
        assert not self.manager._monitor_task.done()

        await self.manager.stop_monitor()
        assert self.manager._monitor_task is None

    @pytest.mark.asyncio
    async def test_start_monitor_idempotent(self):
        """Calling start_monitor twice does not create a second task."""
        await self.manager.start_monitor(interval=1.0)
        first_task = self.manager._monitor_task
        await self.manager.start_monitor(interval=1.0)
        assert self.manager._monitor_task is first_task
        await self.manager.stop_monitor()

    @pytest.mark.asyncio
    async def test_stop_monitor_when_not_started(self):
        """stop_monitor is a no-op when the monitor was never started."""
        await self.manager.stop_monitor()  # should not raise

    @pytest.mark.asyncio
    async def test_crashed_process_detected_and_auto_restarted(self):
        """A crashed process is detected and restarted when auto_restart is on."""
        app = await self.manager.create(name="Crash Me", runtime="python")
        await self.manager.mark_ready(app.id)

        # Simulate a running app with a dead process
        app.status = AppStatus.RUNNING.value
        app.port = 9100
        app.pid = 99999
        app.url = "/apps/crash-me/"
        await self.manager._persist()

        # Create a mock process that has already exited
        dead_proc = MagicMock()
        dead_proc.returncode = 1
        dead_proc.communicate = AsyncMock(return_value=(b"", b"segfault"))
        self.manager._processes[app.id] = dead_proc

        # Patch start() so it doesn't actually spawn a subprocess
        with patch.object(self.manager, "start", new_callable=AsyncMock) as mock_start:
            mock_start.return_value = app
            await self.manager._check_and_restart()

        # start() was called to restart
        mock_start.assert_awaited_once_with(app.id)

    @pytest.mark.asyncio
    async def test_crashed_process_marked_error_when_auto_restart_off(self):
        """A crashed app goes to ERROR state when auto_restart is disabled."""
        manager = AppManager(
            apps_dir=str(self.apps_dir / "no_restart"),
            auto_restart=False,
        )
        app = await manager.create(name="No Restart", runtime="python")
        await manager.mark_ready(app.id)

        app.status = AppStatus.RUNNING.value
        app.port = 9100
        app.pid = 99999
        await manager._persist()

        dead_proc = MagicMock()
        dead_proc.returncode = 137
        dead_proc.communicate = AsyncMock(return_value=(b"", b"killed"))
        manager._processes[app.id] = dead_proc

        await manager._check_and_restart()

        found = await manager.get(app.id)
        assert found.status == AppStatus.ERROR.value
        assert "137" in found.error

    @pytest.mark.asyncio
    async def test_crashed_process_per_app_auto_restart_off(self):
        """Per-app auto_restart=False is respected even if global is on."""
        app = await self.manager.create(name="Per-App Off", runtime="python")
        await self.manager.mark_ready(app.id)

        app.status = AppStatus.RUNNING.value
        app.auto_restart = False
        app.port = 9100
        app.pid = 99999
        await self.manager._persist()

        dead_proc = MagicMock()
        dead_proc.returncode = 1
        dead_proc.communicate = AsyncMock(return_value=(b"", b""))
        self.manager._processes[app.id] = dead_proc

        await self.manager._check_and_restart()

        found = await self.manager.get(app.id)
        assert found.status == AppStatus.ERROR.value

    @pytest.mark.asyncio
    async def test_healthy_apps_are_untouched(self):
        """Running apps with a live process are not disturbed."""
        app = await self.manager.create(name="Healthy", runtime="python")
        await self.manager.mark_ready(app.id)

        app.status = AppStatus.RUNNING.value
        app.port = 9100
        app.pid = 12345
        await self.manager._persist()

        alive_proc = MagicMock()
        alive_proc.returncode = None  # still running
        self.manager._processes[app.id] = alive_proc

        await self.manager._check_and_restart()

        found = await self.manager.get(app.id)
        assert found.status == AppStatus.RUNNING.value

    @pytest.mark.asyncio
    async def test_static_apps_skipped(self):
        """Static apps have no process and are always skipped by the monitor."""
        app = await self.manager.create(name="Static Skip", runtime="static")
        await self.manager.mark_ready(app.id)
        await self.manager.start(app.id)

        # No process entry exists for static apps — should not crash or change state
        await self.manager._check_and_restart()

        found = await self.manager.get(app.id)
        assert found.status == AppStatus.RUNNING.value

    @pytest.mark.asyncio
    async def test_shutdown_stops_monitor(self):
        """shutdown() stops the monitor before stopping apps."""
        await self.manager.start_monitor(interval=60.0)
        assert self.manager._monitor_task is not None

        await self.manager.shutdown()
        assert self.manager._monitor_task is None

    @pytest.mark.asyncio
    async def test_monitor_loop_runs_check(self):
        """The monitor loop calls _check_and_restart at least once."""
        with patch.object(
            self.manager, "_check_and_restart", new_callable=AsyncMock,
        ) as mock_check:
            await self.manager.start_monitor(interval=0.1)
            # Give the loop time to run at least one tick
            await asyncio.sleep(0.3)
            await self.manager.stop_monitor()

        assert mock_check.await_count >= 1
