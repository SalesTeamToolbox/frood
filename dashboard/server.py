"""
FastAPI dashboard server with REST API and WebSocket support.

Security features:
- CORS restricted to configured origins (no wildcard)
- Login rate limiting per IP
- WebSocket connection limits
- Security response headers (CSP, HSTS, X-Frame-Options, etc.)
- Health check returns minimal info without auth

Extended with endpoints for providers, tools, skills, and channels.
"""

import logging
from pathlib import Path

from fastapi import FastAPI, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

from core.config import settings
from core.task_queue import TaskQueue, Task, TaskType, TaskStatus
from core.approval_gate import ApprovalGate
from dashboard.auth import verify_password, create_token, get_current_user, check_rate_limit
from dashboard.websocket_manager import WebSocketManager

logger = logging.getLogger("agent42.server")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all HTTP responses."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self' ws: wss:; frame-ancestors 'none'"
        )
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=()"
        )
        # If serving over HTTPS, enable HSTS
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
        return response

FRONTEND_DIR = Path(__file__).parent / "frontend" / "dist"


class LoginRequest(BaseModel):
    username: str
    password: str


class TaskCreateRequest(BaseModel):
    title: str
    description: str
    task_type: str = "coding"
    priority: int = 0
    context_window: str = "default"


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


def create_app(
    task_queue: TaskQueue,
    ws_manager: WebSocketManager,
    approval_gate: ApprovalGate,
    tool_registry=None,
    skill_loader=None,
    channel_manager=None,
    learner=None,
) -> FastAPI:
    """Build and return the FastAPI application."""

    app = FastAPI(title="Agent42 Dashboard", version="0.3.0")

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
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

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
            logger.info(f"Failed login attempt for '{req.username}' from {client_ip}")
            raise HTTPException(status_code=401, detail="Invalid credentials")

        logger.info(f"Successful login for '{req.username}' from {client_ip}")
        return {"token": create_token(req.username)}

    # -- Tasks -----------------------------------------------------------------

    @app.get("/api/tasks")
    async def list_tasks(_user: str = Depends(get_current_user)):
        return [t.to_dict() for t in task_queue.all_tasks()]

    @app.post("/api/tasks")
    async def create_task(
        req: TaskCreateRequest, _user: str = Depends(get_current_user)
    ):
        task = Task(
            title=req.title,
            description=req.description,
            task_type=TaskType(req.task_type),
            priority=req.priority,
            context_window=req.context_window,
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
    async def move_task(
        task_id: str, req: TaskMoveRequest, _user: str = Depends(get_current_user)
    ):
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
        """Add a comment to a task thread."""
        task = task_queue.get(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        task.add_comment(req.author or _user, req.text)
        await task_queue._persist()
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

    # -- Activity Feed --------------------------------------------------------

    _activity_feed: list[dict] = []

    @app.get("/api/activity")
    async def get_activity(_user: str = Depends(get_current_user)):
        """Get recent activity feed (last 200 events)."""
        return _activity_feed[-200:]

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
    async def handle_approval(
        req: ApprovalAction, _user: str = Depends(get_current_user)
    ):
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
            learner.record_reviewer_feedback(
                task_id=task_id,
                task_title=task.title,
                feedback=req.feedback,
                approved=req.approved,
            )
        if req.approved:
            await task_queue.approve(task_id)
        return {"status": "feedback recorded", "approved": req.approved}

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
                }
                for s in skill_loader.all_skills()
            ]
        return []

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

        # Authenticate via query parameter: ws://host/ws?token=<jwt>
        token = ws.query_params.get("token")
        if not token:
            await ws.close(code=4001, reason="Missing token")
            return
        try:
            from jose import jwt as jose_jwt, JWTError, ExpiredSignatureError
            payload = jose_jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
            if not payload.get("sub"):
                await ws.close(code=4001, reason="Invalid token")
                return
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

        await ws_manager.connect(ws)
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

    # -- Static files (React frontend) ----------------------------------------

    if FRONTEND_DIR.exists():
        app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True))

    return app
