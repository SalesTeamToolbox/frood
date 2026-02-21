"""
Filesystem tools — sandboxed file operations with path traversal protection.
"""

import logging
from pathlib import Path

from core.sandbox import WorkspaceSandbox, SandboxViolation
from tools.base import Tool, ToolResult

logger = logging.getLogger("agent42.tools.filesystem")


class ReadFileTool(Tool):
    """Read file contents within the sandbox."""

    def __init__(self, sandbox: WorkspaceSandbox):
        self._sandbox = sandbox

    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return "Read the contents of a file. Path must be within the workspace."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to read"},
            },
            "required": ["path"],
        }

    async def execute(self, path: str = "", **kwargs) -> ToolResult:
        try:
            resolved = self._sandbox.resolve_path(path)
            if not resolved.exists():
                return ToolResult(error=f"File not found: {path}", success=False)
            if not resolved.is_file():
                return ToolResult(error=f"Not a file: {path}", success=False)
            content = resolved.read_text(encoding="utf-8", errors="replace")
            return ToolResult(output=content)
        except SandboxViolation as e:
            return ToolResult(error=str(e), success=False)
        except Exception as e:
            return ToolResult(error=str(e), success=False)


class WriteFileTool(Tool):
    """Write content to a file within the sandbox."""

    def __init__(self, sandbox: WorkspaceSandbox):
        self._sandbox = sandbox

    @property
    def name(self) -> str:
        return "write_file"

    @property
    def description(self) -> str:
        return "Write content to a file. Creates parent directories automatically. Path must be within the workspace."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to write"},
                "content": {"type": "string", "description": "Content to write"},
            },
            "required": ["path", "content"],
        }

    async def execute(self, path: str = "", content: str = "", **kwargs) -> ToolResult:
        try:
            resolved = self._sandbox.resolve_path(path)
            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_text(content, encoding="utf-8")
            return ToolResult(output=f"Written to {path}")
        except SandboxViolation as e:
            return ToolResult(error=str(e), success=False)
        except Exception as e:
            return ToolResult(error=str(e), success=False)


class EditFileTool(Tool):
    """Targeted text replacement within a file."""

    def __init__(self, sandbox: WorkspaceSandbox):
        self._sandbox = sandbox

    @property
    def name(self) -> str:
        return "edit_file"

    @property
    def description(self) -> str:
        return "Replace a specific string in a file. The old_string must be unique in the file."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to edit"},
                "old_string": {"type": "string", "description": "Text to find and replace"},
                "new_string": {"type": "string", "description": "Replacement text"},
            },
            "required": ["path", "old_string", "new_string"],
        }

    async def execute(self, path: str = "", old_string: str = "", new_string: str = "", **kwargs) -> ToolResult:
        try:
            resolved = self._sandbox.resolve_path(path)
            if not resolved.exists():
                return ToolResult(error=f"File not found: {path}", success=False)

            content = resolved.read_text(encoding="utf-8")
            count = content.count(old_string)

            if count == 0:
                return ToolResult(error="old_string not found in file", success=False)
            if count > 1:
                return ToolResult(
                    error=f"old_string found {count} times — must be unique. Provide more context.",
                    success=False,
                )

            new_content = content.replace(old_string, new_string, 1)
            resolved.write_text(new_content, encoding="utf-8")
            return ToolResult(output=f"Edited {path}")
        except SandboxViolation as e:
            return ToolResult(error=str(e), success=False)
        except Exception as e:
            return ToolResult(error=str(e), success=False)


class ListDirTool(Tool):
    """List directory contents within the sandbox."""

    def __init__(self, sandbox: WorkspaceSandbox):
        self._sandbox = sandbox

    @property
    def name(self) -> str:
        return "list_dir"

    @property
    def description(self) -> str:
        return "List files and directories at a given path within the workspace."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory path to list (default: workspace root)",
                    "default": ".",
                },
            },
        }

    async def execute(self, path: str = ".", **kwargs) -> ToolResult:
        try:
            resolved = self._sandbox.resolve_path(path)
            if not resolved.exists():
                return ToolResult(error=f"Path not found: {path}", success=False)
            if not resolved.is_dir():
                return ToolResult(error=f"Not a directory: {path}", success=False)

            entries = sorted(resolved.iterdir())
            lines = []
            for entry in entries:
                if entry.name.startswith("."):
                    continue
                prefix = "📁 " if entry.is_dir() else "📄 "
                lines.append(f"{prefix}{entry.name}")

            return ToolResult(output="\n".join(lines) if lines else "(empty directory)")
        except SandboxViolation as e:
            return ToolResult(error=str(e), success=False)
        except Exception as e:
            return ToolResult(error=str(e), success=False)
