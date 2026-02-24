"""
WebSocket connection manager for real-time dashboard updates.

Tracks device identity per connection so that events can be sent to
specific devices and the dashboard can show online/offline status.
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
    user: str = ""  # username (JWT) or "device" (API key)
    device_id: str = ""  # non-empty for API-key-authenticated devices
    device_name: str = ""
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
        device_id: str = "",
        device_name: str = "",
    ):
        await ws.accept()
        conn = WSConnection(
            ws=ws,
            user=user,
            device_id=device_id,
            device_name=device_name,
        )
        self._connections.append(conn)
        logger.info(
            f"WebSocket connected: user={user} device={device_id or 'n/a'} "
            f"({self.connection_count} total)"
        )

    def disconnect(self, ws: WebSocket):
        before = len(self._connections)
        self._connections = [c for c in self._connections if c.ws is not ws]
        if len(self._connections) < before:
            logger.info(f"WebSocket disconnected ({self.connection_count} total)")

    def connected_device_ids(self) -> set[str]:
        """Return IDs of currently connected devices."""
        return {c.device_id for c in self._connections if c.device_id}

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

    async def send_to_device(self, device_id: str, event_type: str, data: dict):
        """Send an event to a specific device by ID."""
        message = json.dumps({"type": event_type, "data": data})
        dead: list[WSConnection] = []

        for conn in self._connections:
            if conn.device_id == device_id:
                try:
                    await conn.ws.send_text(message)
                except Exception as e:
                    logger.debug(
                        f"WebSocket send failed for device {device_id} (connection will be removed): {e}"
                    )
                    dead.append(conn)

        for conn in dead:
            self._connections.remove(conn)
