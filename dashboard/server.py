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

from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

from core.approval_gate import ApprovalGate
from core.config import Settings, settings
from core.device_auth import DeviceStore
from dashboard.auth import (
    API_KEY_PREFIX,
    AuthContext,
    check_rate_limit,
    create_token,
    get_current_user,
    pwd_context,
    require_admin,
    verify_password,
)
from dashboard.websocket_manager import WebSocketManager

logger = logging.getLogger("agent42.server")

# ---------------------------------------------------------------------------
# Stubs for modules removed in the v2.0 MCP pivot
# ---------------------------------------------------------------------------
# These minimal stand-ins allow the server to start and return sensible
# responses while the full v2.0 migration is completed.

import enum as _enum


class TaskStatus(_enum.Enum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    RUNNING = "running"
    REVIEW = "review"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"
    ARCHIVED = "archived"


class TaskType(_enum.Enum):
    CODING = "coding"
    CONTENT = "content"
    RESEARCH = "research"
    EMAIL = "email"
    MARKETING = "marketing"
    DEBUG = "debug"
    REVIEW = "review"
    PLANNING = "planning"
    PROJECT_SETUP = "project_setup"
    APP_CREATE = "app_create"
    APP_UPDATE = "app_update"


def infer_task_type(text: str) -> TaskType:
    """Keyword-based task type inference (stub)."""
    lower = text.lower()
    if any(k in lower for k in ("bug", "fix", "error", "debug")):
        return TaskType.DEBUG
    if any(k in lower for k in ("write", "blog", "article", "content")):
        return TaskType.CONTENT
    if any(k in lower for k in ("research", "find", "search", "look up")):
        return TaskType.RESEARCH
    return TaskType.CODING


GENERAL_ASSISTANT_PROMPT = (
    "You are Agent42, a helpful AI assistant. Answer questions accurately "
    "and honestly. If you don't know something, say so."
)


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
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "font-src 'self' https://cdn.jsdelivr.net; "
            "worker-src 'self' blob:; "
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
_INSECURE_PASSWORDS = {"", "changeme-right-now", "password", "123456", "admin"}


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


class ProfileCreateRequest(BaseModel):
    name: str
    description: str = ""
    preferred_skills: list[str] = []
    preferred_task_types: list[str] = []
    prompt_overlay: str = ""


class ProfileUpdateRequest(BaseModel):
    description: str | None = None
    preferred_skills: list[str] | None = None
    preferred_task_types: list[str] | None = None
    prompt_overlay: str | None = None


class PersonaUpdateRequest(BaseModel):
    prompt: str


class AgentRoutingRequest(BaseModel):
    primary: str | None = None
    critic: str | None = None
    fallback: str | None = None


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
    # Agent profiles
    "AGENT_DEFAULT_PROFILE",
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
_PERSONA_FILE = Path(__file__).parent.parent / "data" / "agent42_persona.json"


def _load_persona() -> str:
    """Load the custom chat persona prompt from disk.

    Returns the saved prompt string, or "" if no custom persona is set.
    """
    import json

    if _PERSONA_FILE.exists():
        try:
            data = json.loads(_PERSONA_FILE.read_text())
            return data.get("prompt", "")
        except Exception:
            pass
    return ""


def _save_persona(prompt: str) -> None:
    """Persist a custom chat persona prompt to disk."""
    import json

    _PERSONA_FILE.parent.mkdir(parents=True, exist_ok=True)
    _PERSONA_FILE.write_text(json.dumps({"prompt": prompt}, indent=2))


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


def _build_resolution_chain(store, profile: str) -> list[dict]:
    """Show where each routing field is inherited from, for dashboard display.

    Returns a list of dicts with keys: field, value, source.
    Source is one of: "profile:{name}", "_default", "FALLBACK_ROUTING".
    """
    profile_ov = store.get_overrides(profile) if profile != "_default" else None
    default_ov = store.get_overrides("_default")

    chain = []
    for field in ("primary", "critic", "fallback"):
        if profile_ov and profile_ov.get(field):
            chain.append(
                {"field": field, "value": profile_ov[field], "source": f"profile:{profile}"}
            )
        elif default_ov and default_ov.get(field):
            chain.append({"field": field, "value": default_ov[field], "source": "_default"})
        else:
            chain.append({"field": field, "value": "", "source": "removed_in_v2"})
    return chain


def create_app(
    ws_manager: WebSocketManager = None,
    approval_gate: ApprovalGate | None = None,
    tool_registry=None,
    skill_loader=None,
    channel_manager=None,
    device_store: DeviceStore | None = None,
    heartbeat=None,
    key_store=None,
    app_manager=None,
    project_manager=None,
    repo_manager=None,
    profile_loader=None,
    github_account_store=None,
    memory_store=None,
    effectiveness_store=None,
    agent_manager=None,  # passed from agent42.py after Phase 2
    reward_system=None,  # passed from agent42.py when REWARDS_ENABLED=true
    workspace_registry=None,  # passed from agent42.py for multi-project workspace
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

    # -- Global exception handler for unified error responses ----------------

    @app.exception_handler(HTTPException)
    async def unified_error_handler(request: Request, exc: HTTPException):
        """Convert HTTPException to structured {error, message, action} response."""
        detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        body = {"error": True, "message": detail, "status": exc.status_code}
        return JSONResponse(status_code=exc.status_code, content=body)

    # Shared imports used by multiple handlers within create_app scope
    import json as _json
    import time as _time_mem

    # Memory pipeline logger — records metadata only (no payload content)
    _memory_logger = logging.getLogger("memory.recall")

    # In-memory 24h stats counters — consumed by /api/memory/stats and --health
    _memory_stats = {
        "recall_count": 0,
        "learn_count": 0,
        "error_count": 0,
        "total_latency_ms": 0.0,
        "last_reset": _time_mem.time(),
    }

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
            "tasks_total": 0,
            "tasks_pending": 0,
            "tasks_running": 0,
            "websocket_connections": ws_manager.connection_count if ws_manager else 0,
        }

    # -- Platform Status -------------------------------------------------------

    @app.get("/api/status")
    async def get_status(_user: str = Depends(get_current_user)):
        """Full platform status with system metrics and dynamic capacity."""
        if heartbeat:
            health = heartbeat.get_health(
                tool_registry=tool_registry,
                skill_loader=skill_loader,
            )
            return health.to_dict()
        # Fallback when heartbeat is not available
        tools_count = 0
        skills_count = 0
        if tool_registry:
            tools_count = len(tool_registry.list_tools())
        if skill_loader:
            skills_count = len(skill_loader.all_skills())
        return {
            "active_agents": 0,
            "stalled_agents": 0,
            "tasks_pending": 0,
            "tasks_running": 0,
            "tasks_review": 0,
            "tasks_completed": 0,
            "tasks_failed": 0,
            "uptime_seconds": 0,
            "memory_mb": 0,
            "tools_registered": tools_count,
            "skills_registered": skills_count,
            "effective_max_agents": settings.max_concurrent_agents,
            "configured_max_agents": settings.max_concurrent_agents,
            "capacity_auto_mode": False,
            "capacity_reason": "default",
        }

    # -- Setup Wizard ----------------------------------------------------------

    @app.get("/api/setup/status")
    async def setup_status():
        """Check if first-run setup is needed. Unauthenticated."""
        needs_setup = not settings.dashboard_password_hash
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
            # Task queue removed in v2.0 — setup verification is manual
            logger.info(
                "Qdrant + Redis selected during setup. Verify connectivity manually: "
                "curl http://localhost:6333/healthz && redis-cli ping"
            )

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
    async def login(req: LoginRequest, request: Request, response: Response):
        # Fail-secure: reject all logins when no password is configured
        # (but allow hash-only auth when DASHBOARD_PASSWORD is empty)
        if (not settings.dashboard_password and not settings.dashboard_password_hash) or (
            settings.dashboard_password in _INSECURE_PASSWORDS
            and not settings.dashboard_password_hash
        ):
            logger.warning(
                "Login attempt with no password configured or insecure plaintext password — rejected"
            )
            raise HTTPException(
                status_code=401,
                detail="Dashboard login is disabled. Set DASHBOARD_PASSWORD or DASHBOARD_PASSWORD_HASH, or change insecure password.",
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
        token = create_token(req.username)

        # Set httpOnly cookie for XSS protection
        response.set_cookie(
            key="access_token",
            value=token,
            httponly=True,
            secure=request.url.scheme == "https",
            samesite="lax",
            max_age=86400,  # 24 hours
        )

        return {
            "status": "ok",
            "token": token,  # Keep for non-browser clients
            "message": "Login successful",
        }

    @app.post("/api/logout")
    async def logout(response: Response):
        """Logout endpoint that clears the auth cookie."""
        response.delete_cookie(key="access_token")
        return {"status": "ok", "message": "Logged out successfully"}

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

    # -- Agent Profiles (Agent Zero-inspired) ----------------------------------

    @app.get("/api/profiles")
    async def list_profiles(_user: str = Depends(get_current_user)):
        """List all available agent profiles with default profile info."""
        if not profile_loader:
            return {"profiles": [], "default_profile": ""}
        return {
            "profiles": [p.to_dict() for p in profile_loader.all_profiles()],
            "default_profile": settings.agent_default_profile,
        }

    @app.get("/api/profiles/{name}")
    async def get_profile(name: str, _user: str = Depends(get_current_user)):
        """Get a specific agent profile by name."""
        if not profile_loader:
            raise HTTPException(status_code=404, detail="Profile system not available")
        profile = profile_loader.get(name)
        if not profile:
            raise HTTPException(status_code=404, detail=f"Profile '{name}' not found")
        return {**profile.to_dict(), "prompt_overlay": profile.prompt_overlay}

    @app.post("/api/profiles", status_code=201)
    async def create_profile(req: ProfileCreateRequest, _user: str = Depends(require_admin)):
        """Create a new agent profile."""
        import re

        if not profile_loader:
            raise HTTPException(status_code=500, detail="Profile system not available")
        if not re.match(r"^[a-z0-9][a-z0-9-]*$", req.name):
            raise HTTPException(
                status_code=400,
                detail="Name must be lowercase alphanumeric with hyphens (e.g. 'my-profile')",
            )
        if profile_loader.get(req.name):
            raise HTTPException(status_code=409, detail=f"Profile '{req.name}' already exists")
        profile_loader.save_profile(
            name=req.name,
            description=req.description,
            preferred_skills=req.preferred_skills,
            preferred_task_types=req.preferred_task_types,
            prompt_overlay=req.prompt_overlay,
        )
        profile = profile_loader.get(req.name)
        return {**profile.to_dict(), "prompt_overlay": profile.prompt_overlay}

    @app.put("/api/profiles/{name}")
    async def update_profile(
        name: str, req: ProfileUpdateRequest, _user: str = Depends(require_admin)
    ):
        """Update an existing agent profile."""
        if not profile_loader:
            raise HTTPException(status_code=500, detail="Profile system not available")
        existing = profile_loader.get(name)
        if not existing:
            raise HTTPException(status_code=404, detail=f"Profile '{name}' not found")
        profile_loader.save_profile(
            name=name,
            description=req.description if req.description is not None else existing.description,
            preferred_skills=req.preferred_skills
            if req.preferred_skills is not None
            else existing.preferred_skills,
            preferred_task_types=req.preferred_task_types
            if req.preferred_task_types is not None
            else existing.preferred_task_types,
            prompt_overlay=req.prompt_overlay
            if req.prompt_overlay is not None
            else existing.prompt_overlay,
        )
        profile = profile_loader.get(name)
        return {**profile.to_dict(), "prompt_overlay": profile.prompt_overlay}

    @app.delete("/api/profiles/{name}")
    async def delete_profile_endpoint(name: str, _user: str = Depends(require_admin)):
        """Delete an agent profile."""
        if not profile_loader:
            raise HTTPException(status_code=500, detail="Profile system not available")
        if settings.agent_default_profile == name:
            raise HTTPException(status_code=400, detail="Cannot delete the current default profile")
        if not profile_loader.delete_profile(name):
            raise HTTPException(status_code=404, detail=f"Profile '{name}' not found")
        return {"status": "deleted"}

    @app.put("/api/profiles/default/{name}")
    async def set_default_profile(name: str, _user: str = Depends(require_admin)):
        """Set the default agent profile."""
        import os

        if not profile_loader:
            raise HTTPException(status_code=500, detail="Profile system not available")
        if not profile_loader.get(name):
            raise HTTPException(status_code=404, detail=f"Profile '{name}' not found")
        env_path = Path(__file__).parent.parent / ".env"
        _update_env_file(env_path, {"AGENT_DEFAULT_PROFILE": name})
        os.environ["AGENT_DEFAULT_PROFILE"] = name
        return {"status": "ok", "default_profile": name}

    # -- Agent Routing Config -------------------------------------------------

    # AgentRoutingStore removed in v2.0 — use a minimal stub
    try:
        from agents.agent_routing_store import AgentRoutingStore

        agent_routing_store = AgentRoutingStore()
    except ImportError:

        class _StubRoutingStore:
            def get_overrides(self, profile):
                return None

            def list_all(self):
                return {}

            def get_effective(self, profile, task_type):
                return {}

            def set_overrides(self, profile, overrides):
                pass

            def delete_overrides(self, profile):
                return False

        agent_routing_store = _StubRoutingStore()

    @app.get("/api/agent-routing")
    async def list_agent_routing(_user: str = Depends(get_current_user)):
        """List all agent routing overrides with effective configs."""
        store = agent_routing_store
        all_overrides = store.list_all()

        profiles = {}
        # Include all profiles that have overrides
        for name in all_overrides:
            profiles[name] = {
                "overrides": store.get_overrides(name),
                "effective": store.get_effective(name, TaskType.CODING),
            }

        # Also include profiles from profile_loader that don't have overrides
        if profile_loader:
            for p in profile_loader.all_profiles():
                if p.name not in profiles:
                    profiles[p.name] = {
                        "overrides": None,
                        "effective": store.get_effective(p.name, TaskType.CODING),
                    }

        return {"profiles": profiles}

    @app.get("/api/agent-routing/{profile}")
    async def get_agent_routing(profile: str, _user: str = Depends(get_current_user)):
        """Get routing config for a specific profile."""
        store = agent_routing_store
        overrides = store.get_overrides(profile)

        return {
            "profile": profile,
            "overrides": overrides,
            "effective": store.get_effective(profile, TaskType.CODING),
            "resolution_chain": _build_resolution_chain(store, profile),
        }

    @app.put("/api/agent-routing/{profile}")
    async def set_agent_routing(
        profile: str, req: AgentRoutingRequest, _user: str = Depends(require_admin)
    ):
        """Set routing overrides for a profile."""
        return JSONResponse(
            status_code=410,
            content={
                "error": "Feature removed in v2.0 MCP pivot",
                "status": "deprecated",
                "detail": "Model routing is no longer managed here. Use MCP tools instead.",
            },
        )

    @app.delete("/api/agent-routing/{profile}")
    async def delete_agent_routing(profile: str, _user: str = Depends(require_admin)):
        """Reset a profile's routing overrides to defaults."""
        store = agent_routing_store
        if not store.delete_overrides(profile):
            raise HTTPException(
                status_code=404, detail=f"No overrides found for profile '{profile}'"
            )
        return {"status": "deleted", "profile": profile}

    @app.get("/api/available-models")
    async def list_available_models(_user: str = Depends(get_current_user)):
        """List models available for routing config, grouped by tier."""
        return {
            "l1": [],
            "fallback": [],
            "l2": [],
            "note": "Provider registry removed in v2.0 MCP pivot",
        }

    # -- Chat Persona ---------------------------------------------------------

    @app.get("/api/persona")
    async def get_persona(_user: str = Depends(get_current_user)):
        """Get the current chat persona prompt (custom and default)."""
        return {
            "custom_prompt": _load_persona(),
            "default_prompt": GENERAL_ASSISTANT_PROMPT,
        }

    @app.put("/api/persona")
    async def update_persona(req: PersonaUpdateRequest, _user: str = Depends(require_admin)):
        """Update or reset the chat persona prompt."""
        if not req.prompt.strip():
            # Empty prompt = revert to default
            if _PERSONA_FILE.exists():
                _PERSONA_FILE.unlink()
        else:
            _save_persona(req.prompt)
        return {"status": "ok"}

    # -- Activity Feed --------------------------------------------------------

    _activity_feed: list[dict] = []
    _MAX_ACTIVITY = 500

    def _record_activity(event: str, title: str = "", task_id: str = "", extra: dict | None = None):
        """Append an event to the in-memory activity feed (capped at _MAX_ACTIVITY)."""
        import time as _t

        entry: dict = {"event": event, "title": title, "task_id": task_id, "timestamp": _t.time()}
        if extra:
            entry.update(extra)
        _activity_feed.append(entry)
        # Trim to keep memory bounded
        if len(_activity_feed) > _MAX_ACTIVITY:
            del _activity_feed[: len(_activity_feed) - _MAX_ACTIVITY]

    @app.get("/api/activity")
    async def get_activity(_user: str = Depends(get_current_user)):
        """Get recent activity feed (last 200 events)."""
        return _activity_feed[-200:]

    # -- Token Usage Stats ----------------------------------------------------

    @app.get("/api/stats/tokens")
    async def get_token_stats(_user: str = Depends(get_current_user)):
        """Get aggregate token usage across all tasks."""
        total_tokens = 0
        total_prompt = 0
        total_completion = 0
        by_model: dict = {}

        return {
            "total_tokens": total_tokens,
            "total_prompt_tokens": total_prompt,
            "total_completion_tokens": total_completion,
            "by_model": by_model,
            "daily_spend_usd": 0.0,
            "daily_tokens": 0,
        }

    # -- Reports (admin analytics) -------------------------------------------

    @app.get("/api/reports")
    async def get_reports(_: AuthContext = Depends(require_admin)):
        """Aggregate analytics data for the Reports page."""
        try:
            return await _build_reports()
        except Exception as e:
            logger.error(f"Reports endpoint error: {e}")
            return {
                "token_usage": {
                    "total_tokens": 0,
                    "total_prompt_tokens": 0,
                    "total_completion_tokens": 0,
                    "daily_tokens": 0,
                    "daily_spend_usd": 0.0,
                },
                "llm_usage": [],
                "costs": {"daily_spend_usd": 0.0, "total_estimated_usd": 0.0, "by_model": []},
                "connectivity": {"summary": {}, "models": {}},
                "model_performance": [],
                "task_breakdown": {
                    "total": 0,
                    "by_status": {},
                    "by_type": [],
                    "overall_success_rate": 0.0,
                },
                "project_breakdown": [],
                "tools": {"total": 0, "enabled": 0},
                "skills": {"total": 0, "enabled": 0, "skills": []},
            }

    async def _build_reports():
        # spending_tracker removed in v2.0 — use a minimal stub
        class _StubTracker:
            daily_spend_usd = 0.0
            daily_tokens = 0
            _model_prices = {}

            def get_flat_rate_daily(self):
                return {}

        spending_tracker = _StubTracker()

        all_tasks = []  # Task queue removed in v3.0

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
            done = td.get("done", 0) + td.get("review", 0)
            failed = td.get("failed", 0)
            completed = done + failed
            td["success_rate"] = round(done / completed, 3) if completed > 0 else 0.0
            avg_iter = td["total_iterations"] / td["total"] if td["total"] > 0 else 0
            td["avg_iterations"] = round(avg_iter, 1)
            task_types.append(td)

        # -- Model performance --
        model_perf = []

        # -- Connectivity / health --
        connectivity: dict = {"summary": {}, "models": {}}

        # -- Project breakdown --
        project_list = []
        if project_manager:
            for proj in project_manager.list_projects():
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
            skills_summary["enabled"] = sum(
                1 for s in all_skills if skill_loader.is_enabled(s.name)
            )
            skills_summary["skills"] = [
                {
                    "name": s.name,
                    "description": getattr(s, "description", ""),
                    "task_types": getattr(s, "task_types", []),
                    "enabled": skill_loader.is_enabled(s.name),
                }
                for s in all_skills
            ]

        # Total cost across all models
        total_cost = round(sum(m["estimated_cost_usd"] for m in llm_usage), 4)

        # Flat-rate provider costs (separate from per-token)
        flat_rates = spending_tracker.get_flat_rate_daily()

        # Done + review / (done + review + failed) for overall success rate
        # Tasks in "review" completed successfully and await human approval
        total_done = status_counts.get("done", 0)
        total_review = status_counts.get("review", 0)
        total_failed = status_counts.get("failed", 0)
        total_successful = total_done + total_review
        total_completed = total_successful + total_failed
        overall_success_rate = (
            round(total_successful / total_completed, 3) if total_completed > 0 else 0.0
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
                "flat_rate": flat_rates,  # flat-rate provider costs (e.g. StrongWall $16/mo)
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

    # -- Workspaces (multi-project registry) -----------------------------------

    @app.get("/api/workspaces")
    async def list_workspaces(_user: str = Depends(get_current_user)):
        if not workspace_registry:
            raise HTTPException(503, "Workspace registry not initialized")
        workspaces = workspace_registry.list_all()
        default = workspace_registry.get_default()
        return {
            "workspaces": [ws.to_dict() for ws in workspaces],
            "default_id": default.id if default else None,
        }

    @app.post("/api/workspaces", status_code=201)
    async def create_workspace(body: dict, _user: str = Depends(get_current_user)):
        if not workspace_registry:
            raise HTTPException(503, "Workspace registry not initialized")
        path = body.get("path", "")
        name = body.get("name", "")
        if not path:
            raise HTTPException(400, "path is required")
        try:
            ws = await workspace_registry.create(name=name or Path(path).name, root_path=path)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return ws.to_dict()

    @app.patch("/api/workspaces/{ws_id}")
    async def update_workspace(ws_id: str, body: dict, _user: str = Depends(get_current_user)):
        if not workspace_registry:
            raise HTTPException(503, "Workspace registry not initialized")
        ws = await workspace_registry.update(
            ws_id,
            name=body.get("name"),
            ordering=body.get("ordering"),
        )
        if not ws:
            raise HTTPException(404, "Workspace not found")
        return ws.to_dict()

    @app.delete("/api/workspaces/{ws_id}")
    async def delete_workspace(ws_id: str, _user: str = Depends(get_current_user)):
        if not workspace_registry:
            raise HTTPException(503, "Workspace registry not initialized")
        deleted = await workspace_registry.delete(ws_id)
        if not deleted:
            raise HTTPException(404, "Workspace not found")
        return {"status": "deleted", "id": ws_id}

    # -- IDE (Web IDE file operations) -----------------------------------------

    import os as _os
    import sys as _sys

    # Server-level workspace root (used by CC chat bridge, terminal, etc.)
    # This is the env-var configured workspace, separate from the multi-project registry.
    workspace = Path(_os.environ.get("AGENT42_WORKSPACE", str(Path.cwd())))

    def _resolve_workspace(workspace_id: "str | None" = None) -> Path:
        """Resolve workspace_id to a Path via registry, with env-var fallback."""
        if workspace_registry:
            ws = workspace_registry.resolve(workspace_id)
            if ws:
                return Path(ws.root_path)
            if workspace_id is not None:
                raise HTTPException(404, "Workspace not found")
            # No default in registry — fall through to env var
        return workspace

    @app.get("/api/ide/tree")
    async def ide_tree(
        path: str = "",
        workspace_id: str | None = None,
        _user: str = Depends(get_current_user),
    ):
        """List directory tree for the IDE file explorer."""
        ws_root = _resolve_workspace(workspace_id)
        target = (ws_root / path).resolve()
        if not str(target).startswith(str(ws_root.resolve())):
            raise HTTPException(403, "Path outside workspace")
        if not target.exists():
            raise HTTPException(404, f"Path not found: {path}")
        if not target.is_dir():
            raise HTTPException(400, "Not a directory")

        entries = []
        try:
            for item in sorted(target.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
                name = item.name
                if name.startswith(".") and name not in (".claude", ".env.example"):
                    continue
                if name in ("__pycache__", "node_modules", ".venv", ".git"):
                    continue
                entries.append(
                    {
                        "name": name,
                        "path": str(item.relative_to(ws_root)).replace("\\", "/"),
                        "type": "dir" if item.is_dir() else "file",
                        "size": item.stat().st_size if item.is_file() else 0,
                    }
                )
        except PermissionError:
            raise HTTPException(403, "Permission denied")
        return {"path": path, "entries": entries}

    @app.get("/api/ide/file")
    async def ide_read_file(
        path: str,
        workspace_id: str | None = None,
        _user: str = Depends(get_current_user),
    ):
        """Read file contents for the IDE editor."""
        ws_root = _resolve_workspace(workspace_id)
        target = (ws_root / path).resolve()
        if not str(target).startswith(str(ws_root.resolve())):
            raise HTTPException(403, "Path outside workspace")
        if not target.exists():
            raise HTTPException(404, f"File not found: {path}")
        if not target.is_file():
            raise HTTPException(400, "Not a file")
        if target.stat().st_size > 2_000_000:
            raise HTTPException(413, "File too large (> 2MB)")

        try:
            content = target.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            raise HTTPException(500, f"Read error: {e}")

        # Determine language from extension
        ext_map = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".jsx": "javascript",
            ".tsx": "typescript",
            ".json": "json",
            ".yaml": "yaml",
            ".yml": "yaml",
            ".md": "markdown",
            ".html": "html",
            ".css": "css",
            ".sh": "shell",
            ".bash": "shell",
            ".toml": "toml",
            ".cfg": "ini",
            ".ini": "ini",
            ".sql": "sql",
            ".xml": "xml",
            ".dockerfile": "dockerfile",
            ".rs": "rust",
            ".go": "go",
        }
        ext = target.suffix.lower()
        language = ext_map.get(ext, "plaintext")
        if target.name == "Dockerfile":
            language = "dockerfile"
        elif target.name == "Makefile":
            language = "makefile"

        return {"path": path, "content": content, "language": language}

    class IDEWriteRequest(BaseModel):
        path: str
        content: str
        workspace_id: str | None = None

    @app.post("/api/ide/file")
    async def ide_write_file(
        req: IDEWriteRequest,
        _user: str = Depends(get_current_user),
    ):
        """Write file contents from the IDE editor."""
        ws_root = _resolve_workspace(req.workspace_id)
        target = (ws_root / req.path).resolve()
        if not str(target).startswith(str(ws_root.resolve())):
            raise HTTPException(403, "Path outside workspace")
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            target.write_text(req.content, encoding="utf-8")
        except Exception as e:
            raise HTTPException(500, f"Write error: {e}")
        return {"status": "ok", "path": req.path, "size": len(req.content)}

    @app.get("/api/ide/search")
    async def ide_search(
        q: str,
        path: str = "",
        workspace_id: str | None = None,
        _user: str = Depends(get_current_user),
    ):
        """Search file contents in workspace."""
        import re

        ws_root = _resolve_workspace(workspace_id)
        target = (ws_root / path).resolve()
        if not str(target).startswith(str(ws_root.resolve())):
            raise HTTPException(403, "Path outside workspace")

        results = []
        skip_dirs = {".git", "__pycache__", "node_modules", ".venv", ".agent42"}
        try:
            pattern = re.compile(q, re.IGNORECASE)
        except re.error:
            raise HTTPException(400, f"Invalid search pattern: {q}")

        for root, dirs, files in _os.walk(target):
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            for fname in files:
                fpath = Path(root) / fname
                if fpath.stat().st_size > 500_000:
                    continue
                try:
                    text = fpath.read_text(encoding="utf-8", errors="ignore")
                    for i, line in enumerate(text.splitlines(), 1):
                        if pattern.search(line):
                            results.append(
                                {
                                    "file": str(fpath.relative_to(ws_root)).replace("\\", "/"),
                                    "line": i,
                                    "text": line.strip()[:200],
                                }
                            )
                            if len(results) >= 100:
                                return {"query": q, "results": results, "truncated": True}
                except (PermissionError, UnicodeDecodeError):
                    continue
        return {"query": q, "results": results, "truncated": False}

    # -- GSD Workstreams -------------------------------------------------------

    @app.get("/api/gsd/workstreams")
    async def gsd_workstreams(
        workspace_id: str = None,
        _user: str = Depends(get_current_user),
    ):
        """List all GSD workstreams. Uses AGENT42_WORKSPACE (project root) since GSD data is project-level."""
        import re as _re_gsd

        # GSD .planning/ is always at the project root, not per-workspace
        ws_path = workspace
        planning = Path(ws_path) / ".planning"
        ws_dir = planning / "workstreams"

        # Read active workstream
        active_ws = ""
        aw_file = planning / "active-workstream"
        if aw_file.is_file():
            active_ws = aw_file.read_text().strip()

        workstreams = []
        if ws_dir.is_dir():
            for d in sorted(ws_dir.iterdir()):
                if not d.is_dir():
                    continue
                name = d.name
                state_file = d / "STATE.md"
                roadmap_file = d / "ROADMAP.md"
                phase = ""
                status = "unknown"
                total_phases = 0
                completed_phases = 0
                if state_file.is_file():
                    content = state_file.read_text(errors="replace")
                    m = _re_gsd.search(r"^Phase:\s*(\d+)", content, _re_gsd.MULTILINE)
                    if m:
                        phase = m.group(1)
                    m2 = _re_gsd.search(r"^status:\s*(.+)", content, _re_gsd.MULTILINE)
                    if m2:
                        status = m2.group(1).strip()
                if roadmap_file.is_file():
                    rm_content = roadmap_file.read_text(errors="replace")
                    total_phases = len(
                        _re_gsd.findall(r"^- \[[ x]\] \*\*Phase", rm_content, _re_gsd.MULTILINE)
                    )
                    completed_phases = len(
                        _re_gsd.findall(r"^- \[x\] \*\*Phase", rm_content, _re_gsd.MULTILINE)
                    )

                # Display name: remove common prefixes
                display = name
                for prefix in ("agent42-", "a42-"):
                    if display.startswith(prefix):
                        display = display[len(prefix) :]
                        break

                workstreams.append(
                    {
                        "name": name,
                        "display": display,
                        "phase": phase,
                        "status": status,
                        "total_phases": total_phases,
                        "completed_phases": completed_phases,
                        "is_active": name == active_ws,
                        "is_complete": completed_phases == total_phases and total_phases > 0,
                    }
                )

        return {"workstreams": workstreams, "active": active_ws}

    @app.put("/api/gsd/workstreams/active")
    async def set_active_workstream(
        body: dict,
        _user: str = Depends(get_current_user),
    ):
        """Switch the active GSD workstream by writing to .planning/active-workstream."""
        import aiofiles as _aio_ws

        ws_name = body.get("name", "").strip()
        if not ws_name:
            raise HTTPException(400, "Workstream name required")

        planning = workspace / ".planning"
        ws_dir = planning / "workstreams" / ws_name
        if not ws_dir.is_dir():
            raise HTTPException(404, f"Workstream not found: {ws_name}")

        aw_file = planning / "active-workstream"
        async with _aio_ws.open(str(aw_file), "w") as f:
            await f.write(ws_name)

        return {"active": ws_name}

    # -- IDE Lint --------------------------------------------------------------

    @app.get("/api/ide/lint")
    async def ide_lint(
        workspace_id: str = None,
        _user: str = Depends(get_current_user),
    ):
        """Run ruff check on the workspace and return structured issues."""
        import shutil as _lint_shutil
        import subprocess as _sp

        ws_path = _resolve_workspace(workspace_id)
        ruff_bin = _lint_shutil.which("ruff")
        if not ruff_bin:
            return {"raw": "ruff not found", "issues": []}

        try:
            result = _sp.run(
                [ruff_bin, "check", "--output-format=json", str(ws_path)],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(ws_path),
            )
            raw_text = result.stdout or result.stderr or "No output"

            # Also get human-readable output
            result_text = _sp.run(
                [ruff_bin, "check", str(ws_path)],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(ws_path),
            )
            human_raw = result_text.stdout or result_text.stderr or "No output"

            # Parse JSON output into structured issues
            issues = []
            try:
                import json as _lint_json

                entries = _lint_json.loads(raw_text)
                for e in entries:
                    rel_path = e.get("filename", "")
                    # Make path relative to workspace
                    try:
                        rel_path = str(Path(rel_path).relative_to(ws_path))
                    except ValueError:
                        pass
                    issues.append(
                        {
                            "file": rel_path,
                            "line": e.get("location", {}).get("row", 0),
                            "col": e.get("location", {}).get("column", 0),
                            "code": e.get("code", ""),
                            "message": e.get("message", ""),
                            "severity": "error" if e.get("code", "").startswith("E") else "warning",
                        }
                    )
            except Exception:
                pass  # JSON parse failed — return raw only

            return {"raw": human_raw, "issues": issues}
        except Exception as ex:
            return {"raw": f"Lint error: {ex}", "issues": []}

    # -- Terminal WebSocket ----------------------------------------------------

    import asyncio as _asyncio
    import shutil as _shutil

    _terminal_sessions: dict[str, dict] = {}

    def _get_user_from_token(token: str) -> str:
        """Validate JWT token and return username."""
        from jose import jwt as _jwt

        payload = _jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        return payload.get("sub", "")

    @app.websocket("/ws/terminal")
    async def terminal_ws(websocket: WebSocket):
        """WebSocket endpoint for interactive terminal sessions.

        Uses PTY (winpty on Windows, pty on Unix) for local shells so they
        behave interactively (prompt, colors, job control).  Falls back to
        subprocess PIPE for SSH remote sessions.
        """
        # Security: all subprocess commands use fixed binaries resolved via
        # shutil.which — no user-supplied strings are interpolated into commands.
        await websocket.accept()

        token = websocket.query_params.get("token", "")
        if not token:
            await websocket.close(code=4001, reason="Missing token")
            return
        try:
            _get_user_from_token(token)
        except Exception:
            await websocket.close(code=4001, reason="Invalid token")
            return

        node = websocket.query_params.get("node", "local")
        cmd = websocket.query_params.get("cmd", "shell")
        ws_workspace_id = websocket.query_params.get("workspace_id")
        workspace_path = _resolve_workspace(ws_workspace_id)
        shell = _shutil.which("bash") or _shutil.which("sh") or _shutil.which("cmd")
        if not shell:
            await websocket.send_text("\r\nNo shell found\r\n")
            await websocket.close()
            return

        claude_bin = _shutil.which("claude")
        import json as _json

        # --- Remote sessions use subprocess (SSH needs PIPE, not local PTY) ---
        if node == "remote":
            ssh_host = _os.environ.get("AGENT42_REMOTE_HOST", "")
            if not ssh_host:
                await websocket.send_text(
                    "\r\n\x1b[31mNo remote node configured (AGENT42_REMOTE_HOST not set)\x1b[0m\r\n"
                )
                await websocket.close()
                return
            ssh_args = ["ssh", "-tt", ssh_host]
            if cmd == "claude":
                ssh_args.append("claude")
            try:
                proc = await _asyncio.create_subprocess_exec(
                    *ssh_args,
                    stdin=_asyncio.subprocess.PIPE,
                    stdout=_asyncio.subprocess.PIPE,
                    stderr=_asyncio.subprocess.STDOUT,
                )
            except Exception as e:
                await websocket.send_text(f"\r\nFailed to start SSH: {e}\r\n")
                await websocket.close()
                return

            async def _read_remote():
                try:
                    while True:
                        data = await proc.stdout.read(4096)
                        if not data:
                            break
                        await websocket.send_text(data.decode("utf-8", errors="replace"))
                except Exception:
                    pass

            read_task = _asyncio.create_task(_read_remote())
            try:
                while True:
                    msg = await websocket.receive_text()
                    try:
                        parsed = _json.loads(msg)
                        if isinstance(parsed, dict) and parsed.get("type") == "resize":
                            continue
                    except (_json.JSONDecodeError, ValueError, TypeError):
                        pass
                    if proc.stdin and not proc.stdin.is_closing():
                        proc.stdin.write(msg.encode("utf-8"))
                        await proc.stdin.drain()
            except Exception:
                pass
            finally:
                read_task.cancel()
                if proc.returncode is None:
                    proc.terminate()
            return

        # --- Local sessions: determine command ---
        if cmd == "claude":
            if not claude_bin:
                await websocket.send_text(
                    "\r\nClaude Code CLI not found.\r\n"
                    "Install: npm install -g @anthropic-ai/claude-code\r\n"
                )
                await websocket.close()
                return
            pty_cmd = claude_bin
        else:
            pty_cmd = shell

        # --- Try PTY for interactive local shell ---
        pty_process = None
        use_pty = False
        try:
            if _sys.platform == "win32":
                # Windows paths with spaces (C:\Program Files\...) break PtyProcess.spawn.
                # Convert to 8.3 short path to avoid the issue entirely.
                import ctypes

                from winpty import PtyProcess

                buf = ctypes.create_unicode_buffer(260)
                if ctypes.windll.kernel32.GetShortPathNameW(pty_cmd, buf, 260):
                    pty_cmd = buf.value
                pty_process = PtyProcess.spawn(pty_cmd, cwd=str(workspace_path))
                use_pty = True
            else:
                import pty as _pty_mod
                import subprocess as _subprocess_pty

                master_fd, slave_fd = _pty_mod.openpty()
                proc = _subprocess_pty.Popen(
                    [pty_cmd],
                    stdin=slave_fd,
                    stdout=slave_fd,
                    stderr=slave_fd,
                    cwd=str(workspace_path),
                    preexec_fn=_os.setsid,
                )
                _os.close(slave_fd)
                use_pty = True
        except Exception as e:
            logger.warning(f"PTY unavailable, falling back to PIPE: {e}")
            use_pty = False

        if use_pty and _sys.platform == "win32" and pty_process:
            loop = _asyncio.get_event_loop()

            async def _read_pty_win():
                try:
                    while pty_process.isalive():
                        try:
                            data = await loop.run_in_executor(None, lambda: pty_process.read(4096))
                            if data:
                                await websocket.send_text(data)
                        except EOFError:
                            break
                        except Exception:
                            break
                except Exception:
                    pass

            read_task = _asyncio.create_task(_read_pty_win())
            try:
                while True:
                    msg = await websocket.receive_text()
                    try:
                        parsed = _json.loads(msg)
                        if isinstance(parsed, dict) and parsed.get("type") == "resize":
                            cols = int(parsed.get("cols", 80))
                            rows = int(parsed.get("rows", 24))
                            try:
                                pty_process.setwinsize(rows, cols)
                            except Exception:
                                pass
                            continue
                    except (_json.JSONDecodeError, ValueError, TypeError):
                        pass
                    try:
                        pty_process.write(msg)
                    except Exception:
                        break
            except Exception:
                pass
            finally:
                read_task.cancel()
                if pty_process.isalive():
                    pty_process.terminate()

        elif use_pty and _sys.platform != "win32":
            import select as _select

            loop = _asyncio.get_event_loop()

            def _read_master():
                if _select.select([master_fd], [], [], 0.1)[0]:
                    return _os.read(master_fd, 4096)
                return b""

            async def _read_pty_unix():
                try:
                    while proc.poll() is None:
                        data = await loop.run_in_executor(None, _read_master)
                        if data:
                            await websocket.send_text(data.decode("utf-8", errors="replace"))
                        else:
                            await _asyncio.sleep(0.05)
                except Exception:
                    pass

            read_task = _asyncio.create_task(_read_pty_unix())
            try:
                while True:
                    msg = await websocket.receive_text()
                    try:
                        parsed = _json.loads(msg)
                        if isinstance(parsed, dict) and parsed.get("type") == "resize":
                            import fcntl
                            import struct
                            import termios

                            cols = int(parsed.get("cols", 80))
                            rows = int(parsed.get("rows", 24))
                            winsize = struct.pack("HHHH", rows, cols, 0, 0)
                            fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsize)
                            continue
                    except (_json.JSONDecodeError, ValueError, TypeError):
                        pass
                    _os.write(master_fd, msg.encode("utf-8"))
            except Exception:
                pass
            finally:
                read_task.cancel()
                _os.close(master_fd)
                if proc.poll() is None:
                    proc.terminate()

        else:
            # Fallback: subprocess PIPE (no interactive prompt)
            try:
                proc = await _asyncio.create_subprocess_exec(
                    pty_cmd,
                    stdin=_asyncio.subprocess.PIPE,
                    stdout=_asyncio.subprocess.PIPE,
                    stderr=_asyncio.subprocess.STDOUT,
                    cwd=str(workspace_path),
                )
            except Exception as e:
                await websocket.send_text(f"\r\nFailed to start shell: {e}\r\n")
                await websocket.close()
                return

            async def _read_fallback():
                try:
                    while True:
                        data = await proc.stdout.read(4096)
                        if not data:
                            break
                        await websocket.send_text(data.decode("utf-8", errors="replace"))
                except Exception:
                    pass

            read_task = _asyncio.create_task(_read_fallback())
            try:
                while True:
                    msg = await websocket.receive_text()
                    try:
                        parsed = _json.loads(msg)
                        if isinstance(parsed, dict) and parsed.get("type") == "resize":
                            continue
                    except (_json.JSONDecodeError, ValueError, TypeError):
                        pass
                    if proc.stdin and not proc.stdin.is_closing():
                        proc.stdin.write(msg.encode("utf-8"))
                        await proc.stdin.drain()
            except Exception:
                pass
            finally:
                read_task.cancel()
                if proc.returncode is None:
                    proc.terminate()

    # -- Claude Code Chat WebSocket Bridge -------------------------------------

    from pathlib import Path as _pathlib_Path

    import aiofiles as _aiofiles

    _CC_SESSIONS_DIR = workspace / ".agent42" / "cc-sessions"
    _CC_SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

    import re as _re_cc

    _ANSI_ESCAPE = _re_cc.compile(r"\x1b\[[0-9;]*[mGKHF]")

    # PTY-03: Pre-warmed CC session pool (one warm process per user)
    import time as _time_cc

    _cc_warm_pool: dict = {}
    # Each entry: {
    #   "cc_session_id": str | None,  # From result event of sentinel run
    #   "ready": bool,                # True after sentinel run completes
    #   "spawned_at": float,          # time.monotonic()
    #   "last_used": float,           # time.monotonic() -- for idle timeout
    # }
    # Idle timeout: 300 seconds (5 * 60 = 300)
    _CC_WARM_IDLE_TIMEOUT = 300

    async def _cc_spawn_warm(user: str, workspace_path) -> None:
        """Spawn a CC process with sentinel '.' message to pre-initialize MCP servers.

        On success, stores {cc_session_id, ready: True, spawned_at, last_used} in
        _cc_warm_pool[user]. The warm process exits after the sentinel run; the
        resulting session_id is used with --resume for the user's first real message.
        """
        claude_bin = _shutil.which("claude")
        if not claude_bin:
            logger.warning("CC warm spawn skipped: claude binary not found")
            return

        warm_args = [
            claude_bin,
            "-p",
            ".",
            "--output-format",
            "stream-json",
            "--verbose",
        ]
        warm_session_id = None
        now = _time_cc.monotonic()

        try:
            if _sys.platform == "win32":
                try:
                    from winpty import PtyProcess as _WarmPtyProcess

                    warm_pty = _WarmPtyProcess.spawn(
                        warm_args,
                        cwd=str(workspace_path),
                        dimensions=(24, 220),
                    )
                    loop = _asyncio.get_event_loop()
                    while warm_pty.isalive():
                        try:
                            raw_line = await loop.run_in_executor(None, warm_pty.readline)
                            line = _ANSI_ESCAPE.sub("", raw_line).strip()
                            if not line:
                                continue
                            try:
                                ev = _json.loads(line)
                            except _json.JSONDecodeError:
                                continue
                            if ev.get("type") == "result":
                                warm_session_id = ev.get("session_id")
                                break
                        except EOFError:
                            break
                        except Exception as e:
                            logger.warning(f"CC warm spawn (win PTY) read error: {e}")
                            break
                    if warm_pty.isalive():
                        warm_pty.terminate()
                except Exception as win_err:
                    logger.warning(f"CC warm spawn (win PTY) failed: {win_err}")
                    warm_session_id = None
            else:
                try:
                    import pty as _warm_pty_mod
                    import select as _warm_select
                    import subprocess as _warm_subprocess

                    w_master_fd, w_slave_fd = _warm_pty_mod.openpty()
                    warm_proc = _warm_subprocess.Popen(
                        warm_args,
                        stdin=w_slave_fd,
                        stdout=w_slave_fd,
                        stderr=w_slave_fd,
                        cwd=str(workspace_path),
                        preexec_fn=_os.setsid,
                    )
                    _os.close(w_slave_fd)
                    loop = _asyncio.get_event_loop()
                    w_line_buf = ""

                    def _warm_read_chunk():
                        if _warm_select.select([w_master_fd], [], [], 0.1)[0]:
                            try:
                                return _os.read(w_master_fd, 4096).decode("utf-8", errors="replace")
                            except OSError:
                                return None
                        return ""

                    while warm_proc.poll() is None:
                        chunk = await loop.run_in_executor(None, _warm_read_chunk)
                        if chunk is None:
                            break
                        if not chunk:
                            await _asyncio.sleep(0.05)
                            continue
                        w_line_buf += chunk
                        found_result = False
                        while "\n" in w_line_buf:
                            raw_line, w_line_buf = w_line_buf.split("\n", 1)
                            line = _ANSI_ESCAPE.sub("", raw_line).strip()
                            if not line:
                                continue
                            try:
                                ev = _json.loads(line)
                            except _json.JSONDecodeError:
                                continue
                            if ev.get("type") == "result":
                                warm_session_id = ev.get("session_id")
                                found_result = True
                                break
                        if found_result:
                            break
                    try:
                        _os.close(w_master_fd)
                    except OSError:
                        pass
                    if warm_proc.poll() is None:
                        warm_proc.terminate()
                except Exception as unix_err:
                    logger.warning(f"CC warm spawn (unix PTY) failed: {unix_err}")
                    warm_session_id = None

            if warm_session_id is None:
                # PIPE fallback for warm spawn
                try:
                    warm_proc_pipe = await _asyncio.create_subprocess_exec(
                        *warm_args,
                        stdout=_asyncio.subprocess.PIPE,
                        stderr=_asyncio.subprocess.PIPE,
                        cwd=str(workspace_path),
                    )
                    async for raw_line in warm_proc_pipe.stdout:
                        line = raw_line.decode("utf-8", errors="replace").strip()
                        if not line:
                            continue
                        try:
                            ev = _json.loads(line)
                        except _json.JSONDecodeError:
                            continue
                        if ev.get("type") == "result":
                            warm_session_id = ev.get("session_id")
                            break
                    if warm_proc_pipe.returncode is None:
                        warm_proc_pipe.terminate()
                except Exception as pipe_err:
                    logger.warning(f"CC warm spawn (PIPE fallback) failed: {pipe_err}")

        except Exception as outer_err:
            logger.warning(f"CC warm spawn failed: {outer_err}")
            return

        if warm_session_id:
            _cc_warm_pool[user] = {
                "cc_session_id": warm_session_id,
                "ready": True,
                "spawned_at": now,
                "last_used": now,
            }
            logger.info(f"CC warm session {warm_session_id} ready for {user}")
        else:
            logger.warning(f"CC warm spawn completed but no session_id obtained for {user}")

    async def _cc_prewarm_idle_task():
        """Background task: remove warm pool entries older than 5 minutes (300s)."""
        while True:
            await _asyncio.sleep(60)  # Check every 60 seconds
            now = _time_cc.monotonic()
            expired = [
                user
                for user, entry in _cc_warm_pool.items()
                if now - entry["last_used"] > _CC_WARM_IDLE_TIMEOUT
            ]
            for user in expired:
                del _cc_warm_pool[user]
                logger.info(f"CC warm session expired for {user}")

    @app.on_event("startup")
    async def _start_warm_pool_cleanup():
        _asyncio.create_task(_cc_prewarm_idle_task())

    @app.on_event("startup")
    async def _load_app_manager():
        if app_manager:
            await app_manager.load()

    # Constant: MCP tool name CC uses when requesting user permission
    _CC_PERMISSION_TOOL = "mcp__agent42__cc_permission"
    # Built-in CC tool that blocks waiting for human input
    _CC_ASK_QUESTION_TOOL = "AskUserQuestion"

    def _read_gsd_workstream(root_path) -> dict:
        """Read current GSD workstream name and phase from .planning/ directory."""
        import re as _re_ws

        result: dict = {"workstream": "", "phase": ""}
        try:
            aw_path = Path(root_path) / ".planning" / "active-workstream"
            if aw_path.is_file():
                ws_name = aw_path.read_text().strip()
                if ws_name:
                    display = ws_name
                    for prefix in ("agent42-", "a42-"):
                        if display.startswith(prefix):
                            display = display[len(prefix) :]
                            break
                    result["workstream"] = display
                    state_path = (
                        Path(root_path) / ".planning" / "workstreams" / ws_name / "STATE.md"
                    )
                    if state_path.is_file():
                        content = state_path.read_text()
                        m = _re_ws.search(r"^Phase:\s*(\d+)", content, _re_ws.MULTILINE)
                        if m:
                            result["phase"] = m.group(1)
        except Exception:
            pass
        return result

    def _parse_cc_event(event: dict, tool_id_map: dict, session_state: dict) -> list:
        """Translate one CC NDJSON event into WS envelope dicts.

        Returns [] for events with no WS output (system/init, message_start, etc.).
        Mutates tool_id_map and session_state["cc_session_id"] on result event.
        """
        etype = event.get("type")
        envelopes = []
        logger.info(f"CC event: type={etype}, subtype={event.get('subtype', '-')}")
        if etype == "system":
            subtype = event.get("subtype", "")
            if subtype == "init":
                # UX-01: Collapse per-server messages into a single init_progress chip
                mcp_names = []
                for srv in event.get("mcp_servers", []):
                    srv_name = (srv.get("name", "") if isinstance(srv, dict) else str(srv)).strip()
                    if srv_name:
                        mcp_names.append(srv_name)
                envelopes.append(
                    {
                        "type": "init_progress",
                        "data": {
                            "message": "Initializing Claude Code...",
                            "servers": mcp_names,
                            "phase": "ready",
                        },
                    }
                )
            elif subtype == "hook_started":
                # UX-01: Show hook loading as init_progress (not status)
                hook_name = event.get("hook_name") or event.get("name") or ""
                if hook_name:
                    envelopes.append(
                        {
                            "type": "init_progress",
                            "data": {
                                "message": f"Loading {hook_name}...",
                                "phase": "loading",
                            },
                        }
                    )
            elif subtype == "hook_response":
                # MEM-01/MEM-02: Parse memory hook responses, suppress all others
                hook_name = event.get("hook_name") or event.get("name") or ""
                hook_output = event.get("output", "")
                if "memory-recall" in hook_name.lower():
                    import re as _re_mod

                    count_match = _re_mod.search(r"Recall:\s*(\d+)\s*memories", hook_output)
                    count = int(count_match.group(1)) if count_match else 0
                    if count > 0:
                        envelopes.append(
                            {
                                "type": "memory_loaded",
                                "data": {"count": count, "message": f"Loaded {count} memories"},
                            }
                        )
                elif "memory-learn" in hook_name.lower() or "learning-engine" in hook_name.lower():
                    if "captured" in hook_output.lower() or "Learn:" in hook_output:
                        envelopes.append(
                            {
                                "type": "memory_saved",
                                "data": {"message": "Memory saved"},
                            }
                        )
                # All other hook_response subtypes remain suppressed (too verbose)
        elif etype == "stream_event":
            raw = event.get("event", {})
            raw_type = raw.get("type", "")
            index = raw.get("index")
            if raw_type == "content_block_start":
                cb = raw.get("content_block", {})
                if cb.get("type") == "tool_use":
                    tool_name = cb.get("name", "")
                    tool_id = cb.get("id", "")
                    is_perm = tool_name == _CC_PERMISSION_TOOL
                    is_ask = tool_name == _CC_ASK_QUESTION_TOOL
                    tool_id_map[index] = {
                        "id": tool_id,
                        "name": tool_name,
                        "input_buf": "",
                        "is_permission": is_perm,
                        "is_ask_question": is_ask,
                    }
                    if not is_perm and not is_ask:
                        envelopes.append(
                            {
                                "type": "tool_start",
                                "data": {"id": tool_id, "name": tool_name, "input": {}},
                            }
                        )
                    # Permission/AskUserQuestion: no envelope yet — wait for input_json_delta + content_block_stop
                elif cb.get("type") == "tool_result":
                    # TOOL-03: Relay tool output to frontend so tool cards can show result content
                    envelopes.append(
                        {
                            "type": "tool_output",
                            "data": {
                                "id": cb.get("tool_use_id", ""),
                                "content": cb.get("content", ""),
                                "content_type": "text",
                            },
                        }
                    )
            elif raw_type == "content_block_delta":
                delta = raw.get("delta", {})
                if delta.get("type") == "text_delta":
                    envelopes.append(
                        {
                            "type": "text_delta",
                            "data": {"text": delta.get("text", "")},
                        }
                    )
                    session_state["has_streamed_text"] = True
                elif delta.get("type") == "input_json_delta":
                    partial = delta.get("partial_json", "")
                    if index in tool_id_map:
                        tool_id_map[index]["input_buf"] = (
                            tool_id_map[index].get("input_buf", "") + partial
                        )
                        if not tool_id_map[index].get("is_permission") and not tool_id_map[
                            index
                        ].get("is_ask_question"):
                            envelopes.append(
                                {
                                    "type": "tool_delta",
                                    "data": {
                                        "id": tool_id_map[index]["id"],
                                        "partial": partial,
                                    },
                                }
                            )
                    # Permission/AskUserQuestion tool deltas: silently buffered, not forwarded to frontend
            elif raw_type == "content_block_stop":
                if index in tool_id_map:
                    t = tool_id_map.pop(index)
                    if t.get("is_permission"):
                        # Parse accumulated input — now has the full tool input JSON
                        perm_input = {}
                        try:
                            import json as _json_mod

                            perm_input = _json_mod.loads(t.get("input_buf", "{}") or "{}")
                        except Exception:
                            pass
                        envelopes.append(
                            {
                                "type": "permission_request",
                                "data": {
                                    "id": t["id"],
                                    "name": t["name"],
                                    "input": perm_input,
                                },
                            }
                        )
                    elif t.get("is_ask_question"):
                        # AskUserQuestion: parse question text and emit interactive prompt
                        ask_input = {}
                        try:
                            import json as _json_mod2

                            ask_input = _json_mod2.loads(t.get("input_buf", "{}") or "{}")
                        except Exception:
                            pass
                        raw_question = (
                            ask_input.get("question")
                            or ask_input.get("prompt")
                            or ask_input.get("text")
                            or ""
                        )
                        # Try to parse structured {questions:[...]} payload (GSD discuss-phase).
                        # The question param may be valid JSON or Python-repr dict (single quotes,
                        # capitalised booleans). Convert Python-repr to JSON before parsing.
                        import json as _json_aq
                        import re as _re_aq

                        def _py_repr_to_json_aq(s):
                            s = _re_aq.sub(r"\bTrue\b", "true", s)
                            s = _re_aq.sub(r"\bFalse\b", "false", s)
                            s = _re_aq.sub(r"\bNone\b", "null", s)
                            s = _re_aq.sub(r"'([^']*)'", r'"\1"', s)
                            return s

                        structured = None
                        for _s in (raw_question, _py_repr_to_json_aq(raw_question)):
                            try:
                                _obj = _json_aq.loads(_s)
                                if isinstance(_obj, dict) and "questions" in _obj:
                                    structured = _obj
                                    break
                            except Exception:
                                pass

                        if structured is not None:
                            envelopes.append(
                                {
                                    "type": "ask_question",
                                    "data": {
                                        "id": t["id"],
                                        "format": "structured",
                                        "questions": structured.get("questions", []),
                                    },
                                }
                            )
                        else:
                            envelopes.append(
                                {
                                    "type": "ask_question",
                                    "data": {
                                        "id": t["id"],
                                        "format": "text",
                                        "question": raw_question,
                                    },
                                }
                            )
                    else:
                        envelopes.append(
                            {
                                "type": "tool_complete",
                                "data": {
                                    "id": t.get("id"),
                                    "name": t.get("name"),
                                    "output": "",
                                    "is_error": False,
                                },
                            }
                        )
        elif etype == "assistant":
            # UX-03: Dedup guard — only use assistant event as fallback when stream_event
            # text_deltas were NOT already emitted (pipe-buffered mode). When PTY streaming
            # works, stream_event text_deltas arrive first and set has_streamed_text=True,
            # so we skip this to prevent the same text appearing twice.
            if not session_state.get("has_streamed_text"):
                msg = event.get("message", {})
                for block in msg.get("content", []):
                    if block.get("type") == "text":
                        text = block.get("text", "")
                        if text:
                            envelopes.append({"type": "text_delta", "data": {"text": text}})
        elif etype == "result":
            cc_sid = event.get("session_id")
            session_state["cc_session_id"] = cc_sid
            session_state["has_streamed_text"] = False  # UX-03: reset per-turn flag
            usage = event.get("usage", {})
            envelopes.append(
                {
                    "type": "turn_complete",
                    "data": {
                        "session_id": cc_sid,
                        "cost_usd": event.get("cost_usd", event.get("total_cost_usd")),
                        "input_tokens": usage.get("input_tokens", 0),
                        "output_tokens": usage.get("output_tokens", 0),
                    },
                }
            )
        return envelopes

    async def _save_session(ws_session_id: str, data: dict, sessions_dir=None) -> None:
        """Write session data to .agent42/cc-sessions/{ws_session_id}.json."""
        d = _pathlib_Path(sessions_dir) if sessions_dir is not None else _CC_SESSIONS_DIR
        async with _aiofiles.open(d / f"{ws_session_id}.json", "w") as fh:
            await fh.write(_json.dumps(data, indent=2))

    async def _load_session(ws_session_id: str, sessions_dir=None) -> dict:
        """Read session data; returns {} if file missing or corrupt."""
        d = _pathlib_Path(sessions_dir) if sessions_dir is not None else _CC_SESSIONS_DIR
        path = d / f"{ws_session_id}.json"
        if not path.exists():
            return {}
        try:
            async with _aiofiles.open(path) as fh:
                return _json.loads(await fh.read())
        except Exception:
            return {}

    @app.websocket("/ws/cc-chat")
    async def cc_chat_ws(websocket: WebSocket):
        """CC Chat WebSocket: per-turn spawn, NDJSON relay, multi-turn via --resume.

        Security: subprocess args is a Python list (no shell interpolation). user_message
        is a single positional CC argument passed directly.
        """
        import datetime as _datetime
        import uuid as _uuid

        await websocket.accept()
        token = websocket.query_params.get("token", "")
        if not token:
            await websocket.close(code=4001, reason="Missing token")
            return
        try:
            _cc_user = _get_user_from_token(token)
        except Exception:
            await websocket.close(code=4001, reason="Invalid token")
            return

        ws_session_id = websocket.query_params.get("session_id") or str(_uuid.uuid4())
        ws_workspace_id = websocket.query_params.get("workspace_id")
        workspace_path = _resolve_workspace(ws_workspace_id)
        lightweight = websocket.query_params.get("lightweight", "").lower() in ("true", "1")
        session_data = await _load_session(ws_session_id)
        session_state: dict = {"cc_session_id": session_data.get("cc_session_id")}
        session_title: str = session_data.get("title", "")
        created_at: str = session_data.get("created_at", _datetime.datetime.utcnow().isoformat())
        session_state["permission_events"] = {}  # tool_id -> asyncio.Event
        session_state["permission_results"] = {}  # tool_id -> bool
        session_state["question_pending"] = {}  # tool_id -> True (awaiting stdin response)
        session_state["trust_mode"] = False
        session_state["message_count"] = session_data.get("message_count", 0)
        session_state["last_assistant_text"] = ""
        session_state["has_streamed_text"] = False

        # GSD: Read workstream for this session (from saved data or current file)
        _gsd_info = _read_gsd_workstream(workspace_path)
        session_state["gsd_workstream"] = session_data.get("gsd_workstream") or _gsd_info.get(
            "workstream", ""
        )
        session_state["gsd_phase"] = session_data.get("gsd_phase") or _gsd_info.get("phase", "")

        # PTY-03: Check for ?warm=true and spawn warm process in background
        warm_requested = websocket.query_params.get("warm", "").lower() in ("true", "1", "yes")
        if warm_requested and _cc_user not in _cc_warm_pool:
            _asyncio.create_task(_cc_spawn_warm(_cc_user, workspace))

        try:
            # Send initial workstream to frontend
            await websocket.send_json(
                {
                    "type": "workstream_update",
                    "data": {
                        "workstream": session_state["gsd_workstream"],
                        "phase": session_state["gsd_phase"],
                    },
                }
            )
            while True:
                raw_msg = await websocket.receive_text()
                try:
                    msg_data = _json.loads(raw_msg)
                    user_message = msg_data.get("message", raw_msg)
                except (_json.JSONDecodeError, AttributeError):
                    user_message = raw_msg

                if not user_message.strip():
                    continue
                if not session_title:
                    session_title = user_message[:80]
                session_state["message_count"] = session_state.get("message_count", 0) + 1

                claude_bin = _shutil.which("claude")
                if not claude_bin:
                    # BRIDGE-05: CLI not installed -- notify and emit fallback response
                    await websocket.send_json(
                        {
                            "type": "status",
                            "data": {
                                "message": "CC subscription not available \u2014 using API mode"
                            },
                        }
                    )
                    await websocket.send_json(
                        {
                            "type": "text_delta",
                            "data": {
                                "text": "Claude Code CLI not installed. Run: npm install -g @anthropic-ai/claude-code"
                            },
                        }
                    )
                    await websocket.send_json(
                        {
                            "type": "turn_complete",
                            "data": {
                                "session_id": session_state.get("cc_session_id"),
                                "cost_usd": None,
                                "input_tokens": 0,
                                "output_tokens": 0,
                            },
                        }
                    )
                    continue

                # PTY-03: Check warm pool for pre-initialized session (first message only)
                warm_entry = _cc_warm_pool.pop(_cc_user, None)
                if warm_entry and warm_entry.get("ready") and warm_entry.get("cc_session_id"):
                    if not session_state.get("cc_session_id"):
                        session_state["cc_session_id"] = warm_entry["cc_session_id"]
                        logger.info(
                            f"CC using warm session {warm_entry['cc_session_id']} for {_cc_user}"
                        )
                        await websocket.send_json(
                            {
                                "type": "status",
                                "data": {"message": "Using pre-warmed session"},
                            }
                        )

                # Build subprocess args as a Python list (prevents shell injection)
                args = [
                    claude_bin,
                    "-p",
                    user_message,
                    "--output-format",
                    "stream-json",
                    "--verbose",
                    "--include-partial-messages",
                ]
                # Note: --permission-prompt-tool-name removed — not supported in CC CLI v2.x.
                # Permission prompts are handled via the standard stream-json events.
                cc_session_id = session_state.get("cc_session_id")
                if cc_session_id:
                    args += ["--resume", cc_session_id]

                # Lightweight mode: skip MCP servers for fast chat (~8s vs 30s+)
                if lightweight:
                    _empty_mcp = workspace / ".agent42" / "empty-mcp.json"
                    if not _empty_mcp.exists():
                        _empty_mcp.parent.mkdir(parents=True, exist_ok=True)
                        _empty_mcp.write_text('{"mcpServers":{}}')
                    args += ["--mcp-config", str(_empty_mcp), "--strict-mcp-config"]

                # --- PTY spawn (PTY-01) with PIPE fallback (PTY-04) ---
                use_cc_pty = False
                cc_pty_process = None  # winpty PtyProcess
                cc_proc = None  # asyncio subprocess (PIPE fallback) or Popen (Unix PTY)
                cc_master_fd = None  # Unix PTY master fd

                try:
                    if _sys.platform == "win32":
                        # Skip winpty on Windows — PIPE mode is more reliable for
                        # NDJSON relay (winpty readline can hang on slow startup).
                        pass
                    else:
                        import pty as _cc_pty_mod
                        import subprocess as _cc_subprocess_pty

                        cc_master_fd, _cc_slave_fd = _cc_pty_mod.openpty()
                        cc_proc = _cc_subprocess_pty.Popen(
                            args,
                            stdin=_cc_slave_fd,
                            stdout=_cc_slave_fd,
                            stderr=_cc_slave_fd,
                            cwd=str(workspace_path),
                            preexec_fn=_os.setsid,
                        )
                        _os.close(_cc_slave_fd)
                        use_cc_pty = True
                except Exception as pty_err:
                    logger.warning(f"CC PTY unavailable, falling back to PIPE: {pty_err}")
                    use_cc_pty = False

                if not use_cc_pty:
                    try:
                        logger.info(
                            "CC PIPE: spawning subprocess with %d args, cwd=%s",
                            len(args),
                            workspace_path,
                        )
                        # Use home dir as cwd to avoid loading project-level
                        # .claude/ configs with platform-specific paths (e.g. Windows
                        # MCP paths on a Linux VPS). The workspace is still accessible
                        # to CC via --add-dir if needed.
                        _cc_cwd = (
                            str(Path.home()) if _sys.platform != "win32" else str(workspace_path)
                        )
                        cc_proc = await _asyncio.create_subprocess_exec(
                            *args,
                            stdout=_asyncio.subprocess.PIPE,
                            stderr=_asyncio.subprocess.PIPE,
                            cwd=_cc_cwd,
                        )
                        logger.info("CC PIPE: process spawned, pid=%s", cc_proc.pid)
                    except Exception as spawn_err:
                        await websocket.send_json(
                            {
                                "type": "error",
                                "data": {
                                    "message": f"Failed to start CC: {spawn_err}",
                                    "code": "spawn_failed",
                                },
                            }
                        )
                        continue

                tool_id_map: dict = {}

                def _terminate_cc():
                    """Terminate CC subprocess regardless of PTY mode."""
                    if use_cc_pty and cc_pty_process and _sys.platform == "win32":
                        if cc_pty_process.isalive():
                            cc_pty_process.terminate()
                    elif cc_proc is not None:
                        if hasattr(cc_proc, "returncode"):
                            # asyncio.subprocess
                            if cc_proc.returncode is None:
                                cc_proc.terminate()
                        elif hasattr(cc_proc, "poll"):
                            # subprocess.Popen
                            if cc_proc.poll() is None:
                                cc_proc.terminate()

                loop = _asyncio.get_event_loop()

                if use_cc_pty and _sys.platform == "win32":
                    # Windows PTY: readline via run_in_executor, ANSI stripped (PTY-01)
                    async def _read_stdout():
                        try:
                            while cc_pty_process.isalive():
                                try:
                                    raw_line = await loop.run_in_executor(
                                        None, cc_pty_process.readline
                                    )
                                    line = _ANSI_ESCAPE.sub("", raw_line).strip()
                                    if not line:
                                        continue
                                    try:
                                        event = _json.loads(line)
                                    except _json.JSONDecodeError:
                                        continue
                                    envelopes = _parse_cc_event(event, tool_id_map, session_state)
                                    logger.info(
                                        f"CC PTY event type={event.get('type')}, "
                                        f"envelopes={len(envelopes)}"
                                    )
                                    for env in envelopes:
                                        if env.get("type") == "text_delta":
                                            session_state["last_assistant_text"] = (
                                                session_state.get("last_assistant_text", "")
                                                + env["data"].get("text", "")
                                            )[-200:]
                                    for envelope in envelopes:
                                        try:
                                            await websocket.send_json(envelope)
                                        except Exception as ws_err:
                                            logger.error(f"CC WS send failed: {ws_err}")
                                            return
                                except EOFError:
                                    break
                                except Exception as inner_err:
                                    logger.error(f"CC PTY readline error: {inner_err}")
                                    break
                        except Exception as outer_err:
                            logger.error(f"CC _read_stdout (win PTY) error: {outer_err}")

                elif use_cc_pty:
                    # Unix PTY: select + os.read with line accumulation buffer (PTY-01)
                    import select as _cc_select

                    _cc_line_buf = ""

                    def _read_cc_chunk():
                        if _cc_select.select([cc_master_fd], [], [], 0.1)[0]:
                            try:
                                return _os.read(cc_master_fd, 4096).decode(
                                    "utf-8", errors="replace"
                                )
                            except OSError:
                                return None
                        return ""

                    async def _read_stdout():
                        nonlocal _cc_line_buf
                        try:
                            while cc_proc.poll() is None:
                                chunk = await loop.run_in_executor(None, _read_cc_chunk)
                                if chunk is None:
                                    break
                                if not chunk:
                                    await _asyncio.sleep(0.05)
                                    continue
                                _cc_line_buf += chunk
                                while "\n" in _cc_line_buf:
                                    raw_line, _cc_line_buf = _cc_line_buf.split("\n", 1)
                                    line = _ANSI_ESCAPE.sub("", raw_line).strip()
                                    if not line:
                                        continue
                                    try:
                                        event = _json.loads(line)
                                    except _json.JSONDecodeError:
                                        continue
                                    envelopes = _parse_cc_event(event, tool_id_map, session_state)
                                    logger.info(
                                        f"CC PTY event type={event.get('type')}, "
                                        f"envelopes={len(envelopes)}"
                                    )
                                    for env in envelopes:
                                        if env.get("type") == "text_delta":
                                            session_state["last_assistant_text"] = (
                                                session_state.get("last_assistant_text", "")
                                                + env["data"].get("text", "")
                                            )[-200:]
                                    for envelope in envelopes:
                                        try:
                                            await websocket.send_json(envelope)
                                        except Exception as ws_err:
                                            logger.error(f"CC WS send failed: {ws_err}")
                                            return
                        except Exception as outer_err:
                            logger.error(f"CC _read_stdout (unix PTY) error: {outer_err}")

                else:
                    # PIPE fallback (PTY-04): readline loop (more reliable on Windows)
                    async def _read_stdout():
                        try:
                            logger.info("CC _read_stdout (PIPE): starting readline loop")
                            while True:
                                raw_line = await cc_proc.stdout.readline()
                                if not raw_line:
                                    break
                                line = raw_line.decode("utf-8", errors="replace").strip()
                                if not line:
                                    continue
                                try:
                                    event = _json.loads(line)
                                except _json.JSONDecodeError:
                                    continue
                                envelopes = _parse_cc_event(event, tool_id_map, session_state)
                                logger.info(
                                    f"CC event type={event.get('type')}, envelopes={len(envelopes)}"
                                )
                                for env in envelopes:
                                    if env.get("type") == "text_delta":
                                        session_state["last_assistant_text"] = (
                                            session_state.get("last_assistant_text", "")
                                            + env["data"].get("text", "")
                                        )[-200:]
                                for envelope in envelopes:
                                    try:
                                        await websocket.send_json(envelope)
                                    except Exception as ws_err:
                                        logger.error(f"CC WS send failed: {ws_err}")
                                        return
                            logger.info("CC _read_stdout (PIPE): readline loop finished")
                        except Exception as read_err:
                            logger.error(f"CC _read_stdout (PIPE) error: {read_err}")

                # PTY-05: keepalive task sends {"type": "keepalive"} every 15 seconds
                async def _send_keepalive():
                    try:
                        while True:
                            await _asyncio.sleep(15)
                            try:
                                await websocket.send_json({"type": "keepalive"})
                            except Exception:
                                break
                    except Exception:
                        pass

                keepalive_task = _asyncio.create_task(_send_keepalive())
                read_task = _asyncio.create_task(_read_stdout())

                async def _receive_msg():
                    return await websocket.receive_text()

                receive_task = _asyncio.create_task(_receive_msg())
                try:
                    while True:
                        done, _pending = await _asyncio.wait(
                            {read_task, receive_task}, return_when=_asyncio.FIRST_COMPLETED
                        )
                        if receive_task in done:
                            # Client disconnect raises WebSocketDisconnect in receive_task —
                            # check exception first to avoid infinite spin loop (code-review #1)
                            if receive_task.exception() is not None:
                                read_task.cancel()
                                _terminate_cc()
                                receive_task = None
                                break
                            try:
                                inner = _json.loads(receive_task.result())
                            except Exception:
                                inner = {}
                            if inner.get("type") == "stop":
                                read_task.cancel()
                                _terminate_cc()
                                await websocket.send_json(
                                    {
                                        "type": "turn_complete",
                                        "data": {
                                            "session_id": session_state.get("cc_session_id"),
                                            "cost_usd": None,
                                            "input_tokens": 0,
                                            "output_tokens": 0,
                                        },
                                    }
                                )
                                receive_task = None
                                break
                            elif inner.get("type") == "permission_response":
                                perm_id = inner.get("id", "")
                                approved = inner.get("approved", False)
                                session_state["permission_results"][perm_id] = approved
                                evt = session_state["permission_events"].get(perm_id)
                                if evt:
                                    evt.set()
                            elif inner.get("type") == "question_response":
                                # User answered an AskUserQuestion — write answer to CC stdin
                                answer_text = inner.get("text", "")
                                if (
                                    answer_text
                                    and cc_proc is not None
                                    and hasattr(cc_proc, "stdin")
                                    and cc_proc.stdin
                                    and not cc_proc.stdin.is_closing()
                                ):
                                    try:
                                        cc_proc.stdin.write((answer_text + "\n").encode("utf-8"))
                                        await cc_proc.stdin.drain()
                                        logger.info(
                                            "CC AskUserQuestion: wrote answer to stdin (%d chars)",
                                            len(answer_text),
                                        )
                                    except Exception as q_err:
                                        logger.warning(
                                            "CC AskUserQuestion: stdin write failed: %s", q_err
                                        )
                            elif inner.get("type") == "trust_mode":
                                session_state["trust_mode"] = inner.get("enabled", False)
                            # Not a stop — re-arm receive and check if read_task also completed
                            receive_task = _asyncio.create_task(_receive_msg())
                            if read_task in done:
                                break
                        else:
                            # read_task completed (subprocess exited) — turn done
                            for t in _pending:
                                t.cancel()
                            break
                finally:
                    if receive_task and not receive_task.done():
                        receive_task.cancel()
                    read_task.cancel()
                    keepalive_task.cancel()
                    _terminate_cc()
                    if cc_master_fd is not None:
                        try:
                            _os.close(cc_master_fd)
                        except OSError:
                            pass

                # GSD: Re-read workstream (may have changed during this turn)
                _gsd_updated = _read_gsd_workstream(workspace)
                if _gsd_updated.get("workstream"):
                    session_state["gsd_workstream"] = _gsd_updated["workstream"]
                    session_state["gsd_phase"] = _gsd_updated.get("phase", "")
                try:
                    await websocket.send_json(
                        {
                            "type": "workstream_update",
                            "data": {
                                "workstream": session_state.get("gsd_workstream", ""),
                                "phase": session_state.get("gsd_phase", ""),
                            },
                        }
                    )
                except Exception:
                    pass  # WS may be closing

                await _save_session(
                    ws_session_id,
                    {
                        "ws_session_id": ws_session_id,
                        "cc_session_id": session_state.get("cc_session_id"),
                        "created_at": created_at,
                        "last_active_at": _datetime.datetime.utcnow().isoformat(),
                        "title": session_title,
                        "preview_text": session_state.get("last_assistant_text", "")[:60],
                        "message_count": session_state.get("message_count", 0),
                        "gsd_workstream": session_state.get("gsd_workstream", ""),
                        "gsd_phase": session_state.get("gsd_phase", ""),
                        "workspace_id": ws_workspace_id or "",
                    },
                )

        except WebSocketDisconnect:
            pass
        except Exception as _cc_outer_err:
            logger.error("CC chat WS error: %s", _cc_outer_err, exc_info=True)

    # -- CC Session REST API ---------------------------------------------------

    @app.get("/api/cc/sessions")
    async def cc_sessions(
        workspace_id: str | None = None,
        _user: str = Depends(get_current_user),
    ):
        """List all CC chat sessions, sorted by last modified time.

        If workspace_id is provided, returns only sessions whose workspace_id matches,
        plus legacy sessions (no workspace_id field) which belong to any workspace.
        """
        sessions = []
        cc_dir = workspace / ".agent42" / "cc-sessions"
        if cc_dir.exists():
            for f in sorted(cc_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
                try:
                    async with _aiofiles.open(f) as fh:
                        data = _json.loads(await fh.read())
                    if workspace_id is not None:
                        session_ws = data.get("workspace_id")
                        # Include if: matches filter, or is a legacy session (no workspace_id field)
                        if session_ws and session_ws != workspace_id:
                            continue
                    sessions.append(data)
                except Exception:
                    pass
        return {"sessions": sessions}

    @app.delete("/api/cc/sessions/{session_id}")
    async def cc_delete_session(session_id: str, _user: str = Depends(get_current_user)):
        """Delete a CC chat session file."""
        path = workspace / ".agent42" / "cc-sessions" / f"{session_id}.json"
        if path.exists():
            path.unlink()
        return {"status": "ok"}

    # -- CC Auth Status --------------------------------------------------------

    _cc_auth_cache: dict = {"result": None, "expires": 0.0}

    @app.get("/api/cc/auth-status")
    async def cc_auth_status(_user: str = Depends(get_current_user)):
        """Check CC subscription status via 'claude auth status' exit code."""
        import time as _time

        now = _time.monotonic()
        cached = _cc_auth_cache
        if cached["expires"] > now and cached["result"] is not None:
            available, message = cached["result"]
            return {"available": available, "message": message}

        claude_bin = _shutil.which("claude")
        if not claude_bin:
            result = (False, "claude CLI not installed")
        else:
            try:
                proc = await _asyncio.create_subprocess_exec(
                    claude_bin,
                    "auth",
                    "status",
                    stdout=_asyncio.subprocess.PIPE,
                    stderr=_asyncio.subprocess.PIPE,
                )
                await _asyncio.wait_for(proc.wait(), timeout=10.0)
                available = proc.returncode == 0
                message = "CC subscription active" if available else "CC not authenticated"
                result = (available, message)
            except TimeoutError:
                result = (False, "claude auth status timed out")
            except Exception as e:
                result = (False, f"auth check failed: {e}")

        _cc_auth_cache["result"] = result
        _cc_auth_cache["expires"] = now + 60.0
        available, message = result
        return {"available": available, "message": message}

    # -- Remote Node Status ----------------------------------------------------

    @app.get("/api/remote/status")
    async def remote_status(_user: str = Depends(get_current_user)):
        """Check if a remote node is configured."""
        host = _os.environ.get("AGENT42_REMOTE_HOST", "")
        return {"available": bool(host), "host": host if host else None}

    # -- Memory Search API (used by hooks + frontend) -------------------------

    @app.post("/api/memory/search")
    async def memory_search(request: Request):
        """Search Agent42's memory system (Qdrant + MEMORY.md).

        Used by the memory-recall hook as a fallback when the dedicated
        search service isn't running. No auth required for local hook access.
        """
        # Reset 24h stats window if a full day has passed
        if _time_mem.time() - _memory_stats["last_reset"] > 86400:
            _memory_stats["recall_count"] = 0
            _memory_stats["learn_count"] = 0
            _memory_stats["error_count"] = 0
            _memory_stats["total_latency_ms"] = 0.0
            _memory_stats["last_reset"] = _time_mem.time()

        _start = _time_mem.monotonic()
        keyword_count = 0
        try:
            body = await request.json()
            query = body.get("content", body.get("query", ""))
            if not query:
                return {"results": []}

            keyword_count = len(query.split())
            results = []
            search_method = "none"

            # Try Qdrant semantic search if memory_store is available
            if memory_store:
                try:
                    hits = await memory_store.semantic_search(query, top_k=5)
                    for hit in hits:
                        results.append(
                            {
                                "text": hit.get("text", hit.get("content", "")),
                                "score": hit.get("score", 0.5),
                                "source": hit.get("source", "qdrant"),
                            }
                        )
                    if results:
                        search_method = "semantic"
                except Exception:
                    pass

            # Fallback: keyword search on MEMORY.md
            if not results:
                mem_path = workspace / "memory" / "MEMORY.md"
                if not mem_path.exists():
                    mem_path = workspace / ".agent42" / "MEMORY.md"
                if mem_path.exists():
                    content = mem_path.read_text(encoding="utf-8", errors="replace")
                    keywords = [w.lower() for w in query.split() if len(w) > 3]
                    for section in content.split("\n## "):
                        matches = sum(1 for k in keywords if k in section.lower())
                        if matches >= 2:
                            results.append(
                                {
                                    "text": section[:250].strip(),
                                    "score": min(matches * 0.2, 1.0),
                                    "source": "memory-md",
                                }
                            )
                    if results:
                        search_method = "keyword"

            _elapsed = (_time_mem.monotonic() - _start) * 1000
            _memory_logger.info(
                "recall query: keywords=%d results=%d method=%s latency_ms=%.1f",
                keyword_count,
                len(results),
                search_method,
                _elapsed,
            )
            _memory_stats["recall_count"] += 1
            _memory_stats["total_latency_ms"] += _elapsed

            return {"results": results[:5]}
        except Exception as e:
            _elapsed = (_time_mem.monotonic() - _start) * 1000
            _memory_logger.warning(
                "recall query failed: keywords=%d error=%s latency_ms=%.1f",
                keyword_count,
                str(e)[:100],
                _elapsed,
            )
            _memory_stats["error_count"] += 1
            return {"results": [], "error": str(e)}

    @app.get("/api/memory/stats")
    async def memory_stats():
        """Return 24h memory pipeline activity counters."""
        avg_latency = _memory_stats["total_latency_ms"] / max(_memory_stats["recall_count"], 1)
        return {
            "recall_count": _memory_stats["recall_count"],
            "learn_count": _memory_stats["learn_count"],
            "error_count": _memory_stats["error_count"],
            "avg_latency_ms": round(avg_latency, 1),
            "period_start": _memory_stats["last_reset"],
        }

    # -- IDE Chat (AI-powered code assistant) ----------------------------------

    import httpx as _httpx

    class ChatRequest(BaseModel):
        message: str
        history: list = []
        provider_url: str = ""
        api_key: str = ""
        model: str = ""
        file_context: str = ""

    # -- Chat Session Management -----------------------------------------------

    import json as _chat_json
    import time as _chat_time
    import uuid as _chat_uuid

    import aiofiles as _chat_aiofiles

    _CHAT_SESSIONS_DIR = Path(_os.environ.get("AGENT42_DATA_DIR", ".agent42")) / "chat-sessions"
    _CHAT_SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

    async def _chat_load_sessions(session_type: str = "") -> list[dict]:
        """Load all chat sessions, optionally filtered by type."""
        sessions = []
        if not _CHAT_SESSIONS_DIR.exists():
            return sessions
        for f in _CHAT_SESSIONS_DIR.iterdir():
            if f.suffix == ".json" and not f.stem.endswith("_messages"):
                try:
                    async with _chat_aiofiles.open(f) as fh:
                        s = _chat_json.loads(await fh.read())
                        if session_type and s.get("session_type") != session_type:
                            continue
                        sessions.append(s)
                except Exception:
                    continue
        sessions.sort(key=lambda s: s.get("updated_at", 0), reverse=True)
        return sessions

    async def _chat_load_session(session_id: str) -> dict | None:
        path = _CHAT_SESSIONS_DIR / f"{session_id}.json"
        if not path.exists():
            return None
        try:
            async with _chat_aiofiles.open(path) as fh:
                return _chat_json.loads(await fh.read())
        except Exception:
            return None

    async def _chat_save_session(session: dict):
        path = _CHAT_SESSIONS_DIR / f"{session['id']}.json"
        async with _chat_aiofiles.open(path, "w") as fh:
            await fh.write(_chat_json.dumps(session, indent=2))

    async def _chat_load_messages(session_id: str) -> list[dict]:
        path = _CHAT_SESSIONS_DIR / f"{session_id}_messages.json"
        if not path.exists():
            return []
        try:
            async with _chat_aiofiles.open(path) as fh:
                return _chat_json.loads(await fh.read())
        except Exception:
            return []

    async def _chat_save_messages(session_id: str, messages: list[dict]):
        path = _CHAT_SESSIONS_DIR / f"{session_id}_messages.json"
        async with _chat_aiofiles.open(path, "w") as fh:
            await fh.write(_chat_json.dumps(messages, indent=2))

    async def _chat_via_cc(prompt: str) -> str | None:
        """Try Claude Code subprocess (uses CC subscription). Returns None if unavailable.

        Security: claude binary path is resolved via shutil.which (no user input in args).
        The prompt is passed as a positional arg to create_subprocess_exec (not shell).
        """
        import shutil as _shutil_cc

        claude_bin = _shutil_cc.which("claude")
        if not claude_bin:
            return None

        try:
            # Write empty MCP config to temp file (avoids JSON arg escaping on Windows)
            _empty_mcp = workspace / ".agent42" / "empty-mcp.json"
            if not _empty_mcp.exists():
                _empty_mcp.parent.mkdir(parents=True, exist_ok=True)
                _empty_mcp.write_text('{"mcpServers":{}}')

            # create_subprocess_exec — no shell injection risk (args are not shell-interpreted)
            proc = await _asyncio.create_subprocess_exec(
                claude_bin,
                "-p",
                prompt,
                "--output-format",
                "stream-json",
                "--mcp-config",
                str(_empty_mcp),
                "--strict-mcp-config",
                stdout=_asyncio.subprocess.PIPE,
                stderr=_asyncio.subprocess.PIPE,
                cwd=str(workspace),
            )
            logger.info("CC chat subprocess started, PID=%s", proc.pid)

            # Stream stdout line-by-line. Return as soon as "result" event arrives.
            # Don't use communicate() — Stop hooks run 30s+ after result, blocking exit.
            async def _read_cc_result():
                while True:
                    raw_line = await proc.stdout.readline()
                    if not raw_line:
                        break
                    decoded = raw_line.decode("utf-8", errors="replace").strip()
                    if not decoded:
                        continue
                    try:
                        ev = _json.loads(decoded)
                        if isinstance(ev, dict) and ev.get("type") == "result":
                            return ev.get("result", "")
                    except _json.JSONDecodeError:
                        continue
                return None

            try:
                result_text = await _asyncio.wait_for(_read_cc_result(), timeout=45.0)
            except TimeoutError:
                result_text = None
                logger.warning("CC chat stream timed out (45s)")

            # Kill subprocess — don't wait for Stop hooks
            try:
                proc.kill()
            except Exception:
                pass

            if result_text:
                logger.info("CC chat got result (%d chars)", len(result_text))
                return result_text

            logger.warning("CC chat: no result event in stream")
        except Exception as e:
            logger.warning("CC chat error: %s", e)
        return None

    async def _chat_complete(
        system_prompt: str,
        messages: list[dict],
        user_query: str = "",
        mem_store=None,
    ) -> tuple[str, str]:
        """Try CC subscription first, then API providers. Returns (text, provider_name)."""

        # 1. Try Claude Code subscription (primary — CC loads memory via its own hooks)
        context_parts = []
        if system_prompt:
            context_parts.append(system_prompt)
        for m in messages[-10:]:
            role = "Human" if m["role"] == "user" else "Assistant"
            context_parts.append(f"{role}: {m['content']}")
        cc_prompt = "\n\n".join(context_parts)

        cc_result = await _chat_via_cc(cc_prompt)
        if cc_result:
            return cc_result, "claude-code"

        logger.info("CC subscription unavailable, trying API providers...")

        # Load memory context for API fallback (CC handles this via hooks)
        if user_query and mem_store:
            try:
                from memory.store import build_conversational_memory_context

                mem_ctx = await build_conversational_memory_context(
                    mem_store, user_query, timeout=5.0
                )
                if mem_ctx and mem_ctx.strip():
                    system_prompt += "\n\n" + mem_ctx
            except Exception:
                pass

        # 2. Fall back to API providers
        chat_model = _os.environ.get("CHAT_MODEL", "")
        providers = []

        anthropic_key = _os.environ.get("ANTHROPIC_API_KEY", "")
        if anthropic_key:
            providers.append(("anthropic", anthropic_key))

        synthetic_key = _os.environ.get("SYNTHETIC_API_KEY", "")
        if synthetic_key:
            providers.append(("synthetic", synthetic_key))

        gemini_key = _os.environ.get("GEMINI_API_KEY", "") or _os.environ.get("GOOGLE_API_KEY", "")
        if gemini_key:
            providers.append(("gemini", gemini_key))

        or_key = _os.environ.get("OPENROUTER_API_KEY", "")
        if or_key:
            providers.append(("openrouter", or_key))

        openai_key = _os.environ.get("OPENAI_API_KEY", "")
        if openai_key:
            providers.append(("openai", openai_key))

        if not providers:
            return (
                "Claude Code is not available and no API keys are configured. "
                "Install Claude Code (`npm install -g @anthropic-ai/claude-code`) or "
                "set an API key in Dashboard Settings.",
                "none",
            )

        last_error = ""
        for provider_name, api_key in providers:
            try:
                if provider_name == "anthropic":
                    base = _os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
                    model = chat_model or "claude-sonnet-4-5-20250514"
                    headers = {
                        "x-api-key": api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    }
                    body = {
                        "model": model,
                        "max_tokens": 4096,
                        "system": system_prompt,
                        "messages": messages,
                    }
                    async with _httpx.AsyncClient(timeout=120.0) as client:
                        resp = await client.post(
                            base.rstrip("/") + "/v1/messages",
                            headers=headers,
                            json=body,
                        )
                        if resp.status_code == 200:
                            text = ""
                            for block in resp.json().get("content", []):
                                if block.get("type") == "text":
                                    text += block.get("text", "")
                            return text, "anthropic"
                        last_error = f"Anthropic {resp.status_code}: {resp.text[:200]}"

                elif provider_name == "synthetic":
                    # Synthetic.new — Anthropic-compatible API
                    base = "https://api.synthetic.new"
                    model = chat_model or "claude-sonnet-4-5-20250514"
                    headers = {
                        "x-api-key": api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    }
                    body = {
                        "model": model,
                        "max_tokens": 4096,
                        "system": system_prompt,
                        "messages": messages,
                    }
                    async with _httpx.AsyncClient(timeout=120.0) as client:
                        resp = await client.post(
                            base.rstrip("/") + "/v1/messages",
                            headers=headers,
                            json=body,
                        )
                        if resp.status_code == 200:
                            text = ""
                            for block in resp.json().get("content", []):
                                if block.get("type") == "text":
                                    text += block.get("text", "")
                            return text, "synthetic"
                        last_error = f"Synthetic {resp.status_code}: {resp.text[:200]}"

                elif provider_name == "gemini":
                    model = chat_model or "gemini-2.0-flash"
                    gemini_msgs = [
                        {
                            "role": m["role"] if m["role"] != "assistant" else "model",
                            "parts": [{"text": m["content"]}],
                        }
                        for m in messages
                    ]
                    body = {
                        "system_instruction": {"parts": [{"text": system_prompt}]},
                        "contents": gemini_msgs,
                        "generationConfig": {"maxOutputTokens": 4096},
                    }
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
                    async with _httpx.AsyncClient(timeout=120.0) as client:
                        resp = await client.post(url, json=body)
                        if resp.status_code == 200:
                            data = resp.json()
                            candidates = data.get("candidates", [])
                            if candidates:
                                parts = candidates[0].get("content", {}).get("parts", [])
                                return "".join(p.get("text", "") for p in parts), "gemini"
                            return "(Empty response from Gemini)", "gemini"
                        last_error = f"Gemini {resp.status_code}: {resp.text[:200]}"

                elif provider_name in ("openrouter", "openai"):
                    if provider_name == "openrouter":
                        base = "https://openrouter.ai/api"
                        model = chat_model or "google/gemini-2.0-flash-exp:free"
                    else:
                        base = _os.environ.get("OPENAI_BASE_URL", "https://api.openai.com")
                        model = chat_model or "gpt-4o-mini"
                    oai_msgs = [{"role": "system", "content": system_prompt}] + messages
                    headers = {
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    }
                    body = {"model": model, "messages": oai_msgs, "max_tokens": 4096}
                    async with _httpx.AsyncClient(timeout=120.0) as client:
                        resp = await client.post(
                            base.rstrip("/") + "/v1/chat/completions",
                            headers=headers,
                            json=body,
                        )
                        if resp.status_code == 200:
                            choices = resp.json().get("choices", [])
                            if choices:
                                return choices[0].get("message", {}).get(
                                    "content", ""
                                ), provider_name
                            return "(Empty response)", provider_name
                        last_error = f"{provider_name} {resp.status_code}: {resp.text[:200]}"

            except _httpx.TimeoutException:
                last_error = f"{provider_name} timed out"
            except Exception as e:
                last_error = f"{provider_name} error: {e}"

        return f"All providers failed. Last error: {last_error}", "none"

    @app.get("/api/chat/messages")
    async def chat_messages_legacy(_user: str = Depends(get_current_user)):
        """Get messages for legacy (no-session) chat mode."""
        return await _chat_load_messages("_legacy")

    @app.get("/api/chat/sessions")
    async def chat_sessions_list(type: str = "", _user: str = Depends(get_current_user)):
        """List chat sessions, optionally filtered by type (chat/code)."""
        return await _chat_load_sessions(type)

    class CreateSessionRequest(BaseModel):
        title: str = ""
        session_type: str = "chat"

    @app.post("/api/chat/sessions")
    async def chat_session_create(
        req: CreateSessionRequest, _user: str = Depends(get_current_user)
    ):
        """Create a new chat/code session."""
        now = _chat_time.time()
        session = {
            "id": str(_chat_uuid.uuid4()),
            "title": req.title or "New conversation",
            "session_type": req.session_type,
            "created_at": now,
            "updated_at": now,
            "message_count": 0,
            "deployment_target": None,
        }
        await _chat_save_session(session)
        return session

    @app.get("/api/chat/sessions/{session_id}/messages")
    async def chat_session_messages(session_id: str, _user: str = Depends(get_current_user)):
        """Get all messages for a specific session."""
        return await _chat_load_messages(session_id)

    class SendMessageRequest(BaseModel):
        message: str
        file_context: str = ""

    @app.post("/api/chat/sessions/{session_id}/send")
    async def chat_session_send(
        session_id: str, req: SendMessageRequest, _user: str = Depends(get_current_user)
    ):
        """Send a message in a session and get AI response."""
        session = await _chat_load_session(session_id)
        if not session:
            raise HTTPException(404, "Session not found")

        messages = await _chat_load_messages(session_id)
        now = _chat_time.time()

        # Save user message
        user_msg = {
            "id": str(_chat_uuid.uuid4()),
            "role": "user",
            "content": req.message,
            "timestamp": now,
            "sender": "You",
            "session_id": session_id,
        }
        messages.append(user_msg)

        # Broadcast user message + thinking indicator via WS
        if ws_manager:
            await ws_manager.broadcast("chat_message", user_msg)
            await ws_manager.broadcast(
                "chat_thinking", {"session_id": session_id, "thinking": True}
            )

        # Update session title from first message
        if session.get("message_count", 0) == 0:
            session["title"] = req.message[:80]

        # Build AI conversation history
        ai_messages = []
        for m in messages[-20:]:
            ai_messages.append({"role": m["role"], "content": m["content"]})

        # Build system prompt
        system_parts = [
            "You are Agent42, an AI assistant. Be helpful, concise, and accurate.",
            "You can help with coding, debugging, project management, and general questions.",
        ]
        persona = _load_persona() if callable(_load_persona) else ""
        if persona:
            system_parts.insert(0, persona)
        if req.file_context:
            system_parts.append(f"\nCurrently open file:\n```\n{req.file_context[:3000]}\n```")

        system_prompt = "\n".join(system_parts)

        # Get AI response — CC first (has its own memory via hooks), then API with memory
        _t0 = _chat_time.time()
        response_text, provider_used = await _chat_complete(
            system_prompt, ai_messages, req.message, memory_store
        )
        _elapsed_ms = int((_chat_time.time() - _t0) * 1000)

        # Save assistant message
        assistant_msg = {
            "id": str(_chat_uuid.uuid4()),
            "role": "assistant",
            "content": response_text,
            "timestamp": _chat_time.time(),
            "sender": "Agent42",
            "session_id": session_id,
            "response_ms": _elapsed_ms,
            "provider": provider_used,
        }
        messages.append(assistant_msg)

        # Update session metadata
        session["message_count"] = len([m for m in messages if m["role"] == "user"])
        session["updated_at"] = _chat_time.time()
        session["preview"] = response_text[:60]

        await _chat_save_messages(session_id, messages)
        await _chat_save_session(session)

        # Broadcast response + stop thinking via WS
        if ws_manager:
            await ws_manager.broadcast("chat_message", assistant_msg)
            await ws_manager.broadcast(
                "chat_thinking", {"session_id": session_id, "thinking": False}
            )

        return {"status": "ok"}

    @app.delete("/api/chat/sessions/{session_id}")
    async def chat_session_delete(session_id: str, _user: str = Depends(get_current_user)):
        """Delete a chat session and its messages."""
        session_path = _CHAT_SESSIONS_DIR / f"{session_id}.json"
        messages_path = _CHAT_SESSIONS_DIR / f"{session_id}_messages.json"
        if session_path.exists():
            session_path.unlink()
        if messages_path.exists():
            messages_path.unlink()
        return {"status": "ok"}

    class ChatSetupRequest(BaseModel):
        mode: str = "local"
        runtime: str = "python"
        app_name: str = ""
        ssh_host: str = ""
        github_repo_name: str = ""
        github_clone_url: str = ""
        github_private: bool = True
        repo_id: str = ""

    @app.post("/api/chat/sessions/{session_id}/setup")
    async def chat_session_setup(
        session_id: str, req: ChatSetupRequest, _user: str = Depends(get_current_user)
    ):
        """Configure deployment target for a code session."""
        session = await _chat_load_session(session_id)
        if not session:
            raise HTTPException(404, "Session not found")
        session["deployment_target"] = {
            "mode": req.mode,
            "runtime": req.runtime,
            "app_name": req.app_name,
            "ssh_host": req.ssh_host,
            "github_repo_name": req.github_repo_name,
            "github_clone_url": req.github_clone_url,
            "github_private": req.github_private,
            "repo_id": req.repo_id,
        }
        session["updated_at"] = _chat_time.time()
        await _chat_save_session(session)
        return session

    # -- Effectiveness Tracking API (EFFT-03: MCP tool tracking) ---------------

    @app.post("/api/effectiveness/record")
    async def record_effectiveness(request: Request):
        """Record a tool invocation from an external hook (MCP tool tracking).

        Accepts JSON: {tool_name, task_type, task_id, success, duration_ms}
        Used by PostToolUse hooks to track MCP tools that bypass ToolRegistry.
        """
        try:
            data = await request.json()
            if effectiveness_store:
                await effectiveness_store.record(
                    tool_name=data.get("tool_name", "unknown"),
                    task_type=data.get("task_type", "general"),
                    task_id=data.get("task_id", ""),
                    success=bool(data.get("success", True)),
                    duration_ms=float(data.get("duration_ms", 0)),
                )
            return {"status": "ok"}
        except Exception as e:
            return {"status": "error", "detail": str(e)}

    @app.get("/api/effectiveness/stats")
    async def effectiveness_stats(tool_name: str = "", task_type: str = ""):
        """Return aggregated effectiveness statistics."""
        if not effectiveness_store:
            return {"stats": []}
        stats = await effectiveness_store.get_aggregated_stats(tool_name, task_type)
        return {"stats": stats}

    @app.get("/api/recommendations/retrieve")
    async def retrieve_recommendations(
        task_type: str = "",
        top_k: int = 3,
        min_observations: int = 0,
    ) -> dict:
        """Return top-N tool recommendations for a given task_type.

        Uses EffectivenessStore historical success_rate data.
        Called by proactive-inject.py hook at session start.

        Query parameters:
          task_type        - Required. Returns empty list when omitted.
          top_k            - Max results (default 3, RETR-05 cap).
          min_observations - Override config minimum (0 = use settings default).

        Returns: {"recommendations": [...], "task_type": str}
        Each item: {tool_name, success_rate, avg_duration_ms, invocations}
        """
        if not task_type:
            return {"recommendations": [], "task_type": ""}
        try:
            if not effectiveness_store:
                return {"recommendations": [], "task_type": task_type}
            min_obs = (
                min_observations
                if min_observations > 0
                else settings.recommendations_min_observations
            )
            recs = await effectiveness_store.get_recommendations(
                task_type=task_type,
                min_observations=min_obs,
                top_k=top_k,
            )
            return {"recommendations": recs, "task_type": task_type}
        except Exception:
            return {"recommendations": [], "task_type": task_type}

    async def _maybe_promote_quarantined(ms, task_type: str, outcome: str, summary: str):
        """Increment observation_count on matching quarantined learnings.

        Promotes entries to full confidence when they reach LEARNING_MIN_EVIDENCE.
        Fire-and-forget — never blocks the response.
        """
        import os as _os_local

        try:
            if not ms or not ms.embeddings._qdrant:
                return
            qdrant = ms.embeddings._qdrant
            if not qdrant.is_available:
                return

            from memory.qdrant_store import QdrantStore

            threshold = int(_os_local.environ.get("LEARNING_MIN_EVIDENCE", "3"))

            query_vector = await ms.embeddings.embed_text(summary)
            results = qdrant.search_with_lifecycle(
                QdrantStore.HISTORY,
                query_vector,
                top_k=5,
                task_type_filter=task_type,
            )

            for r in results:
                payload = r.get("payload", {})
                if not payload.get("quarantined"):
                    continue
                if payload.get("outcome") != outcome:
                    continue
                if r.get("score", 0) < 0.70:
                    continue

                point_id = r.get("point_id")
                if not point_id:
                    continue

                new_count = payload.get("observation_count", 1) + 1
                updates = {"observation_count": new_count}
                if new_count >= threshold:
                    updates["confidence"] = 1.0
                    updates["quarantined"] = False
                    logger.info(
                        "Promoted quarantined learning (point %s) after %d observations",
                        point_id,
                        new_count,
                    )
                qdrant.update_payload(QdrantStore.HISTORY, point_id, updates)

        except Exception as e:
            logger.warning("Quarantine promotion check failed (non-critical): %s", e)

    @app.post("/api/effectiveness/learn")
    async def record_learning(request: Request):
        """Persist a learning entry from the Stop hook extraction pipeline.

        Accepts JSON: {task_type, task_id, outcome, summary, tools_used, files_modified, key_insight}
        Writes to HISTORY.md and indexes in Qdrant with quarantine fields.
        No authentication required — called by local Stop hooks only.
        """
        import asyncio as _asyncio
        import os as _os_local

        try:
            data = await request.json()
            task_type = data.get("task_type", "general")
            task_id = data.get("task_id", "")
            outcome = data.get("outcome", "unknown")
            summary = data.get("summary", "")
            key_insight = data.get("key_insight", "")
            tools_used = data.get("tools_used", [])
            files_modified = data.get("files_modified", [])

            if not summary:
                return {"status": "skipped", "reason": "empty summary"}

            # Format: [task_type][task_id][outcome]
            event_type = f"[{task_type}][{task_id}][{outcome}]"
            details = ""
            if tools_used:
                details += f"Tools used: {', '.join(tools_used)}.\n"
            if files_modified:
                details += f"Files modified: {', '.join(files_modified)}.\n"
            if key_insight:
                details += f"Key insight: {key_insight}"

            # Set task context so index_history_entry picks up task_id/task_type
            from core.task_context import _task_id_var, begin_task, end_task
            from core.task_types import TaskType

            # Map string to TaskType enum (fallback to GENERAL)
            try:
                tt_enum = TaskType(task_type)
            except ValueError:
                tt_enum = TaskType.GENERAL

            ctx = begin_task(tt_enum)
            # Override the auto-generated task_id with the one from the hook
            _task_id_var.set(task_id if task_id else ctx.task_id)

            try:
                if memory_store:
                    await memory_store.log_event_semantic(event_type, summary, details)

                    # Add quarantine fields to the Qdrant entry
                    if (
                        memory_store.embeddings._qdrant
                        and memory_store.embeddings._qdrant.is_available
                    ):
                        from memory.qdrant_store import QdrantStore

                        # Find the most recently upserted point and add quarantine fields
                        query_vector = await memory_store.embeddings.embed_text(
                            f"{event_type}: {summary}\n{details}"
                        )
                        results = memory_store.embeddings._qdrant.search_with_lifecycle(
                            QdrantStore.HISTORY,
                            query_vector,
                            top_k=1,
                            task_type_filter=task_type,
                        )
                        if results:
                            point_id = results[0].get("point_id")
                            if point_id:
                                quarantine_conf = float(
                                    _os_local.environ.get("LEARNING_QUARANTINE_CONFIDENCE", "0.6")
                                )
                                memory_store.embeddings._qdrant.update_payload(
                                    QdrantStore.HISTORY,
                                    point_id,
                                    {
                                        "observation_count": 1,
                                        "confidence": quarantine_conf,
                                        "quarantined": True,
                                        "outcome": outcome,
                                    },
                                )
            finally:
                end_task(ctx)

            # Fire-and-forget: check for quarantine promotions
            _asyncio.create_task(
                _maybe_promote_quarantined(memory_store, task_type, outcome, summary)
            )

            return {"status": "ok", "event_type": event_type}
        except Exception as e:
            logger.error("Learning record failed: %s", e)
            return {"status": "error", "detail": str(e)}

    @app.get("/api/learnings/retrieve")
    async def retrieve_learnings(
        task_type: str = "",
        top_k: int = 3,
        min_score: float = 0.80,
        query: str = "",
    ):
        """Retrieve non-quarantined past learnings filtered by task type with score gating.

        Called by the proactive injection hook (Plan 02) to fetch relevant context
        before new tasks start.  No authentication required — local hook access only.

        Query parameters:
          task_type   — Required.  Only learnings matching this task type are returned.
                        Returns empty list when omitted or empty string.
          top_k       — Max number of results (default 3).
          min_score   — Minimum raw_score threshold (default 0.80, RETR-04 gate).
          query       — Optional embedding query text for semantic relevance.
                        Falls back to task_type when empty.

        Returns: {"results": [...], "total_tokens": int, "task_type": str}
        """
        if not task_type:
            return {"results": [], "total_tokens": 0, "task_type": ""}

        try:
            if memory_store is None:
                return {"results": [], "total_tokens": 0, "task_type": task_type}

            # Use the user's prompt for semantic matching; fall back to task_type string
            embed_query = query if query else task_type

            # Fetch extra results (top_k * 3) since we filter post-hoc
            raw_results = await memory_store.semantic_search(
                query=embed_query,
                top_k=top_k * 3,
                task_type=task_type,
                lifecycle_aware=True,
            )

            # Apply score gate (RETR-04) and quarantine gate
            filtered = []
            for r in raw_results:
                raw = r.get("raw_score", r.get("score", 0))
                if raw < min_score:
                    continue
                if r.get("metadata", {}).get("quarantined") is True:
                    continue
                filtered.append(r)

            # Take first top_k results
            filtered = filtered[:top_k]

            # Apply token cap: max 500 tokens (approximated as whitespace-split words)
            _TOKEN_CAP = 500
            results_out = []
            total_tokens = 0
            for r in filtered:
                text = r.get("text", "")
                word_count = len(text.split())
                if total_tokens + word_count > _TOKEN_CAP:
                    # Truncate text to fit within remaining budget
                    remaining = _TOKEN_CAP - total_tokens
                    if remaining > 0:
                        text = " ".join(text.split()[:remaining])
                        word_count = remaining
                    else:
                        break
                total_tokens += word_count
                results_out.append(
                    {
                        "text": text,
                        "score": r.get("score", 0),
                        "raw_score": r.get("raw_score", r.get("score", 0)),
                        "task_type": r.get("metadata", {}).get("task_type", ""),
                        "outcome": r.get("metadata", {}).get("outcome", ""),
                    }
                )

            return {"results": results_out, "total_tokens": total_tokens, "task_type": task_type}

        except Exception:
            return {"results": [], "total_tokens": 0, "task_type": task_type}

    @app.post("/api/knowledge/learn")
    async def extract_knowledge(request: Request):
        """Extract structured learnings from session context via LLM.

        Called by knowledge-learn-worker.py (Stop hook background worker).
        No authentication required — local hook access only.

        Accepts: {session_summary, tools_used, files_modified, messages_context}
        Returns: {status, learnings: [{learning_type, category, title, content, confidence}]}
        """
        import asyncio as _asyncio_local

        try:
            data = await request.json()
            session_summary = data.get("session_summary", "")
            tools_used = data.get("tools_used", [])
            files_modified = data.get("files_modified", [])
            messages_context = data.get("messages_context", [])

            if not session_summary:
                return {"status": "skipped", "reason": "empty summary", "learnings": []}

            # Pydantic models defined inside the endpoint to avoid module-level import issues
            from typing import Literal

            from pydantic import BaseModel, Field

            class ExtractedLearning(BaseModel):
                learning_type: Literal[
                    "decision", "feedback", "pattern", "correction", "trivial"
                ] = Field(
                    description=(
                        "decision=architectural choice, feedback=user correction, "
                        "pattern=recurring approach, correction=error fix, trivial=skip"
                    )
                )
                category: str = Field(
                    description=(
                        "Category tag. Prefer one of: security, feature, refactor, deploy. "
                        "Suggest new if truly different."
                    )
                )
                title: str = Field(description="One-line summary of the learning (max 80 chars)")
                content: str = Field(
                    description="The durable learning — specific enough to be useful next session"
                )
                confidence: float = Field(
                    ge=0.5,
                    le=1.0,
                    description=(
                        "How clearly expressed: 0.9 for definitive decisions, "
                        "0.5 for vague patterns"
                    ),
                )

            class ExtractionResult(BaseModel):
                learnings: list[ExtractedLearning] = Field(
                    description="List of 0-5 learnings. Empty list if session was trivial."
                )

            # Build context from last 20 messages
            msg_text = ""
            for msg in messages_context[-20:]:
                role = msg.get("role", "unknown")
                content = msg.get("content", "")
                if isinstance(content, str) and content.strip():
                    msg_text += f"[{role}]: {content[:500]}\n"
                elif isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            msg_text += f"[{role}]: {block.get('text', '')[:500]}\n"

            prompt = f"""Analyze this development session and extract structured learnings.

Tools used: {", ".join(tools_used)}
Files modified: {", ".join(files_modified)}

Session summary:
{session_summary[:2000]}

Recent conversation context:
{msg_text[:4000]}

Extract 0-5 learnings. For each:
- learning_type: decision (architectural choice made), feedback (user correction), pattern (recurring approach), correction (error fix), trivial (not worth storing)
- category: security, feature, refactor, deploy, or suggest a new category
- title: one-line summary (max 80 chars)
- content: the durable learning — what should be remembered for future sessions
- confidence: 0.5 (vague) to 1.0 (definitive)

If the session was trivial or purely mechanical, return an empty list.
Focus on learnings that would help in future similar sessions."""

            def _sync_extract(prompt_text):
                try:
                    import instructor
                    from openai import OpenAI
                except ImportError:
                    return {"learnings": []}

                import os as _os

                # Use Agent42's own provider routing
                api_key = _os.environ.get("OPENROUTER_API_KEY", "") or _os.environ.get(
                    "GEMINI_API_KEY", ""
                )
                if not api_key:
                    api_key = _os.environ.get("OPENAI_API_KEY", "")
                    base_url = None
                else:
                    base_url = "https://openrouter.ai/api/v1"

                if not api_key:
                    return {"learnings": []}

                client_kwargs = {"api_key": api_key}
                if base_url:
                    client_kwargs["base_url"] = base_url

                client = instructor.from_openai(OpenAI(**client_kwargs), mode=instructor.Mode.JSON)
                result = client.chat.completions.create(
                    model=("google/gemini-2.0-flash-001" if base_url else "gpt-4o-mini"),
                    response_model=ExtractionResult,
                    max_retries=2,
                    messages=[{"role": "user", "content": prompt_text}],
                )
                return result.model_dump()

            try:
                extraction = await _asyncio_local.to_thread(_sync_extract, prompt)
            except Exception as e:
                logger.warning("Knowledge extraction failed: %s", e)
                return {"status": "error", "detail": str(e), "learnings": []}

            # Filter out trivial learnings before returning
            learnings = [
                lrn
                for lrn in extraction.get("learnings", [])
                if lrn.get("learning_type") != "trivial"
            ]
            return {"status": "ok", "learnings": learnings}

        except Exception as e:
            logger.warning("Knowledge extraction endpoint failed: %s", e)
            return {"status": "error", "detail": str(e), "learnings": []}

    @app.post("/api/ide/chat")
    async def ide_chat(req: ChatRequest, _user: str = Depends(get_current_user)):
        """Send a message to the AI provider and get a response.

        Uses Anthropic Messages API format. Compatible with:
        - Anthropic API (default)
        - Synthetic.new (Anthropic-compatible)
        - Any Anthropic-compatible provider
        """

        # Resolve provider settings
        api_key = req.api_key or _os.environ.get("ANTHROPIC_API_KEY", "")
        provider_url = req.provider_url or _os.environ.get(
            "ANTHROPIC_BASE_URL", "https://api.anthropic.com"
        )
        model = req.model or _os.environ.get("CHAT_MODEL", "claude-sonnet-4-5-20250514")

        if not api_key:
            raise HTTPException(
                400, "No API key configured. Set ANTHROPIC_API_KEY in Settings or provide api_key."
            )

        # Build messages
        messages = []
        for h in req.history[-20:]:  # Last 20 messages for context
            messages.append({"role": h.get("role", "user"), "content": h.get("content", "")})
        messages.append({"role": "user", "content": req.message})

        # Build system prompt with Agent42 context
        system_parts = [
            "You are an AI coding assistant integrated into Agent42 IDE.",
            "You have access to the user's workspace files and can help with coding, debugging, and project management.",
        ]
        if req.file_context:
            system_parts.append(f"\nCurrently open file:\n```\n{req.file_context[:3000]}\n```")

        # Load relevant memories if memory_store is available
        if memory_store:
            try:
                recall = memory_store.search(req.message, limit=3)
                if recall:
                    system_parts.append("\nRelevant memories from past work:")
                    for r in recall[:3]:
                        system_parts.append(f"- {r.get('content', r.get('text', ''))[:200]}")
            except Exception:
                pass

        system_prompt = "\n".join(system_parts)

        # Build tool definitions for the AI
        tools = []
        if tool_registry:
            for t in tool_registry.list_tools()[:15]:  # Limit to 15 most useful tools
                tool_def = {
                    "name": t["name"],
                    "description": t.get("description", "")[:200],
                    "input_schema": t.get("parameters", {"type": "object", "properties": {}}),
                }
                tools.append(tool_def)

        # Call AI provider
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        body = {
            "model": model,
            "max_tokens": 4096,
            "system": system_prompt,
            "messages": messages,
        }
        if tools:
            body["tools"] = tools

        try:
            async with _httpx.AsyncClient(timeout=120.0) as client:
                url = provider_url.rstrip("/") + "/v1/messages"
                resp = await client.post(url, headers=headers, json=body)

                if resp.status_code != 200:
                    error_text = resp.text[:500]
                    raise HTTPException(resp.status_code, f"AI provider error: {error_text}")

                data = resp.json()

                # Extract text response
                response_text = ""
                tool_calls = []
                for block in data.get("content", []):
                    if block.get("type") == "text":
                        response_text += block.get("text", "")
                    elif block.get("type") == "tool_use":
                        tool_calls.append(
                            {
                                "id": block.get("id"),
                                "name": block.get("name"),
                                "input": block.get("input", {}),
                            }
                        )

                # Execute tool calls if any
                tool_results = []
                for tc in tool_calls:
                    try:
                        tool = tool_registry.get(tc["name"]) if tool_registry else None
                        if tool:
                            result = await tool.execute(**tc["input"])
                            tool_results.append(
                                {
                                    "tool_call_id": tc["id"],
                                    "name": tc["name"],
                                    "result": result.output
                                    if hasattr(result, "output")
                                    else str(result),
                                }
                            )
                        else:
                            tool_results.append(
                                {
                                    "tool_call_id": tc["id"],
                                    "name": tc["name"],
                                    "result": f"Tool '{tc['name']}' not found",
                                }
                            )
                    except Exception as e:
                        tool_results.append(
                            {
                                "tool_call_id": tc["id"],
                                "name": tc["name"],
                                "result": f"Error: {e}",
                            }
                        )

                return {
                    "response": response_text,
                    "tool_calls": tool_calls,
                    "tool_results": tool_results,
                    "model": data.get("model", model),
                    "usage": data.get("usage", {}),
                }

        except _httpx.TimeoutException:
            raise HTTPException(504, "AI provider timed out")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(500, f"Chat error: {e}")

    @app.get("/api/ide/chat/config")
    async def ide_chat_config(_user: str = Depends(get_current_user)):
        """Return current chat provider configuration (no secrets)."""
        has_key = bool(_os.environ.get("ANTHROPIC_API_KEY", ""))
        provider_url = _os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
        model = _os.environ.get("CHAT_MODEL", "claude-sonnet-4-5-20250514")
        return {
            "has_api_key": has_key,
            "provider_url": provider_url,
            "model": model,
            "providers": [
                {"name": "Anthropic", "url": "https://api.anthropic.com"},
                {"name": "Synthetic", "url": "https://api.synthetic.new/v1"},
                {"name": "OpenRouter", "url": "https://openrouter.ai/api/v1"},
            ],
        }

    # -- Agents (Custom AI Agent Management) -----------------------------------

    from core.agent_manager import AGENT_TEMPLATES, PROVIDER_MODELS, AgentManager
    from core.agent_runtime import AgentRuntime

    _agent_manager = agent_manager or AgentManager(workspace / ".agent42" / "agents")
    # NOTE: agent_manager passed from agent42.py when available (Phase 2+).
    # Fallback preserves backward compatibility for headless/test usage.
    _effectiveness_store = effectiveness_store  # may be None in tests/headless usage
    _agent_runtime = AgentRuntime(workspace)

    class AgentCreateRequest(BaseModel):
        name: str = ""
        description: str = ""
        template: str = ""
        tools: list = []
        skills: list = []
        provider: str = "anthropic"
        provider_url: str = ""
        model: str = "claude-sonnet-4-6"
        schedule: str = "manual"
        memory_scope: str = "global"
        max_iterations: int = 10
        approval_required: bool = False

    class AgentUpdateRequest(BaseModel):
        name: str | None = None
        description: str | None = None
        tools: list | None = None
        skills: list | None = None
        provider: str | None = None
        provider_url: str | None = None
        model: str | None = None
        schedule: str | None = None
        memory_scope: str | None = None
        max_iterations: int | None = None
        approval_required: bool | None = None
        status: str | None = None

    @app.get("/api/agents")
    async def list_agents(_user: str = Depends(get_current_user)):
        return [a.to_dict() for a in _agent_manager.list_all()]

    @app.get("/api/agents/templates")
    async def list_agent_templates(_user: str = Depends(get_current_user)):
        return AGENT_TEMPLATES

    @app.get("/api/agents/models")
    async def list_provider_models(_user: str = Depends(get_current_user)):
        """Return available models per provider for agent configuration."""
        return PROVIDER_MODELS

    @app.post("/api/agents")
    async def create_agent(req: AgentCreateRequest, _user: str = Depends(get_current_user)):
        data = req.model_dump(exclude_none=True)
        agent = _agent_manager.create(**data)
        return agent.to_dict()

    @app.get("/api/agents/{agent_id}")
    async def get_agent(agent_id: str, _user: str = Depends(get_current_user)):
        agent = _agent_manager.get(agent_id)
        if not agent:
            raise HTTPException(404, f"Agent not found: {agent_id}")
        return agent.to_dict()

    @app.patch("/api/agents/{agent_id}")
    async def update_agent(
        agent_id: str, req: AgentUpdateRequest, _user: str = Depends(get_current_user)
    ):
        data = {k: v for k, v in req.model_dump().items() if v is not None}
        agent = _agent_manager.update(agent_id, **data)
        if not agent:
            raise HTTPException(404, f"Agent not found: {agent_id}")
        return agent.to_dict()

    @app.delete("/api/agents/{agent_id}")
    async def delete_agent(agent_id: str, _user: str = Depends(get_current_user)):
        if not _agent_manager.delete(agent_id):
            raise HTTPException(404, f"Agent not found: {agent_id}")
        return {"status": "deleted"}

    @app.post("/api/agents/{agent_id}/start")
    async def start_agent(agent_id: str, _user: str = Depends(get_current_user)):
        agent = _agent_manager.get(agent_id)
        if not agent:
            raise HTTPException(404, f"Agent not found: {agent_id}")

        # Acquire concurrency semaphore for this agent's tier (RSRC-03).
        # Returns None when rewards disabled or tier is empty/provisional — no cap (D-09).
        tier = agent.effective_tier()
        sem = _agent_manager._get_tier_semaphore(tier)
        if sem is not None:
            try:
                await asyncio.wait_for(sem.acquire(), timeout=0.0)
            except TimeoutError:
                raise HTTPException(
                    503,
                    f"Tier '{tier}' concurrent task limit reached. Try again later.",
                )

        # Launch the agent process
        result = await _agent_runtime.start_agent(agent.to_dict())
        if not result:
            if sem is not None:
                sem.release()
            raise HTTPException(500, "Failed to start agent — is Claude Code CLI installed?")
        _agent_manager.set_status(agent_id, "active")
        _agent_manager.record_run(agent_id)
        if sem is not None:
            sem.release()
        return {**agent.to_dict(), "pid": result.pid, "status": "active"}

    @app.post("/api/agents/{agent_id}/stop")
    async def stop_agent(agent_id: str, _user: str = Depends(get_current_user)):
        agent = _agent_manager.get(agent_id)
        if not agent:
            raise HTTPException(404, f"Agent not found: {agent_id}")
        await _agent_runtime.stop_agent(agent_id)
        _agent_manager.set_status(agent_id, "stopped")
        return agent.to_dict()

    @app.get("/api/agents/{agent_id}/status")
    async def agent_runtime_status(agent_id: str, _user: str = Depends(get_current_user)):
        """Get real-time status of a running agent process."""
        status = _agent_runtime.get_status(agent_id)
        if not status:
            return {"agent_id": agent_id, "status": "not_running"}
        return status

    @app.get("/api/agents/{agent_id}/log")
    async def agent_log(agent_id: str, _user: str = Depends(get_current_user)):
        """Get the full log output of an agent run."""
        log = _agent_runtime.get_log(agent_id)
        return {"agent_id": agent_id, "log": log}

    @app.get("/api/agents/running")
    async def list_running_agents(_user: str = Depends(get_current_user)):
        """List all currently running agent processes."""
        return _agent_runtime.list_running()

    # -- Rewards API (Phase 4) — only when agent_manager + reward_system present --

    if agent_manager and reward_system:

        class RewardsToggleRequest(BaseModel):
            enabled: bool

        class TierOverrideRequest(BaseModel):
            tier: str
            expires_at: str | None = None

        @app.get("/api/rewards")
        async def get_rewards_status(_user: str = Depends(get_current_user)):
            """Return rewards system status including enabled flag, config, and tier counts."""
            from core.rewards_config import RewardsConfig

            cfg = RewardsConfig.load()
            agents = _agent_manager.list_all()
            tier_counts = {"bronze": 0, "silver": 0, "gold": 0, "provisional": 0}
            for a in agents:
                t = (a.effective_tier() or "provisional").lower()
                if t in tier_counts:
                    tier_counts[t] += 1
            return {
                "enabled": cfg.enabled,
                "startup_enabled": settings.rewards_enabled,
                "config": {
                    "silver_threshold": cfg.silver_threshold,
                    "gold_threshold": cfg.gold_threshold,
                },
                "tier_counts": tier_counts,
            }

        @app.post("/api/rewards/toggle")
        async def toggle_rewards(
            req: RewardsToggleRequest,
            _admin: AuthContext = Depends(require_admin),
        ):
            """Enable or disable the rewards system at runtime without a server restart."""
            from core.rewards_config import RewardsConfig

            cfg = RewardsConfig.load()
            updated = RewardsConfig(
                enabled=req.enabled,
                silver_threshold=cfg.silver_threshold,
                gold_threshold=cfg.gold_threshold,
            )
            updated.save()
            return {"enabled": req.enabled}

        @app.get("/api/agents/{agent_id}/performance")
        async def agent_performance(agent_id: str, _user: str = Depends(get_current_user)):
            """Return performance metrics for a specific agent."""
            agent = _agent_manager.get(agent_id)
            if not agent:
                raise HTTPException(status_code=404, detail="Agent not found")
            stats = (
                await _effectiveness_store.get_agent_stats(agent_id)
                if _effectiveness_store
                else None
            )
            return {
                "agent_id": agent_id,
                "tier": agent.effective_tier(),
                "performance_score": agent.performance_score or 0.0,
                "task_count": stats["task_volume"] if stats else 0,
                "success_rate": stats["success_rate"] if stats else 0.0,
            }

        @app.patch("/api/agents/{agent_id}/reward-tier")
        async def set_reward_tier(
            agent_id: str,
            req: TierOverrideRequest,
            _admin: AuthContext = Depends(require_admin),
        ):
            """Set a tier override for a specific agent (admin only)."""
            valid_tiers = {"bronze", "silver", "gold", "provisional", ""}
            if req.tier.lower() not in valid_tiers:
                raise HTTPException(status_code=422, detail=f"Invalid tier: {req.tier}")
            override = req.tier if req.tier else None
            agent = _agent_manager.update(agent_id, tier_override=override)
            if not agent:
                raise HTTPException(status_code=404, detail="Agent not found")
            await ws_manager.broadcast(
                "tier_update",
                {
                    "agents": [
                        {
                            "agent_id": agent_id,
                            "tier": agent.effective_tier(),
                            "score": agent.performance_score or 0.0,
                        }
                    ]
                },
            )
            return {"agent_id": agent_id, "tier_override": override}

        @app.post("/api/admin/rewards/recalculate-all", status_code=202)
        async def recalculate_all(_admin: AuthContext = Depends(require_admin)):
            """Trigger an immediate tier recalculation for all agents (admin only)."""
            import asyncio

            asyncio.create_task(reward_system._run_recalculation())
            return {"status": "queued"}

    # -- Approvals -------------------------------------------------------------

    @app.get("/api/approvals")
    async def list_approvals(_user: str = Depends(get_current_user)):
        if approval_gate is None:
            return []
        return approval_gate.pending_requests()

    @app.post("/api/approvals")
    async def handle_approval(req: ApprovalAction, _user: str = Depends(get_current_user)):
        if approval_gate is None:
            raise HTTPException(501, "Approval gate not configured")
        if req.approved:
            approval_gate.approve(req.task_id, req.action, user=_user)
        else:
            approval_gate.deny(req.task_id, req.action, user=_user)
        return {"status": "ok"}

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
        return {
            "providers": [],
            "models": [],
            "note": "Provider registry removed in v2.0 MCP pivot",
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

        policy = os.getenv("MODEL_ROUTING_POLICY", "balanced")
        return {"policy": policy, "account": None, "paid_models_registered": 0}

    @app.get("/api/models/health")
    async def get_model_health(_: AuthContext = Depends(require_admin)):
        """Return model health check results, provider health, and summary."""
        return {"summary": {}, "models": {}, "providers": {}}

    @app.post("/api/models/health-check")
    async def trigger_health_check(_: AuthContext = Depends(require_admin)):
        """Manually trigger a model health check."""

        return {"error": "Model catalog removed in v3.0"}

    @app.get("/api/settings/rlm-status")
    async def get_rlm_status(_: AuthContext = Depends(require_admin)):
        """Return RLM (Recursive Language Model) status and configuration."""
        return {"enabled": False, "note": "RLM provider removed in v2.0 MCP pivot"}

    def _load_cc_sync_status() -> dict:
        """Load CC memory sync status from .agent42/cc-sync-status.json."""
        try:
            import json as _json

            status_path = Path(settings.workspace or ".") / ".agent42" / "cc-sync-status.json"
            if status_path.exists():
                return _json.loads(status_path.read_text())
        except Exception:
            pass
        return {"last_sync": None, "total_synced": 0, "last_error": None}

    def _load_consolidation_status() -> dict:
        """Load memory consolidation status from .agent42/consolidation-status.json."""
        try:
            import json as _json

            status_path = Path(settings.workspace or ".") / ".agent42" / "consolidation-status.json"
            if status_path.exists():
                return _json.loads(status_path.read_text())
        except Exception:
            pass
        return {
            "last_run": None,
            "entries_since": 0,
            "last_scanned": 0,
            "last_removed": 0,
            "last_flagged": 0,
            "last_error": None,
        }

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

        # Compute effective operational mode: what is *actually* working right
        # now, not just what is configured.  When Qdrant is configured but
        # unreachable the system silently degrades to file/Redis-only — the
        # dashboard should communicate that honestly.
        qdrant_operational = qdrant_status in ("connected", "embedded_ok")
        redis_operational = redis_status == "connected"

        if qdrant_operational and redis_operational:
            effective_mode = "qdrant_redis"
        elif qdrant_operational and not redis_operational:
            effective_mode = "qdrant_embedded" if not qdrant_url else "qdrant_server"
        elif not qdrant_operational and redis_operational:
            effective_mode = "redis_only"
        else:
            effective_mode = "file"

        cc_status = _load_cc_sync_status()
        consolidation_status = _load_consolidation_status()
        return {
            "mode": effective_mode,
            "configured_mode": mode,
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
            "cc_sync": {
                "last_sync": cc_status.get("last_sync"),
                "total_synced": cc_status.get("total_synced", 0),
                "last_error": cc_status.get("last_error"),
            },
            "consolidation": {
                "last_run": consolidation_status.get("last_run"),
                "entries_since": consolidation_status.get("entries_since", 0),
                "last_scanned": consolidation_status.get("last_scanned", 0),
                "last_removed": consolidation_status.get("last_removed", 0),
                "last_flagged": consolidation_status.get("last_flagged", 0),
                "last_error": consolidation_status.get("last_error"),
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

    @app.post("/api/consolidate/trigger")
    async def trigger_consolidation(_admin: AuthContext = Depends(require_admin)):
        """Manually trigger memory dedup consolidation.

        Requires admin auth. Runs synchronously and returns stats.
        """
        try:
            # Check if Qdrant is available via the app's memory store
            memory_store = getattr(app.state, "memory_store", None)
            qdrant = getattr(memory_store, "_qdrant", None) if memory_store else None

            if not qdrant or not qdrant.is_available:
                return {"success": False, "error": "Qdrant is not available"}

            from memory.consolidation_worker import run_consolidation

            result = await asyncio.to_thread(run_consolidation, qdrant)
            return {"success": True, **result}
        except Exception as e:
            logger.error("Manual consolidation trigger failed: %s", e)
            return {"success": False, "error": str(e)}

    # -- Channels (Phase 2) ---------------------------------------------------

    @app.get("/api/channels")
    async def list_channels(_user: str = Depends(get_current_user)):
        if channel_manager:
            return channel_manager.list_channels()
        return []

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
            raise HTTPException(
                status_code=410,
                detail="Task queue removed in v3.0. Use MCP tools instead.",
            )

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
            """Create a new app."""
            new_app = await app_manager.create(
                name=req.name,
                description=req.description,
                runtime=req.runtime,
                tags=req.tags,
                app_mode=req.app_mode,
                git_enabled=req.git_enabled,
            )
            return {
                "app": new_app.to_dict(),
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
            """Request changes to an existing app."""
            raise HTTPException(
                status_code=410,
                detail="Task queue removed in v3.0. Use MCP tools instead.",
            )

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

        async def _proxy_to_app(slug: str, path: str, request: Request):
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

    # Expose activity feed helper so agent42.py can record events via ws_manager
    if ws_manager:
        ws_manager.record_activity = _record_activity  # type: ignore[attr-defined]

    return app
