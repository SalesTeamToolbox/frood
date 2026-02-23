"""
App lifecycle manager — build, run, and serve user-created applications.

Apps are self-contained projects that Agent42 builds from natural language
descriptions. Each app lives in its own directory under APPS_DIR, has a
manifest (APP.json), and can be started/stopped as a subprocess or mounted
as static files.

Supported runtimes:
- static:  Pure HTML/CSS/JS served directly by FastAPI
- python:  Flask/FastAPI/Streamlit via subprocess (pip install + uvicorn/python)
- node:    Express/Next.js/Vite via subprocess (npm install + npm start)
- docker:  Docker Compose stack via subprocess (docker compose up)

Security:
- Each app runs in its own directory (no cross-app access)
- App processes inherit a sanitized environment (no Agent42 secrets)
- Port allocation from a restricted range
- Process supervision with graceful shutdown
"""

import asyncio
import json
import logging
import re
import shutil
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path

import aiofiles

logger = logging.getLogger("agent42.app_manager")


class AppStatus(str, Enum):
    DRAFT = "draft"
    BUILDING = "building"
    READY = "ready"
    RUNNING = "running"
    STOPPED = "stopped"
    ERROR = "error"
    ARCHIVED = "archived"


class AppRuntime(str, Enum):
    STATIC = "static"
    PYTHON = "python"
    NODE = "node"
    DOCKER = "docker"


# Safe slug pattern: lowercase letters, digits, hyphens
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,48}[a-z0-9]$")


def _make_slug(name: str) -> str:
    """Convert a name to a URL-safe slug."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    if len(slug) > 50:
        slug = slug[:50].rstrip("-")
    if not slug:
        slug = "app"
    return slug


def _sanitize_env() -> dict[str, str]:
    """Return a sanitized copy of os.environ without Agent42 secrets."""
    import os

    blocked = {
        "OPENROUTER_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "DEEPSEEK_API_KEY",
        "GEMINI_API_KEY",
        "DASHBOARD_PASSWORD",
        "DASHBOARD_PASSWORD_HASH",
        "JWT_SECRET",
        "DISCORD_BOT_TOKEN",
        "SLACK_BOT_TOKEN",
        "SLACK_APP_TOKEN",
        "TELEGRAM_BOT_TOKEN",
        "BRAVE_API_KEY",
        "REPLICATE_API_TOKEN",
        "LUMA_API_KEY",
        "BROWSER_GATEWAY_TOKEN",
        "APPS_GITHUB_TOKEN",
        "REDIS_PASSWORD",
        "QDRANT_API_KEY",
        "EMAIL_IMAP_PASSWORD",
        "EMAIL_SMTP_PASSWORD",
        "VLLM_API_KEY",
    }
    return {k: v for k, v in os.environ.items() if k not in blocked}


@dataclass
class App:
    """Represents a user-created application."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str = ""
    slug: str = ""
    description: str = ""
    version: str = "0.1.0"
    runtime: str = "static"
    status: str = "draft"
    port: int = 0
    entry_point: str = ""
    path: str = ""
    pid: int = 0
    url: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    build_task_id: str = ""
    tags: list = field(default_factory=list)
    error: str = ""
    auto_restart: bool = True
    icon: str = ""
    # Git/GitHub integration (per-app, optional)
    git_enabled: bool = False
    github_repo: str = ""  # e.g. "owner/repo-name"
    github_push_on_build: bool = False  # Auto-push on mark_ready

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "App":
        data = data.copy()
        # Filter to known fields only
        known = cls.__dataclass_fields__
        return cls(**{k: v for k, v in data.items() if k in known})


class AppManager:
    """Manages the full app lifecycle: create, build, start, stop, delete."""

    def __init__(
        self,
        apps_dir: str = "apps",
        port_range_start: int = 9100,
        port_range_end: int = 9199,
        max_running: int = 5,
        auto_restart: bool = True,
        dashboard_port: int = 8000,
        git_enabled_default: bool = False,
        github_token: str = "",
    ):
        self._apps_dir = Path(apps_dir)
        self._apps_dir.mkdir(parents=True, exist_ok=True)
        self._port_start = port_range_start
        self._port_end = port_range_end
        self._max_running = max_running
        self._auto_restart = auto_restart
        self._dashboard_port = dashboard_port
        self._git_enabled_default = git_enabled_default
        self._github_token = github_token

        self._apps: dict[str, App] = {}
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._data_path = self._apps_dir / "apps.json"
        self._port_lock = asyncio.Lock()

    # -- Persistence -----------------------------------------------------------

    async def load(self):
        """Load app registry from disk."""
        if not self._data_path.exists():
            return
        try:
            async with aiofiles.open(self._data_path) as f:
                data = json.loads(await f.read())
            for item in data:
                app = App.from_dict(item)
                # Running apps are marked stopped on reload (process is gone)
                if app.status == AppStatus.RUNNING.value:
                    app.status = AppStatus.STOPPED.value
                    app.pid = 0
                self._apps[app.id] = app
            logger.info("Loaded %d app(s) from %s", len(self._apps), self._data_path)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load apps registry: %s", e)

    async def _persist(self):
        """Save app registry to disk."""
        data = [app.to_dict() for app in self._apps.values()]
        async with aiofiles.open(self._data_path, "w") as f:
            await f.write(json.dumps(data, indent=2))

    # -- CRUD ------------------------------------------------------------------

    async def create(
        self,
        name: str,
        description: str = "",
        runtime: str = "static",
        tags: list | None = None,
        icon: str = "",
        git_enabled: bool | None = None,
    ) -> App:
        """Create a new app with manifest and directory structure.

        Args:
            git_enabled: Enable local git for this app. None = use default from config.
        """
        slug = _make_slug(name)

        # Ensure slug uniqueness
        existing_slugs = {a.slug for a in self._apps.values()}
        base_slug = slug
        counter = 1
        while slug in existing_slugs:
            slug = f"{base_slug}-{counter}"
            counter += 1

        use_git = git_enabled if git_enabled is not None else self._git_enabled_default

        app = App(
            name=name,
            slug=slug,
            description=description,
            runtime=runtime,
            status=AppStatus.DRAFT.value,
            tags=tags or [],
            icon=icon,
            git_enabled=use_git,
        )
        app.path = str(self._apps_dir / app.id)

        # Create directory structure
        app_path = Path(app.path)
        app_path.mkdir(parents=True, exist_ok=True)
        (app_path / "src").mkdir(exist_ok=True)

        if runtime == AppRuntime.STATIC.value:
            (app_path / "public").mkdir(exist_ok=True)
            app.entry_point = "public/index.html"
        elif runtime == AppRuntime.PYTHON.value:
            app.entry_point = "src/app.py"
        elif runtime == AppRuntime.NODE.value:
            app.entry_point = "src/index.js"
        elif runtime == AppRuntime.DOCKER.value:
            app.entry_point = "docker-compose.yml"

        # Write APP.json manifest
        manifest = {
            "id": app.id,
            "name": app.name,
            "slug": app.slug,
            "description": app.description,
            "version": app.version,
            "runtime": app.runtime,
            "entry_point": app.entry_point,
            "port": app.port,
            "tags": app.tags,
            "icon": app.icon,
            "created_at": app.created_at,
            "git_enabled": app.git_enabled,
            "github_repo": app.github_repo,
        }
        async with aiofiles.open(app_path / "APP.json", "w") as f:
            await f.write(json.dumps(manifest, indent=2))

        self._apps[app.id] = app
        await self._persist()
        logger.info("Created app: %s (%s) at %s", app.name, app.id, app.path)

        # Initialize git repo if enabled
        if use_git:
            await self._git_init(app)

        return app

    async def get(self, app_id: str) -> App | None:
        """Get an app by ID."""
        return self._apps.get(app_id)

    def get_by_slug(self, slug: str) -> App | None:
        """Get an app by slug."""
        for app in self._apps.values():
            if app.slug == slug:
                return app
        return None

    def list_apps(self) -> list[App]:
        """List all non-archived apps."""
        return [a for a in self._apps.values() if a.status != AppStatus.ARCHIVED.value]

    def all_apps(self) -> list[App]:
        """List all apps including archived."""
        return list(self._apps.values())

    # -- Port allocation -------------------------------------------------------

    async def _allocate_port(self) -> int:
        """Find the next available port in the configured range."""
        async with self._port_lock:
            used = {a.port for a in self._apps.values() if a.status == AppStatus.RUNNING.value}
            for port in range(self._port_start, self._port_end + 1):
                if port not in used:
                    return port
            raise RuntimeError(
                f"No available ports in range {self._port_start}-{self._port_end}"
            )

    # -- Lifecycle: start/stop -------------------------------------------------

    async def start(self, app_id: str) -> App:
        """Start a ready/stopped app."""
        app = self._apps.get(app_id)
        if not app:
            raise ValueError(f"App not found: {app_id}")

        if app.status == AppStatus.RUNNING.value:
            raise ValueError(f"App already running: {app.name}")

        if app.status not in (AppStatus.READY.value, AppStatus.STOPPED.value):
            raise ValueError(
                f"Cannot start app in '{app.status}' state (must be ready or stopped)"
            )

        running_count = sum(
            1 for a in self._apps.values() if a.status == AppStatus.RUNNING.value
        )
        if running_count >= self._max_running:
            raise ValueError(
                f"Max running apps reached ({self._max_running}). Stop another app first."
            )

        app_path = Path(app.path)

        # Static apps don't need a process
        if app.runtime == AppRuntime.STATIC.value:
            app.status = AppStatus.RUNNING.value
            app.port = 0  # Served by dashboard directly
            app.url = f"/apps/{app.slug}/"
            app.updated_at = time.time()
            await self._persist()
            logger.info("Static app started: %s at %s", app.name, app.url)
            return app

        port = await self._allocate_port()
        app.port = port
        env = _sanitize_env()

        try:
            if app.runtime == AppRuntime.PYTHON.value:
                proc = await self._start_python_app(app_path, app.entry_point, port, env)
            elif app.runtime == AppRuntime.NODE.value:
                proc = await self._start_node_app(app_path, port, env)
            elif app.runtime == AppRuntime.DOCKER.value:
                proc = await self._start_docker_app(app_path, port, env)
            else:
                raise ValueError(f"Unknown runtime: {app.runtime}")

            self._processes[app.id] = proc
            app.pid = proc.pid or 0
            app.status = AppStatus.RUNNING.value
            app.url = f"/apps/{app.slug}/"
            app.error = ""
            app.updated_at = time.time()
            await self._persist()
            logger.info(
                "App started: %s (pid=%d, port=%d, url=%s)",
                app.name, app.pid, app.port, app.url,
            )
            return app

        except Exception as e:
            app.status = AppStatus.ERROR.value
            app.error = str(e)
            app.updated_at = time.time()
            await self._persist()
            raise

    async def _start_python_app(
        self, app_path: Path, entry_point: str, port: int, env: dict
    ) -> asyncio.subprocess.Process:
        """Start a Python app as a subprocess."""
        env["PORT"] = str(port)
        env["HOST"] = "127.0.0.1"

        # Check for requirements.txt and install deps
        reqs = app_path / "requirements.txt"
        if reqs.exists():
            proc = await asyncio.create_subprocess_exec(
                "pip", "install", "-q", "-r", str(reqs),
                cwd=str(app_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            await asyncio.wait_for(proc.communicate(), timeout=120.0)

        entry = app_path / entry_point
        return await asyncio.create_subprocess_exec(
            "python", str(entry),
            cwd=str(app_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

    async def _start_node_app(
        self, app_path: Path, port: int, env: dict
    ) -> asyncio.subprocess.Process:
        """Start a Node.js app as a subprocess."""
        env["PORT"] = str(port)
        env["HOST"] = "127.0.0.1"

        # Install deps if package.json exists
        pkg = app_path / "package.json"
        if pkg.exists():
            proc = await asyncio.create_subprocess_exec(
                "npm", "install", "--production",
                cwd=str(app_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            await asyncio.wait_for(proc.communicate(), timeout=120.0)

        return await asyncio.create_subprocess_exec(
            "npm", "start",
            cwd=str(app_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

    async def _start_docker_app(
        self, app_path: Path, port: int, env: dict
    ) -> asyncio.subprocess.Process:
        """Start a Docker Compose app."""
        env["APP_PORT"] = str(port)
        return await asyncio.create_subprocess_exec(
            "docker", "compose", "up", "--build", "-d",
            cwd=str(app_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

    async def stop(self, app_id: str) -> App:
        """Stop a running app."""
        app = self._apps.get(app_id)
        if not app:
            raise ValueError(f"App not found: {app_id}")

        if app.status != AppStatus.RUNNING.value:
            raise ValueError(f"App is not running: {app.name}")

        # Static apps just change state
        if app.runtime == AppRuntime.STATIC.value:
            app.status = AppStatus.STOPPED.value
            app.url = ""
            app.updated_at = time.time()
            await self._persist()
            return app

        # Docker apps need compose down
        if app.runtime == AppRuntime.DOCKER.value:
            try:
                proc = await asyncio.create_subprocess_exec(
                    "docker", "compose", "down",
                    cwd=app.path,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await asyncio.wait_for(proc.communicate(), timeout=30.0)
            except Exception as e:
                logger.warning("Docker compose down failed for %s: %s", app.name, e)

        # Kill subprocess
        process = self._processes.pop(app_id, None)
        if process and process.returncode is None:
            try:
                process.terminate()
                await asyncio.wait_for(process.wait(), timeout=10.0)
            except (TimeoutError, ProcessLookupError):
                try:
                    process.kill()
                except ProcessLookupError:
                    pass

        app.status = AppStatus.STOPPED.value
        app.pid = 0
        app.url = ""
        app.updated_at = time.time()
        await self._persist()
        logger.info("App stopped: %s", app.name)
        return app

    async def restart(self, app_id: str) -> App:
        """Stop and restart an app."""
        app = self._apps.get(app_id)
        if not app:
            raise ValueError(f"App not found: {app_id}")

        if app.status == AppStatus.RUNNING.value:
            await self.stop(app_id)

        return await self.start(app_id)

    async def delete(self, app_id: str) -> None:
        """Archive an app and optionally clean up files."""
        app = self._apps.get(app_id)
        if not app:
            raise ValueError(f"App not found: {app_id}")

        # Stop if running
        if app.status == AppStatus.RUNNING.value:
            await self.stop(app_id)

        app.status = AppStatus.ARCHIVED.value
        app.updated_at = time.time()
        await self._persist()
        logger.info("App archived: %s", app.name)

    async def delete_permanently(self, app_id: str) -> None:
        """Permanently delete an app and its files."""
        app = self._apps.get(app_id)
        if not app:
            raise ValueError(f"App not found: {app_id}")

        if app.status == AppStatus.RUNNING.value:
            await self.stop(app_id)

        # Remove files
        app_path = Path(app.path)
        if app_path.exists():
            shutil.rmtree(app_path, ignore_errors=True)

        del self._apps[app_id]
        await self._persist()
        logger.info("App permanently deleted: %s", app.name)

    # -- Build integration -----------------------------------------------------

    async def mark_building(self, app_id: str, task_id: str) -> App:
        """Mark an app as being built by an agent task."""
        app = self._apps.get(app_id)
        if not app:
            raise ValueError(f"App not found: {app_id}")

        app.status = AppStatus.BUILDING.value
        app.build_task_id = task_id
        app.updated_at = time.time()
        await self._persist()
        return app

    async def mark_ready(self, app_id: str, version: str = "") -> App:
        """Mark an app as ready (build succeeded).

        If git is enabled, auto-commits all changes. If github_push_on_build
        is set and a GitHub repo is configured, auto-pushes as well.
        """
        app = self._apps.get(app_id)
        if not app:
            raise ValueError(f"App not found: {app_id}")

        app.status = AppStatus.READY.value
        if version:
            app.version = version
        app.error = ""
        app.updated_at = time.time()
        await self._persist()
        logger.info("App ready: %s v%s", app.name, app.version)

        # Auto-commit if git enabled
        if app.git_enabled:
            try:
                msg = f"Build ready: {app.name} v{app.version}"
                await self.git_commit(app_id, message=msg)
            except Exception as e:
                logger.warning("Auto-commit failed for app %s: %s", app.id, e)

            # Auto-push if configured
            if app.github_push_on_build and app.github_repo:
                try:
                    await self.github_push(app_id)
                except Exception as e:
                    logger.warning("Auto-push failed for app %s: %s", app.id, e)

        return app

    async def mark_error(self, app_id: str, error: str) -> App:
        """Mark an app as having a build/runtime error."""
        app = self._apps.get(app_id)
        if not app:
            raise ValueError(f"App not found: {app_id}")

        app.status = AppStatus.ERROR.value
        app.error = error
        app.updated_at = time.time()
        await self._persist()
        return app

    # -- Git / GitHub integration ----------------------------------------------

    async def _run_git(self, app_path: Path, *args: str) -> tuple[int, str, str]:
        """Run a git command in the app directory. Returns (returncode, stdout, stderr)."""
        env = _sanitize_env()
        # Use GitHub token for authentication if available
        if self._github_token:
            env["GIT_ASKPASS"] = "echo"
            env["GIT_TERMINAL_PROMPT"] = "0"
        # Disable commit signing — app repos are local-only by default
        env["GIT_CONFIG_COUNT"] = "1"
        env["GIT_CONFIG_KEY_0"] = "commit.gpgsign"
        env["GIT_CONFIG_VALUE_0"] = "false"
        proc = await asyncio.create_subprocess_exec(
            "git", *args,
            cwd=str(app_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=60.0)
        stdout = stdout_b.decode() if stdout_b else ""
        stderr = stderr_b.decode() if stderr_b else ""
        return proc.returncode or 0, stdout, stderr

    async def _git_init(self, app: App) -> str:
        """Initialize a git repository in the app directory."""
        app_path = Path(app.path)
        git_dir = app_path / ".git"
        if git_dir.exists():
            return "Git repository already initialized"

        rc, out, err = await self._run_git(app_path, "init")
        if rc != 0:
            logger.warning("git init failed for app %s: %s", app.id, err)
            return f"git init failed: {err}"

        # Write .gitignore
        gitignore = (
            "__pycache__/\n"
            "*.pyc\n"
            ".env\n"
            "node_modules/\n"
            "*.egg-info/\n"
            "dist/\n"
            "build/\n"
            ".venv/\n"
            "BUILD.log\n"
        )
        async with aiofiles.open(app_path / ".gitignore", "w") as f:
            await f.write(gitignore)

        # Initial commit with manifest
        await self._run_git(app_path, "add", "-A")
        await self._run_git(
            app_path, "commit", "-m", f"Initial commit: {app.name}"
        )
        logger.info("Git initialized for app %s", app.id)
        return "Git repository initialized with initial commit"

    async def git_commit(self, app_id: str, message: str = "") -> str:
        """Stage all changes and commit in the app's git repo."""
        app = self._apps.get(app_id)
        if not app:
            raise ValueError(f"App not found: {app_id}")
        if not app.git_enabled:
            raise ValueError(f"Git is not enabled for app '{app.name}'. Enable it first.")

        app_path = Path(app.path)
        if not (app_path / ".git").exists():
            await self._git_init(app)

        # Stage all changes
        rc, _, err = await self._run_git(app_path, "add", "-A")
        if rc != 0:
            return f"git add failed: {err}"

        # Check if there are staged changes
        rc, diff_out, _ = await self._run_git(app_path, "diff", "--cached", "--stat")
        if not diff_out.strip():
            return "No changes to commit"

        if not message:
            message = f"Update {app.name} v{app.version}"

        rc, out, err = await self._run_git(app_path, "commit", "-m", message)
        if rc != 0:
            return f"git commit failed: {err}"

        logger.info("Git commit for app %s: %s", app.id, message)
        return f"Committed: {message}\n{out.strip()}"

    async def git_status(self, app_id: str) -> str:
        """Get git status for an app."""
        app = self._apps.get(app_id)
        if not app:
            raise ValueError(f"App not found: {app_id}")
        if not app.git_enabled:
            return "Git is not enabled for this app"

        app_path = Path(app.path)
        if not (app_path / ".git").exists():
            return "Git not initialized (enable git to initialize)"

        rc, out, err = await self._run_git(app_path, "status", "--short")
        if rc != 0:
            return f"git status failed: {err}"

        # Also get log summary
        rc2, log_out, _ = await self._run_git(
            app_path, "log", "--oneline", "-5"
        )
        result = f"Status:\n{out.strip() or '(clean)'}"
        if rc2 == 0 and log_out.strip():
            result += f"\n\nRecent commits:\n{log_out.strip()}"
        return result

    async def git_log(self, app_id: str, count: int = 10) -> str:
        """Get git log for an app."""
        app = self._apps.get(app_id)
        if not app:
            raise ValueError(f"App not found: {app_id}")
        if not app.git_enabled:
            return "Git is not enabled for this app"

        app_path = Path(app.path)
        if not (app_path / ".git").exists():
            return "Git not initialized"

        rc, out, err = await self._run_git(
            app_path, "log", f"--max-count={count}",
            "--format=%h %s (%cr)"
        )
        if rc != 0:
            return f"git log failed: {err}"
        return out.strip() or "(no commits)"

    async def git_enable(self, app_id: str) -> str:
        """Enable git for an existing app."""
        app = self._apps.get(app_id)
        if not app:
            raise ValueError(f"App not found: {app_id}")

        if app.git_enabled:
            return f"Git is already enabled for '{app.name}'"

        app.git_enabled = True
        app.updated_at = time.time()
        await self._persist()

        result = await self._git_init(app)
        return f"Git enabled for '{app.name}'. {result}"

    async def git_disable(self, app_id: str) -> str:
        """Disable git for an app (does not remove .git directory)."""
        app = self._apps.get(app_id)
        if not app:
            raise ValueError(f"App not found: {app_id}")

        if not app.git_enabled:
            return f"Git is already disabled for '{app.name}'"

        app.git_enabled = False
        app.updated_at = time.time()
        await self._persist()
        return f"Git disabled for '{app.name}'. Repository preserved on disk."

    async def github_setup(
        self, app_id: str, repo_name: str = "", private: bool = True,
        push_on_build: bool = True,
    ) -> str:
        """Create a GitHub repo and link it to the app.

        Uses the `gh` CLI if available, otherwise falls back to git remote + token auth.
        """
        app = self._apps.get(app_id)
        if not app:
            raise ValueError(f"App not found: {app_id}")

        if not app.git_enabled:
            app.git_enabled = True
            await self._git_init(app)

        app_path = Path(app.path)

        # Determine repo name
        if not repo_name:
            repo_name = app.slug

        # Try gh CLI first
        gh_available = await self._check_command("gh")
        if gh_available:
            return await self._github_setup_via_gh(app, app_path, repo_name, private, push_on_build)

        # Fallback: manual git remote with token
        if not self._github_token:
            return (
                "GitHub setup requires either the `gh` CLI or APPS_GITHUB_TOKEN.\n"
                "Install gh: https://cli.github.com\n"
                "Or set APPS_GITHUB_TOKEN in .env"
            )

        return await self._github_setup_via_token(app, app_path, repo_name, private, push_on_build)

    async def _check_command(self, cmd: str) -> bool:
        """Check if a command is available on the system."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "which", cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=5.0)
            return proc.returncode == 0
        except Exception:
            return False

    async def _github_setup_via_gh(
        self, app: App, app_path: Path, repo_name: str,
        private: bool, push_on_build: bool,
    ) -> str:
        """Create GitHub repo using the gh CLI."""
        visibility = "--private" if private else "--public"
        env = _sanitize_env()
        if self._github_token:
            env["GH_TOKEN"] = self._github_token

        # Create the repo
        proc = await asyncio.create_subprocess_exec(
            "gh", "repo", "create", repo_name,
            visibility,
            "--source", str(app_path),
            "--push",
            "--description", app.description or f"App: {app.name}",
            cwd=str(app_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60.0)
        out = stdout.decode() if stdout else ""
        err = stderr.decode() if stderr else ""

        if proc.returncode != 0:
            return f"GitHub repo creation failed: {err}"

        # Extract repo URL from output
        repo_url = out.strip()

        # Get the actual owner/repo from the remote
        rc, remote_out, _ = await self._run_git(app_path, "remote", "get-url", "origin")
        if rc == 0 and remote_out.strip():
            # Parse owner/repo from URL
            remote = remote_out.strip()
            for prefix in ["https://github.com/", "git@github.com:"]:
                if remote.startswith(prefix):
                    repo_url = remote[len(prefix):].rstrip(".git")
                    break

        app.github_repo = repo_url
        app.github_push_on_build = push_on_build
        app.updated_at = time.time()
        await self._persist()
        logger.info("GitHub repo created for app %s: %s", app.id, repo_url)
        return f"GitHub repository created: {repo_url}\nPush on build: {push_on_build}"

    async def _github_setup_via_token(
        self, app: App, app_path: Path, repo_name: str,
        private: bool, push_on_build: bool,
    ) -> str:
        """Create GitHub repo using the API via token and add as remote."""
        import os

        # Use httpx to create the repo via GitHub API
        try:
            import httpx
        except ImportError:
            return "httpx is required for token-based GitHub setup. Install: pip install httpx"

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.github.com/user/repos",
                headers={
                    "Authorization": f"token {self._github_token}",
                    "Accept": "application/vnd.github.v3+json",
                },
                json={
                    "name": repo_name,
                    "description": app.description or f"App: {app.name}",
                    "private": private,
                    "auto_init": False,
                },
                timeout=30.0,
            )

            if resp.status_code == 422:
                # Repo might already exist — try to use it
                pass
            elif resp.status_code not in (200, 201):
                return f"GitHub API error ({resp.status_code}): {resp.text}"

            if resp.status_code in (200, 201):
                repo_data = resp.json()
                full_name = repo_data["full_name"]
            else:
                # Try to get existing repo
                # Get authenticated user first
                user_resp = await client.get(
                    "https://api.github.com/user",
                    headers={
                        "Authorization": f"token {self._github_token}",
                        "Accept": "application/vnd.github.v3+json",
                    },
                    timeout=15.0,
                )
                if user_resp.status_code != 200:
                    return "Failed to get GitHub user info"
                username = user_resp.json()["login"]
                full_name = f"{username}/{repo_name}"

        # Add remote
        remote_url = f"https://x-access-token:{self._github_token}@github.com/{full_name}.git"
        # Check if origin already exists
        rc, _, _ = await self._run_git(app_path, "remote", "get-url", "origin")
        if rc == 0:
            await self._run_git(app_path, "remote", "set-url", "origin", remote_url)
        else:
            await self._run_git(app_path, "remote", "add", "origin", remote_url)

        # Push
        rc, out, err = await self._run_git(app_path, "push", "-u", "origin", "main")
        if rc != 0:
            # Try master branch
            rc, out, err = await self._run_git(app_path, "push", "-u", "origin", "master")

        app.github_repo = full_name
        app.github_push_on_build = push_on_build
        app.updated_at = time.time()
        await self._persist()
        logger.info("GitHub repo linked for app %s: %s", app.id, full_name)

        push_status = "pushed" if rc == 0 else f"push pending ({err.strip()})"
        return f"GitHub repository: {full_name}\nStatus: {push_status}\nPush on build: {push_on_build}"

    async def github_push(self, app_id: str) -> str:
        """Push app commits to GitHub."""
        app = self._apps.get(app_id)
        if not app:
            raise ValueError(f"App not found: {app_id}")
        if not app.github_repo:
            raise ValueError(
                f"No GitHub repo configured for '{app.name}'. Use github_setup first."
            )

        app_path = Path(app.path)

        # Set up auth if token available
        if self._github_token:
            remote_url = f"https://x-access-token:{self._github_token}@github.com/{app.github_repo}.git"
            await self._run_git(app_path, "remote", "set-url", "origin", remote_url)

        rc, out, err = await self._run_git(app_path, "push", "origin", "HEAD")
        if rc != 0:
            return f"Push failed: {err.strip()}"

        logger.info("Pushed app %s to GitHub: %s", app.id, app.github_repo)
        return f"Pushed to {app.github_repo}\n{out.strip()}"

    # -- Logs ------------------------------------------------------------------

    async def logs(self, app_id: str, lines: int = 100) -> str:
        """Read recent stdout/stderr from a running app."""
        process = self._processes.get(app_id)
        if not process:
            # Check for a build log
            app = self._apps.get(app_id)
            if app:
                log_path = Path(app.path) / "BUILD.log"
                if log_path.exists():
                    async with aiofiles.open(log_path) as f:
                        content = await f.read()
                    log_lines = content.splitlines()
                    return "\n".join(log_lines[-lines:])
            return "(no logs available — app is not running)"

        # For running processes, we can't easily tail async pipes without
        # a dedicated reader task. Return a status message instead.
        app = self._apps.get(app_id)
        return f"App '{app.name}' is running (pid={app.pid}, port={app.port})"

    # -- Health ----------------------------------------------------------------

    async def health_check(self, app_id: str) -> dict:
        """Check if a running app is responsive."""
        app = self._apps.get(app_id)
        if not app:
            return {"healthy": False, "error": "App not found"}

        if app.status != AppStatus.RUNNING.value:
            return {"healthy": False, "error": f"App is {app.status}"}

        if app.runtime == AppRuntime.STATIC.value:
            # Static apps are always healthy if files exist
            entry = Path(app.path) / app.entry_point
            return {"healthy": entry.exists(), "runtime": "static"}

        # Check process is still alive
        process = self._processes.get(app_id)
        if not process or process.returncode is not None:
            return {"healthy": False, "error": "Process exited"}

        return {
            "healthy": True,
            "pid": app.pid,
            "port": app.port,
            "runtime": app.runtime,
        }

    # -- Export / Import -------------------------------------------------------

    async def export_app(self, app_id: str) -> Path:
        """Export an app as a zip archive."""
        app = self._apps.get(app_id)
        if not app:
            raise ValueError(f"App not found: {app_id}")

        app_path = Path(app.path)
        archive_path = self._apps_dir / f"{app.slug}-v{app.version}"
        result = shutil.make_archive(str(archive_path), "zip", str(app_path))
        return Path(result)

    async def import_app(self, archive_path: Path) -> App:
        """Import an app from a zip archive."""
        import zipfile

        if not archive_path.exists():
            raise ValueError(f"Archive not found: {archive_path}")

        # Extract to temp location to read manifest
        temp_dir = self._apps_dir / f"_import_{uuid.uuid4().hex[:8]}"
        temp_dir.mkdir(parents=True, exist_ok=True)

        try:
            with zipfile.ZipFile(archive_path, "r") as zf:
                zf.extractall(str(temp_dir))

            # Read manifest
            manifest_path = temp_dir / "APP.json"
            if not manifest_path.exists():
                raise ValueError("Archive does not contain APP.json manifest")

            async with aiofiles.open(manifest_path) as f:
                manifest = json.loads(await f.read())

            # Create app with new ID
            app = await self.create(
                name=manifest.get("name", "Imported App"),
                description=manifest.get("description", ""),
                runtime=manifest.get("runtime", "static"),
                tags=manifest.get("tags", []),
                icon=manifest.get("icon", ""),
            )

            # Copy extracted files to app directory
            app_path = Path(app.path)
            for item in temp_dir.iterdir():
                dest = app_path / item.name
                if item.is_dir():
                    if dest.exists():
                        shutil.rmtree(dest)
                    shutil.copytree(str(item), str(dest))
                else:
                    shutil.copy2(str(item), str(dest))

            app.status = AppStatus.READY.value
            app.version = manifest.get("version", "1.0.0")
            app.updated_at = time.time()
            await self._persist()
            return app

        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    # -- Shutdown --------------------------------------------------------------

    async def shutdown(self):
        """Stop all running apps gracefully."""
        running = [
            app_id
            for app_id, app in self._apps.items()
            if app.status == AppStatus.RUNNING.value
        ]
        for app_id in running:
            try:
                await self.stop(app_id)
            except Exception as e:
                logger.warning("Failed to stop app %s during shutdown: %s", app_id, e)
