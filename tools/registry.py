"""
Tool registry — central registry for all available tools.

Handles tool discovery, registration, execution, and schema generation.
Optionally enforces per-tool rate limiting via ToolRateLimiter.
"""

import asyncio
import logging
import time

from tools.base import Tool, ToolResult

logger = logging.getLogger("agent42.tools.registry")

# Tools that are only relevant for code/technical task types.
# Non-code tasks (content, marketing, email, strategy, etc.) should not
# see these tools — free LLMs often call them inappropriately when they
# appear in the schema (e.g., running security scans when asked for a poem).
_CODE_ONLY_TOOLS = {
    "shell",
    "git",
    "grep",
    "diff",
    "test_runner",
    "linter",
    "code_intel",
    "dependency_audit",
    "docker",
    "python_exec",
    "repo_map",
    "pr_generator",
    "security_analyzer",
    "file_watcher",
    "ssh",
    "tunnel",
}

# Task types that should receive the full tool set (including code tools)
_CODE_TASK_TYPES = {
    "coding",
    "debugging",
    "refactoring",
    "app_create",
    "app_update",
    "project_setup",
}


class ToolRegistry:
    """Manages all available tools for agent execution."""

    def __init__(self, rate_limiter=None, effectiveness_store=None):
        self._tools: dict[str, Tool] = {}
        self._rate_limiter = rate_limiter
        self._effectiveness_store = effectiveness_store
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

    async def execute(
        self, tool_name: str, agent_id: str = "default", tier: str = "", **kwargs
    ) -> ToolResult:
        """Execute a tool by name with the given parameters.

        Args:
            tool_name: Name of the registered tool to execute.
            agent_id: Agent identifier for rate limiting.
            tier: Reward tier for rate limit scaling ("gold", "silver", "bronze", or "").
                Passed to ToolRateLimiter.check() to apply the tier's rate multiplier.
                NOT forwarded to tool.execute() — it's a registry-layer concern only.
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

        # Rate limit check — pass tier for multiplier-scaled enforcement
        if self._rate_limiter:
            allowed, reason = self._rate_limiter.check(tool_name, agent_id, tier=tier)
            if not allowed:
                logger.warning(f"Rate limited: {reason}")
                return ToolResult(error=reason, success=False)

        start_ns = time.perf_counter_ns()
        try:
            result = await tool.execute(**kwargs)
        except Exception as e:
            logger.error(f"Tool {tool_name} failed: {e}", exc_info=True)
            result = ToolResult(error=str(e), success=False)

        duration_ms = (time.perf_counter_ns() - start_ns) / 1_000_000

        # Record successful call for rate limiting
        if self._rate_limiter and result.success:
            self._rate_limiter.record(tool_name, agent_id)

        # Fire-and-forget effectiveness tracking (EFFT-02: never blocks tool return)
        if self._effectiveness_store:
            try:
                from core.task_context import get_task_context

                task_id, task_type = get_task_context()
                asyncio.create_task(
                    self._effectiveness_store.record(
                        tool_name=tool_name,
                        task_type=task_type or "general",
                        task_id=task_id or "",
                        success=result.success,
                        duration_ms=duration_ms,
                        agent_id=agent_id,
                    )
                )
            except Exception:
                pass  # Never block tool execution for tracking

            # Phase 43: Accumulate tool name for pattern detection
            try:
                from core.task_context import append_tool_to_task, get_task_context

                task_id, _ = get_task_context()
                if task_id:
                    append_tool_to_task(task_id, tool_name)
            except Exception:
                pass  # Never block tool execution for pattern tracking

        return result

    def all_schemas(self) -> list[dict]:
        """Get OpenAI function-calling schemas for all enabled tools."""
        return [
            tool.to_schema() for tool in self._tools.values() if tool.name not in self._disabled
        ]

    def schemas_for_task_type(self, task_type: str) -> list[dict]:
        """Get tool schemas filtered by task type.

        Non-code task types (content, marketing, email, etc.) only receive
        general-purpose tools — code-specific tools like shell, git, security
        analyzer, and test runner are excluded.  This prevents free LLMs from
        calling irrelevant tools (e.g., running a security scan when asked
        to write a poem).

        Code task types receive the full tool set.
        """
        if task_type in _CODE_TASK_TYPES:
            return self.all_schemas()

        return [
            tool.to_schema()
            for tool in self._tools.values()
            if tool.name not in self._disabled and tool.name not in _CODE_ONLY_TOOLS
        ]

    def list_tools(self) -> list[dict]:
        """List all registered tools with metadata."""
        return [
            {
                "name": t.name,
                "description": t.description,
                "enabled": t.name not in self._disabled,
                "source": "builtin",
            }
            for t in self._tools.values()
        ]
