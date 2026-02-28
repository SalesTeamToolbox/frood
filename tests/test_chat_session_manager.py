"""Tests for ChatSessionManager — session CRUD and JSONL message persistence.

Also tests Agent._build_context() integration with chat history.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.chat_session_manager import ChatSession, ChatSessionManager


class TestChatSession:
    """Test ChatSession dataclass."""

    def test_create_default(self):
        session = ChatSession()
        assert session.title == "New Chat"
        assert session.session_type == "chat"
        assert session.message_count == 0
        assert not session.archived
        assert len(session.id) == 12

    def test_to_dict_roundtrip(self):
        session = ChatSession(title="Test", session_type="code", project_id="proj1")
        d = session.to_dict()
        restored = ChatSession.from_dict(d)
        assert restored.title == "Test"
        assert restored.session_type == "code"
        assert restored.project_id == "proj1"

    def test_from_dict_ignores_unknown_fields(self):
        d = {"id": "abc123", "title": "Hello", "unknown_field": "ignored"}
        session = ChatSession.from_dict(d)
        assert session.id == "abc123"
        assert session.title == "Hello"


class TestChatSessionManager:
    """Test ChatSessionManager CRUD and message persistence."""

    @pytest.fixture
    def manager(self, tmp_path):
        return ChatSessionManager(tmp_path / "sessions")

    @pytest.mark.asyncio
    async def test_create_session(self, manager):
        session = await manager.create(title="My Chat", session_type="chat")
        assert session.title == "My Chat"
        assert session.session_type == "chat"
        assert len(session.id) == 12

    @pytest.mark.asyncio
    async def test_get_session(self, manager):
        session = await manager.create(title="Test")
        fetched = await manager.get(session.id)
        assert fetched is not None
        assert fetched.id == session.id

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_none(self, manager):
        result = await manager.get("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_sessions(self, manager):
        await manager.create(title="Chat 1", session_type="chat")
        await manager.create(title="Code 1", session_type="code")
        await manager.create(title="Chat 2", session_type="chat")

        all_sessions = manager.list_sessions()
        assert len(all_sessions) == 3

        chat_only = manager.list_sessions(session_type="chat")
        assert len(chat_only) == 2

        code_only = manager.list_sessions(session_type="code")
        assert len(code_only) == 1

    @pytest.mark.asyncio
    async def test_list_excludes_archived(self, manager):
        s1 = await manager.create(title="Active")
        s2 = await manager.create(title="Archived")
        await manager.archive(s2.id)

        active = manager.list_sessions()
        assert len(active) == 1
        assert active[0].id == s1.id

        all_sessions = manager.list_sessions(include_archived=True)
        assert len(all_sessions) == 2

    @pytest.mark.asyncio
    async def test_rename_session(self, manager):
        session = await manager.create(title="Original")
        updated = await manager.rename(session.id, "Renamed")
        assert updated is not None
        assert updated.title == "Renamed"

    @pytest.mark.asyncio
    async def test_archive_session(self, manager):
        session = await manager.create(title="To Archive")
        result = await manager.archive(session.id)
        assert result is True
        fetched = await manager.get(session.id)
        assert fetched.archived is True

    @pytest.mark.asyncio
    async def test_delete_session(self, manager):
        session = await manager.create(title="To Delete")
        await manager.add_message(session.id, {"role": "user", "content": "Hello"})

        result = await manager.delete(session.id)
        assert result is True
        assert await manager.get(session.id) is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, manager):
        result = await manager.delete("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_add_and_get_messages(self, manager):
        session = await manager.create(title="Msg Test")
        await manager.add_message(session.id, {"role": "user", "content": "Hello"})
        await manager.add_message(session.id, {"role": "assistant", "content": "Hi there"})

        messages = await manager.get_messages(session.id)
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "Hello"
        assert messages[1]["role"] == "assistant"
        assert "id" in messages[0]  # Auto-assigned
        assert "timestamp" in messages[0]

    @pytest.mark.asyncio
    async def test_message_limit(self, manager):
        session = await manager.create(title="Limit Test")
        for i in range(10):
            await manager.add_message(session.id, {"role": "user", "content": f"Msg {i}"})

        messages = await manager.get_messages(session.id, limit=5)
        assert len(messages) == 5
        assert messages[0]["content"] == "Msg 5"  # Last 5

    @pytest.mark.asyncio
    async def test_messages_for_nonexistent_session(self, manager):
        messages = await manager.get_messages("nonexistent")
        assert messages == []

    @pytest.mark.asyncio
    async def test_session_metadata_updated_on_message(self, manager):
        session = await manager.create(title="New Chat")
        await manager.add_message(session.id, {"role": "user", "content": "My first message"})

        fetched = await manager.get(session.id)
        assert fetched.message_count == 1
        assert fetched.last_message_preview == "My first message"
        # Title auto-generated from first user message
        assert fetched.title == "My first message"

    @pytest.mark.asyncio
    async def test_clear_messages(self, manager):
        session = await manager.create(title="Clear Test")
        await manager.add_message(session.id, {"role": "user", "content": "Hello"})
        await manager.clear_messages(session.id)

        messages = await manager.get_messages(session.id)
        assert messages == []
        fetched = await manager.get(session.id)
        assert fetched.message_count == 0

    @pytest.mark.asyncio
    async def test_persistence_across_reload(self, tmp_path):
        sessions_dir = tmp_path / "sessions"

        # Create and populate
        mgr1 = ChatSessionManager(sessions_dir)
        session = await mgr1.create(title="Persist Test")
        await mgr1.add_message(session.id, {"role": "user", "content": "Saved"})

        # Reload from disk
        mgr2 = ChatSessionManager(sessions_dir)
        await mgr2.load()

        sessions = mgr2.list_sessions()
        assert len(sessions) == 1
        assert sessions[0].title == "Persist Test"

        messages = await mgr2.get_messages(session.id)
        assert len(messages) == 1
        assert messages[0]["content"] == "Saved"

    @pytest.mark.asyncio
    async def test_get_or_create_default(self, manager):
        session = await manager.get_or_create_default("chat")
        assert session.id == "default_chat"
        assert session.session_type == "chat"

        # Second call returns same session
        session2 = await manager.get_or_create_default("chat")
        assert session2.id == session.id

    @pytest.mark.asyncio
    async def test_update_session_fields(self, manager):
        session = await manager.create(title="Test", session_type="code")
        updated = await manager.update(
            session.id,
            deployment_target="remote",
            ssh_host="server.example.com",
            github_repo="user/repo",
        )
        assert updated is not None
        assert updated.deployment_target == "remote"
        assert updated.ssh_host == "server.example.com"
        assert updated.github_repo == "user/repo"

    @pytest.mark.asyncio
    async def test_jsonl_file_format(self, manager):
        session = await manager.create(title="JSONL Test")
        await manager.add_message(session.id, {"role": "user", "content": "Line 1"})
        await manager.add_message(session.id, {"role": "assistant", "content": "Line 2"})

        # Verify file is valid JSONL
        path = manager._messages_path(session.id)
        lines = path.read_text().strip().split("\n")
        assert len(lines) == 2
        for line in lines:
            msg = json.loads(line)
            assert "role" in msg
            assert "content" in msg


class TestAgentChatHistoryContext:
    """Tests for Agent._build_context() chat history integration."""

    @pytest.mark.asyncio
    async def test_build_context_includes_chat_history(self, tmp_path):
        """When chat_session_manager is provided and origin_metadata has a
        chat_session_id, _build_context() should include conversation history."""
        from core.task_queue import Task, TaskType

        sessions_dir = tmp_path / "sessions"
        manager = ChatSessionManager(sessions_dir)
        session = await manager.create(title="Context Test")

        # Add prior conversation messages
        await manager.add_message(session.id, {"role": "user", "content": "What is Python?"})
        await manager.add_message(
            session.id,
            {"role": "assistant", "content": "Python is a programming language."},
        )
        await manager.add_message(session.id, {"role": "user", "content": "Tell me more about it."})

        task = Task(
            title="Follow-up question",
            description="Tell me more about it.",
            task_type=TaskType.RESEARCH,
            origin_metadata={"chat_session_id": session.id},
        )

        # Create a minimal Agent with mocked dependencies
        with (
            patch("agents.agent.ModelRouter"),
            patch("agents.agent.IterationEngine"),
            patch("agents.agent.RLMProvider"),
        ):
            from agents.agent import Agent

            agent = Agent(
                task=task,
                task_queue=MagicMock(),
                worktree_manager=None,
                approval_gate=MagicMock(),
                emit=AsyncMock(),
                chat_session_manager=manager,
            )

            worktree = tmp_path / "worktree"
            worktree.mkdir()

            context = await agent._build_context(task, worktree)

            assert "Conversation History" in context
            assert "What is Python?" in context
            assert "Python is a programming language." in context
            # Current message ("Tell me more about it") should be excluded
            # from the history section (it's already the task description)

    @pytest.mark.asyncio
    async def test_build_context_no_session_manager(self, tmp_path):
        """When chat_session_manager is None, _build_context() should not
        include a conversation history section."""
        from core.task_queue import Task, TaskType

        task = Task(
            title="Solo question",
            description="What is the meaning of life?",
            task_type=TaskType.RESEARCH,
            origin_metadata={"chat_session_id": "some-session"},
        )

        with (
            patch("agents.agent.ModelRouter"),
            patch("agents.agent.IterationEngine"),
            patch("agents.agent.RLMProvider"),
        ):
            from agents.agent import Agent

            agent = Agent(
                task=task,
                task_queue=MagicMock(),
                worktree_manager=None,
                approval_gate=MagicMock(),
                emit=AsyncMock(),
                chat_session_manager=None,
            )

            worktree = tmp_path / "worktree"
            worktree.mkdir()

            context = await agent._build_context(task, worktree)

            assert "Conversation History" not in context

    @pytest.mark.asyncio
    async def test_build_context_no_session_id_in_metadata(self, tmp_path):
        """When origin_metadata has no chat_session_id, _build_context()
        should not include a conversation history section."""
        from core.task_queue import Task, TaskType

        sessions_dir = tmp_path / "sessions"
        manager = ChatSessionManager(sessions_dir)

        task = Task(
            title="No session ID",
            description="Random question",
            task_type=TaskType.RESEARCH,
            origin_metadata={"chat_msg_id": "msg123"},  # No session_id
        )

        with (
            patch("agents.agent.ModelRouter"),
            patch("agents.agent.IterationEngine"),
            patch("agents.agent.RLMProvider"),
        ):
            from agents.agent import Agent

            agent = Agent(
                task=task,
                task_queue=MagicMock(),
                worktree_manager=None,
                approval_gate=MagicMock(),
                emit=AsyncMock(),
                chat_session_manager=manager,
            )

            worktree = tmp_path / "worktree"
            worktree.mkdir()

            context = await agent._build_context(task, worktree)

            assert "Conversation History" not in context

    @pytest.mark.asyncio
    async def test_build_context_single_message_no_history(self, tmp_path):
        """When the session has only one message (the current one),
        no history section should be added."""
        from core.task_queue import Task, TaskType

        sessions_dir = tmp_path / "sessions"
        manager = ChatSessionManager(sessions_dir)
        session = await manager.create(title="Single Msg")

        # Only one message — the current one
        await manager.add_message(session.id, {"role": "user", "content": "First message ever"})

        task = Task(
            title="First question",
            description="First message ever",
            task_type=TaskType.RESEARCH,
            origin_metadata={"chat_session_id": session.id},
        )

        with (
            patch("agents.agent.ModelRouter"),
            patch("agents.agent.IterationEngine"),
            patch("agents.agent.RLMProvider"),
        ):
            from agents.agent import Agent

            agent = Agent(
                task=task,
                task_queue=MagicMock(),
                worktree_manager=None,
                approval_gate=MagicMock(),
                emit=AsyncMock(),
                chat_session_manager=manager,
            )

            worktree = tmp_path / "worktree"
            worktree.mkdir()

            context = await agent._build_context(task, worktree)

            # Only 1 message — no history section expected
            assert "Conversation History" not in context
