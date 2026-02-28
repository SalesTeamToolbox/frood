"""
Web search tool — Brave Search API with DuckDuckGo fallback.

Provides web search capabilities for research tasks.
Uses Brave Search API as primary (requires BRAVE_API_KEY), with automatic
fallback to DuckDuckGo HTML search when Brave is unavailable.
"""

import logging
import os
import re

import httpx

from tools.base import Tool, ToolResult

logger = logging.getLogger("agent42.tools.web_search")

BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
DDG_HTML_URL = "https://html.duckduckgo.com/html/"


class WebSearchTool(Tool):
    """Search the web using Brave Search API with DuckDuckGo fallback."""

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return "Search the web for information. Returns titles, URLs, and snippets."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "count": {
                    "type": "integer",
                    "description": "Number of results (1-10, default 5)",
                    "default": 5,
                },
            },
            "required": ["query"],
        }

    async def execute(self, query: str = "", count: int = 5, **kwargs) -> ToolResult:
        if not query:
            return ToolResult(error="No search query provided", success=False)

        count = max(1, min(10, count))

        # Try Brave Search first (if API key available)
        api_key = os.getenv("BRAVE_API_KEY", "")
        if api_key:
            result = await self._brave_search(query, count, api_key)
            if result.success:
                return result
            logger.warning(f"Brave Search failed, trying DuckDuckGo fallback: {result.error}")

        # Fallback: DuckDuckGo HTML (no API key required)
        return await self._duckduckgo_search(query, count)

    async def _brave_search(self, query: str, count: int, api_key: str) -> ToolResult:
        """Search using Brave Search API."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    BRAVE_SEARCH_URL,
                    headers={
                        "Accept": "application/json",
                        "X-Subscription-Token": api_key,
                    },
                    params={"q": query, "count": count},
                    timeout=15.0,
                )
                response.raise_for_status()

            data = response.json()
            results = data.get("web", {}).get("results", [])

            if not results:
                return ToolResult(output="No results found.")

            return ToolResult(output=self._format_results(results, count))

        except httpx.HTTPStatusError as e:
            return ToolResult(error=f"Search API error: {e.response.status_code}", success=False)
        except Exception as e:
            return ToolResult(error=f"Brave search failed: {e}", success=False)

    async def _duckduckgo_search(self, query: str, count: int) -> ToolResult:
        """Fallback search using DuckDuckGo HTML endpoint (no API key needed)."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    DDG_HTML_URL,
                    data={"q": query},
                    headers={"User-Agent": "Agent42/1.0"},
                    timeout=15.0,
                )
                response.raise_for_status()

            results = self._parse_ddg_html(response.text, count)

            if not results:
                return ToolResult(output="No results found.")

            return ToolResult(output=self._format_results(results, count))

        except Exception as e:
            return ToolResult(error=f"DuckDuckGo search failed: {e}", success=False)

    @staticmethod
    def _parse_ddg_html(html: str, max_results: int) -> list[dict]:
        """Parse DuckDuckGo HTML search results into structured data."""
        results = []

        # DDG HTML results are in <a class="result__a"> for title/URL
        # and <a class="result__snippet"> for descriptions
        link_pattern = re.compile(
            r'<a\s+[^>]*class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
            re.DOTALL,
        )
        snippet_pattern = re.compile(
            r'<a\s+[^>]*class="result__snippet"[^>]*>(.*?)</a>',
            re.DOTALL,
        )

        links = link_pattern.findall(html)
        snippets = snippet_pattern.findall(html)

        for i, (url, title) in enumerate(links[:max_results]):
            # Strip HTML tags from title
            title = re.sub(r"<[^>]+>", "", title).strip()
            snippet = ""
            if i < len(snippets):
                snippet = re.sub(r"<[^>]+>", "", snippets[i]).strip()
            if url and title and url.startswith("http"):
                results.append({"title": title, "url": url, "description": snippet})

        return results

    @staticmethod
    def _format_results(results: list[dict], count: int) -> str:
        """Format search results into readable output."""
        lines = []
        for i, r in enumerate(results[:count], 1):
            lines.append(f"{i}. **{r.get('title', '')}**")
            lines.append(f"   {r.get('url', '')}")
            desc = r.get("description", "")
            if desc:
                lines.append(f"   {desc}")
            lines.append("")
        return "\n".join(lines)


# URL policy: consolidated SSRF + allowlist/denylist from core module
from core.config import settings
from core.url_policy import _BLOCKED_IP_RANGES, UrlPolicy, _is_ssrf_target  # noqa: F401

# Shared URL policy instance for web tools
_url_policy = UrlPolicy(
    allowlist=settings.get_url_allowlist(),
    denylist=settings.get_url_denylist(),
    max_requests_per_agent=settings.max_url_requests_per_agent,
)


class WebFetchTool(Tool):
    """Fetch and extract content from a URL with SSRF protection."""

    @property
    def name(self) -> str:
        return "web_fetch"

    @property
    def description(self) -> str:
        return "Fetch content from a public URL. Returns the text content. Private/internal IPs are blocked."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to fetch (public URLs only)"},
            },
            "required": ["url"],
        }

    async def execute(self, url: str = "", **kwargs) -> ToolResult:
        if not url:
            return ToolResult(error="No URL provided", success=False)

        if not url.startswith(("http://", "https://")):
            return ToolResult(error="Only http/https URLs are supported", success=False)

        # URL policy check: SSRF + allowlist/denylist + per-agent limits
        allowed, reason = _url_policy.check(url, agent_id=kwargs.get("agent_id", "default"))
        if not allowed:
            logger.warning(f"URL blocked: {url} — {reason}")
            return ToolResult(error=reason, success=False)

        try:
            # Disable auto-redirects to validate each redirect destination for SSRF
            async with httpx.AsyncClient(follow_redirects=False) as client:
                response = await client.get(url, timeout=15.0)

                # Follow redirects manually with SSRF checks (max 5 hops)
                redirect_count = 0
                while response.is_redirect and redirect_count < 5:
                    redirect_count += 1
                    next_url = str(response.next_request.url) if response.next_request else None
                    if not next_url:
                        break
                    redirect_ssrf = _is_ssrf_target(next_url)
                    if redirect_ssrf:
                        logger.warning(f"SSRF blocked on redirect: {next_url} — {redirect_ssrf}")
                        return ToolResult(error=f"Redirect blocked: {redirect_ssrf}", success=False)
                    response = await client.get(next_url, timeout=15.0)

                response.raise_for_status()

            text = response.text

            # Truncate very large responses
            max_len = 50000
            if len(text) > max_len:
                text = text[:max_len] + "\n... (content truncated)"

            return ToolResult(output=text)

        except Exception as e:
            return ToolResult(error=f"Fetch failed: {e}", success=False)
