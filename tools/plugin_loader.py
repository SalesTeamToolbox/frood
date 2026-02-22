"""
Plugin loader — auto-discovers custom Tool subclasses from a directory.

Drop a ``.py`` file containing a Tool subclass into the configured
``CUSTOM_TOOLS_DIR`` and it will be discovered, validated, and registered
at startup without modifying ``agent42.py``.

Security:
  - Tool names must match ``^[a-z][a-z0-9_]{1,48}$``
  - Duplicate names (collision with built-in tools) are skipped with a warning
  - Import errors are logged and skipped — one bad plugin can't crash startup

Dependency injection:
  Tools may declare a ``requires`` class variable listing the ToolContext
  fields they need.  Only those fields are passed as kwargs to ``__init__``.

Example custom tool::

    # custom_tools/hello.py
    from tools.base import Tool, ToolResult

    class HelloTool(Tool):
        requires = ["workspace"]

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
"""

from __future__ import annotations

import importlib.util
import inspect
import logging
import re
import sys
from pathlib import Path

from tools.base import Tool
from tools.context import ToolContext

logger = logging.getLogger("agent42.tools.plugin_loader")

_VALID_TOOL_NAME = re.compile(r"^[a-z][a-z0-9_]{1,48}$")


class PluginLoader:
    """Discovers and registers custom Tool subclasses from a directory."""

    @staticmethod
    def load_all(
        directory: Path,
        context: ToolContext,
        registry,
    ) -> list[str]:
        """Scan *directory* for ``.py`` files, find Tool subclasses, register them.

        Returns the list of tool names that were successfully registered.
        """
        if not directory.is_dir():
            logger.debug("Custom tools directory does not exist: %s", directory)
            return []

        registered: list[str] = []

        for py_file in sorted(directory.glob("*.py")):
            if py_file.name.startswith("_"):
                continue  # Skip __init__.py, __pycache__, etc.

            tool_classes = _import_tools_from_file(py_file)

            for tool_cls in tool_classes:
                try:
                    tool = _instantiate_tool(tool_cls, context)
                except Exception as e:
                    logger.warning(
                        "Failed to instantiate tool %s from %s: %s",
                        tool_cls.__name__,
                        py_file.name,
                        e,
                    )
                    continue

                # Validate tool name
                if not _VALID_TOOL_NAME.match(tool.name):
                    logger.warning(
                        "Skipping plugin tool with invalid name %r from %s (must match %s)",
                        tool.name,
                        py_file.name,
                        _VALID_TOOL_NAME.pattern,
                    )
                    continue

                # Collision check
                if registry.get(tool.name) is not None:
                    logger.warning(
                        "Skipping plugin tool %r from %s — name collides with "
                        "an already-registered tool",
                        tool.name,
                        py_file.name,
                    )
                    continue

                registry.register(tool)
                registered.append(tool.name)
                logger.info("Registered custom tool: %s (from %s)", tool.name, py_file.name)

        if registered:
            logger.info("Loaded %d custom tool(s): %s", len(registered), ", ".join(registered))
        else:
            logger.debug("No custom tools found in %s", directory)

        return registered


def _import_tools_from_file(py_file: Path) -> list[type]:
    """Import a .py file and return all Tool subclasses defined in it."""
    module_name = f"_agent42_custom_tool_{py_file.stem}"

    try:
        spec = importlib.util.spec_from_file_location(module_name, py_file)
        if spec is None or spec.loader is None:
            logger.warning("Cannot load module spec from %s", py_file)
            return []

        module = importlib.util.module_from_spec(spec)
        # Add to sys.modules so relative imports work within the plugin
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    except Exception as e:
        logger.warning("Failed to import plugin %s: %s", py_file.name, e)
        # Clean up partial import
        sys.modules.pop(module_name, None)
        return []

    # Find all Tool subclasses defined in this module (not imported ones)
    tool_classes = []
    for attr_name in dir(module):
        obj = getattr(module, attr_name)
        if (
            inspect.isclass(obj)
            and issubclass(obj, Tool)
            and obj is not Tool
            and obj.__module__ == module_name  # Only classes defined here
        ):
            tool_classes.append(obj)

    return tool_classes


def _instantiate_tool(tool_cls: type, context: ToolContext) -> Tool:
    """Create a tool instance, injecting dependencies from ToolContext.

    If the tool class has a ``requires`` class attribute, only those
    context fields are passed.  Otherwise, no context is passed.
    """
    requires = getattr(tool_cls, "requires", None) or []
    kwargs = {}

    for key in requires:
        value = context.get(key)
        if value is None:
            logger.debug(
                "Tool %s requires %r but it is not available in ToolContext",
                tool_cls.__name__,
                key,
            )
        kwargs[key] = value

    return tool_cls(**kwargs)
