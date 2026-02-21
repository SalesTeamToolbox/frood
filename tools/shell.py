"""
Shell execution tool — runs commands with safety filters and sandboxing.

Security layers:
1. CommandFilter — blocks known-dangerous patterns (rm -rf /, mkfs, etc.)
2. Path extraction — detects absolute paths in commands and blocks those outside workspace
3. cwd enforcement — all commands execute inside the workspace directory
4. Timeout — prevents runaway processes
"""

import asyncio
import logging
import re
import shlex

from core.command_filter import CommandFilter, CommandFilterError
from core.sandbox import WorkspaceSandbox, SandboxViolation
from tools.base import Tool, ToolResult

logger = logging.getLogger("agent42.tools.shell")

MAX_OUTPUT_LENGTH = 10000
DEFAULT_TIMEOUT = 60

# Regex to find absolute paths in a command string
_ABS_PATH_RE = re.compile(r'(?<!\w)/(?:[\w./-]+)')

# Patterns that may indicate credentials in command output
_CREDENTIAL_PATTERNS = [
    (re.compile(r'(?i)(password|passwd|pwd)\s*[=:]\s*\S+'), r'\1=***REDACTED***'),
    (re.compile(r'(?i)(api[_-]?key|apikey)\s*[=:]\s*\S+'), r'\1=***REDACTED***'),
    (re.compile(r'(?i)(secret|api[_-]?secret)\s*[=:]\s*\S+'), r'\1=***REDACTED***'),
    (re.compile(r'(?i)(token|auth[_-]?token|access[_-]?token)\s*[=:]\s*\S+'), r'\1=***REDACTED***'),
    (re.compile(r'(?i)(database[_-]?url|db[_-]?url)\s*[=:]\s*\S+'), r'\1=***REDACTED***'),
    (re.compile(r'(?i)(aws[_-]?access[_-]?key[_-]?id)\s*[=:]\s*\S+'), r'\1=***REDACTED***'),
    (re.compile(r'(?i)(aws[_-]?secret[_-]?access[_-]?key)\s*[=:]\s*\S+'), r'\1=***REDACTED***'),
    # AWS key pattern
    (re.compile(r'AKIA[0-9A-Z]{16}'), '***AWS_KEY_REDACTED***'),
    # Slack token pattern
    (re.compile(r'xox[bpras]-[a-zA-Z0-9-]{10,}'), '***SLACK_TOKEN_REDACTED***'),
    # GitHub token pattern
    (re.compile(r'gh[pousr]_[A-Za-z0-9_]{36,}'), '***GITHUB_TOKEN_REDACTED***'),
]


def _sanitize_output(text: str) -> str:
    """Redact likely credentials from command output."""
    for pattern, replacement in _CREDENTIAL_PATTERNS:
        text = pattern.sub(replacement, text)
    return text

# Paths that are always allowed (read-only system utilities)
_SAFE_PATH_PREFIXES = (
    "/usr/bin", "/usr/local/bin", "/usr/sbin",
    "/bin", "/sbin",
    "/usr/lib", "/usr/local/lib", "/usr/share",
    "/dev/null", "/dev/stdin", "/dev/stdout", "/dev/stderr",
    "/proc/self",
    # Note: /tmp is intentionally excluded — it could be used as a staging area
    # for attack payloads outside the sandbox. Agents should use workspace-local
    # temp files instead.
)


class ShellTool(Tool):
    """Execute shell commands within the sandbox with safety filters.

    Path enforcement: any absolute path in the command is checked against
    the workspace sandbox. Commands referencing /var/www, /etc/nginx, or
    any other directory outside the workspace are blocked.
    """

    def __init__(
        self,
        sandbox: WorkspaceSandbox,
        command_filter: CommandFilter | None = None,
        timeout: int = DEFAULT_TIMEOUT,
    ):
        self._sandbox = sandbox
        self._filter = command_filter or CommandFilter()
        self._timeout = timeout

    @property
    def name(self) -> str:
        return "shell"

    @property
    def description(self) -> str:
        return (
            "Execute a shell command in the workspace directory. "
            "Commands that reference files outside the workspace are blocked."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute",
                },
            },
            "required": ["command"],
        }

    def _check_paths(self, command: str) -> None:
        """Scan a command for absolute paths and block any outside the sandbox.

        Allows system utility paths (/usr/bin, /bin, /tmp, etc.) since those
        are needed for normal command execution.
        """
        if not self._sandbox.enabled:
            return

        for match in _ABS_PATH_RE.finditer(command):
            path = match.group(0)

            # Allow system utility paths (read-only)
            if any(path.startswith(prefix) for prefix in _SAFE_PATH_PREFIXES):
                continue

            # Check against sandbox
            if not self._sandbox.check_path(path):
                raise SandboxViolation(path, str(self._sandbox.allowed_dir))

    async def execute(self, command: str = "", **kwargs) -> ToolResult:
        if not command:
            return ToolResult(error="No command provided", success=False)

        # Layer 1: deny-pattern filter
        try:
            self._filter.check(command)
        except CommandFilterError as e:
            logger.warning(f"Blocked command (filter): {command} — {e}")
            return ToolResult(error=str(e), success=False)

        # Layer 2: path enforcement — block access outside workspace
        try:
            self._check_paths(command)
        except SandboxViolation as e:
            logger.warning(f"Blocked command (sandbox): {command} — {e}")
            return ToolResult(error=str(e), success=False)

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                cwd=str(self._sandbox.allowed_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self._timeout
            )

            output = stdout.decode("utf-8", errors="replace")
            errors = stderr.decode("utf-8", errors="replace")

            # Sanitize credentials from output before returning
            output = _sanitize_output(output)
            errors = _sanitize_output(errors)

            # Truncate long outputs
            if len(output) > MAX_OUTPUT_LENGTH:
                output = output[:MAX_OUTPUT_LENGTH] + "\n... (output truncated)"
            if len(errors) > MAX_OUTPUT_LENGTH:
                errors = errors[:MAX_OUTPUT_LENGTH] + "\n... (output truncated)"

            combined = output
            if errors:
                combined += f"\nSTDERR:\n{errors}"

            return ToolResult(
                output=combined,
                success=proc.returncode == 0,
                error=errors if proc.returncode != 0 else "",
            )

        except asyncio.TimeoutError:
            # Kill the orphaned process to prevent resource leaks
            try:
                proc.kill()
                await asyncio.wait_for(proc.wait(), timeout=5)
            except Exception:
                pass  # Best effort cleanup
            return ToolResult(
                error=f"Command timed out after {self._timeout} seconds",
                success=False,
            )
        except Exception as e:
            return ToolResult(error=str(e), success=False)
