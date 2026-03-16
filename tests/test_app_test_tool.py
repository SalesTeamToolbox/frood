"""Tests for the AppTestTool — AI-driven app QA testing."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tools.app_test_tool import _ERROR_PATTERNS, AppTestTool, Finding


class TestAppTestToolBasics:
    """Basic tool interface tests."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.workspace = tmp_path / "workspace"
        self.workspace.mkdir()
        self.sandbox = MagicMock()
        self.sandbox.workspace_path = self.workspace
        self.manager = AsyncMock()
        self.tool = AppTestTool(self.manager, self.sandbox)

    def test_name(self):
        assert self.tool.name == "app_test"

    def test_description(self):
        assert "Test running applications" in self.tool.description

    def test_parameters_schema(self):
        params = self.tool.parameters
        assert params["type"] == "object"
        assert "action" in params["properties"]
        actions = params["properties"]["action"]["enum"]
        assert "smoke_test" in actions
        assert "visual_check" in actions
        assert "check_logs" in actions
        assert "test_flow" in actions
        assert "health_check" in actions
        assert "generate_report" in actions

    @pytest.mark.asyncio
    async def test_unknown_action(self):
        result = await self.tool.execute(action="nonexistent")
        assert not result.success
        assert "Unknown action" in result.error


class TestHealthCheck:
    """Tests for the health_check action."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.workspace = tmp_path / "workspace"
        self.workspace.mkdir()
        self.sandbox = MagicMock()
        self.sandbox.workspace_path = self.workspace
        self.manager = AsyncMock()
        self.tool = AppTestTool(self.manager, self.sandbox)

    @pytest.mark.asyncio
    async def test_health_check_requires_app_id_or_url(self):
        result = await self.tool.execute(action="health_check")
        assert not result.success
        assert "required" in result.error.lower()

    @pytest.mark.asyncio
    async def test_health_check_with_url_success(self):
        async def mock_health(url):
            return "PASS — HTTP 200 in 50ms (Content-Length: 15 bytes)"

        with patch.object(self.tool, "_do_health_check", side_effect=mock_health):
            result = await self.tool.execute(action="health_check", url="http://localhost:8080")
        assert result.success
        assert "PASS" in result.output
        assert "200" in result.output

    @pytest.mark.asyncio
    async def test_health_check_with_url_failure(self):
        async def mock_health(url):
            self.tool._findings.append(
                Finding(category="health", severity="error", message=f"HTTP 500 from {url}")
            )
            return "FAIL — HTTP 500 in 100ms (Content-Length: 21 bytes)"

        with patch.object(self.tool, "_do_health_check", side_effect=mock_health):
            result = await self.tool.execute(action="health_check", url="http://localhost:8080")
        assert result.success  # Tool itself succeeds — reports the failure
        assert "FAIL" in result.output
        assert "500" in result.output

    @pytest.mark.asyncio
    async def test_health_check_connection_error(self):
        async def mock_health(url):
            self.tool._findings.append(
                Finding(category="health", severity="critical", message=f"Cannot connect to {url}")
            )
            return "FAIL — Cannot connect: Connection refused"

        with patch.object(self.tool, "_do_health_check", side_effect=mock_health):
            result = await self.tool.execute(action="health_check", url="http://localhost:8080")
        assert "FAIL" in result.output
        assert "Cannot connect" in result.output

    @pytest.mark.asyncio
    async def test_health_check_with_app_id(self):
        self.manager.get_status = AsyncMock(
            return_value={"status": "running", "port": 9100, "host": "127.0.0.1"}
        )

        async def mock_health(url):
            return "PASS — HTTP 200 in 30ms (Content-Length: 2 bytes)"

        with patch.object(self.tool, "_do_health_check", side_effect=mock_health):
            result = await self.tool.execute(action="health_check", app_id="test-app")
        assert result.success
        assert "PASS" in result.output

    @pytest.mark.asyncio
    async def test_health_check_app_not_running(self):
        self.manager.get_status = AsyncMock(return_value={"status": "stopped", "port": 9100})

        result = await self.tool.execute(action="health_check", app_id="test-app")
        assert not result.success
        assert "not running" in result.error


class TestDoHealthCheck:
    """Tests for the _do_health_check internal method (with httpx mock)."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.sandbox = MagicMock()
        self.sandbox.workspace_path = tmp_path
        self.manager = AsyncMock()
        self.tool = AppTestTool(self.manager, self.sandbox)

    @pytest.mark.asyncio
    async def test_do_health_check_success(self):

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"OK"
        mock_response.text = "OK"

        with patch("httpx.AsyncClient") as MockClient:
            client_instance = AsyncMock()
            client_instance.get = AsyncMock(return_value=mock_response)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=client_instance)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await self.tool._do_health_check("http://localhost:8080")

        assert "PASS" in result
        assert "200" in result

    @pytest.mark.asyncio
    async def test_do_health_check_server_error(self):

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.content = b"error"
        mock_response.text = "Internal Server Error"

        with patch("httpx.AsyncClient") as MockClient:
            client_instance = AsyncMock()
            client_instance.get = AsyncMock(return_value=mock_response)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=client_instance)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await self.tool._do_health_check("http://localhost:8080")

        assert "FAIL" in result
        assert len(self.tool._findings) > 0

    @pytest.mark.asyncio
    async def test_do_health_check_connection_refused(self):
        with patch("httpx.AsyncClient") as MockClient:
            client_instance = AsyncMock()
            client_instance.get = AsyncMock(side_effect=ConnectionError("refused"))
            MockClient.return_value.__aenter__ = AsyncMock(return_value=client_instance)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await self.tool._do_health_check("http://localhost:8080")

        assert "FAIL" in result
        assert "Cannot connect" in result
        assert len(self.tool._findings) > 0


class TestCheckLogs:
    """Tests for the check_logs action."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.workspace = tmp_path / "workspace"
        self.workspace.mkdir()
        self.sandbox = MagicMock()
        self.sandbox.workspace_path = self.workspace
        self.manager = AsyncMock()
        self.tool = AppTestTool(self.manager, self.sandbox)

    @pytest.mark.asyncio
    async def test_check_logs_requires_app_id(self):
        result = await self.tool.execute(action="check_logs")
        assert not result.success

    @pytest.mark.asyncio
    async def test_check_logs_clean(self):
        self.manager.get_logs = AsyncMock(
            return_value="INFO: Server started\nINFO: Listening on port 8080\nINFO: Request GET /\n"
        )
        result = await self.tool.execute(action="check_logs", app_id="test-app")
        assert result.success
        assert "Clean" in result.output

    @pytest.mark.asyncio
    async def test_check_logs_with_errors(self):
        self.manager.get_logs = AsyncMock(
            return_value="INFO: Server started\nERROR: Database connection failed\nTraceback (most recent call last):\n  File app.py\n"
        )
        result = await self.tool.execute(action="check_logs", app_id="test-app")
        assert result.success
        assert "ERROR" in result.output
        # Findings should be recorded
        assert len(self.tool._findings) > 0

    @pytest.mark.asyncio
    async def test_check_logs_with_warnings(self):
        self.manager.get_logs = AsyncMock(
            return_value="WARNING: Deprecated API usage\nINFO: Request handled\n"
        )
        result = await self.tool.execute(action="check_logs", app_id="test-app")
        assert result.success
        assert "WARNING" in result.output

    @pytest.mark.asyncio
    async def test_check_logs_no_logs(self):
        self.manager.get_logs = AsyncMock(return_value="")
        result = await self.tool.execute(action="check_logs", app_id="test-app")
        assert result.success
        assert "No logs" in result.output

    @pytest.mark.asyncio
    async def test_check_logs_string_log_lines(self):
        """LLM may send log_lines as string instead of int."""
        self.manager.get_logs = AsyncMock(return_value="INFO: OK\n")
        result = await self.tool.execute(action="check_logs", app_id="test-app", log_lines="50")
        assert result.success

    @pytest.mark.asyncio
    async def test_check_logs_5xx_detection(self):
        self.manager.get_logs = AsyncMock(return_value='127.0.0.1 - - "GET /api" 502 0\n')
        result = await self.tool.execute(action="check_logs", app_id="test-app")
        assert result.success
        assert len(self.tool._findings) > 0


class TestSmokeTest:
    """Tests for the smoke_test action."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.workspace = tmp_path / "workspace"
        self.workspace.mkdir()
        self.sandbox = MagicMock()
        self.sandbox.workspace_path = self.workspace
        self.manager = AsyncMock()
        self.tool = AppTestTool(self.manager, self.sandbox)

    @pytest.mark.asyncio
    async def test_smoke_test_requires_app_id(self):
        result = await self.tool.execute(action="smoke_test")
        assert not result.success
        assert "app_id" in result.error.lower()

    @pytest.mark.asyncio
    async def test_smoke_test_app_not_found(self):
        self.manager.get_status = AsyncMock(return_value=None)
        result = await self.tool.execute(action="smoke_test", app_id="nonexistent")
        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_smoke_test_app_not_running(self):
        self.manager.get_status = AsyncMock(return_value={"status": "stopped"})
        result = await self.tool.execute(action="smoke_test", app_id="test-app")
        assert not result.success
        assert "not running" in result.error.lower()

    @pytest.mark.asyncio
    async def test_smoke_test_success_no_browser(self):
        """Smoke test without Playwright — HTTP-only path."""
        self.manager.get_status = AsyncMock(
            return_value={"status": "running", "port": 9100, "host": "127.0.0.1"}
        )
        self.manager.get_logs = AsyncMock(return_value="INFO: Server started\n")

        async def mock_health(url):
            return "PASS — HTTP 200 in 50ms (Content-Length: 15 bytes)"

        async def mock_screenshot(url, prompt):
            return "Browser not available (Playwright not installed)."

        with (
            patch.object(self.tool, "_do_health_check", side_effect=mock_health),
            patch.object(self.tool, "_do_screenshot_and_analyze", side_effect=mock_screenshot),
        ):
            result = await self.tool.execute(action="smoke_test", app_id="test-app")

        assert result.success
        assert "Health Check" in result.output
        assert "PASS" in result.output

    @pytest.mark.asyncio
    async def test_smoke_test_health_fail_still_checks_logs(self):
        """If health check fails, should still check logs for diagnosis."""
        self.manager.get_status = AsyncMock(
            return_value={"status": "running", "port": 9100, "host": "127.0.0.1"}
        )
        self.manager.get_logs = AsyncMock(return_value="ERROR: Port already in use\n")

        async def mock_health(url):
            return "FAIL — Cannot connect: Connection refused"

        with patch.object(self.tool, "_do_health_check", side_effect=mock_health):
            result = await self.tool.execute(action="smoke_test", app_id="test-app")

        assert result.success  # Tool completes; it reports failures in output
        assert "FAIL" in result.output
        assert "Logs" in result.output


class TestVisualCheck:
    """Tests for the visual_check action."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.workspace = tmp_path / "workspace"
        self.workspace.mkdir()
        self.sandbox = MagicMock()
        self.sandbox.workspace_path = self.workspace
        self.manager = AsyncMock()
        self.tool = AppTestTool(self.manager, self.sandbox)

    @pytest.mark.asyncio
    async def test_visual_check_requires_url(self):
        result = await self.tool.execute(action="visual_check")
        assert not result.success
        assert "url" in result.error.lower()

    @pytest.mark.asyncio
    async def test_visual_check_no_browser(self):
        """Without Playwright, should return informative message."""
        with patch.object(self.tool, "_ensure_browser", return_value=False):
            result = await self.tool.execute(action="visual_check", url="http://localhost:8080")
        assert result.success
        assert "not available" in result.output.lower() or "Playwright" in result.output


class TestTestFlow:
    """Tests for the test_flow action."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.workspace = tmp_path / "workspace"
        self.workspace.mkdir()
        self.sandbox = MagicMock()
        self.sandbox.workspace_path = self.workspace
        self.manager = AsyncMock()
        self.tool = AppTestTool(self.manager, self.sandbox)

    @pytest.mark.asyncio
    async def test_test_flow_requires_steps(self):
        result = await self.tool.execute(action="test_flow")
        assert not result.success
        assert "steps" in result.error.lower()

    @pytest.mark.asyncio
    async def test_test_flow_no_browser(self):
        with patch.object(self.tool, "_ensure_browser", return_value=False):
            result = await self.tool.execute(
                action="test_flow",
                steps=[{"action": "navigate", "url": "http://localhost:8080"}],
            )
        assert not result.success
        assert "Playwright" in result.error

    @pytest.mark.asyncio
    async def test_test_flow_json_string_steps(self):
        """LLM may send steps as a JSON string instead of a list."""
        with patch.object(self.tool, "_ensure_browser", return_value=False):
            result = await self.tool.execute(
                action="test_flow",
                steps='[{"action": "navigate", "url": "http://localhost:8080"}]',
            )
        assert not result.success
        assert "Playwright" in result.error

    @pytest.mark.asyncio
    async def test_test_flow_invalid_json_string(self):
        result = await self.tool.execute(action="test_flow", steps="not json")
        assert not result.success
        assert "Invalid" in result.error

    @pytest.mark.asyncio
    async def test_test_flow_with_mock_browser(self):
        """Test flow execution with mocked browser."""
        mock_page = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.click = AsyncMock()
        mock_page.fill = AsyncMock()
        mock_page.screenshot = AsyncMock()

        self.tool._page = mock_page
        self.tool._browser = MagicMock()

        steps = [
            {"action": "navigate", "url": "http://localhost:8080", "description": "Open app"},
            {"action": "click", "selector": "#login-btn", "description": "Click login"},
            {
                "action": "fill",
                "selector": "#username",
                "value": "admin",
                "description": "Enter username",
            },
            {"action": "wait", "value": "500", "description": "Wait for animation"},
        ]

        result = await self.tool.execute(action="test_flow", steps=steps)
        assert result.success
        assert "Open app" in result.output
        assert "Click login" in result.output
        assert "Enter username" in result.output
        assert "Waited 500ms" in result.output

    @pytest.mark.asyncio
    async def test_test_flow_step_failure(self):
        """Step failures should be recorded but not crash the flow."""
        mock_page = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.click = AsyncMock(side_effect=Exception("Element not found"))
        mock_page.screenshot = AsyncMock()

        self.tool._page = mock_page
        self.tool._browser = MagicMock()

        steps = [
            {"action": "navigate", "url": "http://localhost:8080"},
            {"action": "click", "selector": "#missing"},
        ]

        result = await self.tool.execute(action="test_flow", steps=steps)
        assert result.success
        assert "FAIL" in result.output
        assert len(self.tool._findings) > 0


class TestGenerateReport:
    """Tests for the generate_report action."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.workspace = tmp_path / "workspace"
        self.workspace.mkdir()
        self.sandbox = MagicMock()
        self.sandbox.workspace_path = self.workspace
        self.manager = AsyncMock()
        self.tool = AppTestTool(self.manager, self.sandbox)

    @pytest.mark.asyncio
    async def test_generate_report_no_findings(self):
        result = await self.tool.execute(action="generate_report")
        assert result.success
        assert "No findings" in result.output

    @pytest.mark.asyncio
    async def test_generate_report_with_findings(self):
        self.tool._findings = [
            Finding(category="health", severity="critical", message="App unreachable"),
            Finding(category="log", severity="error", message="DB connection failed"),
            Finding(category="visual", severity="warning", message="Layout shift"),
            Finding(category="flow", severity="info", message="All steps passed"),
        ]

        result = await self.tool.execute(action="generate_report")
        assert result.success
        assert "FAIL" in result.output  # Has critical/error findings
        assert "Critical: 1" in result.output
        assert "Errors: 1" in result.output
        assert "Warnings: 1" in result.output
        assert "Info: 1" in result.output

    @pytest.mark.asyncio
    async def test_generate_report_pass_status(self):
        """Report with only info findings should be PASS."""
        self.tool._findings = [
            Finding(category="flow", severity="info", message="Step completed"),
        ]

        result = await self.tool.execute(action="generate_report")
        assert "PASS" in result.output

    @pytest.mark.asyncio
    async def test_generate_report_warning_status(self):
        """Report with warnings but no errors should be WARNING."""
        self.tool._findings = [
            Finding(category="visual", severity="warning", message="Minor issue"),
        ]

        result = await self.tool.execute(action="generate_report")
        assert "WARNING" in result.output

    @pytest.mark.asyncio
    async def test_generate_report_clears_findings(self):
        self.tool._findings = [
            Finding(category="health", severity="error", message="Test"),
        ]

        await self.tool.execute(action="generate_report")
        assert len(self.tool._findings) == 0


class TestFinding:
    """Tests for the Finding dataclass."""

    def test_to_dict_minimal(self):
        f = Finding(category="health", severity="error", message="Test error")
        d = f.to_dict()
        assert d["category"] == "health"
        assert d["severity"] == "error"
        assert d["message"] == "Test error"
        assert "details" not in d
        assert "screenshot_path" not in d

    def test_to_dict_full(self):
        f = Finding(
            category="visual",
            severity="warning",
            message="Layout issue",
            details="Header misaligned",
            screenshot_path="/tmp/screenshot.png",
        )
        d = f.to_dict()
        assert d["details"] == "Header misaligned"
        assert d["screenshot_path"] == "/tmp/screenshot.png"


class TestErrorPatterns:
    """Tests for log error pattern matching."""

    def test_detects_error(self):
        assert any(p.search("ERROR: something failed") for p in _ERROR_PATTERNS)

    def test_detects_traceback(self):
        assert any(p.search("Traceback (most recent call last):") for p in _ERROR_PATTERNS)

    def test_detects_5xx(self):
        assert any(p.search("HTTP 502 Bad Gateway") for p in _ERROR_PATTERNS)

    def test_detects_warning(self):
        assert any(p.search("WARNING: deprecated API") for p in _ERROR_PATTERNS)

    def test_detects_unhandled_rejection(self):
        assert any(p.search("UnhandledPromiseRejection: TypeError") for p in _ERROR_PATTERNS)

    def test_ignores_clean_info(self):
        line = "INFO: Server started on port 8080"
        # Should not match any error pattern
        assert not any(p.search(line) for p in _ERROR_PATTERNS)


class TestGetAppUrl:
    """Tests for the _get_app_url helper."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.sandbox = MagicMock()
        self.sandbox.workspace_path = tmp_path
        self.manager = AsyncMock()
        self.tool = AppTestTool(self.manager, self.sandbox)

    @pytest.mark.asyncio
    async def test_app_not_found(self):
        self.manager.get_status = AsyncMock(return_value=None)
        url, msg = await self.tool._get_app_url("nonexistent")
        assert url == ""
        assert "not found" in msg.lower()

    @pytest.mark.asyncio
    async def test_app_not_running(self):
        self.manager.get_status = AsyncMock(return_value={"status": "stopped"})
        url, msg = await self.tool._get_app_url("test-app")
        assert url == ""
        assert "not running" in msg.lower()

    @pytest.mark.asyncio
    async def test_app_no_port(self):
        self.manager.get_status = AsyncMock(return_value={"status": "running"})
        url, msg = await self.tool._get_app_url("test-app")
        assert url == ""
        assert "no port" in msg.lower()

    @pytest.mark.asyncio
    async def test_app_running(self):
        self.manager.get_status = AsyncMock(
            return_value={"status": "running", "port": 9100, "host": "127.0.0.1"}
        )
        url, msg = await self.tool._get_app_url("test-app")
        assert url == "http://127.0.0.1:9100"
        assert "running" in msg.lower()

    @pytest.mark.asyncio
    async def test_app_status_error(self):
        self.manager.get_status = AsyncMock(side_effect=Exception("DB error"))
        url, msg = await self.tool._get_app_url("test-app")
        assert url == ""
        assert "failed" in msg.lower()


class TestBrowserCleanup:
    """Tests for browser resource cleanup."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.sandbox = MagicMock()
        self.sandbox.workspace_path = tmp_path
        self.manager = AsyncMock()
        self.tool = AppTestTool(self.manager, self.sandbox)

    @pytest.mark.asyncio
    async def test_close_with_browser(self):
        mock_browser = AsyncMock()
        self.tool._browser = mock_browser
        self.tool._page = MagicMock()

        await self.tool.close()

        mock_browser.close.assert_called_once()
        assert self.tool._browser is None
        assert self.tool._page is None

    @pytest.mark.asyncio
    async def test_close_without_browser(self):
        """Close should be safe to call without a browser."""
        await self.tool.close()  # Should not raise

    @pytest.mark.asyncio
    async def test_close_browser_error(self):
        """Close should handle browser.close() errors gracefully."""
        mock_browser = AsyncMock()
        mock_browser.close = AsyncMock(side_effect=Exception("already closed"))
        self.tool._browser = mock_browser
        self.tool._page = MagicMock()

        await self.tool.close()  # Should not raise
        assert self.tool._browser is None
