"""
FastAPI dashboard server with REST API and WebSocket support.

Extended with endpoints for providers, tools, skills, and channels.
"""

import logging
from pathlib import Path

from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core.task_queue import TaskQueue, Task, TaskType
from core.approval_gate import ApprovalGate
from dashboard.auth import verify_password, create_token, get_current_user
from dashboard.websocket_manager import WebSocketManager

logger = logging.getLogger("agent42.server")

FRONTEND_DIR = Path(__file__).parent / "frontend" / "dist"


class LoginRequest(BaseModel):
    username: str
    password: str


class TaskCreateRequest(BaseModel):
    title: str
    description: str
    task_type: str = "coding"


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

    app = FastAPI(title="Agent42 Dashboard", version="0.2.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # -- Auth ------------------------------------------------------------------

    @app.post("/api/login")
    async def login(req: LoginRequest):
        if req.username != "admin" or not verify_password(req.password):
            raise HTTPException(status_code=401, detail="Invalid credentials")
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

    # -- Approvals -------------------------------------------------------------

    @app.get("/api/approvals")
    async def list_approvals(_user: str = Depends(get_current_user)):
        return approval_gate.pending_requests()

    @app.post("/api/approvals")
    async def handle_approval(
        req: ApprovalAction, _user: str = Depends(get_current_user)
    ):
        if req.approved:
            approval_gate.approve(req.task_id, req.action)
        else:
            approval_gate.deny(req.task_id, req.action)
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
        await ws_manager.connect(ws)
        try:
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            ws_manager.disconnect(ws)

    # -- Static files (React frontend) ----------------------------------------

    if FRONTEND_DIR.exists():
        app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True))

    return app
