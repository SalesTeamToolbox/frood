"""
Security analyzer tool — risk-score tool calls and code changes.

Inspired by OpenHands' LLMSecurityAnalyzer. Analyzes proposed actions
and code for security risks, assigning a risk level and providing
remediation guidance.
"""

import logging
import os
import re

from tools.base import Tool, ToolResult

logger = logging.getLogger("agent42.tools.security_analyzer")

# Risk levels
RISK_NONE = "none"
RISK_LOW = "low"
RISK_MEDIUM = "medium"
RISK_HIGH = "high"
RISK_CRITICAL = "critical"

# Dangerous patterns to scan for
_PATTERNS = {
    RISK_CRITICAL: [
        (r"eval\s*\(", "eval() — arbitrary code execution"),
        (r"exec\s*\(", "exec() — arbitrary code execution"),
        (r"os\.system\s*\(", "os.system() — shell injection risk"),
        (r"subprocess\.call\(.*shell\s*=\s*True", "subprocess with shell=True"),
        (r"__import__\s*\(", "dynamic import — code injection risk"),
        (r"pickle\.loads?\s*\(", "pickle deserialization — arbitrary code execution"),
        (r"yaml\.load\s*\([^,]+\)(?!.*Loader)", "yaml.load without safe Loader"),
        (r"innerHTML\s*=", "innerHTML assignment — XSS risk"),
        (r"dangerouslySetInnerHTML", "dangerouslySetInnerHTML — XSS risk"),
        (r"rm\s+-rf\s+/", "recursive delete from root"),
    ],
    RISK_HIGH: [
        (r"subprocess\.(run|Popen|call)\s*\(", "subprocess execution"),
        (r"os\.(popen|exec|spawn)", "os process execution"),
        (r"SELECT\s+.*FROM\s+.*WHERE.*['\"]\s*\+", "SQL string concatenation — injection risk"),
        (r"cursor\.execute\([^,]*%s?[^,]*\%", "SQL format string — injection risk"),
        (r"\.format\(.*request\.", "string format with request data"),
        (r"f['\"].*\{request\.", "f-string with request data"),
        (r"open\s*\(.*request\.", "file open with request data — path traversal"),
        (r"(SECRET|PASSWORD|TOKEN|KEY)\s*=\s*['\"][^'\"]+['\"]", "hardcoded secret"),
        (r"chmod\s+777", "world-writable permissions"),
        (r"--no-verify", "bypassing verification"),
    ],
    RISK_MEDIUM: [
        (r"\.env\b", ".env file access — possible secrets"),
        (r"print\(.*password", "logging password"),
        (r"print\(.*token", "logging token"),
        (r"print\(.*secret", "logging secret"),
        (r"logging\..*password", "logging password to logfile"),
        (r"cors.*\*", "CORS wildcard — any origin allowed"),
        (r"verify\s*=\s*False", "SSL verification disabled"),
        (r"allow_redirects\s*=\s*True", "following redirects — SSRF risk"),
        (r"debug\s*=\s*True", "debug mode enabled"),
        (r"ALLOWED_HOSTS\s*=\s*\[\s*['\"]?\*", "Django ALLOWED_HOSTS wildcard"),
    ],
    RISK_LOW: [
        (r"TODO.*security", "security TODO — unfinished work"),
        (r"FIXME.*auth", "auth FIXME — unfinished work"),
        (r"# ?HACK", "HACK comment — fragile code"),
        (r"except\s*:", "bare except — swallows all errors"),
        (r"except\s+Exception\s*:", "broad exception catch"),
        (r"import \*", "wildcard import — namespace pollution"),
    ],
}


class SecurityAnalyzerTool(Tool):
    """Analyze code and commands for security risks."""

    def __init__(self, workspace_path: str = "."):
        self._workspace = workspace_path

    @property
    def name(self) -> str:
        return "security_analyze"

    @property
    def description(self) -> str:
        return (
            "Analyze code or shell commands for security vulnerabilities. "
            "Returns a risk level (none/low/medium/high/critical) with specific "
            "findings and remediation advice. Use before executing risky operations."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["scan_code", "scan_file", "scan_command", "scan_diff"],
                    "description": "What to analyze",
                },
                "code": {
                    "type": "string",
                    "description": "Code snippet to analyze (for scan_code)",
                    "default": "",
                },
                "path": {
                    "type": "string",
                    "description": "File path to analyze (for scan_file)",
                    "default": "",
                },
                "command": {
                    "type": "string",
                    "description": "Shell command to analyze (for scan_command)",
                    "default": "",
                },
                "diff": {
                    "type": "string",
                    "description": "Git diff to analyze (for scan_diff)",
                    "default": "",
                },
            },
            "required": ["action"],
        }

    async def execute(
        self,
        action: str = "",
        code: str = "",
        path: str = "",
        command: str = "",
        diff: str = "",
        **kwargs,
    ) -> ToolResult:
        if not action:
            return ToolResult(error="Action is required", success=False)

        if action == "scan_code":
            if not code:
                return ToolResult(error="Code required for scan_code", success=False)
            return self._scan_text(code, source="code snippet")
        elif action == "scan_file":
            return self._scan_file(path)
        elif action == "scan_command":
            if not command:
                return ToolResult(error="Command required for scan_command", success=False)
            return self._scan_command(command)
        elif action == "scan_diff":
            if not diff:
                return ToolResult(error="Diff required for scan_diff", success=False)
            return self._scan_text(diff, source="diff")
        else:
            return ToolResult(error=f"Unknown action: {action}", success=False)

    def _scan_text(self, text: str, source: str = "input") -> ToolResult:
        """Scan text for security patterns."""
        findings = []
        for risk_level, patterns in _PATTERNS.items():
            for pattern, description in patterns:
                for match in re.finditer(pattern, text, re.IGNORECASE):
                    # Find line number
                    line_num = text[:match.start()].count("\n") + 1
                    context = text[max(0, match.start()-20):match.end()+20].strip()
                    findings.append({
                        "risk": risk_level,
                        "description": description,
                        "line": line_num,
                        "context": context[:100],
                    })

        return self._format_findings(findings, source)

    def _scan_file(self, path: str) -> ToolResult:
        """Scan a file for security patterns."""
        if not path:
            return ToolResult(error="File path required", success=False)

        # Always resolve relative to workspace — never accept raw absolute paths
        full_path = os.path.normpath(os.path.join(self._workspace, path))
        # Prevent path traversal: resolved path must stay within workspace
        workspace_real = os.path.realpath(self._workspace)
        full_real = os.path.realpath(full_path)
        if not full_real.startswith(workspace_real + os.sep) and full_real != workspace_real:
            return ToolResult(
                error=f"Blocked: path '{path}' is outside the workspace",
                success=False,
            )
        if not os.path.isfile(full_real):
            return ToolResult(error=f"File not found: {path}", success=False)

        try:
            with open(full_real, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except Exception as e:
            return ToolResult(error=f"Failed to read file: {e}", success=False)

        if len(content) > 500000:
            return ToolResult(error="File too large (>500KB)", success=False)

        return self._scan_text(content, source=path)

    def _scan_command(self, command: str) -> ToolResult:
        """Scan a shell command for security risks."""
        findings = []

        # Check for dangerous commands
        dangerous_commands = {
            RISK_CRITICAL: [
                (r"rm\s+-rf\s+/", "Recursive delete from root"),
                (r"mkfs\.", "Filesystem format"),
                (r"dd\s+if=.*of=/dev/", "Direct disk write"),
                (r":()\{.*\|.*&\s*\};:", "Fork bomb"),
                (r">\s*/dev/sd", "Write to disk device"),
            ],
            RISK_HIGH: [
                (r"curl.*\|\s*(bash|sh)", "Pipe URL to shell"),
                (r"wget.*\|\s*(bash|sh)", "Pipe download to shell"),
                (r"chmod\s+777", "World-writable permissions"),
                (r"chmod\s+\+s", "Set SUID bit"),
                (r"ssh\s+-R", "Reverse SSH tunnel"),
                (r"nc\s+-l", "Netcat listener"),
                (r"ncat\s+-l", "Ncat listener"),
            ],
            RISK_MEDIUM: [
                (r"sudo\s+", "Privilege escalation"),
                (r"--force", "Force flag — bypasses safety checks"),
                (r"--no-verify", "Skip verification"),
                (r">\s*/etc/", "Write to system config"),
            ],
        }

        for risk_level, patterns in dangerous_commands.items():
            for pattern, description in patterns:
                if re.search(pattern, command, re.IGNORECASE):
                    findings.append({
                        "risk": risk_level,
                        "description": description,
                        "line": 0,
                        "context": command[:100],
                    })

        return self._format_findings(findings, source=f"command: {command[:60]}")

    def _format_findings(self, findings: list[dict], source: str) -> ToolResult:
        """Format security findings into structured output."""
        if not findings:
            return ToolResult(
                output=f"## Security Analysis: CLEAN\n\n**Source:** {source}\n\nNo security issues detected.",
                success=True,
            )

        # Determine overall risk level
        risk_order = [RISK_CRITICAL, RISK_HIGH, RISK_MEDIUM, RISK_LOW]
        overall_risk = RISK_LOW
        for risk in risk_order:
            if any(f["risk"] == risk for f in findings):
                overall_risk = risk
                break

        by_risk: dict[str, list] = {}
        for f in findings:
            by_risk.setdefault(f["risk"], []).append(f)

        lines = [
            f"## Security Analysis: {overall_risk.upper()} RISK",
            f"**Source:** {source}",
            f"**Findings:** {len(findings)}\n",
        ]

        for risk in risk_order:
            items = by_risk.get(risk, [])
            if not items:
                continue
            lines.append(f"### {risk.upper()} ({len(items)})")
            for item in items:
                loc = f"L{item['line']}" if item["line"] else ""
                lines.append(f"- {loc} **{item['description']}**")
                if item["context"]:
                    lines.append(f"  `{item['context']}`")
            lines.append("")

        is_safe = overall_risk in (RISK_NONE, RISK_LOW)
        return ToolResult(output="\n".join(lines), success=is_safe)
