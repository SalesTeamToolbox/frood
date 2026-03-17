"""
Agent42 MCP Server — exposes Agent42 tools and skills to Claude Code via MCP.

Phase 4: Skills as MCP Prompts — all tools + 43 skills exposed via MCP protocol.

Capabilities:
- Tools:   41+ tools (filesystem, git, memory, web, devops, etc.)
- Prompts: 43 skills (debugging, code-review, security, memory, etc.)

Usage:
    python mcp_server.py                     # stdio transport (Claude Code)
    python mcp_server.py --transport sse     # SSE transport (remote node, Phase 7)

Claude Code integration (.mcp.json):
    {
      "mcpServers": {
        "agent42": {
          "command": "python",
          "args": ["path/to/agent42/mcp_server.py"],
          "env": { "AGENT42_WORKSPACE": "${workspaceFolder}" }
        }
      }
    }
"""

import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Any

import mcp.server.stdio
import mcp.types as types
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.models import InitializationOptions

# Ensure the agent42 package root is importable
_AGENT42_ROOT = Path(__file__).resolve().parent
if str(_AGENT42_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENT42_ROOT))

from core.command_filter import CommandFilter
from core.rate_limiter import ToolRateLimiter
from core.sandbox import WorkspaceSandbox
from mcp_registry import MCPRegistryAdapter
from tools.registry import ToolRegistry

logger = logging.getLogger("agent42.mcp.server")

# ---------------------------------------------------------------------------
# Server version — used in MCP initialize handshake
# ---------------------------------------------------------------------------
SERVER_NAME = "agent42"
SERVER_VERSION = "2.0.0-alpha"


def _resolve_workspace() -> Path:
    """Determine the workspace directory.

    Priority:
    1. AGENT42_WORKSPACE env var
    2. Current working directory
    """
    ws = os.environ.get("AGENT42_WORKSPACE", "")
    if ws:
        return Path(ws).resolve()
    return Path.cwd().resolve()


def _safe_import(module_path: str, class_name: str):
    """Import a tool class, returning None if the import fails.

    Allows the MCP server to start even if optional dependencies are missing.
    """
    try:
        import importlib

        mod = importlib.import_module(module_path)
        return getattr(mod, class_name)
    except Exception as e:
        logger.warning(f"Skipping {class_name} from {module_path}: {e}")
        return None


def _build_registry() -> ToolRegistry:
    """Create a ToolRegistry with all Phase 2 MCP tools.

    Tools are registered in groups by dependency complexity.
    Tools that fail to import are skipped gracefully.
    """
    workspace = _resolve_workspace()
    workspace_str = str(workspace)
    logger.info(f"Workspace: {workspace}")

    sandbox = WorkspaceSandbox(workspace, enabled=True)
    command_filter = CommandFilter()
    rate_limiter = ToolRateLimiter()

    registry = ToolRegistry(rate_limiter=rate_limiter)

    def _register(tool_or_none):
        """Register a tool, skipping None (failed imports)."""
        if tool_or_none is not None:
            try:
                registry.register(tool_or_none)
            except Exception as e:
                name = getattr(tool_or_none, "name", "unknown")
                logger.warning(f"Failed to register {name}: {e}")

    # ── Redundant tools NOT registered (Claude Code provides natively):
    # ReadFileTool, WriteFileTool, EditFileTool, ListDirTool → CC Read/Write/Edit/Glob
    # ShellTool → CC Bash tool
    # WebSearchTool, WebFetchTool → CC WebSearch/WebFetch
    # GrepTool → CC Grep tool
    # HttpClientTool → CC Bash + curl

    # ── Group A: No dependencies ──────────────────────────────────────────
    for mod, cls in [
        ("tools.content_analyzer", "ContentAnalyzerTool"),
        ("tools.data_tool", "DataTool"),
        ("tools.template_tool", "TemplateTool"),
        ("tools.outline_tool", "OutlineTool"),
        ("tools.scoring_tool", "ScoringTool"),
        ("tools.persona_tool", "PersonaTool"),
        ("tools.security_audit", "SecurityAuditTool"),
    ]:
        ToolClass = _safe_import(mod, cls)
        _register(ToolClass() if ToolClass else None)

    # ── Group B: workspace_path only ──────────────────────────────────────
    for mod, cls in [
        ("tools.git_tool", "GitTool"),
        ("tools.diff_tool", "DiffTool"),
        ("tools.test_runner", "TestRunnerTool"),
        ("tools.linter_tool", "LinterTool"),
        ("tools.code_intel", "CodeIntelTool"),
        ("tools.dependency_audit", "DependencyAuditTool"),
        ("tools.docker_tool", "DockerTool"),
        ("tools.python_exec", "PythonExecTool"),
        ("tools.repo_map", "RepoMapTool"),
        ("tools.pr_generator", "PRGeneratorTool"),
        ("tools.security_analyzer", "SecurityAnalyzerTool"),
        ("tools.summarizer_tool", "SummarizerTool"),
        ("tools.file_watcher", "FileWatcherTool"),
        ("tools.browser_tool", "BrowserTool"),
    ]:
        ToolClass = _safe_import(mod, cls)
        _register(ToolClass(workspace_str) if ToolClass else None)

    # ── Group C: sandbox-based ────────────────────────────────────────────
    VisionTool = _safe_import("tools.vision_tool", "VisionTool")
    KnowledgeTool = _safe_import("tools.knowledge_tool", "KnowledgeTool")

    _register(VisionTool(sandbox) if VisionTool else None)
    _register(KnowledgeTool(sandbox) if KnowledgeTool else None)

    # ── Memory Backend (Phase 3A) ────────────────────────────────────────
    memory_dir = workspace / ".agent42" / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)

    # Detect embedding vector dimension (probe without Qdrant to avoid lock)
    vector_dim = 384  # Default for local sentence-transformers
    try:
        from memory.embeddings import LOCAL_EMBEDDINGS_AVAILABLE, LOCAL_VECTOR_DIM

        if LOCAL_EMBEDDINGS_AVAILABLE:
            vector_dim = LOCAL_VECTOR_DIM
            logger.info(f"Local embeddings available ({vector_dim} dims)")
        else:
            # Check for OpenAI API key (1536 dims)
            if os.environ.get("OPENAI_API_KEY"):
                vector_dim = 1536
    except Exception:
        pass

    qdrant_store = None
    qdrant_url = os.environ.get("QDRANT_URL", "")
    try:
        from memory.qdrant_store import QdrantConfig, QdrantStore

        if qdrant_url:
            qdrant_store = QdrantStore(QdrantConfig(url=qdrant_url, vector_dim=vector_dim))
        else:
            qdrant_path = str(workspace / ".agent42" / "qdrant")
            qdrant_store = QdrantStore(QdrantConfig(local_path=qdrant_path, vector_dim=vector_dim))

        if not qdrant_store.is_available:
            logger.info("Qdrant not reachable — using file backend")
            qdrant_store = None
    except Exception as e:
        logger.info(f"Qdrant not available: {e}")

    redis_backend = None
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    if redis_url:
        try:
            from memory.redis_session import RedisConfig, RedisSessionBackend

            redis_backend = RedisSessionBackend(RedisConfig(url=redis_url))
        except Exception as e:
            logger.info(f"Redis not available: {e}")

    memory_store = None
    try:
        from memory.store import MemoryStore

        memory_store = MemoryStore(
            memory_dir, qdrant_store=qdrant_store, redis_backend=redis_backend
        )
        semantic = "semantic" if memory_store.semantic_available else "keyword"
        logger.info(f"Memory backend: {semantic} search, dir={memory_dir}")
    except Exception as e:
        logger.warning(f"Memory backend failed to initialize: {e}")

    # ── Group E: lightweight deps ─────────────────────────────────────────
    BehaviourTool = _safe_import("tools.behaviour_tool", "BehaviourTool")
    MemoryTool = _safe_import("tools.memory_tool", "MemoryTool")
    WorkflowTool = _safe_import("tools.workflow_tool", "WorkflowTool")

    _register(
        BehaviourTool(memory_dir=workspace / ".agent42" / "memory") if BehaviourTool else None
    )
    _register(MemoryTool(memory_store=memory_store) if MemoryTool else None)
    _register(WorkflowTool(workspace_str, registry) if WorkflowTool else None)

    # ── Context Assembler (Phase 7 — smart project context retrieval) ────
    # Note: skill_loader is created later in _create_server(); pass None here.
    # The tool handles None gracefully (skips skill search).
    ContextAssemblerTool = _safe_import("tools.context_assembler", "ContextAssemblerTool")
    _register(
        ContextAssemblerTool(
            memory_store=memory_store,
            skill_loader=None,
            workspace=workspace_str,
        )
        if ContextAssemblerTool
        else None
    )

    # ── Node Sync (Phase 9 — memory sync between nodes) ────────────────
    NodeSyncTool = _safe_import("tools.node_sync", "NodeSyncTool")
    _register(
        NodeSyncTool(memory_store=memory_store, workspace=workspace_str) if NodeSyncTool else None
    )

    # ── Skipped tools (require LLM layer or agent orchestration) ──────────
    # SubagentTool    — Claude Code handles sub-agents
    # TeamTool        — Claude Code handles orchestration
    # NotifyUserTool  — needs ws_manager (dashboard only)
    # ImageGenTool    — needs ModelRouter (removing in Phase 5)
    # VideoGenTool    — needs ModelRouter (removing in Phase 5)
    # ProjectInterview— needs ModelRouter + task_queue
    # DynamicTool     — meta-tool for runtime creation
    # CronTool        — needs CronScheduler runtime (Phase 6 dashboard)
    # SSHTool         — needs ApprovalGate (Phase 6 dashboard)
    # TunnelTool      — needs ApprovalGate (Phase 6 dashboard)
    # AppTool         — needs AppManager (Phase 6 dashboard)
    # AppTestTool     — needs AppManager (Phase 6 dashboard)
    # MCPToolProxy    — we ARE the MCP server

    count = len(registry.list_tools())
    logger.info(f"Registered {count} tools for MCP")
    return registry


def _load_skills() -> "SkillLoader":
    """Load all skills from builtin and workspace directories.

    Returns a SkillLoader with all skills parsed and extensions resolved.
    """
    from skills.loader import SkillLoader

    workspace = _resolve_workspace()
    skill_dirs = [
        _AGENT42_ROOT / "skills" / "builtins",
        _AGENT42_ROOT / "skills" / "workspace",
        workspace / ".claude" / "skills",
        workspace / "custom_skills",
    ]

    loader = SkillLoader(skill_dirs)
    loader.load_all()
    return loader


def _skill_to_prompt(skill) -> types.Prompt:
    """Convert a Skill object to an MCP Prompt definition."""
    arguments = []

    # Add task_type argument if the skill is task-specific
    if skill.task_types:
        arguments.append(
            types.PromptArgument(
                name="task_type",
                description=f"Task context. Relevant types: {', '.join(skill.task_types)}",
                required=False,
            )
        )

    # Add a generic context argument for all skills
    arguments.append(
        types.PromptArgument(
            name="context",
            description="Additional context about what you're working on",
            required=False,
        )
    )

    return types.Prompt(
        name=f"agent42_{skill.name}",
        description=skill.description or f"Agent42 skill: {skill.name}",
        arguments=arguments if arguments else None,
    )


def _create_server() -> tuple[Server, MCPRegistryAdapter]:
    """Create the MCP server with tool and prompt handlers."""
    registry = _build_registry()
    adapter = MCPRegistryAdapter(registry)
    skill_loader = _load_skills()

    server = Server(SERVER_NAME)

    # ── Tool handlers ──────────────────────────────────────────────────

    @server.list_tools()
    async def handle_list_tools() -> list[types.Tool]:
        return adapter.list_tools()

    @server.call_tool()
    async def handle_call_tool(
        name: str, arguments: dict[str, Any] | None
    ) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
        args = arguments or {}
        result = await adapter.call_tool(name, args)
        return result

    # ── Prompt handlers (Phase 4: Skills as MCP Prompts) ───────────────

    @server.list_prompts()
    async def handle_list_prompts() -> list[types.Prompt]:
        """Return all loaded skills as MCP prompts."""
        prompts = []
        for skill in skill_loader.all_skills():
            if skill_loader.is_enabled(skill.name):
                prompts.append(_skill_to_prompt(skill))
        return prompts

    @server.get_prompt()
    async def handle_get_prompt(
        name: str, arguments: dict[str, str] | None
    ) -> types.GetPromptResult:
        """Execute a skill and return its instructions as prompt messages."""
        args = arguments or {}

        # Strip agent42_ prefix if present
        skill_name = name.removeprefix("agent42_")
        skill = skill_loader.get(skill_name)

        if skill is None:
            return types.GetPromptResult(
                description=f"Unknown skill: {skill_name}",
                messages=[
                    types.PromptMessage(
                        role="user",
                        content=types.TextContent(
                            type="text",
                            text=f"Error: Skill '{skill_name}' not found. "
                            f"Available skills: {', '.join(s.name for s in skill_loader.all_skills())}",
                        ),
                    )
                ],
            )

        # Build the prompt content
        parts = []

        # Skill instructions (the main content)
        if skill.instructions:
            parts.append(skill.instructions)

        # System prompt override (if specified)
        if skill.system_prompt_override:
            parts.append(f"\n## System Context\n{skill.system_prompt_override}")

        # Add user context if provided
        user_context = args.get("context", "")
        if user_context:
            parts.append(f"\n## Current Context\n{user_context}")

        # Add task type context if provided
        task_type = args.get("task_type", "")
        if task_type:
            parts.append(f"\n## Task Type: {task_type}")

        content = "\n\n".join(parts)

        return types.GetPromptResult(
            description=skill.description or f"Agent42 skill: {skill.name}",
            messages=[
                types.PromptMessage(
                    role="user",
                    content=types.TextContent(type="text", text=content),
                )
            ],
        )

    prompt_count = len([s for s in skill_loader.all_skills() if skill_loader.is_enabled(s.name)])
    logger.info(f"Registered {prompt_count} skills as MCP prompts")

    return server, adapter


async def run_stdio():
    """Run the MCP server with stdio transport (for Claude Code)."""
    server, _adapter = _create_server()

    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name=SERVER_NAME,
                server_version=SERVER_VERSION,
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


async def run_sse(port: int = 8100):
    """Run the MCP server with SSE transport (for remote access).

    Starts an HTTP server that Claude Code (or any MCP client) can connect
    to via Server-Sent Events. Use this on the VPS to expose Agent42 tools
    over the network.

    Usage:
        python mcp_server.py --transport sse --port 8100
    """
    import uvicorn
    from mcp.server.sse import SseServerTransport
    from starlette.applications import Starlette
    from starlette.routing import Mount, Route

    server, _adapter = _create_server()
    sse = SseServerTransport("/messages/")

    async def handle_sse(request):
        async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
            await server.run(
                streams[0],
                streams[1],
                InitializationOptions(
                    server_name=SERVER_NAME,
                    server_version=SERVER_VERSION,
                    capabilities=server.get_capabilities(
                        notification_options=NotificationOptions(),
                        experimental_capabilities={},
                    ),
                ),
            )

    async def handle_messages(request):
        await sse.handle_post_message(request.scope, request.receive, request._send)

    app = Starlette(
        routes=[
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=sse.handle_post_message),
        ],
    )

    host = os.environ.get("MCP_SSE_HOST", "127.0.0.1")
    logger.info(f"MCP SSE server starting on {host}:{port}")
    logger.info(f"  Connect URL: http://{host}:{port}/sse")

    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    uvi_server = uvicorn.Server(config)
    await uvi_server.serve()


def main():
    """Entry point — parse transport argument and start server."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,  # MCP uses stdout for protocol; logs go to stderr
    )

    transport = "stdio"
    if "--transport" in sys.argv:
        idx = sys.argv.index("--transport")
        if idx + 1 < len(sys.argv):
            transport = sys.argv[idx + 1]

    # Parse optional --port for SSE transport
    port = 8100
    if "--port" in sys.argv:
        idx = sys.argv.index("--port")
        if idx + 1 < len(sys.argv):
            port = int(sys.argv[idx + 1])

    if transport == "stdio":
        asyncio.run(run_stdio())
    elif transport == "sse":
        asyncio.run(run_sse(port=port))
    else:
        logger.error(f"Unknown transport: {transport}")
        sys.exit(1)


if __name__ == "__main__":
    main()
