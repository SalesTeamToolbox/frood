"""
App testing tool — AI-driven QA for built applications.

Connects the app platform (AppTool), browser automation (BrowserTool),
vision analysis (VisionTool), and log monitoring into an integrated
testing workflow. Enables agents to verify apps work correctly by
navigating to them, taking screenshots, analyzing visuals, and
checking for errors.

Graceful degradation:
- No Playwright installed -> HTTP-only testing (health_check, check_logs)
- No vision API key -> screenshots saved but not analyzed
- No app running -> clear error messages
"""

import asyncio
import base64
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

from tools.base import Tool, ToolResult

logger = logging.getLogger("frood.tools.app_test")

# Patterns that indicate errors in app logs
_ERROR_PATTERNS = [
    re.compile(r"\bERROR\b", re.IGNORECASE),
    re.compile(r"\bTraceback\b"),
    re.compile(r"\bException\b"),
    re.compile(r"\b5\d{2}\b"),  # 5xx status codes
    re.compile(r"\bWARNING\b", re.IGNORECASE),
    re.compile(r"\bCRITICAL\b", re.IGNORECASE),
    re.compile(r"\bFATAL\b", re.IGNORECASE),
    re.compile(r"\bUnhandledPromiseRejection\b"),
    re.compile(r"\bSegmentation fault\b", re.IGNORECASE),
]

# Severity classification for log entries
_SEVERITY_MAP = {
    "CRITICAL": "critical",
    "FATAL": "critical",
    "ERROR": "error",
    "Traceback": "error",
    "Exception": "error",
    "UnhandledPromiseRejection": "error",
    "Segmentation fault": "error",
    "WARNING": "warning",
}


@dataclass
class Finding:
    """A single QA finding from testing."""

    category: str  # visual, log, health, flow
    severity: str  # critical, error, warning, info
    message: str
    details: str = ""
    screenshot_path: str = ""

    def to_dict(self) -> dict:
        d = {"category": self.category, "severity": self.severity, "message": self.message}
        if self.details:
            d["details"] = self.details
        if self.screenshot_path:
            d["screenshot_path"] = self.screenshot_path
        return d


class AppTestTool(Tool):
    """Test running applications with browser automation and visual analysis.

    Actions:
    - smoke_test: Start app, navigate, screenshot, vision analyze, check logs
    - visual_check: Navigate to URL, screenshot, vision analyze with prompt
    - check_logs: Tail app logs and scan for errors/warnings
    - test_flow: Multi-step browser flow with screenshots at each step
    - health_check: HTTP GET to app URL — status code and response time
    - generate_report: Aggregate findings into a QA summary
    """

    def __init__(self, app_manager, sandbox):
        self._manager = app_manager
        self._sandbox = sandbox
        self._findings: list[Finding] = []
        self._browser = None
        self._page = None

    @property
    def name(self) -> str:
        return "app_test"

    @property
    def description(self) -> str:
        return (
            "Test running applications with automated QA. Navigate to apps, "
            "take screenshots, analyze visuals with AI vision, check logs for "
            "errors, run multi-step browser flows, and generate QA reports. "
            "Actions: smoke_test, visual_check, check_logs, test_flow, "
            "health_check, generate_report."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "smoke_test",
                        "visual_check",
                        "check_logs",
                        "test_flow",
                        "health_check",
                        "generate_report",
                    ],
                    "description": "Testing action to perform",
                },
                "app_id": {
                    "type": "string",
                    "description": "App ID to test (for smoke_test, check_logs, health_check)",
                },
                "url": {
                    "type": "string",
                    "description": "URL to navigate to (for visual_check, or override for smoke_test)",
                },
                "prompt": {
                    "type": "string",
                    "description": "Custom vision analysis prompt (for visual_check)",
                },
                "steps": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "action": {
                                "type": "string",
                                "enum": ["navigate", "click", "fill", "wait", "screenshot"],
                            },
                            "selector": {"type": "string"},
                            "value": {"type": "string"},
                            "url": {"type": "string"},
                            "description": {"type": "string"},
                        },
                    },
                    "description": "Browser steps for test_flow action",
                },
                "log_lines": {
                    "type": "integer",
                    "description": "Number of log lines to check (default: 100)",
                },
            },
            "required": ["action"],
        }

    async def execute(self, action: str = "", **kwargs) -> ToolResult:
        try:
            if action == "smoke_test":
                return await self._smoke_test(**kwargs)
            elif action == "visual_check":
                return await self._visual_check(**kwargs)
            elif action == "check_logs":
                return await self._check_logs(**kwargs)
            elif action == "test_flow":
                return await self._test_flow(**kwargs)
            elif action == "health_check":
                return await self._health_check(**kwargs)
            elif action == "generate_report":
                return await self._generate_report(**kwargs)
            return ToolResult(error=f"Unknown action: {action}", success=False)
        except Exception as e:
            logger.error(f"app_test {action} failed: {e}")
            return ToolResult(error=f"app_test {action} failed: {e}", success=False)

    # ------------------------------------------------------------------
    # Action implementations
    # ------------------------------------------------------------------

    async def _smoke_test(self, app_id: str = "", url: str = "", **kwargs) -> ToolResult:
        """Full smoke test: start app, navigate, screenshot, analyze, check logs."""
        if not app_id:
            return ToolResult(error="app_id is required for smoke_test", success=False)

        parts = []

        # 1. Check app status and get URL
        app_url = url
        if not app_url:
            app_url, status_msg = await self._get_app_url(app_id)
            parts.append(status_msg)
            if not app_url:
                return ToolResult(error=f"Cannot determine app URL. {status_msg}", success=False)

        # 2. Health check
        health_result = await self._do_health_check(app_url)
        parts.append(f"\n## Health Check\n{health_result}")

        if "FAIL" in health_result:
            self._findings.append(
                Finding(
                    category="health",
                    severity="critical",
                    message="App failed health check",
                    details=health_result,
                )
            )
            # Still try to check logs even if health check fails
            log_result = await self._do_check_logs(app_id, 50)
            parts.append(f"\n## Logs\n{log_result}")
            return ToolResult(output="\n".join(parts))

        # 3. Screenshot + visual analysis (if browser available)
        screenshot_result = await self._do_screenshot_and_analyze(
            app_url,
            "Analyze this web application screenshot. Check for: "
            "1) Page loaded correctly (not blank/error page) "
            "2) Layout and styling look correct "
            "3) No broken images or missing resources "
            "4) Text is readable and properly formatted "
            "5) Any error messages visible on page",
        )
        parts.append(f"\n## Visual Analysis\n{screenshot_result}")

        # 4. Check logs
        log_result = await self._do_check_logs(app_id, 50)
        parts.append(f"\n## Log Analysis\n{log_result}")

        # 5. Summary
        errors = [f for f in self._findings if f.severity in ("critical", "error")]
        warnings = [f for f in self._findings if f.severity == "warning"]
        status = "PASS" if not errors else "FAIL"
        parts.append(
            f"\n## Smoke Test Result: {status}\nErrors: {len(errors)}, Warnings: {len(warnings)}"
        )

        return ToolResult(output="\n".join(parts))

    async def _visual_check(self, url: str = "", prompt: str = "", **kwargs) -> ToolResult:
        """Navigate to URL, screenshot, and analyze with vision."""
        if not url:
            return ToolResult(error="url is required for visual_check", success=False)

        analysis_prompt = prompt or (
            "Analyze this web page screenshot. Describe the layout, content, "
            "styling, and identify any visual issues or improvements."
        )

        result = await self._do_screenshot_and_analyze(url, analysis_prompt)
        return ToolResult(output=result)

    async def _check_logs(self, app_id: str = "", log_lines: int = 100, **kwargs) -> ToolResult:
        """Tail app logs and scan for errors."""
        if not app_id:
            return ToolResult(error="app_id is required for check_logs", success=False)

        if isinstance(log_lines, str):
            log_lines = int(log_lines) if log_lines.isdigit() else 100

        result = await self._do_check_logs(app_id, log_lines)
        return ToolResult(output=result)

    async def _test_flow(self, steps: list | None = None, **kwargs) -> ToolResult:
        """Execute multi-step browser flow with screenshots at each step."""
        if not steps:
            return ToolResult(error="steps array is required for test_flow", success=False)

        # Parse steps if they come as a JSON string
        if isinstance(steps, str):
            try:
                steps = json.loads(steps)
            except json.JSONDecodeError:
                return ToolResult(error="Invalid steps JSON", success=False)

        has_browser = await self._ensure_browser()
        if not has_browser:
            return ToolResult(
                error="Playwright is required for test_flow but is not installed. "
                "Install with: pip install playwright && playwright install chromium",
                success=False,
            )

        results = []
        for i, step in enumerate(steps):
            step_action = step.get("action", "")
            step_desc = step.get("description", f"Step {i + 1}: {step_action}")
            results.append(f"\n### {step_desc}")

            try:
                if step_action == "navigate":
                    url = step.get("url", step.get("value", ""))
                    if not url:
                        results.append("SKIP — no URL provided")
                        continue
                    await self._page.goto(url, wait_until="networkidle", timeout=15000)
                    results.append(f"Navigated to {url}")

                elif step_action == "click":
                    selector = step.get("selector", "")
                    if not selector:
                        results.append("SKIP — no selector provided")
                        continue
                    await self._page.click(selector, timeout=5000)
                    results.append(f"Clicked: {selector}")

                elif step_action == "fill":
                    selector = step.get("selector", "")
                    value = step.get("value", "")
                    if not selector:
                        results.append("SKIP — no selector provided")
                        continue
                    await self._page.fill(selector, value, timeout=5000)
                    results.append(f"Filled {selector} with '{value}'")

                elif step_action == "wait":
                    ms = int(step.get("value", "1000"))
                    await asyncio.sleep(ms / 1000)
                    results.append(f"Waited {ms}ms")

                elif step_action == "screenshot":
                    screenshot_result = await self._take_screenshot_and_analyze(
                        step.get("value", f"Step {i + 1} screenshot analysis")
                    )
                    results.append(screenshot_result)

                else:
                    results.append(f"Unknown step action: {step_action}")

                # Take a screenshot after each step for visual tracking
                if step_action != "screenshot":
                    ss_path = await self._save_screenshot(f"flow_step_{i + 1}")
                    if ss_path:
                        results.append(f"Screenshot saved: {ss_path}")

            except Exception as e:
                error_msg = f"FAIL — {e}"
                results.append(error_msg)
                self._findings.append(
                    Finding(
                        category="flow",
                        severity="error",
                        message=f"Step {i + 1} ({step_action}) failed",
                        details=str(e),
                    )
                )

        return ToolResult(output="\n".join(results))

    async def _health_check(self, app_id: str = "", url: str = "", **kwargs) -> ToolResult:
        """HTTP GET to app — status code and response time."""
        check_url = url
        if not check_url:
            if not app_id:
                return ToolResult(error="app_id or url is required for health_check", success=False)
            check_url, status_msg = await self._get_app_url(app_id)
            if not check_url:
                return ToolResult(error=status_msg, success=False)

        result = await self._do_health_check(check_url)
        return ToolResult(output=result)

    async def _generate_report(self, **kwargs) -> ToolResult:
        """Aggregate all findings into a structured QA report."""
        if not self._findings:
            return ToolResult(
                output="## QA Report\n\nNo findings recorded. "
                "Run smoke_test, visual_check, check_logs, or test_flow first."
            )

        critical = [f for f in self._findings if f.severity == "critical"]
        errors = [f for f in self._findings if f.severity == "error"]
        warnings = [f for f in self._findings if f.severity == "warning"]
        info = [f for f in self._findings if f.severity == "info"]

        overall = "FAIL" if (critical or errors) else ("WARNING" if warnings else "PASS")

        parts = [
            f"## QA Report — {overall}",
            f"\nTotal findings: {len(self._findings)}",
            f"- Critical: {len(critical)}",
            f"- Errors: {len(errors)}",
            f"- Warnings: {len(warnings)}",
            f"- Info: {len(info)}",
        ]

        for severity_label, items in [
            ("Critical", critical),
            ("Errors", errors),
            ("Warnings", warnings),
            ("Info", info),
        ]:
            if items:
                parts.append(f"\n### {severity_label}")
                for f in items:
                    parts.append(f"- [{f.category}] {f.message}")
                    if f.details:
                        parts.append(f"  Details: {f.details[:200]}")

        # Clear findings after report
        self._findings.clear()

        return ToolResult(output="\n".join(parts))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_app_url(self, app_id: str) -> tuple[str, str]:
        """Get the URL for a running app. Returns (url, status_message)."""
        try:
            status = await self._manager.get_status(app_id)
        except Exception as e:
            return "", f"Failed to get app status: {e}"

        if not status:
            return "", f"App '{app_id}' not found"

        if status.get("status") != "running":
            return "", f"App '{app_id}' is not running (status: {status.get('status', 'unknown')})"

        port = status.get("port")
        if not port:
            return "", f"App '{app_id}' has no port assigned"

        host = status.get("host", "127.0.0.1")
        url = f"http://{host}:{port}"
        return url, f"App '{app_id}' running at {url}"

    async def _do_health_check(self, url: str) -> str:
        """Perform HTTP health check on a URL."""
        try:
            import httpx

            start = time.monotonic()
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                resp = await client.get(url)
            elapsed = (time.monotonic() - start) * 1000

            status = "PASS" if resp.status_code < 400 else "FAIL"
            result = (
                f"{status} — HTTP {resp.status_code} in {elapsed:.0f}ms "
                f"(Content-Length: {len(resp.content)} bytes)"
            )

            if resp.status_code >= 400:
                self._findings.append(
                    Finding(
                        category="health",
                        severity="error" if resp.status_code >= 500 else "warning",
                        message=f"HTTP {resp.status_code} from {url}",
                        details=resp.text[:500],
                    )
                )

            return result
        except Exception as e:
            self._findings.append(
                Finding(
                    category="health",
                    severity="critical",
                    message=f"Cannot connect to {url}",
                    details=str(e),
                )
            )
            return f"FAIL — Cannot connect: {e}"

    async def _do_check_logs(self, app_id: str, num_lines: int = 100) -> str:
        """Check app logs for errors and warnings."""
        try:
            logs = await self._manager.get_logs(app_id, lines=num_lines)
        except Exception as e:
            return f"Failed to read logs: {e}"

        if not logs:
            return "No logs available"

        issues = []
        for line_num, line in enumerate(logs.splitlines(), 1):
            for pattern in _ERROR_PATTERNS:
                match = pattern.search(line)
                if match:
                    matched_text = match.group(0)
                    severity = "warning"
                    for keyword, sev in _SEVERITY_MAP.items():
                        if keyword.lower() in matched_text.lower():
                            severity = sev
                            break

                    issues.append(
                        {
                            "line": line_num,
                            "severity": severity,
                            "text": line.strip()[:200],
                        }
                    )

                    self._findings.append(
                        Finding(
                            category="log",
                            severity=severity,
                            message=f"Log line {line_num}: {matched_text}",
                            details=line.strip()[:200],
                        )
                    )
                    break  # One match per line

        if not issues:
            return f"Clean — no errors or warnings in last {num_lines} lines"

        # Deduplicate similar messages
        error_count = sum(1 for i in issues if i["severity"] in ("critical", "error"))
        warn_count = sum(1 for i in issues if i["severity"] == "warning")

        parts = [f"Found {error_count} errors and {warn_count} warnings:\n"]
        for issue in issues[:20]:  # Cap at 20 to avoid huge output
            parts.append(f"  [{issue['severity'].upper()}] L{issue['line']}: {issue['text']}")

        if len(issues) > 20:
            parts.append(f"\n  ... and {len(issues) - 20} more issues")

        return "\n".join(parts)

    async def _ensure_browser(self) -> bool:
        """Lazily initialize Playwright browser. Returns False if unavailable."""
        if self._page:
            return True

        try:
            from playwright.async_api import async_playwright

            pw = await async_playwright().start()
            self._browser = await pw.chromium.launch(headless=True)
            self._page = await self._browser.new_page(viewport={"width": 1280, "height": 720})
            return True
        except ImportError:
            logger.info("Playwright not installed — browser testing unavailable")
            return False
        except Exception as e:
            logger.warning(f"Failed to launch browser: {e}")
            return False

    async def _save_screenshot(self, name: str = "screenshot") -> str:
        """Take a screenshot and save to workspace. Returns path or empty string."""
        if not self._page:
            return ""

        try:
            workspace = str(self._sandbox.workspace_path)
            screenshots_dir = Path(workspace) / ".frood" / "screenshots"
            screenshots_dir.mkdir(parents=True, exist_ok=True)

            timestamp = int(time.time())
            filename = f"{name}_{timestamp}.png"
            filepath = screenshots_dir / filename

            await self._page.screenshot(path=str(filepath), full_page=True)
            return str(filepath)
        except Exception as e:
            logger.warning(f"Screenshot failed: {e}")
            return ""

    async def _do_screenshot_and_analyze(self, url: str, prompt: str) -> str:
        """Navigate to URL, take screenshot, and optionally analyze with vision."""
        has_browser = await self._ensure_browser()

        if not has_browser:
            # Fallback: HTTP-only check
            return (
                "Browser not available (Playwright not installed). "
                "Use health_check for HTTP-level testing, or install Playwright: "
                "pip install playwright && playwright install chromium"
            )

        try:
            await self._page.goto(url, wait_until="networkidle", timeout=15000)
        except Exception as e:
            self._findings.append(
                Finding(
                    category="visual",
                    severity="error",
                    message=f"Failed to navigate to {url}",
                    details=str(e),
                )
            )
            return f"Failed to load page: {e}"

        # Take screenshot
        screenshot_path = await self._save_screenshot("visual_check")
        if not screenshot_path:
            return "Failed to capture screenshot"

        # Try vision analysis
        analysis = await self._analyze_screenshot(screenshot_path, prompt)
        if analysis.startswith("["):
            # Vision failed — return screenshot path for manual review
            self._findings.append(
                Finding(
                    category="visual",
                    severity="info",
                    message="Screenshot saved for manual review",
                    screenshot_path=screenshot_path,
                )
            )
            return (
                f"Screenshot saved: {screenshot_path}\n"
                f"Vision analysis unavailable: {analysis}\n"
                "Review the screenshot manually."
            )

        # Check vision analysis for issues
        lower_analysis = analysis.lower()
        if any(
            kw in lower_analysis
            for kw in ["error", "broken", "missing", "blank page", "not loading"]
        ):
            self._findings.append(
                Finding(
                    category="visual",
                    severity="warning",
                    message="Visual issues detected",
                    details=analysis[:300],
                    screenshot_path=screenshot_path,
                )
            )

        return f"Screenshot: {screenshot_path}\n\nVisual Analysis:\n{analysis}"

    async def _take_screenshot_and_analyze(self, prompt: str) -> str:
        """Take screenshot of current page and analyze (no navigation)."""
        screenshot_path = await self._save_screenshot("flow_analysis")
        if not screenshot_path:
            return "Failed to capture screenshot"

        analysis = await self._analyze_screenshot(screenshot_path, prompt)
        return f"Screenshot: {screenshot_path}\nAnalysis: {analysis}"

    async def _analyze_screenshot(self, screenshot_path: str, prompt: str) -> str:
        """Send screenshot to vision LLM for analysis."""
        try:
            import aiofiles

            from tools.vision_tool import _compress_image
        except ImportError as e:
            return f"[Vision dependencies not available: {e}]"

        try:
            async with aiofiles.open(screenshot_path, "rb") as f:
                raw_data = await f.read()

            compressed, mime = _compress_image(raw_data)
            b64 = base64.b64encode(compressed).decode("utf-8")
        except Exception as e:
            return f"[Failed to process screenshot: {e}]"

        # Build vision message and call LLM
        try:
            from openai import AsyncOpenAI

            from core.config import settings

            # Determine vision model and API key (same logic as VisionTool)
            model = getattr(settings, "vision_model", "") or ""
            api_key = ""
            base_url = ""

            if model:
                if "gpt" in model.lower():
                    api_key = os.getenv("OPENAI_API_KEY", "")
                    base_url = "https://api.openai.com/v1"
                elif "claude" in model.lower():
                    api_key = os.getenv("ANTHROPIC_API_KEY", "")
                    base_url = "https://api.anthropic.com/v1"
                else:
                    api_key = os.getenv("OPENROUTER_API_KEY", "")
                    base_url = "https://openrouter.ai/api/v1"
            else:
                openai_key = os.getenv("OPENAI_API_KEY", "")
                or_key = os.getenv("OPENROUTER_API_KEY", "")
                if openai_key:
                    api_key = openai_key
                    base_url = "https://api.openai.com/v1"
                    model = "gpt-4o-mini"
                elif or_key:
                    api_key = or_key
                    base_url = "https://openrouter.ai/api/v1"
                    model = "openai/gpt-4o-mini"
                else:
                    return (
                        "[No vision API key configured. Set OPENAI_API_KEY or OPENROUTER_API_KEY]"
                    )

            client = AsyncOpenAI(api_key=api_key, base_url=base_url)
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime};base64,{b64}"},
                        },
                    ],
                }
            ]

            response = await client.chat.completions.create(
                model=model, messages=messages, max_tokens=1024
            )
            return response.choices[0].message.content or "[No response]"
        except ImportError:
            return "[OpenAI SDK not installed]"
        except Exception as e:
            logger.error(f"Vision analysis failed: {e}")
            return f"[Vision analysis failed: {e}]"

    async def close(self):
        """Clean up browser resources."""
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None
            self._page = None
