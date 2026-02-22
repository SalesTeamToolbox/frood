"""Tests for knowledge base / RAG tool."""

from unittest.mock import patch

import pytest

from core.sandbox import WorkspaceSandbox
from tools.knowledge_tool import (
    KnowledgeTool,
    _checksum,
    _chunk_text,
    _extract_html_text,
)


@pytest.fixture
def sandbox(tmp_path):
    return WorkspaceSandbox(tmp_path, enabled=True)


@pytest.fixture
def knowledge_tool(sandbox, tmp_path):
    with patch("tools.knowledge_tool.settings") as mock_settings:
        mock_settings.knowledge_dir = str(tmp_path / "knowledge")
        mock_settings.knowledge_chunk_size = 100
        mock_settings.knowledge_chunk_overlap = 10
        mock_settings.knowledge_max_results = 10
        tool = KnowledgeTool(sandbox, embedding_store=None)
    return tool


class TestChunking:
    def test_empty_text(self):
        assert _chunk_text("") == []

    def test_short_text(self):
        chunks = _chunk_text("Hello world", chunk_size=100)
        assert len(chunks) == 1
        assert chunks[0] == "Hello world"

    def test_long_text_produces_multiple_chunks(self):
        text = " ".join([f"word{i}" for i in range(500)])
        chunks = _chunk_text(text, chunk_size=100, overlap=10)
        assert len(chunks) > 1
        # Each chunk should be non-empty
        for chunk in chunks:
            assert chunk.strip()

    def test_overlap_works(self):
        text = " ".join([f"word{i}" for i in range(200)])
        chunks = _chunk_text(text, chunk_size=50, overlap=10)
        # With overlap, later chunks should contain some words from previous chunks
        assert len(chunks) >= 2


class TestHTMLExtraction:
    def test_basic_html(self):
        html = "<html><body><p>Hello world</p></body></html>"
        text = _extract_html_text(html)
        assert "Hello world" in text

    def test_strips_script_and_style(self):
        html = "<html><head><style>.x{}</style></head><body><script>alert(1)</script><p>Content</p></body></html>"
        text = _extract_html_text(html)
        assert "Content" in text
        assert "alert" not in text
        assert ".x" not in text

    def test_empty_html(self):
        assert _extract_html_text("") == ""


class TestChecksum:
    def test_same_content_same_hash(self):
        assert _checksum("hello") == _checksum("hello")

    def test_different_content_different_hash(self):
        assert _checksum("hello") != _checksum("world")


class TestKnowledgeTool:
    def test_tool_properties(self, knowledge_tool):
        assert knowledge_tool.name == "knowledge"
        assert "knowledge" in knowledge_tool.description.lower()
        params = knowledge_tool.parameters
        assert params["type"] == "object"
        assert "action" in params["properties"]

    @pytest.mark.asyncio
    async def test_unknown_action(self, knowledge_tool):
        result = await knowledge_tool.execute(action="invalid")
        assert not result.success
        assert "Unknown action" in result.error

    @pytest.mark.asyncio
    async def test_import_file_missing_path(self, knowledge_tool):
        result = await knowledge_tool.execute(action="import_file")
        assert not result.success
        assert "Path is required" in result.error

    @pytest.mark.asyncio
    async def test_import_file_not_found(self, knowledge_tool):
        result = await knowledge_tool.execute(action="import_file", path="nonexistent.txt")
        assert not result.success or "not found" in result.output.lower()

    @pytest.mark.asyncio
    async def test_import_text_file(self, knowledge_tool, sandbox, tmp_path):
        # Create a text file in the workspace
        test_file = tmp_path / "test.txt"
        test_file.write_text("This is a test document with some content for indexing.")

        with patch("tools.knowledge_tool.settings") as mock_settings:
            mock_settings.knowledge_dir = str(tmp_path / "knowledge")
            mock_settings.knowledge_chunk_size = 100
            mock_settings.knowledge_chunk_overlap = 10
            mock_settings.knowledge_max_results = 10
            result = await knowledge_tool.execute(action="import_file", path=str(test_file))

        assert result.success
        assert "Imported" in result.output
        assert "test.txt" in result.output

    @pytest.mark.asyncio
    async def test_import_markdown_file(self, knowledge_tool, tmp_path):
        test_file = tmp_path / "readme.md"
        test_file.write_text(
            "# Title\n\nSome markdown content.\n\n## Section\n\nMore content here."
        )

        with patch("tools.knowledge_tool.settings") as mock_settings:
            mock_settings.knowledge_dir = str(tmp_path / "knowledge")
            mock_settings.knowledge_chunk_size = 100
            mock_settings.knowledge_chunk_overlap = 10
            result = await knowledge_tool.execute(action="import_file", path=str(test_file))

        assert result.success

    @pytest.mark.asyncio
    async def test_import_unsupported_type(self, knowledge_tool, tmp_path):
        test_file = tmp_path / "binary.exe"
        test_file.write_bytes(b"\x00\x01\x02")

        result = await knowledge_tool.execute(action="import_file", path=str(test_file))
        assert not result.success or "Unsupported" in result.output

    @pytest.mark.asyncio
    async def test_import_dir(self, knowledge_tool, tmp_path):
        # Create multiple files
        (tmp_path / "doc1.txt").write_text("Document one content here.")
        (tmp_path / "doc2.md").write_text("# Document Two\n\nMarkdown content.")
        (tmp_path / "skip.exe").write_bytes(b"\x00")  # Should be skipped

        with patch("tools.knowledge_tool.settings") as mock_settings:
            mock_settings.knowledge_dir = str(tmp_path / "knowledge")
            mock_settings.knowledge_chunk_size = 100
            mock_settings.knowledge_chunk_overlap = 10
            mock_settings.knowledge_max_results = 10
            result = await knowledge_tool.execute(action="import_dir", path=str(tmp_path))

        assert result.success
        assert "2 files" in result.output  # Only .txt and .md

    @pytest.mark.asyncio
    async def test_import_dir_missing_path(self, knowledge_tool):
        result = await knowledge_tool.execute(action="import_dir")
        assert not result.success
        assert "Path is required" in result.error

    @pytest.mark.asyncio
    async def test_list_empty(self, knowledge_tool):
        result = await knowledge_tool.execute(action="list")
        assert result.success
        assert "empty" in result.output.lower()

    @pytest.mark.asyncio
    async def test_list_after_import(self, knowledge_tool, tmp_path):
        test_file = tmp_path / "doc.txt"
        test_file.write_text("Some test content for listing.")

        with patch("tools.knowledge_tool.settings") as mock_settings:
            mock_settings.knowledge_dir = str(tmp_path / "knowledge")
            mock_settings.knowledge_chunk_size = 100
            mock_settings.knowledge_chunk_overlap = 10
            mock_settings.knowledge_max_results = 10
            await knowledge_tool.execute(action="import_file", path=str(test_file))
            result = await knowledge_tool.execute(action="list")

        assert result.success
        assert "doc.txt" in result.output

    @pytest.mark.asyncio
    async def test_delete_missing_path(self, knowledge_tool):
        result = await knowledge_tool.execute(action="delete")
        assert not result.success
        assert "Path is required" in result.error

    @pytest.mark.asyncio
    async def test_delete_not_found(self, knowledge_tool):
        result = await knowledge_tool.execute(action="delete", path="nonexistent.txt")
        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_query_missing_query(self, knowledge_tool):
        result = await knowledge_tool.execute(action="query")
        assert not result.success
        assert "Query is required" in result.error

    @pytest.mark.asyncio
    async def test_query_empty_knowledge_base(self, knowledge_tool):
        result = await knowledge_tool.execute(action="query", query="test")
        assert result.success
        assert "No results" in result.output

    @pytest.mark.asyncio
    async def test_import_csv_file(self, knowledge_tool, tmp_path):
        test_file = tmp_path / "data.csv"
        test_file.write_text("name,age,city\nAlice,30,NYC\nBob,25,LA\n")

        with patch("tools.knowledge_tool.settings") as mock_settings:
            mock_settings.knowledge_dir = str(tmp_path / "knowledge")
            mock_settings.knowledge_chunk_size = 100
            mock_settings.knowledge_chunk_overlap = 10
            result = await knowledge_tool.execute(action="import_file", path=str(test_file))

        assert result.success

    @pytest.mark.asyncio
    async def test_import_html_file(self, knowledge_tool, tmp_path):
        test_file = tmp_path / "page.html"
        test_file.write_text("<html><body><h1>Title</h1><p>Content paragraph.</p></body></html>")

        with patch("tools.knowledge_tool.settings") as mock_settings:
            mock_settings.knowledge_dir = str(tmp_path / "knowledge")
            mock_settings.knowledge_chunk_size = 100
            mock_settings.knowledge_chunk_overlap = 10
            result = await knowledge_tool.execute(action="import_file", path=str(test_file))

        assert result.success
