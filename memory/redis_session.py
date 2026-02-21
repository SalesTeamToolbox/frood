"""
Redis-backed session storage for fast conversation access.

Provides a Redis caching layer over the JSONL session files with:
- Sub-millisecond session reads (vs. disk I/O)
- TTL-based auto-expiry for old sessions
- Cross-instance session sharing for multi-node deployments
- Embedding vector cache to reduce API calls

Falls back gracefully when redis is not installed or unavailable —
callers should check `is_available` before using.
"""

import hashlib
import json
import logging
import time
from dataclasses import dataclass

logger = logging.getLogger("agent42.memory.redis_session")

try:
    import redis

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    logger.debug("redis package not installed — Redis backend unavailable")


@dataclass
class RedisConfig:
    """Configuration for Redis connection."""

    url: str = ""  # e.g. "redis://localhost:6379/0"
    password: str = ""
    session_ttl_days: int = 7
    embedding_cache_ttl_hours: int = 24
    key_prefix: str = "agent42"


class RedisSessionBackend:
    """Redis-backed session cache with embedding cache support.

    Key patterns:
    - {prefix}:session:{channel}:{id}       — List of session messages (JSON)
    - {prefix}:session:{channel}:{id}:meta   — Hash of session metadata
    - {prefix}:embed_cache:{hash}            — Cached embedding vectors
    - {prefix}:memory_version                — Memory version counter
    """

    def __init__(self, config: RedisConfig):
        self.config = config
        self._client: "redis.Redis | None" = None
        self._session_ttl = config.session_ttl_days * 86400  # Convert to seconds
        self._embed_ttl = config.embedding_cache_ttl_hours * 3600

        if not REDIS_AVAILABLE:
            logger.info("Redis backend: redis package not installed, unavailable")
            return

        try:
            kwargs = {
                "decode_responses": True,
                "socket_timeout": 5,
                "socket_connect_timeout": 5,
                "retry_on_timeout": True,
            }
            if config.url:
                self._client = redis.from_url(config.url, **kwargs)
            else:
                logger.info("Redis backend: no REDIS_URL configured, unavailable")
                return

            # Test connection
            self._client.ping()
            logger.info(f"Redis backend: connected to {config.url}")
        except Exception as e:
            logger.warning(f"Redis backend: failed to connect — {e}")
            self._client = None

    @property
    def is_available(self) -> bool:
        """Whether Redis is connected and usable."""
        return self._client is not None

    def _key(self, *parts: str) -> str:
        """Build a Redis key with prefix."""
        return ":".join([self.config.key_prefix, *parts])

    # -- Session operations --

    def add_message(
        self,
        channel_type: str,
        channel_id: str,
        message_dict: dict,
        max_messages: int = 500,
    ):
        """Add a message to the session list in Redis.

        Args:
            channel_type: Channel type (e.g. "discord", "slack")
            channel_id: Channel/chat ID
            message_dict: Message as a dict (role, content, timestamp, etc.)
            max_messages: Max messages to keep in the list
        """
        if not self._client:
            return

        key = self._key("session", channel_type, channel_id)
        meta_key = self._key("session", channel_type, channel_id, "meta")

        try:
            pipe = self._client.pipeline()
            pipe.rpush(key, json.dumps(message_dict))
            pipe.ltrim(key, -max_messages, -1)  # Keep only last N
            pipe.expire(key, self._session_ttl)
            pipe.hset(
                meta_key,
                mapping={
                    "last_active": str(time.time()),
                    "channel_type": channel_type,
                    "channel_id": channel_id,
                },
            )
            pipe.expire(meta_key, self._session_ttl)
            pipe.execute()
        except Exception as e:
            logger.warning(f"Redis: failed to add message — {e}")

    def get_history(
        self,
        channel_type: str,
        channel_id: str,
        max_messages: int = 50,
    ) -> list[dict] | None:
        """Get recent messages from Redis.

        Returns None if not in cache (caller should fall back to JSONL).
        Returns empty list if session exists but has no messages.
        """
        if not self._client:
            return None

        key = self._key("session", channel_type, channel_id)

        try:
            # Check if key exists first
            if not self._client.exists(key):
                return None

            # Get last N messages
            raw_messages = self._client.lrange(key, -max_messages, -1)
            messages = []
            for raw in raw_messages:
                try:
                    messages.append(json.loads(raw))
                except json.JSONDecodeError:
                    continue
            return messages
        except Exception as e:
            logger.warning(f"Redis: failed to get history — {e}")
            return None

    def clear_session(self, channel_type: str, channel_id: str):
        """Clear a session from Redis."""
        if not self._client:
            return

        key = self._key("session", channel_type, channel_id)
        meta_key = self._key("session", channel_type, channel_id, "meta")

        try:
            self._client.delete(key, meta_key)
        except Exception as e:
            logger.warning(f"Redis: failed to clear session — {e}")

    def warm_cache(
        self, channel_type: str, channel_id: str, messages: list[dict]
    ):
        """Pre-populate Redis cache from JSONL data.

        Called when a session is loaded from disk but not yet in Redis.
        """
        if not self._client or not messages:
            return

        key = self._key("session", channel_type, channel_id)

        try:
            pipe = self._client.pipeline()
            pipe.delete(key)
            for msg in messages:
                pipe.rpush(key, json.dumps(msg))
            pipe.expire(key, self._session_ttl)
            pipe.execute()
        except Exception as e:
            logger.warning(f"Redis: failed to warm cache — {e}")

    # -- Embedding cache --

    def get_cached_embedding(self, text: str) -> list[float] | None:
        """Get a cached embedding vector for a text string.

        Returns None on cache miss.
        """
        if not self._client:
            return None

        text_hash = hashlib.sha256(text.encode()).hexdigest()[:16]
        key = self._key("embed_cache", text_hash)

        try:
            cached = self._client.get(key)
            if cached:
                return json.loads(cached)
        except Exception:
            pass
        return None

    def cache_embedding(self, text: str, vector: list[float]):
        """Cache an embedding vector for future lookups."""
        if not self._client:
            return

        text_hash = hashlib.sha256(text.encode()).hexdigest()[:16]
        key = self._key("embed_cache", text_hash)

        try:
            self._client.setex(key, self._embed_ttl, json.dumps(vector))
        except Exception as e:
            logger.debug(f"Redis: failed to cache embedding — {e}")

    # -- Memory version tracking --

    def get_memory_version(self) -> int:
        """Get the current memory version counter."""
        if not self._client:
            return 0

        try:
            val = self._client.get(self._key("memory_version"))
            return int(val) if val else 0
        except Exception:
            return 0

    def increment_memory_version(self) -> int:
        """Increment the memory version (called after memory updates)."""
        if not self._client:
            return 0

        try:
            return self._client.incr(self._key("memory_version"))
        except Exception:
            return 0

    # -- Utility --

    def get_active_sessions(self) -> list[dict]:
        """List all active sessions with metadata."""
        if not self._client:
            return []

        try:
            pattern = self._key("session", "*", "*", "meta")
            sessions = []
            for meta_key in self._client.scan_iter(match=pattern, count=100):
                meta = self._client.hgetall(meta_key)
                if meta:
                    sessions.append(meta)
            return sessions
        except Exception as e:
            logger.warning(f"Redis: failed to list sessions — {e}")
            return []

    def close(self):
        """Close the Redis connection."""
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None
