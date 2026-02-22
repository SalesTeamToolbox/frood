"""
Pluggable storage backends for the TaskQueue.

Backends:
  - JsonFileBackend (default): writes tasks.json on every change
  - RedisQueueBackend (optional): Redis hashes + pub/sub for persistence and events

The in-process asyncio.PriorityQueue handles dispatch ordering; backends
handle persistence only.
"""

import json
import logging
from abc import ABC, abstractmethod
from pathlib import Path

import aiofiles

logger = logging.getLogger("agent42.queue_backend")


class QueueBackend(ABC):
    """Abstract storage backend for task persistence."""

    @abstractmethod
    async def save_task(self, task_dict: dict) -> None:
        """Persist a single task (create or update)."""

    @abstractmethod
    async def load_all(self) -> list[dict]:
        """Load all tasks from storage. Returns list of task dicts."""

    @abstractmethod
    async def delete_task(self, task_id: str) -> None:
        """Remove a task from storage."""

    async def start(self) -> None:
        """Initialize the backend (called once at startup)."""
        pass

    async def stop(self) -> None:
        """Cleanup the backend (called on shutdown)."""
        pass


class JsonFileBackend(QueueBackend):
    """JSON file backend — extracts the existing persistence logic."""

    def __init__(self, json_path: str):
        self._json_path = Path(json_path)
        self._tasks_cache: dict[str, dict] = {}

    async def save_task(self, task_dict: dict) -> None:
        self._tasks_cache[task_dict["id"]] = task_dict
        await self._write_all()

    async def load_all(self) -> list[dict]:
        if not self._json_path.exists():
            return []
        try:
            async with aiofiles.open(self._json_path) as f:
                raw = await f.read()
            data = json.loads(raw)
            for item in data:
                if isinstance(item, dict) and "id" in item:
                    self._tasks_cache[item["id"]] = item
            return data
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"Failed to load tasks file: {e}")
            return []

    async def delete_task(self, task_id: str) -> None:
        self._tasks_cache.pop(task_id, None)
        await self._write_all()

    async def _write_all(self) -> None:
        data = list(self._tasks_cache.values())
        try:
            async with aiofiles.open(self._json_path, "w") as f:
                await f.write(json.dumps(data, indent=2))
        except OSError as e:
            logger.error(f"Failed to persist tasks: {e}")


# Redis hash field types that need special serialization/deserialization
_LIST_FIELDS = ("tags", "comments", "origin_metadata")
_INT_FIELDS = ("priority", "position", "iterations", "max_iterations", "retry_count", "max_retries")
_FLOAT_FIELDS = ("created_at", "updated_at")


class RedisQueueBackend(QueueBackend):
    """Redis-backed task storage with pub/sub for state changes.

    Key patterns:
      {prefix}:task:{task_id}   -- Hash storing all task fields
      {prefix}:task_ids         -- Set of all task IDs
      {prefix}:task_events      -- Pub/sub channel for state changes

    Falls back gracefully to JsonFileBackend if Redis connection fails.
    """

    def __init__(
        self,
        redis_url: str,
        redis_password: str = "",
        key_prefix: str = "agent42",
        fallback_json_path: str = "tasks.json",
    ):
        self._redis_url = redis_url
        self._redis_password = redis_password
        self._prefix = key_prefix
        self._client = None
        self._fallback = JsonFileBackend(fallback_json_path)

    def _key(self, *parts: str) -> str:
        return ":".join([self._prefix, *parts])

    @property
    def is_redis_active(self) -> bool:
        return self._client is not None

    async def start(self) -> None:
        try:
            import redis.asyncio as aioredis
        except ImportError:
            logger.warning(
                "redis.asyncio not available — pip install redis[hiredis]. Using JSON file backend."
            )
            return

        try:
            self._client = aioredis.from_url(
                self._redis_url,
                password=self._redis_password or None,
                decode_responses=True,
                socket_timeout=5,
                socket_connect_timeout=5,
            )
            await self._client.ping()
            logger.info(f"Redis queue backend connected: {self._redis_url}")
        except Exception as e:
            logger.warning(f"Redis queue backend unavailable ({e}) — falling back to JSON")
            self._client = None

    async def stop(self) -> None:
        if self._client:
            await self._client.aclose()
        await self._fallback.stop()

    async def save_task(self, task_dict: dict) -> None:
        if not self._client:
            return await self._fallback.save_task(task_dict)

        try:
            task_id = task_dict["id"]
            key = self._key("task", task_id)
            flat = _task_dict_to_hash(task_dict)
            await self._client.hset(key, mapping=flat)
            await self._client.sadd(self._key("task_ids"), task_id)
            # Publish state change event for future multi-node subscribers
            await self._client.publish(
                self._key("task_events"),
                json.dumps({"task_id": task_id, "status": task_dict.get("status", "")}),
            )
        except Exception as e:
            logger.error(f"Redis save_task failed ({e}) — falling back to JSON")
            await self._fallback.save_task(task_dict)

    async def load_all(self) -> list[dict]:
        if not self._client:
            return await self._fallback.load_all()

        try:
            task_ids = await self._client.smembers(self._key("task_ids"))
            if not task_ids:
                # Redis empty — try loading from JSON fallback and warm cache
                tasks = await self._fallback.load_all()
                if tasks:
                    logger.info(
                        f"Redis empty, loaded {len(tasks)} tasks from JSON — warming Redis cache"
                    )
                    for t in tasks:
                        if isinstance(t, dict) and "id" in t:
                            key = self._key("task", t["id"])
                            await self._client.hset(key, mapping=_task_dict_to_hash(t))
                            await self._client.sadd(self._key("task_ids"), t["id"])
                return tasks

            pipe = self._client.pipeline()
            for tid in task_ids:
                pipe.hgetall(self._key("task", tid))
            results = await pipe.execute()

            tasks = []
            for raw in results:
                if raw:
                    tasks.append(_hash_to_task_dict(raw))
            return tasks
        except Exception as e:
            logger.error(f"Redis load_all failed ({e}) — falling back to JSON")
            return await self._fallback.load_all()

    async def delete_task(self, task_id: str) -> None:
        if not self._client:
            return await self._fallback.delete_task(task_id)

        try:
            await self._client.delete(self._key("task", task_id))
            await self._client.srem(self._key("task_ids"), task_id)
        except Exception as e:
            logger.error(f"Redis delete_task failed: {e}")
            await self._fallback.delete_task(task_id)


def _task_dict_to_hash(task_dict: dict) -> dict[str, str]:
    """Convert a task dict to a flat string dict for Redis HSET."""
    flat: dict[str, str] = {}
    for k, v in task_dict.items():
        if isinstance(v, (list, dict)):
            flat[k] = json.dumps(v)
        elif v is None:
            flat[k] = ""
        else:
            flat[k] = str(v)
    return flat


def _hash_to_task_dict(raw: dict[str, str]) -> dict:
    """Convert a Redis hash (all strings) back to a task dict."""
    result = dict(raw)
    for field_name in _LIST_FIELDS:
        if field_name in result and isinstance(result[field_name], str):
            try:
                result[field_name] = json.loads(result[field_name])
            except (json.JSONDecodeError, TypeError):
                result[field_name] = [] if field_name != "origin_metadata" else {}
    for field_name in _INT_FIELDS:
        if field_name in result:
            try:
                result[field_name] = int(result[field_name])
            except (ValueError, TypeError):
                pass
    for field_name in _FLOAT_FIELDS:
        if field_name in result:
            try:
                result[field_name] = float(result[field_name])
            except (ValueError, TypeError):
                pass
    return result
