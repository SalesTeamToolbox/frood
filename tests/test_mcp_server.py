"""Tests for MCP server and registry adapter.

Validates:
- Tool schema conversion (to_mcp_schema)
- MCPRegistryAdapter tool listing and execution
- Tool name prefixing/stripping
- Security layer integration (sandbox, command filter)
- MCP server creation and handler registration
"""

import pytest

from core.command_filter import CommandFilter
from core.sandbox import WorkspaceSandbox
from mcp_registry import MCPRegistryAdapter
from tools.base import Tool, ToolResult
from tools.filesystem import ReadFileTool, WriteFileTool
from tools.registry import ToolRegistry
from tools.shell import ShellTool

# ── to_mcp_schema ────────────────────────────────────────────────────────


class TestToMcpSchema:
    def setup_method(self):
        class SimpleTool(Tool):
            @property
            def name(self):
                return "test_tool"

            @property
            def description(self):
                return "A test tool"

            @property
            def parameters(self):
                return {
                    "type": "object",
                    "properties": {"input": {"type": "string"}},
                    "required": ["input"],
                }

            async def execute(self, **kwargs):
                return ToolResult(output="ok")

        self.tool = SimpleTool()

    def test_mcp_schema_has_prefix(self):
        schema = self.tool.to_mcp_schema()
        assert schema["name"] == "frood_test_tool"

    def test_mcp_schema_custom_prefix(self):
        schema = self.tool.to_mcp_schema(prefix="custom")
        assert schema["name"] == "custom_test_tool"

    def test_mcp_schema_no_prefix(self):
        schema = self.tool.to_mcp_schema(prefix="")
        assert schema["name"] == "test_tool"

    def test_mcp_schema_has_description(self):
        schema = self.tool.to_mcp_schema()
        assert schema["description"] == "A test tool"

    def test_mcp_schema_has_input_schema(self):
        schema = self.tool.to_mcp_schema()
        assert schema["inputSchema"]["type"] == "object"
        assert "input" in schema["inputSchema"]["properties"]

    def test_mcp_schema_preserves_required(self):
        schema = self.tool.to_mcp_schema()
        assert schema["inputSchema"]["required"] == ["input"]


# ── MCPRegistryAdapter ───────────────────────────────────────────────────


class TestMCPRegistryAdapter:
    def setup_method(self):
        self.registry = ToolRegistry()

        class EchoTool(Tool):
            @property
            def name(self):
                return "echo"

            @property
            def description(self):
                return "Echo input"

            @property
            def parameters(self):
                return {
                    "type": "object",
                    "properties": {"message": {"type": "string"}},
                }

            async def execute(self, message: str = "", **kwargs):
                return ToolResult(output=f"Echo: {message}")

        class FailTool(Tool):
            @property
            def name(self):
                return "fail"

            @property
            def description(self):
                return "Always fails"

            @property
            def parameters(self):
                return {"type": "object", "properties": {}}

            async def execute(self, **kwargs):
                return ToolResult(error="Intentional failure", success=False)

        self.registry.register(EchoTool())
        self.registry.register(FailTool())
        self.adapter = MCPRegistryAdapter(self.registry)

    def test_list_tools_returns_mcp_types(self):
        tools = self.adapter.list_tools()
        assert len(tools) == 2
        names = {t.name for t in tools}
        assert "frood_echo" in names
        assert "frood_fail" in names

    def test_list_tools_has_descriptions(self):
        tools = self.adapter.list_tools()
        echo = next(t for t in tools if t.name == "frood_echo")
        assert echo.description == "Echo input"

    def test_list_tools_has_input_schema(self):
        tools = self.adapter.list_tools()
        echo = next(t for t in tools if t.name == "frood_echo")
        assert echo.inputSchema["type"] == "object"
        assert "message" in echo.inputSchema["properties"]

    def test_list_tools_excludes_disabled(self):
        self.registry.set_enabled("fail", False)
        tools = self.adapter.list_tools()
        assert len(tools) == 1
        assert tools[0].name == "frood_echo"

    @pytest.mark.asyncio
    async def test_call_tool_success(self):
        result = await self.adapter.call_tool("frood_echo", {"message": "hello"})
        assert len(result) == 1
        assert result[0].text == "Echo: hello"

    @pytest.mark.asyncio
    async def test_call_tool_failure_returns_error_text(self):
        result = await self.adapter.call_tool("frood_fail", {})
        assert len(result) == 1
        assert "Intentional failure" in result[0].text

    @pytest.mark.asyncio
    async def test_call_tool_unknown_returns_error(self):
        result = await self.adapter.call_tool("frood_nonexistent", {})
        assert len(result) == 1
        assert "Unknown tool" in result[0].text

    def test_strip_prefix(self):
        assert self.adapter._strip_prefix("frood_echo") == "echo"
        assert self.adapter._strip_prefix("frood_read_file") == "read_file"
        assert self.adapter._strip_prefix("other_echo") == "other_echo"


# ── Security integration ─────────────────────────────────────────────────


class TestMCPSecurityIntegration:
    def setup_method(self, tmp_path=None):
        # Will be called by pytest with fixtures injected via test methods
        pass

    @pytest.mark.asyncio
    async def test_read_file_within_sandbox(self, tmp_workspace):
        # Create a file in the workspace
        test_file = tmp_workspace / "hello.txt"
        test_file.write_text("Hello from Agent42")

        sandbox = WorkspaceSandbox(str(tmp_workspace), enabled=True)
        registry = ToolRegistry()
        registry.register(ReadFileTool(sandbox))
        adapter = MCPRegistryAdapter(registry)

        result = await adapter.call_tool("frood_read_file", {"path": "hello.txt"})
        assert result[0].text == "Hello from Agent42"

    @pytest.mark.asyncio
    async def test_read_file_blocks_traversal(self, tmp_workspace):
        sandbox = WorkspaceSandbox(str(tmp_workspace), enabled=True)
        registry = ToolRegistry()
        registry.register(ReadFileTool(sandbox))
        adapter = MCPRegistryAdapter(registry)

        result = await adapter.call_tool("frood_read_file", {"path": "../../etc/passwd"})
        assert "Error" in result[0].text

    @pytest.mark.asyncio
    async def test_write_file_within_sandbox(self, tmp_workspace):
        sandbox = WorkspaceSandbox(str(tmp_workspace), enabled=True)
        registry = ToolRegistry()
        registry.register(WriteFileTool(sandbox))
        adapter = MCPRegistryAdapter(registry)

        result = await adapter.call_tool(
            "frood_write_file",
            {"path": "output.txt", "content": "written via MCP"},
        )
        assert "Written" in result[0].text
        assert (tmp_workspace / "output.txt").read_text() == "written via MCP"

    @pytest.mark.asyncio
    async def test_shell_blocks_dangerous_command(self, tmp_workspace):
        sandbox = WorkspaceSandbox(str(tmp_workspace), enabled=True)
        command_filter = CommandFilter()
        registry = ToolRegistry()
        registry.register(ShellTool(sandbox, command_filter))
        adapter = MCPRegistryAdapter(registry)

        result = await adapter.call_tool("frood_shell", {"command": "rm -rf /"})
        # Should be blocked by command filter
        assert "Error" in result[0].text

    @pytest.mark.asyncio
    async def test_shell_allows_safe_command(self, tmp_workspace):
        sandbox = WorkspaceSandbox(str(tmp_workspace), enabled=True)
        command_filter = CommandFilter()
        registry = ToolRegistry()
        registry.register(ShellTool(sandbox, command_filter))
        adapter = MCPRegistryAdapter(registry)

        result = await adapter.call_tool("frood_shell", {"command": "echo hello"})
        assert "hello" in result[0].text


# ── MCP Server creation ──────────────────────────────────────────────────


class TestMCPServerCreation:
    def test_create_server_returns_server_and_adapter(self):
        from mcp_server import _create_server

        server, adapter = _create_server()
        assert server is not None
        assert adapter is not None

    def test_create_server_has_core_tools(self):
        from mcp_server import _create_server

        _server, adapter = _create_server()
        tools = adapter.list_tools()
        names = {t.name for t in tools}
        # Core tools must be present
        assert "frood_context" in names
        assert "frood_memory" in names
        assert "frood_git" in names
        # 25+ tools registered
        assert len(tools) >= 25

    def test_resolve_workspace_defaults_to_cwd(self):

        from mcp_server import _resolve_workspace

        ws = _resolve_workspace()
        assert ws == __import__("pathlib").Path.cwd().resolve()

    def test_resolve_workspace_uses_env(self, tmp_path, monkeypatch):
        from mcp_server import _resolve_workspace

        monkeypatch.setenv("FROOD_WORKSPACE", str(tmp_path))
        ws = _resolve_workspace()
        assert ws == tmp_path.resolve()
