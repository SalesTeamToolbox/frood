"""
Channel manager — lifecycle management for all chat platform channels.

Starts/stops channels, routes inbound messages to the agent pipeline,
and dispatches outbound responses back to the originating channel.
"""

import asyncio
import logging
from typing import Callable, Awaitable

from channels.base import BaseChannel, InboundMessage, OutboundMessage

logger = logging.getLogger("agent42.channels.manager")


class ChannelManager:
    """Manages the lifecycle and message routing for all channels."""

    def __init__(self):
        self._channels: dict[str, BaseChannel] = {}
        self._message_handler: Callable[[InboundMessage], Awaitable[OutboundMessage | None]] | None = None
        self._running = False

    def register(self, channel: BaseChannel):
        """Register a channel for management."""
        self._channels[channel.channel_type] = channel
        logger.info(f"Registered channel: {channel.channel_type}")

    def on_message(self, handler: Callable[[InboundMessage], Awaitable[OutboundMessage | None]]):
        """Set the message handler that processes inbound messages."""
        self._message_handler = handler

    async def start_all(self):
        """Start all registered channels and begin message routing."""
        self._running = True
        tasks = []

        for name, channel in self._channels.items():
            try:
                await channel.start()
                tasks.append(asyncio.create_task(self._route_messages(channel)))
                logger.info(f"Channel started: {name}")
            except Exception as e:
                logger.error(f"Failed to start channel {name}: {e}", exc_info=True)

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def stop_all(self):
        """Stop all registered channels."""
        self._running = False
        for name, channel in self._channels.items():
            try:
                await channel.stop()
                logger.info(f"Channel stopped: {name}")
            except Exception as e:
                logger.error(f"Error stopping channel {name}: {e}")

    async def send(self, message: OutboundMessage):
        """Send a message through the appropriate channel."""
        channel = self._channels.get(message.channel_type)
        if not channel:
            logger.error(f"No channel registered for type: {message.channel_type}")
            return
        await channel.send(message)

    async def _route_messages(self, channel: BaseChannel):
        """Route inbound messages from a channel to the handler."""
        while self._running:
            try:
                message = await asyncio.wait_for(channel.receive(), timeout=5.0)

                if self._message_handler:
                    response = await self._message_handler(message)
                    if response:
                        await channel.send(response)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(
                    f"Error routing message from {channel.channel_type}: {e}",
                    exc_info=True,
                )

    def list_channels(self) -> list[dict]:
        """List all registered channels and their status."""
        return [
            {
                "type": name,
                "running": channel._running,
                "allowed_users": channel._allowed_users,
            }
            for name, channel in self._channels.items()
        ]
