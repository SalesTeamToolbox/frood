"""
App management tool — create, build, run, and manage user applications.

Provides the agent with the ability to scaffold new apps, manage their
lifecycle (start/stop/restart), check status, and view logs. Works with
the AppManager for process supervision and the existing filesystem tools
for writing app source code.
"""

import logging

from core.app_manager import AppManager, AppRuntime
from tools.base import Tool, ToolResult

logger = logging.getLogger("agent42.tools.app")


class AppTool(Tool):
    """Create and manage user applications.

    Actions:
    - create: Initialize a new app with directory structure and manifest
    - scaffold: Show recommended project structure for a runtime
    - install_deps: Install app dependencies (pip/npm)
    - start: Launch the app process
    - stop: Stop a running app
    - restart: Stop and restart an app
    - status: Check an app's current state and health
    - list: List all apps with their status
    - logs: View app output logs
    - mark_ready: Mark an app as ready after building
    - update_manifest: Update app metadata (name, description, version, etc.)
    """

    def __init__(self, app_manager: AppManager):
        self._manager = app_manager

    @property
    def name(self) -> str:
        return "app"

    @property
    def description(self) -> str:
        return (
            "Create and manage user applications. Build web apps from descriptions, "
            "then start/stop/manage them. Actions: create, scaffold, install_deps, "
            "start, stop, restart, status, list, logs, mark_ready, update_manifest."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "create",
                        "scaffold",
                        "install_deps",
                        "start",
                        "stop",
                        "restart",
                        "status",
                        "list",
                        "logs",
                        "mark_ready",
                        "update_manifest",
                    ],
                    "description": "Action to perform",
                },
                "app_id": {
                    "type": "string",
                    "description": "App ID (required for most actions except create/list/scaffold)",
                    "default": "",
                },
                "name": {
                    "type": "string",
                    "description": "App name (for create action)",
                    "default": "",
                },
                "app_description": {
                    "type": "string",
                    "description": "App description (for create action)",
                    "default": "",
                },
                "runtime": {
                    "type": "string",
                    "enum": ["static", "python", "node", "docker"],
                    "description": "App runtime type (for create/scaffold)",
                    "default": "static",
                },
                "tags": {
                    "type": "string",
                    "description": "Comma-separated tags (for create)",
                    "default": "",
                },
                "version": {
                    "type": "string",
                    "description": "Version string (for mark_ready/update_manifest)",
                    "default": "",
                },
                "field": {
                    "type": "string",
                    "description": "Manifest field to update (for update_manifest)",
                    "default": "",
                },
                "value": {
                    "type": "string",
                    "description": "New value for the field (for update_manifest)",
                    "default": "",
                },
                "lines": {
                    "type": "integer",
                    "description": "Number of log lines to return (for logs)",
                    "default": 50,
                },
            },
            "required": ["action"],
        }

    async def execute(self, action: str = "", **kwargs) -> ToolResult:
        try:
            if action == "create":
                return await self._create(**kwargs)
            elif action == "scaffold":
                return self._scaffold(**kwargs)
            elif action == "install_deps":
                return await self._install_deps(**kwargs)
            elif action == "start":
                return await self._start(**kwargs)
            elif action == "stop":
                return await self._stop(**kwargs)
            elif action == "restart":
                return await self._restart(**kwargs)
            elif action == "status":
                return await self._status(**kwargs)
            elif action == "list":
                return self._list(**kwargs)
            elif action == "logs":
                return await self._logs(**kwargs)
            elif action == "mark_ready":
                return await self._mark_ready(**kwargs)
            elif action == "update_manifest":
                return await self._update_manifest(**kwargs)
            else:
                return ToolResult(error=f"Unknown action: {action}", success=False)
        except Exception as e:
            return ToolResult(error=str(e), success=False)

    async def _create(self, **kwargs) -> ToolResult:
        name = kwargs.get("name", "").strip()
        if not name:
            return ToolResult(error="App name is required", success=False)

        desc = kwargs.get("app_description", "") or kwargs.get("description", "")
        runtime = kwargs.get("runtime", "static")
        tags_str = kwargs.get("tags", "")
        tags = [t.strip() for t in tags_str.split(",") if t.strip()] if tags_str else []
        icon = kwargs.get("icon", "")

        app = await self._manager.create(
            name=name,
            description=desc,
            runtime=runtime,
            tags=tags,
            icon=icon,
        )

        return ToolResult(
            output=(
                f"App created successfully!\n"
                f"  ID: {app.id}\n"
                f"  Name: {app.name}\n"
                f"  Slug: {app.slug}\n"
                f"  Runtime: {app.runtime}\n"
                f"  Path: {app.path}\n"
                f"  Entry point: {app.entry_point}\n\n"
                f"Next steps:\n"
                f"1. Write your app code to {app.path}/\n"
                f"2. Use 'app mark_ready' when done\n"
                f"3. Use 'app start' to launch"
            )
        )

    def _scaffold(self, **kwargs) -> ToolResult:
        runtime = kwargs.get("runtime", "static")
        scaffolds = {
            "static": (
                "Recommended structure for a static HTML/CSS/JS app:\n\n"
                "public/\n"
                "├── index.html          # Main entry point\n"
                "├── css/\n"
                "│   └── style.css       # Stylesheet (use Tailwind CDN or custom)\n"
                "├── js/\n"
                "│   └── app.js          # Application logic\n"
                "└── assets/\n"
                "    └── (images, fonts)  # Static assets\n\n"
                "Tips:\n"
                "- Use Tailwind CSS via CDN for styling\n"
                "- Use Alpine.js or vanilla JS for interactivity\n"
                "- Data can be stored in localStorage\n"
                "- No server needed — served directly by Agent42"
            ),
            "python": (
                "Recommended structure for a Python web app:\n\n"
                "src/\n"
                "├── app.py              # Flask/FastAPI entry point\n"
                "├── models.py           # Data models (SQLAlchemy/dataclasses)\n"
                "├── routes.py           # Route handlers (if separate from app.py)\n"
                "├── templates/          # Jinja2 HTML templates\n"
                "│   ├── base.html       # Base layout template\n"
                "│   ├── index.html      # Home page\n"
                "│   └── ...             # Other pages\n"
                "├── static/             # CSS, JS, images\n"
                "│   ├── style.css\n"
                "│   └── app.js\n"
                "└── data/               # SQLite DB, JSON files\n"
                "requirements.txt        # Python dependencies\n"
                "tests/\n"
                "└── test_app.py         # Tests\n\n"
                "Tips:\n"
                "- Use Flask for simple apps, FastAPI for APIs\n"
                "- Read PORT and HOST from environment: os.environ.get('PORT', '8080')\n"
                "- Use SQLite for data persistence (no external DB needed)\n"
                "- Entry point must start the server (e.g., app.run(host=host, port=port))"
            ),
            "node": (
                "Recommended structure for a Node.js web app:\n\n"
                "src/\n"
                "├── index.js            # Express entry point\n"
                "├── routes/             # Route handlers\n"
                "├── views/              # EJS/Pug templates\n"
                "│   └── index.ejs\n"
                "└── public/             # Static assets\n"
                "    ├── css/\n"
                "    └── js/\n"
                "package.json            # Dependencies + start script\n"
                "tests/\n"
                "└── test.js             # Tests\n\n"
                "Tips:\n"
                "- Use Express for server-side, or Vite for SPAs\n"
                "- Read port: process.env.PORT || 3000\n"
                "- package.json must have a 'start' script\n"
                "- Use SQLite (better-sqlite3) for data persistence"
            ),
            "docker": (
                "Recommended structure for a Docker Compose app:\n\n"
                "docker-compose.yml      # Service definitions\n"
                "Dockerfile              # App image build\n"
                "src/\n"
                "├── app.py              # Application code\n"
                "└── ...\n"
                "requirements.txt        # Dependencies\n"
                "nginx.conf              # Optional: reverse proxy config\n\n"
                "Tips:\n"
                "- Use APP_PORT env var for port mapping\n"
                "- Include health checks in compose file\n"
                "- Use named volumes for data persistence\n"
                "- Multi-stage builds to reduce image size"
            ),
        }
        return ToolResult(output=scaffolds.get(runtime, f"Unknown runtime: {runtime}"))

    async def _install_deps(self, **kwargs) -> ToolResult:
        import asyncio
        from pathlib import Path

        app_id = kwargs.get("app_id", "")
        if not app_id:
            return ToolResult(error="app_id is required", success=False)

        app = await self._manager.get(app_id)
        if not app:
            return ToolResult(error=f"App not found: {app_id}", success=False)

        app_path = Path(app.path)

        if app.runtime == AppRuntime.PYTHON.value:
            reqs = app_path / "requirements.txt"
            if not reqs.exists():
                return ToolResult(output="No requirements.txt found — nothing to install")

            proc = await asyncio.create_subprocess_exec(
                "pip", "install", "-q", "-r", str(reqs),
                cwd=str(app_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120.0)
            output = stdout.decode() if stdout else ""
            errors = stderr.decode() if stderr else ""
            if proc.returncode != 0:
                return ToolResult(error=f"pip install failed:\n{errors}", success=False)
            return ToolResult(output=f"Dependencies installed.\n{output}")

        elif app.runtime == AppRuntime.NODE.value:
            pkg = app_path / "package.json"
            if not pkg.exists():
                return ToolResult(output="No package.json found — nothing to install")

            proc = await asyncio.create_subprocess_exec(
                "npm", "install",
                cwd=str(app_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120.0)
            output = stdout.decode() if stdout else ""
            if proc.returncode != 0:
                errors = stderr.decode() if stderr else ""
                return ToolResult(error=f"npm install failed:\n{errors}", success=False)
            return ToolResult(output=f"Dependencies installed.\n{output}")

        else:
            return ToolResult(output=f"No dependency installation needed for {app.runtime} runtime")

    async def _start(self, **kwargs) -> ToolResult:
        app_id = kwargs.get("app_id", "")
        if not app_id:
            return ToolResult(error="app_id is required", success=False)

        app = await self._manager.start(app_id)
        return ToolResult(
            output=(
                f"App started: {app.name}\n"
                f"  URL: {app.url}\n"
                f"  Port: {app.port}\n"
                f"  PID: {app.pid}\n"
                f"  Runtime: {app.runtime}"
            )
        )

    async def _stop(self, **kwargs) -> ToolResult:
        app_id = kwargs.get("app_id", "")
        if not app_id:
            return ToolResult(error="app_id is required", success=False)

        app = await self._manager.stop(app_id)
        return ToolResult(output=f"App stopped: {app.name}")

    async def _restart(self, **kwargs) -> ToolResult:
        app_id = kwargs.get("app_id", "")
        if not app_id:
            return ToolResult(error="app_id is required", success=False)

        app = await self._manager.restart(app_id)
        return ToolResult(
            output=(
                f"App restarted: {app.name}\n"
                f"  URL: {app.url}\n"
                f"  Port: {app.port}"
            )
        )

    async def _status(self, **kwargs) -> ToolResult:
        app_id = kwargs.get("app_id", "")
        if not app_id:
            return ToolResult(error="app_id is required", success=False)

        app = await self._manager.get(app_id)
        if not app:
            return ToolResult(error=f"App not found: {app_id}", success=False)

        health = await self._manager.health_check(app_id)
        lines = [
            f"App: {app.name} ({app.id})",
            f"  Status: {app.status}",
            f"  Runtime: {app.runtime}",
            f"  Version: {app.version}",
            f"  Path: {app.path}",
        ]
        if app.url:
            lines.append(f"  URL: {app.url}")
        if app.port:
            lines.append(f"  Port: {app.port}")
        if app.pid:
            lines.append(f"  PID: {app.pid}")
        if app.error:
            lines.append(f"  Error: {app.error}")
        lines.append(f"  Healthy: {health.get('healthy', 'unknown')}")
        if app.tags:
            lines.append(f"  Tags: {', '.join(app.tags)}")

        return ToolResult(output="\n".join(lines))

    def _list(self, **kwargs) -> ToolResult:
        apps = self._manager.list_apps()
        if not apps:
            return ToolResult(output="No apps found. Use 'app create' to build one.")

        lines = [f"Apps ({len(apps)} total):", ""]
        for app in apps:
            status_icon = {
                "running": "[RUNNING]",
                "ready": "[READY]",
                "building": "[BUILDING]",
                "stopped": "[STOPPED]",
                "error": "[ERROR]",
                "draft": "[DRAFT]",
            }.get(app.status, f"[{app.status.upper()}]")

            line = f"  {status_icon} {app.name} ({app.id}) — {app.runtime}"
            if app.url:
                line += f" — {app.url}"
            lines.append(line)

        return ToolResult(output="\n".join(lines))

    async def _logs(self, **kwargs) -> ToolResult:
        app_id = kwargs.get("app_id", "")
        if not app_id:
            return ToolResult(error="app_id is required", success=False)

        lines = kwargs.get("lines", 50)
        output = await self._manager.logs(app_id, lines=lines)
        return ToolResult(output=output)

    async def _mark_ready(self, **kwargs) -> ToolResult:
        app_id = kwargs.get("app_id", "")
        if not app_id:
            return ToolResult(error="app_id is required", success=False)

        version = kwargs.get("version", "")
        app = await self._manager.mark_ready(app_id, version=version)
        return ToolResult(
            output=(
                f"App marked as ready: {app.name} v{app.version}\n"
                f"Use 'app start --app_id {app.id}' to launch."
            )
        )

    async def _update_manifest(self, **kwargs) -> ToolResult:
        app_id = kwargs.get("app_id", "")
        if not app_id:
            return ToolResult(error="app_id is required", success=False)

        field_name = kwargs.get("field", "")
        value = kwargs.get("value", "")
        if not field_name:
            return ToolResult(error="field is required", success=False)

        app = await self._manager.get(app_id)
        if not app:
            return ToolResult(error=f"App not found: {app_id}", success=False)

        allowed_fields = {"name", "description", "version", "icon", "entry_point"}
        if field_name not in allowed_fields:
            return ToolResult(
                error=f"Cannot update '{field_name}'. Allowed: {', '.join(sorted(allowed_fields))}",
                success=False,
            )

        setattr(app, field_name, value)
        app.updated_at = __import__("time").time()
        await self._manager._persist()

        return ToolResult(output=f"Updated {field_name} = {value} for app {app.name}")
