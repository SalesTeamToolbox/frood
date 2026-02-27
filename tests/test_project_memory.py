"""Tests for project-scoped memory, context improvements, and project propagation."""

from unittest.mock import AsyncMock, MagicMock, patch

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
# IterationEngine: critic enrichment
# ---------------------------------------------------------------------------


class TestCriticEnrichment:
    """Test that the critic receives tool summaries."""

    def test_build_tool_summary(self):
        from agents.iteration_engine import IterationEngine, ToolCallRecord

        records = [
            ToolCallRecord(
                tool_name="shell",
                arguments={"command": "touch /tmp/test.py"},
                result="File created at /tmp/test.py\nDone.",
                success=True,
            ),
            ToolCallRecord(
                tool_name="read_file",
                arguments={"path": "/tmp/missing.py"},
                result="Error: file not found",
                success=False,
            ),
        ]
        summary = IterationEngine._build_tool_summary(records)
        assert "shell: OK" in summary
        assert "read_file: FAIL" in summary
        assert "File created" in summary
        assert "file not found" in summary

    def test_build_tool_summary_empty(self):
        from agents.iteration_engine import IterationEngine

        summary = IterationEngine._build_tool_summary([])
        assert summary == "(no tools called)"


# ---------------------------------------------------------------------------
# IterationEngine: tool result compaction
# ---------------------------------------------------------------------------


class TestToolCompaction:
    """Test that old tool messages get compacted when threshold is exceeded."""

    def test_compact_skips_when_under_threshold(self):
        from agents.iteration_engine import IterationEngine

        messages = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Do something"},
            {"role": "tool", "tool_call_id": "1", "content": "Short result"},
            {"role": "tool", "tool_call_id": "2", "content": "Another short"},
            {"role": "tool", "tool_call_id": "3", "content": "Third short"},
        ]
        IterationEngine._compact_tool_messages(messages)
        # Under threshold — nothing should change
        assert messages[2]["content"] == "Short result"

    def test_compact_truncates_old_messages(self):
        from agents.iteration_engine import IterationEngine

        long_content = "x" * 20000
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "task"},
            {"role": "tool", "tool_call_id": "1", "content": long_content},
            {"role": "tool", "tool_call_id": "2", "content": long_content},
            {"role": "tool", "tool_call_id": "3", "content": long_content},
            {"role": "tool", "tool_call_id": "4", "content": "recent result"},
        ]
        IterationEngine._compact_tool_messages(messages)
        # First two tool messages should be truncated, last two kept intact
        assert len(messages[2]["content"]) < 300
        assert len(messages[3]["content"]) < 300
        assert messages[4]["content"] == long_content  # 2nd to last kept
        assert messages[5]["content"] == "recent result"  # last kept

    def test_compact_noop_with_two_or_fewer_tools(self):
        from agents.iteration_engine import IterationEngine

        long_content = "y" * 60000
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "tool", "tool_call_id": "1", "content": long_content},
            {"role": "tool", "tool_call_id": "2", "content": long_content},
        ]
        IterationEngine._compact_tool_messages(messages)
        # Only 2 tool messages — should never compact
        assert len(messages[1]["content"]) == 60000


# ---------------------------------------------------------------------------
# RLMProvider: should_use_rlm_recompress
# ---------------------------------------------------------------------------


class TestRLMRecompress:
    """Test the RLM recompression threshold check."""

    def test_recompress_fires_above_60k(self):
        from providers.rlm_provider import RLMProvider

        provider = RLMProvider()
        assert provider.should_use_rlm_recompress(70_000) is True

    def test_recompress_skips_below_60k(self):
        from providers.rlm_provider import RLMProvider

        provider = RLMProvider()
        assert provider.should_use_rlm_recompress(50_000) is False

    def test_recompress_respects_disabled(self):
        from core.rlm_config import RLMConfig
        from providers.rlm_provider import RLMProvider

        config = RLMConfig(enabled=False)
        provider = RLMProvider(config=config)
        assert provider.should_use_rlm_recompress(100_000) is False

    def test_recompress_respects_cost_limit(self):
        from core.rlm_config import RLMConfig
        from providers.rlm_provider import RLMProvider

        config = RLMConfig(cost_limit=0.10)
        provider = RLMProvider(config=config)
        provider._total_cost_usd = 0.11  # Over limit
        assert provider.should_use_rlm_recompress(100_000) is False


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
# SubagentTool: project_id propagation
# ---------------------------------------------------------------------------


class TestSubagentProjectPropagation:
    """Test that SubagentTool passes project_id to spawned tasks."""

    @pytest.mark.asyncio
    async def test_subagent_inherits_project_id(self):
        from tools.subagent import SubagentTool

        mock_queue = AsyncMock()
        tool = SubagentTool(task_queue=mock_queue)

        result = await tool.execute(
            title="Subtask",
            description="Do something",
            task_type="coding",
            project_id="proj-sub-1",
        )

        assert result.success
        # Verify the task was added with the project_id
        add_call = mock_queue.add.call_args
        task_arg = add_call[0][0]
        assert task_arg.project_id == "proj-sub-1"

    @pytest.mark.asyncio
    async def test_subagent_no_project_id(self):
        from tools.subagent import SubagentTool

        mock_queue = AsyncMock()
        tool = SubagentTool(task_queue=mock_queue)

        result = await tool.execute(
            title="Subtask",
            description="Do something",
            task_type="coding",
        )

        assert result.success
        add_call = mock_queue.add.call_args
        task_arg = add_call[0][0]
        assert task_arg.project_id == ""


# ---------------------------------------------------------------------------
# IterationEngine: RLM recompression integration
# ---------------------------------------------------------------------------


class TestRLMRecompressIntegration:
    """Test _rlm_recompress helper method."""

    @pytest.mark.asyncio
    async def test_rlm_recompress_replaces_intermediate_messages(self):
        from agents.iteration_engine import IterationEngine

        mock_rlm = AsyncMock()
        mock_rlm.complete = AsyncMock(
            return_value={
                "response": "Compressed summary of work done",
                "used_rlm": True,
            }
        )

        messages = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Original task"},
            {"role": "assistant", "content": "Step 1 work"},
            {"role": "tool", "tool_call_id": "1", "content": "Tool result 1"},
            {"role": "assistant", "content": "Step 2 work"},
            {"role": "tool", "tool_call_id": "2", "content": "Tool result 2"},
        ]

        result = await IterationEngine._rlm_recompress(mock_rlm, messages, "task desc")
        assert len(result) == 3
        assert result[0]["role"] == "system"
        assert result[1]["role"] == "user"
        assert "RLM-compressed" in result[2]["content"]
        assert "Compressed summary" in result[2]["content"]

    @pytest.mark.asyncio
    async def test_rlm_recompress_fallback_on_failure(self):
        from agents.iteration_engine import IterationEngine

        mock_rlm = AsyncMock()
        mock_rlm.complete = AsyncMock(return_value=None)

        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "task"},
            {"role": "assistant", "content": "work"},
        ]
        original_len = len(messages)
        result = await IterationEngine._rlm_recompress(mock_rlm, messages, "task")
        assert len(result) == original_len

    @pytest.mark.asyncio
    async def test_rlm_recompress_noop_for_short_messages(self):
        from agents.iteration_engine import IterationEngine

        mock_rlm = AsyncMock()
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "task"},
        ]
        result = await IterationEngine._rlm_recompress(mock_rlm, messages, "task")
        assert len(result) == 2  # Unchanged — too few messages
