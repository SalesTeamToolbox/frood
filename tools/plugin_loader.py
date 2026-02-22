"""
Plugin loader — auto-discovers custom Tool and ToolExtension subclasses.

Drop a ``.py`` file containing a Tool subclass into the configured
``CUSTOM_TOOLS_DIR`` and it will be discovered, validated, and registered
at startup without modifying ``agent42.py``.

Extension mechanism:
  A file may also contain ``ToolExtension`` subclasses that augment existing
  tools with additional parameters and pre/post execution hooks.  Extensions
  are applied after all new tools are registered, mirroring the skill system's
  ``extends:`` pattern.

Security:
  - Tool / extension names must match ``^[a-z][a-z0-9_]{1,48}$``
  - Duplicate names (collision with built-in tools) are skipped with a warning
  - Import errors are logged and skipped — one bad plugin can't crash startup

Dependency injection:
  Tools and extensions may declare a ``requires`` class variable listing the
  ToolContext fields they need.  Only those fields are passed as kwargs to
  ``__init__``.

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

Example tool extension::

    # custom_tools/shell_audit.py
    from tools.base import ToolExtension, ToolResult

    class ShellAuditExtension(ToolExtension):
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

from __future__ import annotations

import importlib.util
import inspect
import logging
import re
import sys
from collections import defaultdict
from pathlib import Path

from tools.base import ExtendedTool, Tool, ToolExtension
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

        Two-phase process:
        1. Discover and register new ``Tool`` subclasses (existing behavior).
        2. Discover ``ToolExtension`` subclasses, group by base tool, and wrap
           each base tool with its extensions via ``ExtendedTool``.

        Returns the list of tool names that were successfully registered.
        """
        if not directory.is_dir():
            logger.debug("Custom tools directory does not exist: %s", directory)
            return []

        registered: list[str] = []
        pending_extensions: list[tuple[type, Path]] = []

        # Phase 1: Discover and register new tools; collect extensions
        for py_file in sorted(directory.glob("*.py")):
            if py_file.name.startswith("_"):
                continue  # Skip __init__.py, __pycache__, etc.

            tool_classes, ext_classes = _import_from_file(py_file)

            # Register new tools
            for tool_cls in tool_classes:
                try:
                    tool = _instantiate(tool_cls, context)
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

            # Collect extensions for phase 2
            for ext_cls in ext_classes:
                pending_extensions.append((ext_cls, py_file))

        # Phase 2: Apply extensions to existing tools
        _apply_extensions(pending_extensions, context, registry)

        if registered:
            logger.info("Loaded %d custom tool(s): %s", len(registered), ", ".join(registered))
        else:
            logger.debug("No custom tools found in %s", directory)

        return registered


def _import_from_file(py_file: Path) -> tuple[list[type], list[type]]:
    """Import a .py file and return (tool_classes, extension_classes)."""
    module_name = f"_agent42_custom_tool_{py_file.stem}"

    try:
        spec = importlib.util.spec_from_file_location(module_name, py_file)
        if spec is None or spec.loader is None:
            logger.warning("Cannot load module spec from %s", py_file)
            return [], []

        module = importlib.util.module_from_spec(spec)
        # Add to sys.modules so relative imports work within the plugin
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    except Exception as e:
        logger.warning("Failed to import plugin %s: %s", py_file.name, e)
        # Clean up partial import
        sys.modules.pop(module_name, None)
        return [], []

    tool_classes = []
    ext_classes = []
    for attr_name in dir(module):
        obj = getattr(module, attr_name)
        if not (inspect.isclass(obj) and obj.__module__ == module_name):
            continue
        # Check ToolExtension first (it is NOT a Tool subclass, so order is safe)
        if issubclass(obj, ToolExtension) and obj is not ToolExtension:
            ext_classes.append(obj)
        elif issubclass(obj, Tool) and obj is not Tool and not issubclass(obj, ExtendedTool):
            tool_classes.append(obj)

    return tool_classes, ext_classes


def _apply_extensions(
    pending: list[tuple[type, Path]],
    context: ToolContext,
    registry,
) -> None:
    """Instantiate extensions, group by base tool, wrap with ExtendedTool."""
    # Group instantiated extensions by their base tool name
    grouped: dict[str, list[ToolExtension]] = defaultdict(list)

    for ext_cls, py_file in pending:
        base_name = getattr(ext_cls, "extends", "")
        if not base_name:
            logger.warning(
                "Skipping extension %s from %s — no 'extends' specified",
                ext_cls.__name__,
                py_file.name,
            )
            continue

        try:
            ext = _instantiate(ext_cls, context)
        except Exception as e:
            logger.warning(
                "Failed to instantiate extension %s from %s: %s",
                ext_cls.__name__,
                py_file.name,
                e,
            )
            continue

        # Validate extension name
        if not _VALID_TOOL_NAME.match(ext.name):
            logger.warning(
                "Skipping extension with invalid name %r from %s (must match %s)",
                ext.name,
                py_file.name,
                _VALID_TOOL_NAME.pattern,
            )
            continue

        # Verify base tool exists
        if registry.get(base_name) is None:
            logger.warning(
                "Extension %r extends %r but base tool not found — skipping",
                ext.name,
                base_name,
            )
            continue

        grouped[base_name].append(ext)
        logger.info(
            "Collected extension %r for base tool %r (from %s)",
            ext.name,
            base_name,
            py_file.name,
        )

    # Wrap each base tool with its extensions
    for base_name, extensions in grouped.items():
        base_tool = registry.get(base_name)
        extended = ExtendedTool(base_tool, extensions)
        registry.register(extended)
        ext_names = ", ".join(e.name for e in extensions)
        logger.info(
            "Extended tool %r with %d extension(s): %s",
            base_name,
            len(extensions),
            ext_names,
        )


def _instantiate(cls: type, context: ToolContext):
    """Create a Tool or ToolExtension instance, injecting ToolContext deps.

    If the class has a ``requires`` class attribute, only those context
    fields are passed as keyword arguments to ``__init__``.
    """
    requires = getattr(cls, "requires", None) or []
    kwargs = {}

    for key in requires:
        value = context.get(key)
        if value is None:
            logger.debug(
                "%s requires %r but it is not available in ToolContext",
                cls.__name__,
                key,
            )
        kwargs[key] = value

    return cls(**kwargs)


# Keep the old names importable for backward compatibility
_import_tools_from_file = _import_from_file
_instantiate_tool = _instantiate
