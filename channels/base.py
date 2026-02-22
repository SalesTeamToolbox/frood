"""
Channel abstraction layer — unified messaging gateway.

All chat platforms (Discord, Slack, Telegram, Email, etc.) implement BaseChannel
and communicate through normalized InboundMessage/OutboundMessage dataclasses.
"""

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

logger = logging.getLogger("agent42.channels")


@dataclass
class InboundMessage:
    """Normalized incoming message from any channel."""

    channel_type: str  # "discord", "slack", "telegram", "email", etc.
    channel_id: str  # Server/channel/chat identifier
    sender_id: str  # User identifier on the platform
    sender_name: str  # Display name
    content: str  # Message text
    timestamp: float = field(default_factory=time.time)
    reply_to: str = ""  # Message ID being replied to (if applicable)
    attachments: list[str] = field(default_factory=list)  # URLs or file paths
    metadata: dict = field(default_factory=dict)  # Platform-specific data


@dataclass
class OutboundMessage:
    """Normalized outgoing message to any channel."""

    channel_type: str
    channel_id: str
    content: str
    reply_to: str = ""
    attachments: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


class BaseChannel(ABC):
    """Abstract base class for all chat platform integrations."""

    def __init__(self, channel_type: str, config: dict):
        self.channel_type = channel_type
        self.config = config
        self._message_queue: asyncio.Queue[InboundMessage] = asyncio.Queue()
        self._running = False
        self._allowed_users: list[str] = config.get("allow_from", [])

    @abstractmethod
    async def start(self):
        """Connect to the platform and begin listening for messages."""
        ...

    @abstractmethod
    async def stop(self):
        """Disconnect from the platform gracefully."""
        ...

    @abstractmethod
    async def send(self, message: OutboundMessage):
        """Send a message to the platform."""
        ...

    def is_user_allowed(self, user_id: str) -> bool:
        """Check if a user is authorized. Empty allowlist = all allowed."""
        if not self._allowed_users:
            return True
        return user_id in self._allowed_users

    async def receive(self) -> InboundMessage:
        """Wait for and return the next inbound message."""
        return await self._message_queue.get()

    async def _enqueue(self, message: InboundMessage):
        """Add an inbound message to the queue (used by subclasses)."""
        if not self.is_user_allowed(message.sender_id):
            logger.warning(
                f"[{self.channel_type}] Blocked message from unauthorized user: {message.sender_id}"
            )
            return
        await self._message_queue.put(message)
