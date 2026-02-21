"""
MCP (Model Context Protocol) client — connects to external MCP servers.

Supports both stdio (local process) and HTTP (remote endpoint) transports.
Tools from MCP servers are auto-discovered and registered with namespaced names.
"""

import asyncio
import json
import logging
import os
import uuid

from tools.base import Tool, ToolResult

logger = logging.getLogger("agent42.tools.mcp")


class MCPConnection:
    """Manages a connection to a single MCP server."""

    def __init__(self, name: str, config: dict):
        self.name = name
        self.config = config
        self.transport = config.get("transport", "stdio")
        self._proc: asyncio.subprocess.Process | None = None
        self._request_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._reader_task: asyncio.Task | None = None

    async def connect(self):
        """Establish connection to the MCP server."""
        if self.transport == "stdio":
            await self._connect_stdio()
        else:
            logger.warning(f"MCP HTTP transport not yet implemented for {self.name}")
            return

        # Initialize the server
        await self._send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "agent42", "version": "0.1.0"},
        })
        await self._send_notification("notifications/initialized", {})
        logger.info(f"MCP server connected: {self.name}")

    async def disconnect(self):
        """Close the connection."""
        if self._reader_task:
            self._reader_task.cancel()
        if self._proc:
            self._proc.terminate()
            await self._proc.wait()
        logger.info(f"MCP server disconnected: {self.name}")

    async def list_tools(self) -> list[dict]:
        """Discover available tools from the server."""
        try:
            result = await self._send_request("tools/list", {})
            return result.get("tools", [])
        except Exception as e:
            logger.error(f"Failed to list tools from {self.name}: {e}")
            return []

    async def call_tool(self, tool_name: str, arguments: dict) -> str:
        """Call a tool on the MCP server."""
        result = await self._send_request("tools/call", {
            "name": tool_name,
            "arguments": arguments,
        })
        # Extract text from content blocks
        content = result.get("content", [])
        texts = []
        for block in content:
            if block.get("type") == "text":
                texts.append(block.get("text", ""))
        return "\n".join(texts) if texts else json.dumps(result)

    async def _connect_stdio(self):
        """Connect via stdio (local process)."""
        command = self.config.get("command", "")
        args = self.config.get("args", [])
        env_overrides = self.config.get("env", {})

        env = os.environ.copy()
        env.update(env_overrides)

        self._proc = await asyncio.create_subprocess_exec(
            command, *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        self._reader_task = asyncio.create_task(self._read_loop())

    async def _read_loop(self):
        """Read JSON-RPC messages from the server."""
        buffer = ""
        while self._proc and self._proc.stdout:
            try:
                line = await self._proc.stdout.readline()
                if not line:
                    break

                text = line.decode("utf-8").strip()
                if not text:
                    continue

                try:
                    msg = json.loads(text)
                except json.JSONDecodeError:
                    continue

                msg_id = msg.get("id")
                if msg_id is not None and msg_id in self._pending:
                    future = self._pending.pop(msg_id)
                    if "error" in msg:
                        future.set_exception(
                            RuntimeError(msg["error"].get("message", "MCP error"))
                        )
                    else:
                        future.set_result(msg.get("result", {}))

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"MCP read error ({self.name}): {e}")

    async def _send_request(self, method: str, params: dict) -> dict:
        """Send a JSON-RPC request and wait for response."""
        self._request_id += 1
        msg_id = self._request_id

        message = {
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": method,
            "params": params,
        }

        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[msg_id] = future

        if self._proc and self._proc.stdin:
            data = json.dumps(message) + "\n"
            self._proc.stdin.write(data.encode("utf-8"))
            await self._proc.stdin.drain()

        return await asyncio.wait_for(future, timeout=30.0)

    async def _send_notification(self, method: str, params: dict):
        """Send a JSON-RPC notification (no response expected)."""
        message = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        if self._proc and self._proc.stdin:
            data = json.dumps(message) + "\n"
            self._proc.stdin.write(data.encode("utf-8"))
            await self._proc.stdin.drain()


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
            return []

    async def disconnect_all(self):
        """Disconnect all MCP servers."""
        for name, conn in self._connections.items():
            await conn.disconnect()
        self._connections.clear()
