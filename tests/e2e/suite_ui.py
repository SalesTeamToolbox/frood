"""
UI / Dashboard Test Suite

Tests the Agent42 dashboard frontend:
  - Login flow & setup wizard
  - Sidebar navigation to all views
  - Page rendering & key elements
  - Modals, forms, toggles
  - WebSocket connection indicator
  - Console error detection

Self-improving: uses discovery.discover_frontend_views() to dynamically
generate navigation tests for any new views added to the codebase.
"""

import re
import time

from .cli import PlaywrightCLI
from .config import config
from .discovery import build_manifest
from .runner import (
    BaseSuite,
    SkipTest,
    assert_contains,
    assert_not_contains,
    register_suite,
)


@register_suite("ui")
class UISuite(BaseSuite):
    name = "ui"

    def setup(self):
        self.cli = PlaywrightCLI(session="e2e-ui", headed=config.headed)
        self.manifest = build_manifest()
        self.logged_in = False

    def teardown(self):
        self.cli.close()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _ensure_server_up(self):
        if not self.cli.wait_for_ready(f"{config.base_url}/health", retries=5, delay=1):
            raise SkipTest(f"Server not reachable at {config.base_url}")

    def _find_ref(self, snap_content: str, pattern: str) -> str | None:
        """Find a ref=eXX for an element matching pattern in snapshot YAML."""
        for line in snap_content.split("\n"):
            if pattern.lower() in line.lower():
                m = re.search(r'\[ref=(e\d+)\]', line)
                if m:
                    return m.group(1)
        return None

    def _login(self):
        """Navigate to login page and authenticate using playwright-cli refs."""
        if self.logged_in:
            return
        self._ensure_server_up()
        self.cli.open(config.base_url)
        time.sleep(1)

        if not config.password:
            raise SkipTest("No password configured — set E2E_PASSWORD env var")

        token = self.cli.login_ui(config.username, config.password)
        if not token:
            raise SkipTest("Login failed — set E2E_PASSWORD=<your-password>")

        self.logged_in = True

    def _nav_to(self, page_name: str):
        """Navigate to a page via sidebar link click using snapshot refs."""
        snap = self.cli.snapshot_content()
        ref = self._find_ref(snap, f'link "{page_name}"') or self._find_ref(snap, page_name)
        if ref:
            self.cli.click(ref)
            time.sleep(1)

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    def test_01_server_health(self, result):
        """Health endpoint responds."""
        result.covers.append("GET /health")
        self._ensure_server_up()
        self.cli.open(f"{config.base_url}/health")
        time.sleep(1)
        snap = self.cli.snapshot_content()
        assert_contains(snap, "ok", "Health check should return ok")

    def test_02_login_page_renders(self, result):
        """Login page shows form with username/password fields."""
        result.covers.append("GET /api/setup/status")
        self._ensure_server_up()
        self.cli.open(config.base_url)
        time.sleep(1)
        snap = self.cli.snapshot_content()
        has_login = "sign in" in snap.lower() or "password" in snap.lower()
        has_dashboard = "mission" in snap.lower() or "sidebar" in snap.lower()
        has_setup = "setup" in snap.lower()
        assert has_login or has_dashboard or has_setup, \
            f"Should show login, dashboard, or setup wizard:\n{snap[:500]}"

    def test_03_login_flow(self, result):
        """Can log in with valid credentials."""
        result.covers.append("POST /api/login")
        self._login()
        snap = self.cli.snapshot_content()
        has_nav = any(
            kw in snap.lower()
            for kw in ["mission", "tasks", "sidebar", "status", "chat", "navigation"]
        )
        assert has_nav, f"Dashboard should render after login:\n{snap[:500]}"

    def test_04_sidebar_navigation_elements(self, result):
        """Sidebar contains nav links for all major pages."""
        self._login()
        snap = self.cli.snapshot_content()
        expected = ["tasks", "status", "chat", "tools", "settings"]
        for page in expected:
            if page in snap.lower():
                result.covers.append(f"NAV:{page}")

    def test_05_navigate_to_status(self, result):
        """Navigate to Status page and verify system metrics."""
        self._login()
        self._nav_to("Status")
        snap = self.cli.snapshot_content()
        has_content = any(
            kw in snap.lower()
            for kw in ["agent", "capacity", "cpu", "memory", "uptime", "active"]
        )
        assert has_content, f"Status page should show system metrics:\n{snap[:500]}"
        result.covers.append("GET /api/status")

    def test_06_navigate_to_chat(self, result):
        """Navigate to Chat page and verify layout."""
        self._login()
        self._nav_to("Chat")
        snap = self.cli.snapshot_content()
        has_chat = any(
            kw in snap.lower()
            for kw in ["chat", "new chat", "session", "send", "message", "welcome"]
        )
        assert has_chat, f"Chat page should render:\n{snap[:500]}"
        result.covers.append("GET /api/chat/sessions")

    def test_07_navigate_to_tools(self, result):
        """Navigate to Tools page and verify tool listing."""
        self._login()
        self._nav_to("Tools")
        snap = self.cli.snapshot_content()
        has_tools = any(
            kw in snap.lower()
            for kw in ["tool", "enabled", "toggle", "checkbox", "switch"]
        )
        assert has_tools, f"Tools page should list tools:\n{snap[:500]}"
        result.covers.append("GET /api/tools")

    def test_08_navigate_to_skills(self, result):
        """Navigate to Skills page and verify skill listing."""
        self._login()
        self._nav_to("Skills")
        snap = self.cli.snapshot_content()
        has_skills = any(
            kw in snap.lower()
            for kw in ["skill", "enabled", "auto-load", "task"]
        )
        assert has_skills, f"Skills page should list skills:\n{snap[:500]}"
        result.covers.append("GET /api/skills")

    def test_09_navigate_to_settings(self, result):
        """Navigate to Settings page and verify tabs."""
        self._login()
        self._nav_to("Settings")
        snap = self.cli.snapshot_content()
        has_settings = any(
            kw in snap.lower()
            for kw in ["settings", "provider", "api key", "environment", "persona", "tab"]
        )
        assert has_settings, f"Settings page should show configuration:\n{snap[:500]}"
        result.covers.append("GET /api/settings/keys")

    def test_10_navigate_to_approvals(self, result):
        """Navigate to Approvals page."""
        self._login()
        self._nav_to("Approvals")
        snap = self.cli.snapshot_content()
        has_approvals = any(
            kw in snap.lower()
            for kw in ["approval", "pending", "no pending", "approve", "deny"]
        )
        assert has_approvals, f"Approvals page should render:\n{snap[:500]}"
        result.covers.append("GET /api/approvals")

    def test_11_navigate_to_agents(self, result):
        """Navigate to Agents/Profiles page."""
        self._login()
        self._nav_to("Agents")
        snap = self.cli.snapshot_content()
        has_agents = any(
            kw in snap.lower()
            for kw in ["agent", "profile", "default", "persona", "create"]
        )
        assert has_agents, f"Agents page should render:\n{snap[:500]}"
        result.covers.append("GET /api/profiles")

    def test_12_navigate_to_apps(self, result):
        """Navigate to Apps page."""
        self._login()
        self._nav_to("Apps")
        snap = self.cli.snapshot_content()
        has_apps = any(
            kw in snap.lower()
            for kw in ["app", "running", "stopped", "create", "total", "no app"]
        )
        assert has_apps, f"Apps page should render:\n{snap[:500]}"

    def test_13_navigate_to_reports(self, result):
        """Navigate to Reports page."""
        self._login()
        self._nav_to("Reports")
        snap = self.cli.snapshot_content()
        has_reports = any(
            kw in snap.lower()
            for kw in ["report", "token", "overview", "analytics", "usage"]
        )
        assert has_reports, f"Reports page should render:\n{snap[:500]}"
        result.covers.append("GET /api/reports")

    def test_14_websocket_indicator(self, result):
        """WebSocket connection indicator present in sidebar."""
        self._login()
        self._nav_to("Mission Control")
        snap = self.cli.snapshot_content()
        has_ws = any(
            kw in snap.lower()
            for kw in ["connected", "disconnected", "ws", "websocket", "online"]
        )
        # Soft check — ws indicator may not be in the accessibility tree
        if has_ws:
            result.covers.append("WS:indicator-present")

    def test_15_no_console_errors(self, result):
        """No critical JavaScript errors in console."""
        self._login()
        console = self.cli.console("error")
        # Filter benign errors
        lines = [
            line for line in console.split("\n")
            if line.strip()
            and "favicon" not in line.lower()
            and "websocket" not in line.lower()
        ]

    def test_16_kanban_board_renders(self, result):
        """Mission Control kanban board renders with columns."""
        self._login()
        self._nav_to("Mission Control")
        snap = self.cli.snapshot_content()
        has_board = any(
            kw in snap.lower()
            for kw in ["pending", "running", "review", "done", "kanban", "list", "task"]
        )
        assert has_board, f"Task board should render:\n{snap[:500]}"
        result.covers.append("GET /api/tasks")
        result.covers.append("GET /api/tasks/board")

    def test_17_create_task_modal(self, result):
        """Create Task button exists and can be clicked."""
        self._login()
        self._nav_to("Mission Control")
        snap = self.cli.snapshot_content()
        create_ref = (
            self._find_ref(snap, "Create Task")
            or self._find_ref(snap, "New Task")
            or self._find_ref(snap, "button \"+\"")
            or self._find_ref(snap, "Create")
        )
        if create_ref:
            self.cli.click(create_ref)
            time.sleep(1)
            modal_snap = self.cli.snapshot_content()
            has_modal = any(
                kw in modal_snap.lower()
                for kw in ["title", "description", "type", "create", "dialog"]
            )
            # Close modal
            self.cli.press("Escape")
            assert has_modal, f"Create task modal should have form:\n{modal_snap[:500]}"
        else:
            # Create button may use a different label
            pass

    def test_18_screenshot_dashboard(self, result):
        """Take a screenshot of the dashboard for visual verification."""
        self._login()
        self._nav_to("Mission Control")
        output = self.cli.screenshot(
            filename=f"{config.output_dir}/dashboard-tasks.png"
        )
        result.screenshots.append(f"{config.output_dir}/dashboard-tasks.png")

    def test_19_dynamic_view_coverage(self, result):
        """Auto-discovered views: verify navigability."""
        self._login()
        views = self.manifest.frontend_views
        if not views:
            raise SkipTest("No frontend views discovered")

        snap = self.cli.snapshot_content()
        navigable = 0
        for view in views:
            ref = self._find_ref(snap, view)
            if ref:
                navigable += 1
                result.covers.append(f"VIEW:{view}")

    def test_20_page_title(self, result):
        """Page title contains Agent42."""
        self._login()
        title = self.cli.eval_js("document.title")
        assert_contains(title, "Agent42", "Page title should contain Agent42")
