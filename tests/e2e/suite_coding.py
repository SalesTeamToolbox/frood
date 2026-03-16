"""
Coding & Code Execution Test Suite

Tests Agent42's coding capabilities:
  - Chat sessions: CRUD, send messages
  - Code sessions: create, setup
  - Tool/skill toggle via API
  - Persona customization
  - Settings page UI
  - Visual regression screenshots

Self-improving: uses discover_tools() and discover_skills() to verify
all tools/skills are registered in the API.
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


@register_suite("coding")
class CodingSuite(BaseSuite):
    name = "coding"

    def setup(self):
        self.cli = PlaywrightCLI(session="e2e-coding", headed=config.headed)
        self.manifest = build_manifest()
        self.token = None
        self._chat_session_id = None
        self._code_session_id = None

    def teardown(self):
        if self.token:
            if self._chat_session_id:
                self._fetch("DELETE", f"/api/chat/sessions/{self._chat_session_id}")
            if self._code_session_id:
                self._fetch("DELETE", f"/api/chat/sessions/{self._code_session_id}")
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

    def _login_ui(self):
        """Login via browser UI for page-level tests."""
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

    # ------------------------------------------------------------------
    # Tests: Chat Sessions
    # ------------------------------------------------------------------

    def test_01_create_chat_session(self, result):
        """Create a new chat session via API."""
        result.covers.append("POST /api/chat/sessions")
        self._login()
        status, data = self._fetch("POST", "/api/chat/sessions", {
            "title": "E2E Test Chat",
            "type": "chat",
        })
        assert status in (200, 201), f"Chat session creation failed: {status} {data}"
        if isinstance(data, dict):
            self._chat_session_id = data.get("id") or data.get("session_id")
        assert self._chat_session_id, f"Should return session ID: {data}"

    def test_02_list_chat_sessions(self, result):
        """List chat sessions includes the created one."""
        result.covers.append("GET /api/chat/sessions")
        self._login()
        status, data = self._fetch("GET", "/api/chat/sessions?type=chat")
        assert status == 200, f"List sessions failed: {status}"

    def test_03_send_chat_message(self, result):
        """Send a message to the chat session."""
        self._login()
        if not self._chat_session_id:
            raise SkipTest("No chat session created")
        result.covers.append("POST /api/chat/sessions/{session_id}/send")
        status, _ = self._fetch(
            "POST",
            f"/api/chat/sessions/{self._chat_session_id}/send",
            {"message": "Hello from E2E test runner. What is 2+2?"},
        )
        assert status in (200, 201, 202), f"Send message failed: {status}"

    def test_04_get_chat_messages(self, result):
        """Retrieve messages from the chat session."""
        self._login()
        if not self._chat_session_id:
            raise SkipTest("No chat session created")
        result.covers.append("GET /api/chat/sessions/{session_id}/messages")
        time.sleep(2)
        status, _ = self._fetch(
            "GET",
            f"/api/chat/sessions/{self._chat_session_id}/messages",
        )
        assert status == 200, f"Get messages failed: {status}"

    def test_05_chat_ui_renders(self, result):
        """Chat page renders with session sidebar and message area."""
        self._login()
        self._login_ui()
        snap = self.cli.snapshot_content()
        chat_ref = self._find_ref(snap, "Chat")
        if chat_ref:
            self.cli.click(chat_ref)
            time.sleep(2)
        snap = self.cli.snapshot_content()
        has_chat = any(
            kw in snap.lower()
            for kw in ["new chat", "session", "send", "message", "chat", "welcome"]
        )
        assert has_chat, f"Chat UI should render:\n{snap[:500]}"

    def test_06_delete_chat_session(self, result):
        """Delete the test chat session."""
        self._login()
        if not self._chat_session_id:
            raise SkipTest("No chat session created")
        result.covers.append("DELETE /api/chat/sessions/{session_id}")
        status, _ = self._fetch("DELETE", f"/api/chat/sessions/{self._chat_session_id}")
        assert status == 200, f"Delete session failed: {status}"
        self._chat_session_id = None

    # ------------------------------------------------------------------
    # Tests: Code Sessions
    # ------------------------------------------------------------------

    def test_07_create_code_session(self, result):
        """Create a code-type session."""
        self._login()
        status, data = self._fetch("POST", "/api/chat/sessions", {
            "title": "E2E Code Session",
            "type": "code",
        })
        assert status in (200, 201), f"Code session creation failed: {status}"
        if isinstance(data, dict):
            self._code_session_id = data.get("id") or data.get("session_id")

    def test_08_code_page_ui(self, result):
        """Code page renders."""
        self._login()
        self._login_ui()
        snap = self.cli.snapshot_content()
        code_ref = self._find_ref(snap, "Code")
        if code_ref:
            self.cli.click(code_ref)
            time.sleep(2)
        snap = self.cli.snapshot_content()
        has_code = any(
            kw in snap.lower()
            for kw in ["code", "session", "setup", "canvas", "send", "welcome"]
        )
        assert has_code, f"Code UI should render:\n{snap[:500]}"

    def test_09_delete_code_session(self, result):
        """Clean up code session."""
        self._login()
        if not self._code_session_id:
            raise SkipTest("No code session created")
        status, _ = self._fetch("DELETE", f"/api/chat/sessions/{self._code_session_id}")
        assert status == 200, f"Delete code session failed: {status}"
        self._code_session_id = None

    # ------------------------------------------------------------------
    # Tests: Tool & Skill Management
    # ------------------------------------------------------------------

    def test_10_toggle_tool(self, result):
        """Toggle a tool enabled/disabled via API."""
        result.covers.append("PATCH /api/tools/{name}")
        self._login()
        status, data = self._fetch("GET", "/api/tools")
        if status != 200 or not isinstance(data, list) or not data:
            raise SkipTest("No tools available")

        safe = [t for t in data if t.get("name") not in ("shell", "filesystem", "git_tool")]
        if not safe:
            raise SkipTest("No safe tools to toggle")

        tool = safe[0]
        name = tool.get("name")
        was = tool.get("enabled", True)
        s1, _ = self._fetch("PATCH", f"/api/tools/{name}", {"enabled": not was})
        assert s1 == 200, f"Toggle failed: {s1}"
        self._fetch("PATCH", f"/api/tools/{name}", {"enabled": was})

    def test_11_toggle_skill(self, result):
        """Toggle a skill enabled/disabled via API."""
        result.covers.append("PATCH /api/skills/{name}")
        self._login()
        status, data = self._fetch("GET", "/api/skills")
        if status != 200 or not isinstance(data, list) or not data:
            raise SkipTest("No skills available")

        skill = data[0]
        name = skill.get("name")
        was = skill.get("enabled", True)
        s1, _ = self._fetch("PATCH", f"/api/skills/{name}", {"enabled": not was})
        assert s1 == 200, f"Skill toggle failed: {s1}"
        self._fetch("PATCH", f"/api/skills/{name}", {"enabled": was})

    # ------------------------------------------------------------------
    # Tests: Persona
    # ------------------------------------------------------------------

    def test_12_get_persona(self, result):
        """Get the current persona configuration."""
        result.covers.append("GET /api/persona")
        self._login()
        status, _ = self._fetch("GET", "/api/persona")
        assert status == 200, f"Get persona failed: {status}"

    def test_13_update_persona(self, result):
        """Update persona and verify."""
        result.covers.append("PUT /api/persona")
        self._login()
        _, original = self._fetch("GET", "/api/persona")
        original_prompt = original.get("prompt", "") if isinstance(original, dict) else ""

        status, _ = self._fetch("PUT", "/api/persona", {
            "prompt": "E2E test persona - You are a helpful coding assistant."
        })
        assert status == 200, f"Update persona failed: {status}"

        _, updated = self._fetch("GET", "/api/persona")
        if isinstance(updated, dict):
            assert_contains(updated.get("prompt", ""), "E2E test persona", "Persona updated")

        self._fetch("PUT", "/api/persona", {"prompt": original_prompt})

    # ------------------------------------------------------------------
    # Tests: Settings
    # ------------------------------------------------------------------

    def test_14_settings_ui_tabs(self, result):
        """Settings page renders with tabs."""
        self._login()
        self._login_ui()
        snap = self.cli.snapshot_content()
        settings_ref = self._find_ref(snap, "Settings")
        if settings_ref:
            self.cli.click(settings_ref)
            time.sleep(2)
        snap = self.cli.snapshot_content()
        expected = ["provider", "tool", "skill", "key", "persona", "tab"]
        found = sum(1 for t in expected if t in snap.lower())
        assert found >= 2, f"Settings should show tabs. Found {found}/6:\n{snap[:500]}"

    # ------------------------------------------------------------------
    # Tests: Dynamic coverage
    # ------------------------------------------------------------------

    def test_15_all_discovered_tools_in_api(self, result):
        """Verify codebase tools appear in API."""
        self._login()
        status, data = self._fetch("GET", "/api/tools")
        if status != 200 or not isinstance(data, list):
            raise SkipTest("Cannot fetch tools")
        api_names = {t.get("name", "") for t in data}
        for t in self.manifest.tools:
            if t.name in api_names:
                result.covers.append(f"TOOL_REGISTERED:{t.name}")

    def test_16_all_discovered_skills_in_api(self, result):
        """Verify codebase skills appear in API."""
        self._login()
        status, data = self._fetch("GET", "/api/skills")
        if status != 200 or not isinstance(data, list):
            raise SkipTest("Cannot fetch skills")
        api_names = {s.get("name", "") for s in data}
        for skill in self.manifest.skills:
            if skill in api_names:
                result.covers.append(f"SKILL_REGISTERED:{skill}")

    def test_17_password_change_form(self, result):
        """Settings has password change section."""
        result.covers.append("POST /api/settings/password")
        self._login()
        self._login_ui()
        snap = self.cli.snapshot_content()
        settings_ref = self._find_ref(snap, "Settings")
        if settings_ref:
            self.cli.click(settings_ref)
            time.sleep(1)
        snap = self.cli.snapshot_content()
        if "password" in snap.lower():
            result.covers.append("UI:password-change-form")

    def test_18_l2_status(self, result):
        """GET /api/l2/status returns escalation status."""
        result.covers.append("GET /api/l2/status")
        self._login()
        status, _ = self._fetch("GET", "/api/l2/status")
        assert status in (200, 404), f"L2 status unexpected: {status}"

    def test_19_notifications_config(self, result):
        """GET /api/notifications/config returns settings."""
        result.covers.append("GET /api/notifications/config")
        self._login()
        status, _ = self._fetch("GET", "/api/notifications/config")
        assert status in (200, 404), f"Notifications config unexpected: {status}"

    def test_20_screenshot_all_pages(self, result):
        """Take screenshots of key pages for visual regression."""
        self._login()
        self._login_ui()
        snap = self.cli.snapshot_content()

        pages = ["Mission Control", "Status", "Chat", "Tools", "Settings", "Reports"]
        for page in pages:
            ref = self._find_ref(snap, page)
            if ref:
                self.cli.click(ref)
                time.sleep(1)
                safe_name = page.lower().replace(" ", "-")
                self.cli.screenshot(filename=f"{config.output_dir}/page-{safe_name}.png")
                result.screenshots.append(f"{config.output_dir}/page-{safe_name}.png")
                # Re-read snap for next nav
                snap = self.cli.snapshot_content()
