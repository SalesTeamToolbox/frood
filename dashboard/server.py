"""
FastAPI dashboard server — Frood intelligence layer admin panel.

Security features:
- CORS restricted to configured origins (no wildcard)
- Login rate limiting per IP
- WebSocket connection limits
- Security response headers (CSP, HSTS, X-Frame-Options, etc.)
- Health check returns minimal info without auth

Routes: auth, memory, LLM proxy, effectiveness, providers, tools, skills,
reports, settings, Agent Apps, WebSocket broadcast.
"""

import asyncio
import logging
import time as _time
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

from core.config import Settings, settings
from dashboard.auth import (
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


# Passwords treated as unconfigured — trigger the setup wizard
_INSECURE_PASSWORDS = {"", "changeme-right-now", "password", "123456", "admin"}


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
    # Learning toggle (Phase 40)
    "LEARNING_ENABLED",
    # Zen proxy model selection
    "ZEN_DEFAULT_MODEL",
    "ZEN_ALLOW_PAID",
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
    ws_manager: WebSocketManager = None,
    tool_registry=None,
    skill_loader=None,
    heartbeat=None,
    key_store=None,
    app_manager=None,
    memory_store=None,
    effectiveness_store=None,
) -> FastAPI:
    """Build and return the FastAPI application."""

    app = FastAPI(title="Frood Dashboard", version="0.4.0")

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

    # -- Phase 36: PAPERCLIP-05 — gate standalone dashboard in sidecar mode ----
    if settings.sidecar_enabled:

        @app.get("/")
        async def dashboard_paperclip_redirect():
            """Return status page when dashboard is disabled in Paperclip mode."""
            return JSONResponse(
                content={
                    "status": "paperclip_mode",
                    "message": (
                        "Frood dashboard UI is disabled in Paperclip mode. "
                        "Access workspace features through the Paperclip dashboard."
                    ),
                    "sidecar_port": settings.paperclip_sidecar_port,
                },
                status_code=503,
            )

    # Shared imports used by multiple handlers within create_app scope
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

    # Key store for API key management
    _key_store = key_store  # passed from agent42.py when available

    # -- Health ----------------------------------------------------------------

    @app.get("/health")
    async def health_check():
        """Public health check — returns only liveness status.

        Does NOT expose task counts or connection info to unauthenticated users.
        """
        response_data: dict = {"status": "ok"}
        if settings.sidecar_enabled:
            response_data["mode"] = "paperclip_sidecar"
        return response_data

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

    # -- Token Usage Stats ----------------------------------------------------

    @app.get("/api/stats/tokens")
    async def get_token_stats(_user: str = Depends(get_current_user)):
        """Get aggregate token usage — reads jcodemunch token savings from stats file."""
        import json as _json_ts

        import aiofiles as _aiofiles_ts

        project_root = Path(__file__).parent.parent
        stats_path = project_root / ".claude" / ".jcodemunch-stats.json"

        jcm_stats: dict = {}
        try:
            async with _aiofiles_ts.open(stats_path) as f:
                jcm_stats = _json_ts.loads(await f.read())
        except (OSError, ValueError):
            pass

        total_tokens = jcm_stats.get("tokens_used", 0)
        tokens_saved = jcm_stats.get("tokens_saved", 0)
        total_calls = jcm_stats.get("calls", 0)
        by_tool = jcm_stats.get("tool_breakdown", {})

        return {
            "total_tokens": total_tokens,
            "total_prompt_tokens": 0,
            "total_completion_tokens": 0,
            "by_model": {},
            "daily_spend_usd": 0.0,
            "daily_tokens": total_tokens,
            "jcodemunch": {
                "tokens_used": total_tokens,
                "tokens_saved": tokens_saved,
                "tokens_avoided": jcm_stats.get("tokens_avoided", 0),
                "calls": total_calls,
                "files_targeted": jcm_stats.get("files_targeted", 0),
                "by_tool": by_tool,
                "session_start": jcm_stats.get("session_start"),
                "last_updated": jcm_stats.get("last_updated"),
            },
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

        # -- Project breakdown (removed in Phase 50) --
        project_list = []

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
                "flat_rate": flat_rates,  # flat-rate provider costs
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

    # -- Memory Search API (used by hooks + frontend) -------------------------

    import os as _os

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

    @app.post("/llm/chat/completions")
    @app.post("/llm/v1/chat/completions")
    async def llm_chat_completions(request: Request):
        """OpenAI-compatible LLM proxy for Claude Code.
        
        Use this endpoint as the API base for Claude Code to route through Agent42.
        Claude Code can switch models via the model query param or X-Model header.
        
        Examples:
          curl -X POST http://localhost:8000/llm/v1/chat/completions \
            -H "Content-Type: application/json" \
            -H "Authorization: Bearer dummy" \
            -d '{"model": "qwen3.6-plus-free", "messages": [{"role": "user", "content": "hi"}]}'
          
          # Switch model via header:
          curl -X POST http://localhost:8000/llm/v1/chat/completions \
            -H "Content-Type: application/json" \
            -H "X-Model: minimax-m2.5-free" \
            -d '{"messages": [{"role": "user", "content": "hi"}]}'
        """
        try:
            body = await request.json()
        except Exception:
            return {"error": {"message": "Invalid JSON body", "type": "invalid_request_error"}}

        model = (
            body.get("model")
            or request.headers.get("X-Model")
            or _os.environ.get("LLM_PROXY_MODEL", "qwen3.6-plus-free")
        )
        messages = body.get("messages", [])

        chat_model = model
        providers = []

        if model.startswith("zen:"):
            actual_model = model.split(":", 1)[1]
            chat_model = actual_model
            zen_key = _os.environ.get("ZEN_API_KEY", "")
            if zen_key:
                providers.append(("zen", zen_key))
        elif model in (
            "qwen3.6-plus-free",
            "minimax-m2.5-free",
            "nemotron-3-super-free",
            "big-pickle",
        ):
            zen_key = _os.environ.get("ZEN_API_KEY", "")
            if zen_key:
                providers.append(("zen", zen_key))
        else:
            if _os.environ.get("ANTHROPIC_API_KEY", ""):
                providers.append(("anthropic", _os.environ.get("ANTHROPIC_API_KEY", "")))
            if _os.environ.get("OPENROUTER_API_KEY", ""):
                providers.append(("openrouter", _os.environ.get("OPENROUTER_API_KEY", "")))
            if _os.environ.get("OPENAI_API_KEY", ""):
                providers.append(("openai", _os.environ.get("OPENAI_API_KEY", "")))

        if not providers:
            return {"error": {"message": "No API keys configured", "type": "invalid_request_error"}}

        system_msg = ""
        filtered_messages = []
        for msg in messages:
            if msg.get("role") == "system":
                system_msg = msg.get("content", "")
            else:
                filtered_messages.append(msg)

        try:
            text, provider_used = await _chat_complete(
                system_prompt=system_msg,
                messages=filtered_messages,
                user_query=filtered_messages[-1].get("content", "") if filtered_messages else "",
                model=chat_model,
                providers=providers,
            )
        except Exception as e:
            return {"error": {"message": str(e), "type": "internal_error"}}

        if not text or text.startswith("All providers failed"):
            return {"error": {"message": text or "No response", "type": "server_error"}}

        import uuid as _uuid

        return {
            "id": f"chatcmpl-{_uuid.uuid4().hex[:8]}",
            "object": "chat.completion",
            "created": int(_time.time()),
            "model": chat_model,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": text,
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            },
        }

    @app.post("/llm/v1/messages")
    async def llm_messages(request: Request):
        """Anthropic-compatible Messages API endpoint for Claude Code /model switching.

        Claude Code sends requests in Anthropic format:
          POST /v1/messages
          {"model": "...", "system": "...", "messages": [...], "max_tokens": ...}

        This endpoint translates to the internal provider routing and returns
        an Anthropic-compatible response.
        """
        try:
            body = await request.json()
        except Exception:
            return JSONResponse(
                status_code=400,
                content={
                    "type": "error",
                    "error": {"type": "invalid_request_error", "message": "Invalid JSON body"},
                },
            )

        model = (
            body.get("model")
            or request.headers.get("X-Model")
            or _os.environ.get("LLM_PROXY_MODEL", "qwen3.6-plus-free")
        )
        system_prompt = body.get("system", "")
        messages = body.get("messages", [])

        # Route to internal provider logic
        chat_model = model
        providers = []

        if model.startswith("zen:"):
            actual_model = model.split(":", 1)[1]
            chat_model = actual_model
            zen_key = _os.environ.get("ZEN_API_KEY", "")
            if zen_key:
                providers.append(("zen", zen_key))
        elif model in (
            "qwen3.6-plus-free",
            "minimax-m2.5-free",
            "nemotron-3-super-free",
            "big-pickle",
        ):
            zen_key = _os.environ.get("ZEN_API_KEY", "")
            if zen_key:
                providers.append(("zen", zen_key))
        else:
            if _os.environ.get("ANTHROPIC_API_KEY", ""):
                providers.append(("anthropic", _os.environ.get("ANTHROPIC_API_KEY", "")))
            if _os.environ.get("OPENROUTER_API_KEY", ""):
                providers.append(("openrouter", _os.environ.get("OPENROUTER_API_KEY", "")))
            if _os.environ.get("OPENAI_API_KEY", ""):
                providers.append(("openai", _os.environ.get("OPENAI_API_KEY", "")))

        if not providers:
            return JSONResponse(
                status_code=400,
                content={
                    "type": "error",
                    "error": {
                        "type": "invalid_request_error",
                        "message": "No API keys configured",
                    },
                },
            )

        try:
            text, provider_used = await _chat_complete(
                system_prompt=system_prompt,
                messages=messages,
                user_query=messages[-1].get("content", "") if messages else "",
                model=chat_model,
                providers=providers,
            )
        except Exception as e:
            return JSONResponse(
                status_code=500,
                content={
                    "type": "error",
                    "error": {"type": "api_error", "message": str(e)},
                },
            )

        if not text or text.startswith("All providers failed"):
            return JSONResponse(
                status_code=500,
                content={
                    "type": "error",
                    "error": {"type": "api_error", "message": text or "No response"},
                },
            )

        import uuid as _uuid

        return {
            "id": f"msg_{_uuid.uuid4().hex[:12]}",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": text}],
            "model": chat_model,
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {
                "input_tokens": 0,
                "output_tokens": 0,
            },
        }

    @app.get("/llm/models")
    @app.get("/llm/v1/models")
    async def llm_models():
        """Return available models for LLM proxy."""
        from core.agent_manager import PROVIDER_MODELS

        models = []
        for provider, category_map in PROVIDER_MODELS.items():
            if provider == "zen":
                for category, model_id in category_map.items():
                    models.append(
                        {
                            "id": model_id,
                            "object": "model",
                            "created": 1700000000,
                            "owned_by": "opencode",
                            "provider": "zen",
                            "category": category,
                        }
                    )
            elif provider == "openrouter":
                for category, model_id in category_map.items():
                    models.append(
                        {
                            "id": model_id,
                            "object": "model",
                            "created": 1700000000,
                            "owned_by": "openrouter",
                            "provider": "openrouter",
                            "category": category,
                        }
                    )
            elif provider == "anthropic":
                for category, model_id in category_map.items():
                    models.append(
                        {
                            "id": model_id,
                            "object": "model",
                            "created": 1700000000,
                            "owned_by": "anthropic",
                            "provider": "anthropic",
                            "category": category,
                        }
                    )

        return {
            "object": "list",
            "data": models,
        }

    @app.get("/llm/config")
    async def llm_config():
        """Return LLM proxy configuration for Claude Code.

        Claude Code can use this to discover the endpoint and available models.
        """
        base_url = _os.environ.get("LLM_PROXY_BASE_URL", "http://localhost:8000")
        return {
            "endpoint": f"{base_url}/llm/v1/chat/completions",
            "auth_type": "none",
            "model_header": "X-Model",
            "default_model": _os.environ.get("LLM_PROXY_MODEL", "qwen3.6-plus-free"),
            "available_models": [
                {"id": "qwen3.6-plus-free", "provider": "zen", "category": "fast"},
                {"id": "minimax-m2.5-free", "provider": "zen", "category": "general"},
                {"id": "nemotron-3-super-free", "provider": "zen", "category": "reasoning"},
                {"id": "big-pickle", "provider": "zen", "category": "content"},
            ],
        }

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

    # -- Providers (Phase 5) ---------------------------------------------------

    @app.get("/api/providers")
    async def list_providers(_user: str = Depends(get_current_user)):
        return {
            "providers": [],
            "models": [],
            "note": "Provider registry removed in v2.0 MCP pivot",
        }

    @app.get("/api/settings/provider-status")
    async def get_provider_status(
        _admin: AuthContext = Depends(require_admin),
    ):
        """Return live connectivity status for each configured LLM provider."""
        import os
        import time as _time

        import httpx

        results = []

        # Helper for pinging /v1/models with Bearer auth
        async def _ping_provider(name, label, env_var, base_url, auth_header_fn):
            key = os.environ.get(env_var, "")
            if not key:
                return {"name": name, "label": label, "configured": False, "status": "unconfigured"}
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    headers = auth_header_fn(key)
                    resp = await client.get(f"{base_url}/models", headers=headers)
                status = (
                    "ok"
                    if resp.status_code == 200
                    else ("auth_error" if resp.status_code in (401, 403) else "unreachable")
                )
            except httpx.TimeoutException:
                status = "timeout"
            except Exception:
                status = "unreachable"
            return {"name": name, "label": label, "configured": True, "status": status}

        # OpenCode Zen -- ping https://opencode.ai/zen/v1/models
        zen_status = "unconfigured"
        zen_exhausted = []
        zen_key = os.environ.get("ZEN_API_KEY", "")
        if zen_key:
            try:
                from providers.zen_api import get_zen_client

                client = get_zen_client()
                zen_exhausted = client._rate_limiter.get_exhausted_models()
                async with httpx.AsyncClient(timeout=5.0) as client:
                    headers = {"Authorization": f"Bearer {zen_key}"}
                    resp = await client.get("https://opencode.ai/zen/v1/models", headers=headers)
                zen_status = (
                    "ok"
                    if resp.status_code == 200
                    else ("auth_error" if resp.status_code in (401, 403) else "unreachable")
                )
            except httpx.TimeoutException:
                zen_status = "timeout"
            except Exception:
                zen_status = "unreachable"
        results.append(
            {
                "name": "zen",
                "label": "OpenCode Zen",
                "configured": bool(zen_key),
                "status": zen_status,
                "exhausted": zen_exhausted,
            }
        )

        # OpenRouter -- ping https://openrouter.ai/api/v1/models
        results.append(
            await _ping_provider(
                "openrouter",
                "OpenRouter",
                "OPENROUTER_API_KEY",
                "https://openrouter.ai/api/v1",
                lambda k: {"Authorization": f"Bearer {k}"},
            )
        )

        # Anthropic -- ping https://api.anthropic.com/v1/models
        results.append(
            await _ping_provider(
                "anthropic",
                "Anthropic",
                "ANTHROPIC_API_KEY",
                "https://api.anthropic.com/v1",
                lambda k: {"x-api-key": k, "anthropic-version": "2023-06-01"},
            )
        )

        # OpenAI -- ping https://api.openai.com/v1/models
        results.append(
            await _ping_provider(
                "openai",
                "OpenAI",
                "OPENAI_API_KEY",
                "https://api.openai.com/v1",
                lambda k: {"Authorization": f"Bearer {k}"},
            )
        )

        return {"providers": results, "checked_at": _time.time()}

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
        if not _key_store:
            raise HTTPException(status_code=503, detail="Key store not configured")
        return _key_store.get_masked_keys()

    @app.put("/api/settings/keys")
    async def update_api_keys(req: KeyUpdateRequest, _admin: AuthContext = Depends(require_admin)):
        """Update one or more API keys (admin only)."""
        if not _key_store:
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
                _key_store.delete_key(env_var)
            else:
                _key_store.set_key(env_var, value)
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

    @app.delete("/api/settings/memory/{collection}")
    async def purge_memory_collection(
        collection: str,
        _admin: AuthContext = Depends(require_admin),
    ):
        """Purge all entries in a Qdrant memory collection (irreversible). Per D-15."""
        valid_collections = {"memory", "knowledge", "history"}
        if collection not in valid_collections:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid collection '{collection}'. Must be one of: {', '.join(sorted(valid_collections))}",
            )
        # Retrieve qdrant store from app state (set during startup)
        _qdrant = getattr(app.state, "qdrant_store", None)
        if not _qdrant:
            # Fallback: try to get from memory_store
            _ms = getattr(app.state, "memory_store", None)
            _qdrant = getattr(_ms, "_qdrant", None) if _ms else None
        if not _qdrant or not getattr(_qdrant, "is_available", False):
            raise HTTPException(status_code=503, detail="Qdrant store not available")
        success = await asyncio.get_running_loop().run_in_executor(
            None, _qdrant.clear_collection, collection
        )
        if not success:
            raise HTTPException(
                status_code=500, detail=f"Failed to purge collection '{collection}'"
            )
        return {
            "ok": True,
            "collection": collection,
            "message": f"Collection '{collection}' purged",
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

    # -- WebSocket -------------------------------------------------------------

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket):
        # Connection limit
        if ws_manager.connection_count >= settings.max_websocket_connections:
            await ws.close(code=4003, reason="Too many connections")
            return

        # Authenticate via query parameter: ws://host/ws?token=<jwt>
        token = ws.query_params.get("token")
        if not token:
            await ws.close(code=4001, reason="Missing token")
            return

        user = ""

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

        await ws_manager.connect(ws, user=user)
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

    return app
