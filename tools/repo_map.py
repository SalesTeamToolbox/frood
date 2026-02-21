"""
Repository map tool — generate structural codebase maps.

Inspired by Aider's tree-sitter repository mapping. Produces a compact
representation of the codebase showing file structure, class hierarchies,
and function signatures — giving LLMs efficient context about the project
without reading every file.
"""

import ast
import logging
import os

from tools.base import Tool, ToolResult

logger = logging.getLogger("agent42.tools.repo_map")

_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".tox", ".mypy_cache"}
_CODE_EXTS = {".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".java", ".rb", ".php"}
_CONFIG_EXTS = {".json", ".yaml", ".yml", ".toml", ".ini", ".cfg"}
_DOC_EXTS = {".md", ".rst", ".txt"}


class RepoMapTool(Tool):
    """Generate a structural map of the repository."""

    def __init__(self, workspace_path: str = "."):
        self._workspace = workspace_path

    @property
    def name(self) -> str:
        return "repo_map"

    @property
    def description(self) -> str:
        return (
            "Generate a structural map of the codebase: file tree, class/function "
            "signatures, and project structure. Gives efficient context without "
            "reading entire files. Inspired by Aider's repository mapping."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory to map (default: project root)",
                    "default": "",
                },
                "depth": {
                    "type": "integer",
                    "description": "Maximum directory depth (default: 4)",
                    "default": 4,
                },
                "signatures": {
                    "type": "boolean",
                    "description": "Include function/class signatures (default: true)",
                    "default": True,
                },
                "max_files": {
                    "type": "integer",
                    "description": "Maximum files to include (default: 100)",
                    "default": 100,
                },
            },
            "required": [],
        }

    async def execute(
        self,
        path: str = "",
        depth: int = 4,
        signatures: bool = True,
        max_files: int = 100,
        **kwargs,
    ) -> ToolResult:
        root = os.path.join(self._workspace, path) if path else self._workspace
        if not os.path.isdir(root):
            return ToolResult(error=f"Directory not found: {path}", success=False)

        lines = [f"## Repository Map: {os.path.basename(root) or '.'}\n"]

        # Collect all files
        all_files = []
        for dirpath, dirs, files in os.walk(root):
            # Prune skip dirs
            dirs[:] = [d for d in sorted(dirs) if d not in _SKIP_DIRS]

            rel_dir = os.path.relpath(dirpath, root)
            current_depth = 0 if rel_dir == "." else rel_dir.count(os.sep) + 1
            if current_depth > depth:
                dirs.clear()
                continue

            for fname in sorted(files):
                ext = os.path.splitext(fname)[1]
                if ext in _CODE_EXTS | _CONFIG_EXTS | _DOC_EXTS:
                    full_path = os.path.join(dirpath, fname)
                    rel_path = os.path.relpath(full_path, root)
                    all_files.append((rel_path, full_path, ext))

        # Stats
        code_files = [f for f in all_files if f[2] in _CODE_EXTS]
        config_files = [f for f in all_files if f[2] in _CONFIG_EXTS]
        doc_files = [f for f in all_files if f[2] in _DOC_EXTS]

        lines.append(f"**Files:** {len(all_files)} total ({len(code_files)} code, {len(config_files)} config, {len(doc_files)} docs)\n")

        # File tree
        lines.append("### File Tree\n```")
        shown = 0
        for rel_path, _, ext in all_files:
            if shown >= max_files:
                lines.append(f"... ({len(all_files) - shown} more files)")
                break
            indent = "  " * rel_path.count(os.sep)
            lines.append(f"{indent}{os.path.basename(rel_path)}")
            shown += 1
        lines.append("```\n")

        # Signatures
        if signatures:
            lines.append("### Code Signatures\n")
            files_mapped = 0
            for rel_path, full_path, ext in code_files:
                if files_mapped >= max_files:
                    break
                sigs = self._extract_signatures(full_path, ext)
                if sigs:
                    lines.append(f"**{rel_path}**")
                    for sig in sigs:
                        lines.append(f"  {sig}")
                    lines.append("")
                    files_mapped += 1

        output = "\n".join(lines)
        if len(output) > 100000:
            output = output[:100000] + "\n... (map truncated)"

        return ToolResult(output=output, success=True)

    def _extract_signatures(self, filepath: str, ext: str) -> list[str]:
        """Extract class/function signatures from a source file."""
        if ext == ".py":
            return self._python_signatures(filepath)
        elif ext in (".js", ".ts", ".jsx", ".tsx"):
            return self._js_signatures(filepath)
        return []

    def _python_signatures(self, filepath: str) -> list[str]:
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                tree = ast.parse(f.read(), filename=filepath)
        except SyntaxError:
            return []

        sigs = []
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                bases = ", ".join(
                    getattr(b, "id", getattr(b, "attr", "?")) for b in node.bases
                )
                sigs.append(f"class {node.name}({bases})  # L{node.lineno}")
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        args = self._format_args(item.args)
                        prefix = "async " if isinstance(item, ast.AsyncFunctionDef) else ""
                        sigs.append(f"  {prefix}def {item.name}({args})  # L{item.lineno}")
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                args = self._format_args(node.args)
                prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
                sigs.append(f"{prefix}def {node.name}({args})  # L{node.lineno}")
        return sigs

    @staticmethod
    def _format_args(args: ast.arguments) -> str:
        """Format function arguments compactly."""
        parts = []
        for a in args.args:
            annotation = ""
            if a.annotation:
                if isinstance(a.annotation, ast.Name):
                    annotation = f": {a.annotation.id}"
                elif isinstance(a.annotation, ast.Constant):
                    annotation = f": {a.annotation.value}"
            parts.append(f"{a.arg}{annotation}")
        if len(parts) > 5:
            parts = parts[:5] + ["..."]
        return ", ".join(parts)

    def _js_signatures(self, filepath: str) -> list[str]:
        """Extract JS/TS signatures via regex (no tree-sitter dependency)."""
        import re
        sigs = []
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except Exception:
            return []

        class_re = re.compile(r"(?:export\s+)?class\s+(\w+)(?:\s+extends\s+(\w+))?")
        func_re = re.compile(r"(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)")
        arrow_re = re.compile(r"(?:export\s+)?(?:const|let)\s+(\w+)\s*=\s*(?:async\s+)?\(([^)]*)\)\s*(?:=>|:\s*\w+\s*=>)")
        method_re = re.compile(r"^\s+(?:async\s+)?(\w+)\s*\(([^)]*)\)\s*\{")

        in_class = False
        for i, line in enumerate(lines):
            m = class_re.search(line)
            if m:
                extends = f" extends {m.group(2)}" if m.group(2) else ""
                sigs.append(f"class {m.group(1)}{extends}  # L{i+1}")
                in_class = True
                continue

            m = func_re.search(line)
            if m:
                params = m.group(2).strip()
                if len(params) > 40:
                    params = params[:40] + "..."
                sigs.append(f"function {m.group(1)}({params})  # L{i+1}")
                continue

            m = arrow_re.search(line)
            if m:
                params = m.group(2).strip()
                if len(params) > 40:
                    params = params[:40] + "..."
                sigs.append(f"const {m.group(1)} = ({params}) =>  # L{i+1}")
                continue

            if in_class:
                m = method_re.match(line)
                if m and m.group(1) not in ("if", "for", "while", "switch", "try"):
                    params = m.group(2).strip()
                    if len(params) > 40:
                        params = params[:40] + "..."
                    sigs.append(f"  {m.group(1)}({params})  # L{i+1}")

        return sigs
