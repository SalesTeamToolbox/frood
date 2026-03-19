"""Tests for the MemoryTool — explicit read/write access to persistent memory."""

import tempfile

import pytest

from memory.store import MemoryStore
from tools.memory_tool import MemoryTool


class TestMemoryToolStore:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.store = MemoryStore(self.tmpdir)
        self.tool = MemoryTool(memory_store=self.store)

    @pytest.mark.asyncio
    async def test_store_appends_to_section(self):
        result = await self.tool.execute(
            action="store",
            section="User Preferences",
            content="User's favorite poem is 'The Road Not Taken'",
        )
        assert result.success
        assert "Stored in memory" in result.output
        memory = self.store.read_memory()
        assert "The Road Not Taken" in memory
        assert "User Preferences" in memory

    @pytest.mark.asyncio
    async def test_store_creates_new_section(self):
        result = await self.tool.execute(
            action="store",
            section="Poems",
            content="Roses are red, violets are blue",
        )
        assert result.success
        memory = self.store.read_memory()
        assert "## Poems" in memory
        assert "Roses are red" in memory

    @pytest.mark.asyncio
    async def test_store_defaults_to_general_section(self):
        result = await self.tool.execute(
            action="store",
            content="Important fact",
        )
        assert result.success
        memory = self.store.read_memory()
        assert "## General" in memory
        assert "Important fact" in memory

    @pytest.mark.asyncio
    async def test_store_requires_content(self):
        result = await self.tool.execute(action="store", section="Test")
        assert not result.success
        assert "No content" in result.output

    @pytest.mark.asyncio
    async def test_store_empty_content_fails(self):
        result = await self.tool.execute(action="store", content="   ")
        assert not result.success


class TestMemoryToolRecall:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.store = MemoryStore(self.tmpdir)
        self.tool = MemoryTool(memory_store=self.store)

    @pytest.mark.asyncio
    async def test_recall_returns_memory(self):
        self.store.append_to_section("Facts", "The sky is blue")
        result = await self.tool.execute(action="recall")
        assert result.success
        assert "The sky is blue" in result.output

    @pytest.mark.asyncio
    async def test_recall_empty_memory(self):
        result = await self.tool.execute(action="recall")
        assert result.success
        # Should still return the default template
        assert "Agent42 Memory" in result.output


class TestMemoryToolLog:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.store = MemoryStore(self.tmpdir)
        self.tool = MemoryTool(memory_store=self.store)

    @pytest.mark.asyncio
    async def test_log_event(self):
        result = await self.tool.execute(
            action="log",
            event_type="user_request",
            content="User asked to remember a poem",
        )
        assert result.success
        assert "Event logged" in result.output
        history = self.store.read_history()
        assert "user_request" in history
        assert "remember a poem" in history

    @pytest.mark.asyncio
    async def test_log_requires_content(self):
        result = await self.tool.execute(action="log", event_type="test")
        assert not result.success

    @pytest.mark.asyncio
    async def test_log_default_event_type(self):
        result = await self.tool.execute(
            action="log",
            content="Something happened",
        )
        assert result.success
        history = self.store.read_history()
        assert "note" in history


class TestMemoryToolSearch:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.store = MemoryStore(self.tmpdir)
        self.tool = MemoryTool(memory_store=self.store)

    @pytest.mark.asyncio
    async def test_search_memory(self):
        self.store.append_to_section("Facts", "Python was created by Guido")
        result = await self.tool.execute(action="search", content="Python")
        assert result.success
        assert "Python" in result.output
        # May show as [memory] (semantic) or [keyword] (no Qdrant)
        assert "[memory" in result.output or "[keyword]" in result.output

    @pytest.mark.asyncio
    async def test_search_history(self):
        self.store.log_event("deploy", "Deployed version 3.0")
        result = await self.tool.execute(action="search", content="deploy")
        assert result.success
        assert "[history]" in result.output

    @pytest.mark.asyncio
    async def test_search_no_results(self):
        result = await self.tool.execute(action="search", content="nonexistent")
        assert result.success
        assert "No results" in result.output

    @pytest.mark.asyncio
    async def test_search_requires_query(self):
        result = await self.tool.execute(action="search")
        assert not result.success


class TestMemoryToolNoStore:
    @pytest.mark.asyncio
    async def test_no_store_returns_error(self):
        tool = MemoryTool(memory_store=None)
        result = await tool.execute(action="recall")
        assert not result.success
        assert "not initialized" in result.output


class TestMemoryToolUnknownAction:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.store = MemoryStore(self.tmpdir)
        self.tool = MemoryTool(memory_store=self.store)

    @pytest.mark.asyncio
    async def test_unknown_action(self):
        result = await self.tool.execute(action="delete")
        assert not result.success
        assert "Unknown action" in result.output


class TestMemoryToolSchema:
    def setup_method(self):
        self.tool = MemoryTool(memory_store=None)

    def test_name(self):
        assert self.tool.name == "memory"

    def test_schema_format(self):
        schema = self.tool.to_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "memory"
        props = schema["function"]["parameters"]["properties"]
        assert "action" in props
        assert "section" in props
        assert "content" in props
        assert "event_type" in props


class TestMemoryToolConsolidate:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.store = MemoryStore(self.tmpdir)
        self.tool = MemoryTool(memory_store=self.store)

    @pytest.mark.asyncio
    async def test_consolidate_no_qdrant(self):
        """Consolidate fails gracefully when Qdrant unavailable."""
        result = await self.tool.execute(action="consolidate")
        assert not result.success
        assert "Qdrant" in result.output

    @pytest.mark.asyncio
    async def test_consolidate_action_in_schema(self):
        """The consolidate action is listed in the tool schema."""
        schema = self.tool.parameters
        actions = schema["properties"]["action"]["enum"]
        assert "consolidate" in actions


class TestMemoryToolSearchScoring:
    """Tests for QUAL-02: search results include confidence scores and recall counts."""

    def setup_method(self):
        from unittest.mock import AsyncMock, patch  # noqa: F401

        self.tmpdir = tempfile.mkdtemp()
        self.store = MemoryStore(self.tmpdir)
        self.tool = MemoryTool(memory_store=self.store)

    @pytest.mark.asyncio
    async def test_search_shows_relevance_label(self):
        """Search output uses 'relevance=' for lifecycle-adjusted results."""
        from unittest.mock import AsyncMock, patch

        mock_hits = [
            {
                "text": "User prefers dark mode",
                "source": "memory",
                "score": 0.85,
                "confidence": 0.7,
                "recall_count": 3,
            }
        ]
        with patch.object(self.store, "semantic_available", True):
            with patch.object(
                self.store, "semantic_search", new_callable=AsyncMock, return_value=mock_hits
            ):
                result = await self.tool.execute(action="search", content="dark mode")
        assert "relevance=0.85" in result.output

    @pytest.mark.asyncio
    async def test_search_shows_confidence_when_present(self):
        """Confidence is shown even at default value (0.5)."""
        from unittest.mock import AsyncMock, patch

        mock_hits = [
            {
                "text": "Some memory",
                "source": "memory",
                "score": 0.75,
                "confidence": 0.5,
                "recall_count": 0,
            }
        ]
        with patch.object(self.store, "semantic_available", True):
            with patch.object(
                self.store, "semantic_search", new_callable=AsyncMock, return_value=mock_hits
            ):
                result = await self.tool.execute(action="search", content="test")
        assert "conf=0.50" in result.output

    @pytest.mark.asyncio
    async def test_search_shows_recall_count_zero(self):
        """recall_count=0 is shown (not hidden because it's falsy)."""
        from unittest.mock import AsyncMock, patch

        mock_hits = [
            {
                "text": "New memory entry",
                "source": "memory",
                "score": 0.90,
                "confidence": 0.5,
                "recall_count": 0,
            }
        ]
        with patch.object(self.store, "semantic_available", True):
            with patch.object(
                self.store, "semantic_search", new_callable=AsyncMock, return_value=mock_hits
            ):
                result = await self.tool.execute(action="search", content="new")
        assert "recalls=0" in result.output

    @pytest.mark.asyncio
    async def test_search_hides_lifecycle_for_keyword(self):
        """Keyword-only results don't show conf/recalls."""
        self.store.append_to_section("Facts", "Python is great")
        result = await self.tool.execute(action="search", content="Python")
        assert result.success
        # Keyword results have [keyword] prefix, no conf/recalls
        for line in result.output.splitlines():
            if "[keyword]" in line:
                assert "conf=" not in line
                assert "recalls=" not in line
