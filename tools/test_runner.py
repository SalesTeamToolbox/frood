"""
Test runner tool — execute test suites and parse structured results.

Supports pytest (Python), jest/vitest (JavaScript), and generic test commands.
Returns structured pass/fail/error counts and failure details.
"""

import asyncio
import json
import logging

from tools.base import Tool, ToolResult

logger = logging.getLogger("agent42.tools.test_runner")


class TestRunnerTool(Tool):
    """Run tests and return structured results."""

    def __init__(self, workspace_path: str = "."):
        self._workspace = workspace_path

    @property
    def name(self) -> str:
        return "run_tests"

    @property
    def description(self) -> str:
        return (
            "Run test suites (pytest, jest, vitest, or custom). "
            "Returns structured results with pass/fail counts and failure details. "
            "Use 'framework' to auto-detect, or specify a custom command."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "framework": {
                    "type": "string",
                    "enum": ["auto", "pytest", "jest", "vitest", "custom"],
                    "description": "Test framework (default: auto-detect)",
                    "default": "auto",
                },
                "path": {
                    "type": "string",
                    "description": "Test file or directory (default: project root)",
                    "default": "",
                },
                "filter": {
                    "type": "string",
                    "description": "Filter pattern (e.g., test name substring, -k for pytest)",
                    "default": "",
                },
                "command": {
                    "type": "string",
                    "description": "Custom test command (only for framework='custom')",
                    "default": "",
                },
                "verbose": {
                    "type": "boolean",
                    "description": "Verbose output (default: true)",
                    "default": True,
                },
            },
            "required": [],
        }

    async def execute(
        self,
        framework: str = "auto",
        path: str = "",
        filter: str = "",
        command: str = "",
        verbose: bool = True,
        **kwargs,
    ) -> ToolResult:
        if framework == "auto":
            framework = await self._detect_framework()

        if framework == "pytest":
            return await self._run_pytest(path, filter, verbose)
        elif framework in ("jest", "vitest"):
            return await self._run_js_tests(framework, path, filter, verbose)
        elif framework == "custom":
            if not command:
                return ToolResult(error="Custom command required", success=False)
            return await self._run_custom(command)
        else:
            return ToolResult(error=f"Unknown framework: {framework}", success=False)

    async def _detect_framework(self) -> str:
        """Auto-detect the test framework from project files."""
        import os

        workspace = self._workspace

        # Check for Python
        for name in ("pytest.ini", "pyproject.toml", "setup.cfg", "conftest.py"):
            if os.path.exists(os.path.join(workspace, name)):
                return "pytest"
        if os.path.exists(os.path.join(workspace, "tests")):
            return "pytest"

        # Check for JavaScript
        pkg_json = os.path.join(workspace, "package.json")
        if os.path.exists(pkg_json):
            try:
                with open(pkg_json) as f:
                    pkg = json.load(f)
                deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
                if "vitest" in deps:
                    return "vitest"
                if "jest" in deps:
                    return "jest"
            except Exception:
                pass

        return "pytest"  # Default

    async def _run_pytest(self, path: str, filter_: str, verbose: bool) -> ToolResult:
        cmd = ["python", "-m", "pytest"]
        if verbose:
            cmd.append("-v")
        cmd.append("--tb=short")
        cmd.append("--no-header")
        if filter_:
            cmd.extend(["-k", filter_])
        if path:
            cmd.append(path)

        return await self._run_and_format(cmd, "pytest")

    async def _run_js_tests(
        self, framework: str, path: str, filter_: str, verbose: bool
    ) -> ToolResult:
        cmd = ["npx", framework, "run"]
        if path:
            cmd.append(path)
        if filter_:
            cmd.extend(["-t", filter_])
        if not verbose:
            cmd.append("--silent")

        return await self._run_and_format(cmd, framework)

    async def _run_custom(self, command: str) -> ToolResult:
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=self._workspace,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300.0)
        except TimeoutError:
            proc.kill()
            return ToolResult(error="Test command timed out (>5min)", success=False)

        output = stdout.decode("utf-8", errors="replace")
        errors = stderr.decode("utf-8", errors="replace")
        combined = output + ("\n" + errors if errors else "")

        if len(combined) > 50000:
            combined = combined[:50000] + "\n... (output truncated)"

        passed = proc.returncode == 0
        return ToolResult(
            output=f"## Test Results (exit code: {proc.returncode})\n\n{combined}",
            success=passed,
        )

    async def _run_and_format(self, cmd: list[str], framework: str) -> ToolResult:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=self._workspace,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300.0)
        except TimeoutError:
            proc.kill()
            return ToolResult(error="Tests timed out (>5min)", success=False)

        output = stdout.decode("utf-8", errors="replace")
        errors = stderr.decode("utf-8", errors="replace")
        combined = output + ("\n" + errors if errors else "")

        if len(combined) > 50000:
            combined = combined[:50000] + "\n... (output truncated)"

        passed = proc.returncode == 0
        status = "PASSED" if passed else "FAILED"

        return ToolResult(
            output=f"## {framework} Results: {status} (exit code: {proc.returncode})\n\n{combined}",
            success=passed,
        )
