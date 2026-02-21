"""
Grep / code search tool — fast pattern matching across codebases.

Uses ripgrep (rg) when available, falls back to grep.
Returns structured results with file paths, line numbers, and context.
"""

import asyncio
import logging
import shutil
from tools.base import Tool, ToolResult

logger = logging.getLogger("agent42.tools.grep")

# Detect ripgrep availability
_RG_PATH = shutil.which("rg")
_GREP_PATH = shutil.which("grep")


class GrepTool(Tool):
    """Fast codebase search with context lines."""

    def __init__(self, workspace_path: str = "."):
        self._workspace = workspace_path

    @property
    def name(self) -> str:
        return "grep"

    @property
    def description(self) -> str:
        engine = "ripgrep" if _RG_PATH else "grep"
        return (
            f"Search for patterns in files ({engine}). Returns matching lines "
            "with file paths and line numbers. Supports regex, file type "
            "filtering, and context lines."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Search pattern (regex supported)",
                },
                "path": {
                    "type": "string",
                    "description": "Directory or file to search in (default: workspace root)",
                    "default": ".",
                },
                "file_type": {
                    "type": "string",
                    "description": "File type filter: py, js, ts, json, yaml, md, etc.",
                    "default": "",
                },
                "context": {
                    "type": "integer",
                    "description": "Number of context lines before and after match (default: 2)",
                    "default": 2,
                },
                "case_insensitive": {
                    "type": "boolean",
                    "description": "Case-insensitive search",
                    "default": False,
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of matching lines to return (default: 50)",
                    "default": 50,
                },
            },
            "required": ["pattern"],
        }

    async def execute(
        self,
        pattern: str = "",
        path: str = ".",
        file_type: str = "",
        context: int = 2,
        case_insensitive: bool = False,
        max_results: int = 50,
        **kwargs,
    ) -> ToolResult:
        if not pattern:
            return ToolResult(error="No search pattern provided", success=False)

        if _RG_PATH:
            return await self._search_ripgrep(
                pattern, path, file_type, context, case_insensitive, max_results
            )
        elif _GREP_PATH:
            return await self._search_grep(
                pattern, path, file_type, context, case_insensitive, max_results
            )
        else:
            return ToolResult(error="Neither ripgrep nor grep found on this system", success=False)

    async def _search_ripgrep(
        self, pattern, path, file_type, context, case_insensitive, max_results,
    ) -> ToolResult:
        cmd = [_RG_PATH, "--line-number", "--no-heading", "--color=never"]

        if context > 0:
            cmd.extend([f"--context={context}"])
        if case_insensitive:
            cmd.append("--ignore-case")
        if file_type:
            cmd.extend([f"--type={file_type}"])
        if max_results:
            cmd.extend([f"--max-count={max_results}"])

        # Always exclude common noise directories
        cmd.extend([
            "--glob=!.git",
            "--glob=!node_modules",
            "--glob=!__pycache__",
            "--glob=!*.pyc",
            "--glob=!.next",
            "--glob=!dist",
            "--glob=!build",
        ])

        cmd.extend([pattern, path])

        return await self._run_search(cmd)

    async def _search_grep(
        self, pattern, path, file_type, context, case_insensitive, max_results,
    ) -> ToolResult:
        cmd = [_GREP_PATH, "--recursive", "--line-number", "--color=never"]

        if context > 0:
            cmd.extend([f"--context={context}"])
        if case_insensitive:
            cmd.append("--ignore-case")
        if file_type:
            ext_map = {
                "py": "*.py", "js": "*.js", "ts": "*.ts", "json": "*.json",
                "yaml": "*.yaml", "yml": "*.yml", "md": "*.md", "tsx": "*.tsx",
                "jsx": "*.jsx", "css": "*.css", "html": "*.html", "go": "*.go",
                "rs": "*.rs", "java": "*.java", "rb": "*.rb",
            }
            include = ext_map.get(file_type, f"*.{file_type}")
            cmd.extend([f"--include={include}"])
        if max_results:
            cmd.extend([f"--max-count={max_results}"])

        cmd.extend([
            "--exclude-dir=.git",
            "--exclude-dir=node_modules",
            "--exclude-dir=__pycache__",
        ])

        cmd.extend([pattern, path])

        return await self._run_search(cmd)

    async def _run_search(self, cmd: list[str]) -> ToolResult:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=self._workspace,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)
        except asyncio.TimeoutError:
            proc.kill()
            return ToolResult(error="Search timed out (>30s)", success=False)

        output = stdout.decode("utf-8", errors="replace")

        if proc.returncode == 1:
            # grep/rg return 1 for "no matches"
            return ToolResult(output="No matches found.")

        if proc.returncode != 0:
            err = stderr.decode("utf-8", errors="replace")
            return ToolResult(error=f"Search failed: {err}", success=False)

        # Truncate very large output
        if len(output) > 50000:
            output = output[:50000] + "\n... (results truncated)"

        match_count = sum(1 for line in output.split("\n") if line and not line.startswith("--"))
        return ToolResult(output=f"Found {match_count} matches:\n\n{output}")
