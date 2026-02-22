"""
Linter tool — run code linters and return structured diagnostics.

Supports ruff (Python), eslint (JavaScript/TypeScript), and custom linter commands.
Returns structured output with file, line, severity, and message.
"""

import asyncio
import json
import logging
import shutil

from tools.base import Tool, ToolResult

logger = logging.getLogger("agent42.tools.linter")


class LinterTool(Tool):
    """Run linters and return structured diagnostics."""

    def __init__(self, workspace_path: str = "."):
        self._workspace = workspace_path

    @property
    def name(self) -> str:
        return "run_linter"

    @property
    def description(self) -> str:
        return (
            "Run code linters (ruff, eslint, or custom) and return structured diagnostics. "
            "Returns file, line number, severity, and message for each issue found."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "linter": {
                    "type": "string",
                    "enum": ["auto", "ruff", "eslint", "custom"],
                    "description": "Linter to use (default: auto-detect)",
                    "default": "auto",
                },
                "path": {
                    "type": "string",
                    "description": "File or directory to lint (default: project root)",
                    "default": "",
                },
                "fix": {
                    "type": "boolean",
                    "description": "Auto-fix issues where possible (default: false)",
                    "default": False,
                },
                "command": {
                    "type": "string",
                    "description": "Custom linter command (only for linter='custom')",
                    "default": "",
                },
            },
            "required": [],
        }

    async def execute(
        self,
        linter: str = "auto",
        path: str = "",
        fix: bool = False,
        command: str = "",
        **kwargs,
    ) -> ToolResult:
        if linter == "auto":
            linter = self._detect_linter()

        if linter == "ruff":
            return await self._run_ruff(path, fix)
        elif linter == "eslint":
            return await self._run_eslint(path, fix)
        elif linter == "custom":
            if not command:
                return ToolResult(error="Custom command required", success=False)
            return await self._run_custom(command)
        else:
            return ToolResult(error=f"Unknown linter: {linter}", success=False)

    def _detect_linter(self) -> str:
        """Auto-detect the appropriate linter."""
        import os

        workspace = self._workspace

        # Check for ruff config or Python project
        for name in ("ruff.toml", "pyproject.toml", "setup.cfg", "setup.py"):
            if os.path.exists(os.path.join(workspace, name)):
                if shutil.which("ruff"):
                    return "ruff"

        # Check for eslint config or JS project
        for name in (
            ".eslintrc",
            ".eslintrc.js",
            ".eslintrc.json",
            ".eslintrc.yml",
            "eslint.config.js",
            "eslint.config.mjs",
        ):
            if os.path.exists(os.path.join(workspace, name)):
                return "eslint"

        if os.path.exists(os.path.join(workspace, "package.json")):
            return "eslint"

        # Default to ruff if available
        if shutil.which("ruff"):
            return "ruff"

        return "ruff"  # Will fail gracefully if not installed

    async def _run_ruff(self, path: str, fix: bool) -> ToolResult:
        cmd = ["ruff", "check", "--output-format=json"]
        if fix:
            cmd.append("--fix")
        if path:
            cmd.append(path)
        else:
            cmd.append(".")

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=self._workspace,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120.0)
        except TimeoutError:
            proc.kill()
            return ToolResult(error="Linter timed out (>2min)", success=False)

        output = stdout.decode("utf-8", errors="replace")
        errors = stderr.decode("utf-8", errors="replace")

        # Parse ruff JSON output
        try:
            issues = json.loads(output) if output.strip() else []
            return self._format_ruff_issues(issues, fix)
        except json.JSONDecodeError:
            # Fallback to raw output
            combined = output + ("\n" + errors if errors else "")
            if len(combined) > 50000:
                combined = combined[:50000] + "\n... (output truncated)"
            no_issues = proc.returncode == 0
            return ToolResult(
                output=f"## Ruff Results\n\n{combined}"
                if combined.strip()
                else "## Ruff Results\n\nNo issues found.",
                success=no_issues,
            )

    def _format_ruff_issues(self, issues: list, fix: bool) -> ToolResult:
        """Format ruff JSON issues into structured output."""
        if not issues:
            msg = "## Ruff Results: CLEAN\n\nNo issues found."
            if fix:
                msg += " (with auto-fix applied)"
            return ToolResult(output=msg, success=True)

        lines = [f"## Ruff Results: {len(issues)} issue(s) found\n"]
        if fix:
            lines.append("(auto-fix was applied where possible)\n")

        by_file: dict[str, list] = {}
        for issue in issues:
            filename = issue.get("filename", "unknown")
            by_file.setdefault(filename, []).append(issue)

        for filename, file_issues in by_file.items():
            lines.append(f"### {filename}")
            for issue in file_issues:
                row = issue.get("location", {}).get("row", "?")
                col = issue.get("location", {}).get("column", "?")
                code = issue.get("code", "")
                msg = issue.get("message", "")
                fix_info = ""
                if issue.get("fix", {}).get("applicability") == "safe":
                    fix_info = " [fixable]"
                lines.append(f"  L{row}:{col} {code} {msg}{fix_info}")
            lines.append("")

        return ToolResult(output="\n".join(lines), success=False)

    async def _run_eslint(self, path: str, fix: bool) -> ToolResult:
        cmd = ["npx", "eslint", "--format=json"]
        if fix:
            cmd.append("--fix")
        if path:
            cmd.append(path)
        else:
            cmd.append(".")

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=self._workspace,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120.0)
        except TimeoutError:
            proc.kill()
            return ToolResult(error="Linter timed out (>2min)", success=False)

        output = stdout.decode("utf-8", errors="replace")
        errors = stderr.decode("utf-8", errors="replace")

        try:
            results = json.loads(output) if output.strip() else []
            return self._format_eslint_results(results, fix)
        except json.JSONDecodeError:
            combined = output + ("\n" + errors if errors else "")
            if len(combined) > 50000:
                combined = combined[:50000] + "\n... (output truncated)"
            no_issues = proc.returncode == 0
            return ToolResult(
                output=f"## ESLint Results\n\n{combined}"
                if combined.strip()
                else "## ESLint Results\n\nNo issues found.",
                success=no_issues,
            )

    def _format_eslint_results(self, results: list, fix: bool) -> ToolResult:
        """Format eslint JSON results into structured output."""
        total_errors = sum(r.get("errorCount", 0) for r in results)
        total_warnings = sum(r.get("warningCount", 0) for r in results)

        if total_errors == 0 and total_warnings == 0:
            msg = "## ESLint Results: CLEAN\n\nNo issues found."
            if fix:
                msg += " (with auto-fix applied)"
            return ToolResult(output=msg, success=True)

        lines = [f"## ESLint Results: {total_errors} error(s), {total_warnings} warning(s)\n"]
        if fix:
            lines.append("(auto-fix was applied where possible)\n")

        for result in results:
            messages = result.get("messages", [])
            if not messages:
                continue
            filepath = result.get("filePath", "unknown")
            lines.append(f"### {filepath}")
            for msg in messages:
                line = msg.get("line", "?")
                col = msg.get("column", "?")
                severity = "error" if msg.get("severity") == 2 else "warning"
                rule = msg.get("ruleId", "")
                text = msg.get("message", "")
                lines.append(f"  L{line}:{col} [{severity}] {rule}: {text}")
            lines.append("")

        return ToolResult(output="\n".join(lines), success=total_errors == 0)

    async def _run_custom(self, command: str) -> ToolResult:
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=self._workspace,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120.0)
        except TimeoutError:
            proc.kill()
            return ToolResult(error="Linter command timed out (>2min)", success=False)

        output = stdout.decode("utf-8", errors="replace")
        errors = stderr.decode("utf-8", errors="replace")
        combined = output + ("\n" + errors if errors else "")

        if len(combined) > 50000:
            combined = combined[:50000] + "\n... (output truncated)"

        passed = proc.returncode == 0
        return ToolResult(
            output=f"## Linter Results (exit code: {proc.returncode})\n\n{combined}",
            success=passed,
        )
