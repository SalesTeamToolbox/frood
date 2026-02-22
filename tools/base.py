"""
Abstract base for all agent tools.

Tools follow a schema-based pattern: each tool declares its name, description,
and parameters (JSON Schema) so the LLM can call them via function calling.

Extension mechanism:
  ``ToolExtension`` lets plugin authors augment existing tools with additional
  parameters and pre/post execution hooks — without replacing the tool.
  ``ExtendedTool`` wraps a base tool with one or more extensions.
"""

import copy
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ToolResult:
    """Result of a tool execution."""

    output: str = ""
    error: str = ""
    success: bool = True

    @property
    def content(self) -> str:
        return self.output if self.success else f"Error: {self.error}"


class Tool(ABC):
    """Abstract base class for all agent tools."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique tool identifier."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description for the LLM."""
        ...

    @property
    @abstractmethod
    def parameters(self) -> dict:
        """JSON Schema for tool parameters."""
        ...

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """Execute the tool with the given parameters."""
        ...

    def to_schema(self) -> dict:
        """Serialize to OpenAI function-calling format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolExtension(ABC):
    """Extends an existing tool with additional parameters and behavior hooks.

    Drop a ``ToolExtension`` subclass into ``CUSTOM_TOOLS_DIR`` to augment a
    built-in tool without replacing it.  Multiple extensions can layer onto
    one base tool — parameters are merged and hooks are chained.

    Class variables:
        extends: Name of the base tool to extend (required).
        requires: ToolContext dependency keys for injection (same as Tool).

    Example::

        class ShellAudit(ToolExtension):
            extends = "shell"
            requires = ["workspace"]

            def __init__(self, workspace="", **kwargs):
                self._workspace = workspace

            @property
            def name(self) -> str: return "shell_audit"

            @property
            def extra_parameters(self) -> dict:
                return {"audit": {"type": "boolean", "description": "Log command"}}

            async def pre_execute(self, **kwargs) -> dict:
                return kwargs

            async def post_execute(self, result, **kwargs):
                return result
    """

    extends: str = ""
    requires: list[str] = []

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier for this extension."""
        ...

    @property
    def extra_parameters(self) -> dict:
        """Additional JSON Schema properties merged into the base tool's parameters."""
        return {}

    @property
    def description_suffix(self) -> str:
        """Text appended to the base tool's description."""
        return ""

    async def pre_execute(self, **kwargs) -> dict:
        """Called before the base tool executes.

        May inspect or modify *kwargs*.  Must return the (potentially modified)
        kwargs dict that will be forwarded to the next extension or the base.
        """
        return kwargs

    async def post_execute(self, result: ToolResult, **kwargs) -> ToolResult:
        """Called after the base tool executes.

        Receives the ``ToolResult`` and the original *kwargs* for context.
        Must return a (potentially modified) ``ToolResult``.
        """
        return result


class ExtendedTool(Tool):
    """Wraps a base ``Tool`` with one or more ``ToolExtension`` instances.

    Created automatically by the ``PluginLoader`` when extensions target an
    existing tool.  The extended tool keeps the base tool's name so it
    transparently replaces it in the registry.
    """

    def __init__(self, base: Tool, extensions: list[ToolExtension]):
        self._base = base
        self._extensions = list(extensions)

    @property
    def name(self) -> str:
        return self._base.name

    @property
    def description(self) -> str:
        desc = self._base.description
        for ext in self._extensions:
            suffix = ext.description_suffix
            if suffix:
                desc += " " + suffix
        return desc

    @property
    def parameters(self) -> dict:
        params = copy.deepcopy(self._base.parameters)
        for ext in self._extensions:
            extra = ext.extra_parameters
            if extra:
                params.setdefault("properties", {}).update(extra)
        return params

    async def execute(self, **kwargs) -> ToolResult:
        for ext in self._extensions:
            kwargs = await ext.pre_execute(**kwargs)
        result = await self._base.execute(**kwargs)
        for ext in self._extensions:
            result = await ext.post_execute(result, **kwargs)
        return result
