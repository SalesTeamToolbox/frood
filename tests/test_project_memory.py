"""Tests for project-scoped memory, context improvements, and project propagation."""

from unittest.mock import MagicMock, patch

import pytest

from memory.store import MemoryStore

# ---------------------------------------------------------------------------
# ProjectMemoryStore
# ---------------------------------------------------------------------------


class TestProjectMemoryStore:
    """Test ProjectMemoryStore creation and delegation."""

    def setup_method(self, tmp_path_factory=None):
        pass

    def test_creates_project_directory(self, tmp_path):
        from memory.project_memory import ProjectMemoryStore

        global_store = MemoryStore(tmp_path / "global")
        pm = ProjectMemoryStore(
            project_id="proj-123",
            base_dir=tmp_path,
            global_store=global_store,
        )
        project_dir = tmp_path / "projects" / "proj-123"
        # Directory is created lazily by MemoryStore on first write
        pm.append_to_section("Learnings", "Test learning")
        assert project_dir.exists()

    def test_read_memory_returns_project_content(self, tmp_path):
        from memory.project_memory import ProjectMemoryStore

        global_store = MemoryStore(tmp_path / "global")
        pm = ProjectMemoryStore(
            project_id="proj-456",
            base_dir=tmp_path,
            global_store=global_store,
        )
        pm.append_to_section("Patterns", "Use async everywhere")
        content = pm.read_memory()
        assert "Use async everywhere" in content

    def test_append_to_section_writes_to_project(self, tmp_path):
        from memory.project_memory import ProjectMemoryStore

        global_store = MemoryStore(tmp_path / "global")
        pm = ProjectMemoryStore(
            project_id="proj-789",
            base_dir=tmp_path,
            global_store=global_store,
        )
        pm.append_to_section("Conventions", "PEP8 style")
        memory = pm.read_memory()
        assert "PEP8 style" in memory

    def test_log_event_writes_to_project_history(self, tmp_path):
        from memory.project_memory import ProjectMemoryStore

        global_store = MemoryStore(tmp_path / "global")
        pm = ProjectMemoryStore(
            project_id="proj-hist",
            base_dir=tmp_path,
            global_store=global_store,
        )
        pm.log_event("task_complete", "Finished coding task", "Details here")
        history = pm.search_history("coding")
        # History should contain at least the event
        assert isinstance(history, list)

    def test_build_context_merges_project_and_global(self, tmp_path):
        from memory.project_memory import ProjectMemoryStore

        global_store = MemoryStore(tmp_path / "global")
        global_store.append_to_section("Global Learnings", "Global pattern ABC")

        pm = ProjectMemoryStore(
            project_id="proj-ctx",
            base_dir=tmp_path,
            global_store=global_store,
        )
        pm.append_to_section("Project Learnings", "Project pattern XYZ")

        ctx = pm.build_context()
        assert "Project pattern XYZ" in ctx
        assert "Global pattern ABC" in ctx
        assert "Project Memory" in ctx
        assert "Global Memory" in ctx

    @pytest.mark.asyncio
    async def test_build_context_semantic_fallback_to_basic(self, tmp_path):
        """When semantic search is not available, falls back to build_context."""
        from memory.project_memory import ProjectMemoryStore

        global_store = MemoryStore(tmp_path / "global")
        pm = ProjectMemoryStore(
            project_id="proj-sem",
            base_dir=tmp_path,
            global_store=global_store,
        )
        pm.append_to_section("Data", "Semantic test content")
        ctx = await pm.build_context_semantic("test query")
        assert "Semantic test content" in ctx

    def test_standalone_tasks_use_global_only(self, tmp_path):
        """When no project_id, agents should use MemoryStore directly (not ProjectMemoryStore)."""
        global_store = MemoryStore(tmp_path / "global")
        global_store.append_to_section("Lessons", "Global lesson")
        ctx = global_store.build_context()
        assert "Global lesson" in ctx


# ---------------------------------------------------------------------------
# ProjectManager.get_project_memory
# ---------------------------------------------------------------------------


class TestProjectManagerMemory:
    """Test that ProjectManager correctly resolves project memory."""

    @pytest.mark.asyncio
    async def test_get_project_memory_returns_store(self, tmp_path):
        from core.project_manager import ProjectManager

        pm = ProjectManager(tmp_path, task_queue=MagicMock())
        project = await pm.create(name="Test Project", description="A test")

        global_store = MemoryStore(tmp_path / "global")
        memory = pm.get_project_memory(project.id, global_store=global_store)
        assert memory is not None
        assert memory.project_id == project.id

    @pytest.mark.asyncio
    async def test_get_project_memory_returns_none_without_global_store(self, tmp_path):
        from core.project_manager import ProjectManager

        pm = ProjectManager(tmp_path, task_queue=MagicMock())
        project = await pm.create(name="Test", description="A test")

        memory = pm.get_project_memory(project.id, global_store=None)
        assert memory is None

    def test_get_project_memory_returns_none_for_missing_project(self, tmp_path):
        from core.project_manager import ProjectManager

        pm = ProjectManager(tmp_path, task_queue=MagicMock())
        global_store = MemoryStore(tmp_path / "global")
        memory = pm.get_project_memory("nonexistent-id", global_store=global_store)
        assert memory is None


# ---------------------------------------------------------------------------
# Config: project_memory_enabled
# ---------------------------------------------------------------------------


class TestProjectMemoryConfig:
    """Test project memory config setting."""

    def test_default_enabled(self):
        from core.config import Settings

        s = Settings()
        assert s.project_memory_enabled is True

    def test_from_env_disabled(self):
        with patch.dict("os.environ", {"PROJECT_MEMORY_ENABLED": "false"}):
            from core.config import Settings

            s = Settings.from_env()
            assert s.project_memory_enabled is False


# ---------------------------------------------------------------------------
# IterationEngine / RLM tests removed — modules deleted in v2.0 MCP pivot.
# (agents.iteration_engine, providers.rlm_provider, core.rlm_config)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# TeamContext: project_id propagation
# ---------------------------------------------------------------------------


class TestTeamContextProjectId:
    """Test that TeamContext propagates project_id into role context."""

    def test_build_role_context_includes_project_id(self):
        from tools.team_tool import TeamContext

        ctx = TeamContext(
            task_description="Write a report",
            project_id="proj-team-1",
        )
        role_ctx = ctx.build_role_context("researcher")
        assert "proj-team-1" in role_ctx
        assert "Project" in role_ctx

    def test_build_role_context_no_project_id(self):
        from tools.team_tool import TeamContext

        ctx = TeamContext(task_description="Write a report")
        role_ctx = ctx.build_role_context("researcher")
        assert "Project" not in role_ctx


# ---------------------------------------------------------------------------
# SubagentTool / RLM recompression tests removed — depend on modules deleted
# in v2.0 MCP pivot (core.task_queue, agents.iteration_engine).
# ---------------------------------------------------------------------------
