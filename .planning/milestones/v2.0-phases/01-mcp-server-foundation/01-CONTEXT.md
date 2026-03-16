# Phase 1: MCP Server Foundation - Context

**Gathered:** 2026-03-15
**Status:** Ready for planning

<domain>
## Phase Boundary

Create a stdio MCP server that exposes Agent42 tools to Claude Code. A minimal proof-of-concept tool set (filesystem + shell) demonstrates the integration works end-to-end with security layers enforced. Also migrate the existing MCP client to use the official SDK for consistency.

</domain>

<decisions>
## Implementation Decisions

### MCP SDK Approach
- Use the official `mcp` Python SDK (`pip install mcp`) for the server
- Migrate existing `tools/mcp_client.py` from raw JSON-RPC to the SDK as well
- Both client and server use the same SDK — one consistent approach
- SDK handles protocol negotiation, schema validation, and transport layers
- Phase 7 (SSE transport for remote node) comes nearly free with the SDK

### Tool Naming Convention
- All Agent42 MCP tools use `agent42_` prefix: `agent42_shell`, `agent42_read_file`, etc.
- Avoids conflicts with Claude Code built-in tools (Read, Write, Bash, Grep)
- For Phase 7 multi-node: MCP server name handles distinction (`agent42` vs `agent42_remote`), not tool-level prefixes
- Claude Code auto-prefixes with server name in its internal routing

### Proof-of-Concept Tool Set
- Phase 1 ships with **3 tools only**: `agent42_shell`, `agent42_read_file`, `agent42_write_file`
- Shell tool includes CommandFilter security layer
- Filesystem tools include WorkspaceSandbox security layer
- This minimal set proves: MCP protocol works, security layers enforce, basic I/O flows end-to-end
- All remaining tools (memory, git, browser, etc.) come in Phase 2

### Security Layer Integration
- Tools operate within a sandbox-scoped workspace set by `AGENT42_WORKSPACE` env var (or cwd)
- WorkspaceSandbox enforces path boundaries on filesystem tools
- CommandFilter enforces shell command restrictions
- **Error with explanation**: blocked commands return MCP error with reason (e.g., "Command blocked by security filter: rm -rf denied"). Transparent — Claude Code sees the error and adjusts.
- **Claude Code handles approvals**: ApprovalGate is NOT used in MCP mode. Claude Code's built-in permission system handles user confirmation. No need to duplicate.
- Rate limiter wraps MCP tool execution (same as internal agent execution)

### Claude's Discretion
- MCP server module structure (single file vs package)
- Tool schema adapter implementation details
- Test structure and coverage approach
- Logging and error handling patterns

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### MCP Protocol
- Official MCP Python SDK docs — use Context7 to fetch current API for `mcp` library
- MCP specification (protocol version `2024-11-05`) — as used in existing `tools/mcp_client.py`

### Existing Code (must-read before implementation)
- `tools/base.py` — Tool ABC, ToolResult, ToolExtension, ExtendedTool. Has `to_schema()` for OpenAI format; needs MCP equivalent `to_mcp_schema()`
- `tools/registry.py` — ToolRegistry with `all_schemas()`, `execute()`, `list_tools()`. Maps directly to MCP `tools/list` and `tools/call`
- `tools/mcp_client.py` — Current raw JSON-RPC MCP client (MCPConnection, MCPToolProxy, MCPManager). Being migrated to SDK
- `tools/plugin_loader.py` — Auto-discovers custom tools from `CUSTOM_TOOLS_DIR`
- `tools/context.py` — ToolContext class for dependency injection into tools
- `core/sandbox.py` — WorkspaceSandbox (path resolution, traversal blocking)
- `core/command_filter.py` — CommandFilter (6-layer shell command filtering)
- `core/rate_limiter.py` — ToolRateLimiter (per-agent per-tool sliding window)
- `tools/filesystem.py` — ReadFileTool, WriteFileTool (existing implementations)
- `tools/shell.py` — ShellTool (existing implementation with command filter)

### Configuration
- `.mcp.json` — Claude Code MCP server configuration format
- `core/config.py` — Settings class, `AGENT42_WORKSPACE` env var handling

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `Tool` ABC (`tools/base.py`): Already has `name`, `description`, `parameters`, `execute()`, `to_schema()`. Adding `to_mcp_schema()` is straightforward — same data, different format
- `ToolRegistry` (`tools/registry.py`): `all_schemas()` → MCP `tools/list`; `execute()` → MCP `tools/call`. Almost a 1:1 mapping
- `ToolExtension` / `ExtendedTool`: Extension system should work transparently through MCP — extensions wrap the base tool's execute, MCP just calls the final tool
- `PluginLoader` (`tools/plugin_loader.py`): Custom tools auto-discovered and registered will automatically become MCP tools if the registry serves MCP
- `ShellTool` (`tools/shell.py`): Already integrates with CommandFilter and sandbox
- `ReadFileTool` / `WriteFileTool` (`tools/filesystem.py`): Already integrate with sandbox

### Established Patterns
- All tools are async (`async def execute(**kwargs) -> ToolResult`)
- Tools declare dependencies via `requires` class variable for ToolContext injection
- `ToolResult(output=str, error=str, success=bool)` is the universal return type — maps to MCP `TextContent` + `isError`
- Security layers are injected at construction time, not per-call

### Integration Points
- `agent42.py:_register_tools()` — where all 41+ tools are instantiated with their dependencies (sandbox, command_filter, etc.)
- `agent42.py:_setup_mcp()` — where MCP client connections are established (will add server setup here too)
- `.mcp.json` in project root — Claude Code reads this to discover MCP servers

</code_context>

<specifics>
## Specific Ideas

- The MCP server should be launchable standalone (`python mcp_server.py`) for Claude Code integration, independent of the dashboard
- `.mcp.json` should use `${workspaceFolder}` variable for workspace path so it works across projects
- The `agent42_` prefix was chosen over shorter `a42_` for clarity and zero ambiguity

</specifics>

<deferred>
## Deferred Ideas

- Memory tools (Phase 2/3)
- All remaining 38+ tools (Phase 2)
- SSE/HTTP transport for remote node (Phase 7)
- ApprovalGate integration via MCP (Phase 6 — dashboard redesign)
- Custom tool hot-reload in MCP mode

</deferred>

---

*Phase: 01-mcp-server-foundation*
*Context gathered: 2026-03-15*
