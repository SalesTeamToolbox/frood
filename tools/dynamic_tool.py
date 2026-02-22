"""
Dynamic tool creation — define and register new tools at runtime.

Allows the agent to create custom tools on-the-fly when existing tools
don't cover the task. Created tools execute user-provided Python code
in a sandboxed subprocess, following the same safety model as PythonExecTool.

Code contract: the provided code must define a `run(**kwargs) -> str` function.
"""

import asyncio
import json
import logging
import os
import re
import tempfile

from tools.base import Tool, ToolResult
from tools.python_exec import PythonExecTool

logger = logging.getLogger("agent42.tools.dynamic_tool")

# Prefix for all dynamically created tools
DYNAMIC_TOOL_PREFIX = "dynamic_"

# Max number of dynamic tools per session
MAX_DYNAMIC_TOOLS = 10

# Valid tool name pattern: alphanumeric + underscores, 3-50 chars
_TOOL_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{2,49}$")


class DynamicTool(Tool):
    """A tool created at runtime from user-provided Python code.

    The code must define a ``run(**kwargs) -> str`` function. When the tool
    is executed, ``run`` is called with the parameters the LLM provided and
    its return value is captured as the tool output.

    Execution happens in an isolated subprocess with the same safety
    guardrails as PythonExecTool (secret stripping, timeout, output limits).
    """

    def __init__(
        self,
        tool_name: str,
        tool_description: str,
        param_schema: dict,
        code: str,
        workspace_path: str = ".",
    ):
        self._name = f"{DYNAMIC_TOOL_PREFIX}{tool_name}"
        self._description = tool_description
        self._param_schema = param_schema
        self._code = code
        self._workspace = workspace_path

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return f"[Dynamic] {self._description}"

    @property
    def parameters(self) -> dict:
        return self._param_schema

    async def execute(self, **kwargs) -> ToolResult:
        """Execute the dynamic tool by running its code in a subprocess."""
        # Build a script that defines the user code then calls run() with kwargs
        kwargs_json = json.dumps(kwargs)
        script = (
            f"{self._code}\n\n"
            f"import json as _json\n"
            f"_kwargs = _json.loads({kwargs_json!r})\n"
            f"_result = run(**_kwargs)\n"
            f"print(str(_result))\n"
        )

        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".py",
            dir=self._workspace,
            delete=False,
        ) as f:
            f.write(script)
            script_path = f.name

        try:
            proc = await asyncio.create_subprocess_exec(
                "python",
                script_path,
                cwd=self._workspace,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=PythonExecTool._safe_env(),
            )

            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
            except TimeoutError:
                proc.kill()
                return ToolResult(
                    error="Dynamic tool execution timed out after 30s",
                    success=False,
                )

            output = stdout.decode("utf-8", errors="replace")
            errors = stderr.decode("utf-8", errors="replace")

            if len(output) > 50000:
                output = output[:50000] + "\n... (output truncated)"

            if proc.returncode != 0:
                return ToolResult(
                    output=output,
                    error=f"Exit code {proc.returncode}:\n{errors}",
                    success=False,
                )

            result = output.strip() if output.strip() else "(no output)"
            if errors.strip():
                result += f"\nSTDERR:\n{errors}"
            return ToolResult(output=result, success=True)

        finally:
            try:
                os.unlink(script_path)
            except OSError:
                pass


class CreateToolTool(Tool):
    """Meta-tool that creates and registers new tools at runtime.

    The LLM calls this tool to define a new tool by providing its name,
    description, parameter schema, and Python implementation code. The
    new tool is immediately registered and available for subsequent calls.
    """

    def __init__(self, registry, workspace_path: str = "."):
        self._registry = registry
        self._workspace = workspace_path
        self._dynamic_count = 0

    @property
    def name(self) -> str:
        return "create_tool"

    @property
    def description(self) -> str:
        return (
            "Create a new tool at runtime. Provide a name, description, "
            "JSON Schema for parameters, and Python code defining a "
            "`run(**kwargs) -> str` function. The tool will be immediately "
            "available for use."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "tool_name": {
                    "type": "string",
                    "description": (
                        "Unique name for the tool (lowercase, alphanumeric + "
                        "underscores, 3-50 chars). Will be prefixed with 'dynamic_'."
                    ),
                },
                "description": {
                    "type": "string",
                    "description": "What the tool does — shown to the LLM.",
                },
                "parameters": {
                    "type": "object",
                    "description": (
                        "JSON Schema for the tool's parameters. Must have "
                        "'type': 'object' and 'properties' dict."
                    ),
                },
                "code": {
                    "type": "string",
                    "description": (
                        "Python code that defines a `run(**kwargs) -> str` function. "
                        "The function receives the tool parameters as keyword arguments "
                        "and must return a string result."
                    ),
                },
            },
            "required": ["tool_name", "description", "parameters", "code"],
        }

    async def execute(
        self,
        tool_name: str = "",
        description: str = "",
        parameters: dict | str = None,
        code: str = "",
        **kwargs,
    ) -> ToolResult:
        # --- Validation ---

        # 1. Check dynamic tool limit
        if self._dynamic_count >= MAX_DYNAMIC_TOOLS:
            return ToolResult(
                error=f"Maximum dynamic tools reached ({MAX_DYNAMIC_TOOLS}). "
                f"Cannot create more tools in this session.",
                success=False,
            )

        # 2. Validate tool name
        if not tool_name:
            return ToolResult(error="tool_name is required", success=False)

        if not _TOOL_NAME_RE.match(tool_name):
            return ToolResult(
                error=f"Invalid tool name '{tool_name}'. Must be lowercase "
                f"alphanumeric + underscores, 3-50 chars, starting with a letter.",
                success=False,
            )

        # 3. Check for name collision
        full_name = f"{DYNAMIC_TOOL_PREFIX}{tool_name}"
        if self._registry.get(full_name):
            return ToolResult(
                error=f"Tool '{full_name}' already exists. Choose a different name.",
                success=False,
            )

        # Also prevent shadowing built-in tools
        if self._registry.get(tool_name):
            return ToolResult(
                error=f"A built-in tool named '{tool_name}' already exists. "
                f"Choose a different name.",
                success=False,
            )

        # 4. Validate description
        if not description:
            return ToolResult(error="description is required", success=False)

        # 5. Validate parameters schema
        if parameters is None:
            parameters = {"type": "object", "properties": {}}

        if isinstance(parameters, str):
            try:
                parameters = json.loads(parameters)
            except json.JSONDecodeError:
                return ToolResult(
                    error="parameters must be a valid JSON Schema object",
                    success=False,
                )

        if not isinstance(parameters, dict):
            return ToolResult(
                error="parameters must be a JSON Schema object",
                success=False,
            )

        # 6. Validate code
        if not code:
            return ToolResult(error="code is required", success=False)

        if "def run(" not in code:
            return ToolResult(
                error="Code must define a `run(**kwargs) -> str` function.",
                success=False,
            )

        # 7. Safety check — reuse python_exec patterns
        safety_error = PythonExecTool._check_code_safety(code)
        if safety_error:
            return ToolResult(error=safety_error, success=False)

        # --- Create and register ---
        try:
            dynamic_tool = DynamicTool(
                tool_name=tool_name,
                tool_description=description,
                param_schema=parameters,
                code=code,
                workspace_path=self._workspace,
            )

            self._registry.register(dynamic_tool)
            self._dynamic_count += 1

            _schema = dynamic_tool.to_schema()
            logger.info(f"Created dynamic tool: {full_name}")

            return ToolResult(
                output=(
                    f"Tool '{full_name}' created and registered successfully.\n"
                    f"Description: {description}\n"
                    f"Parameters: {json.dumps(parameters, indent=2)}\n"
                    f"The tool is now available for use."
                ),
                success=True,
            )

        except Exception as e:
            logger.error(f"Failed to create dynamic tool: {e}", exc_info=True)
            return ToolResult(error=f"Failed to create tool: {e}", success=False)
