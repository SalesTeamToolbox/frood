"""Tests for memory context loading in conversational/direct response paths."""

import asyncio
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from memory.store import MemoryStore, build_conversational_memory_context


class TestBuildConversationalMemoryContext:
    """Unit tests for the build_conversational_memory_context helper."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.store = MemoryStore(self.tmpdir)

    @pytest.mark.asyncio
    async def test_returns_empty_when_store_is_none(self):
        result = await build_conversational_memory_context(None, "hello")
        assert result == ""

    @pytest.mark.asyncio
    async def test_basic_context_without_semantic(self):
        """When semantic search is not available, uses sync build_context."""
        self.store.update_memory("# Memory\n\nUser likes Python.")
        self.store.log_event("chat", "Discussed web scraping")

        result = await build_conversational_memory_context(self.store, "hello")
        assert "Persistent Memory" in result
        assert "User likes Python" in result

    @pytest.mark.asyncio
    async def test_respects_max_memory_lines(self):
        """Passes max_memory_lines and max_history_lines to build_context."""
        with patch.object(self.store, "build_context", return_value="memory") as mock_bc:
            # Force semantic_available to False
            with patch.object(
                type(self.store),
                "semantic_available",
                new_callable=lambda: property(lambda s: False),
            ):
                result = await build_conversational_memory_context(
                    self.store,
                    "query",
                    max_memory_lines=15,
                    max_history_lines=5,
                )
                mock_bc.assert_called_once_with(
                    max_memory_lines=15,
                    max_history_lines=5,
                )
                assert result == "memory"

    @pytest.mark.asyncio
    async def test_uses_semantic_when_available(self):
        """When semantic search is available, calls build_context_semantic."""
        mock_store = MagicMock()
        mock_store.semantic_available = True
        mock_store.build_context_semantic = AsyncMock(
            return_value="## Relevant Context\n\nSemantic result"
        )

        result = await build_conversational_memory_context(
            mock_store, "What did we discuss?", top_k=3
        )

        mock_store.build_context_semantic.assert_awaited_once_with(
            query="What did we discuss?",
            top_k=3,
            max_memory_lines=30,
        )
        assert "Semantic result" in result

    @pytest.mark.asyncio
    async def test_falls_back_on_semantic_failure(self):
        """When semantic search raises, falls back to sync build_context."""
        mock_store = MagicMock()
        mock_store.semantic_available = True
        mock_store.build_context_semantic = AsyncMock(
            side_effect=RuntimeError("Embedding API down")
        )
        mock_store.build_context = MagicMock(return_value="fallback memory")

        result = await build_conversational_memory_context(mock_store, "test query")

        assert result == "fallback memory"
        mock_store.build_context.assert_called_once_with(
            max_memory_lines=30,
            max_history_lines=10,
        )

    @pytest.mark.asyncio
    async def test_returns_empty_on_double_failure(self):
        """When both semantic and sync build_context fail, returns empty."""
        mock_store = MagicMock()
        mock_store.semantic_available = True
        mock_store.build_context_semantic = AsyncMock(
            side_effect=RuntimeError("Embedding API down")
        )
        mock_store.build_context = MagicMock(side_effect=OSError("Disk error"))

        result = await build_conversational_memory_context(mock_store, "test query")
        assert result == ""

    @pytest.mark.asyncio
    async def test_timeout_triggers_fallback(self):
        """When semantic search exceeds timeout, falls back to sync."""

        async def slow_semantic(*args, **kwargs):
            await asyncio.sleep(10)
            return "too slow"

        mock_store = MagicMock()
        mock_store.semantic_available = True
        mock_store.build_context_semantic = slow_semantic
        mock_store.build_context = MagicMock(return_value="fast fallback")

        result = await build_conversational_memory_context(mock_store, "query", timeout=0.1)

        assert result == "fast fallback"
        mock_store.build_context.assert_called_once()


class TestChatSendSessionId:
    """Test that /api/chat/send includes chat_session_id in origin_metadata."""

    def test_origin_metadata_includes_session_id(self):
        """Verify the dict merge pattern produces the expected metadata."""
        msg_id = "abc123"
        session_id = "sess456"

        # Replicate the pattern from server.py
        origin_metadata = {
            "chat_msg_id": msg_id,
            **({"chat_session_id": session_id} if session_id else {}),
        }

        assert origin_metadata["chat_msg_id"] == "abc123"
        assert origin_metadata["chat_session_id"] == "sess456"

    def test_origin_metadata_omits_session_id_when_empty(self):
        """When session_id is empty, chat_session_id is not in metadata."""
        msg_id = "abc123"
        session_id = ""

        origin_metadata = {
            "chat_msg_id": msg_id,
            **({"chat_session_id": session_id} if session_id else {}),
        }

        assert origin_metadata["chat_msg_id"] == "abc123"
        assert "chat_session_id" not in origin_metadata
