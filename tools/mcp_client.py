"""
MCP (Model Context Protocol) client — connects to external MCP servers.

Uses the official ``mcp`` Python SDK for protocol handling.
Supports stdio (local process) transport.  SSE/HTTP planned for Phase 7.

Tools from MCP servers are auto-discovered and registered with namespaced names.
"""

import logging
import os
import shutil
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from tools.base import Tool, ToolResult

logger = logging.getLogger("agent42.tools.mcp")


class MCPConnection:
    """Manages a connection to a single MCP server via the MCP SDK."""

    # Commands that are allowed for MCP stdio servers
    _ALLOWED_MCP_COMMANDS = {
        "npx",
        "node",
        "python",
        "python3",
        "uvx",
        "uv",
        "docker",
        "deno",
        "bun",
    }

    # Env keys that cannot be overridden by MCP server configs
    _BLOCKED_ENV_KEYS = {"PATH", "LD_PRELOAD", "LD_LIBRARY_PATH", "PYTHONPATH"}

    def __init__(self, name: str, config: dict):
        self.name = name
        self.config = config
        self._exit_stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None

    async def connect(self):
        """Establish connection to the MCP server using the SDK."""
        command = self.config.get("command", "")
        args = self.config.get("args", [])
        env_overrides = self.config.get("env", {})

        # Validate command against allowlist
        resolved_command = self._validate_command(command)

        # Sanitize env overrides
        sanitized_env = {}
        for key, value in env_overrides.items():
            if key.upper() in self._BLOCKED_ENV_KEYS:
                logger.warning(f"MCP server {self.name}: blocked env override '{key}'")
            else:
                sanitized_env[key] = value

        env = dict(os.environ)
        env.update(sanitized_env)

        server_params = StdioServerParameters(
            command=resolved_command,
            args=args,
            env=env,
        )

        # Use AsyncExitStack to manage SDK context managers with explicit lifecycle
        self._exit_stack = AsyncExitStack()
        await self._exit_stack.__aenter__()

        read_stream, write_stream = await self._exit_stack.enter_async_context(
            stdio_client(server_params)
        )
        self._session = await self._exit_stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await self._session.initialize()

        logger.info(f"MCP server connected: {self.name}")

    async def disconnect(self):
        """Close the connection."""
        if self._exit_stack:
            await self._exit_stack.__aexit__(None, None, None)
            self._exit_stack = None
            self._session = None
        logger.info(f"MCP server disconnected: {self.name}")

    async def list_tools(self) -> list[dict]:
        """Discover available tools from the server."""
        if not self._session:
            return []
        try:
            result = await self._session.list_tools()
            return [
                {
                    "name": t.name,
                    "description": t.description or "",
                    "inputSchema": t.inputSchema if hasattr(t, "inputSchema") else {},
                }
                for t in result.tools
            ]
        except Exception as e:
            logger.error(f"Failed to list tools from {self.name}: {e}")
            return []

    async def call_tool(self, tool_name: str, arguments: dict) -> str:
        """Call a tool on the MCP server."""
        if not self._session:
            raise RuntimeError(f"MCP server {self.name} not connected")

        result = await self._session.call_tool(tool_name, arguments=arguments)

        # Extract text from content blocks
        texts = []
        for block in result.content:
            if hasattr(block, "text"):
                texts.append(block.text)
        return "\n".join(texts) if texts else str(result)

    @classmethod
    def _validate_command(cls, command: str) -> str:
        """Validate the MCP server command against an allowlist.

        Only known MCP server runners are allowed to prevent arbitrary
        code execution via malicious mcp_servers.json configs.
        """
        if not command:
            raise ValueError("MCP server command cannot be empty")

        # Extract base command name (strip path)
        base = os.path.basename(command)

        if base not in cls._ALLOWED_MCP_COMMANDS:
            raise ValueError(
                f"MCP command '{command}' not in allowlist. "
                f"Allowed: {', '.join(sorted(cls._ALLOWED_MCP_COMMANDS))}"
            )

        # Resolve to full path to avoid PATH manipulation attacks
        resolved = shutil.which(command)
        if not resolved:
            raise FileNotFoundError(f"MCP command not found: {command}")

        return resolved


class MCPToolProxy(Tool):
    """Proxy tool that forwards calls to an MCP server."""

    def __init__(self, server_name: str, tool_info: dict, connection: MCPConnection):
        self._server_name = server_name
        self._tool_name = tool_info.get("name", "")
        self._description = tool_info.get("description", "")
        self._schema = tool_info.get("inputSchema", {"type": "object", "properties": {}})
        self._connection = connection

    @property
    def name(self) -> str:
        return f"mcp_{self._server_name}_{self._tool_name}"

    @property
    def description(self) -> str:
        return f"[MCP:{self._server_name}] {self._description}"

    @property
    def parameters(self) -> dict:
        return self._schema

    async def execute(self, **kwargs) -> ToolResult:
        try:
            result = await self._connection.call_tool(self._tool_name, kwargs)
            return ToolResult(output=result)
        except Exception as e:
            return ToolResult(error=f"MCP tool error: {e}", success=False)


class MCPManager:
    """Manages connections to multiple MCP servers."""

    def __init__(self):
        self._connections: dict[str, MCPConnection] = {}

    async def connect_server(self, name: str, config: dict) -> list[Tool]:
        """Connect to an MCP server and return proxy tools for its capabilities."""
        conn = MCPConnection(name, config)
        try:
            await conn.connect()
            self._connections[name] = conn

            # Discover tools
            tool_infos = await conn.list_tools()
            tools = [MCPToolProxy(name, info, conn) for info in tool_infos]

            logger.info(f"MCP server {name}: discovered {len(tools)} tools")
            return tools

        except Exception as e:
            logger.error(f"Failed to connect MCP server {name}: {e}")
            try:
                await conn.disconnect()
            except Exception:
                pass
            return []

    async def disconnect_all(self):
        """Disconnect all MCP servers."""
        for name, conn in self._connections.items():
            await conn.disconnect()
        self._connections.clear()
