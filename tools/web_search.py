"""
Web search tool — Brave Search API integration.

Provides web search capabilities for research tasks.
Requires a BRAVE_API_KEY environment variable.
"""

import logging
import os

import httpx

from tools.base import Tool, ToolResult

logger = logging.getLogger("agent42.tools.web_search")

BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"


class WebSearchTool(Tool):
    """Search the web using Brave Search API."""

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
        api_key = os.getenv("BRAVE_API_KEY", "")
        if not api_key:
            return ToolResult(error="BRAVE_API_KEY not configured", success=False)

        if not query:
            return ToolResult(error="No search query provided", success=False)

        count = max(1, min(10, count))

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

            lines = []
            for i, r in enumerate(results[:count], 1):
                lines.append(f"{i}. **{r.get('title', '')}**")
                lines.append(f"   {r.get('url', '')}")
                desc = r.get("description", "")
                if desc:
                    lines.append(f"   {desc}")
                lines.append("")

            return ToolResult(output="\n".join(lines))

        except httpx.HTTPStatusError as e:
            return ToolResult(error=f"Search API error: {e.response.status_code}", success=False)
        except Exception as e:
            return ToolResult(error=f"Search failed: {e}", success=False)


# URL policy: consolidated SSRF + allowlist/denylist from core module
from core.url_policy import UrlPolicy, _is_ssrf_target, _BLOCKED_IP_RANGES  # noqa: F401
from core.config import settings

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
