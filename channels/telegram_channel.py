"""
Telegram channel — bot polling integration.

Uses python-telegram-bot for async polling. Supports text messages,
replies, and document attachments.
"""

import asyncio
import logging

from channels.base import BaseChannel, InboundMessage, OutboundMessage

logger = logging.getLogger("agent42.channels.telegram")

try:
    from telegram import Update
    from telegram.ext import Application, ContextTypes, MessageHandler, filters

    HAS_TELEGRAM = True
except ImportError:
    HAS_TELEGRAM = False


class TelegramChannel(BaseChannel):
    """Telegram bot channel using polling."""

    def __init__(self, config: dict):
        super().__init__("telegram", config)
        self.token = config.get("bot_token", "")
        self._app: Application | None = None
        self._task: asyncio.Task | None = None

    async def start(self):
        if not HAS_TELEGRAM:
            raise ImportError(
                "python-telegram-bot is required for Telegram integration. "
                "Install with: pip install python-telegram-bot"
            )

        if not self.token:
            raise ValueError("Telegram bot_token is required")

        self._app = Application.builder().token(self.token).build()
        self._app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message))

        self._running = True
        await self._app.initialize()
        await self._app.start()
        self._task = asyncio.create_task(self._app.updater.start_polling())
        logger.info("Telegram channel started (polling)")

    async def stop(self):
        self._running = False
        if self._app:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
        logger.info("Telegram channel stopped")

    async def send(self, message: OutboundMessage):
        if not self._app:
            return

        # Validate and convert chat_id
        try:
            chat_id = int(message.channel_id)
        except (ValueError, OverflowError):
            logger.error(f"Invalid channel_id format: {message.channel_id!r}")
            return

        # Validate reply_to if present
        reply_to_id = None
        if message.reply_to:
            try:
                reply_to_id = int(message.reply_to)
            except (ValueError, OverflowError):
                logger.warning(f"Invalid reply_to format: {message.reply_to!r}, ignoring")

        # Split long messages (Telegram limit: 4096 chars)
        content = message.content
        while content:
            chunk = content[:4096]
            content = content[4096:]
            try:
                await self._app.bot.send_message(
                    chat_id=chat_id,
                    text=chunk,
                    reply_to_message_id=reply_to_id,
                )
            except Exception as e:
                logger.error(f"Failed to send Telegram message: {e}")
                return

    async def _handle_message(self, update: "Update", context: "ContextTypes.DEFAULT_TYPE"):
        """Process incoming Telegram messages."""
        msg = update.message
        if not msg or not msg.text:
            return

        inbound = InboundMessage(
            channel_type="telegram",
            channel_id=str(msg.chat_id),
            sender_id=str(msg.from_user.id) if msg.from_user else "",
            sender_name=msg.from_user.full_name if msg.from_user else "Unknown",
            content=msg.text,
            reply_to=str(msg.reply_to_message.message_id) if msg.reply_to_message else "",
            metadata={
                "message_id": str(msg.message_id),
                "chat_type": msg.chat.type,
                "chat_title": msg.chat.title or "",
            },
        )
        await self._enqueue(inbound)
