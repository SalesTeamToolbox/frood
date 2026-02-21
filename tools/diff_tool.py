"""
Diff / patch tool — apply unified diffs to files.

More precise than string-replace for multi-line edits. Supports creating
diffs between files, applying patches, and generating unified diffs from
inline specifications.
"""

import asyncio
import logging
import tempfile
from pathlib import Path
from tools.base import Tool, ToolResult

logger = logging.getLogger("agent42.tools.diff")


class DiffTool(Tool):
    """Create and apply unified diffs."""

    def __init__(self, workspace_path: str = "."):
        self._workspace = workspace_path

    @property
    def name(self) -> str:
        return "diff"

    @property
    def description(self) -> str:
        return (
            "Create or apply unified diffs. Actions: 'create' generates a diff "
            "between two files, 'apply' applies a unified diff/patch to the workspace, "
            "'compare' shows differences between two strings/contents."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create", "apply", "compare"],
                    "description": "Action to perform",
                },
                "file_a": {
                    "type": "string",
                    "description": "First file path (for create) or target file (for apply)",
                },
                "file_b": {
                    "type": "string",
                    "description": "Second file path (for create)",
                },
                "patch": {
                    "type": "string",
                    "description": "Unified diff content to apply (for apply action)",
                },
                "content_a": {
                    "type": "string",
                    "description": "First content string (for compare)",
                },
                "content_b": {
                    "type": "string",
                    "description": "Second content string (for compare)",
                },
            },
            "required": ["action"],
        }

    async def execute(self, action: str = "", **kwargs) -> ToolResult:
        if action == "create":
            return await self._create_diff(
                kwargs.get("file_a", ""),
                kwargs.get("file_b", ""),
            )
        elif action == "apply":
            return await self._apply_patch(
                kwargs.get("patch", ""),
            )
        elif action == "compare":
            return await self._compare_strings(
                kwargs.get("content_a", ""),
                kwargs.get("content_b", ""),
                kwargs.get("file_a", "a"),
                kwargs.get("file_b", "b"),
            )
        else:
            return ToolResult(error=f"Unknown action: {action}", success=False)

    async def _create_diff(self, file_a: str, file_b: str) -> ToolResult:
        if not file_a or not file_b:
            return ToolResult(error="Both file_a and file_b required for create", success=False)

        proc = await asyncio.create_subprocess_exec(
            "diff", "-u", file_a, file_b,
            cwd=self._workspace,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        output = stdout.decode("utf-8", errors="replace")

        if proc.returncode == 0:
            return ToolResult(output="Files are identical.")
        elif proc.returncode == 1:
            return ToolResult(output=output)
        else:
            return ToolResult(
                error=f"diff failed: {stderr.decode()}", success=False
            )

    async def _apply_patch(self, patch: str) -> ToolResult:
        if not patch:
            return ToolResult(error="No patch content provided", success=False)

        # Write patch to temp file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".patch", delete=False
        ) as f:
            f.write(patch)
            patch_path = f.name

        try:
            # Dry run first to check if patch applies cleanly
            proc = await asyncio.create_subprocess_exec(
                "patch", "--dry-run", "-p1", "-i", patch_path,
                cwd=self._workspace,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                output = stdout.decode() + stderr.decode()
                return ToolResult(
                    error=f"Patch would not apply cleanly:\n{output}",
                    success=False,
                )

            # Apply for real
            proc = await asyncio.create_subprocess_exec(
                "patch", "-p1", "-i", patch_path,
                cwd=self._workspace,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                return ToolResult(
                    error=f"Patch apply failed: {stderr.decode()}",
                    success=False,
                )

            return ToolResult(output=f"Patch applied:\n{stdout.decode()}")
        finally:
            Path(patch_path).unlink(missing_ok=True)

    async def _compare_strings(
        self, content_a: str, content_b: str, label_a: str, label_b: str,
    ) -> ToolResult:
        if not content_a and not content_b:
            return ToolResult(error="At least one content string required", success=False)

        # Write to temp files and diff
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".a", delete=False
        ) as fa:
            fa.write(content_a)
            path_a = fa.name

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".b", delete=False
        ) as fb:
            fb.write(content_b)
            path_b = fb.name

        try:
            proc = await asyncio.create_subprocess_exec(
                "diff", "-u", f"--label={label_a}", f"--label={label_b}",
                path_a, path_b,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            output = stdout.decode("utf-8", errors="replace")

            if proc.returncode == 0:
                return ToolResult(output="Contents are identical.")
            elif proc.returncode == 1:
                return ToolResult(output=output)
            else:
                return ToolResult(error=f"diff failed: {stderr.decode()}", success=False)
        finally:
            Path(path_a).unlink(missing_ok=True)
            Path(path_b).unlink(missing_ok=True)
