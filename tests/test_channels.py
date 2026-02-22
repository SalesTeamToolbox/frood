"""Tests for Phase 2: Channel abstraction and manager."""

import asyncio

import pytest

from channels.base import BaseChannel, InboundMessage, OutboundMessage
from channels.manager import ChannelManager


class MockChannel(BaseChannel):
    """Test channel for unit testing."""

    def __init__(self, config=None):
        super().__init__("mock", config or {})
        self.sent_messages: list[OutboundMessage] = []
        self.started = False
        self.stopped = False

    async def start(self):
        self.started = True
        self._running = True

    async def stop(self):
        self.stopped = True
        self._running = False

    async def send(self, message: OutboundMessage):
        self.sent_messages.append(message)

    async def inject_message(self, content: str, sender_id: str = "user1"):
        """Helper to simulate an incoming message."""
        msg = InboundMessage(
            channel_type="mock",
            channel_id="test-channel",
            sender_id=sender_id,
            sender_name="Test User",
            content=content,
        )
        await self._enqueue(msg)


class TestInboundMessage:
    def test_create_message(self):
        msg = InboundMessage(
            channel_type="discord",
            channel_id="12345",
            sender_id="user1",
            sender_name="TestUser",
            content="Hello agent",
        )
        assert msg.channel_type == "discord"
        assert msg.content == "Hello agent"
        assert msg.attachments == []
        assert msg.metadata == {}


class TestOutboundMessage:
    def test_create_message(self):
        msg = OutboundMessage(
            channel_type="slack",
            channel_id="C123",
            content="Response text",
        )
        assert msg.channel_type == "slack"
        assert msg.content == "Response text"


class TestBaseChannel:
    def test_user_allowed_empty_allowlist(self):
        ch = MockChannel({})
        assert ch.is_user_allowed("anyone") is True

    def test_user_allowed_with_allowlist(self):
        ch = MockChannel({"allow_from": ["user1", "user2"]})
        assert ch.is_user_allowed("user1") is True
        assert ch.is_user_allowed("user3") is False

    @pytest.mark.asyncio
    async def test_enqueue_allowed_user(self):
        ch = MockChannel({"allow_from": ["user1"]})
        await ch.inject_message("hello", sender_id="user1")
        msg = await asyncio.wait_for(ch.receive(), timeout=1.0)
        assert msg.content == "hello"

    @pytest.mark.asyncio
    async def test_enqueue_blocked_user(self):
        ch = MockChannel({"allow_from": ["user1"]})
        await ch.inject_message("hello", sender_id="blocked_user")
        # Queue should be empty
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(ch.receive(), timeout=0.1)


class TestChannelManager:
    @pytest.mark.asyncio
    async def test_register_channel(self):
        mgr = ChannelManager()
        ch = MockChannel()
        mgr.register(ch)
        assert "mock" in mgr._channels

    @pytest.mark.asyncio
    async def test_send_routes_to_channel(self):
        mgr = ChannelManager()
        ch = MockChannel()
        mgr.register(ch)

        out = OutboundMessage(
            channel_type="mock",
            channel_id="test",
            content="Hello!",
        )
        await mgr.send(out)
        assert len(ch.sent_messages) == 1
        assert ch.sent_messages[0].content == "Hello!"

    def test_list_channels(self):
        mgr = ChannelManager()
        ch = MockChannel()
        mgr.register(ch)
        channels = mgr.list_channels()
        assert len(channels) == 1
        assert channels[0]["type"] == "mock"
