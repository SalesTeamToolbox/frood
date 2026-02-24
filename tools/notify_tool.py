"""
NotifyUserTool — real-time user notifications from running agents.

Inspired by Agent Zero's notify_user and input tools, this lets an agent
push progress updates and request mid-task feedback from the user via
WebSocket without creating a full approval gate.

Operations:
  notify   — push an info/warning/success/error message to the dashboard
  progress — report percentage completion (0-100) for the current task
  request_input — ask the user a question and wait for their response
"""

import asyncio
import logging
import time

from tools.base import Tool, ToolResult

logger = logging.getLogger("agent42.tools.notify")

# Global registry of pending input requests: task_id -> asyncio.Future
_pending_inputs: dict[str, asyncio.Future] = {}


def resolve_input(task_id: str, response: str) -> bool:
    """Called by the dashboard endpoint to resolve a pending input request.

    Returns True if there was a pending request, False otherwise.
    """
    future = _pending_inputs.get(task_id)
    if future and not future.done():
        future.set_result(response)
        return True
    return False


class NotifyUserTool(Tool):
    """Push real-time messages and request user input mid-task.

    The tool broadcasts WebSocket events to all connected dashboard clients.
    For request_input, it waits up to ``input_timeout_seconds`` for a reply
    before timing out with a descriptive message.
    """

    # Default timeout for user input requests (seconds)
    INPUT_TIMEOUT = 300  # 5 minutes

    def __init__(self, ws_manager=None, task_id: str = ""):
        """
        Args:
            ws_manager: WebSocketManager instance for broadcasting events.
                        If None, notifications are logged but not broadcast.
            task_id:    Current task ID (set per-agent run).
        """
        self._ws_manager = ws_manager
        self._task_id = task_id

    @property
    def name(self) -> str:
        return "notify_user"

    @property
    def description(self) -> str:
        return (
            "Send real-time notifications to the user during task execution. "
            "Use 'notify' to push status messages, 'progress' to report completion "
            "percentage, or 'request_input' to ask the user a question and wait "
            "for their response. This tool lets you communicate with the user "
            "mid-task without stopping execution."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["notify", "progress", "request_input"],
                    "description": (
                        "notify: push a message to the dashboard; "
                        "progress: update task completion percentage (0-100); "
                        "request_input: ask user a question and wait for answer"
                    ),
                },
                "message": {
                    "type": "string",
                    "description": "The message to display to the user (for notify operation).",
                },
                "level": {
                    "type": "string",
                    "enum": ["info", "warning", "success", "error"],
                    "description": "Severity level for the notification (default: info).",
                },
                "progress": {
                    "type": "integer",
                    "description": "Completion percentage 0-100 (for progress operation).",
                    "minimum": 0,
                    "maximum": 100,
                },
                "question": {
                    "type": "string",
                    "description": "The question to ask the user (for request_input operation).",
                },
            },
            "required": ["operation"],
        }

    async def execute(
        self,
        operation: str = "notify",
        message: str = "",
        level: str = "info",
        progress: int | None = None,
        question: str = "",
        task_id: str = "",
        **kwargs,
    ) -> ToolResult:
        # Use provided task_id, fall back to agent_id (injected by ToolRegistry), then instance default
        effective_task_id = task_id or kwargs.get("agent_id", "") or self._task_id

        if operation == "notify":
            return await self._handle_notify(effective_task_id, message, level)
        elif operation == "progress":
            return await self._handle_progress(effective_task_id, progress)
        elif operation == "request_input":
            return await self._handle_request_input(effective_task_id, question or message)
        else:
            return ToolResult(
                output=f"Unknown operation: {operation}. Use notify, progress, or request_input.",
                success=False,
            )

    async def _handle_notify(self, task_id: str, message: str, level: str) -> ToolResult:
        """Broadcast a notification message to all dashboard clients."""
        if not message:
            return ToolResult(output="No message provided for notify operation.", success=False)

        valid_levels = {"info", "warning", "success", "error"}
        if level not in valid_levels:
            level = "info"

        event_data = {
            "task_id": task_id,
            "level": level,
            "message": message,
            "timestamp": time.time(),
        }

        if self._ws_manager:
            await self._ws_manager.broadcast("agent_notification", event_data)

        logger.info(f"[{level.upper()}] Task {task_id}: {message}")
        return ToolResult(output=f"Notification sent ({level}): {message}")

    async def _handle_progress(self, task_id: str, progress: int | None) -> ToolResult:
        """Broadcast a progress update to all dashboard clients."""
        if progress is None:
            return ToolResult(output="No progress value provided.", success=False)

        progress = max(0, min(100, int(progress)))

        event_data = {
            "task_id": task_id,
            "progress": progress,
            "timestamp": time.time(),
        }

        if self._ws_manager:
            await self._ws_manager.broadcast("agent_progress", event_data)

        logger.info(f"Task {task_id} progress: {progress}%")
        return ToolResult(output=f"Progress updated: {progress}%")

    async def _handle_request_input(self, task_id: str, question: str) -> ToolResult:
        """Ask the user a question and wait for their response."""
        if not question:
            return ToolResult(
                output="No question provided for request_input operation.", success=False
            )

        # Create a Future for this request
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()

        # Register the pending request
        _pending_inputs[task_id] = future

        event_data = {
            "task_id": task_id,
            "question": question,
            "timestamp": time.time(),
        }

        if self._ws_manager:
            await self._ws_manager.broadcast("agent_input_request", event_data)

        logger.info(f"Task {task_id} requesting user input: {question}")

        try:
            response = await asyncio.wait_for(future, timeout=self.INPUT_TIMEOUT)
            return ToolResult(output=f"User response: {response}")
        except TimeoutError:
            return ToolResult(
                output=(
                    f"No response received within {self.INPUT_TIMEOUT // 60} minutes. "
                    "Continuing without user input."
                ),
                success=True,  # Not a hard failure — agent can continue
            )
        finally:
            _pending_inputs.pop(task_id, None)
