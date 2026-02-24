"""
Approval gate for protected operations.

Certain actions (sending email, git push, file deletion) require
explicit human approval through the dashboard before proceeding.

Approval decisions are persisted to a JSONL audit log so that:
1. All approval activity is recorded for compliance/auditing
2. The audit trail survives application restarts
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import aiofiles

logger = logging.getLogger("agent42.approval")


class ProtectedAction(str, Enum):
    GMAIL_SEND = "gmail_send"
    GIT_PUSH = "git_push"
    FILE_DELETE = "file_delete"
    EXTERNAL_API = "external_api"
    SSH_CONNECT = "ssh_connect"
    TUNNEL_START = "tunnel_start"


@dataclass
class ApprovalRequest:
    task_id: str
    action: ProtectedAction
    description: str
    details: dict = field(default_factory=dict)
    approved: bool | None = None
    requested_at: float = field(default_factory=time.time)
    _event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)


DEFAULT_TIMEOUT = 3600  # 1 hour default timeout for approval requests


class ApprovalGate:
    """Intercepts protected operations and waits for human approval.

    All approval events (request, approve, deny, timeout) are appended to a
    JSONL audit log for persistent record-keeping and compliance.
    """

    def __init__(
        self,
        task_queue,
        timeout: int = DEFAULT_TIMEOUT,
        log_path: str = ".agent42/approvals.jsonl",
    ):
        self.task_queue = task_queue
        self.timeout = timeout
        self._pending: dict[str, ApprovalRequest] = {}
        self._log_path = Path(log_path)
        self._log_path.parent.mkdir(parents=True, exist_ok=True)

    async def _log_event(self, event_type: str, key: str, **details):
        """Append an event to the JSONL audit log (non-blocking)."""
        entry = {
            "timestamp": time.time(),
            "event": event_type,
            "key": key,
            **details,
        }
        try:
            async with aiofiles.open(self._log_path, "a") as f:
                await f.write(json.dumps(entry, default=str) + "\n")
        except OSError as e:
            logger.error(f"Failed to write approval log: {e}")

    async def request(
        self,
        task_id: str,
        action: ProtectedAction,
        description: str,
        details: dict | None = None,
    ) -> bool:
        """Block until the user approves/denies or timeout expires (auto-deny)."""
        req = ApprovalRequest(
            task_id=task_id,
            action=action,
            description=description,
            details=details or {},
        )
        key = f"{task_id}:{action.value}"
        self._pending[key] = req

        logger.info(f"Approval requested: {key} — {description}")
        await self._log_event(
            "requested",
            key,
            task_id=task_id,
            action=action.value,
            description=description,
            details=details or {},
        )

        try:
            await asyncio.wait_for(req._event.wait(), timeout=self.timeout)
        except TimeoutError:
            logger.warning(f"Approval timed out after {self.timeout}s: {key} — auto-denying")
            req.approved = False
            await self._log_event("timeout", key, task_id=task_id, action=action.value)

        self._pending.pop(key, None)
        return req.approved is True

    def approve(self, task_id: str, action: str, user: str = ""):
        """Approve a pending request (called from dashboard)."""
        key = f"{task_id}:{action}"
        req = self._pending.get(key)
        if req:
            req.approved = True
            req._event.set()
            logger.info(f"AUDIT: Approved {key} by {user or 'unknown'}")
            asyncio.ensure_future(
                self._log_event(
                    "approved", key, task_id=task_id, action=action, user=user or "unknown"
                )
            )

    def deny(self, task_id: str, action: str, user: str = ""):
        """Deny a pending request (called from dashboard)."""
        key = f"{task_id}:{action}"
        req = self._pending.get(key)
        if req:
            req.approved = False
            req._event.set()
            logger.info(f"AUDIT: Denied {key} by {user or 'unknown'}")
            asyncio.ensure_future(
                self._log_event(
                    "denied", key, task_id=task_id, action=action, user=user or "unknown"
                )
            )

    def pending_requests(self) -> list[dict]:
        """List all pending approval requests for the dashboard."""
        return [
            {
                "task_id": r.task_id,
                "action": r.action.value,
                "description": r.description,
                "details": r.details,
                "requested_at": r.requested_at,
            }
            for r in self._pending.values()
        ]
