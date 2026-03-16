"""
API / Backend Test Suite

Tests Agent42 API endpoints via browser fetch():
  - Auth: login, logout, JWT persistence
  - Tasks CRUD: create, list, detail, status transitions
  - Profiles, Settings, Approvals, Chat
  - Network request inspection

Self-improving: uses discovery.discover_endpoints() to detect new endpoints
and auto-tests any new GET routes not explicitly covered.
"""

import json
import re
import time

from .cli import PlaywrightCLI
from .config import config
from .discovery import build_manifest
from .runner import (
    BaseSuite,
    SkipTest,
    assert_contains,
    register_suite,
)


@register_suite("api")
class APISuite(BaseSuite):
    name = "api"

    def setup(self):
        self.cli = PlaywrightCLI(session="e2e-api", headed=config.headed)
        self.manifest = build_manifest()
        self.token = None

    def teardown(self):
        self.cli.close()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _ensure_server_up(self):
        if not self.cli.wait_for_ready(f"{config.base_url}/health", retries=5, delay=1):
            raise SkipTest(f"Server not reachable at {config.base_url}")

    def _open_browser(self):
        """Ensure browser is open on the target."""
        self._ensure_server_up()
        self.cli.open(config.base_url)
        time.sleep(1)

    def _fetch(self, method: str, path: str, body: dict | None = None) -> tuple[int, str]:
        """Fetch via browser context."""
        return self.cli.fetch_api(method, path, body, token=self.token)

    def _login(self):
        if self.token:
            return
        self._open_browser()
        if not config.password:
            raise SkipTest("No password configured — set E2E_PASSWORD env var")
        self.token = self.cli.login_ui(config.username, config.password)
        if not self.token:
            raise SkipTest(
                "Login failed — password may not match DASHBOARD_PASSWORD_HASH. "
                "Set E2E_PASSWORD=<your-password> to enable authenticated tests."
            )

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    def test_01_health_public(self, result):
        """GET /health returns 200 without auth."""
        result.covers.append("GET /health")
        self._open_browser()
        status, body = self._fetch("GET", "/health")
        assert status == 200, f"Health should return 200, got {status}"
        assert_contains(body, "ok", "Health should contain ok")

    def test_02_setup_status(self, result):
        """GET /api/setup/status returns setup state."""
        result.covers.append("GET /api/setup/status")
        status, body = self._fetch("GET", "/api/setup/status")
        assert status == 200, f"Setup status should return 200, got {status}"

    def test_03_login(self, result):
        """Login via UI and obtain JWT token."""
        result.covers.append("POST /api/login")
        self._login()
        assert self.token, "Login should produce a JWT token"

    def test_04_authenticated_health(self, result):
        """GET /api/health requires auth and returns detailed info."""
        result.covers.append("GET /api/health")
        self._login()
        status, body = self._fetch("GET", "/api/health")
        assert status == 200, f"Authenticated health should return 200, got {status}"

    def test_05_unauthenticated_rejected(self, result):
        """API endpoints reject requests without token."""
        self._open_browser()
        status, body = self.cli.fetch_api("GET", "/api/tasks", token=None)
        assert status == 401, f"Tasks should require auth, got {status}"

    def test_06_list_tasks(self, result):
        """GET /api/tasks returns task list."""
        result.covers.append("GET /api/tasks")
        self._login()
        status, body = self._fetch("GET", "/api/tasks")
        assert status == 200, f"Tasks should return 200, got {status}"

    def test_07_create_task(self, result):
        """POST /api/tasks creates a new task."""
        result.covers.append("POST /api/tasks")
        self._login()
        status, body = self._fetch("POST", "/api/tasks", {
            "title": "E2E API Test Task",
            "description": "Created by e2e test runner",
            "task_type": "CODING",
            "priority": "normal",
        })
        assert status in (200, 201), f"Task creation should succeed: {status} {body[:200]}"

    def test_08_get_task_board(self, result):
        """GET /api/tasks/board returns kanban board data."""
        result.covers.append("GET /api/tasks/board")
        self._login()
        status, body = self._fetch("GET", "/api/tasks/board")
        assert status == 200, f"Task board should return 200, got {status}"

    def test_09_list_profiles(self, result):
        """GET /api/profiles returns agent profiles."""
        result.covers.append("GET /api/profiles")
        self._login()
        status, body = self._fetch("GET", "/api/profiles")
        assert status == 200, f"Profiles should return 200, got {status}"

    def test_10_list_tools(self, result):
        """GET /api/tools returns registered tools."""
        result.covers.append("GET /api/tools")
        self._login()
        status, body = self._fetch("GET", "/api/tools")
        assert status == 200, f"Tools should return 200, got {status}"

    def test_11_list_skills(self, result):
        """GET /api/skills returns loaded skills."""
        result.covers.append("GET /api/skills")
        self._login()
        status, body = self._fetch("GET", "/api/skills")
        assert status == 200, f"Skills should return 200, got {status}"

    def test_12_list_providers(self, result):
        """GET /api/providers returns LLM provider configs."""
        result.covers.append("GET /api/providers")
        self._login()
        status, body = self._fetch("GET", "/api/providers")
        assert status == 200, f"Providers should return 200, got {status}"

    def test_13_get_settings_keys(self, result):
        """GET /api/settings/keys returns API key config."""
        result.covers.append("GET /api/settings/keys")
        self._login()
        status, body = self._fetch("GET", "/api/settings/keys")
        assert status == 200, f"Settings keys should return 200, got {status}"

    def test_14_get_settings_env(self, result):
        """GET /api/settings/env returns environment variables."""
        result.covers.append("GET /api/settings/env")
        self._login()
        status, body = self._fetch("GET", "/api/settings/env")
        assert status == 200, f"Settings env should return 200, got {status}"

    def test_15_get_status(self, result):
        """GET /api/status returns system status."""
        result.covers.append("GET /api/status")
        self._login()
        status, body = self._fetch("GET", "/api/status")
        assert status == 200, f"Status should return 200, got {status}"

    def test_16_get_activity(self, result):
        """GET /api/activity returns activity feed."""
        result.covers.append("GET /api/activity")
        self._login()
        status, body = self._fetch("GET", "/api/activity")
        assert status == 200, f"Activity should return 200, got {status}"

    def test_17_get_token_stats(self, result):
        """GET /api/stats/tokens returns token usage."""
        result.covers.append("GET /api/stats/tokens")
        self._login()
        status, body = self._fetch("GET", "/api/stats/tokens")
        assert status == 200, f"Token stats should return 200, got {status}"

    def test_18_get_reports(self, result):
        """GET /api/reports returns report data."""
        result.covers.append("GET /api/reports")
        self._login()
        status, body = self._fetch("GET", "/api/reports")
        assert status == 200, f"Reports should return 200, got {status}"

    def test_19_get_approvals(self, result):
        """GET /api/approvals returns pending approvals."""
        result.covers.append("GET /api/approvals")
        self._login()
        status, body = self._fetch("GET", "/api/approvals")
        assert status == 200, f"Approvals should return 200, got {status}"

    def test_20_chat_sessions(self, result):
        """GET /api/chat/sessions returns chat sessions."""
        result.covers.append("GET /api/chat/sessions")
        self._login()
        status, body = self._fetch("GET", "/api/chat/sessions")
        assert status == 200, f"Chat sessions should return 200, got {status}"

    def test_21_get_persona(self, result):
        """GET /api/persona returns custom persona."""
        result.covers.append("GET /api/persona")
        self._login()
        status, body = self._fetch("GET", "/api/persona")
        assert status == 200, f"Persona should return 200, got {status}"

    def test_22_get_channels(self, result):
        """GET /api/channels returns channel configs."""
        result.covers.append("GET /api/channels")
        self._login()
        status, body = self._fetch("GET", "/api/channels")
        assert status in range(200, 500), f"Channels should return valid HTTP status: {status}"

    def test_23_get_devices(self, result):
        """GET /api/devices returns device list."""
        result.covers.append("GET /api/devices")
        self._login()
        status, body = self._fetch("GET", "/api/devices")
        assert status == 200, f"Devices should return 200, got {status}"

    def test_24_models_health(self, result):
        """GET /api/models/health returns model status."""
        result.covers.append("GET /api/models/health")
        self._login()
        status, body = self._fetch("GET", "/api/models/health")
        assert status == 200, f"Models health should return 200, got {status}"

    def test_25_openrouter_status(self, result):
        """GET /api/settings/openrouter-status returns status."""
        result.covers.append("GET /api/settings/openrouter-status")
        self._login()
        status, body = self._fetch("GET", "/api/settings/openrouter-status")
        assert status in range(200, 500), f"OpenRouter should return valid status: {status}"

    def test_26_storage_status(self, result):
        """GET /api/settings/storage returns storage backend info."""
        result.covers.append("GET /api/settings/storage")
        self._login()
        status, body = self._fetch("GET", "/api/settings/storage")
        assert status == 200, f"Storage should return 200, got {status}"

    def test_27_rlm_status(self, result):
        """GET /api/settings/rlm-status returns RLM status."""
        result.covers.append("GET /api/settings/rlm-status")
        self._login()
        status, body = self._fetch("GET", "/api/settings/rlm-status")
        assert status in range(200, 500), f"RLM should return valid status: {status}"

    def test_28_logout(self, result):
        """POST /api/logout clears session."""
        result.covers.append("POST /api/logout")
        self._login()
        status, body = self._fetch("POST", "/api/logout")
        assert status == 200, f"Logout should return 200, got {status}"

    def test_29_network_requests(self, result):
        """Inspect network requests made during page load."""
        self._login()
        self.cli.goto(config.base_url)
        time.sleep(2)
        network = self.cli.network()
        if "/api/" in network:
            result.covers.append("NETWORK:api-calls-observed")

    def test_30_dynamic_endpoint_coverage(self, result):
        """Auto-test new GET endpoints not explicitly tested above."""
        self._login()
        tested = {
            "/health", "/api/health", "/api/setup/status", "/api/tasks",
            "/api/tasks/board", "/api/profiles", "/api/tools", "/api/skills",
            "/api/providers", "/api/settings/keys", "/api/settings/env",
            "/api/status", "/api/activity", "/api/stats/tokens", "/api/reports",
            "/api/approvals", "/api/chat/sessions", "/api/persona",
            "/api/channels", "/api/devices", "/api/models/health",
            "/api/settings/openrouter-status", "/api/settings/storage",
            "/api/settings/rlm-status",
        }
        new = [
            e for e in self.manifest.endpoints
            if e.method == "GET" and e.path not in tested and "{" not in e.path
        ]
        if not new:
            raise SkipTest("No new GET endpoints beyond explicit tests")

        for ep in new[:10]:
            status, _ = self._fetch("GET", ep.path)
            if 200 <= status < 500:
                result.covers.append(f"{ep.method} {ep.path}")
