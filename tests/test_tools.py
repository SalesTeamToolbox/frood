"""Tests for Phase 4: Tool ecosystem."""

import pytest

from core.command_filter import CommandFilter
from core.sandbox import WorkspaceSandbox
from tools.base import Tool, ToolResult
from tools.registry import ToolRegistry


class MockTool(Tool):
    @property
    def name(self):
        return "mock_tool"

    @property
    def description(self):
        return "A mock tool for testing"

    @property
    def parameters(self):
        return {
            "type": "object",
            "properties": {
                "input": {"type": "string"},
            },
        }

    async def execute(self, input: str = "", **kwargs):
        return ToolResult(output=f"Processed: {input}")


class FailingTool(Tool):
    @property
    def name(self):
        return "failing_tool"

    @property
    def description(self):
        return "Always fails"

    @property
    def parameters(self):
        return {"type": "object", "properties": {}}

    async def execute(self, **kwargs):
        raise ValueError("Intentional failure")


class TestToolResult:
    def test_success_result(self):
        r = ToolResult(output="hello", success=True)
        assert r.content == "hello"

    def test_error_result(self):
        r = ToolResult(error="bad input", success=False)
        assert r.content == "Error: bad input"


class TestToolSchema:
    def test_to_schema(self):
        tool = MockTool()
        schema = tool.to_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "mock_tool"
        assert schema["function"]["description"] == "A mock tool for testing"


class TestToolRegistry:
    def setup_method(self):
        self.registry = ToolRegistry()

    def test_register_and_get(self):
        tool = MockTool()
        self.registry.register(tool)
        assert self.registry.get("mock_tool") is tool

    def test_get_unknown_returns_none(self):
        assert self.registry.get("nonexistent") is None

    @pytest.mark.asyncio
    async def test_execute_tool(self):
        self.registry.register(MockTool())
        result = await self.registry.execute("mock_tool", input="test")
        assert result.success is True
        assert result.output == "Processed: test"

    @pytest.mark.asyncio
    async def test_execute_unknown_tool(self):
        result = await self.registry.execute("nonexistent")
        assert result.success is False
        assert "Unknown tool" in result.error

    @pytest.mark.asyncio
    async def test_execute_failing_tool(self):
        self.registry.register(FailingTool())
        result = await self.registry.execute("failing_tool")
        assert result.success is False
        assert "Intentional failure" in result.error

    def test_unregister(self):
        self.registry.register(MockTool())
        self.registry.unregister("mock_tool")
        assert self.registry.get("mock_tool") is None

    def test_all_schemas(self):
        self.registry.register(MockTool())
        schemas = self.registry.all_schemas()
        assert len(schemas) == 1
        assert schemas[0]["function"]["name"] == "mock_tool"

    def test_list_tools(self):
        self.registry.register(MockTool())
        tools = self.registry.list_tools()
        assert len(tools) == 1
        assert tools[0]["name"] == "mock_tool"
        assert tools[0]["enabled"] is True

    def test_set_enabled_disable(self):
        self.registry.register(MockTool())
        result = self.registry.set_enabled("mock_tool", False)
        assert result is True
        assert self.registry.is_enabled("mock_tool") is False
        tools = self.registry.list_tools()
        assert tools[0]["enabled"] is False

    def test_set_enabled_reenable(self):
        self.registry.register(MockTool())
        self.registry.set_enabled("mock_tool", False)
        self.registry.set_enabled("mock_tool", True)
        assert self.registry.is_enabled("mock_tool") is True

    def test_set_enabled_unknown_tool(self):
        result = self.registry.set_enabled("nonexistent", False)
        assert result is False

    def test_all_schemas_excludes_disabled(self):
        self.registry.register(MockTool())
        self.registry.set_enabled("mock_tool", False)
        schemas = self.registry.all_schemas()
        assert len(schemas) == 0

    @pytest.mark.asyncio
    async def test_execute_disabled_tool_returns_error(self):
        self.registry.register(MockTool())
        self.registry.set_enabled("mock_tool", False)
        result = await self.registry.execute("mock_tool", input="test")
        assert result.success is False
        assert "disabled" in result.error


class MockCodeTool(Tool):
    """A mock tool whose name is in _CODE_ONLY_TOOLS for task-type filtering tests."""

    @property
    def name(self):
        return "shell"

    @property
    def description(self):
        return "Mock shell tool"

    @property
    def parameters(self):
        return {"type": "object", "properties": {"command": {"type": "string"}}}

    async def execute(self, command: str = "", **kwargs):
        return ToolResult(output=f"Ran: {command}")


class TestTaskTypeFiltering:
    """Test that schemas_for_task_type properly filters code-only tools."""

    def setup_method(self):
        self.registry = ToolRegistry()
        self.registry.register(MockTool())  # general-purpose tool
        self.registry.register(MockCodeTool())  # code-only tool (name="shell")

    def test_code_task_sees_all_tools(self):
        """Code task types should see all tools including code-only ones."""
        from tools.registry import _CODE_TASK_TYPES

        for task_type in _CODE_TASK_TYPES:
            schemas = self.registry.schemas_for_task_type(task_type)
            names = {s["function"]["name"] for s in schemas}
            assert "shell" in names, f"Code task '{task_type}' should see 'shell'"
            assert "mock_tool" in names

    def test_non_code_task_excludes_code_tools(self):
        """Non-code task types should NOT see code-only tools."""
        for task_type in ("content", "marketing", "email", "strategy", "research"):
            schemas = self.registry.schemas_for_task_type(task_type)
            names = {s["function"]["name"] for s in schemas}
            assert "shell" not in names, f"Non-code task '{task_type}' should NOT see 'shell'"
            assert "mock_tool" in names  # general-purpose still visible

    def test_disabled_tool_excluded_from_filtered_schemas(self):
        """Disabled tools are excluded even for code task types."""
        self.registry.set_enabled("shell", False)
        schemas = self.registry.schemas_for_task_type("coding")
        names = {s["function"]["name"] for s in schemas}
        assert "shell" not in names

    def test_all_code_only_tools_listed(self):
        """Every tool in _CODE_ONLY_TOOLS should be a recognized code tool name."""
        from tools.registry import _CODE_ONLY_TOOLS

        # These are the tools that should be restricted — verify the set is non-empty
        assert len(_CODE_ONLY_TOOLS) > 0
        # shell, git, security_analyzer should all be in the set
        for expected in ("shell", "git", "security_analyzer", "test_runner"):
            assert expected in _CODE_ONLY_TOOLS


class TestShellTool:
    @pytest.mark.asyncio
    async def test_safe_command(self):
        import tempfile

        from tools.shell import ShellTool

        tmpdir = tempfile.mkdtemp()
        sandbox = WorkspaceSandbox(tmpdir)
        tool = ShellTool(sandbox, CommandFilter())
        result = await tool.execute(command="echo hello")
        assert result.success is True
        assert "hello" in result.output

    @pytest.mark.asyncio
    async def test_blocked_command(self):
        import tempfile

        from tools.shell import ShellTool

        tmpdir = tempfile.mkdtemp()
        sandbox = WorkspaceSandbox(tmpdir)
        tool = ShellTool(sandbox, CommandFilter())
        result = await tool.execute(command="rm -rf /")
        assert result.success is False
        assert "Blocked" in result.error

    @pytest.mark.asyncio
    async def test_empty_command(self):
        import tempfile

        from tools.shell import ShellTool

        tmpdir = tempfile.mkdtemp()
        sandbox = WorkspaceSandbox(tmpdir)
        tool = ShellTool(sandbox, CommandFilter())
        result = await tool.execute(command="")
        assert result.success is False


class TestFilesystemTools:
    @pytest.mark.asyncio
    async def test_write_and_read(self):
        import tempfile

        from tools.filesystem import ReadFileTool, WriteFileTool

        tmpdir = tempfile.mkdtemp()
        sandbox = WorkspaceSandbox(tmpdir)

        writer = WriteFileTool(sandbox)
        result = await writer.execute(path="test.txt", content="hello world")
        assert result.success is True

        reader = ReadFileTool(sandbox)
        result = await reader.execute(path="test.txt")
        assert result.success is True
        assert result.output == "hello world"

    @pytest.mark.asyncio
    async def test_read_nonexistent(self):
        import tempfile

        from tools.filesystem import ReadFileTool

        tmpdir = tempfile.mkdtemp()
        sandbox = WorkspaceSandbox(tmpdir)
        reader = ReadFileTool(sandbox)
        result = await reader.execute(path="nope.txt")
        assert result.success is False

    @pytest.mark.asyncio
    async def test_edit_file(self):
        import tempfile

        from tools.filesystem import EditFileTool, ReadFileTool, WriteFileTool

        tmpdir = tempfile.mkdtemp()
        sandbox = WorkspaceSandbox(tmpdir)

        writer = WriteFileTool(sandbox)
        await writer.execute(path="edit_test.txt", content="foo bar baz")

        editor = EditFileTool(sandbox)
        result = await editor.execute(path="edit_test.txt", old_string="bar", new_string="qux")
        assert result.success is True

        reader = ReadFileTool(sandbox)
        result = await reader.execute(path="edit_test.txt")
        assert result.output == "foo qux baz"

    @pytest.mark.asyncio
    async def test_sandbox_violation(self):
        import tempfile

        from tools.filesystem import ReadFileTool

        tmpdir = tempfile.mkdtemp()
        sandbox = WorkspaceSandbox(tmpdir)
        reader = ReadFileTool(sandbox)
        result = await reader.execute(path="/etc/passwd")
        assert result.success is False
        assert "Sandbox" in result.error

    @pytest.mark.asyncio
    async def test_list_dir(self):
        import tempfile

        from tools.filesystem import ListDirTool, WriteFileTool

        tmpdir = tempfile.mkdtemp()
        sandbox = WorkspaceSandbox(tmpdir)

        writer = WriteFileTool(sandbox)
        await writer.execute(path="file1.txt", content="a")
        await writer.execute(path="file2.txt", content="b")

        lister = ListDirTool(sandbox)
        result = await lister.execute(path=".")
        assert result.success is True
        assert "file1.txt" in result.output
        assert "file2.txt" in result.output
