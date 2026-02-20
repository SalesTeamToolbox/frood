"""
Approval gate for protected operations.

Certain actions (sending email, git push, file deletion) require
explicit human approval through the dashboard before proceeding.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger("agent42.approval")


class ProtectedAction(str, Enum):
    GMAIL_SEND = "gmail_send"
    GIT_PUSH = "git_push"
    FILE_DELETE = "file_delete"
    EXTERNAL_API = "external_api"


@dataclass
class ApprovalRequest:
    task_id: str
    action: ProtectedAction
    description: str
    details: dict = field(default_factory=dict)
    approved: bool | None = None
    _event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)


class ApprovalGate:
    """Intercepts protected operations and waits for human approval."""

    def __init__(self, task_queue):
        self.task_queue = task_queue
        self._pending: dict[str, ApprovalRequest] = {}

    async def request(
        self,
        task_id: str,
        action: ProtectedAction,
        description: str,
        details: dict | None = None,
    ) -> bool:
        """Block until the user approves or denies the action."""
        req = ApprovalRequest(
            task_id=task_id,
            action=action,
            description=description,
            details=details or {},
        )
        key = f"{task_id}:{action.value}"
        self._pending[key] = req

        logger.info(f"Approval requested: {key} — {description}")
        await req._event.wait()

        self._pending.pop(key, None)
        return req.approved is True

    def approve(self, task_id: str, action: str):
        """Approve a pending request (called from dashboard)."""
        key = f"{task_id}:{action}"
        req = self._pending.get(key)
        if req:
            req.approved = True
            req._event.set()
            logger.info(f"Approved: {key}")

    def deny(self, task_id: str, action: str):
        """Deny a pending request (called from dashboard)."""
        key = f"{task_id}:{action}"
        req = self._pending.get(key)
        if req:
            req.approved = False
            req._event.set()
            logger.info(f"Denied: {key}")

    def pending_requests(self) -> list[dict]:
        """List all pending approval requests for the dashboard."""
        return [
            {
                "task_id": r.task_id,
                "action": r.action.value,
                "description": r.description,
                "details": r.details,
            }
            for r in self._pending.values()
        ]
