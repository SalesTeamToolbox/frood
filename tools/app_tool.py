"""
App management tool — create, build, run, and manage user applications.

Provides the agent with the ability to scaffold new apps, manage their
lifecycle (start/stop/restart), check status, and view logs. Works with
the AppManager for process supervision and the existing filesystem tools
for writing app source code.

Supports dual-mode apps (internal/external), per-app auth/visibility,
and agent-to-app API interaction for autonomous app operation.
"""

import json
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
    - git_enable: Enable local git version control for an app
    - git_disable: Disable git for an app (preserves repo on disk)
    - git_commit: Stage and commit all changes
    - git_status: Show git status and recent commits
    - git_log: Show commit history
    - github_setup: Create a GitHub repo and link it to the app
    - github_push: Push commits to GitHub
    - set_mode: Switch app between internal and external mode
    - set_visibility: Set app visibility (private/unlisted/public)
    - set_auth: Toggle authentication requirement for app access
    - app_api: Call a running app's HTTP API endpoints (agent interaction)
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
            "then start/stop/manage them. Supports dual-mode (internal/external), "
            "per-app auth/visibility, git version control, GitHub integration, "
            "and agent-to-app API interaction. Actions: create, scaffold, install_deps, "
            "start, stop, restart, status, list, logs, mark_ready, update_manifest, "
            "git_enable, git_disable, git_commit, git_status, git_log, "
            "github_setup, github_push, set_mode, set_visibility, set_auth, app_api."
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
                        "git_enable",
                        "git_disable",
                        "git_commit",
                        "git_status",
                        "git_log",
                        "github_setup",
                        "github_push",
                        "set_mode",
                        "set_visibility",
                        "set_auth",
                        "app_api",
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
                "git_enabled": {
                    "type": "boolean",
                    "description": "Enable git version control for the app (for create)",
                    "default": False,
                },
                "message": {
                    "type": "string",
                    "description": "Commit message (for git_commit)",
                    "default": "",
                },
                "repo_name": {
                    "type": "string",
                    "description": "GitHub repository name (for github_setup, defaults to app slug)",
                    "default": "",
                },
                "private": {
                    "type": "boolean",
                    "description": "Create as private GitHub repo (for github_setup)",
                    "default": True,
                },
                "push_on_build": {
                    "type": "boolean",
                    "description": "Auto-push to GitHub when app is marked ready (for github_setup)",
                    "default": True,
                },
                "app_mode": {
                    "type": "string",
                    "enum": ["internal", "external"],
                    "description": "App mode: 'internal' (Agent42 system app) or 'external' (public release). For create/set_mode.",
                    "default": "",
                },
                "visibility": {
                    "type": "string",
                    "enum": ["private", "unlisted", "public"],
                    "description": "App visibility (for set_visibility)",
                    "default": "",
                },
                "require_auth": {
                    "type": "boolean",
                    "description": "Require dashboard auth to access app (for set_auth)",
                    "default": False,
                },
                "method": {
                    "type": "string",
                    "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"],
                    "description": "HTTP method (for app_api)",
                    "default": "GET",
                },
                "endpoint": {
                    "type": "string",
                    "description": "API endpoint path, e.g. '/api/trades' (for app_api)",
                    "default": "/",
                },
                "body": {
                    "type": "string",
                    "description": "Request body as JSON string (for app_api POST/PUT)",
                    "default": "",
                },
                "api_headers": {
                    "type": "string",
                    "description": "Comma-separated headers 'Key: Value, Key2: Value2' (for app_api)",
                    "default": "",
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
            elif action == "git_enable":
                return await self._git_enable(**kwargs)
            elif action == "git_disable":
                return await self._git_disable(**kwargs)
            elif action == "git_commit":
                return await self._git_commit(**kwargs)
            elif action == "git_status":
                return await self._git_status(**kwargs)
            elif action == "git_log":
                return await self._git_log(**kwargs)
            elif action == "github_setup":
                return await self._github_setup(**kwargs)
            elif action == "github_push":
                return await self._github_push(**kwargs)
            elif action == "set_mode":
                return await self._set_mode(**kwargs)
            elif action == "set_visibility":
                return await self._set_visibility(**kwargs)
            elif action == "set_auth":
                return await self._set_auth(**kwargs)
            elif action == "app_api":
                return await self._app_api(**kwargs)
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
        git_enabled = kwargs.get("git_enabled")
        # Handle string "true"/"false" from tool params
        if isinstance(git_enabled, str):
            git_enabled = git_enabled.lower() in ("true", "1", "yes")

        app_mode = kwargs.get("app_mode", "")
        if isinstance(app_mode, str):
            app_mode = app_mode.strip()

        app = await self._manager.create(
            name=name,
            description=desc,
            runtime=runtime,
            tags=tags,
            icon=icon,
            git_enabled=git_enabled,
            app_mode=app_mode,
        )

        return ToolResult(
            output=(
                f"App created successfully!\n"
                f"  ID: {app.id}\n"
                f"  Name: {app.name}\n"
                f"  Slug: {app.slug}\n"
                f"  Runtime: {app.runtime}\n"
                f"  Mode: {app.app_mode}\n"
                f"  Visibility: {app.visibility}\n"
                f"  Auth required: {app.require_auth}\n"
                f"  Git: {'enabled' if app.git_enabled else 'disabled'}\n"
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
                "pip",
                "install",
                "-q",
                "-r",
                str(reqs),
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
                "npm",
                "install",
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
            output=(f"App restarted: {app.name}\n  URL: {app.url}\n  Port: {app.port}")
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
            f"  Mode: {app.app_mode}",
            f"  Runtime: {app.runtime}",
            f"  Version: {app.version}",
            f"  Visibility: {app.visibility}",
            f"  Auth required: {app.require_auth}",
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
        lines.append(f"  Git: {'enabled' if app.git_enabled else 'disabled'}")
        if app.github_repo:
            lines.append(f"  GitHub: {app.github_repo}")
            lines.append(f"  Push on build: {app.github_push_on_build}")

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

            mode_tag = f"[{app.app_mode}]" if app.app_mode else ""
            line = f"  {status_icon} {mode_tag} {app.name} ({app.id}) — {app.runtime}"
            if app.git_enabled:
                line += " [git"
                if app.github_repo:
                    line += f"→{app.github_repo}"
                line += "]"
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

    # -- Git / GitHub actions --------------------------------------------------

    async def _git_enable(self, **kwargs) -> ToolResult:
        app_id = kwargs.get("app_id", "")
        if not app_id:
            return ToolResult(error="app_id is required", success=False)
        result = await self._manager.git_enable(app_id)
        return ToolResult(output=result)

    async def _git_disable(self, **kwargs) -> ToolResult:
        app_id = kwargs.get("app_id", "")
        if not app_id:
            return ToolResult(error="app_id is required", success=False)
        result = await self._manager.git_disable(app_id)
        return ToolResult(output=result)

    async def _git_commit(self, **kwargs) -> ToolResult:
        app_id = kwargs.get("app_id", "")
        if not app_id:
            return ToolResult(error="app_id is required", success=False)
        message = kwargs.get("message", "")
        result = await self._manager.git_commit(app_id, message=message)
        return ToolResult(output=result)

    async def _git_status(self, **kwargs) -> ToolResult:
        app_id = kwargs.get("app_id", "")
        if not app_id:
            return ToolResult(error="app_id is required", success=False)
        result = await self._manager.git_status(app_id)
        return ToolResult(output=result)

    async def _git_log(self, **kwargs) -> ToolResult:
        app_id = kwargs.get("app_id", "")
        if not app_id:
            return ToolResult(error="app_id is required", success=False)
        count = kwargs.get("lines", 10)
        result = await self._manager.git_log(app_id, count=count)
        return ToolResult(output=result)

    async def _github_setup(self, **kwargs) -> ToolResult:
        app_id = kwargs.get("app_id", "")
        if not app_id:
            return ToolResult(error="app_id is required", success=False)
        repo_name = kwargs.get("repo_name", "")
        private = kwargs.get("private", True)
        if isinstance(private, str):
            private = private.lower() in ("true", "1", "yes")
        push_on_build = kwargs.get("push_on_build", True)
        if isinstance(push_on_build, str):
            push_on_build = push_on_build.lower() in ("true", "1", "yes")
        result = await self._manager.github_setup(
            app_id, repo_name=repo_name, private=private, push_on_build=push_on_build,
        )
        return ToolResult(output=result)

    async def _github_push(self, **kwargs) -> ToolResult:
        app_id = kwargs.get("app_id", "")
        if not app_id:
            return ToolResult(error="app_id is required", success=False)
        result = await self._manager.github_push(app_id)
        return ToolResult(output=result)

    # -- Mode / visibility / auth actions --------------------------------------

    async def _set_mode(self, **kwargs) -> ToolResult:
        app_id = kwargs.get("app_id", "")
        if not app_id:
            return ToolResult(error="app_id is required", success=False)
        mode = kwargs.get("app_mode", "")
        if not mode:
            return ToolResult(error="app_mode is required (internal or external)", success=False)
        app = await self._manager.set_app_mode(app_id, mode)
        return ToolResult(output=f"App '{app.name}' mode set to: {app.app_mode}")

    async def _set_visibility(self, **kwargs) -> ToolResult:
        app_id = kwargs.get("app_id", "")
        if not app_id:
            return ToolResult(error="app_id is required", success=False)
        visibility = kwargs.get("visibility", "")
        if not visibility:
            return ToolResult(
                error="visibility is required (private, unlisted, or public)", success=False
            )
        app = await self._manager.set_app_visibility(app_id, visibility)
        return ToolResult(output=f"App '{app.name}' visibility set to: {app.visibility}")

    async def _set_auth(self, **kwargs) -> ToolResult:
        app_id = kwargs.get("app_id", "")
        if not app_id:
            return ToolResult(error="app_id is required", success=False)
        require_auth = kwargs.get("require_auth", False)
        if isinstance(require_auth, str):
            require_auth = require_auth.lower() in ("true", "1", "yes")
        app = await self._manager.set_app_auth(app_id, require_auth)
        status = "enabled" if app.require_auth else "disabled"
        return ToolResult(output=f"Authentication {status} for app '{app.name}'")

    # -- Agent-to-app API interaction ------------------------------------------

    async def _app_api(self, **kwargs) -> ToolResult:
        """Call a running app's HTTP API endpoint directly."""
        app_id = kwargs.get("app_id", "")
        if not app_id:
            return ToolResult(error="app_id is required", success=False)

        app = await self._manager.get(app_id)
        if not app:
            return ToolResult(error=f"App not found: {app_id}", success=False)
        if app.status != "running":
            return ToolResult(
                error=f"App is not running (status: {app.status}). Start it first.",
                success=False,
            )
        if app.runtime == "static":
            return ToolResult(
                error="Static apps do not have API endpoints. Use a Python or Node runtime.",
                success=False,
            )

        method = kwargs.get("method", "GET").upper()
        endpoint = kwargs.get("endpoint", "/").lstrip("/")
        body = kwargs.get("body", "")
        headers = {}
        headers_str = kwargs.get("api_headers", "")
        if headers_str:
            for pair in headers_str.split(","):
                if ":" in pair:
                    k, v = pair.split(":", 1)
                    headers[k.strip()] = v.strip()

        import httpx

        url = f"http://127.0.0.1:{app.port}/{endpoint}"
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    content=body.encode() if body else None,
                )
            # Format response
            try:
                resp_body = resp.json()
                resp_body_str = json.dumps(resp_body, indent=2)
            except Exception:
                resp_body_str = resp.text[:5000]

            return ToolResult(
                output=(
                    f"HTTP {resp.status_code} {method} /{endpoint}\n"
                    f"Response:\n{resp_body_str}"
                )
            )
        except httpx.ConnectError:
            return ToolResult(
                error=f"App '{app.name}' not responding on port {app.port}",
                success=False,
            )
        except httpx.TimeoutException:
            return ToolResult(error="Request timed out (30s)", success=False)
