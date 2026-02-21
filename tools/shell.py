"""
Shell execution tool — runs commands with safety filters and sandboxing.
"""

import asyncio
import logging

from core.command_filter import CommandFilter, CommandFilterError
from core.sandbox import WorkspaceSandbox
from tools.base import Tool, ToolResult

logger = logging.getLogger("agent42.tools.shell")

MAX_OUTPUT_LENGTH = 10000
DEFAULT_TIMEOUT = 60


class ShellTool(Tool):
    """Execute shell commands within the sandbox with safety filters."""

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
        return "Execute a shell command in the workspace directory. Dangerous commands are blocked."

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

    async def execute(self, command: str = "", **kwargs) -> ToolResult:
        if not command:
            return ToolResult(error="No command provided", success=False)

        # Check command against safety filters
        try:
            self._filter.check(command)
        except CommandFilterError as e:
            logger.warning(f"Blocked command: {command} — {e}")
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
            return ToolResult(
                error=f"Command timed out after {self._timeout} seconds",
                success=False,
            )
        except Exception as e:
            return ToolResult(error=str(e), success=False)
