"""
Discord channel — bot integration using discord.py.

Connects to Discord via bot token and WebSocket gateway.
Supports text channels and direct messages.
"""

import asyncio
import logging

from channels.base import BaseChannel, InboundMessage, OutboundMessage

logger = logging.getLogger("agent42.channels.discord")

try:
    import discord
    HAS_DISCORD = True
except ImportError:
    HAS_DISCORD = False


class DiscordChannel(BaseChannel):
    """Discord bot channel using discord.py."""

    def __init__(self, config: dict):
        super().__init__("discord", config)
        self.token = config.get("bot_token", "")
        self.guild_ids: list[int] = config.get("guild_ids", [])
        self._client: "discord.Client | None" = None
        self._task: asyncio.Task | None = None

    async def start(self):
        if not HAS_DISCORD:
            raise ImportError(
                "discord.py is required for Discord integration. "
                "Install with: pip install discord.py"
            )

        if not self.token:
            raise ValueError("Discord bot_token is required")

        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True

        self._client = discord.Client(intents=intents)
        self._setup_handlers()
        self._running = True

        # Run the bot in a background task
        self._task = asyncio.create_task(self._client.start(self.token))
        logger.info("Discord channel starting...")

    async def stop(self):
        self._running = False
        if self._client:
            await self._client.close()
        if self._task:
            self._task.cancel()
        logger.info("Discord channel stopped")

    async def send(self, message: OutboundMessage):
        if not self._client:
            return

        channel = self._client.get_channel(int(message.channel_id))
        if not channel:
            logger.error(f"Discord channel not found: {message.channel_id}")
            return

        # Split long messages (Discord has a 2000 char limit)
        content = message.content
        while content:
            chunk = content[:2000]
            content = content[2000:]
            await channel.send(chunk)

    def _setup_handlers(self):
        """Set up Discord event handlers."""

        @self._client.event
        async def on_ready():
            logger.info(f"Discord bot connected as {self._client.user}")

        @self._client.event
        async def on_message(msg: "discord.Message"):
            # Ignore bot's own messages
            if msg.author == self._client.user:
                return

            # Filter by guild if configured
            if self.guild_ids and msg.guild and msg.guild.id not in self.guild_ids:
                return

            inbound = InboundMessage(
                channel_type="discord",
                channel_id=str(msg.channel.id),
                sender_id=str(msg.author.id),
                sender_name=str(msg.author),
                content=msg.content,
                reply_to=str(msg.reference.message_id) if msg.reference else "",
                attachments=[a.url for a in msg.attachments],
                metadata={
                    "guild_id": str(msg.guild.id) if msg.guild else "",
                    "guild_name": msg.guild.name if msg.guild else "DM",
                    "message_id": str(msg.id),
                },
            )
            await self._enqueue(inbound)
