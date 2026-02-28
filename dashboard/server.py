"""
FastAPI dashboard server with REST API and WebSocket support.

Security features:
- CORS restricted to configured origins (no wildcard)
- Login rate limiting per IP
- WebSocket connection limits
- Security response headers (CSP, HSTS, X-Frame-Options, etc.)
- Health check returns minimal info without auth
- Device API key authentication for multi-device gateway

Extended with endpoints for providers, tools, skills, channels, and devices.
"""

import asyncio
import logging
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

from core.approval_gate import ApprovalGate
from core.config import Settings, settings
from core.device_auth import DeviceStore
from core.task_queue import Task, TaskQueue, TaskStatus, TaskType
from dashboard.auth import (
    API_KEY_PREFIX,
    AuthContext,
    check_rate_limit,
    create_token,
    get_auth_context,
    get_current_user,
    pwd_context,
    require_admin,
    verify_password,
)
from dashboard.websocket_manager import WebSocketManager

logger = logging.getLogger("agent42.server")


async def _pip_install(packages: list[str]) -> tuple[list[str], list[str]]:
    """Install pip packages using the current Python interpreter.

    Returns (installed, errors) — errors is non-empty on failure.
    Non-fatal: errors are logged but callers decide how to handle them.
    """
    import sys

    installed: list[str] = []
    errors: list[str] = []
    for package in packages:
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "pip",
                "install",
                "-q",
                package,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
            if proc.returncode == 0:
                installed.append(package)
            else:
                msg = stderr.decode().strip()
                logger.warning("pip install %s failed: %s", package, msg)
                errors.append(f"{package}: {msg[:200]}")
        except TimeoutError:
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass
            errors.append(f"{package}: install timed out")
        except Exception as exc:
            logger.warning("pip install %s error: %s", package, exc)
            errors.append(f"{package}: {exc}")
    return installed, errors


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all HTTP responses."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self' ws: wss:; frame-ancestors 'none'"
        )
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=()"
        )
        # If serving over HTTPS, enable HSTS
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


FRONTEND_DIR = Path(__file__).parent / "frontend" / "dist"


class LoginRequest(BaseModel):
    username: str
    password: str


class SetupRequest(BaseModel):
    password: str
    openrouter_api_key: str = ""
    memory_backend: str = ""  # "", "skip", "qdrant_embedded", "qdrant_redis"


class TaskCreateRequest(BaseModel):
    title: str
    description: str
    task_type: str = "coding"
    priority: int = 0
    context_window: str = "default"
    project_id: str = ""
    repo_id: str = ""
    branch: str = ""
    profile: str = ""  # Agent profile name (empty = use default)


# Passwords treated as unconfigured — trigger the setup wizard
_INSECURE_PASSWORDS = {"", "changeme-right-now"}


class InterventionRequest(BaseModel):
    message: str


class UserInputResponse(BaseModel):
    response: str


class TaskMoveRequest(BaseModel):
    status: str
    position: int = 0


class TaskCommentRequest(BaseModel):
    text: str
    author: str = "admin"


class TaskAssignRequest(BaseModel):
    agent_id: str


class TaskPriorityRequest(BaseModel):
    priority: int


class TaskBlockRequest(BaseModel):
    reason: str


class ApprovalAction(BaseModel):
    task_id: str
    action: str
    approved: bool


class ReviewFeedback(BaseModel):
    feedback: str
    approved: bool


class DeviceRegisterRequest(BaseModel):
    name: str
    device_type: str = "other"
    capabilities: list[str] = ["tasks", "monitor"]


class KeyUpdateRequest(BaseModel):
    keys: dict[str, str]


class SettingsUpdateRequest(BaseModel):
    settings: dict[str, str]


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class ToggleRequest(BaseModel):
    enabled: bool


# Settings that can be changed from the dashboard (non-secret, non-security).
# Security-critical settings (sandbox, password, JWT) are deliberately excluded.
_DASHBOARD_EDITABLE_SETTINGS = {
    "MAX_CONCURRENT_AGENTS",
    "MAX_DAILY_API_SPEND_USD",
    "DEFAULT_REPO_PATH",
    "TASKS_JSON_PATH",
    "MCP_SERVERS_JSON",
    "CRON_JOBS_PATH",
    "MEMORY_DIR",
    "SESSIONS_DIR",
    "OUTPUTS_DIR",
    "TEMPLATES_DIR",
    "IMAGES_DIR",
    "SKILLS_DIRS",
    "DISCORD_GUILD_IDS",
    "EMAIL_IMAP_HOST",
    "EMAIL_IMAP_PORT",
    "EMAIL_SMTP_HOST",
    "EMAIL_SMTP_PORT",
    "LOGIN_RATE_LIMIT",
    "MAX_WEBSOCKET_CONNECTIONS",
    "CORS_ALLOWED_ORIGINS",
    "DASHBOARD_HOST",
    "DASHBOARD_USERNAME",
    "CUSTOM_TOOLS_DIR",
    "MODEL_TRIAL_PERCENTAGE",
    "MODEL_CATALOG_REFRESH_HOURS",
    "MODEL_RESEARCH_ENABLED",
    "MODEL_ROUTING_POLICY",
    "OPENROUTER_BALANCE_CHECK_HOURS",
    # Project-scoped memory
    "PROJECT_MEMORY_ENABLED",
    # RLM (Recursive Language Models)
    "RLM_ENABLED",
    "RLM_THRESHOLD_TOKENS",
    "RLM_ENVIRONMENT",
    "RLM_MAX_DEPTH",
    "RLM_MAX_ITERATIONS",
    "RLM_VERBOSE",
    "RLM_COST_LIMIT",
    "RLM_TIMEOUT_SECONDS",
    "RLM_LOG_DIR",
}


def _update_env_file(env_path: Path, updates: dict[str, str]) -> None:
    """Update or add key=value pairs in a .env file.

    For each key in *updates*:
    - If the key exists (commented or not), replace the entire line.
    - If the key does not exist, append it at the end.
    - Empty values write ``KEY=`` (clears the variable).
    Creates the file if it does not exist.
    """
    lines: list[str] = []
    if env_path.exists():
        lines = env_path.read_text().splitlines()

    remaining = dict(updates)
    new_lines: list[str] = []

    for line in lines:
        stripped = line.lstrip()
        matched_key = None
        for key in remaining:
            if (
                stripped.startswith(f"{key}=")
                or stripped.startswith(f"# {key}=")
                or stripped.startswith(f"#{key}=")
            ):
                matched_key = key
                break
        if matched_key is not None:
            value = remaining.pop(matched_key)
            new_lines.append(f"{matched_key}={value}" if value else f"{matched_key}=")
        else:
            new_lines.append(line)

    for key, value in remaining.items():
        new_lines.append(f"{key}={value}" if value else f"{key}=")

    env_path.write_text("\n".join(new_lines) + "\n")


# ---------------------------------------------------------------------------
# Tool / skill toggle state persistence
# ---------------------------------------------------------------------------

_TOGGLE_STATE_FILE = Path(__file__).parent.parent / "data" / "tool_skill_state.json"


def _load_toggle_state() -> dict:
    """Load persisted enabled/disabled state for tools and skills."""
    import json

    if _TOGGLE_STATE_FILE.exists():
        try:
            return json.loads(_TOGGLE_STATE_FILE.read_text())
        except Exception:
            pass
    return {"disabled_tools": [], "disabled_skills": []}


def _save_toggle_state(disabled_tools: list[str], disabled_skills: list[str]) -> None:
    """Persist the current enabled/disabled state to disk."""
    import json

    _TOGGLE_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _TOGGLE_STATE_FILE.write_text(
        json.dumps(
            {"disabled_tools": sorted(disabled_tools), "disabled_skills": sorted(disabled_skills)},
            indent=2,
        )
    )


def create_app(
    task_queue: TaskQueue,
    ws_manager: WebSocketManager,
    approval_gate: ApprovalGate,
    tool_registry=None,
    skill_loader=None,
    channel_manager=None,
    learner=None,
    device_store: DeviceStore | None = None,
    heartbeat=None,
    key_store=None,
    app_manager=None,
    chat_session_manager=None,
    project_manager=None,
    repo_manager=None,
    profile_loader=None,
    intervention_queues: dict | None = None,
    github_account_store=None,
    model_catalog=None,
    model_evaluator=None,
    intent_classifier=None,
    memory_store=None,
) -> FastAPI:
    """Build and return the FastAPI application."""

    app = FastAPI(title="Agent42 Dashboard", version="0.4.0")

    # Security headers on all responses
    app.add_middleware(SecurityHeadersMiddleware)

    # CORS: always enabled with secure defaults
    # If CORS_ALLOWED_ORIGINS is not configured, default to same-origin only
    # (empty list = no cross-origin requests allowed)
    cors_origins = settings.get_cors_origins()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins if cors_origins else [],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    # Apply persisted tool/skill toggle state
    _toggle_state = _load_toggle_state()
    if tool_registry:
        for name in _toggle_state.get("disabled_tools", []):
            tool_registry.set_enabled(name, False)
    if skill_loader:
        for name in _toggle_state.get("disabled_skills", []):
            skill_loader.set_enabled(name, False)

    # -- Health ----------------------------------------------------------------

    @app.get("/health")
    async def health_check():
        """Public health check — returns only liveness status.

        Does NOT expose task counts or connection info to unauthenticated users.
        """
        return {"status": "ok"}

    @app.get("/api/health")
    async def health_detail(_user: str = Depends(get_current_user)):
        """Authenticated health check with detailed metrics."""
        return {
            "status": "ok",
            "tasks_total": len(task_queue.all_tasks()),
            "tasks_pending": sum(
                1 for t in task_queue.all_tasks() if t.status == TaskStatus.PENDING
            ),
            "tasks_running": sum(
                1 for t in task_queue.all_tasks() if t.status == TaskStatus.RUNNING
            ),
            "websocket_connections": ws_manager.connection_count,
        }

    # -- Platform Status -------------------------------------------------------

    @app.get("/api/status")
    async def get_status(_user: str = Depends(get_current_user)):
        """Full platform status with system metrics and dynamic capacity."""
        if heartbeat:
            health = heartbeat.get_health(task_queue=task_queue, tool_registry=tool_registry)
            return health.to_dict()
        # Fallback when heartbeat is not available
        from core.capacity import compute_effective_capacity

        cap = compute_effective_capacity(settings.max_concurrent_agents)
        return {
            "active_agents": 0,
            "stalled_agents": 0,
            "tasks_pending": 0,
            "tasks_completed": 0,
            "tasks_failed": 0,
            "uptime_seconds": 0,
            "memory_mb": 0,
            "tools_registered": 0,
            **{
                k: v
                for k, v in cap.items()
                if k not in ("configured_max", "auto_mode", "effective_max", "reason")
            },
            "effective_max_agents": cap["effective_max"],
            "configured_max_agents": cap["configured_max"],
            "capacity_auto_mode": cap.get("auto_mode", False),
            "capacity_reason": cap["reason"],
        }

    # -- Setup Wizard ----------------------------------------------------------

    @app.get("/api/setup/status")
    async def setup_status():
        """Check if first-run setup is needed. Unauthenticated."""
        needs_setup = (
            not settings.dashboard_password_hash
            and settings.dashboard_password in _INSECURE_PASSWORDS
        )
        return {"setup_needed": needs_setup}

    @app.post("/api/setup/complete")
    async def setup_complete(req: SetupRequest, request: Request):
        """Complete first-run setup: set password, optional API key, memory backend.

        Only available when no real password is configured (first run or
        insecure default).  Writes to .env, reloads settings, and returns
        a JWT for immediate login.  Optionally queues a Docker setup task
        when the user selects a memory backend that needs Docker services.
        """
        # Security gate: reject if a real password is already configured
        if settings.dashboard_password_hash or (
            settings.dashboard_password and settings.dashboard_password not in _INSECURE_PASSWORDS
        ):
            raise HTTPException(
                status_code=403,
                detail="Setup already completed. Use login instead.",
            )

        client_ip = request.client.host if request.client else "unknown"
        if not check_rate_limit(client_ip):
            raise HTTPException(
                status_code=429,
                detail="Too many attempts. Try again in 1 minute.",
            )

        password = req.password.strip()
        if len(password) < 8:
            raise HTTPException(
                status_code=400,
                detail="Password must be at least 8 characters.",
            )

        import secrets as _secrets

        password_hash = pwd_context.hash(password)
        jwt_secret = _secrets.token_hex(32)

        env_path = Path(__file__).parent.parent / ".env"
        _update_env_file(
            env_path,
            {
                "DASHBOARD_PASSWORD_HASH": password_hash,
                "DASHBOARD_PASSWORD": "",
                "JWT_SECRET": jwt_secret,
            },
        )

        if req.openrouter_api_key and req.openrouter_api_key.strip():
            import os

            api_key = req.openrouter_api_key.strip()
            _update_env_file(env_path, {"OPENROUTER_API_KEY": api_key})
            os.environ["OPENROUTER_API_KEY"] = api_key

        # Handle memory backend selection
        memory_backend = (req.memory_backend or "").strip().lower()
        setup_task_id = ""

        if memory_backend == "qdrant_embedded":
            _update_env_file(
                env_path,
                {
                    "QDRANT_ENABLED": "true",
                    "QDRANT_LOCAL_PATH": ".agent42/qdrant",
                },
            )
            await _pip_install(["qdrant-client"])
        elif memory_backend == "qdrant_redis":
            _update_env_file(
                env_path,
                {
                    "QDRANT_URL": "http://localhost:6333",
                    "QDRANT_ENABLED": "true",
                    "REDIS_URL": "redis://localhost:6379/0",
                },
            )
            await _pip_install(["qdrant-client", "redis[hiredis]"])
            # Auto-queue a task to verify memory backend connectivity
            setup_task = Task(
                title="Verify enhanced memory (Qdrant + Redis)",
                description=(
                    "The setup wizard selected Qdrant + Redis for enhanced memory.\n\n"
                    "If you used the production installer (deploy/install-server.sh),\n"
                    "Redis and Qdrant are already running as system services.\n\n"
                    "Verify connectivity:\n"
                    "  - Qdrant: curl http://localhost:6333/healthz\n"
                    "  - Redis:  redis-cli ping\n\n"
                    "If running locally without the installer, start them manually:\n"
                    "  sudo apt install redis-server\n"
                    "  # See docs for Qdrant installation\n\n"
                    "Restart Agent42 to pick up the new .env settings.\n\n"
                    "The .env file has already been configured with:\n"
                    "  QDRANT_URL=http://localhost:6333\n"
                    "  QDRANT_ENABLED=true\n"
                    "  REDIS_URL=redis://localhost:6379/0"
                ),
                task_type=TaskType.CODING,
                priority=10,
            )
            await task_queue.add(setup_task)
            setup_task_id = setup_task.id

        Settings.reload_from_env()

        logger.info(
            "First-run setup completed from %s (memory_backend=%s)",
            client_ip,
            memory_backend or "skip",
        )
        token = create_token(settings.dashboard_username)
        return {
            "status": "ok",
            "token": token,
            "message": "Setup complete. You are now logged in.",
            "memory_backend": memory_backend or "skip",
            "setup_task_id": setup_task_id,
        }

    # -- Auth ------------------------------------------------------------------

    @app.post("/api/login")
    async def login(req: LoginRequest, request: Request):
        # Fail-secure: reject all logins when no password is configured
        if not settings.dashboard_password and not settings.dashboard_password_hash:
            logger.warning("Login attempt with no password configured — rejected")
            raise HTTPException(
                status_code=401,
                detail="Dashboard login is disabled. Set DASHBOARD_PASSWORD or DASHBOARD_PASSWORD_HASH.",
            )

        client_ip = request.client.host if request.client else "unknown"

        if not check_rate_limit(client_ip):
            raise HTTPException(
                status_code=429,
                detail="Too many login attempts. Try again in 1 minute.",
            )

        if req.username != settings.dashboard_username or not verify_password(req.password):
            # Log diagnostic details (never the actual passwords)
            user_ok = req.username == settings.dashboard_username
            logger.warning(
                "Failed login for '%s' from %s — username_match=%s, "
                "password_len_sent=%d, password_configured=%s, hash_configured=%s",
                req.username,
                client_ip,
                user_ok,
                len(req.password),
                bool(settings.dashboard_password),
                bool(settings.dashboard_password_hash),
            )
            raise HTTPException(status_code=401, detail="Invalid credentials")

        logger.info(f"Successful login for '{req.username}' from {client_ip}")
        return {"token": create_token(req.username)}

    @app.post("/api/settings/password")
    async def change_password(
        req: ChangePasswordRequest,
        request: Request,
        _admin: AuthContext = Depends(require_admin),
    ):
        """Change the dashboard password. Requires current password verification."""
        client_ip = request.client.host if request.client else "unknown"

        if not check_rate_limit(client_ip):
            raise HTTPException(
                status_code=429,
                detail="Too many attempts. Try again in 1 minute.",
            )

        if not verify_password(req.current_password):
            logger.warning(
                "Failed password change attempt from %s — wrong current password", client_ip
            )
            raise HTTPException(status_code=401, detail="Current password is incorrect.")

        new_password = req.new_password.strip()
        if len(new_password) < 8:
            raise HTTPException(
                status_code=400,
                detail="New password must be at least 8 characters.",
            )

        new_hash = pwd_context.hash(new_password)
        env_path = Path(__file__).parent.parent / ".env"
        _update_env_file(
            env_path,
            {
                "DASHBOARD_PASSWORD_HASH": new_hash,
                "DASHBOARD_PASSWORD": "",
            },
        )
        Settings.reload_from_env()

        logger.info("Password changed successfully from %s", client_ip)
        token = create_token(settings.dashboard_username)
        return {"status": "ok", "token": token, "message": "Password changed successfully."}

    # -- Tasks -----------------------------------------------------------------

    @app.get("/api/tasks")
    async def list_tasks(_user: str = Depends(get_current_user)):
        return [t.to_dict() for t in task_queue.all_tasks()]

    @app.post("/api/tasks")
    async def create_task(req: TaskCreateRequest, auth: AuthContext = Depends(get_auth_context)):
        task = Task(
            title=req.title,
            description=req.description,
            task_type=TaskType(req.task_type),
            priority=req.priority,
            context_window=req.context_window,
            origin_device_id=auth.device_id,
            project_id=req.project_id,
            repo_id=req.repo_id,
            branch=req.branch,
            profile=req.profile,
        )
        await task_queue.add(task)
        return task.to_dict()

    @app.get("/api/tasks/{task_id}")
    async def get_task(task_id: str, _user: str = Depends(get_current_user)):
        task = task_queue.get(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        return task.to_dict()

    @app.post("/api/tasks/{task_id}/approve")
    async def approve_task(task_id: str, _user: str = Depends(get_current_user)):
        await task_queue.approve(task_id)
        return {"status": "approved"}

    @app.post("/api/tasks/{task_id}/escalate")
    async def escalate_to_l2(task_id: str, _user: str = Depends(get_current_user)):
        """Escalate an L1-completed task to L2 premium review."""
        task = task_queue.get(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        if task.status not in (TaskStatus.REVIEW, TaskStatus.DONE):
            raise HTTPException(
                status_code=400,
                detail="Only completed/review tasks can be escalated",
            )
        if task.tier == "L2":
            raise HTTPException(status_code=400, detail="Task is already at L2 tier")

        # Check L2 routing availability
        from agents.model_router import ModelRouter

        router = ModelRouter()
        l2_routing = router.get_l2_routing(task.task_type)
        if not l2_routing:
            raise HTTPException(
                status_code=400,
                detail="L2 tier not available — premium API key not configured",
            )

        # Create L2 review task
        from core.task_queue import Task as TaskModel

        l2_task = TaskModel(
            title=f"[L2 Review] {task.title}",
            description=task.description,
            task_type=task.task_type,
            tier="L2",
            l1_result=task.result or "",
            escalated_from=task.id,
            project_id=task.project_id,
            origin_channel=task.origin_channel,
            origin_channel_id=task.origin_channel_id,
            origin_device_id=task.origin_device_id,
            repo_id=task.repo_id,
            branch=task.branch,
        )
        await task_queue.add(l2_task)
        return {"task_id": l2_task.id, "status": "escalated"}

    @app.get("/api/l2/status")
    async def l2_status(_user: str = Depends(get_current_user)):
        """Check L2 tier availability for the dashboard UI."""
        from agents.model_router import ModelRouter

        router = ModelRouter()
        available_types = []
        for tt in TaskType:
            if router.get_l2_routing(tt) is not None:
                available_types.append(tt.value)
        return {
            "l2_enabled": bool(available_types),
            "available_task_types": available_types,
        }

    @app.post("/api/tasks/{task_id}/cancel")
    async def cancel_task(task_id: str, _user: str = Depends(get_current_user)):
        """Cancel a pending or running task."""
        await task_queue.cancel(task_id)
        return {"status": "cancelled"}

    @app.post("/api/tasks/{task_id}/retry")
    async def retry_task(task_id: str, _user: str = Depends(get_current_user)):
        """Re-queue a failed task."""
        task = task_queue.get(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        if task.status != TaskStatus.FAILED:
            raise HTTPException(status_code=400, detail="Only failed tasks can be retried")
        await task_queue.retry(task_id)
        return {"status": "retried"}

    # -- Mission Control (Kanban) endpoints ------------------------------------

    @app.get("/api/tasks/board")
    async def get_board(_user: str = Depends(get_current_user)):
        """Get tasks grouped by status for Kanban board."""
        return task_queue.board()

    @app.patch("/api/tasks/{task_id}/move")
    async def move_task(task_id: str, req: TaskMoveRequest, _user: str = Depends(get_current_user)):
        """Move task to a new status column (Kanban drag-and-drop)."""
        task = task_queue.get(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        await task_queue.move_task(task_id, req.status, req.position)
        return {"status": "moved", "new_status": req.status}

    @app.post("/api/tasks/{task_id}/comment")
    async def add_comment(
        task_id: str, req: TaskCommentRequest, _user: str = Depends(get_current_user)
    ):
        """Add a comment to a task thread.

        Comments are stored on the task AND routed to the running agent
        (via intervention queue) so Agent42 can act on them.  A task_update
        broadcast ensures all connected clients (including open chat views)
        see the new comment in real time.
        """
        task = task_queue.get(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        author = req.author or _user
        task.add_comment(author, req.text)
        await task_queue._persist(task)

        # Route the comment text to the running agent so it can act on it
        active_statuses = {TaskStatus.PENDING, TaskStatus.ASSIGNED, TaskStatus.RUNNING}
        if task.status in active_statuses:
            await task_queue.route_message_to_task(
                task,
                req.text,
                author,
                intervention_queues or {},
            )

        # Broadcast task update so all clients (task view + chat) refresh
        await ws_manager.broadcast("task_update", task.to_dict())

        # If this task originated from a chat session, also mirror the
        # comment as a chat message so the chat view stays in sync.
        session_id = task.origin_metadata.get("chat_session_id", "")
        if session_id and chat_session_manager:
            import time as _time
            import uuid as _uuid

            chat_msg = {
                "id": _uuid.uuid4().hex[:12],
                "role": "user",
                "content": req.text,
                "timestamp": _time.time(),
                "sender": author,
                "session_id": session_id,
                "source": "task_comment",
                "task_id": task_id,
            }
            await chat_session_manager.add_message(session_id, chat_msg)
            await ws_manager.broadcast("chat_message", chat_msg)

        return {"status": "comment_added", "comments": len(task.comments)}

    @app.patch("/api/tasks/{task_id}/assign")
    async def assign_task(
        task_id: str, req: TaskAssignRequest, _user: str = Depends(get_current_user)
    ):
        """Assign task to a specific agent."""
        task = task_queue.get(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        task.assigned_agent = req.agent_id
        task.status = TaskStatus.ASSIGNED
        task.updated_at = __import__("time").time()
        await task_queue._persist()
        return {"status": "assigned", "agent_id": req.agent_id}

    @app.patch("/api/tasks/{task_id}/priority")
    async def set_priority(
        task_id: str, req: TaskPriorityRequest, _user: str = Depends(get_current_user)
    ):
        """Set task priority."""
        task = task_queue.get(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        task.priority = req.priority
        task.updated_at = __import__("time").time()
        await task_queue._persist()
        return {"status": "priority_set", "priority": req.priority}

    @app.patch("/api/tasks/{task_id}/block")
    async def block_task(
        task_id: str, req: TaskBlockRequest, _user: str = Depends(get_current_user)
    ):
        """Mark task as blocked with reason."""
        task = task_queue.get(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        task.block(req.reason)
        await task_queue._persist()
        return {"status": "blocked", "reason": req.reason}

    @app.patch("/api/tasks/{task_id}/unblock")
    async def unblock_task(task_id: str, _user: str = Depends(get_current_user)):
        """Remove blocked status from task."""
        task = task_queue.get(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        task.unblock()
        await task_queue._persist()
        return {"status": "unblocked"}

    @app.post("/api/tasks/{task_id}/archive")
    async def archive_task(task_id: str, _user: str = Depends(get_current_user)):
        """Archive a completed task."""
        task = task_queue.get(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        if task.status == TaskStatus.RUNNING:
            raise HTTPException(status_code=400, detail="Cannot archive a running task")
        task.archive()
        await task_queue._persist()
        return {"status": "archived"}

    # -- Mid-Task Intervention (Agent Zero-inspired) ---------------------------

    @app.post("/api/tasks/{task_id}/intervene")
    async def intervene_task(
        task_id: str, req: InterventionRequest, _user: str = Depends(get_current_user)
    ):
        """Inject a user feedback message into a running agent's iteration loop.

        The message is queued and consumed at the start of the next iteration,
        allowing real-time course correction without stopping the agent.
        """
        task = task_queue.get(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        if not req.message or not req.message.strip():
            raise HTTPException(status_code=400, detail="Intervention message cannot be empty")

        queue = (intervention_queues or {}).get(task_id)
        if queue is None:
            raise HTTPException(
                status_code=409,
                detail="No active agent for this task. Task may not be running.",
            )

        await queue.put(req.message.strip())
        await ws_manager.broadcast(
            "agent_intervention_received",
            {"task_id": task_id, "message": req.message.strip()},
        )
        return {"status": "queued", "message": req.message.strip()}

    @app.post("/api/tasks/{task_id}/input")
    async def provide_task_input(
        task_id: str, req: UserInputResponse, _user: str = Depends(get_current_user)
    ):
        """Provide a response to the agent's input request (notify_user request_input).

        The agent will receive this response and continue execution.
        """
        from tools.notify_tool import resolve_input

        resolved = resolve_input(task_id, req.response)
        if not resolved:
            raise HTTPException(status_code=409, detail="No pending input request for this task.")
        return {"status": "resolved", "response": req.response}

    # -- Agent Profiles (Agent Zero-inspired) ----------------------------------

    @app.get("/api/profiles")
    async def list_profiles(_user: str = Depends(get_current_user)):
        """List all available agent profiles."""
        if not profile_loader:
            return []
        return [p.to_dict() for p in profile_loader.all_profiles()]

    @app.get("/api/profiles/{name}")
    async def get_profile(name: str, _user: str = Depends(get_current_user)):
        """Get a specific agent profile by name."""
        if not profile_loader:
            raise HTTPException(status_code=404, detail="Profile system not available")
        profile = profile_loader.get(name)
        if not profile:
            raise HTTPException(status_code=404, detail=f"Profile '{name}' not found")
        return {**profile.to_dict(), "prompt_overlay": profile.prompt_overlay}

    # -- Activity Feed --------------------------------------------------------

    _activity_feed: list[dict] = []

    @app.get("/api/activity")
    async def get_activity(_user: str = Depends(get_current_user)):
        """Get recent activity feed (last 200 events)."""
        return _activity_feed[-200:]

    # -- Token Usage Stats ----------------------------------------------------

    @app.get("/api/stats/tokens")
    async def get_token_stats(_user: str = Depends(get_current_user)):
        """Get aggregate token usage across all tasks."""
        from providers.registry import spending_tracker

        total_tokens = 0
        total_prompt = 0
        total_completion = 0
        by_model: dict = {}

        for task in task_queue.all_tasks():
            usage = task.token_usage
            if not usage or not isinstance(usage, dict):
                continue
            total_tokens += usage.get("total_tokens", 0)
            total_prompt += usage.get("total_prompt_tokens", 0)
            total_completion += usage.get("total_completion_tokens", 0)
            for model_key, model_data in usage.get("by_model", {}).items():
                if model_key not in by_model:
                    by_model[model_key] = {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0}
                by_model[model_key]["prompt_tokens"] += model_data.get("prompt_tokens", 0)
                by_model[model_key]["completion_tokens"] += model_data.get("completion_tokens", 0)
                by_model[model_key]["calls"] += model_data.get("calls", 0)

        return {
            "total_tokens": total_tokens,
            "total_prompt_tokens": total_prompt,
            "total_completion_tokens": total_completion,
            "by_model": by_model,
            "daily_spend_usd": spending_tracker.daily_spend_usd,
            "daily_tokens": spending_tracker.daily_tokens,
        }

    # -- Reports (admin analytics) -------------------------------------------

    @app.get("/api/reports")
    async def get_reports(_: AuthContext = Depends(require_admin)):
        """Aggregate analytics data for the Reports page."""
        from providers.registry import spending_tracker

        all_tasks = task_queue.all_tasks()

        # -- LLM usage (per-model token breakdown) --
        model_agg: dict[str, dict] = {}
        total_tokens = 0
        total_prompt = 0
        total_completion = 0
        type_agg: dict[str, dict] = {}
        status_counts: dict[str, int] = {}

        for task in all_tasks:
            # Status counts
            s = task.status.value if hasattr(task.status, "value") else str(task.status)
            status_counts[s] = status_counts.get(s, 0) + 1

            # Task-type aggregation
            tt = task.task_type.value if hasattr(task.task_type, "value") else str(task.task_type)
            if tt not in type_agg:
                type_agg[tt] = {
                    "type": tt,
                    "total": 0,
                    "done": 0,
                    "failed": 0,
                    "running": 0,
                    "pending": 0,
                    "total_iterations": 0,
                    "total_tokens": 0,
                }
            type_agg[tt]["total"] += 1
            type_agg[tt][s] = type_agg[tt].get(s, 0) + 1
            type_agg[tt]["total_iterations"] += getattr(task, "iterations", 0) or 0

            # Token usage
            usage = task.token_usage
            if not usage or not isinstance(usage, dict):
                continue
            t_tok = usage.get("total_tokens", 0)
            t_p = usage.get("total_prompt_tokens", 0)
            t_c = usage.get("total_completion_tokens", 0)
            total_tokens += t_tok
            total_prompt += t_p
            total_completion += t_c
            type_agg[tt]["total_tokens"] += t_tok

            for model_key, mdata in usage.get("by_model", {}).items():
                if model_key not in model_agg:
                    model_agg[model_key] = {
                        "model_key": model_key,
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "total_tokens": 0,
                        "calls": 0,
                        "estimated_cost_usd": 0.0,
                    }
                mp = mdata.get("prompt_tokens", 0)
                mc = mdata.get("completion_tokens", 0)
                model_agg[model_key]["prompt_tokens"] += mp
                model_agg[model_key]["completion_tokens"] += mc
                model_agg[model_key]["total_tokens"] += mp + mc
                model_agg[model_key]["calls"] += mdata.get("calls", 0)

        # Estimate costs per model using spending tracker pricing
        for mk, md in model_agg.items():
            # Look up actual pricing if available
            price = spending_tracker._model_prices.get(mk)
            if price:
                md["estimated_cost_usd"] = round(
                    md["prompt_tokens"] * price[0] + md["completion_tokens"] * price[1], 6
                )
            else:
                # Conservative fallback: $5/$15 per million tokens
                md["estimated_cost_usd"] = round(
                    (md["prompt_tokens"] * 5.0 + md["completion_tokens"] * 15.0) / 1_000_000, 6
                )

        llm_usage = sorted(model_agg.values(), key=lambda m: m["total_tokens"], reverse=True)

        # Task type breakdown with success rates
        task_types = []
        for td in sorted(type_agg.values(), key=lambda t: t["total"], reverse=True):
            done = td.get("done", 0)
            failed = td.get("failed", 0)
            completed = done + failed
            td["success_rate"] = round(done / completed, 3) if completed > 0 else 0.0
            avg_iter = td["total_iterations"] / td["total"] if td["total"] > 0 else 0
            td["avg_iterations"] = round(avg_iter, 1)
            task_types.append(td)

        # -- Model performance (from evaluator) --
        model_perf = []
        if model_evaluator:
            for stats in model_evaluator._stats.values():
                model_perf.append(stats.to_dict())
            model_perf.sort(key=lambda m: m.get("composite_score", 0), reverse=True)

        # -- Connectivity / health --
        connectivity: dict = {"summary": {}, "models": {}}
        if model_catalog:
            connectivity["summary"] = model_catalog.get_health_summary()
            connectivity["models"] = model_catalog._health_status

        # -- Project breakdown --
        project_list = []
        if project_manager:
            for proj in project_manager.all_projects():
                pstats = project_manager.project_stats(proj.id)
                project_list.append(
                    {
                        "id": proj.id,
                        "name": proj.name,
                        "status": proj.status,
                        "total_tasks": pstats.get("total", 0),
                        "done": pstats.get("done", 0),
                        "failed": pstats.get("failed", 0),
                        "running": pstats.get("running", 0),
                        "pending": pstats.get("pending", 0),
                    }
                )

        # -- Tools & skills summary --
        tools_summary = {"total": 0, "enabled": 0}
        if tool_registry:
            all_tools = tool_registry.all_schemas()
            tools_summary["total"] = len(all_tools)
            tools_summary["enabled"] = sum(1 for t in all_tools if t.get("enabled", True))

        skills_summary = {"total": 0, "enabled": 0, "skills": []}
        if skill_loader:
            all_skills = skill_loader.all_skills()
            skills_summary["total"] = len(all_skills)
            skills_summary["enabled"] = sum(1 for s in all_skills if s.enabled is not False)
            skills_summary["skills"] = [
                {
                    "name": s.name,
                    "description": getattr(s, "description", ""),
                    "task_types": getattr(s, "task_types", []),
                    "enabled": getattr(s, "enabled", True),
                }
                for s in all_skills
            ]

        # Total cost across all models
        total_cost = round(sum(m["estimated_cost_usd"] for m in llm_usage), 4)

        # Done / failed for overall success rate
        total_done = status_counts.get("done", 0)
        total_failed = status_counts.get("failed", 0)
        total_completed = total_done + total_failed
        overall_success_rate = (
            round(total_done / total_completed, 3) if total_completed > 0 else 0.0
        )

        return {
            "token_usage": {
                "total_tokens": total_tokens,
                "total_prompt_tokens": total_prompt,
                "total_completion_tokens": total_completion,
                "daily_tokens": spending_tracker.daily_tokens,
                "daily_spend_usd": spending_tracker.daily_spend_usd,
            },
            "llm_usage": llm_usage,
            "costs": {
                "daily_spend_usd": spending_tracker.daily_spend_usd,
                "total_estimated_usd": total_cost,
                "by_model": llm_usage,  # same list, includes estimated_cost_usd
            },
            "connectivity": connectivity,
            "model_performance": model_perf,
            "task_breakdown": {
                "total": len(all_tasks),
                "by_status": status_counts,
                "by_type": task_types,
                "overall_success_rate": overall_success_rate,
            },
            "project_breakdown": project_list,
            "tools": tools_summary,
            "skills": skills_summary,
        }

    # -- Notification config endpoint -----------------------------------------

    @app.get("/api/notifications/config")
    async def get_notification_config(_user: str = Depends(get_current_user)):
        """Get current notification configuration."""
        return {
            "webhook_urls": settings.get_webhook_urls(),
            "webhook_events": settings.get_webhook_events(),
            "email_recipients": settings.get_notification_email_recipients(),
        }

    # -- Approvals -------------------------------------------------------------

    @app.get("/api/approvals")
    async def list_approvals(_user: str = Depends(get_current_user)):
        return approval_gate.pending_requests()

    @app.post("/api/approvals")
    async def handle_approval(req: ApprovalAction, _user: str = Depends(get_current_user)):
        if req.approved:
            approval_gate.approve(req.task_id, req.action, user=_user)
        else:
            approval_gate.deny(req.task_id, req.action, user=_user)
        return {"status": "ok"}

    # -- Review Feedback (learning from human review) --------------------------

    @app.post("/api/tasks/{task_id}/review")
    async def submit_review_feedback(
        task_id: str, req: ReviewFeedback, _user: str = Depends(get_current_user)
    ):
        """Submit human reviewer feedback — the agent learns from this."""
        task = task_queue.get(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        if learner:
            await learner.record_reviewer_feedback(
                task_id=task_id,
                task_title=task.title,
                feedback=req.feedback,
                approved=req.approved,
            )
        if req.approved:
            await task_queue.approve(task_id)
        return {"status": "feedback recorded", "approved": req.approved}

    # -- Devices (Gateway Authentication) --------------------------------------

    @app.post("/api/devices/register")
    async def register_device(
        req: DeviceRegisterRequest, _admin: AuthContext = Depends(require_admin)
    ):
        """Register a new device and return its API key (shown once)."""
        if not device_store:
            raise HTTPException(status_code=503, detail="Device store not configured")

        device, raw_key = device_store.register(
            name=req.name,
            device_type=req.device_type,
            capabilities=req.capabilities,
        )
        return {
            "device_id": device.device_id,
            "name": device.name,
            "device_type": device.device_type,
            "capabilities": device.capabilities,
            "api_key": raw_key,
            "message": "Store this API key securely — it will not be shown again.",
        }

    @app.get("/api/devices")
    async def list_devices(_user: str = Depends(get_current_user)):
        """List all registered devices with online status."""
        if not device_store:
            return []
        connected = ws_manager.connected_device_ids()
        return [
            {
                "device_id": d.device_id,
                "name": d.name,
                "device_type": d.device_type,
                "capabilities": d.capabilities,
                "created_at": d.created_at,
                "last_seen": d.last_seen,
                "is_revoked": d.is_revoked,
                "is_online": d.device_id in connected,
            }
            for d in device_store.list_devices()
        ]

    @app.get("/api/devices/{device_id}")
    async def get_device(device_id: str, _user: str = Depends(get_current_user)):
        """Get details for a specific device."""
        if not device_store:
            raise HTTPException(status_code=503, detail="Device store not configured")
        device = device_store.get(device_id)
        if not device:
            raise HTTPException(status_code=404, detail="Device not found")
        connected = ws_manager.connected_device_ids()
        return {
            "device_id": device.device_id,
            "name": device.name,
            "device_type": device.device_type,
            "capabilities": device.capabilities,
            "created_at": device.created_at,
            "last_seen": device.last_seen,
            "is_revoked": device.is_revoked,
            "is_online": device.device_id in connected,
        }

    @app.post("/api/devices/{device_id}/revoke")
    async def revoke_device(device_id: str, _admin: AuthContext = Depends(require_admin)):
        """Revoke a device's API key (admin only)."""
        if not device_store:
            raise HTTPException(status_code=503, detail="Device store not configured")
        if not device_store.revoke(device_id):
            raise HTTPException(status_code=404, detail="Device not found")
        return {"status": "revoked", "device_id": device_id}

    # -- Providers (Phase 5) ---------------------------------------------------

    @app.get("/api/providers")
    async def list_providers(_user: str = Depends(get_current_user)):
        from providers.registry import ProviderRegistry

        registry = ProviderRegistry()
        return {
            "providers": registry.available_providers(),
            "models": registry.available_models(),
        }

    # -- Tools (Phase 4) ------------------------------------------------------

    @app.get("/api/tools")
    async def list_tools(_user: str = Depends(get_current_user)):
        if tool_registry:
            return tool_registry.list_tools()
        return []

    @app.patch("/api/tools/{name}")
    async def toggle_tool(
        name: str, req: ToggleRequest, _admin: AuthContext = Depends(require_admin)
    ):
        """Enable or disable a tool by name (admin only)."""
        if not tool_registry:
            raise HTTPException(status_code=503, detail="Tool registry not available")
        if not tool_registry.set_enabled(name, req.enabled):
            raise HTTPException(status_code=404, detail=f"Tool '{name}' not found")
        # Persist updated state
        disabled = [t["name"] for t in tool_registry.list_tools() if not t["enabled"]]
        disabled_skills: list[str] = []
        if skill_loader:
            disabled_skills = [
                s.name for s in skill_loader.all_skills() if not skill_loader.is_enabled(s.name)
            ]
        _save_toggle_state(disabled, disabled_skills)
        return {"name": name, "enabled": req.enabled}

    # -- Skills (Phase 3) -----------------------------------------------------

    @app.get("/api/skills")
    async def list_skills(_user: str = Depends(get_current_user)):
        if skill_loader:
            return [
                {
                    "name": s.name,
                    "description": s.description,
                    "always_load": s.always_load,
                    "task_types": s.task_types,
                    "enabled": skill_loader.is_enabled(s.name),
                }
                for s in skill_loader.all_skills()
            ]
        return []

    @app.patch("/api/skills/{name}")
    async def toggle_skill(
        name: str, req: ToggleRequest, _admin: AuthContext = Depends(require_admin)
    ):
        """Enable or disable a skill by name (admin only)."""
        if not skill_loader:
            raise HTTPException(status_code=503, detail="Skill loader not available")
        if not skill_loader.set_enabled(name, req.enabled):
            raise HTTPException(status_code=404, detail=f"Skill '{name}' not found")
        # Persist updated state
        disabled_skills = [
            s.name for s in skill_loader.all_skills() if not skill_loader.is_enabled(s.name)
        ]
        disabled_tools: list[str] = []
        if tool_registry:
            disabled_tools = [t["name"] for t in tool_registry.list_tools() if not t["enabled"]]
        _save_toggle_state(disabled_tools, disabled_skills)
        return {"name": name, "enabled": req.enabled}

    # -- Settings (API Keys) --------------------------------------------------

    @app.get("/api/settings/keys")
    async def get_api_keys(_admin: AuthContext = Depends(require_admin)):
        """Get all configurable API keys with masked values (admin only)."""
        if not key_store:
            raise HTTPException(status_code=503, detail="Key store not configured")
        return key_store.get_masked_keys()

    @app.put("/api/settings/keys")
    async def update_api_keys(req: KeyUpdateRequest, _admin: AuthContext = Depends(require_admin)):
        """Update one or more API keys (admin only)."""
        if not key_store:
            raise HTTPException(status_code=503, detail="Key store not configured")

        from core.key_store import ADMIN_CONFIGURABLE_KEYS

        errors = []
        updated = []
        for env_var, value in req.keys.items():
            if env_var not in ADMIN_CONFIGURABLE_KEYS:
                errors.append(f"{env_var} is not a configurable key")
                continue
            value = value.strip()
            if not value:
                key_store.delete_key(env_var)
            else:
                key_store.set_key(env_var, value)
            updated.append(env_var)

        # Keys are injected into os.environ by set_key/delete_key.
        # _build_client() reads from os.getenv(spec.api_key_env) so new
        # ProviderRegistry instances (created per-agent-run) pick up the
        # change immediately. Reload settings so that any code reading
        # settings.xxx_api_key directly also sees the new value.
        Settings.reload_from_env()
        return {"status": "ok", "updated": updated, "errors": errors}

    # -- Settings (Editable .env) ----------------------------------------------

    @app.get("/api/settings/env")
    async def get_env_settings(_admin: AuthContext = Depends(require_admin)):
        """Get current values for dashboard-editable settings."""
        import os

        result: dict[str, str] = {}
        for key in _DASHBOARD_EDITABLE_SETTINGS:
            result[key] = os.getenv(key, "")
        return result

    @app.put("/api/settings/env")
    async def update_env_settings(
        req: SettingsUpdateRequest, _admin: AuthContext = Depends(require_admin)
    ):
        """Update .env settings and hot-reload the config."""
        import os

        env_path = Path(__file__).parent.parent / ".env"
        errors = []
        updated = []

        updates = {}
        for key, value in req.settings.items():
            if key not in _DASHBOARD_EDITABLE_SETTINGS:
                errors.append(f"{key} is not editable from the dashboard")
                continue
            stripped = value.strip()
            if key == "MODEL_ROUTING_POLICY" and stripped not in {
                "free_only",
                "balanced",
                "performance",
            }:
                errors.append(
                    "MODEL_ROUTING_POLICY must be one of: free_only, balanced, performance"
                )
                continue
            updates[key] = stripped
            updated.append(key)

        if updates:
            _update_env_file(env_path, updates)
            for key, value in updates.items():
                os.environ[key] = value
            Settings.reload_from_env()

        return {"status": "ok", "updated": updated, "errors": errors}

    @app.get("/api/settings/openrouter-status")
    async def get_openrouter_status(_: AuthContext = Depends(require_admin)):
        """Return OpenRouter account status and routing policy info."""
        import os

        from providers.registry import MODELS

        policy = os.getenv("MODEL_ROUTING_POLICY", "balanced")
        account = model_catalog.openrouter_account_status if model_catalog else None
        if account is None and model_catalog and os.getenv("OPENROUTER_API_KEY"):
            account = await model_catalog.check_account(api_key=os.getenv("OPENROUTER_API_KEY", ""))
        paid_count = len([k for k in MODELS if k.startswith("or-paid-")]) if model_catalog else 0
        return {"policy": policy, "account": account, "paid_models_registered": paid_count}

    @app.get("/api/models/health")
    async def get_model_health(_: AuthContext = Depends(require_admin)):
        """Return model health check results and summary."""
        if not model_catalog:
            return {"error": "Model catalog not available", "summary": {}, "models": {}}
        summary = model_catalog.get_health_summary()
        return {
            "summary": summary,
            "models": model_catalog._health_status,
        }

    @app.post("/api/models/health-check")
    async def trigger_health_check(_: AuthContext = Depends(require_admin)):
        """Manually trigger a model health check."""
        import os

        if not model_catalog:
            return {"error": "Model catalog not available"}
        api_key = os.getenv("OPENROUTER_API_KEY", "")
        await model_catalog.health_check(api_key=api_key)
        return model_catalog.get_health_summary()

    @app.get("/api/settings/rlm-status")
    async def get_rlm_status(_: AuthContext = Depends(require_admin)):
        """Return RLM (Recursive Language Model) status and configuration."""
        try:
            from providers.rlm_provider import RLMProvider

            provider = RLMProvider()
            return provider.get_status()
        except Exception as e:
            return {"enabled": False, "error": str(e)}

    @app.get("/api/settings/storage")
    async def get_storage_status(_admin: AuthContext = Depends(require_admin)):
        """Return the active storage backend configuration and live connectivity status."""
        # Determine configured backend mode from settings
        qdrant_enabled = settings.qdrant_enabled
        qdrant_url = settings.qdrant_url
        qdrant_local_path = settings.qdrant_local_path
        redis_url = settings.redis_url

        if qdrant_enabled and redis_url:
            mode = "qdrant_redis"
        elif qdrant_enabled and not redis_url:
            mode = "qdrant_embedded" if not qdrant_url else "qdrant_server"
        else:
            mode = "file"

        qdrant_status = "disabled"
        redis_status = "disabled"

        # Check Qdrant connectivity
        if qdrant_enabled:
            try:
                import importlib.util

                if importlib.util.find_spec("qdrant_client") is None:
                    qdrant_status = "not_installed"
                elif qdrant_url:
                    # Server mode — attempt HTTP health check
                    import httpx

                    async with httpx.AsyncClient(timeout=3.0) as client:
                        resp = await client.get(f"{qdrant_url.rstrip('/')}/healthz")
                    qdrant_status = "connected" if resp.status_code == 200 else "unreachable"
                else:
                    # Embedded mode — check local path exists / is writable
                    p = Path(qdrant_local_path)
                    qdrant_status = "embedded_ok" if (p.exists() or not p.exists()) else "error"
                    # Always reachable for embedded — no network needed
                    qdrant_status = "embedded_ok"
            except Exception:
                qdrant_status = "unreachable"

        # Check Redis connectivity
        if redis_url:
            try:
                import importlib.util

                if importlib.util.find_spec("redis") is None:
                    redis_status = "not_installed"
                else:
                    import redis as redis_lib

                    client = redis_lib.from_url(
                        redis_url,
                        socket_timeout=2,
                        socket_connect_timeout=2,
                        decode_responses=True,
                    )
                    await asyncio.get_running_loop().run_in_executor(None, client.ping)
                    redis_status = "connected"
            except Exception:
                redis_status = "unreachable"

        return {
            "mode": mode,
            "qdrant": {
                "enabled": qdrant_enabled,
                "url": qdrant_url or None,
                "local_path": qdrant_local_path if (qdrant_enabled and not qdrant_url) else None,
                "status": qdrant_status,
            },
            "redis": {
                "enabled": bool(redis_url),
                "url": redis_url or None,
                "status": redis_status,
            },
        }

    @app.post("/api/settings/storage/install-packages")
    async def install_storage_packages(_admin: AuthContext = Depends(require_admin)):
        """Install missing Python packages for the configured storage backend.

        Installs qdrant-client if Qdrant is enabled and the package is absent.
        Installs redis[hiredis] if a Redis URL is configured and the package is absent.
        Requires admin auth. Returns lists of installed packages and any errors.
        """
        import importlib.util

        to_install: list[str] = []

        if settings.qdrant_enabled and importlib.util.find_spec("qdrant_client") is None:
            to_install.append("qdrant-client")

        if settings.redis_url and importlib.util.find_spec("redis") is None:
            to_install.append("redis[hiredis]")

        if not to_install:
            return {
                "status": "ok",
                "installed": [],
                "errors": [],
                "message": "All packages already installed.",
            }

        installed, errors = await _pip_install(to_install)
        return {
            "status": "ok" if not errors else "partial",
            "installed": installed,
            "errors": errors,
        }

    # -- Channels (Phase 2) ---------------------------------------------------

    @app.get("/api/channels")
    async def list_channels(_user: str = Depends(get_current_user)):
        if channel_manager:
            return channel_manager.list_channels()
        return []

    # -- Chat ------------------------------------------------------------------

    # Chat history is stored on ws_manager.chat_messages so agent42.py
    # can also append assistant messages (ensuring reload persistence).
    _chat_messages = ws_manager.chat_messages

    class ChatSendRequest(BaseModel):
        message: str

    @app.get("/api/chat/messages")
    async def get_chat_messages(_user: str = Depends(get_current_user)):
        """Return the dashboard chat history."""
        return _chat_messages[-200:]  # Last 200 messages

    @app.post("/api/chat/send")
    async def send_chat_message(
        req: ChatSendRequest, auth: AuthContext = Depends(get_auth_context)
    ):
        """Send a message in the dashboard chat.

        Creates a task from the user's message so an agent processes it.
        The agent's result is posted back as an assistant message via the
        task_update callback.
        """
        import time as _time
        import uuid as _uuid

        text = req.message.strip()
        if not text:
            raise HTTPException(status_code=400, detail="Message cannot be empty.")
        if len(text) > 4000:
            raise HTTPException(status_code=400, detail="Message too long (max 4000 chars).")

        msg_id = _uuid.uuid4().hex[:12]
        user_msg = {
            "id": msg_id,
            "role": "user",
            "content": text,
            "timestamp": _time.time(),
            "sender": auth.user,
        }
        _chat_messages.append(user_msg)
        await ws_manager.broadcast("chat_message", user_msg)

        # Route to active task if one exists for dashboard chat
        _existing = task_queue.find_active_task(
            origin_channel="dashboard_chat",
            origin_channel_id="chat",
        )
        if _existing:
            await task_queue.route_message_to_task(
                _existing,
                text,
                auth.user,
                intervention_queues or {},
            )
            return {"status": "queued", "message": user_msg, "task_id": _existing.id}

        # Classify task type — use LLM classifier with conversation history when
        # available; fall back to keyword matching if no classifier is injected.
        classification = None
        if intent_classifier is not None:
            history = [
                {"role": m["role"], "content": m["content"]}
                for m in _chat_messages[-10:]
                if m.get("role") in ("user", "assistant") and m.get("content")
            ]
            classification = await intent_classifier.classify(text, conversation_history=history)
            task_type = classification.task_type
        else:
            from core.task_queue import infer_task_type

            task_type = infer_task_type(text)

        # Conversational mode: respond directly without creating a task
        if classification and classification.is_conversational and settings.conversational_enabled:
            try:
                from agents.agent import GENERAL_ASSISTANT_PROMPT
                from agents.model_router import ModelRouter

                _conv_router = ModelRouter()
                _conv_model = settings.conversational_model
                if not _conv_model:
                    _conv_routing = _conv_router.get_routing(TaskType.EMAIL)
                    _conv_model = _conv_routing["primary"]

                _conv_messages = [{"role": "system", "content": GENERAL_ASSISTANT_PROMPT}]
                for h in history[-10:]:
                    _conv_messages.append(h)
                _conv_messages.append({"role": "user", "content": text})

                _conv_text, _ = await asyncio.wait_for(
                    _conv_router.complete(_conv_model, _conv_messages),
                    timeout=30.0,
                )
                if _conv_text:
                    _reply_msg = {
                        "id": _uuid.uuid4().hex[:12],
                        "role": "assistant",
                        "content": _conv_text,
                        "timestamp": _time.time(),
                        "sender": "Agent42",
                    }
                    _chat_messages.append(_reply_msg)
                    await ws_manager.broadcast("chat_message", _reply_msg)

                    # Persist to chat session if available
                    if req.session_id and chat_session_manager:
                        await chat_session_manager.add_message(req.session_id, user_msg)
                        await chat_session_manager.add_message(req.session_id, _reply_msg)

                    return {"status": "ok", "message": user_msg, "reply": _reply_msg}
            except Exception as _conv_err:
                logger.warning(
                    "Dashboard conversational response failed, falling back to task: %s",
                    _conv_err,
                )

        # No active task — create new one
        task = Task(
            title=text[:120] + ("..." if len(text) > 120 else ""),
            description=text,
            task_type=task_type,
            priority=1,
            origin_channel="dashboard_chat",
            origin_channel_id="chat",
            origin_metadata={"chat_msg_id": msg_id},
        )

        # Smart project creation: only create a project when the classifier
        # determines this is an ongoing goal (not simple Q&A).
        if classification and classification.needs_project and project_manager:
            _proj = await project_manager.create(
                name=text[:60],
                description="Auto-created for dashboard chat goal",
                status="active",
            )
            task.project_id = _proj.id

        await task_queue.add(task)

        return {"status": "ok", "message": user_msg, "task_id": task.id}

    # -- WebSocket -------------------------------------------------------------

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket):
        # Connection limit
        if ws_manager.connection_count >= settings.max_websocket_connections:
            await ws.close(code=4003, reason="Too many connections")
            return

        # Authenticate via query parameter: ws://host/ws?token=<jwt_or_api_key>
        token = ws.query_params.get("token")
        if not token:
            await ws.close(code=4001, reason="Missing token")
            return

        user = ""
        device_id = ""
        device_name = ""

        if token.startswith(API_KEY_PREFIX):
            # API key authentication (device)
            if not device_store:
                await ws.close(code=4001, reason="Device auth not configured")
                return
            device = device_store.validate_api_key(token)
            if not device:
                await ws.close(code=4001, reason="Invalid or revoked API key")
                return
            user = "device"
            device_id = device.device_id
            device_name = device.name
        else:
            # JWT authentication (dashboard user)
            try:
                from jose import ExpiredSignatureError, JWTError
                from jose import jwt as jose_jwt

                payload = jose_jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
                if not payload.get("sub"):
                    await ws.close(code=4001, reason="Invalid token")
                    return
                user = payload["sub"]
            except ExpiredSignatureError:
                await ws.close(code=4001, reason="Token expired")
                return
            except JWTError:
                await ws.close(code=4001, reason="Invalid token")
                return
            except Exception as e:
                logger.error(f"Unexpected error in WebSocket auth: {e}")
                await ws.close(code=1011, reason="Server error")
                return

        await ws_manager.connect(ws, user=user, device_id=device_id, device_name=device_name)
        try:
            while True:
                data = await ws.receive_text()
                # Validate incoming message size (prevent memory exhaustion)
                if len(data) > 4096:
                    logger.warning("WebSocket message too large, ignoring")
                    continue
                # Client messages are currently ignored (server-push only)
                # but we validate and log for future use
        except WebSocketDisconnect:
            ws_manager.disconnect(ws)

    # -- Chat Sessions ---------------------------------------------------------

    if chat_session_manager:

        class ChatSessionCreateRequest(BaseModel):
            title: str = ""
            session_type: str = "chat"

        class ChatSessionUpdateRequest(BaseModel):
            title: str = ""

        class ChatSessionSendRequest(BaseModel):
            message: str

        class ChatSessionSetupRequest(BaseModel):
            mode: str = "local"  # "local", "remote", or "github"
            runtime: str = "python"
            app_name: str = ""
            ssh_host: str = ""
            deploy_now: bool = False
            github_repo_name: str = ""
            github_clone_url: str = ""
            github_private: bool = True
            repo_id: str = ""  # Use an already-connected repo from Settings

        @app.get("/api/chat/sessions")
        async def list_chat_sessions(
            type: str = "",
            _user: str = Depends(get_current_user),
        ):
            """List chat sessions, optionally filtered by type."""
            sessions = chat_session_manager.list_sessions(session_type=type)
            return [s.to_dict() for s in sessions]

        @app.post("/api/chat/sessions")
        async def create_chat_session(
            req: ChatSessionCreateRequest,
            _user: str = Depends(get_current_user),
        ):
            """Create a new chat session."""
            session = await chat_session_manager.create(
                title=req.title or "New Chat",
                session_type=req.session_type,
            )
            return session.to_dict()

        @app.get("/api/chat/sessions/{session_id}")
        async def get_chat_session(
            session_id: str,
            _user: str = Depends(get_current_user),
        ):
            """Get chat session details."""
            session = await chat_session_manager.get(session_id)
            if not session:
                raise HTTPException(status_code=404, detail="Session not found")
            return session.to_dict()

        @app.patch("/api/chat/sessions/{session_id}")
        async def update_chat_session(
            session_id: str,
            req: ChatSessionUpdateRequest,
            _user: str = Depends(get_current_user),
        ):
            """Update a chat session (rename)."""
            session = await chat_session_manager.update(session_id, title=req.title)
            if not session:
                raise HTTPException(status_code=404, detail="Session not found")
            return session.to_dict()

        @app.delete("/api/chat/sessions/{session_id}")
        async def delete_chat_session(
            session_id: str,
            _user: str = Depends(get_current_user),
        ):
            """Archive/delete a chat session."""
            result = await chat_session_manager.delete(session_id)
            if not result:
                raise HTTPException(status_code=404, detail="Session not found")
            return {"status": "deleted"}

        @app.get("/api/chat/sessions/{session_id}/messages")
        async def get_session_messages(
            session_id: str,
            limit: int = 200,
            _user: str = Depends(get_current_user),
        ):
            """Get messages for a chat session."""
            session = await chat_session_manager.get(session_id)
            if not session:
                raise HTTPException(status_code=404, detail="Session not found")
            return await chat_session_manager.get_messages(session_id, limit=limit)

        @app.post("/api/chat/sessions/{session_id}/send")
        async def send_session_message(
            session_id: str,
            req: ChatSessionSendRequest,
            auth: AuthContext = Depends(get_auth_context),
        ):
            """Send a message in a specific chat session."""
            import time as _time
            import uuid as _uuid

            session = await chat_session_manager.get(session_id)
            if not session:
                raise HTTPException(status_code=404, detail="Session not found")

            text = req.message.strip()
            if not text:
                raise HTTPException(status_code=400, detail="Message cannot be empty.")
            if len(text) > 4000:
                raise HTTPException(status_code=400, detail="Message too long (max 4000 chars).")

            msg_id = _uuid.uuid4().hex[:12]
            user_msg = {
                "id": msg_id,
                "role": "user",
                "content": text,
                "timestamp": _time.time(),
                "sender": auth.user,
                "session_id": session_id,
            }
            await chat_session_manager.add_message(session_id, user_msg)
            await ws_manager.broadcast("chat_message", user_msg)

            # For ALL session types, route to active task if one exists
            _existing = task_queue.find_active_task(session_id=session_id)
            if _existing:
                await task_queue.route_message_to_task(
                    _existing,
                    text,
                    auth.user,
                    intervention_queues or {},
                )
                return {
                    "status": "queued",
                    "message": user_msg,
                    "task_id": _existing.id,
                    "note": "Message delivered to active task.",
                }

            # Infer task type from message
            from core.task_queue import TaskType, infer_task_type

            task_type = infer_task_type(text)

            # Detect explicit "create a project" intent from the code page and route
            # it through the project interview flow (PROJECT_SETUP task type).
            if (
                session.session_type == "code"
                and settings.project_interview_enabled
                and settings.project_interview_mode != "never"
            ):
                _project_keywords = (
                    "create a project",
                    "start a project",
                    "new project",
                    "build a project",
                    "create project",
                    "start project",
                    "i want to create a project",
                    "i want to start a project",
                    "let's create a project",
                    "let's start a project",
                    "plan a project",
                    "kickoff a project",
                    "kick off a project",
                )
                if any(kw in text.lower() for kw in _project_keywords):
                    task_type = TaskType.PROJECT_SETUP

            # For code sessions without a project, auto-create one on first message
            if session.session_type == "code" and not session.project_id and project_manager:
                _proj = await project_manager.create(
                    name=session.title or text[:60],
                    description=f"Auto-created for code session {session_id}",
                    chat_session_id=session_id,
                    status="active",
                )
                session = await chat_session_manager.update(session_id, project_id=_proj.id)
                logger.info(
                    "Auto-created project %s for code session %s on first message",
                    _proj.id,
                    session_id,
                )

            task = Task(
                title=text[:120] + ("..." if len(text) > 120 else ""),
                description=text,
                task_type=task_type,
                priority=1,
                origin_channel="dashboard_chat",
                origin_channel_id="chat",
                origin_metadata={
                    "chat_msg_id": msg_id,
                    "chat_session_id": session_id,
                },
            )
            # Link to project if session has one
            if session.project_id:
                task.project_id = session.project_id

            await task_queue.add(task)

            return {"status": "ok", "message": user_msg, "task_id": task.id}

        @app.post("/api/chat/sessions/{session_id}/setup")
        async def setup_code_session(
            session_id: str,
            req: ChatSessionSetupRequest,
            _user: str = Depends(get_current_user),
        ):
            """Configure a code session's project setup."""
            session = await chat_session_manager.get(session_id)
            if not session:
                raise HTTPException(status_code=404, detail="Session not found")
            if session.session_type != "code":
                raise HTTPException(status_code=400, detail="Only code sessions support setup")

            updates = {"deployment_target": req.mode}

            if req.mode == "local" and app_manager:
                # Create a local app via AppManager
                new_app = await app_manager.create(
                    name=req.app_name or "Untitled Project",
                    runtime=req.runtime,
                )
                updates["app_id"] = new_app.id

            if req.mode == "remote":
                # Validate SSH host
                allowed = settings.get_ssh_allowed_hosts()
                if allowed and req.ssh_host not in allowed:
                    raise HTTPException(
                        status_code=400,
                        detail=f"SSH host '{req.ssh_host}' not in allowed hosts",
                    )
                updates["ssh_host"] = req.ssh_host

            if req.mode == "github":
                # GitHub repository mode — use connected repo, create new, or clone URL
                if req.repo_id and repo_manager:
                    # Use an already-connected repo from Settings
                    existing_repo = repo_manager.get(req.repo_id)
                    if not existing_repo:
                        raise HTTPException(status_code=404, detail="Repository not found")
                    updates["repo_id"] = existing_repo.id
                    updates["github_repo"] = existing_repo.github_repo or existing_repo.name
                elif req.github_clone_url:
                    updates["github_clone_url"] = req.github_clone_url
                    updates["github_repo"] = req.github_repo_name or req.github_clone_url.rstrip(
                        "/"
                    ).split("/")[-1].removesuffix(".git")
                elif req.github_repo_name:
                    # Create a new GitHub repo if connected
                    github_token = (
                        settings.github_oauth_token
                        if hasattr(settings, "github_oauth_token")
                        else ""
                    )
                    if github_token:
                        from core.github_oauth import GitHubDeviceAuth

                        try:
                            repo_info = await GitHubDeviceAuth.create_repo(
                                token=github_token,
                                name=req.github_repo_name,
                                private=req.github_private,
                            )
                            updates["github_repo"] = repo_info["full_name"]
                            updates["github_clone_url"] = repo_info["clone_url"]
                        except Exception as exc:
                            logger.warning("GitHub repo creation failed: %s", exc)
                            updates["github_repo"] = req.github_repo_name
                    else:
                        updates["github_repo"] = req.github_repo_name
                # Create a local app to work in (only when not using a connected repo)
                if not req.repo_id and app_manager:
                    app_name = updates.get(
                        "github_repo", req.github_repo_name or "github-project"
                    ).split("/")[-1]
                    new_app = await app_manager.create(
                        name=app_name,
                        runtime=req.runtime,
                    )
                    updates["app_id"] = new_app.id

            if req.mode != "github" and req.github_repo_name:
                updates["github_repo"] = req.github_repo_name

            # Auto-create a Project for this code session so tasks get linked
            if project_manager and not session.project_id:
                proj_name = (
                    req.app_name
                    or updates.get("github_repo", "").split("/")[-1]
                    or session.title
                    or "Code Session"
                )
                new_project = await project_manager.create(
                    name=proj_name,
                    description=f"Auto-created for code session {session_id}",
                    chat_session_id=session_id,
                    app_id=updates.get("app_id", ""),
                    github_repo=updates.get("github_repo", ""),
                    status="active",
                )
                updates["project_id"] = new_project.id
                logger.info(
                    "Auto-created project %s for code session %s", new_project.id, session_id
                )

            session = await chat_session_manager.update(session_id, **updates)
            return session.to_dict()

    # -- Projects --------------------------------------------------------------

    if project_manager:

        class ProjectCreateRequest(BaseModel):
            name: str
            description: str = ""
            tags: list[str] = []
            priority: int = 0

        class ProjectUpdateRequest(BaseModel):
            name: str = ""
            description: str = ""
            tags: list[str] | None = None
            priority: int | None = None
            color: str = ""

        class ProjectStatusRequest(BaseModel):
            status: str

        class ProjectTaskCreateRequest(BaseModel):
            title: str
            description: str
            task_type: str = "coding"
            priority: int = 0

        @app.get("/api/projects")
        async def list_projects(
            include_archived: bool = False,
            _user: str = Depends(get_current_user),
        ):
            """List all projects."""
            projects = project_manager.list_projects(include_archived=include_archived)
            result = []
            for p in projects:
                d = p.to_dict()
                d["stats"] = project_manager.project_stats(p.id)
                result.append(d)
            return result

        @app.post("/api/projects")
        async def create_project(
            req: ProjectCreateRequest,
            _user: str = Depends(get_current_user),
        ):
            """Create a new project."""
            project = await project_manager.create(
                name=req.name,
                description=req.description,
                tags=req.tags,
                priority=req.priority,
            )
            d = project.to_dict()
            d["stats"] = project_manager.project_stats(project.id)
            await ws_manager.broadcast("project_update", d)
            return d

        @app.get("/api/projects/board")
        async def projects_board(_user: str = Depends(get_current_user)):
            """Get projects grouped by status for Kanban board."""
            return project_manager.board()

        @app.get("/api/projects/{project_id}")
        async def get_project(
            project_id: str,
            _user: str = Depends(get_current_user),
        ):
            """Get project details with stats."""
            project = await project_manager.get(project_id)
            if not project:
                raise HTTPException(status_code=404, detail="Project not found")
            d = project.to_dict()
            d["stats"] = project_manager.project_stats(project_id)
            return d

        @app.patch("/api/projects/{project_id}")
        async def update_project(
            project_id: str,
            req: ProjectUpdateRequest,
            _user: str = Depends(get_current_user),
        ):
            """Update project fields."""
            updates = {}
            if req.name:
                updates["name"] = req.name
            if req.description:
                updates["description"] = req.description
            if req.tags is not None:
                updates["tags"] = req.tags
            if req.priority is not None:
                updates["priority"] = req.priority
            if req.color:
                updates["color"] = req.color

            project = await project_manager.update(project_id, **updates)
            if not project:
                raise HTTPException(status_code=404, detail="Project not found")
            d = project.to_dict()
            d["stats"] = project_manager.project_stats(project_id)
            await ws_manager.broadcast("project_update", d)
            return d

        @app.patch("/api/projects/{project_id}/status")
        async def update_project_status(
            project_id: str,
            req: ProjectStatusRequest,
            _user: str = Depends(get_current_user),
        ):
            """Change project status."""
            project = await project_manager.set_status(project_id, req.status)
            if not project:
                raise HTTPException(status_code=400, detail="Invalid status or project not found")
            d = project.to_dict()
            d["stats"] = project_manager.project_stats(project_id)
            await ws_manager.broadcast("project_update", d)
            return d

        @app.delete("/api/projects/{project_id}")
        async def delete_project(
            project_id: str,
            _user: str = Depends(get_current_user),
        ):
            """Archive a project."""
            result = await project_manager.archive(project_id)
            if not result:
                raise HTTPException(status_code=404, detail="Project not found")
            return {"status": "archived"}

        @app.get("/api/projects/{project_id}/tasks")
        async def get_project_tasks(
            project_id: str,
            _user: str = Depends(get_current_user),
        ):
            """List tasks for a project."""
            project = await project_manager.get(project_id)
            if not project:
                raise HTTPException(status_code=404, detail="Project not found")
            tasks = project_manager.get_project_tasks(project_id)
            return [t.to_dict() for t in tasks]

        @app.post("/api/projects/{project_id}/tasks")
        async def create_project_task(
            project_id: str,
            req: ProjectTaskCreateRequest,
            _user: str = Depends(get_current_user),
        ):
            """Create a task linked to a project."""
            project = await project_manager.get(project_id)
            if not project:
                raise HTTPException(status_code=404, detail="Project not found")

            task = Task(
                title=req.title,
                description=req.description,
                task_type=TaskType[req.task_type.upper()]
                if req.task_type.upper() in TaskType.__members__
                else TaskType.CODING,
                priority=req.priority,
                project_id=project_id,
            )
            await task_queue.add(task)
            await ws_manager.broadcast("task_update", task.to_dict())
            return task.to_dict()

    # -- Project Memory --------------------------------------------------------

    @app.get("/api/projects/{project_id}/memory")
    async def get_project_memory(
        project_id: str,
        _user: str = Depends(get_current_user),
    ):
        """Return project memory contents for dashboard display."""
        project = await project_manager.get(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        pm = project_manager.get_project_memory(
            project_id,
            global_store=memory_store,
        )
        if not pm:
            return {"memory": "", "history": "", "project_id": project_id}

        return {
            "memory": pm.read_memory(),
            "history": pm._store.read_history(),
            "project_id": project_id,
        }

    # -- GitHub OAuth ----------------------------------------------------------

    class GitHubDeviceStartRequest(BaseModel):
        pass  # No params needed

    class GitHubPollRequest(BaseModel):
        device_code: str

    @app.get("/api/github/status")
    async def github_status(_user: str = Depends(get_current_user)):
        """Check if GitHub is configured."""
        return {
            "connected": bool(settings.github_oauth_token),
            "client_id_configured": bool(settings.github_client_id),
        }

    @app.post("/api/github/device-auth/start")
    async def github_device_start(_user: str = Depends(get_current_user)):
        """Start GitHub OAuth device flow."""
        if not settings.github_client_id:
            raise HTTPException(
                status_code=400,
                detail="GITHUB_CLIENT_ID not configured. Set it in Settings.",
            )
        from core.github_oauth import GitHubDeviceAuth

        auth = GitHubDeviceAuth(settings.github_client_id)
        try:
            result = await auth.start_device_flow()
            return result
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"GitHub API error: {e}")

    @app.post("/api/github/device-auth/poll")
    async def github_device_poll(
        req: GitHubPollRequest,
        _user: str = Depends(get_current_user),
    ):
        """Poll for GitHub OAuth token."""
        if not settings.github_client_id:
            raise HTTPException(status_code=400, detail="GITHUB_CLIENT_ID not configured.")

        from core.github_oauth import GitHubDeviceAuth

        auth = GitHubDeviceAuth(settings.github_client_id)
        try:
            token = await auth.poll_for_token(req.device_code)
            if token:
                # Save token to .env
                env_path = Path(__file__).parent.parent / ".env"
                GitHubDeviceAuth.save_token(token, env_path)
                Settings.reload_from_env()
                # Get user info
                user_info = await GitHubDeviceAuth.get_user(token)
                return {"status": "authorized", "user": user_info}
            return {"status": "pending"}
        except TimeoutError as e:
            return {"status": "expired", "error": str(e)}
        except PermissionError as e:
            return {"status": "denied", "error": str(e)}
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"GitHub API error: {e}")

    @app.post("/api/github/create-repo")
    async def github_create_repo(
        name: str,
        private: bool = True,
        description: str = "",
        _user: str = Depends(get_current_user),
    ):
        """Create a GitHub repo using the stored OAuth token."""
        if not settings.github_oauth_token:
            raise HTTPException(
                status_code=400, detail="GitHub not connected. Use device auth first."
            )

        from core.github_oauth import GitHubDeviceAuth

        try:
            result = await GitHubDeviceAuth.create_repo(
                token=settings.github_oauth_token,
                name=name,
                private=private,
                description=description,
            )
            return result
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"GitHub API error: {e}")

    # -- GitHub multi-account management ---------------------------------------

    if github_account_store:

        class GitHubAccountAddRequest(BaseModel):
            label: str = ""
            token: str

        @app.get("/api/github/accounts")
        async def list_github_accounts(_admin: AuthContext = Depends(require_admin)):
            """List all saved GitHub accounts (tokens masked)."""
            return github_account_store.list_accounts()

        @app.post("/api/github/accounts")
        async def add_github_account(
            req: GitHubAccountAddRequest,
            _admin: AuthContext = Depends(require_admin),
        ):
            """Add a GitHub account by PAT.  The username is verified via the API."""
            if not req.token.strip():
                raise HTTPException(status_code=400, detail="token is required")

            # Verify token + fetch username
            try:
                import httpx

                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(
                        "https://api.github.com/user",
                        headers={
                            "Authorization": f"Bearer {req.token.strip()}",
                            "Accept": "application/vnd.github+json",
                        },
                    )
                if resp.status_code == 200:
                    username = resp.json().get("login", "")
                elif resp.status_code == 401:
                    raise HTTPException(status_code=401, detail="Invalid GitHub token")
                else:
                    username = ""
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(status_code=502, detail=f"GitHub API error: {e}")

            label = req.label.strip() or username
            acct = github_account_store.add_account(label, req.token.strip(), username)
            # Also inject into os.environ as GITHUB_TOKEN if nothing is set there yet
            import os

            if not os.environ.get("GITHUB_TOKEN"):
                os.environ["GITHUB_TOKEN"] = req.token.strip()
            return acct

        @app.delete("/api/github/accounts/{account_id}")
        async def remove_github_account(
            account_id: str,
            _admin: AuthContext = Depends(require_admin),
        ):
            """Remove a GitHub account by id."""
            removed = github_account_store.remove_account(account_id)
            if not removed:
                raise HTTPException(status_code=404, detail="Account not found")
            return {"status": "ok"}

    # -- Repositories ----------------------------------------------------------

    if repo_manager:

        class RepoCreateRequest(BaseModel):
            name: str
            source: str = "local"  # "local" or "github"
            local_path: str = ""  # for source=local
            github_repo: str = ""  # for source=github (owner/repo)
            default_branch: str = "main"
            tags: list[str] = []
            account_id: str = ""  # optional: which GitHub account to use

        @app.get("/api/repos")
        async def list_repos(_user: str = Depends(get_current_user)):
            """List all connected repositories."""
            return [r.to_dict() for r in repo_manager.list_repos()]

        @app.post("/api/repos")
        async def create_repo(req: RepoCreateRequest, _admin: AuthContext = Depends(require_admin)):
            """Add a repository (local path or clone from GitHub)."""
            if req.source == "github":
                if not req.github_repo:
                    raise HTTPException(400, "github_repo is required for source=github")
                # Resolve which token to use: account_id > default
                account_token = ""
                if req.account_id and github_account_store:
                    account_token = github_account_store.get_token(req.account_id)
                repo = await repo_manager.add_from_github(
                    github_repo=req.github_repo,
                    default_branch=req.default_branch,
                    tags=req.tags,
                    token=account_token,
                )
            else:
                if not req.local_path:
                    raise HTTPException(400, "local_path is required for source=local")
                repo = await repo_manager.add_local(
                    name=req.name,
                    local_path=req.local_path,
                    default_branch=req.default_branch,
                    tags=req.tags,
                )
            return repo.to_dict()

        @app.get("/api/repos/{repo_id}")
        async def get_repo(repo_id: str, _user: str = Depends(get_current_user)):
            """Get a single repository by ID."""
            repo = repo_manager.get(repo_id)
            if not repo:
                raise HTTPException(404, "Repository not found")
            return repo.to_dict()

        @app.delete("/api/repos/{repo_id}")
        async def delete_repo(repo_id: str, _admin: AuthContext = Depends(require_admin)):
            """Remove a repository from the registry."""
            try:
                await repo_manager.remove(repo_id)
            except ValueError as e:
                raise HTTPException(404, str(e))
            return {"status": "removed"}

        @app.get("/api/repos/{repo_id}/branches")
        async def list_repo_branches(repo_id: str, _user: str = Depends(get_current_user)):
            """List branches for a repository."""
            branches = await repo_manager.list_branches(repo_id)
            return {"branches": branches}

        @app.post("/api/repos/{repo_id}/sync")
        async def sync_repo(repo_id: str, _user: str = Depends(get_current_user)):
            """Fetch latest changes for a repository."""
            try:
                msg = await repo_manager.sync_repo(repo_id)
            except ValueError as e:
                raise HTTPException(404, str(e))
            return {"status": "ok", "message": msg}

        @app.get("/api/github/repos")
        async def list_github_repos(
            account_id: str = "",
            _admin: AuthContext = Depends(require_admin),
        ):
            """List repos from connected GitHub accounts.

            If account_id is specified, only list repos for that account.
            Otherwise, merge repos from all accounts (default token + stored accounts).
            """
            if account_id and github_account_store:
                tok = github_account_store.get_token(account_id)
                repos = await repo_manager.list_github_repos(token=tok)
                for repo in repos:
                    repo["account_id"] = account_id
                return {"repos": repos}

            if github_account_store:
                all_tokens = github_account_store.get_all_tokens()
                if all_tokens:
                    seen: set[str] = set()
                    merged: list[dict] = []
                    for acct_id, tok in all_tokens:
                        for repo in await repo_manager.list_github_repos(token=tok):
                            key = repo.get("full_name", "")
                            if key not in seen:
                                seen.add(key)
                                repo["account_id"] = acct_id
                                merged.append(repo)
                    return {"repos": merged}

            # Fall back to default token
            repos = await repo_manager.list_github_repos()
            return {"repos": repos}

    # -- Apps Platform ---------------------------------------------------------

    if app_manager:

        class AppCreateRequest(BaseModel):
            name: str
            description: str = ""
            runtime: str = "python"
            tags: list[str] = []
            app_mode: str = ""
            git_enabled: bool | None = None

        class AppUpdateRequest(BaseModel):
            description: str = ""

        @app.get("/api/apps")
        async def list_apps(mode: str = "", _user: str = Depends(get_current_user)):
            """List all apps, optionally filtered by mode (internal/external)."""
            if mode and mode in ("internal", "external"):
                apps = app_manager.list_apps_by_mode(mode)
            else:
                apps = app_manager.list_apps()
            return [a.to_dict() for a in apps]

        @app.post("/api/apps")
        async def create_user_app(req: AppCreateRequest, _user: str = Depends(get_current_user)):
            """Create a new app and optionally trigger a build task."""
            new_app = await app_manager.create(
                name=req.name,
                description=req.description,
                runtime=req.runtime,
                tags=req.tags,
                app_mode=req.app_mode,
                git_enabled=req.git_enabled,
            )
            # Create a build task for the app
            task = Task(
                title=f"Build App: {req.name}",
                description=(
                    f"Build a complete web application:\n\n"
                    f"Name: {req.name}\n"
                    f"Description: {req.description}\n"
                    f"Runtime: {req.runtime}\n"
                    f"App ID: {new_app.id}\n"
                    f"App Path: {new_app.path}\n\n"
                    f"Use the 'app' tool to manage the app lifecycle. "
                    f"Write all source files to the app path. "
                    f"When done, mark the app as ready and start it."
                ),
                task_type=TaskType.APP_CREATE,
                priority=1,
            )
            await task_queue.add(task)
            await app_manager.mark_building(new_app.id, task.id)
            return {
                "app": new_app.to_dict(),
                "task_id": task.id,
            }

        @app.get("/api/apps/{app_id}")
        async def get_app(app_id: str, _user: str = Depends(get_current_user)):
            """Get app details."""
            found = await app_manager.get(app_id)
            if not found:
                raise HTTPException(status_code=404, detail="App not found")
            return found.to_dict()

        @app.post("/api/apps/{app_id}/start")
        async def start_app(app_id: str, _user: str = Depends(get_current_user)):
            """Start a ready/stopped app."""
            try:
                started = await app_manager.start(app_id)
                return {"status": "started", "url": started.url, "port": started.port}
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))

        @app.post("/api/apps/{app_id}/stop")
        async def stop_app(app_id: str, _user: str = Depends(get_current_user)):
            """Stop a running app."""
            try:
                await app_manager.stop(app_id)
                return {"status": "stopped"}
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))

        @app.post("/api/apps/{app_id}/restart")
        async def restart_app(app_id: str, _user: str = Depends(get_current_user)):
            """Restart an app."""
            try:
                restarted = await app_manager.restart(app_id)
                return {"status": "restarted", "url": restarted.url}
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))

        @app.delete("/api/apps/{app_id}")
        async def delete_app(app_id: str, _user: str = Depends(get_current_user)):
            """Permanently delete an app and remove its files."""
            try:
                await app_manager.delete_permanently(app_id)
                return {"status": "deleted"}
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))

        @app.get("/api/apps/{app_id}/logs")
        async def get_app_logs(
            app_id: str, lines: int = 100, _user: str = Depends(get_current_user)
        ):
            """Get app logs."""
            output = await app_manager.logs(app_id, lines=lines)
            return {"logs": output}

        @app.get("/api/apps/{app_id}/health")
        async def app_health(app_id: str, _user: str = Depends(get_current_user)):
            """Check app health."""
            return await app_manager.health_check(app_id)

        @app.post("/api/apps/{app_id}/update")
        async def update_app(
            app_id: str, req: AppUpdateRequest, _user: str = Depends(get_current_user)
        ):
            """Request changes to an existing app (triggers APP_UPDATE task)."""
            found = await app_manager.get(app_id)
            if not found:
                raise HTTPException(status_code=404, detail="App not found")

            task = Task(
                title=f"Update App: {found.name}",
                description=(
                    f"Update the existing application:\n\n"
                    f"App: {found.name} ({found.id})\n"
                    f"Path: {found.path}\n"
                    f"Runtime: {found.runtime}\n\n"
                    f"Requested changes:\n{req.description}\n\n"
                    f"Read the existing app files first. Make targeted changes. "
                    f"Restart the app when done."
                ),
                task_type=TaskType.APP_UPDATE,
                priority=1,
            )
            await task_queue.add(task)
            return {"task_id": task.id, "app_id": app_id}

        class AppSettingsRequest(BaseModel):
            app_mode: str | None = None
            require_auth: bool | None = None
            visibility: str | None = None

        @app.patch("/api/apps/{app_id}/settings")
        async def update_app_settings(
            app_id: str,
            req: AppSettingsRequest,
            _user: str = Depends(get_current_user),
        ):
            """Update app mode, auth, or visibility settings."""
            found = await app_manager.get(app_id)
            if not found:
                raise HTTPException(status_code=404, detail="App not found")
            if req.app_mode is not None:
                if req.app_mode not in ("internal", "external"):
                    raise HTTPException(status_code=400, detail="Invalid mode")
                found.app_mode = req.app_mode
            if req.require_auth is not None:
                found.require_auth = req.require_auth
            if req.visibility is not None:
                if req.visibility not in ("private", "unlisted", "public"):
                    raise HTTPException(status_code=400, detail="Invalid visibility")
                found.visibility = req.visibility
            import time as _time

            found.updated_at = _time.time()
            await app_manager._persist()
            return found.to_dict()

        # -- App reverse proxy (for running dynamic apps) ----------------------

        from starlette.responses import Response

        @app.api_route(
            "/apps/{slug}/{path:path}",
            methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
        )
        async def proxy_app_with_path(slug: str, path: str, request: Request):
            """Reverse proxy requests to running app processes."""
            return await _proxy_to_app(slug, path, request)

        @app.get("/apps/{slug}/")
        async def proxy_app_root(slug: str, request: Request):
            """Serve the root of a running app."""
            return await _proxy_to_app(slug, "", request)

        @app.get("/apps/{slug}")
        async def proxy_app_redirect(slug: str):
            """Redirect to trailing slash."""
            from starlette.responses import RedirectResponse

            return RedirectResponse(url=f"/apps/{slug}/")

        async def _proxy_to_app(slug: str, path: str, request: Request) -> Response:
            """Internal: forward request to the app's local port."""
            found = app_manager.get_by_slug(slug)
            if not found:
                raise HTTPException(status_code=404, detail=f"App '{slug}' not found")

            if found.status != "running":
                raise HTTPException(
                    status_code=503, detail=f"App '{slug}' is not running (status: {found.status})"
                )

            # Auth gate: if app requires auth, check for dashboard login
            if found.require_auth:
                from dashboard.auth import get_current_user_optional

                user = get_current_user_optional(request)
                if not user:
                    raise HTTPException(
                        status_code=401,
                        detail=f"App '{slug}' requires authentication. Log in to the dashboard first.",
                    )

            # Static apps: serve files directly
            if found.runtime == "static":
                from starlette.responses import FileResponse

                app_path = Path(found.path)
                public_dir = app_path / "public"
                if not public_dir.exists():
                    raise HTTPException(status_code=404, detail="App public directory not found")

                file_path = public_dir / path if path else public_dir / "index.html"
                if not file_path.exists():
                    file_path = public_dir / "index.html"  # SPA fallback
                if not file_path.exists():
                    raise HTTPException(status_code=404, detail="File not found")

                # Security: prevent path traversal
                try:
                    file_path.resolve().relative_to(public_dir.resolve())
                except ValueError:
                    raise HTTPException(status_code=403, detail="Access denied")

                return FileResponse(str(file_path))

            # Dynamic apps: proxy to their port
            import httpx

            target_url = f"http://127.0.0.1:{found.port}/{path}"
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    # Forward the request
                    body = await request.body()
                    headers = dict(request.headers)
                    headers.pop("host", None)

                    resp = await client.request(
                        method=request.method,
                        url=target_url,
                        headers=headers,
                        content=body,
                        params=dict(request.query_params),
                    )

                    # Filter response headers
                    resp_headers = dict(resp.headers)
                    resp_headers.pop("transfer-encoding", None)
                    resp_headers.pop("content-encoding", None)

                    return Response(
                        content=resp.content,
                        status_code=resp.status_code,
                        headers=resp_headers,
                    )
            except httpx.ConnectError:
                raise HTTPException(
                    status_code=502,
                    detail=f"App '{slug}' is not responding on port {found.port}",
                )
            except httpx.TimeoutException:
                raise HTTPException(status_code=504, detail=f"App '{slug}' timed out")

    # -- Static files (React frontend) ----------------------------------------

    if FRONTEND_DIR.exists():
        app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True))

    return app
