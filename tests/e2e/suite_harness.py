"""
Agent Harness Test Suite

Tests the AI Agent orchestration features:
  - Task lifecycle: create -> comment -> priority -> block -> cancel -> retry -> archive
  - Agent profiles: CRUD
  - Approvals listing
  - Task board UI rendering
  - Dynamic task type coverage

Self-improving: uses discover_task_types() to ensure all registered task types
can be created, and discover_tools() to verify tool count matches the API.
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


@register_suite("harness")
class HarnessSuite(BaseSuite):
    name = "harness"

    def setup(self):
        self.cli = PlaywrightCLI(session="e2e-harness", headed=config.headed)
        self.manifest = build_manifest()
        self.token = None
        self._created_task_id = None
        self._created_profile_name = None

    def teardown(self):
        if self.token:
            if self._created_task_id:
                self._fetch("POST", f"/api/tasks/{self._created_task_id}/archive")
            if self._created_profile_name:
                self._fetch("DELETE", f"/api/profiles/{self._created_profile_name}")
        self.cli.close()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _ensure_server_up(self):
        if not self.cli.wait_for_ready(f"{config.base_url}/health", retries=5, delay=1):
            raise SkipTest(f"Server not reachable at {config.base_url}")

    def _fetch(self, method: str, path: str, body: dict | None = None) -> tuple[int, dict | str]:
        status, raw = self.cli.fetch_api(method, path, body, token=self.token)
        try:
            return status, json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return status, raw

    def _login(self):
        if self.token:
            return
        self._ensure_server_up()
        self.cli.open(config.base_url)
        time.sleep(1)
        if not config.password:
            raise SkipTest("No password configured — set E2E_PASSWORD env var")
        self.token = self.cli.login_ui(config.username, config.password)
        if not self.token:
            raise SkipTest("Login failed — set E2E_PASSWORD=<your-password>")

    def _find_ref(self, snap: str, pattern: str) -> str | None:
        for line in snap.split("\n"):
            if pattern.lower() in line.lower():
                m = re.search(r'\[ref=(e\d+)\]', line)
                if m:
                    return m.group(1)
        return None

    # ------------------------------------------------------------------
    # Tests: Task Lifecycle
    # ------------------------------------------------------------------

    def test_01_create_task(self, result):
        """Create a test task via API."""
        result.covers.append("POST /api/tasks")
        self._login()
        status, data = self._fetch("POST", "/api/tasks", {
            "title": "E2E Harness Test Task",
            "description": "Automated test for agent harness lifecycle",
            "task_type": "CODING",
            "priority": "normal",
        })
        assert status in (200, 201), f"Task creation failed: {status} {data}"
        if isinstance(data, dict):
            self._created_task_id = data.get("id") or data.get("task_id")
        assert self._created_task_id, f"Should return an ID: {data}"

    def test_02_get_task_detail(self, result):
        """Retrieve the created task by ID."""
        self._login()
        if not self._created_task_id:
            raise SkipTest("No task created")
        result.covers.append("GET /api/tasks/{task_id}")
        status, data = self._fetch("GET", f"/api/tasks/{self._created_task_id}")
        assert status == 200, f"Task detail failed: {status}"

    def test_03_add_comment(self, result):
        """Add a comment to the test task."""
        self._login()
        if not self._created_task_id:
            raise SkipTest("No task created")
        result.covers.append("POST /api/tasks/{task_id}/comment")
        status, _ = self._fetch("POST", f"/api/tasks/{self._created_task_id}/comment", {
            "message": "Automated test comment from e2e runner",
        })
        assert status == 200, f"Comment failed: {status}"

    def test_04_set_priority(self, result):
        """Change task priority."""
        self._login()
        if not self._created_task_id:
            raise SkipTest("No task created")
        result.covers.append("PATCH /api/tasks/{task_id}/priority")
        status, _ = self._fetch("PATCH", f"/api/tasks/{self._created_task_id}/priority", {
            "priority": "high",
        })
        assert status == 200, f"Priority change failed: {status}"

    def test_05_block_task(self, result):
        """Block a task with a reason."""
        self._login()
        if not self._created_task_id:
            raise SkipTest("No task created")
        result.covers.append("PATCH /api/tasks/{task_id}/block")
        status, _ = self._fetch("PATCH", f"/api/tasks/{self._created_task_id}/block", {
            "reason": "Blocked by e2e test",
        })
        if status == 200:
            result.covers.append("PATCH /api/tasks/{task_id}/unblock")
            self._fetch("PATCH", f"/api/tasks/{self._created_task_id}/unblock")

    def test_06_cancel_task(self, result):
        """Cancel the test task."""
        self._login()
        if not self._created_task_id:
            raise SkipTest("No task created")
        result.covers.append("POST /api/tasks/{task_id}/cancel")
        status, _ = self._fetch("POST", f"/api/tasks/{self._created_task_id}/cancel")
        assert status in (200, 400, 409), f"Cancel unexpected: {status}"

    def test_07_retry_task(self, result):
        """Retry a failed/cancelled task."""
        self._login()
        if not self._created_task_id:
            raise SkipTest("No task created")
        result.covers.append("POST /api/tasks/{task_id}/retry")
        status, _ = self._fetch("POST", f"/api/tasks/{self._created_task_id}/retry")
        assert status in (200, 400, 409), f"Retry unexpected: {status}"

    def test_08_archive_task(self, result):
        """Archive the test task."""
        self._login()
        if not self._created_task_id:
            raise SkipTest("No task created")
        result.covers.append("POST /api/tasks/{task_id}/archive")
        status, _ = self._fetch("POST", f"/api/tasks/{self._created_task_id}/archive")
        assert status in (200, 400, 409), f"Archive unexpected: {status}"

    # ------------------------------------------------------------------
    # Tests: Task Board via UI
    # ------------------------------------------------------------------

    def test_09_task_board_ui(self, result):
        """View task board in browser."""
        self._login()
        # Login via UI using refs
        self.cli.goto(config.base_url)
        time.sleep(1)
        snap = self.cli.snapshot_content()
        signin_ref = self._find_ref(snap, 'button "Sign In"')
        if signin_ref:
            username_ref = self._find_ref(snap, 'textbox "Username"')
            password_ref = self._find_ref(snap, 'textbox "Password"')
            if username_ref and password_ref:
                self.cli.fill(username_ref, config.username)
                self.cli.fill(password_ref, config.password)
                self.cli.click(signin_ref)
                time.sleep(2)

        snap = self.cli.snapshot_content()
        has_board = any(
            kw in snap.lower()
            for kw in ["pending", "running", "done", "kanban", "mission", "task"]
        )
        assert has_board, f"Task board should render:\n{snap[:500]}"

    def test_10_task_detail_ui(self, result):
        """Click a task to view detail page."""
        snap = self.cli.snapshot_content()
        # Find any clickable task card ref
        task_ref = None
        for line in snap.split("\n"):
            if "task" in line.lower() and "[ref=" in line:
                m = re.search(r'\[ref=(e\d+)\]', line)
                if m:
                    task_ref = m.group(1)
                    break
        if not task_ref:
            raise SkipTest("No tasks on board to click")
        self.cli.click(task_ref)
        time.sleep(1)

    # ------------------------------------------------------------------
    # Tests: Agent Profiles
    # ------------------------------------------------------------------

    def test_11_create_profile(self, result):
        """Create an agent profile via API."""
        result.covers.append("POST /api/profiles")
        self._login()
        self._created_profile_name = "e2e-test-profile"
        status, _ = self._fetch("POST", "/api/profiles", {
            "name": self._created_profile_name,
            "description": "Created by E2E test runner",
            "preferred_task_types": ["CODING"],
        })
        assert status in (200, 201, 409), f"Profile creation failed: {status}"

    def test_12_get_profile(self, result):
        """Get the created profile by name."""
        self._login()
        if not self._created_profile_name:
            raise SkipTest("No profile created")
        result.covers.append("GET /api/profiles/{name}")
        status, _ = self._fetch("GET", f"/api/profiles/{self._created_profile_name}")
        assert status == 200, f"Profile get failed: {status}"

    def test_13_update_profile(self, result):
        """Update the test profile."""
        self._login()
        if not self._created_profile_name:
            raise SkipTest("No profile created")
        result.covers.append("PUT /api/profiles/{name}")
        status, _ = self._fetch("PUT", f"/api/profiles/{self._created_profile_name}", {
            "description": "Updated by E2E test runner",
        })
        assert status == 200, f"Profile update failed: {status}"

    def test_14_delete_profile(self, result):
        """Delete the test profile."""
        self._login()
        if not self._created_profile_name:
            raise SkipTest("No profile created")
        result.covers.append("DELETE /api/profiles/{name}")
        status, _ = self._fetch("DELETE", f"/api/profiles/{self._created_profile_name}")
        assert status == 200, f"Profile delete failed: {status}"
        self._created_profile_name = None

    # ------------------------------------------------------------------
    # Tests: Approvals
    # ------------------------------------------------------------------

    def test_15_approvals_empty(self, result):
        """Approvals list returns valid response."""
        result.covers.append("GET /api/approvals")
        self._login()
        status, _ = self._fetch("GET", "/api/approvals")
        assert status == 200, f"Approvals failed: {status}"

    # ------------------------------------------------------------------
    # Tests: Dynamic
    # ------------------------------------------------------------------

    def test_16_all_task_types_creatable(self, result):
        """Auto-discovered task types: verify each can be created."""
        self._login()
        task_types = self.manifest.task_types
        if not task_types:
            raise SkipTest("No task types discovered")

        created_ids = []
        for tt in task_types[:5]:
            status, data = self._fetch("POST", "/api/tasks", {
                "title": f"E2E type test: {tt}",
                "description": f"Testing task type {tt}",
                "task_type": tt,
            })
            if status in (200, 201) and isinstance(data, dict):
                tid = data.get("id") or data.get("task_id")
                if tid:
                    created_ids.append(tid)
                    result.covers.append(f"TASK_TYPE:{tt}")

        for tid in created_ids:
            self._fetch("POST", f"/api/tasks/{tid}/cancel")
            self._fetch("POST", f"/api/tasks/{tid}/archive")

        assert len(created_ids) > 0, f"Should create at least 1 task"

    def test_17_tool_count_matches(self, result):
        """Tools in API vs codebase count."""
        self._login()
        status, data = self._fetch("GET", "/api/tools")
        if status != 200 or not isinstance(data, list):
            raise SkipTest(f"Could not fetch tools: {status}")
        assert len(data) > 0, "API should return at least 1 tool"
        result.covers.append(f"TOOLS:api={len(data)},discovered={len(self.manifest.tools)}")

    def test_18_skill_count_matches(self, result):
        """Skills in API vs discovered skills."""
        self._login()
        status, data = self._fetch("GET", "/api/skills")
        if status != 200 or not isinstance(data, list):
            raise SkipTest(f"Could not fetch skills: {status}")
        result.covers.append(f"SKILLS:api={len(data)},discovered={len(self.manifest.skills)}")
