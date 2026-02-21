"""
Browser automation tool — interact with web pages via Playwright.

Inspired by OpenClaw's `browser` tool and OpenHands' BrowserInteractiveAction.
Supports navigation, clicking, form filling, screenshot capture, and content extraction.
Requires: pip install playwright && playwright install chromium
"""

import asyncio
import base64
import logging
import os
import re

from tools.base import Tool, ToolResult

logger = logging.getLogger("agent42.tools.browser")


class BrowserTool(Tool):
    """Automate web browser interactions via Playwright."""

    def __init__(self, workspace_path: str = "."):
        self._workspace = workspace_path
        self._browser = None
        self._page = None

    @property
    def name(self) -> str:
        return "browser"

    @property
    def description(self) -> str:
        return (
            "Automate web browser interactions: navigate to URLs, click elements, "
            "fill forms, extract text, take screenshots. Requires Playwright."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "navigate", "click", "fill", "text", "screenshot",
                        "html", "evaluate", "wait", "back", "forward", "close",
                    ],
                    "description": "Browser action to perform",
                },
                "url": {
                    "type": "string",
                    "description": "URL to navigate to (for 'navigate' action)",
                    "default": "",
                },
                "selector": {
                    "type": "string",
                    "description": "CSS selector for element interactions",
                    "default": "",
                },
                "value": {
                    "type": "string",
                    "description": "Value for fill action, or JS for evaluate action",
                    "default": "",
                },
                "timeout": {
                    "type": "number",
                    "description": "Timeout in milliseconds (default: 30000)",
                    "default": 30000,
                },
            },
            "required": ["action"],
        }

    async def _ensure_browser(self):
        """Lazily initialize browser and page."""
        if self._page is not None:
            return

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise RuntimeError(
                "Playwright not installed. Run: pip install playwright && playwright install chromium"
            )

        pw = await async_playwright().start()
        self._browser = await pw.chromium.launch(headless=True)
        self._page = await self._browser.new_page()

    async def execute(
        self,
        action: str = "",
        url: str = "",
        selector: str = "",
        value: str = "",
        timeout: float = 30000,
        **kwargs,
    ) -> ToolResult:
        if not action:
            return ToolResult(error="Action is required", success=False)

        try:
            await self._ensure_browser()
        except RuntimeError as e:
            return ToolResult(error=str(e), success=False)

        try:
            if action == "navigate":
                return await self._navigate(url, timeout)
            elif action == "click":
                return await self._click(selector, timeout)
            elif action == "fill":
                return await self._fill(selector, value, timeout)
            elif action == "text":
                return await self._get_text(selector)
            elif action == "screenshot":
                return await self._screenshot()
            elif action == "html":
                return await self._get_html(selector)
            elif action == "evaluate":
                return await self._evaluate(value)
            elif action == "wait":
                return await self._wait(selector, timeout)
            elif action == "back":
                await self._page.go_back()
                return ToolResult(output="Navigated back", success=True)
            elif action == "forward":
                await self._page.go_forward()
                return ToolResult(output="Navigated forward", success=True)
            elif action == "close":
                return await self._close()
            else:
                return ToolResult(error=f"Unknown action: {action}", success=False)
        except Exception as e:
            return ToolResult(error=f"Browser error: {e}", success=False)

    async def _navigate(self, url: str, timeout: float) -> ToolResult:
        if not url:
            return ToolResult(error="URL required for navigate action", success=False)

        # SSRF protection
        try:
            from tools.web_search import _is_ssrf_target
            ssrf = _is_ssrf_target(url)
            if ssrf:
                return ToolResult(error=f"Blocked: {ssrf}", success=False)
        except ImportError:
            pass

        resp = await self._page.goto(url, timeout=timeout)
        title = await self._page.title()
        status = resp.status if resp else "unknown"
        return ToolResult(
            output=f"Navigated to: {url}\nTitle: {title}\nStatus: {status}",
            success=True,
        )

    async def _click(self, selector: str, timeout: float) -> ToolResult:
        if not selector:
            return ToolResult(error="Selector required for click", success=False)
        await self._page.click(selector, timeout=timeout)
        return ToolResult(output=f"Clicked: {selector}", success=True)

    async def _fill(self, selector: str, value: str, timeout: float) -> ToolResult:
        if not selector:
            return ToolResult(error="Selector required for fill", success=False)
        await self._page.fill(selector, value, timeout=timeout)
        return ToolResult(output=f"Filled '{selector}' with value", success=True)

    async def _get_text(self, selector: str) -> ToolResult:
        if selector:
            element = await self._page.query_selector(selector)
            if not element:
                return ToolResult(error=f"Element not found: {selector}", success=False)
            text = await element.text_content()
        else:
            text = await self._page.inner_text("body")

        if len(text) > 50000:
            text = text[:50000] + "\n... (truncated)"
        return ToolResult(output=text, success=True)

    async def _screenshot(self) -> ToolResult:
        screenshot_dir = os.path.join(self._workspace, ".screenshots")
        os.makedirs(screenshot_dir, exist_ok=True)

        import time
        filename = f"screenshot_{int(time.time())}.png"
        path = os.path.join(screenshot_dir, filename)
        await self._page.screenshot(path=path, full_page=False)
        return ToolResult(
            output=f"Screenshot saved: {path}\nPage title: {await self._page.title()}",
            success=True,
        )

    async def _get_html(self, selector: str) -> ToolResult:
        if selector:
            element = await self._page.query_selector(selector)
            if not element:
                return ToolResult(error=f"Element not found: {selector}", success=False)
            html = await element.inner_html()
        else:
            html = await self._page.content()

        if len(html) > 50000:
            html = html[:50000] + "\n... (truncated)"
        return ToolResult(output=html, success=True)

    # Patterns that indicate data exfiltration or dangerous JS operations
    _BLOCKED_JS_PATTERNS = [
        re.compile(r'\bfetch\s*\(', re.IGNORECASE),
        re.compile(r'\bXMLHttpRequest\b', re.IGNORECASE),
        re.compile(r'\bnew\s+WebSocket\b', re.IGNORECASE),
        re.compile(r'\bnavigator\.sendBeacon\b', re.IGNORECASE),
        re.compile(r'\bdocument\.cookie\b', re.IGNORECASE),
        re.compile(r'\blocalStorage\b', re.IGNORECASE),
        re.compile(r'\bsessionStorage\b', re.IGNORECASE),
        re.compile(r'\bindexedDB\b', re.IGNORECASE),
        re.compile(r'\beval\s*\(', re.IGNORECASE),
        re.compile(r'\bFunction\s*\(', re.IGNORECASE),
        re.compile(r'\bimportScripts\b', re.IGNORECASE),
        re.compile(r'\bwindow\.open\b', re.IGNORECASE),
    ]

    async def _evaluate(self, js: str) -> ToolResult:
        if not js:
            return ToolResult(error="JavaScript code required", success=False)

        # Block dangerous JS patterns that could exfiltrate data
        for pattern in self._BLOCKED_JS_PATTERNS:
            if pattern.search(js):
                return ToolResult(
                    error=f"Blocked: JavaScript contains disallowed pattern ({pattern.pattern}). "
                          "Use specific browser actions (text, html, click, fill) instead.",
                    success=False,
                )

        result = await self._page.evaluate(js)
        return ToolResult(output=str(result), success=True)

    async def _wait(self, selector: str, timeout: float) -> ToolResult:
        if not selector:
            return ToolResult(error="Selector required for wait", success=False)
        await self._page.wait_for_selector(selector, timeout=timeout)
        return ToolResult(output=f"Element found: {selector}", success=True)

    async def _close(self) -> ToolResult:
        if self._browser:
            await self._browser.close()
            self._browser = None
            self._page = None
        return ToolResult(output="Browser closed", success=True)
