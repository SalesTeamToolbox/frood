"""
Agent Execution Extension Loader — pluggable lifecycle hooks for the agent pipeline.

Inspired by Agent Zero's extension system, this module discovers Python files
from a configured directory and exposes named hook functions that are called at
key points during agent execution.

The 6 supported hook points are:

    before_system_prompt(prompt: str, task_type: str) -> str
        Called just before the system prompt is finalised.
        Return the (possibly modified) prompt string.

    after_system_prompt(prompt: str) -> str
        Called after all modifications (profile, behaviour) have been applied.
        Last chance to modify the system prompt.

    before_iteration(messages: list[dict], iteration_num: int) -> list[dict]
        Called at the start of each iteration loop, before the primary LLM call.
        Return the (possibly modified) messages list.

    after_iteration(output: str, iteration_num: int) -> str
        Called after the primary model produces output but before the critic.
        Return the (possibly modified) output string.

    before_tool_call(tool_name: str, kwargs: dict) -> dict
        Called before each tool is executed.
        Return the (possibly modified) kwargs dict.

    after_tool_call(tool_name: str, result: any) -> any
        Called after each tool is executed.
        Return the (possibly modified) result.

**Extension file format** (drop a ``.py`` file into ``EXTENSIONS_DIR``):

    # extensions/my_extension.py

    def before_system_prompt(prompt: str, task_type: str) -> str:
        return prompt + "\\n\\nAlways use type hints."

    def after_tool_call(tool_name: str, result):
        # audit tool calls
        return result

Extensions that define only some hook functions are fine — missing hooks are
silently skipped. Extensions are discovered and called in alphabetical filename
order for predictable layering.
"""

import importlib.util
import logging
import sys
from pathlib import Path
from types import ModuleType

logger = logging.getLogger("agent42.extension_loader")

# The 6 supported hook names
HOOK_NAMES = frozenset(
    [
        "before_system_prompt",
        "after_system_prompt",
        "before_iteration",
        "after_iteration",
        "before_tool_call",
        "after_tool_call",
    ]
)


class ExtensionLoader:
    """Discovers and runs agent execution lifecycle extensions.

    Extensions are ``.py`` files in the configured directory. Each file may
    define any subset of the 6 hook functions. They are called in alphabetical
    filename order so you can control execution order by naming files
    ``01_logging.py``, ``02_security.py``, etc.
    """

    def __init__(self, extensions_dir: str | Path | None = None):
        self._dir: Path | None = None
        self._modules: list[ModuleType] = []

        if extensions_dir:
            p = Path(extensions_dir)
            if p.exists() and p.is_dir():
                self._dir = p
                self._load_extensions()
            else:
                logger.info(f"Extensions directory does not exist: {p} — no extensions loaded")

    def _load_extensions(self) -> None:
        """Discover and import extension modules from the configured directory."""
        if not self._dir:
            return

        py_files = sorted(self._dir.glob("*.py"))
        for path in py_files:
            module_name = f"agent42_extension_{path.stem}"
            try:
                spec = importlib.util.spec_from_file_location(module_name, path)
                if spec is None or spec.loader is None:
                    continue
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
                self._modules.append(module)
                hooks = [h for h in HOOK_NAMES if hasattr(module, h)]
                logger.info(
                    f"Loaded extension: {path.name} (hooks: {', '.join(sorted(hooks)) or 'none'})"
                )
            except Exception as e:
                logger.warning(f"Failed to load extension {path.name}: {e}")

    @property
    def has_extensions(self) -> bool:
        return bool(self._modules)

    def call_before_system_prompt(self, prompt: str, task_type: str) -> str:
        """Call all ``before_system_prompt`` hooks in order."""
        for module in self._modules:
            fn = getattr(module, "before_system_prompt", None)
            if fn:
                try:
                    result = fn(prompt, task_type)
                    if isinstance(result, str):
                        prompt = result
                except Exception as e:
                    logger.warning(f"Extension {module.__name__}.before_system_prompt error: {e}")
        return prompt

    def call_after_system_prompt(self, prompt: str) -> str:
        """Call all ``after_system_prompt`` hooks in order."""
        for module in self._modules:
            fn = getattr(module, "after_system_prompt", None)
            if fn:
                try:
                    result = fn(prompt)
                    if isinstance(result, str):
                        prompt = result
                except Exception as e:
                    logger.warning(f"Extension {module.__name__}.after_system_prompt error: {e}")
        return prompt

    def call_before_iteration(self, messages: list[dict], iteration_num: int) -> list[dict]:
        """Call all ``before_iteration`` hooks in order."""
        for module in self._modules:
            fn = getattr(module, "before_iteration", None)
            if fn:
                try:
                    result = fn(messages, iteration_num)
                    if isinstance(result, list):
                        messages = result
                except Exception as e:
                    logger.warning(f"Extension {module.__name__}.before_iteration error: {e}")
        return messages

    def call_after_iteration(self, output: str, iteration_num: int) -> str:
        """Call all ``after_iteration`` hooks in order."""
        for module in self._modules:
            fn = getattr(module, "after_iteration", None)
            if fn:
                try:
                    result = fn(output, iteration_num)
                    if isinstance(result, str):
                        output = result
                except Exception as e:
                    logger.warning(f"Extension {module.__name__}.after_iteration error: {e}")
        return output

    def call_before_tool_call(self, tool_name: str, kwargs: dict) -> dict:
        """Call all ``before_tool_call`` hooks in order."""
        for module in self._modules:
            fn = getattr(module, "before_tool_call", None)
            if fn:
                try:
                    result = fn(tool_name, kwargs)
                    if isinstance(result, dict):
                        kwargs = result
                except Exception as e:
                    logger.warning(f"Extension {module.__name__}.before_tool_call error: {e}")
        return kwargs

    def call_after_tool_call(self, tool_name: str, result):
        """Call all ``after_tool_call`` hooks in order."""
        for module in self._modules:
            fn = getattr(module, "after_tool_call", None)
            if fn:
                try:
                    result = fn(tool_name, result)
                except Exception as e:
                    logger.warning(f"Extension {module.__name__}.after_tool_call error: {e}")
        return result

    def list_extensions(self) -> list[dict]:
        """Return metadata about loaded extensions."""
        result = []
        for module in self._modules:
            hooks = [h for h in HOOK_NAMES if hasattr(module, h)]
            path = getattr(module, "__file__", "unknown")
            result.append(
                {
                    "name": Path(path).name if path != "unknown" else module.__name__,
                    "hooks": sorted(hooks),
                }
            )
        return result
