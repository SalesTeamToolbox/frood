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


import ipaddress
import socket
from urllib.parse import urlparse

# SSRF protection: blocked IP ranges
_BLOCKED_IP_RANGES = [
    ipaddress.ip_network("127.0.0.0/8"),       # Loopback
    ipaddress.ip_network("10.0.0.0/8"),         # Private
    ipaddress.ip_network("172.16.0.0/12"),      # Private
    ipaddress.ip_network("192.168.0.0/16"),     # Private
    ipaddress.ip_network("169.254.0.0/16"),     # Link-local / cloud metadata
    ipaddress.ip_network("0.0.0.0/8"),          # Current network
    ipaddress.ip_network("::1/128"),            # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),           # IPv6 private
    ipaddress.ip_network("fe80::/10"),          # IPv6 link-local
    ipaddress.ip_network("::ffff:127.0.0.0/104"),  # IPv4-mapped loopback
    ipaddress.ip_network("::ffff:10.0.0.0/104"),   # IPv4-mapped private
    ipaddress.ip_network("::ffff:172.16.0.0/108"), # IPv4-mapped private
    ipaddress.ip_network("::ffff:192.168.0.0/112"), # IPv4-mapped private
]

# Hostnames that resolve to localhost regardless of DNS
_BLOCKED_HOSTNAMES = {"localhost", "localhost.localdomain", "local"}


def _is_ssrf_target(url: str) -> str | None:
    """Check if a URL targets an internal/private IP. Returns error message or None."""
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
        if not hostname:
            return "Invalid URL: no hostname"

        # Block known localhost hostnames
        if hostname.lower() in _BLOCKED_HOSTNAMES:
            return f"Blocked: {hostname} is a localhost alias"

        # Resolve hostname to IP
        try:
            addr_infos = socket.getaddrinfo(hostname, parsed.port or 80)
        except socket.gaierror:
            return None  # DNS resolution failed — let httpx handle it

        for family, _, _, _, sockaddr in addr_infos:
            ip = ipaddress.ip_address(sockaddr[0])
            for blocked in _BLOCKED_IP_RANGES:
                if ip in blocked:
                    return f"Blocked: {hostname} resolves to private/internal IP {ip}"
        return None
    except Exception:
        return None  # Don't block on validation errors


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

        # SSRF protection: block requests to internal networks
        ssrf_error = _is_ssrf_target(url)
        if ssrf_error:
            logger.warning(f"SSRF blocked: {url} — {ssrf_error}")
            return ToolResult(error=ssrf_error, success=False)

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
