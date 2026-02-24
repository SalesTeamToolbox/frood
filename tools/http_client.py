"""
HTTP client tool — make API requests with structured results.

Supports GET, POST, PUT, PATCH, DELETE with headers, body, and auth.
Includes SSRF protection (blocks private/internal IPs).
"""

import asyncio
import json
import logging
import re
import time
from urllib.parse import urlparse

from tools.base import Tool, ToolResult

logger = logging.getLogger("agent42.tools.http_client")

# RFC 7230 valid header name characters
_VALID_HEADER_NAME_RE = re.compile(r"^[a-zA-Z0-9!#$%&'*+\-.^_`|~]+$")

# Headers that must not be user-controlled (hop-by-hop and security-sensitive)
_FORBIDDEN_HEADERS = frozenset(
    {
        "host",
        "connection",
        "content-length",
        "transfer-encoding",
        "upgrade",
        "te",
        "trailer",
        "proxy-authorization",
        "proxy-authenticate",
    }
)

# Reuse URL policy from core module (SSRF + allowlist/denylist)
try:
    from tools.web_search import _url_policy
except ImportError:
    _url_policy = None


class HttpClientTool(Tool):
    """Make HTTP API requests with structured response handling."""

    @property
    def name(self) -> str:
        return "http_request"

    @property
    def description(self) -> str:
        return (
            "Make HTTP requests (GET, POST, PUT, PATCH, DELETE) to APIs. "
            "Returns status code, headers, and body. Blocks requests to private IPs."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to request",
                },
                "method": {
                    "type": "string",
                    "enum": ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"],
                    "description": "HTTP method (default: GET)",
                    "default": "GET",
                },
                "headers": {
                    "type": "object",
                    "description": "Request headers as key-value pairs",
                    "default": {},
                },
                "body": {
                    "type": "string",
                    "description": "Request body (string or JSON)",
                    "default": "",
                },
                "json_body": {
                    "type": "object",
                    "description": "JSON request body (auto-sets Content-Type)",
                },
                "timeout": {
                    "type": "number",
                    "description": "Request timeout in seconds (default: 30)",
                    "default": 30,
                },
            },
            "required": ["url"],
        }

    @staticmethod
    def _validate_headers(headers: dict | None) -> tuple[bool, str, dict]:
        """Validate and sanitize request headers.

        Returns (ok, error_message, validated_headers).
        """
        if not headers:
            return True, "", {}

        validated = {}
        for name, value in headers.items():
            if not isinstance(name, str) or not _VALID_HEADER_NAME_RE.match(name):
                return False, f"Invalid header name: {name!r}", {}
            if name.lower() in _FORBIDDEN_HEADERS:
                return False, f"Forbidden header: {name}", {}
            if not isinstance(value, str):
                return False, f"Header value must be string: {name}", {}
            if "\r" in value or "\n" in value:
                return False, f"Header value contains newlines (CRLF injection): {name}", {}
            if len(value) > 8192:
                return False, f"Header value too long ({len(value)} bytes): {name}", {}
            validated[name] = value

        return True, "", validated

    async def execute(
        self,
        url: str = "",
        method: str = "GET",
        headers: dict | None = None,
        body: str = "",
        json_body: dict | None = None,
        timeout: float = 30,
        **kwargs,
    ) -> ToolResult:
        if not url:
            return ToolResult(error="URL is required", success=False)

        # Validate headers
        ok, err_msg, validated_headers = self._validate_headers(headers)
        if not ok:
            return ToolResult(error=f"Invalid headers: {err_msg}", success=False)

        # URL policy check (SSRF + allowlist/denylist + per-agent limits)
        if _url_policy:
            allowed, reason = _url_policy.check(url, agent_id=kwargs.get("agent_id", "default"))
            if not allowed:
                return ToolResult(error=f"Blocked: {reason}", success=False)

        # Validate URL
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return ToolResult(error=f"Unsupported scheme: {parsed.scheme}", success=False)

        try:
            import aiohttp  # noqa: F401
        except ImportError:
            # Fallback to urllib
            return await self._urllib_request(
                url, method, validated_headers, body, json_body, timeout
            )

        return await self._aiohttp_request(url, method, validated_headers, body, json_body, timeout)

    async def _aiohttp_request(
        self,
        url: str,
        method: str,
        headers: dict,
        body: str,
        json_body: dict | None,
        timeout: float,
    ) -> ToolResult:
        """Make request using aiohttp."""
        import aiohttp

        req_kwargs: dict = {
            "headers": headers,
            "timeout": aiohttp.ClientTimeout(total=timeout),
        }

        if json_body is not None:
            req_kwargs["json"] = json_body
        elif body:
            req_kwargs["data"] = body

        start = time.monotonic()
        try:
            async with aiohttp.ClientSession() as session:
                async with session.request(method, url, **req_kwargs) as resp:
                    elapsed = time.monotonic() - start
                    resp_body = await resp.text()

                    # Truncate large responses
                    if len(resp_body) > 50000:
                        resp_body = resp_body[:50000] + "\n... (response truncated)"

                    # Try to format JSON
                    content_type = resp.headers.get("Content-Type", "")
                    if "json" in content_type:
                        try:
                            parsed = json.loads(resp_body)
                            resp_body = json.dumps(parsed, indent=2)
                        except json.JSONDecodeError:
                            pass

                    output = self._format_response(
                        status=resp.status,
                        reason=resp.reason,
                        headers=dict(resp.headers),
                        body=resp_body,
                        elapsed=elapsed,
                        method=method,
                        url=url,
                    )

                    return ToolResult(
                        output=output,
                        success=200 <= resp.status < 400,
                    )
        except TimeoutError:
            return ToolResult(error=f"Request timed out after {timeout}s", success=False)
        except Exception as e:
            return ToolResult(error=f"Request failed: {e}", success=False)

    async def _urllib_request(
        self,
        url: str,
        method: str,
        headers: dict | None,
        body: str,
        json_body: dict | None,
        timeout: float,
    ) -> ToolResult:
        """Fallback using urllib (no aiohttp dependency)."""
        import urllib.error
        import urllib.request

        headers = headers or {}

        data = None
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            headers.setdefault("Content-Type", "application/json")
        elif body:
            data = body.encode("utf-8")

        req = urllib.request.Request(url, data=data, headers=headers, method=method)

        start = time.monotonic()
        try:
            loop = asyncio.get_running_loop()
            resp = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: urllib.request.urlopen(req, timeout=timeout),  # nosec B310
                ),
                timeout=timeout + 5,
            )
            elapsed = time.monotonic() - start

            resp_body = resp.read().decode("utf-8", errors="replace")
            if len(resp_body) > 50000:
                resp_body = resp_body[:50000] + "\n... (response truncated)"

            content_type = resp.headers.get("Content-Type", "")
            if "json" in content_type:
                try:
                    parsed = json.loads(resp_body)
                    resp_body = json.dumps(parsed, indent=2)
                except json.JSONDecodeError:
                    pass

            output = self._format_response(
                status=resp.status,
                reason=resp.reason,
                headers=dict(resp.headers),
                body=resp_body,
                elapsed=elapsed,
                method=method,
                url=url,
            )

            return ToolResult(output=output, success=200 <= resp.status < 400)

        except urllib.error.HTTPError as e:
            elapsed = time.monotonic() - start
            resp_body = e.read().decode("utf-8", errors="replace")
            if len(resp_body) > 50000:
                resp_body = resp_body[:50000] + "\n... (response truncated)"

            output = self._format_response(
                status=e.code,
                reason=e.reason,
                headers=dict(e.headers),
                body=resp_body,
                elapsed=elapsed,
                method=method,
                url=url,
            )
            return ToolResult(output=output, success=False)

        except TimeoutError:
            return ToolResult(error=f"Request timed out after {timeout}s", success=False)
        except Exception as e:
            return ToolResult(error=f"Request failed: {e}", success=False)

    @staticmethod
    def _format_response(
        status: int,
        reason: str,
        headers: dict,
        body: str,
        elapsed: float,
        method: str,
        url: str,
    ) -> str:
        """Format the HTTP response into readable output."""
        lines = [
            f"## {method} {url}",
            f"**Status:** {status} {reason}  ({elapsed:.2f}s)",
            "",
            "### Response Headers",
        ]

        # Show key headers only
        important_headers = [
            "Content-Type",
            "Content-Length",
            "X-RateLimit-Remaining",
            "X-RateLimit-Limit",
            "Location",
            "Set-Cookie",
            "Authorization",
        ]
        for key in important_headers:
            if key in headers:
                lines.append(f"  {key}: {headers[key]}")

        lines.extend(["", "### Response Body", "```", body, "```"])

        return "\n".join(lines)
