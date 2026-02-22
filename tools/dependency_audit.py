"""
Dependency audit tool — scan for vulnerable dependencies.

Supports pip-audit (Python) and npm audit (JavaScript).
Returns structured vulnerability reports with severity and fix recommendations.
"""

import asyncio
import json
import logging

from tools.base import Tool, ToolResult

logger = logging.getLogger("agent42.tools.dependency_audit")


class DependencyAuditTool(Tool):
    """Scan project dependencies for known vulnerabilities."""

    def __init__(self, workspace_path: str = "."):
        self._workspace = workspace_path

    @property
    def name(self) -> str:
        return "dependency_audit"

    @property
    def description(self) -> str:
        return (
            "Scan dependencies for known vulnerabilities using pip-audit (Python) "
            "or npm audit (JavaScript). Returns severity, affected package, and fix info."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "ecosystem": {
                    "type": "string",
                    "enum": ["auto", "python", "javascript"],
                    "description": "Package ecosystem to audit (default: auto-detect)",
                    "default": "auto",
                },
                "fix": {
                    "type": "boolean",
                    "description": "Attempt to auto-fix vulnerabilities (default: false)",
                    "default": False,
                },
            },
            "required": [],
        }

    async def execute(
        self,
        ecosystem: str = "auto",
        fix: bool = False,
        **kwargs,
    ) -> ToolResult:
        if ecosystem == "auto":
            ecosystem = self._detect_ecosystem()

        if ecosystem == "python":
            return await self._audit_python(fix)
        elif ecosystem == "javascript":
            return await self._audit_javascript(fix)
        else:
            return ToolResult(error=f"Unknown ecosystem: {ecosystem}", success=False)

    def _detect_ecosystem(self) -> str:
        import os

        ws = self._workspace
        for name in ("requirements.txt", "pyproject.toml", "setup.py", "Pipfile"):
            if os.path.exists(os.path.join(ws, name)):
                return "python"
        for name in ("package.json", "package-lock.json", "yarn.lock"):
            if os.path.exists(os.path.join(ws, name)):
                return "javascript"
        return "python"

    async def _audit_python(self, fix: bool) -> ToolResult:
        # Try pip-audit first
        cmd = ["pip-audit", "--format=json"]
        if fix:
            cmd.append("--fix")

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
            return ToolResult(error="Audit timed out (>2min)", success=False)

        output = stdout.decode("utf-8", errors="replace")
        errors = stderr.decode("utf-8", errors="replace")

        # pip-audit not installed — try safety
        if proc.returncode != 0 and "No module named" in errors:
            return await self._audit_python_safety(fix)

        try:
            data = json.loads(output) if output.strip() else {}
            return self._format_pip_audit(data, fix)
        except json.JSONDecodeError:
            combined = output + ("\n" + errors if errors else "")
            if len(combined) > 50000:
                combined = combined[:50000] + "\n... (truncated)"
            return ToolResult(
                output=f"## Python Dependency Audit\n\n{combined}",
                success=proc.returncode == 0,
            )

    async def _audit_python_safety(self, fix: bool) -> ToolResult:
        """Fallback to 'safety check' if pip-audit is not available."""
        cmd = ["safety", "check", "--json"]
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
            return ToolResult(error="Safety check timed out", success=False)

        output = stdout.decode("utf-8", errors="replace")

        if "No module named" in output or "command not found" in output:
            return ToolResult(
                error="Neither pip-audit nor safety is installed. Run: pip install pip-audit",
                success=False,
            )

        if len(output) > 50000:
            output = output[:50000] + "\n... (truncated)"
        return ToolResult(
            output=f"## Python Dependency Audit (safety)\n\n{output}",
            success=proc.returncode == 0,
        )

    def _format_pip_audit(self, data: dict, fix: bool) -> ToolResult:
        vulns = data.get("vulnerabilities", [])
        deps = data.get("dependencies", [])

        if not vulns:
            msg = f"## Python Dependency Audit: CLEAN\n\n{len(deps)} dependencies scanned, no vulnerabilities found."
            if fix:
                msg += " (auto-fix was enabled)"
            return ToolResult(output=msg, success=True)

        lines = [f"## Python Dependency Audit: {len(vulns)} vulnerability(ies) found\n"]
        if fix:
            lines.append("(auto-fix was attempted)\n")

        for vuln in vulns:
            name = vuln.get("name", "unknown")
            version = vuln.get("version", "?")
            vuln_id = vuln.get("id", "")
            desc = vuln.get("description", "")
            fix_versions = vuln.get("fix_versions", [])

            lines.append(f"### {name} {version}")
            lines.append(f"  **ID:** {vuln_id}")
            if desc:
                lines.append(f"  **Description:** {desc[:200]}")
            if fix_versions:
                lines.append(f"  **Fix:** upgrade to {', '.join(fix_versions)}")
            lines.append("")

        return ToolResult(output="\n".join(lines), success=False)

    async def _audit_javascript(self, fix: bool) -> ToolResult:
        cmd = ["npm", "audit", "--json"]
        if fix:
            cmd = ["npm", "audit", "fix", "--json"]

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
            return ToolResult(error="npm audit timed out", success=False)

        output = stdout.decode("utf-8", errors="replace")

        try:
            data = json.loads(output) if output.strip() else {}
            return self._format_npm_audit(data, fix)
        except json.JSONDecodeError:
            if len(output) > 50000:
                output = output[:50000] + "\n... (truncated)"
            return ToolResult(
                output=f"## JavaScript Dependency Audit\n\n{output}",
                success=proc.returncode == 0,
            )

    def _format_npm_audit(self, data: dict, fix: bool) -> ToolResult:
        metadata = data.get("metadata", {})
        vulns = metadata.get("vulnerabilities", {})
        total = sum(vulns.get(sev, 0) for sev in ("critical", "high", "moderate", "low"))

        if total == 0:
            total_deps = metadata.get("totalDependencies", "?")
            return ToolResult(
                output=f"## JavaScript Dependency Audit: CLEAN\n\n{total_deps} dependencies scanned, no vulnerabilities found.",
                success=True,
            )

        lines = [f"## JavaScript Dependency Audit: {total} vulnerability(ies)\n"]
        lines.append(f"  Critical: {vulns.get('critical', 0)}")
        lines.append(f"  High: {vulns.get('high', 0)}")
        lines.append(f"  Moderate: {vulns.get('moderate', 0)}")
        lines.append(f"  Low: {vulns.get('low', 0)}")
        lines.append("")

        advisories = data.get("advisories", data.get("vulnerabilities", {}))
        if isinstance(advisories, dict):
            for key, advisory in list(advisories.items())[:20]:
                if isinstance(advisory, dict):
                    name = advisory.get("name", advisory.get("module_name", key))
                    severity = advisory.get("severity", "?")
                    title = advisory.get("title", advisory.get("overview", ""))
                    via = advisory.get("via", [])
                    lines.append(f"### [{severity}] {name}")
                    if title:
                        lines.append(f"  {title[:200]}")
                    if isinstance(via, list) and via:
                        lines.append(f"  Via: {', '.join(str(v) for v in via[:5])}")
                    lines.append("")

        if fix:
            lines.append("(npm audit fix was applied)")

        return ToolResult(output="\n".join(lines), success=False)
