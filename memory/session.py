"""
Session-based conversation history for channel interactions.

Each channel+chat combination gets its own session with persistent
message history stored as JSONL (one JSON object per line).

When Redis is available, sessions are cached in Redis for fast access
with TTL-based expiry. JSONL files remain the durable backing store.

When the consolidation pipeline is available, old messages are summarized
before pruning so the knowledge is preserved in long-term memory.
"""

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

logger = logging.getLogger("agent42.memory.session")


@dataclass
class SessionMessage:
    """A single message in a conversation session."""
    role: str           # "user", "assistant", "system"
    content: str
    timestamp: float = field(default_factory=time.time)
    channel_type: str = ""
    sender_id: str = ""
    sender_name: str = ""


class SessionManager:
    """Manages conversation sessions with JSONL persistence.

    When a RedisSessionBackend is provided, sessions are cached in Redis
    for fast retrieval with automatic TTL expiry. JSONL files remain the
    durable backing store (write-through caching pattern).
    """

    def __init__(self, sessions_dir: str | Path, redis_backend=None,
                 consolidation_pipeline=None):
        self.sessions_dir = Path(sessions_dir)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self._sessions: dict[str, list[SessionMessage]] = {}
        self._redis = redis_backend  # RedisSessionBackend (optional)
        self._consolidation = consolidation_pipeline  # ConsolidationPipeline (optional)

    def _session_key(self, channel_type: str, channel_id: str) -> str:
        """Generate a unique session key."""
        return f"{channel_type}_{channel_id}"

    def _session_path(self, key: str) -> Path:
        """Get the JSONL file path for a session."""
        # Sanitize the key for use as a filename
        safe_key = "".join(c if c.isalnum() or c in "-_" else "_" for c in key)
        return self.sessions_dir / f"{safe_key}.jsonl"

    # Max messages per session before pruning
    MAX_SESSION_MESSAGES = 500

    def add_message(self, channel_type: str, channel_id: str, message: SessionMessage):
        """Add a message to a session and persist it.

        Write-through pattern: writes to both JSONL (durable) and Redis (cache).
        When pruning is needed, triggers consolidation if available.
        """
        key = self._session_key(channel_type, channel_id)

        if key not in self._sessions:
            self._sessions[key] = self._load_session(key)

        self._sessions[key].append(message)

        # Write-through to Redis cache
        if self._redis and self._redis.is_available:
            self._redis.add_message(
                channel_type, channel_id, asdict(message),
                max_messages=self.MAX_SESSION_MESSAGES,
            )

        # Prune old messages to prevent unbounded growth
        if len(self._sessions[key]) > self.MAX_SESSION_MESSAGES:
            # Consolidate before pruning (if pipeline available)
            pruned_messages = self._sessions[key][:-self.MAX_SESSION_MESSAGES]
            if pruned_messages and self._consolidation and self._consolidation.is_available:
                self._schedule_consolidation(
                    pruned_messages, channel_type, channel_id,
                )

            self._sessions[key] = self._sessions[key][-self.MAX_SESSION_MESSAGES:]
            self._rewrite_session(key)
            return

        # Append to JSONL file
        path = self._session_path(key)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(message)) + "\n")

    def _rewrite_session(self, key: str):
        """Rewrite the entire session file (used after pruning)."""
        path = self._session_path(key)
        messages = self._sessions.get(key, [])
        try:
            with open(path, "w", encoding="utf-8") as f:
                for msg in messages:
                    f.write(json.dumps(asdict(msg)) + "\n")
            logger.info(f"Session pruned: {key} ({len(messages)} messages kept)")
        except Exception as e:
            logger.error(f"Failed to rewrite session {key}: {e}")

    def get_history(
        self,
        channel_type: str,
        channel_id: str,
        max_messages: int = 50,
    ) -> list[SessionMessage]:
        """Get recent conversation history for a session.

        Checks Redis cache first, falls back to JSONL if not cached.
        Warms Redis cache on JSONL fallback load.
        """
        # Try Redis first for fast access
        if self._redis and self._redis.is_available:
            cached = self._redis.get_history(channel_type, channel_id, max_messages)
            if cached is not None:
                return [SessionMessage(**m) for m in cached]

        key = self._session_key(channel_type, channel_id)

        if key not in self._sessions:
            self._sessions[key] = self._load_session(key)

        messages = self._sessions[key][-max_messages:]

        # Warm Redis cache from JSONL data
        if self._redis and self._redis.is_available and messages:
            self._redis.warm_cache(
                channel_type, channel_id,
                [asdict(m) for m in self._sessions[key]],
            )

        return messages

    def get_messages_as_dicts(
        self,
        channel_type: str,
        channel_id: str,
        max_messages: int = 50,
    ) -> list[dict]:
        """Get history as OpenAI-format message dicts."""
        messages = self.get_history(channel_type, channel_id, max_messages)
        return [{"role": m.role, "content": m.content} for m in messages]

    def clear_session(self, channel_type: str, channel_id: str):
        """Clear a session's history."""
        key = self._session_key(channel_type, channel_id)
        self._sessions.pop(key, None)
        path = self._session_path(key)
        if path.exists():
            path.unlink()

        # Also clear from Redis
        if self._redis and self._redis.is_available:
            self._redis.clear_session(channel_type, channel_id)

        logger.info(f"Session cleared: {key}")

    def _load_session(self, key: str) -> list[SessionMessage]:
        """Load a session from its JSONL file."""
        path = self._session_path(key)
        messages = []

        if not path.exists():
            return messages

        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        messages.append(SessionMessage(**data))
                    except (json.JSONDecodeError, TypeError):
                        continue
        except Exception as e:
            logger.error(f"Failed to load session {key}: {e}")

        return messages

    def _schedule_consolidation(
        self,
        messages: list[SessionMessage],
        channel_type: str,
        channel_id: str,
    ):
        """Schedule async consolidation of pruned messages.

        This is fire-and-forget — consolidation failures don't affect
        the session manager's normal operation.
        """
        import asyncio

        message_dicts = [asdict(m) for m in messages]

        async def _consolidate():
            try:
                await self._consolidation.consolidate_and_store(
                    message_dicts, channel_type, channel_id,
                )
            except Exception as e:
                logger.warning(f"Consolidation failed (non-critical): {e}")

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_consolidate())
        except RuntimeError:
            # No running event loop — skip consolidation
            logger.debug("No event loop available for consolidation")
