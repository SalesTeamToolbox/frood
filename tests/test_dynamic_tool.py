"""Tests for dynamic tool creation."""

import json

import pytest

from tools.base import ToolResult
from tools.dynamic_tool import (
    DYNAMIC_TOOL_PREFIX,
    MAX_DYNAMIC_TOOLS,
    CreateToolTool,
    DynamicTool,
)
from tools.registry import ToolRegistry


class TestDynamicTool:
    """Tests for the DynamicTool class."""

    def _make_tool(self, code: str, name: str = "test_tool", **kwargs):
        return DynamicTool(
            tool_name=name,
            tool_description="A test tool",
            param_schema=kwargs.get(
                "param_schema",
                {
                    "type": "object",
                    "properties": {
                        "input": {"type": "string"},
                    },
                },
            ),
            code=code,
            workspace_path="/tmp",
        )

    def test_name_prefix(self):
        tool = self._make_tool("def run(**kwargs): return 'ok'")
        assert tool.name == f"{DYNAMIC_TOOL_PREFIX}test_tool"

    def test_description_prefix(self):
        tool = self._make_tool("def run(**kwargs): return 'ok'")
        assert tool.description.startswith("[Dynamic]")

    def test_schema_generation(self):
        tool = self._make_tool("def run(**kwargs): return 'ok'")
        schema = tool.to_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == f"{DYNAMIC_TOOL_PREFIX}test_tool"

    @pytest.mark.asyncio
    async def test_execute_simple(self):
        tool = self._make_tool(
            "def run(**kwargs):\n    return f\"Hello {kwargs.get('input', 'world')}\""
        )
        result = await tool.execute(input="Agent42")
        assert result.success is True
        assert "Hello Agent42" in result.output

    @pytest.mark.asyncio
    async def test_execute_no_args(self):
        tool = self._make_tool("def run(**kwargs):\n    return 'no args needed'")
        result = await tool.execute()
        assert result.success is True
        assert "no args needed" in result.output

    @pytest.mark.asyncio
    async def test_execute_returns_json(self):
        tool = self._make_tool(
            "import json\ndef run(**kwargs):\n    return json.dumps({'status': 'ok'})"
        )
        result = await tool.execute()
        assert result.success is True
        data = json.loads(result.output.strip())
        assert data["status"] == "ok"

    @pytest.mark.asyncio
    async def test_execute_bad_code(self):
        tool = self._make_tool("def run(**kwargs):\n    raise ValueError('intentional')")
        result = await tool.execute()
        assert result.success is False

    @pytest.mark.asyncio
    async def test_execute_syntax_error(self):
        tool = self._make_tool("def run(**kwargs:\n    return 'bad syntax'")
        result = await tool.execute()
        assert result.success is False


class TestCreateToolTool:
    """Tests for the CreateToolTool meta-tool."""

    def setup_method(self):
        self.registry = ToolRegistry()
        self.creator = CreateToolTool(self.registry, workspace_path="/tmp")
        self.registry.register(self.creator)

    @pytest.mark.asyncio
    async def test_create_simple_tool(self):
        result = await self.creator.execute(
            tool_name="greet",
            description="Greets someone",
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                },
            },
            code="def run(name='world', **kwargs):\n    return f'Hello {name}'",
        )
        assert result.success is True
        assert "dynamic_greet" in result.output

        # Verify tool was registered
        tool = self.registry.get("dynamic_greet")
        assert tool is not None
        assert tool.description.startswith("[Dynamic]")

    @pytest.mark.asyncio
    async def test_created_tool_is_executable(self):
        await self.creator.execute(
            tool_name="adder",
            description="Adds two numbers",
            parameters={
                "type": "object",
                "properties": {
                    "a": {"type": "number"},
                    "b": {"type": "number"},
                },
            },
            code="def run(a=0, b=0, **kwargs):\n    return str(int(a) + int(b))",
        )

        result = await self.registry.execute("dynamic_adder", a=3, b=5)
        assert result.success is True
        assert "8" in result.output

    @pytest.mark.asyncio
    async def test_reject_invalid_name_uppercase(self):
        result = await self.creator.execute(
            tool_name="MyTool",
            description="Bad name",
            parameters={"type": "object", "properties": {}},
            code="def run(**kwargs): return 'ok'",
        )
        assert result.success is False
        assert "Invalid tool name" in result.error

    @pytest.mark.asyncio
    async def test_reject_invalid_name_too_short(self):
        result = await self.creator.execute(
            tool_name="ab",
            description="Too short",
            parameters={"type": "object", "properties": {}},
            code="def run(**kwargs): return 'ok'",
        )
        assert result.success is False
        assert "Invalid tool name" in result.error

    @pytest.mark.asyncio
    async def test_reject_empty_name(self):
        result = await self.creator.execute(
            tool_name="",
            description="No name",
            parameters={"type": "object", "properties": {}},
            code="def run(**kwargs): return 'ok'",
        )
        assert result.success is False

    @pytest.mark.asyncio
    async def test_reject_missing_run_function(self):
        result = await self.creator.execute(
            tool_name="bad_code",
            description="Missing run",
            parameters={"type": "object", "properties": {}},
            code="def process(**kwargs): return 'wrong name'",
        )
        assert result.success is False
        assert "run(" in result.error

    @pytest.mark.asyncio
    async def test_reject_dangerous_code(self):
        result = await self.creator.execute(
            tool_name="evil_tool",
            description="Dangerous",
            parameters={"type": "object", "properties": {}},
            code="import subprocess\ndef run(**kwargs): return subprocess.check_output(['ls'])",
        )
        assert result.success is False
        assert "Blocked" in result.error

    @pytest.mark.asyncio
    async def test_reject_name_collision_dynamic(self):
        # Create a tool first
        await self.creator.execute(
            tool_name="unique_tool",
            description="First",
            parameters={"type": "object", "properties": {}},
            code="def run(**kwargs): return 'first'",
        )
        # Try to create another with the same name
        result = await self.creator.execute(
            tool_name="unique_tool",
            description="Second",
            parameters={"type": "object", "properties": {}},
            code="def run(**kwargs): return 'second'",
        )
        assert result.success is False
        assert "already exists" in result.error

    @pytest.mark.asyncio
    async def test_reject_builtin_name_collision(self):
        # Register a fake built-in tool
        from tools.base import Tool

        class FakeBuiltin(Tool):
            @property
            def name(self):
                return "shell"

            @property
            def description(self):
                return "Fake"

            @property
            def parameters(self):
                return {"type": "object", "properties": {}}

            async def execute(self, **kw):
                return ToolResult(output="ok")

        self.registry.register(FakeBuiltin())

        result = await self.creator.execute(
            tool_name="shell",
            description="Shadow shell",
            parameters={"type": "object", "properties": {}},
            code="def run(**kwargs): return 'shadowed'",
        )
        assert result.success is False
        assert "built-in" in result.error

    @pytest.mark.asyncio
    async def test_max_dynamic_tools_limit(self):
        for i in range(MAX_DYNAMIC_TOOLS):
            result = await self.creator.execute(
                tool_name=f"tool_{i:03d}",
                description=f"Tool {i}",
                parameters={"type": "object", "properties": {}},
                code=f"def run(**kwargs): return 'tool {i}'",
            )
            assert result.success is True, f"Failed creating tool {i}: {result.error}"

        # The next one should fail
        result = await self.creator.execute(
            tool_name="one_too_many",
            description="Over the limit",
            parameters={"type": "object", "properties": {}},
            code="def run(**kwargs): return 'nope'",
        )
        assert result.success is False
        assert "Maximum" in result.error

    @pytest.mark.asyncio
    async def test_schema_appears_in_registry(self):
        await self.creator.execute(
            tool_name="schema_test",
            description="Test schema visibility",
            parameters={
                "type": "object",
                "properties": {
                    "x": {"type": "string"},
                },
            },
            code="def run(**kwargs): return 'ok'",
        )

        schemas = self.registry.all_schemas()
        names = [s["function"]["name"] for s in schemas]
        assert "dynamic_schema_test" in names

    @pytest.mark.asyncio
    async def test_parameters_as_json_string(self):
        """Parameters can be passed as a JSON string (LLM may do this)."""
        result = await self.creator.execute(
            tool_name="json_params",
            description="Params from string",
            parameters='{"type": "object", "properties": {"x": {"type": "string"}}}',
            code="def run(**kwargs): return 'ok'",
        )
        assert result.success is True

    @pytest.mark.asyncio
    async def test_reject_missing_description(self):
        result = await self.creator.execute(
            tool_name="no_desc",
            description="",
            parameters={"type": "object", "properties": {}},
            code="def run(**kwargs): return 'ok'",
        )
        assert result.success is False

    @pytest.mark.asyncio
    async def test_reject_missing_code(self):
        result = await self.creator.execute(
            tool_name="no_code",
            description="No code provided",
            parameters={"type": "object", "properties": {}},
            code="",
        )
        assert result.success is False
