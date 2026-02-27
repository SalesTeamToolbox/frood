"""Tests for ProjectManager — project CRUD and task aggregation."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.project_manager import Project, ProjectManager
from core.task_queue import Task, TaskQueue, TaskStatus


class TestProject:
    """Test Project dataclass."""

    def test_create_default(self):
        project = Project(name="Test")
        assert project.name == "Test"
        assert project.status == "planning"
        assert project.priority == 0
        assert len(project.id) == 12

    def test_to_dict_roundtrip(self):
        project = Project(name="My Project", tags=["web", "api"], priority=1)
        d = project.to_dict()
        restored = Project.from_dict(d)
        assert restored.name == "My Project"
        assert restored.tags == ["web", "api"]
        assert restored.priority == 1

    def test_from_dict_ignores_unknown_fields(self):
        d = {"id": "abc", "name": "Test", "unknown": "ignored"}
        project = Project.from_dict(d)
        assert project.id == "abc"
        assert project.name == "Test"


class TestProjectManager:
    """Test ProjectManager CRUD and task aggregation."""

    @pytest.fixture
    def task_queue(self, tmp_path):
        return TaskQueue(str(tmp_path / "tasks.json"))

    @pytest.fixture
    def manager(self, tmp_path, task_queue):
        return ProjectManager(tmp_path / "projects", task_queue)

    @pytest.mark.asyncio
    async def test_create_project(self, manager):
        project = await manager.create(name="Website Redesign", description="Full redesign")
        assert project.name == "Website Redesign"
        assert project.description == "Full redesign"
        assert project.status == "planning"

    @pytest.mark.asyncio
    async def test_get_project(self, manager):
        project = await manager.create(name="Test")
        fetched = await manager.get(project.id)
        assert fetched is not None
        assert fetched.id == project.id

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, manager):
        result = await manager.get("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_projects(self, manager):
        await manager.create(name="Project A")
        await manager.create(name="Project B")
        projects = manager.list_projects()
        assert len(projects) == 2

    @pytest.mark.asyncio
    async def test_list_excludes_archived(self, manager):
        p1 = await manager.create(name="Active")
        p2 = await manager.create(name="Archived")
        await manager.archive(p2.id)

        active = manager.list_projects()
        assert len(active) == 1
        assert active[0].id == p1.id

        all_projects = manager.list_projects(include_archived=True)
        assert len(all_projects) == 2

    @pytest.mark.asyncio
    async def test_update_project(self, manager):
        project = await manager.create(name="Original")
        updated = await manager.update(project.id, name="Updated", priority=2)
        assert updated.name == "Updated"
        assert updated.priority == 2

    @pytest.mark.asyncio
    async def test_set_status(self, manager):
        project = await manager.create(name="Statusful")
        updated = await manager.set_status(project.id, "active")
        assert updated.status == "active"

    @pytest.mark.asyncio
    async def test_set_invalid_status(self, manager):
        project = await manager.create(name="Bad Status")
        result = await manager.set_status(project.id, "nonexistent_status")
        assert result is None

    @pytest.mark.asyncio
    async def test_archive_project(self, manager):
        project = await manager.create(name="To Archive")
        result = await manager.archive(project.id)
        assert result is True
        fetched = await manager.get(project.id)
        assert fetched.status == "archived"

    @pytest.mark.asyncio
    async def test_delete_project(self, manager):
        project = await manager.create(name="To Delete")
        result = await manager.delete(project.id)
        assert result is True
        assert await manager.get(project.id) is None

    @pytest.mark.asyncio
    async def test_project_stats(self, manager, task_queue):
        project = await manager.create(name="Stats Test")

        # Add tasks linked to the project
        t1 = Task(title="Task 1", description="", project_id=project.id, status=TaskStatus.DONE)
        t2 = Task(title="Task 2", description="", project_id=project.id, status=TaskStatus.DONE)
        t3 = Task(title="Task 3", description="", project_id=project.id, status=TaskStatus.RUNNING)
        t4 = Task(title="Task 4", description="", project_id=project.id, status=TaskStatus.FAILED)
        t5 = Task(title="Task 5", description="", project_id=project.id, status=TaskStatus.PENDING)
        # Unrelated task
        t6 = Task(title="Unrelated", description="", project_id="other")

        for t in [t1, t2, t3, t4, t5, t6]:
            await task_queue.add(t)

        stats = manager.project_stats(project.id)
        assert stats["total"] == 5
        assert stats["done"] == 2
        assert stats["running"] == 1
        assert stats["failed"] == 1
        assert stats["pending"] == 1

    @pytest.mark.asyncio
    async def test_get_project_tasks(self, manager, task_queue):
        project = await manager.create(name="Tasks Test")
        t1 = Task(title="Task A", description="", project_id=project.id)
        t2 = Task(title="Task B", description="", project_id=project.id)
        t3 = Task(title="Unrelated", description="", project_id="")
        for t in [t1, t2, t3]:
            await task_queue.add(t)

        tasks = manager.get_project_tasks(project.id)
        assert len(tasks) == 2

    @pytest.mark.asyncio
    async def test_board(self, manager):
        await manager.create(name="Planning Project")
        p2 = await manager.create(name="Active Project")
        await manager.set_status(p2.id, "active")
        p3 = await manager.create(name="Completed Project")
        await manager.set_status(p3.id, "completed")

        board = manager.board()
        assert len(board["planning"]) == 1
        assert len(board["active"]) == 1
        assert len(board["completed"]) == 1
        assert len(board["paused"]) == 0
        # Board entries include stats
        assert "stats" in board["planning"][0]

    @pytest.mark.asyncio
    async def test_persistence_across_reload(self, tmp_path, task_queue):
        projects_dir = tmp_path / "projects"

        mgr1 = ProjectManager(projects_dir, task_queue)
        await mgr1.create(name="Persist Test", tags=["web"])

        mgr2 = ProjectManager(projects_dir, task_queue)
        await mgr2.load()

        projects = mgr2.list_projects()
        assert len(projects) == 1
        assert projects[0].name == "Persist Test"
        assert projects[0].tags == ["web"]

    @pytest.mark.asyncio
    async def test_create_with_kwargs(self, manager):
        project = await manager.create(
            name="Full Project",
            description="Detailed description",
            tags=["frontend", "react"],
            priority=2,
            github_repo="user/repo",
            assigned_team="team-alpha",
        )
        assert project.name == "Full Project"
        assert project.priority == 2
        assert project.github_repo == "user/repo"
        assert project.assigned_team == "team-alpha"

    @pytest.mark.asyncio
    async def test_archive_project_with_app_archives_app(self, manager):
        """Archiving a project with app_id also archives the associated app."""
        project = await manager.create(name="App Project", app_id="abc123")

        mock_app_manager = MagicMock()
        mock_app_manager.delete = AsyncMock()

        result = await manager.archive(project.id, app_manager=mock_app_manager)

        assert result is True
        mock_app_manager.delete.assert_awaited_once_with("abc123")
        fetched = await manager.get(project.id)
        assert fetched.status == "archived"

    @pytest.mark.asyncio
    async def test_archive_project_with_app_not_found(self, manager):
        """Archiving a project continues successfully even if the app is missing."""
        project = await manager.create(name="Missing App Project", app_id="missing")

        mock_app_manager = MagicMock()
        mock_app_manager.delete = AsyncMock(side_effect=ValueError("App not found"))

        result = await manager.archive(project.id, app_manager=mock_app_manager)

        assert result is True
        fetched = await manager.get(project.id)
        assert fetched.status == "archived"

    @pytest.mark.asyncio
    async def test_archive_project_without_app_id(self, manager):
        """Archiving a project with no app_id does not call app_manager."""
        project = await manager.create(name="No App Project")

        mock_app_manager = MagicMock()
        mock_app_manager.delete = AsyncMock()

        result = await manager.archive(project.id, app_manager=mock_app_manager)

        assert result is True
        mock_app_manager.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_project_with_app_archives_app(self, manager):
        """Permanently deleting a project with app_id also archives the associated app."""
        project = await manager.create(name="Delete App Project", app_id="xyz789")

        mock_app_manager = MagicMock()
        mock_app_manager.delete = AsyncMock()

        result = await manager.delete(project.id, app_manager=mock_app_manager)

        assert result is True
        mock_app_manager.delete.assert_awaited_once_with("xyz789")
        assert await manager.get(project.id) is None
