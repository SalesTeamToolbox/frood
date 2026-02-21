"""
Tool registry — central registry for all available tools.

Handles tool discovery, registration, execution, and schema generation.
"""

import logging
from tools.base import Tool, ToolResult

logger = logging.getLogger("agent42.tools.registry")


class ToolRegistry:
    """Manages all available tools for agent execution."""

    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool):
        """Register a tool."""
        self._tools[tool.name] = tool
        logger.debug(f"Registered tool: {tool.name}")

    def unregister(self, name: str):
        """Remove a tool from the registry."""
        self._tools.pop(name, None)

    def get(self, name: str) -> Tool | None:
        """Get a tool by name."""
        return self._tools.get(name)

    async def execute(self, name: str, **kwargs) -> ToolResult:
        """Execute a tool by name with the given parameters."""
        tool = self._tools.get(name)
        if not tool:
            return ToolResult(error=f"Unknown tool: {name}", success=False)

        try:
            return await tool.execute(**kwargs)
        except Exception as e:
            logger.error(f"Tool {name} failed: {e}", exc_info=True)
            return ToolResult(error=str(e), success=False)

    def all_schemas(self) -> list[dict]:
        """Get OpenAI function-calling schemas for all tools."""
        return [tool.to_schema() for tool in self._tools.values()]

    def list_tools(self) -> list[dict]:
        """List all registered tools with metadata."""
        return [
            {"name": t.name, "description": t.description}
            for t in self._tools.values()
        ]
