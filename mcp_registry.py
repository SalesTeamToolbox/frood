"""
MCP registry adapter — bridges Agent42 ToolRegistry with MCP protocol.

Converts Agent42 Tool instances to MCP tool definitions and routes
MCP tool calls through the existing ToolRegistry with security layers.
"""

import logging

import mcp.types as types

from tools.base import ToolResult
from tools.registry import ToolRegistry

logger = logging.getLogger("agent42.mcp.registry")

# Prefix for all Agent42 tools exposed via MCP
TOOL_PREFIX = "agent42"


class MCPRegistryAdapter:
    """Adapts ToolRegistry for MCP server protocol.

    Handles:
    - Tool name prefixing (``agent42_shell``, ``agent42_read_file``, etc.)
    - Converting Tool schemas to ``mcp.types.Tool`` definitions
    - Routing MCP ``tools/call`` to ``ToolRegistry.execute()``
    - Converting ``ToolResult`` to MCP content blocks
    """

    def __init__(self, registry: ToolRegistry, prefix: str = TOOL_PREFIX):
        self._registry = registry
        self._prefix = prefix

    def list_tools(self) -> list[types.Tool]:
        """Return MCP tool definitions for all enabled tools."""
        tools = []
        for tool_info in self._registry.list_tools():
            if not tool_info["enabled"]:
                continue
            tool = self._registry.get(tool_info["name"])
            if tool is None:
                continue
            schema = tool.to_mcp_schema(prefix=self._prefix)
            tools.append(
                types.Tool(
                    name=schema["name"],
                    description=schema["description"],
                    inputSchema=schema["inputSchema"],
                )
            )
        return tools

    def _strip_prefix(self, mcp_name: str) -> str:
        """Strip the prefix from an MCP tool name to get the internal name."""
        expected = f"{self._prefix}_"
        if mcp_name.startswith(expected):
            return mcp_name[len(expected) :]
        return mcp_name

    async def call_tool(
        self, name: str, arguments: dict
    ) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
        """Execute a tool via MCP and return content blocks."""
        internal_name = self._strip_prefix(name)
        tool = self._registry.get(internal_name)

        if tool is None:
            return [
                types.TextContent(
                    type="text",
                    text=f"Unknown tool: {name} (internal: {internal_name})",
                )
            ]

        logger.info(f"MCP tool call: {name} -> {internal_name}")
        result = await self._registry.execute(internal_name, agent_id="mcp_client", **arguments)

        return self._result_to_content(result)

    def call_tool_is_error(self, name: str, result: ToolResult) -> bool:
        """Check if a tool result should be marked as an MCP error."""
        return not result.success

    @staticmethod
    def _result_to_content(
        result: ToolResult,
    ) -> list[types.TextContent]:
        """Convert a ToolResult to MCP content blocks."""
        if result.success:
            return [types.TextContent(type="text", text=result.output or "(empty)")]
        else:
            # Error with explanation — per CONTEXT.md decision
            error_text = f"Error: {result.error}" if result.error else "Unknown error"
            if result.output:
                error_text = f"{result.output}\n\n{error_text}"
            return [types.TextContent(type="text", text=error_text)]
