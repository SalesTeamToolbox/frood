"""
Slack channel — Socket Mode integration using slack-sdk.

Connects via Socket Mode (no public URL needed) and handles
messages, threads, and markdown formatting.
"""

import logging

from channels.base import BaseChannel, InboundMessage, OutboundMessage

logger = logging.getLogger("agent42.channels.slack")

try:
    from slack_sdk.socket_mode.aiohttp import SocketModeClient
    from slack_sdk.socket_mode.request import SocketModeRequest
    from slack_sdk.socket_mode.response import SocketModeResponse
    from slack_sdk.web.async_client import AsyncWebClient

    HAS_SLACK = True
except ImportError:
    HAS_SLACK = False


class SlackChannel(BaseChannel):
    """Slack channel using Socket Mode (no public URL needed)."""

    def __init__(self, config: dict):
        super().__init__("slack", config)
        self.bot_token = config.get("bot_token", "")
        self.app_token = config.get("app_token", "")  # xapp- token for Socket Mode
        self._socket_client = None
        self._web_client = None
        self._bot_user_id = ""

    async def start(self):
        if not HAS_SLACK:
            raise ImportError(
                "slack-sdk is required for Slack integration. "
                "Install with: pip install slack-sdk[optional] aiohttp"
            )

        if not self.bot_token or not self.app_token:
            raise ValueError("Slack bot_token and app_token are required")

        self._web_client = AsyncWebClient(token=self.bot_token)
        self._socket_client = SocketModeClient(
            app_token=self.app_token,
            web_client=self._web_client,
        )

        # Get bot user ID to filter self-messages
        auth = await self._web_client.auth_test()
        self._bot_user_id = auth["user_id"]

        self._socket_client.socket_mode_request_listeners.append(self._handle_event)
        self._running = True

        await self._socket_client.connect()
        logger.info(f"Slack channel connected as {auth['user']}")

    async def stop(self):
        self._running = False
        if self._socket_client:
            await self._socket_client.disconnect()
        logger.info("Slack channel stopped")

    async def send(self, message: OutboundMessage):
        if not self._web_client:
            return

        kwargs = {
            "channel": message.channel_id,
            "text": message.content,
        }

        # Reply in thread if this is a threaded conversation
        thread_ts = message.metadata.get("thread_ts")
        if thread_ts:
            kwargs["thread_ts"] = thread_ts

        await self._web_client.chat_postMessage(**kwargs)

    async def _handle_event(self, client: "SocketModeClient", req: "SocketModeRequest"):
        """Process incoming Socket Mode events."""
        # Acknowledge the event immediately
        await client.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))

        if req.type != "events_api":
            return

        event = req.payload.get("event", {})
        if event.get("type") != "message":
            return

        # Skip bot messages and subtypes (edits, joins, etc.)
        if event.get("bot_id") or event.get("subtype"):
            return
        if event.get("user") == self._bot_user_id:
            return

        inbound = InboundMessage(
            channel_type="slack",
            channel_id=event.get("channel", ""),
            sender_id=event.get("user", ""),
            sender_name=event.get("user", ""),  # Resolve later if needed
            content=event.get("text", ""),
            reply_to=event.get("thread_ts", ""),
            metadata={
                "thread_ts": event.get("thread_ts", event.get("ts", "")),
                "ts": event.get("ts", ""),
                "team": req.payload.get("team_id", ""),
            },
        )
        await self._enqueue(inbound)
