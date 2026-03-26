# Architecture Patterns

## All I/O is Async

Every file operation uses `aiofiles`, every HTTP call uses `httpx` or `openai.AsyncOpenAI`,
every queue operation is `asyncio`-native. **Never use blocking I/O** in tool implementations.

```python
# CORRECT
async with aiofiles.open(path, "r") as f:
    content = await f.read()

# WRONG — blocks the event loop
with open(path, "r") as f:
    content = f.read()
```

## Frozen Dataclass Configuration

`Settings` is a frozen dataclass loaded once from environment at import time (`core/config.py`).
When adding new configuration:
1. Add field to `Settings` class with default
2. Add `os.getenv()` call in `Settings.from_env()`
3. Add to `.env.example` with documentation

```python
# Boolean fields use this pattern:
sandbox_enabled=os.getenv("SANDBOX_ENABLED", "true").lower() in ("true", "1", "yes")

# Comma-separated fields have get_*() helper methods:
def get_discord_guild_ids(self) -> list[int]: ...
```

## Plugin Architecture

**Tools (built-in):** Subclass `tools.base.Tool`, implement `name`/`description`/`parameters`/`execute()`,
register in `agent42.py` `_register_tools()`.

```python
class MyTool(Tool):
    @property
    def name(self) -> str: return "my_tool"
    @property
    def description(self) -> str: return "Does something useful"
    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {"input": {"type": "string"}}}
    async def execute(self, input: str = "", **kwargs) -> ToolResult:
        return ToolResult(output=f"Result: {input}")
```

**Tools (custom plugins):** Drop a `.py` file into `CUSTOM_TOOLS_DIR` and it will be
auto-discovered at startup via `tools/plugin_loader.py`. No core code changes needed.
Tools declare dependencies via a `requires` class variable for `ToolContext` injection.

```python
# custom_tools/hello.py
from tools.base import Tool, ToolResult

class HelloTool(Tool):
    requires = ["workspace"]  # Injects workspace from ToolContext

    def __init__(self, workspace="", **kwargs):
        self._workspace = workspace

    @property
    def name(self) -> str: return "hello"
    @property
    def description(self) -> str: return "Says hello"
    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {}}
    async def execute(self, **kwargs) -> ToolResult:
        return ToolResult(output=f"Hello from {self._workspace}!")
```

**Tool extensions (custom plugins):** To *extend* an existing tool instead of
creating a new one, subclass `ToolExtension` instead of `Tool`.  Extensions add
parameters and pre/post execution hooks without replacing the base tool.  Multiple
extensions can layer onto one base — just like skills.

```python
# custom_tools/shell_audit.py
from tools.base import ToolExtension, ToolResult

class ShellAuditExtension(ToolExtension):
    extends = "shell"                      # Name of the tool to extend
    requires = ["workspace"]               # ToolContext injection (same as Tool)

    def __init__(self, workspace="", **kwargs):
        self._workspace = workspace

    @property
    def name(self) -> str: return "shell_audit"

    @property
    def extra_parameters(self) -> dict:    # Merged into the base tool's schema
        return {"audit": {"type": "boolean", "description": "Log command to audit file"}}

    @property
    def description_suffix(self) -> str:   # Appended to the base tool's description
        return "Supports audit logging."

    async def pre_execute(self, **kwargs) -> dict:
        # Called before the base tool — can inspect/modify kwargs
        return kwargs

    async def post_execute(self, result: ToolResult, **kwargs) -> ToolResult:
        # Called after the base tool — can inspect/modify result
        return result
```

**Skills:** Create a directory with `SKILL.md` containing YAML frontmatter:

```markdown
---
name: my-skill
description: One-line description of what this skill does.
always: false
task_types: [coding, debugging]
---

# My Skill

Instructions for the agent when this skill is active...
```

## Graceful Degradation

Redis, Qdrant, channels, and MCP servers are all optional. Code **must** handle their
absence with fallback behavior, never with crashes.

```python
# CORRECT — conditional import and check
if settings.redis_url:
    from memory.redis_session import RedisSessionStore
    session_store = RedisSessionStore(settings.redis_url)
else:
    session_store = FileSessionStore(settings.sessions_dir)

# WRONG — crashes if Redis isn't installed
from memory.redis_session import RedisSessionStore
```

## MCP Architecture (v2.0)

Claude Code provides the intelligence layer (LLM, orchestration). Agent42 provides
the tooling layer via MCP:

- **MCP Server** (`mcp_server.py`) — 36+ tools exposed via stdio transport
- **Memory** — ONNX embeddings + Qdrant for semantic search (~25 MB RAM)
- **Associative Recall** — Hook auto-surfaces relevant memories on every prompt
- **Context Assembler** — `agent42_context` tool pulls from memory, docs, git, skills
- **Dashboard** — FastAPI web UI for monitoring and configuration

## Security Layers (Defense in Depth)

| Layer | Module | Purpose |
|-------|--------|---------|
| 1 | `WorkspaceSandbox` | Path resolution, traversal blocking, symlink defense |
| 2 | `CommandFilter` | 6-layer shell command filtering (structural, deny, interpreter, metachar, indirect, allowlist) |
| 3 | `ApprovalGate` | Human review for protected actions |
| 4 | `ToolRateLimiter` | Per-agent per-tool sliding window |
| 5 | `URLPolicy` | Allowlist/denylist for HTTP requests (SSRF protection) |
| 6 | `BrowserGatewayToken` | Per-session token for browser tool |
| 7 | `SpendingTracker` | Daily API cost cap across all providers |
| 8 | `LoginRateLimit` | Per-IP brute force protection on dashboard |