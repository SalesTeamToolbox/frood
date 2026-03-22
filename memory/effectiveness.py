"""Async SQLite-backed effectiveness tracking for tool invocations.

Records tool_name, task_type, task_id, success, duration_ms, and timestamp
for every tool call. Writes are fire-and-forget via asyncio.create_task()
so the tool execution hot path is never blocked.

Graceful degradation: if the SQLite DB is missing or unwritable, all methods
silently log a warning and return without raising.
"""

import logging
import time
from pathlib import Path

logger = logging.getLogger("agent42.memory.effectiveness")

try:
    import aiosqlite

    AIOSQLITE_AVAILABLE = True
except ImportError:
    AIOSQLITE_AVAILABLE = False
    logger.debug("aiosqlite not installed — effectiveness tracking unavailable")


class EffectivenessStore:
    """Async SQLite store for tool invocation effectiveness data.

    Usage:
        store = EffectivenessStore(Path(".agent42/effectiveness.db"))
        # Fire-and-forget from ToolRegistry:
        asyncio.create_task(store.record(
            tool_name="shell", task_type="coding", task_id="abc-123",
            success=True, duration_ms=42.5
        ))
    """

    def __init__(self, db_path: "str | Path"):
        self._db_path = Path(db_path)
        self._available: bool | None = None  # None = untested
        self._db_initialized = False

    @property
    def is_available(self) -> bool:
        """Whether the store has successfully written at least once."""
        if not AIOSQLITE_AVAILABLE:
            return False
        if self._available is None:
            return True  # Optimistic until first write attempt
        return self._available

    async def _ensure_db(self) -> None:
        """Create the DB file and table if they don't exist."""
        if self._db_initialized:
            return
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS tool_invocations (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    tool_name   TEXT    NOT NULL,
                    task_type   TEXT    NOT NULL,
                    task_id     TEXT    NOT NULL,
                    success     INTEGER NOT NULL,
                    duration_ms REAL    NOT NULL,
                    ts          REAL    NOT NULL
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_tool_task "
                "ON tool_invocations (tool_name, task_type)"
            )
            await db.execute("CREATE INDEX IF NOT EXISTS idx_task_id ON tool_invocations (task_id)")
            await db.commit()
            # Phase rewards: add agent_id column to existing databases
            # SQLite ALTER TABLE ADD COLUMN is idempotent-safe via try/except
            try:
                await db.execute("ALTER TABLE tool_invocations ADD COLUMN agent_id TEXT DEFAULT ''")
                await db.commit()
            except Exception:
                pass  # Column already exists — safe to ignore
        self._db_initialized = True

    async def record(
        self,
        tool_name: str,
        task_type: str,
        task_id: str,
        success: bool,
        duration_ms: float,
        agent_id: str = "",
    ) -> None:
        """Write one effectiveness record. Never raises."""
        if not AIOSQLITE_AVAILABLE:
            return
        try:
            await self._ensure_db()
            async with aiosqlite.connect(self._db_path) as db:
                await db.execute(
                    """INSERT INTO tool_invocations
                       (tool_name, task_type, task_id, success, duration_ms, ts, agent_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        tool_name,
                        task_type,
                        task_id,
                        int(success),
                        duration_ms,
                        time.time(),
                        agent_id,
                    ),
                )
                await db.commit()
            self._available = True
        except Exception as e:
            self._available = False
            logger.warning("EffectivenessStore write failed (non-critical): %s", e)

    async def get_aggregated_stats(self, tool_name: str = "", task_type: str = "") -> list:
        """Return success_rate and avg_duration by tool+task_type pair.

        Filters by tool_name and/or task_type when provided (non-empty string).
        Returns empty list on any failure.
        """
        if not AIOSQLITE_AVAILABLE:
            return []
        try:
            await self._ensure_db()
            query = """
                SELECT
                    tool_name,
                    task_type,
                    COUNT(*)                   AS invocations,
                    AVG(CAST(success AS REAL)) AS success_rate,
                    AVG(duration_ms)           AS avg_duration_ms
                FROM tool_invocations
                WHERE (? = '' OR tool_name = ?)
                  AND (? = '' OR task_type = ?)
                GROUP BY tool_name, task_type
                ORDER BY invocations DESC
            """
            async with aiosqlite.connect(self._db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    query, (tool_name, tool_name, task_type, task_type)
                ) as cursor:
                    rows = await cursor.fetchall()
            return [dict(row) for row in rows]
        except Exception as e:
            logger.warning("EffectivenessStore aggregation failed: %s", e)
            return []

    async def get_task_records(self, task_id: str) -> list:
        """Return all records for a specific task_id. Used by learning extraction."""
        if not AIOSQLITE_AVAILABLE:
            return []
        try:
            await self._ensure_db()
            async with aiosqlite.connect(self._db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    "SELECT * FROM tool_invocations WHERE task_id = ? ORDER BY ts",
                    (task_id,),
                ) as cursor:
                    rows = await cursor.fetchall()
            return [dict(row) for row in rows]
        except Exception as e:
            logger.warning("EffectivenessStore task query failed: %s", e)
            return []

    async def get_agent_stats(self, agent_id: str) -> dict | None:
        """Return performance stats for a specific agent.

        Returns dict with keys: success_rate (float 0-1), task_volume (int),
        avg_speed (float ms). Returns None if no records exist for agent_id.
        """
        if not AIOSQLITE_AVAILABLE:
            return None
        try:
            await self._ensure_db()
            async with aiosqlite.connect(self._db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    """
                    SELECT
                        COUNT(*)                   AS task_volume,
                        AVG(CAST(success AS REAL)) AS success_rate,
                        AVG(duration_ms)           AS avg_speed
                    FROM tool_invocations
                    WHERE agent_id = ?
                    """,
                    (agent_id,),
                ) as cursor:
                    row = await cursor.fetchone()
            if row is None or dict(row)["task_volume"] == 0:
                return None
            return {
                "success_rate": dict(row)["success_rate"],
                "task_volume": int(dict(row)["task_volume"]),
                "avg_speed": dict(row)["avg_speed"],
            }
        except Exception as exc:
            logger.warning("EffectivenessStore get_agent_stats failed: %s", exc)
            return None

    async def get_recommendations(
        self,
        task_type: str,
        min_observations: int = 5,
        top_k: int = 3,
    ) -> list:
        """Return top tools ranked by success_rate for a given task_type.

        Only includes tools with >= min_observations invocations.
        Ordered by success_rate DESC, avg_duration_ms ASC (tie-break per D-08).
        Returns empty list on any failure or insufficient data.
        """
        if not AIOSQLITE_AVAILABLE or not task_type:
            return []
        try:
            await self._ensure_db()
            query = """
                SELECT
                    tool_name,
                    task_type,
                    COUNT(*)                   AS invocations,
                    AVG(CAST(success AS REAL)) AS success_rate,
                    AVG(duration_ms)           AS avg_duration_ms
                FROM tool_invocations
                WHERE task_type = ?
                GROUP BY tool_name, task_type
                HAVING COUNT(*) >= ?
                ORDER BY success_rate DESC, avg_duration_ms ASC
                LIMIT ?
            """
            async with aiosqlite.connect(self._db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(query, (task_type, min_observations, top_k)) as cursor:
                    rows = await cursor.fetchall()
            return [dict(row) for row in rows]
        except Exception as e:
            logger.warning("EffectivenessStore recommendations query failed: %s", e)
            return []
