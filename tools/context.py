"""
Dependency injection context for custom tools.

Custom tools declare what they need via a ``requires`` class variable.
The PluginLoader inspects this list and injects matching attributes from
the ToolContext into the tool constructor.

Example::

    class MyTool(Tool):
        requires = ["sandbox"]  # Only inject sandbox

        def __init__(self, sandbox=None, **kwargs):
            self._sandbox = sandbox
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolContext:
    """Container holding references to core Agent42 subsystems.

    The PluginLoader reads a tool's ``requires`` list and passes only
    the requested attributes as keyword arguments to the tool constructor.
    """

    sandbox: Any = None  # WorkspaceSandbox
    command_filter: Any = None  # CommandFilter
    task_queue: Any = None  # TaskQueue
    workspace: str = ""  # Resolved repo path string
    tool_registry: Any = None  # ToolRegistry (for tools that compose others)
    model_router: Any = None  # ModelRouter (for tools that need LLM calls)

    # Allow arbitrary extras for future extensibility
    extras: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str) -> Any:
        """Look up a dependency by name, checking fields then extras."""
        if hasattr(self, key) and key != "extras":
            return getattr(self, key)
        return self.extras.get(key)

    def available_keys(self) -> list[str]:
        """Return all keys that have non-None values."""
        keys = []
        for f in self.__dataclass_fields__:
            if f == "extras":
                continue
            if getattr(self, f) is not None and getattr(self, f) != "":
                keys.append(f)
        keys.extend(k for k, v in self.extras.items() if v is not None)
        return keys
