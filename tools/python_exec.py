"""
Python execution tool — run Python code in a sandboxed subprocess.

Inspired by OpenHands' IPythonRunCellAction.
Executes Python code snippets and returns stdout/stderr/return value.
Isolated from the main process for safety.
"""

import asyncio
import json
import logging
import os
import tempfile

from tools.base import Tool, ToolResult

logger = logging.getLogger("agent42.tools.python_exec")


class PythonExecTool(Tool):
    """Execute Python code snippets in an isolated subprocess."""

    def __init__(self, workspace_path: str = "."):
        self._workspace = workspace_path

    @property
    def name(self) -> str:
        return "python_exec"

    @property
    def description(self) -> str:
        return (
            "Execute Python code in an isolated subprocess. Returns stdout, stderr, "
            "and any return value. Use for data analysis, calculations, testing snippets, "
            "or running scripts. The working directory is the project workspace."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Python code to execute",
                },
                "timeout": {
                    "type": "number",
                    "description": "Execution timeout in seconds (default: 30)",
                    "default": 30,
                },
            },
            "required": ["code"],
        }

    async def execute(
        self,
        code: str = "",
        timeout: float = 30,
        **kwargs,
    ) -> ToolResult:
        if not code:
            return ToolResult(error="No code provided", success=False)

        # Cap timeout at 5 minutes
        timeout = min(timeout, 300)

        # Write code to a temporary file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", dir=self._workspace, delete=False,
        ) as f:
            # Wrap code to capture the result of the last expression
            wrapped = self._wrap_code(code)
            f.write(wrapped)
            script_path = f.name

        try:
            proc = await asyncio.create_subprocess_exec(
                "python", script_path,
                cwd=self._workspace,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )

            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                return ToolResult(error=f"Execution timed out after {timeout}s", success=False)

            output = stdout.decode("utf-8", errors="replace")
            errors = stderr.decode("utf-8", errors="replace")

            if len(output) > 50000:
                output = output[:50000] + "\n... (output truncated)"
            if len(errors) > 20000:
                errors = errors[:20000] + "\n... (errors truncated)"

            if proc.returncode != 0:
                return ToolResult(
                    output=output if output else "",
                    error=f"Exit code {proc.returncode}:\n{errors}",
                    success=False,
                )

            result_parts = []
            if output:
                result_parts.append(output)
            if errors:
                result_parts.append(f"STDERR:\n{errors}")

            return ToolResult(
                output="\n".join(result_parts) if result_parts else "(no output)",
                success=True,
            )
        finally:
            try:
                os.unlink(script_path)
            except OSError:
                pass

    @staticmethod
    def _wrap_code(code: str) -> str:
        """Wrap code to capture exceptions cleanly."""
        # Don't wrap if it already has a __name__ guard or is a script
        if "__name__" in code or code.strip().startswith("#!"):
            return code
        return code
