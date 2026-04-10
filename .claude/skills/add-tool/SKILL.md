---
name: add-tool
description: Scaffold a new Tool with ABC methods, registration, and tests
always: false
task_types: [coding]
---

# /add-tool

Scaffold a new built-in tool for Frood, including the tool implementation, registration, and test file.

## Usage

```
/add-tool
```

This skill is interactive -- it will ask for the required information before generating code.

## Step 1: Gather Input

Ask the developer for:

1. **Tool name** (snake_case, e.g., `my_tool`) -- This becomes the file name and the tool's `name` property.
2. **Brief description** -- One line describing what the tool does (shown to the LLM for function calling).
3. **Parameters** -- For each parameter: name, type (`string`, `integer`, `boolean`, `array`, `object`), and description. Ask if any are required.
4. **ToolContext injection** -- Does this tool need access to `workspace`, `sandbox`, `command_filter`, or other context? If yes, which ones? This determines the `requires` class variable and constructor parameters.

## Step 2: Read Context

Before generating code, read these files:

1. **`tools/base.py`** -- Review the `Tool` ABC interface:
   - `name` (property, abstract) -> str
   - `description` (property, abstract) -> str
   - `parameters` (property, abstract) -> dict (JSON Schema)
   - `execute(**kwargs)` (async, abstract) -> ToolResult
   - `ToolResult(output="", error="", success=True)` dataclass

2. **An existing simple tool** (e.g., `tools/grep.py` or `tools/git.py`) -- Use as a style exemplar for imports, docstrings, error handling patterns, and how `ToolResult` is returned.

3. **`frood.py`** -- Locate the `_register_tools()` method to understand the registration pattern and where to add the new tool.

## Step 3: Generate the Tool File

Create `tools/<tool_name>.py` using this template:

```python
"""<Description> tool for Frood."""

from tools.base import Tool, ToolResult


class <ClassName>Tool(Tool):
    """<Description>.

    <Optional longer description of what the tool does, when it should be
    used, and any important behavior notes.>
    """

    # Uncomment if tool needs ToolContext injection:
    # requires = ["workspace"]

    def __init__(self, workspace="", **kwargs):
        self._workspace = workspace

    @property
    def name(self) -> str:
        return "<tool_name>"

    @property
    def description(self) -> str:
        return "<description>"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "<param_name>": {
                    "type": "<param_type>",
                    "description": "<param_description>",
                },
            },
            "required": ["<param_name>"],
        }

    async def execute(self, <param_name>: str = "", **kwargs) -> ToolResult:
        """Execute the <tool_name> tool.

        Args:
            <param_name>: <param_description>
            **kwargs: Additional parameters (required by Tool ABC).

        Returns:
            ToolResult with the operation output or error.
        """
        try:
            # Implementation here
            # IMPORTANT: All I/O must be async (aiofiles, httpx, etc.)
            result = f"Result for {<param_name>}"
            return ToolResult(output=result)
        except Exception as e:
            return ToolResult(error=str(e), success=False)
```

### Template Rules

1. **Module docstring**: `"""<Description> tool for Frood."""`
2. **Class name**: PascalCase with `Tool` suffix (e.g., `MyTool`, `CodeSearchTool`)
3. **Constructor**: Accept injected context via keyword arguments with defaults. Always include `**kwargs` to handle extra ToolContext fields.
4. **`requires` class variable**: Only add if the tool needs ToolContext injection. List needed keys (e.g., `["workspace", "sandbox"]`).
5. **`name` property**: Return the snake_case tool name string.
6. **`description` property**: Return a clear description that helps the LLM decide when to use this tool.
7. **`parameters` property**: Return valid JSON Schema with `type`, `properties`, and `required` fields.
8. **`execute` method**: MUST be `async`. MUST accept `**kwargs`. MUST return `ToolResult`. Wrap body in try/except returning `ToolResult(error=..., success=False)` on failure.
9. **Async I/O only**: Use `aiofiles` for file operations, `httpx` for HTTP, `asyncio` for subprocess. NEVER use blocking `open()`, `requests`, or `subprocess.run()`.

## Step 4: Register the Tool

Add the tool to `frood.py`:

1. **Import** at the top of the file with other tool imports:
   ```python
   from tools.<tool_name> import <ClassName>Tool
   ```

2. **Register** in `_register_tools()` method, placed in the appropriate section:
   ```python
   self.tool_registry.register(<ClassName>Tool(workspace))
   ```
   If the tool needs sandbox or other context, pass them:
   ```python
   self.tool_registry.register(<ClassName>Tool(workspace=workspace, sandbox=self.sandbox))
   ```

Place the registration in the appropriate comment group within `_register_tools()`:
- **Core tools**: Shell, file, git operations
- **Development tools**: Code search, grep, analysis
- **Advanced tools**: App management, browser, memory

## Step 5: Generate the Test File

Create `tests/test_<tool_name>.py` using this template:

```python
"""Tests for <tool_name> tool."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from tools.<tool_name> import <ClassName>Tool
from tools.base import ToolResult


class Test<ClassName>Tool:
    """Tests for <ClassName>Tool."""

    def setup_method(self):
        """Set up test fixtures."""
        self.tool = <ClassName>Tool(workspace="/tmp/test-workspace")

    def test_tool_name_returns_expected(self):
        """Test tool name property returns correct identifier."""
        assert self.tool.name == "<tool_name>"

    def test_tool_description_is_nonempty(self):
        """Test tool description is a non-empty string."""
        assert isinstance(self.tool.description, str)
        assert len(self.tool.description) > 0

    def test_tool_parameters_valid_schema(self):
        """Test parameters returns valid JSON Schema structure."""
        params = self.tool.parameters
        assert params["type"] == "object"
        assert "properties" in params

    @pytest.mark.asyncio
    async def test_execute_happy_path_returns_success(self):
        """Test execute returns successful result for valid input."""
        result = await self.tool.execute(<param_name>="test_value")
        assert isinstance(result, ToolResult)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_execute_empty_input_handles_gracefully(self):
        """Test execute handles empty input without crashing."""
        result = await self.tool.execute(<param_name>="")
        assert isinstance(result, ToolResult)

    @pytest.mark.asyncio
    async def test_execute_error_returns_failure(self):
        """Test execute returns failure ToolResult on error."""
        # Patch internal dependency to raise an exception
        # with patch("tools.<tool_name>.<dependency>", side_effect=Exception("fail")):
        #     result = await self.tool.execute(<param_name>="test")
        #     assert result.success is False
        #     assert "fail" in result.error
        pass
```

### Test Template Rules

1. **Module docstring**: `"""Tests for <tool_name> tool."""`
2. **Class-based**: `class Test<ClassName>Tool:` with `setup_method`
3. **Metadata tests**: Verify `name`, `description`, and `parameters` schema
4. **`@pytest.mark.asyncio`**: On every async test method
5. **Test naming**: `test_<method>_<scenario>_<expected>`
6. **Mock externals**: Use `unittest.mock.patch` and `AsyncMock` for any external calls (LLM, HTTP, filesystem)
7. **At least 5 tests**: name, description, parameters, happy path execute, edge case execute, error execute

## Step 6: Run Tests

After generating both files, run:

```bash
python -m pytest tests/test_<tool_name>.py -x -q
```

Review results:
- If all tests pass, report success.
- If tests fail, fix the failing tests or tool implementation.
- Re-run until all tests pass.

## What NOT to Do

- Do NOT use blocking I/O in `execute()` -- all I/O must be async per CLAUDE.md
- Do NOT forget `**kwargs` in the `execute()` signature -- the Tool ABC requires it
- Do NOT place plugin/custom tools in `tools/` directly -- only built-in tools go in `tools/`. Plugins go in `CUSTOM_TOOLS_DIR` and are auto-discovered by `tools/plugin_loader.py`
- Do NOT forget to import and register the tool in `frood.py`
- Do NOT use `ToolResult(output=...)` for errors -- use `ToolResult(error=..., success=False)`
- Do NOT hardcode file paths -- use the workspace parameter from ToolContext
- Do NOT create tools that duplicate existing tool functionality -- check `tool_registry` first
