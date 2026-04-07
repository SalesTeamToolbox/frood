"""
WebSocket connection manager for real-time dashboard updates.
"""

import json
import logging
import time
from dataclasses import dataclass, field

from fastapi import WebSocket

logger = logging.getLogger("agent42.websocket")


@dataclass
class WSConnection:
    """A WebSocket connection with identity metadata."""

    ws: WebSocket
    user: str = ""  # authenticated username
    connected_at: float = field(default_factory=time.time)


class WebSocketManager:
    """Manages active WebSocket connections and broadcasts events."""

    def __init__(self):
        self._connections: list[WSConnection] = []
        self.chat_messages: list[dict] = []  # Shared chat history

    @property
    def connection_count(self) -> int:
        return len(self._connections)

    async def connect(
        self,
        ws: WebSocket,
        user: str = "",
    ):
        await ws.accept()
        conn = WSConnection(ws=ws, user=user)
        self._connections.append(conn)
        logger.info(f"WebSocket connected: user={user} ({self.connection_count} total)")

    def disconnect(self, ws: WebSocket):
        before = len(self._connections)
        self._connections = [c for c in self._connections if c.ws is not ws]
        if len(self._connections) < before:
            logger.info(f"WebSocket disconnected ({self.connection_count} total)")

    async def broadcast(self, event_type: str, data: dict):
        """Send an event to all connected clients."""
        message = json.dumps({"type": event_type, "data": data})
        dead: list[WSConnection] = []

        for conn in self._connections:
            try:
                await conn.ws.send_text(message)
            except Exception as e:
                logger.debug(f"WebSocket send failed (connection will be removed): {e}")
                dead.append(conn)

        for conn in dead:
            self._connections.remove(conn)
