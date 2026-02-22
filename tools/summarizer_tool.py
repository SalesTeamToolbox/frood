"""
Summarizer tool — compress long text, code, or conversation context.

Inspired by SWE-agent's Summarizer for handling long context windows.
Provides extractive and structural summarization of code, diffs, logs,
and conversation history.
"""

import logging
import os
import re

from tools.base import Tool, ToolResult

logger = logging.getLogger("agent42.tools.summarizer")


class SummarizerTool(Tool):
    """Summarize long text, code, diffs, or logs into compact form."""

    def __init__(self, workspace_path: str = "."):
        self._workspace = workspace_path

    @property
    def name(self) -> str:
        return "summarize"

    @property
    def description(self) -> str:
        return (
            "Summarize long content: code files (extract signatures), diffs (extract changes), "
            "logs (extract errors/warnings), or arbitrary text (extract key sentences). "
            "Reduces content to fit within context windows."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["code", "diff", "log", "text", "file"],
                    "description": "Type of content to summarize",
                },
                "content": {
                    "type": "string",
                    "description": "Content to summarize (for code/diff/log/text)",
                    "default": "",
                },
                "path": {
                    "type": "string",
                    "description": "File path to summarize (for file action)",
                    "default": "",
                },
                "max_lines": {
                    "type": "integer",
                    "description": "Maximum output lines (default: 50)",
                    "default": 50,
                },
            },
            "required": ["action"],
        }

    async def execute(
        self,
        action: str = "",
        content: str = "",
        path: str = "",
        max_lines: int = 50,
        **kwargs,
    ) -> ToolResult:
        if not action:
            return ToolResult(error="Action is required", success=False)

        if action == "file":
            if not path:
                return ToolResult(error="File path required", success=False)
            # Always resolve relative to workspace — never accept raw absolute paths
            full_path = os.path.normpath(os.path.join(self._workspace, path))
            workspace_real = os.path.realpath(self._workspace)
            full_real = os.path.realpath(full_path)
            if not full_real.startswith(workspace_real + os.sep) and full_real != workspace_real:
                return ToolResult(
                    error=f"Blocked: path '{path}' is outside the workspace",
                    success=False,
                )
            try:
                with open(full_real, encoding="utf-8", errors="replace") as f:
                    content = f.read()
            except Exception as e:
                return ToolResult(error=f"Failed to read file: {e}", success=False)
            # Auto-detect type
            ext = os.path.splitext(path)[1]
            if ext in (".py", ".js", ".ts", ".go", ".rs", ".java"):
                action = "code"
            elif ext in (".log", ".txt") or "log" in path.lower():
                action = "log"
            else:
                action = "text"

        if not content:
            return ToolResult(error="Content required", success=False)

        if action == "code":
            return self._summarize_code(content, max_lines)
        elif action == "diff":
            return self._summarize_diff(content, max_lines)
        elif action == "log":
            return self._summarize_log(content, max_lines)
        elif action == "text":
            return self._summarize_text(content, max_lines)
        else:
            return ToolResult(error=f"Unknown action: {action}", success=False)

    def _summarize_code(self, content: str, max_lines: int) -> ToolResult:
        """Extract code structure: imports, class/function signatures."""
        lines = content.split("\n")
        summary = []

        summary.append(f"**{len(lines)} lines of code**\n")

        # Extract imports
        imports = [l.strip() for l in lines if l.strip().startswith(("import ", "from "))]
        if imports:
            summary.append(f"### Imports ({len(imports)})")
            for imp in imports[:10]:
                summary.append(f"  {imp}")
            if len(imports) > 10:
                summary.append(f"  ... ({len(imports) - 10} more)")
            summary.append("")

        # Extract class/function definitions
        defs = []
        for i, line in enumerate(lines):
            stripped = line.rstrip()
            if re.match(r"^(class |def |async def )", stripped):
                defs.append(f"  L{i + 1}: {stripped}")
            elif re.match(r"^    (def |async def )", stripped):
                defs.append(f"  L{i + 1}:   {stripped.strip()}")

        if defs:
            summary.append(f"### Definitions ({len(defs)})")
            for d in defs[:max_lines]:
                summary.append(d)
            if len(defs) > max_lines:
                summary.append(f"  ... ({len(defs) - max_lines} more)")

        return ToolResult(output="\n".join(summary), success=True)

    def _summarize_diff(self, content: str, max_lines: int) -> ToolResult:
        """Extract key changes from a diff."""
        lines = content.split("\n")
        summary = []

        _files_changed = [
            l
            for l in lines
            if l.startswith("diff --git") or l.startswith("---") or l.startswith("+++")
        ]
        additions = sum(1 for l in lines if l.startswith("+") and not l.startswith("+++"))
        deletions = sum(1 for l in lines if l.startswith("-") and not l.startswith("---"))

        summary.append(f"**Diff summary:** +{additions} / -{deletions} lines\n")

        # Extract file names
        current_file = ""
        file_changes: dict[str, dict] = {}
        for line in lines:
            if line.startswith("diff --git"):
                parts = line.split()
                if len(parts) >= 4:
                    current_file = parts[3].lstrip("b/")
                    file_changes[current_file] = {"adds": 0, "dels": 0, "hunks": []}
            elif line.startswith("@@") and current_file:
                file_changes[current_file]["hunks"].append(line)
            elif current_file in file_changes:
                if line.startswith("+") and not line.startswith("+++"):
                    file_changes[current_file]["adds"] += 1
                elif line.startswith("-") and not line.startswith("---"):
                    file_changes[current_file]["dels"] += 1

        summary.append(f"### Files Changed ({len(file_changes)})")
        for fname, stats in file_changes.items():
            summary.append(f"  {fname}: +{stats['adds']} / -{stats['dels']}")
        summary.append("")

        return ToolResult(output="\n".join(summary[:max_lines]), success=True)

    def _summarize_log(self, content: str, max_lines: int) -> ToolResult:
        """Extract errors, warnings, and key events from logs."""
        lines = content.split("\n")
        summary = [f"**{len(lines)} log lines**\n"]

        errors = [l for l in lines if re.search(r"\b(ERROR|FATAL|CRITICAL)\b", l, re.IGNORECASE)]
        warnings = [l for l in lines if re.search(r"\bWARN(ING)?\b", l, re.IGNORECASE)]
        exceptions = [l for l in lines if re.search(r"(Exception|Traceback|Error:)", l)]

        if errors:
            summary.append(f"### Errors ({len(errors)})")
            for e in errors[:15]:
                summary.append(f"  {e.strip()[:150]}")
            if len(errors) > 15:
                summary.append(f"  ... ({len(errors) - 15} more)")
            summary.append("")

        if warnings:
            summary.append(f"### Warnings ({len(warnings)})")
            for w in warnings[:10]:
                summary.append(f"  {w.strip()[:150]}")
            if len(warnings) > 10:
                summary.append(f"  ... ({len(warnings) - 10} more)")
            summary.append("")

        if exceptions and not errors:
            summary.append(f"### Exceptions ({len(exceptions)})")
            for ex in exceptions[:10]:
                summary.append(f"  {ex.strip()[:150]}")
            summary.append("")

        if not errors and not warnings and not exceptions:
            summary.append("No errors, warnings, or exceptions found.")

        return ToolResult(output="\n".join(summary[:max_lines]), success=True)

    def _summarize_text(self, content: str, max_lines: int) -> ToolResult:
        """Extract key sentences from arbitrary text."""
        lines = content.split("\n")
        summary = [f"**{len(lines)} lines, {len(content)} chars**\n"]

        # Extract headings
        headings = [l for l in lines if l.strip().startswith("#")]
        if headings:
            summary.append("### Structure")
            for h in headings[:20]:
                summary.append(f"  {h.strip()}")
            summary.append("")

        # Extract key sentences (first non-empty lines, bullet points)
        key_lines = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith(("- ", "* ", "1.", "2.", "3.", "> ")) or (
                len(stripped) > 20 and stripped[0].isupper()
            ):
                key_lines.append(stripped)
            if len(key_lines) >= max_lines:
                break

        if key_lines:
            summary.append("### Key Content")
            for kl in key_lines[:max_lines]:
                if len(kl) > 150:
                    kl = kl[:150] + "..."
                summary.append(f"  {kl}")

        return ToolResult(output="\n".join(summary[: max_lines * 2]), success=True)
