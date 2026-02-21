"""
Code intelligence tool — AST-aware code navigation and search.

Inspired by Aider's tree-sitter repo mapping and AutoCodeRover's
structure-aware search. Provides class/function/method search rather
than just text grep.

Falls back to regex-based parsing when tree-sitter is not available.
"""

import ast
import logging
import os
import re

from tools.base import Tool, ToolResult

logger = logging.getLogger("agent42.tools.code_intel")

# File extensions we know how to parse
_PYTHON_EXTS = {".py"}
_JS_EXTS = {".js", ".jsx", ".ts", ".tsx", ".mjs"}
_PARSEABLE_EXTS = _PYTHON_EXTS | _JS_EXTS

# Directories to skip
_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}


class CodeIntelTool(Tool):
    """AST-aware code navigation: search by class, function, method, or symbol."""

    def __init__(self, workspace_path: str = "."):
        self._workspace = workspace_path

    @property
    def name(self) -> str:
        return "code_intel"

    @property
    def description(self) -> str:
        return (
            "Search code by structure: find classes, functions, methods, imports. "
            "Unlike grep, this understands code structure (AST) for precise results. "
            "Supports Python and JavaScript/TypeScript."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "find_class", "find_function", "find_method",
                        "find_imports", "list_symbols", "outline",
                    ],
                    "description": "Type of code search to perform",
                },
                "name": {
                    "type": "string",
                    "description": "Name to search for (class/function/method name)",
                    "default": "",
                },
                "path": {
                    "type": "string",
                    "description": "File or directory to search in (default: workspace root)",
                    "default": "",
                },
                "include_body": {
                    "type": "boolean",
                    "description": "Include the full body of found definitions (default: false)",
                    "default": False,
                },
            },
            "required": ["action"],
        }

    async def execute(
        self,
        action: str = "",
        name: str = "",
        path: str = "",
        include_body: bool = False,
        **kwargs,
    ) -> ToolResult:
        if not action:
            return ToolResult(error="Action is required", success=False)

        search_path = os.path.join(self._workspace, path) if path else self._workspace

        if action == "find_class":
            return self._find_class(search_path, name, include_body)
        elif action == "find_function":
            return self._find_function(search_path, name, include_body)
        elif action == "find_method":
            return self._find_method(search_path, name, include_body)
        elif action == "find_imports":
            return self._find_imports(search_path, name)
        elif action == "list_symbols":
            return self._list_symbols(search_path)
        elif action == "outline":
            return self._outline(search_path)
        else:
            return ToolResult(error=f"Unknown action: {action}", success=False)

    def _collect_files(self, search_path: str) -> list[str]:
        """Collect all parseable source files."""
        files = []
        if os.path.isfile(search_path):
            return [search_path]

        for root, dirs, filenames in os.walk(search_path):
            dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
            for fname in filenames:
                if os.path.splitext(fname)[1] in _PARSEABLE_EXTS:
                    files.append(os.path.join(root, fname))
        return sorted(files)[:200]  # Cap at 200 files

    def _parse_python(self, filepath: str) -> ast.Module | None:
        """Parse a Python file into AST."""
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                return ast.parse(f.read(), filename=filepath)
        except SyntaxError:
            return None

    def _read_lines(self, filepath: str) -> list[str]:
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                return f.readlines()
        except Exception:
            return []

    def _get_body(self, filepath: str, node) -> str:
        """Extract the source code of an AST node."""
        lines = self._read_lines(filepath)
        if not lines:
            return ""
        start = node.lineno - 1
        end = getattr(node, "end_lineno", start + 10)
        body_lines = lines[start:end]
        if len(body_lines) > 50:
            body_lines = body_lines[:50] + ["    # ... (truncated)\n"]
        return "".join(body_lines)

    def _relpath(self, filepath: str) -> str:
        try:
            return os.path.relpath(filepath, self._workspace)
        except ValueError:
            return filepath

    def _find_class(self, search_path: str, name: str, include_body: bool) -> ToolResult:
        if not name:
            return ToolResult(error="Class name required", success=False)

        results = []
        for filepath in self._collect_files(search_path):
            ext = os.path.splitext(filepath)[1]
            if ext in _PYTHON_EXTS:
                tree = self._parse_python(filepath)
                if not tree:
                    continue
                for node in ast.walk(tree):
                    if isinstance(node, ast.ClassDef) and name in node.name:
                        bases = ", ".join(
                            getattr(b, "id", getattr(b, "attr", "?"))
                            for b in node.bases
                        )
                        entry = f"{self._relpath(filepath)}:{node.lineno} class {node.name}({bases})"
                        methods = [
                            n.name for n in node.body
                            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                        ]
                        if methods:
                            entry += f"\n  methods: {', '.join(methods)}"
                        if include_body:
                            entry += f"\n```python\n{self._get_body(filepath, node)}```"
                        results.append(entry)
            elif ext in _JS_EXTS:
                results.extend(self._regex_find_class(filepath, name, include_body))

        if not results:
            return ToolResult(output=f"No classes matching '{name}' found.", success=True)
        return ToolResult(output=f"## Classes matching '{name}'\n\n" + "\n\n".join(results), success=True)

    def _regex_find_class(self, filepath: str, name: str, include_body: bool) -> list[str]:
        """Regex fallback for JS/TS class search."""
        results = []
        lines = self._read_lines(filepath)
        pattern = re.compile(rf"class\s+(\w*{re.escape(name)}\w*)")
        for i, line in enumerate(lines):
            m = pattern.search(line)
            if m:
                entry = f"{self._relpath(filepath)}:{i+1} class {m.group(1)}"
                if include_body:
                    body = "".join(lines[i:i+30])
                    entry += f"\n```\n{body}```"
                results.append(entry)
        return results

    def _find_function(self, search_path: str, name: str, include_body: bool) -> ToolResult:
        if not name:
            return ToolResult(error="Function name required", success=False)

        results = []
        for filepath in self._collect_files(search_path):
            ext = os.path.splitext(filepath)[1]
            if ext in _PYTHON_EXTS:
                tree = self._parse_python(filepath)
                if not tree:
                    continue
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and name in node.name:
                        # Skip methods (functions inside classes)
                        args = ", ".join(a.arg for a in node.args.args)
                        prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
                        entry = f"{self._relpath(filepath)}:{node.lineno} {prefix} {node.name}({args})"
                        if include_body:
                            entry += f"\n```python\n{self._get_body(filepath, node)}```"
                        results.append(entry)
            elif ext in _JS_EXTS:
                results.extend(self._regex_find_function(filepath, name, include_body))

        if not results:
            return ToolResult(output=f"No functions matching '{name}' found.", success=True)
        return ToolResult(output=f"## Functions matching '{name}'\n\n" + "\n\n".join(results), success=True)

    def _regex_find_function(self, filepath: str, name: str, include_body: bool) -> list[str]:
        results = []
        lines = self._read_lines(filepath)
        patterns = [
            re.compile(rf"(?:export\s+)?(?:async\s+)?function\s+(\w*{re.escape(name)}\w*)"),
            re.compile(rf"(?:const|let|var)\s+(\w*{re.escape(name)}\w*)\s*=\s*(?:async\s+)?\("),
            re.compile(rf"(\w*{re.escape(name)}\w*)\s*(?::\s*\w+)?\s*\(.*\)\s*(?:=>|\{{)"),
        ]
        for i, line in enumerate(lines):
            for pattern in patterns:
                m = pattern.search(line)
                if m:
                    entry = f"{self._relpath(filepath)}:{i+1} {m.group(0).strip()}"
                    if include_body:
                        body = "".join(lines[i:i+20])
                        entry += f"\n```\n{body}```"
                    results.append(entry)
                    break
        return results

    def _find_method(self, search_path: str, name: str, include_body: bool) -> ToolResult:
        if not name:
            return ToolResult(error="Method name required", success=False)

        results = []
        for filepath in self._collect_files(search_path):
            ext = os.path.splitext(filepath)[1]
            if ext in _PYTHON_EXTS:
                tree = self._parse_python(filepath)
                if not tree:
                    continue
                for node in ast.walk(tree):
                    if isinstance(node, ast.ClassDef):
                        for item in node.body:
                            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and name in item.name:
                                args = ", ".join(a.arg for a in item.args.args)
                                entry = (
                                    f"{self._relpath(filepath)}:{item.lineno} "
                                    f"{node.name}.{item.name}({args})"
                                )
                                if include_body:
                                    entry += f"\n```python\n{self._get_body(filepath, item)}```"
                                results.append(entry)

        if not results:
            return ToolResult(output=f"No methods matching '{name}' found.", success=True)
        return ToolResult(output=f"## Methods matching '{name}'\n\n" + "\n\n".join(results), success=True)

    def _find_imports(self, search_path: str, name: str) -> ToolResult:
        results = []
        for filepath in self._collect_files(search_path):
            if not filepath.endswith(".py"):
                continue
            tree = self._parse_python(filepath)
            if not tree:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if not name or name in alias.name:
                            results.append(f"{self._relpath(filepath)}:{node.lineno} import {alias.name}")
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    for alias in node.names:
                        if not name or name in alias.name or name in module:
                            results.append(
                                f"{self._relpath(filepath)}:{node.lineno} from {module} import {alias.name}"
                            )

        if not results:
            msg = f"No imports matching '{name}' found." if name else "No imports found."
            return ToolResult(output=msg, success=True)
        return ToolResult(output=f"## Imports{' matching ' + repr(name) if name else ''}\n\n" + "\n".join(results), success=True)

    def _list_symbols(self, search_path: str) -> ToolResult:
        symbols: dict[str, list[str]] = {"classes": [], "functions": [], "constants": []}

        for filepath in self._collect_files(search_path):
            if not filepath.endswith(".py"):
                continue
            tree = self._parse_python(filepath)
            if not tree:
                continue
            rel = self._relpath(filepath)
            for node in ast.iter_child_nodes(tree):
                if isinstance(node, ast.ClassDef):
                    symbols["classes"].append(f"{rel}:{node.lineno} {node.name}")
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    symbols["functions"].append(f"{rel}:{node.lineno} {node.name}")
                elif isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name) and target.id.isupper():
                            symbols["constants"].append(f"{rel}:{node.lineno} {target.id}")

        lines = []
        for category, items in symbols.items():
            if items:
                lines.append(f"### {category.title()} ({len(items)})")
                for item in items[:100]:
                    lines.append(f"  {item}")
                if len(items) > 100:
                    lines.append(f"  ... ({len(items) - 100} more)")
                lines.append("")

        if not lines:
            return ToolResult(output="No symbols found.", success=True)
        return ToolResult(output="## Symbols\n\n" + "\n".join(lines), success=True)

    def _outline(self, search_path: str) -> ToolResult:
        """Generate a structural outline of a file or directory."""
        if os.path.isfile(search_path):
            return self._outline_file(search_path)

        files = self._collect_files(search_path)
        lines = [f"## Project Outline ({len(files)} files)\n"]
        for filepath in files[:50]:
            rel = self._relpath(filepath)
            lines.append(f"### {rel}")
            outline = self._file_outline(filepath)
            if outline:
                for item in outline:
                    lines.append(f"  {item}")
            lines.append("")

        if len(files) > 50:
            lines.append(f"... ({len(files) - 50} more files)")

        return ToolResult(output="\n".join(lines), success=True)

    def _outline_file(self, filepath: str) -> ToolResult:
        rel = self._relpath(filepath)
        outline = self._file_outline(filepath)
        if not outline:
            return ToolResult(output=f"## {rel}\n\nNo outline available.", success=True)
        return ToolResult(
            output=f"## {rel}\n\n" + "\n".join(outline),
            success=True,
        )

    def _file_outline(self, filepath: str) -> list[str]:
        if not filepath.endswith(".py"):
            return []
        tree = self._parse_python(filepath)
        if not tree:
            return []

        items = []
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                items.append(f"L{node.lineno} class {node.name}")
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        prefix = "async " if isinstance(item, ast.AsyncFunctionDef) else ""
                        items.append(f"  L{item.lineno} {prefix}def {item.name}()")
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
                items.append(f"L{node.lineno} {prefix}def {node.name}()")
        return items
