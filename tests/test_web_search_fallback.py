"""Tests for WebSearchTool — Brave Search + DuckDuckGo fallback."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tools.web_search import WebSearchTool

# ---------------------------------------------------------------------------
# Sample HTML for DuckDuckGo parsing tests
# ---------------------------------------------------------------------------

SAMPLE_DDG_HTML = """
<div class="result results_links results_links_deep web-result ">
  <div class="links_main links_deep result__body">
    <h2 class="result__title">
      <a rel="nofollow" class="result__a" href="https://example.com/page1">
        Example Page One
      </a>
    </h2>
    <a class="result__snippet" href="https://example.com/page1">
      This is a snippet for the first result.
    </a>
  </div>
</div>
<div class="result results_links results_links_deep web-result ">
  <div class="links_main links_deep result__body">
    <h2 class="result__title">
      <a rel="nofollow" class="result__a" href="https://example.com/page2">
        <b>Example</b> Page Two
      </a>
    </h2>
    <a class="result__snippet" href="https://example.com/page2">
      This is a snippet for the <b>second</b> result.
    </a>
  </div>
</div>
"""


# ---------------------------------------------------------------------------
# HTML parsing tests (unit, no network)
# ---------------------------------------------------------------------------


class TestDuckDuckGoHTMLParsing:
    """Test the static HTML parser for DuckDuckGo results."""

    def test_parse_extracts_results(self):
        results = WebSearchTool._parse_ddg_html(SAMPLE_DDG_HTML, 10)
        assert len(results) == 2

    def test_parse_extracts_urls(self):
        results = WebSearchTool._parse_ddg_html(SAMPLE_DDG_HTML, 10)
        assert results[0]["url"] == "https://example.com/page1"
        assert results[1]["url"] == "https://example.com/page2"

    def test_parse_strips_html_from_titles(self):
        results = WebSearchTool._parse_ddg_html(SAMPLE_DDG_HTML, 10)
        assert results[0]["title"] == "Example Page One"
        # Second title has <b> tags that should be stripped
        assert "<b>" not in results[1]["title"]
        assert "Example" in results[1]["title"]

    def test_parse_strips_html_from_snippets(self):
        results = WebSearchTool._parse_ddg_html(SAMPLE_DDG_HTML, 10)
        assert "<b>" not in results[1]["description"]
        assert "second" in results[1]["description"]

    def test_parse_respects_max_results(self):
        results = WebSearchTool._parse_ddg_html(SAMPLE_DDG_HTML, 1)
        assert len(results) == 1

    def test_parse_empty_html(self):
        results = WebSearchTool._parse_ddg_html("", 5)
        assert results == []

    def test_parse_no_results_html(self):
        results = WebSearchTool._parse_ddg_html("<html><body>No results</body></html>", 5)
        assert results == []

    def test_parse_ignores_non_http_urls(self):
        html = '<a class="result__a" href="javascript:void(0)">Bad Link</a>'
        results = WebSearchTool._parse_ddg_html(html, 5)
        assert len(results) == 0


# ---------------------------------------------------------------------------
# Execute flow tests (mocked network)
# ---------------------------------------------------------------------------


class TestWebSearchExecute:
    """Test the execute method's Brave → DuckDuckGo fallback logic."""

    def setup_method(self):
        self.tool = WebSearchTool()

    @pytest.mark.asyncio
    async def test_empty_query_returns_error(self):
        result = await self.tool.execute(query="")
        assert not result.success
        assert "query" in result.error.lower()

    @pytest.mark.asyncio
    async def test_brave_success_skips_ddg(self):
        """When Brave works, DuckDuckGo is not called."""
        brave_result = MagicMock()
        brave_result.success = True
        brave_result.output = "Brave results"

        with patch.dict("os.environ", {"BRAVE_API_KEY": "test-key"}):
            with patch.object(
                self.tool, "_brave_search", new_callable=AsyncMock, return_value=brave_result
            ) as mock_brave:
                with patch.object(
                    self.tool, "_duckduckgo_search", new_callable=AsyncMock
                ) as mock_ddg:
                    result = await self.tool.execute(query="test query")
                    mock_brave.assert_called_once()
                    mock_ddg.assert_not_called()
                    assert result.success

    @pytest.mark.asyncio
    async def test_missing_key_falls_to_ddg(self):
        """When BRAVE_API_KEY is not set, fall through to DuckDuckGo."""
        ddg_result = MagicMock()
        ddg_result.success = True
        ddg_result.output = "DDG results"

        with patch.dict("os.environ", {}, clear=True):
            with patch.object(
                self.tool, "_duckduckgo_search", new_callable=AsyncMock, return_value=ddg_result
            ) as mock_ddg:
                result = await self.tool.execute(query="test query")
                mock_ddg.assert_called_once_with("test query", 5)
                assert result.success

    @pytest.mark.asyncio
    async def test_brave_error_falls_to_ddg(self):
        """When Brave fails, fall through to DuckDuckGo."""
        from tools.base import ToolResult

        brave_fail = ToolResult(error="Search API error: 422", success=False)
        ddg_result = ToolResult(output="DDG results", success=True)

        with patch.dict("os.environ", {"BRAVE_API_KEY": "test-key"}):
            with patch.object(
                self.tool, "_brave_search", new_callable=AsyncMock, return_value=brave_fail
            ):
                with patch.object(
                    self.tool, "_duckduckgo_search", new_callable=AsyncMock, return_value=ddg_result
                ) as mock_ddg:
                    result = await self.tool.execute(query="test query")
                    mock_ddg.assert_called_once()
                    assert result.success
                    assert "DDG results" in result.output

    @pytest.mark.asyncio
    async def test_both_fail_returns_error(self):
        """When both Brave and DuckDuckGo fail, return error."""
        from tools.base import ToolResult

        brave_fail = ToolResult(error="Brave failed", success=False)
        ddg_fail = ToolResult(error="DDG failed", success=False)

        with patch.dict("os.environ", {"BRAVE_API_KEY": "test-key"}):
            with patch.object(
                self.tool, "_brave_search", new_callable=AsyncMock, return_value=brave_fail
            ):
                with patch.object(
                    self.tool, "_duckduckgo_search", new_callable=AsyncMock, return_value=ddg_fail
                ):
                    result = await self.tool.execute(query="test query")
                    assert not result.success

    @pytest.mark.asyncio
    async def test_count_clamped(self):
        """Count should be clamped to 1-10 range."""
        from tools.base import ToolResult

        ddg_result = ToolResult(output="results", success=True)

        with patch.dict("os.environ", {}, clear=True):
            with patch.object(
                self.tool, "_duckduckgo_search", new_callable=AsyncMock, return_value=ddg_result
            ) as mock_ddg:
                await self.tool.execute(query="test", count=50)
                mock_ddg.assert_called_once_with("test", 10)

                mock_ddg.reset_mock()
                await self.tool.execute(query="test", count=-5)
                mock_ddg.assert_called_once_with("test", 1)


# ---------------------------------------------------------------------------
# Format results test
# ---------------------------------------------------------------------------


class TestFormatResults:
    """Test the shared result formatting method."""

    def test_format_with_descriptions(self):
        results = [
            {"title": "Page 1", "url": "https://example.com/1", "description": "Desc 1"},
            {"title": "Page 2", "url": "https://example.com/2", "description": "Desc 2"},
        ]
        output = WebSearchTool._format_results(results, 5)
        assert "1. **Page 1**" in output
        assert "https://example.com/1" in output
        assert "Desc 1" in output
        assert "2. **Page 2**" in output

    def test_format_without_descriptions(self):
        results = [{"title": "Page 1", "url": "https://example.com/1", "description": ""}]
        output = WebSearchTool._format_results(results, 5)
        assert "1. **Page 1**" in output
        assert "https://example.com/1" in output

    def test_format_respects_count(self):
        results = [
            {"title": f"Page {i}", "url": f"https://example.com/{i}", "description": ""}
            for i in range(10)
        ]
        output = WebSearchTool._format_results(results, 3)
        assert "3. **Page 2**" in output
        assert "4." not in output
