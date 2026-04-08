"""
Auto-discovery engine for self-improving tests.

Scans the Agent42 codebase to find:
  - API endpoints (from server.py decorators)
  - Frontend routes/views (from app.js)
  - Tools (from tools/ directory)
  - Task types (from task_queue.py enum)
  - Skills (from skills/ directory)

Tests use this to dynamically generate test cases, so when new endpoints,
tools, or features are added, tests automatically cover them.
"""

import ast
import re
from dataclasses import dataclass, field


@dataclass
class Endpoint:
    method: str
    path: str
    auth_required: bool = True
    line_number: int = 0


@dataclass
class ToolInfo:
    name: str
    file: str
    class_name: str = ""


@dataclass
class CodebaseManifest:
    """Snapshot of what exists in the Agent42 codebase."""

    endpoints: list[Endpoint] = field(default_factory=list)
    tools: list[ToolInfo] = field(default_factory=list)
    task_types: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    frontend_views: list[str] = field(default_factory=list)
    channels: list[str] = field(default_factory=list)


def discover_endpoints() -> list[Endpoint]:
    """Parse server.py for all @app.{method}(...) decorated routes."""
    server_py = FROOD_ROOT / "dashboard" / "server.py"
    if not server_py.exists():
        return []

    endpoints = []
    pattern = re.compile(r'@app\.(get|post|put|patch|delete)\(\s*["\']([^"\']+)["\']')
    no_auth_paths = {"/health", "/api/login", "/api/setup/status", "/api/setup/complete"}

    with open(server_py, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            m = pattern.search(line)
            if m:
                method, path = m.group(1).upper(), m.group(2)
                endpoints.append(
                    Endpoint(
                        method=method,
                        path=path,
                        auth_required=path not in no_auth_paths,
                        line_number=lineno,
                    )
                )
    return endpoints


def discover_tools() -> list[ToolInfo]:
    """Scan tools/ directory for tool classes."""
    tools_dir = FROOD_ROOT / "tools"
    if not tools_dir.exists():
        return []

    tools = []
    for py_file in sorted(tools_dir.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        try:
            source = py_file.read_text(encoding="utf-8")
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name.endswith("Tool"):
                    tools.append(
                        ToolInfo(
                            name=py_file.stem,
                            file=str(py_file.relative_to(FROOD_ROOT)),
                            class_name=node.name,
                        )
                    )
        except (SyntaxError, UnicodeDecodeError):
            tools.append(ToolInfo(name=py_file.stem, file=str(py_file.relative_to(FROOD_ROOT))))
    return tools


def discover_task_types() -> list[str]:
    """Extract TaskType enum members from task_queue.py."""
    task_queue = FROOD_ROOT / "core" / "task_queue.py"
    if not task_queue.exists():
        return []

    types = []
    in_enum = False
    with open(task_queue, encoding="utf-8") as f:
        for line in f:
            if "class TaskType" in line:
                in_enum = True
                continue
            if in_enum:
                stripped = line.strip()
                if not stripped or stripped.startswith("class ") or stripped.startswith("def "):
                    break
                m = re.match(r"(\w+)\s*=", stripped)
                if m:
                    types.append(m.group(1))
    return types


def discover_skills() -> list[str]:
    """Find all skills (built-in + workspace)."""
    skills = []
    for skills_dir in [
        FROOD_ROOT / "skills" / "builtins",
        FROOD_ROOT / "skills" / "workspace",
        FROOD_ROOT / "skills",
    ]:
        if not skills_dir.exists():
            continue
        for item in sorted(skills_dir.iterdir()):
            if item.is_dir() and (item / "SKILL.md").exists():
                skills.append(item.name)
            elif item.suffix == ".md" and item.name == "SKILL.md":
                skills.append(skills_dir.name)
    return list(dict.fromkeys(skills))  # dedupe preserving order


def discover_frontend_views() -> list[str]:
    """Detect view/page identifiers from app.js."""
    app_js = FROOD_ROOT / "dashboard" / "frontend" / "dist" / "app.js"
    if not app_js.exists():
        return []

    views = []
    content = app_js.read_text(encoding="utf-8", errors="replace")
    # Match patterns like showView('tasks'), renderXxxView, data-view="xxx"
    for m in re.finditer(r"""showView\s*\(\s*['"](\w+)['"]""", content):
        views.append(m.group(1))
    for m in re.finditer(r"""data-view\s*=\s*['"](\w+)['"]""", content):
        views.append(m.group(1))
    for m in re.finditer(r"""render(\w+)View""", content):
        views.append(m.group(1).lower())
    return list(dict.fromkeys(views))


def discover_channels() -> list[str]:
    """Find channel implementations."""
    channels_dir = FROOD_ROOT / "channels"
    if not channels_dir.exists():
        return []

    channels = []
    for py_file in sorted(channels_dir.glob("*.py")):
        name = py_file.stem
        if name not in ("__init__", "base", "manager"):
            channels.append(name)
    return channels


def build_manifest() -> CodebaseManifest:
    """Build a complete manifest of the current codebase."""
    return CodebaseManifest(
        endpoints=discover_endpoints(),
        tools=discover_tools(),
        task_types=discover_task_types(),
        skills=discover_skills(),
        frontend_views=discover_frontend_views(),
        channels=discover_channels(),
    )
