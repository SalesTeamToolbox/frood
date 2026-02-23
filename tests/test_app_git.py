"""Tests for App git/GitHub integration — per-app version control."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from core.app_manager import App, AppManager, AppStatus


class TestAppGitFields:
    """Test that git/GitHub fields are present and serialize correctly."""

    def test_defaults(self):
        app = App()
        assert app.git_enabled is False
        assert app.github_repo == ""
        assert app.github_push_on_build is False

    def test_to_dict_includes_git_fields(self):
        app = App(name="Test", git_enabled=True, github_repo="owner/repo")
        d = app.to_dict()
        assert d["git_enabled"] is True
        assert d["github_repo"] == "owner/repo"
        assert d["github_push_on_build"] is False

    def test_from_dict_with_git_fields(self):
        data = {
            "id": "abc",
            "name": "Test",
            "slug": "test",
            "git_enabled": True,
            "github_repo": "user/my-app",
            "github_push_on_build": True,
        }
        app = App.from_dict(data)
        assert app.git_enabled is True
        assert app.github_repo == "user/my-app"
        assert app.github_push_on_build is True

    def test_from_dict_without_git_fields(self):
        """Backward compat: old apps without git fields get defaults."""
        data = {"id": "old", "name": "Old App", "slug": "old-app"}
        app = App.from_dict(data)
        assert app.git_enabled is False
        assert app.github_repo == ""


class TestAppManagerGit:
    """Test git operations in AppManager."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.apps_dir = tmp_path / "apps"
        self.manager = AppManager(
            apps_dir=str(self.apps_dir),
            port_range_start=9100,
            port_range_end=9110,
            max_running=3,
            git_enabled_default=False,
        )

    @pytest.mark.asyncio
    async def test_create_without_git(self):
        app = await self.manager.create(name="No Git App")
        assert app.git_enabled is False
        assert not (Path(app.path) / ".git").exists()

    @pytest.mark.asyncio
    async def test_create_with_git_enabled(self):
        app = await self.manager.create(name="Git App", git_enabled=True)
        assert app.git_enabled is True
        assert (Path(app.path) / ".git").exists()
        assert (Path(app.path) / ".gitignore").exists()

    @pytest.mark.asyncio
    async def test_create_respects_default_setting(self):
        manager = AppManager(
            apps_dir=str(self.apps_dir / "default_git"),
            git_enabled_default=True,
        )
        app = await manager.create(name="Default Git")
        assert app.git_enabled is True
        assert (Path(app.path) / ".git").exists()

    @pytest.mark.asyncio
    async def test_create_override_default(self):
        """Explicit git_enabled=False overrides default=True."""
        manager = AppManager(
            apps_dir=str(self.apps_dir / "override"),
            git_enabled_default=True,
        )
        app = await manager.create(name="No Git Override", git_enabled=False)
        assert app.git_enabled is False

    @pytest.mark.asyncio
    async def test_manifest_includes_git_fields(self):
        app = await self.manager.create(name="Manifest Git", git_enabled=True)
        manifest_path = Path(app.path) / "APP.json"
        manifest = json.loads(manifest_path.read_text())
        assert manifest["git_enabled"] is True
        assert manifest["github_repo"] == ""

    @pytest.mark.asyncio
    async def test_git_enable(self):
        app = await self.manager.create(name="Enable Later")
        assert app.git_enabled is False
        result = await self.manager.git_enable(app.id)
        assert "enabled" in result.lower()
        updated = await self.manager.get(app.id)
        assert updated.git_enabled is True
        assert (Path(app.path) / ".git").exists()

    @pytest.mark.asyncio
    async def test_git_enable_already_enabled(self):
        app = await self.manager.create(name="Already Git", git_enabled=True)
        result = await self.manager.git_enable(app.id)
        assert "already enabled" in result.lower()

    @pytest.mark.asyncio
    async def test_git_disable(self):
        app = await self.manager.create(name="Disable Git", git_enabled=True)
        result = await self.manager.git_disable(app.id)
        assert "disabled" in result.lower()
        updated = await self.manager.get(app.id)
        assert updated.git_enabled is False
        # .git dir preserved on disk
        assert (Path(app.path) / ".git").exists()

    @pytest.mark.asyncio
    async def test_git_disable_already_disabled(self):
        app = await self.manager.create(name="No Git")
        result = await self.manager.git_disable(app.id)
        assert "already disabled" in result.lower()

    @pytest.mark.asyncio
    async def test_git_commit(self):
        app = await self.manager.create(name="Commit Test", git_enabled=True)
        # Write a file to commit
        (Path(app.path) / "src" / "hello.py").write_text("print('hello')")
        result = await self.manager.git_commit(app.id, message="Add hello.py")
        assert "committed" in result.lower() or "add hello" in result.lower()

    @pytest.mark.asyncio
    async def test_git_commit_no_changes(self):
        app = await self.manager.create(name="No Changes", git_enabled=True)
        result = await self.manager.git_commit(app.id, message="Nothing")
        assert "no changes" in result.lower()

    @pytest.mark.asyncio
    async def test_git_commit_not_enabled(self):
        app = await self.manager.create(name="No Git Commit")
        with pytest.raises(ValueError, match="not enabled"):
            await self.manager.git_commit(app.id, message="fail")

    @pytest.mark.asyncio
    async def test_git_status(self):
        app = await self.manager.create(name="Status App", git_enabled=True)
        result = await self.manager.git_status(app.id)
        assert "status" in result.lower() or "clean" in result.lower()

    @pytest.mark.asyncio
    async def test_git_status_with_changes(self):
        app = await self.manager.create(name="Dirty Status", git_enabled=True)
        (Path(app.path) / "src" / "new.py").write_text("x = 1")
        result = await self.manager.git_status(app.id)
        assert "new.py" in result or "?" in result

    @pytest.mark.asyncio
    async def test_git_status_not_enabled(self):
        app = await self.manager.create(name="No Git Status")
        result = await self.manager.git_status(app.id)
        assert "not enabled" in result.lower()

    @pytest.mark.asyncio
    async def test_git_log(self):
        app = await self.manager.create(name="Log App", git_enabled=True)
        result = await self.manager.git_log(app.id)
        assert "initial commit" in result.lower()

    @pytest.mark.asyncio
    async def test_git_log_not_enabled(self):
        app = await self.manager.create(name="No Git Log")
        result = await self.manager.git_log(app.id)
        assert "not enabled" in result.lower()

    @pytest.mark.asyncio
    async def test_mark_ready_auto_commits(self):
        app = await self.manager.create(name="Auto Commit", runtime="python", git_enabled=True)
        # Write the entry point
        (Path(app.path) / "src" / "app.py").write_text("import os\nprint('hello')\n")
        await self.manager.mark_ready(app.id, version="1.0.0")

        # Check that the commit was made
        rc, out, _ = await self.manager._run_git(Path(app.path), "log", "--oneline", "-1")
        assert rc == 0
        assert "build ready" in out.lower()

    @pytest.mark.asyncio
    async def test_mark_ready_no_git_no_commit(self):
        """mark_ready without git should not crash."""
        app = await self.manager.create(name="No Git Ready")
        updated = await self.manager.mark_ready(app.id, version="1.0.0")
        assert updated.status == AppStatus.READY.value

    @pytest.mark.asyncio
    async def test_persistence_with_git_fields(self):
        """Git fields survive persistence round-trip."""
        app = await self.manager.create(name="Persist Git", git_enabled=True)
        app.github_repo = "owner/persist-test"
        app.github_push_on_build = True
        await self.manager._persist()

        # Reload
        manager2 = AppManager(apps_dir=str(self.apps_dir))
        await manager2.load()
        found = await manager2.get(app.id)
        assert found.git_enabled is True
        assert found.github_repo == "owner/persist-test"
        assert found.github_push_on_build is True

    @pytest.mark.asyncio
    async def test_git_enable_nonexistent(self):
        with pytest.raises(ValueError, match="not found"):
            await self.manager.git_enable("nonexistent")

    @pytest.mark.asyncio
    async def test_git_commit_nonexistent(self):
        with pytest.raises(ValueError, match="not found"):
            await self.manager.git_commit("nonexistent")

    @pytest.mark.asyncio
    async def test_github_push_no_repo(self):
        app = await self.manager.create(name="No Repo", git_enabled=True)
        with pytest.raises(ValueError, match="No GitHub repo"):
            await self.manager.github_push(app.id)

    @pytest.mark.asyncio
    async def test_github_setup_no_gh_no_token(self):
        """github_setup without gh CLI or token gives helpful message."""
        app = await self.manager.create(name="No Auth", git_enabled=True)
        with patch.object(self.manager, "_check_command", return_value=False):
            result = await self.manager.github_setup(app.id, repo_name="test")
        assert "gh" in result.lower() or "token" in result.lower()

    @pytest.mark.asyncio
    async def test_gitignore_contents(self):
        app = await self.manager.create(name="Gitignore Test", git_enabled=True)
        gitignore = (Path(app.path) / ".gitignore").read_text()
        assert "__pycache__/" in gitignore
        assert "node_modules/" in gitignore
        assert ".env" in gitignore


class TestAppToolGit:
    """Test git/GitHub actions via the AppTool interface."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        from tools.app_tool import AppTool

        self.apps_dir = tmp_path / "apps"
        self.manager = AppManager(
            apps_dir=str(self.apps_dir),
            port_range_start=9100,
            port_range_end=9110,
            max_running=3,
        )
        self.tool = AppTool(self.manager)

    @pytest.mark.asyncio
    async def test_create_with_git_flag(self):
        result = await self.tool.execute(
            action="create",
            name="Git Tool App",
            git_enabled=True,
        )
        assert result.success
        assert "enabled" in result.output.lower()

    @pytest.mark.asyncio
    async def test_create_with_git_string_true(self):
        """Handle string 'true' from tool parameters."""
        result = await self.tool.execute(
            action="create",
            name="Git String",
            git_enabled="true",
        )
        assert result.success
        assert "enabled" in result.output.lower()

    @pytest.mark.asyncio
    async def test_git_enable_action(self):
        app = await self.manager.create(name="Enable Via Tool")
        result = await self.tool.execute(action="git_enable", app_id=app.id)
        assert result.success
        assert "enabled" in result.output.lower()

    @pytest.mark.asyncio
    async def test_git_disable_action(self):
        app = await self.manager.create(name="Disable Via Tool", git_enabled=True)
        result = await self.tool.execute(action="git_disable", app_id=app.id)
        assert result.success
        assert "disabled" in result.output.lower()

    @pytest.mark.asyncio
    async def test_git_commit_action(self):
        app = await self.manager.create(name="Commit Via Tool", git_enabled=True)
        (Path(app.path) / "src" / "test.py").write_text("# test")
        result = await self.tool.execute(action="git_commit", app_id=app.id, message="Test commit")
        assert result.success

    @pytest.mark.asyncio
    async def test_git_status_action(self):
        app = await self.manager.create(name="Status Via Tool", git_enabled=True)
        result = await self.tool.execute(action="git_status", app_id=app.id)
        assert result.success

    @pytest.mark.asyncio
    async def test_git_log_action(self):
        app = await self.manager.create(name="Log Via Tool", git_enabled=True)
        result = await self.tool.execute(action="git_log", app_id=app.id)
        assert result.success
        assert "initial commit" in result.output.lower()

    @pytest.mark.asyncio
    async def test_git_actions_require_app_id(self):
        for action in [
            "git_enable",
            "git_disable",
            "git_commit",
            "git_status",
            "git_log",
            "github_setup",
            "github_push",
        ]:
            result = await self.tool.execute(action=action)
            assert not result.success
            assert "required" in result.error.lower()

    @pytest.mark.asyncio
    async def test_status_shows_git_info(self):
        app = await self.manager.create(name="Status Git Info", git_enabled=True)
        result = await self.tool.execute(action="status", app_id=app.id)
        assert "Git: enabled" in result.output

    @pytest.mark.asyncio
    async def test_status_shows_github_info(self):
        app = await self.manager.create(name="Status GitHub", git_enabled=True)
        app.github_repo = "owner/status-test"
        app.github_push_on_build = True
        result = await self.tool.execute(action="status", app_id=app.id)
        assert "owner/status-test" in result.output
        assert "Push on build: True" in result.output

    @pytest.mark.asyncio
    async def test_list_shows_git_indicator(self):
        await self.manager.create(name="Git App", git_enabled=True)
        await self.manager.create(name="Plain App")
        result = await self.tool.execute(action="list")
        assert "[git]" in result.output

    @pytest.mark.asyncio
    async def test_parameters_include_git_actions(self):
        params = self.tool.parameters
        actions = params["properties"]["action"]["enum"]
        assert "git_enable" in actions
        assert "git_disable" in actions
        assert "git_commit" in actions
        assert "git_status" in actions
        assert "git_log" in actions
        assert "github_setup" in actions
        assert "github_push" in actions

    @pytest.mark.asyncio
    async def test_parameters_include_git_fields(self):
        params = self.tool.parameters
        props = params["properties"]
        assert "git_enabled" in props
        assert "message" in props
        assert "repo_name" in props
        assert "private" in props
        assert "push_on_build" in props
