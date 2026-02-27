"""
Tool registry — central registry for all available tools.

Handles tool discovery, registration, execution, and schema generation.
Optionally enforces per-tool rate limiting via ToolRateLimiter.
"""

import logging

from tools.base import Tool, ToolResult

logger = logging.getLogger("agent42.tools.registry")


class ToolRegistry:
    """Manages all available tools for agent execution."""

    def __init__(self, rate_limiter=None):
        self._tools: dict[str, Tool] = {}
        self._rate_limiter = rate_limiter
        self._disabled: set[str] = set()

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

    def set_enabled(self, name: str, enabled: bool) -> bool:
        """Enable or disable a tool by name. Returns True if tool exists."""
        if name not in self._tools:
            return False
        if enabled:
            self._disabled.discard(name)
        else:
            self._disabled.add(name)
        logger.info(f"Tool '{name}' {'enabled' if enabled else 'disabled'}")
        return True

    def is_enabled(self, name: str) -> bool:
        """Return True if the tool exists and is not disabled."""
        return name in self._tools and name not in self._disabled

    async def execute(self, tool_name: str, agent_id: str = "default", **kwargs) -> ToolResult:
        """Execute a tool by name with the given parameters.

        Args:
            tool_name: Name of the registered tool to execute.
            agent_id: Agent identifier for rate limiting.
            **kwargs: Arguments forwarded to the tool's execute() method.

        Note: The first parameter is named ``tool_name`` (not ``name``) to
        avoid collisions when callers spread LLM-provided arguments via
        ``**kwargs`` — many tools declare a ``name`` parameter.
        """
        tool = self._tools.get(tool_name)
        if not tool:
            return ToolResult(error=f"Unknown tool: {tool_name}", success=False)

        if tool_name in self._disabled:
            return ToolResult(error=f"Tool '{tool_name}' is disabled", success=False)

        # Rate limit check
        if self._rate_limiter:
            allowed, reason = self._rate_limiter.check(tool_name, agent_id)
            if not allowed:
                logger.warning(f"Rate limited: {reason}")
                return ToolResult(error=reason, success=False)

        try:
            result = await tool.execute(**kwargs)
        except Exception as e:
            logger.error(f"Tool {tool_name} failed: {e}", exc_info=True)
            return ToolResult(error=str(e), success=False)

        # Record successful call for rate limiting
        if self._rate_limiter:
            self._rate_limiter.record(tool_name, agent_id)

        return result

    def all_schemas(self) -> list[dict]:
        """Get OpenAI function-calling schemas for all enabled tools."""
        return [
            tool.to_schema() for tool in self._tools.values() if tool.name not in self._disabled
        ]

    def list_tools(self) -> list[dict]:
        """List all registered tools with metadata."""
        return [
            {
                "name": t.name,
                "description": t.description,
                "enabled": t.name not in self._disabled,
            }
            for t in self._tools.values()
        ]
