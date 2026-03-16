"""
Thin wrapper around playwright-cli for E2E tests.

Handles session management, output parsing, and error reporting.
"""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .config import config


def _find_playwright_cli() -> str:
    """Locate the playwright-cli binary, handling Windows .cmd wrappers."""
    # Check if it's directly available
    found = shutil.which("playwright-cli")
    if found:
        return found
    # Windows: try the .cmd variant explicitly
    if sys.platform == "win32":
        found = shutil.which("playwright-cli.cmd")
        if found:
            return found
    # Fallback: use npx
    return "npx playwright-cli"


class PlaywrightCLI:
    """Wrapper around playwright-cli binary with session support."""

    def __init__(self, session: str | None = None, headed: bool = False):
        self.session = session or config.session_name
        self.headed = headed or config.headed
        self._browser_open = False
        self._binary = _find_playwright_cli()

    def _run(self, args: list[str], timeout: int = 30) -> str:
        cmd = [self._binary, f"-s={self.session}"] + args
        env = os.environ.copy()
        env["PLAYWRIGHT_CLI_SESSION"] = self.session
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(config.agent42_root),
            env=env,
            shell=(sys.platform == "win32"),
        )
        output = result.stdout.strip()
        if result.returncode != 0 and result.stderr:
            output += f"\nSTDERR: {result.stderr.strip()}"
        return output

    def open(self, url: str | None = None) -> str:
        args = ["open"]
        if url:
            args.append(url)
        if self.headed:
            args.append("--headed")
        result = self._run(args, timeout=30)
        self._browser_open = True
        return result

    def goto(self, url: str) -> str:
        return self._run(["goto", url], timeout=15)

    def snapshot(self, filename: str | None = None) -> str:
        args = ["snapshot"]
        if filename:
            args.append(f"--filename={filename}")
        return self._run(args)

    def click(self, ref: str, button: str = "") -> str:
        args = ["click", ref]
        if button:
            args.append(button)
        return self._run(args)

    def fill(self, ref: str, text: str) -> str:
        return self._run(["fill", ref, text])

    def type_text(self, text: str) -> str:
        return self._run(["type", text])

    def press(self, key: str) -> str:
        return self._run(["press", key])

    def screenshot(self, ref: str | None = None, filename: str | None = None) -> str:
        args = ["screenshot"]
        if ref:
            args.append(ref)
        if filename:
            args.append(f"--filename={filename}")
        return self._run(args)

    def eval_js(self, expr: str, ref: str | None = None) -> str:
        args = ["eval", expr]
        if ref:
            args.append(ref)
        return self._run(args)

    def run_code(self, code: str) -> str:
        """Run async Playwright code snippet (has access to `page`)."""
        return self._run(["run-code", code], timeout=30)

    def fetch_api(self, method: str, path: str, body: dict | None = None,
                  token: str | None = None) -> tuple[int, str]:
        """Execute a fetch() call in the browser context. Returns (status, body_text)."""
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        headers_json = json.dumps(headers)
        body_json = json.dumps(body) if body else "null"

        code = (
            f"async page => {{"
            f"  const r = await page.evaluate(async () => {{"
            f"    const opts = {{method: '{method}', headers: {headers_json}}};"
            f"    const bodyData = {body_json};"
            f"    if (bodyData !== null) opts.body = JSON.stringify(bodyData);"
            f"    const resp = await fetch('{path}', opts);"
            f"    return resp.status + '|||' + await resp.text();"
            f"  }});"
            f"  return r;"
            f"}}"
        )
        raw = self.run_code(code)
        # Parse "### Result\n\"200|||{...}\"\n..."
        result_str = ""
        for line in raw.split("\n"):
            line = line.strip().strip('"')
            if "|||" in line:
                result_str = line
                break
        if not result_str:
            return 0, raw

        parts = result_str.split("|||", 1)
        status = int(parts[0]) if parts[0].isdigit() else 0
        return status, parts[1] if len(parts) > 1 else ""

    def snapshot_content(self) -> str:
        """Take a snapshot and return the full YAML content (with element refs)."""
        output = self.snapshot()
        # Extract snapshot file path from output like:
        # [Snapshot](.playwright-cli\page-2026-...yml)
        import re
        m = re.search(r'\[Snapshot\]\(([^)]+)\)', output)
        if m:
            snap_path = config.agent42_root / m.group(1).replace("\\", "/")
            if snap_path.exists():
                return snap_path.read_text(encoding="utf-8", errors="replace")
        # Fallback: return the raw output
        return output

    def login_ui(self, username: str, password: str) -> str | None:
        """Login via the browser UI, return the JWT token from localStorage."""
        import re
        snap = self.snapshot_content()

        # Find login form refs
        def _ref(pattern):
            for line in snap.split("\n"):
                if pattern.lower() in line.lower():
                    m = re.search(r'\[ref=(e\d+)\]', line)
                    if m:
                        return m.group(1)
            return None

        username_ref = _ref('textbox "Username"')
        password_ref = _ref('textbox "Password"')
        signin_ref = _ref('button "Sign In"')

        if not (username_ref and password_ref and signin_ref):
            # Already logged in or different page
            return self._extract_token()

        self.fill(username_ref, username)
        self.fill(password_ref, password)
        self.click(signin_ref)
        time.sleep(2)
        return self._extract_token()

    def _extract_token(self) -> str | None:
        """Get JWT token from localStorage."""
        raw = self.eval_js("localStorage.getItem('agent42_token')")
        # Output: ### Result\n"eyJ..."\n...
        for line in raw.split("\n"):
            line = line.strip().strip('"')
            if line.startswith("eyJ"):
                return line
        return None

    def console(self, level: str = "") -> str:
        args = ["console"]
        if level:
            args.append(level)
        return self._run(args)

    def network(self) -> str:
        return self._run(["network"])

    def select(self, ref: str, value: str) -> str:
        return self._run(["select", ref, value])

    def check(self, ref: str) -> str:
        return self._run(["check", ref])

    def uncheck(self, ref: str) -> str:
        return self._run(["uncheck", ref])

    def hover(self, ref: str) -> str:
        return self._run(["hover", ref])

    def tab_list(self) -> str:
        return self._run(["tab-list"])

    def tab_new(self, url: str | None = None) -> str:
        args = ["tab-new"]
        if url:
            args.append(url)
        return self._run(args)

    def tab_select(self, index: int) -> str:
        return self._run(["tab-select", str(index)])

    def close(self) -> str:
        if self._browser_open:
            self._browser_open = False
            return self._run(["close"])
        return ""

    def close_all(self) -> str:
        self._browser_open = False
        return self._run(["close-all"])

    def cookie_list(self) -> str:
        return self._run(["cookie-list"])

    def localstorage_list(self) -> str:
        return self._run(["localstorage-list"])

    def route(self, pattern: str, **kwargs) -> str:
        args = ["route", pattern]
        for k, v in kwargs.items():
            args.append(f"--{k}={v}")
        return self._run(args)

    def unroute(self, pattern: str = "") -> str:
        args = ["unroute"]
        if pattern:
            args.append(pattern)
        return self._run(args)

    def tracing_start(self) -> str:
        return self._run(["tracing-start"])

    def tracing_stop(self) -> str:
        return self._run(["tracing-stop"])

    def video_start(self) -> str:
        return self._run(["video-start"])

    def video_stop(self, filename: str | None = None) -> str:
        args = ["video-stop"]
        if filename:
            args.append(filename)
        return self._run(args)

    def wait_for_ready(self, url: str, retries: int = 30, delay: float = 1.0) -> bool:
        """Poll until the server responds at url."""
        import urllib.request
        import urllib.error

        for _ in range(retries):
            try:
                urllib.request.urlopen(url, timeout=2)
                return True
            except (urllib.error.URLError, OSError):
                time.sleep(delay)
        return False
