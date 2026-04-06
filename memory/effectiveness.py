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

            # Phase 29: routing_decisions table (D-11)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS routing_decisions (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id       TEXT    NOT NULL,
                    agent_id     TEXT    NOT NULL,
                    company_id   TEXT    NOT NULL DEFAULT '',
                    provider     TEXT    NOT NULL,
                    model        TEXT    NOT NULL,
                    tier         TEXT    NOT NULL,
                    task_category TEXT   NOT NULL,
                    ts           REAL    NOT NULL
                )
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_routing_agent_ts
                ON routing_decisions (agent_id, ts DESC)
            """)

            # Phase 29: spend_history table (D-14)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS spend_history (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id      TEXT    NOT NULL,
                    company_id    TEXT    NOT NULL DEFAULT '',
                    provider      TEXT    NOT NULL,
                    model         TEXT    NOT NULL,
                    input_tokens  INTEGER NOT NULL DEFAULT 0,
                    output_tokens INTEGER NOT NULL DEFAULT 0,
                    cost_usd      REAL    NOT NULL DEFAULT 0.0,
                    hour_bucket   TEXT    NOT NULL,
                    ts            REAL    NOT NULL
                )
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_spend_agent_hour
                ON spend_history (agent_id, hour_bucket)
            """)

            # Phase 29: run_transcripts table (D-18)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS run_transcripts (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id       TEXT    NOT NULL UNIQUE,
                    agent_id     TEXT    NOT NULL,
                    company_id   TEXT    NOT NULL DEFAULT '',
                    task_type    TEXT    NOT NULL DEFAULT '',
                    summary      TEXT    NOT NULL,
                    extracted    INTEGER NOT NULL DEFAULT 0,
                    ts           REAL    NOT NULL
                )
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_transcripts_pending
                ON run_transcripts (extracted, ts)
            """)
            await db.commit()

            # Phase 43: Tool pattern detection tables
            await db.execute("""
                CREATE TABLE IF NOT EXISTS tool_sequences (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id        TEXT    NOT NULL DEFAULT '',
                    task_type       TEXT    NOT NULL DEFAULT '',
                    tool_sequence   TEXT    NOT NULL,
                    execution_count INTEGER NOT NULL DEFAULT 1,
                    first_seen      REAL    NOT NULL,
                    last_seen       REAL    NOT NULL,
                    fingerprint     TEXT    NOT NULL,
                    status          TEXT    NOT NULL DEFAULT 'active'
                )
            """)
            await db.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_seq_agent_type_fp "
                "ON tool_sequences (agent_id, task_type, fingerprint)"
            )

            await db.execute("""
                CREATE TABLE IF NOT EXISTS workflow_suggestions (
                    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id              TEXT    NOT NULL DEFAULT '',
                    task_type             TEXT    NOT NULL DEFAULT '',
                    fingerprint           TEXT    NOT NULL,
                    tool_sequence         TEXT    NOT NULL,
                    execution_count       INTEGER NOT NULL,
                    tokens_saved_estimate INTEGER NOT NULL DEFAULT 0,
                    suggested_at          REAL    NOT NULL,
                    status                TEXT    NOT NULL DEFAULT 'pending'
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_suggestions_agent "
                "ON workflow_suggestions (agent_id, status)"
            )
            await db.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_suggestions_agent_fp "
                "ON workflow_suggestions (agent_id, fingerprint)"
            )

            await db.execute("""
                CREATE TABLE IF NOT EXISTS workflow_mappings (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id       TEXT    NOT NULL DEFAULT '',
                    fingerprint    TEXT    NOT NULL,
                    workflow_id    TEXT    NOT NULL,
                    webhook_url    TEXT    NOT NULL,
                    template       TEXT    NOT NULL DEFAULT '',
                    created_at     REAL    NOT NULL,
                    last_triggered REAL    NOT NULL DEFAULT 0.0,
                    trigger_count  INTEGER NOT NULL DEFAULT 0,
                    status         TEXT    NOT NULL DEFAULT 'active'
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_mappings_agent_fp "
                "ON workflow_mappings (agent_id, fingerprint)"
            )
            await db.commit()

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

    async def get_aggregated_stats(
        self, tool_name: str = "", task_type: str = "", agent_id: str = ""
    ) -> list:
        """Return success_rate and avg_duration by tool+task_type pair.

        Filters by tool_name, task_type, and/or agent_id when provided (non-empty string).
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
                  AND (? = '' OR agent_id = ?)
                GROUP BY tool_name, task_type
                ORDER BY invocations DESC
            """
            async with aiosqlite.connect(self._db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    query, (tool_name, tool_name, task_type, task_type, agent_id, agent_id)
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

    # -------------------------------------------------------------------------
    # Phase 29 — Routing decisions, spend history, and run transcripts
    # -------------------------------------------------------------------------

    async def log_routing_decision(
        self,
        run_id: str,
        agent_id: str,
        company_id: str,
        provider: str,
        model: str,
        tier: str,
        task_category: str,
    ) -> None:
        """Record a routing decision for history queries (D-11). Never raises."""
        if not AIOSQLITE_AVAILABLE:
            return
        try:
            await self._ensure_db()
            async with aiosqlite.connect(self._db_path) as db:
                await db.execute(
                    """INSERT INTO routing_decisions
                       (run_id, agent_id, company_id, provider, model, tier, task_category, ts)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        run_id,
                        agent_id,
                        company_id,
                        provider,
                        model,
                        tier,
                        task_category,
                        time.time(),
                    ),
                )
                await db.commit()
        except Exception as exc:
            logger.warning("EffectivenessStore log_routing_decision failed (non-critical): %s", exc)

    async def get_routing_history(self, agent_id: str, limit: int = 20) -> list:
        """Return recent routing decisions for an agent (D-11).

        Returns list of dicts with keys: run_id, provider, model, tier, task_category, ts.
        Returns empty list on any failure.
        """
        if not AIOSQLITE_AVAILABLE:
            return []
        try:
            await self._ensure_db()
            async with aiosqlite.connect(self._db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    """SELECT run_id, provider, model, tier, task_category, ts
                       FROM routing_decisions
                       WHERE agent_id = ?
                       ORDER BY ts DESC
                       LIMIT ?""",
                    (agent_id, limit),
                ) as cursor:
                    rows = await cursor.fetchall()
            return [dict(row) for row in rows]
        except Exception as exc:
            logger.warning("EffectivenessStore get_routing_history failed: %s", exc)
            return []

    async def log_spend(
        self,
        agent_id: str,
        company_id: str,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
    ) -> None:
        """Record token spend for 24h aggregation (D-14). Never raises."""
        if not AIOSQLITE_AVAILABLE:
            return
        try:
            await self._ensure_db()
            hour_bucket = datetime.now(UTC).strftime("%Y-%m-%dT%H:00:00")
            async with aiosqlite.connect(self._db_path) as db:
                await db.execute(
                    """INSERT INTO spend_history
                       (agent_id, company_id, provider, model,
                        input_tokens, output_tokens, cost_usd, hour_bucket, ts)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        agent_id,
                        company_id,
                        provider,
                        model,
                        input_tokens,
                        output_tokens,
                        cost_usd,
                        hour_bucket,
                        time.time(),
                    ),
                )
                await db.commit()
        except Exception as exc:
            logger.warning("EffectivenessStore log_spend failed (non-critical): %s", exc)

    async def get_agent_spend(self, agent_id: str = "", hours: int = 24) -> list:
        """Return spend grouped by provider over last N hours (D-14).

        Returns list of dicts with keys: provider, model, input_tokens,
        output_tokens, cost_usd, hour_bucket.
        Returns empty list on any failure.
        """
        if not AIOSQLITE_AVAILABLE:
            return []
        try:
            await self._ensure_db()
            cutoff = datetime.now(UTC) - timedelta(hours=hours)
            cutoff_bucket = cutoff.strftime("%Y-%m-%dT%H:00:00")
            async with aiosqlite.connect(self._db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    """SELECT
                           provider,
                           model,
                           SUM(input_tokens)  AS input_tokens,
                           SUM(output_tokens) AS output_tokens,
                           SUM(cost_usd)      AS cost_usd,
                           hour_bucket
                       FROM spend_history
                       WHERE (? = '' OR agent_id = ?)
                         AND hour_bucket >= ?
                       GROUP BY provider, model, hour_bucket
                       ORDER BY hour_bucket DESC""",
                    (agent_id, agent_id, cutoff_bucket),
                ) as cursor:
                    rows = await cursor.fetchall()
            return [dict(row) for row in rows]
        except Exception as exc:
            logger.warning("EffectivenessStore get_agent_spend failed: %s", exc)
            return []

    async def save_transcript(
        self,
        run_id: str,
        agent_id: str,
        company_id: str,
        task_type: str,
        summary: str,
    ) -> None:
        """Save run transcript for later learning extraction (D-18). Never raises."""
        if not AIOSQLITE_AVAILABLE:
            return
        try:
            await self._ensure_db()
            async with aiosqlite.connect(self._db_path) as db:
                await db.execute(
                    """INSERT OR IGNORE INTO run_transcripts
                       (run_id, agent_id, company_id, task_type, summary, extracted, ts)
                       VALUES (?, ?, ?, ?, ?, 0, ?)""",
                    (run_id, agent_id, company_id, task_type, summary, time.time()),
                )
                await db.commit()
        except Exception as exc:
            logger.warning("EffectivenessStore save_transcript failed (non-critical): %s", exc)

    async def drain_pending_transcripts(self, batch_size: int = 20) -> list:
        """Return and mark pending transcripts for extraction (D-19).

        Returns list of dicts with keys: run_id, agent_id, company_id, task_type, summary.
        Marks each returned transcript as extracted=1 in the same transaction.
        Returns empty list on any failure.
        """
        from core.config import settings as _settings

        if not _settings.learning_enabled:
            return []
        if not AIOSQLITE_AVAILABLE:
            return []
        try:
            await self._ensure_db()
            async with aiosqlite.connect(self._db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    """SELECT id, run_id, agent_id, company_id, task_type, summary
                       FROM run_transcripts
                       WHERE extracted = 0
                       ORDER BY ts ASC
                       LIMIT ?""",
                    (batch_size,),
                ) as cursor:
                    rows = await cursor.fetchall()
                results = [dict(row) for row in rows]
                for row in results:
                    await db.execute(
                        "UPDATE run_transcripts SET extracted = 1 WHERE id = ?",
                        (row["id"],),
                    )
                await db.commit()
            # Strip internal id before returning
            return [{k: v for k, v in r.items() if k != "id"} for r in results]
        except Exception as exc:
            logger.warning("EffectivenessStore drain_pending_transcripts failed: %s", exc)
            return []

    # -------------------------------------------------------------------------
    # Phase 43 — Tool pattern detection and workflow suggestions
    # -------------------------------------------------------------------------

    async def record_sequence(
        self, agent_id: str, task_type: str, tool_names: list[str]
    ) -> int | None:
        """Record a tool sequence. Returns execution_count if >= threshold, else None. Never raises."""
        if not AIOSQLITE_AVAILABLE or len(tool_names) < 2:
            return None
        try:
            import hashlib
            import json

            await self._ensure_db()
            fingerprint = hashlib.md5(json.dumps(tool_names).encode()).hexdigest()
            now = time.time()
            tool_seq_json = json.dumps(tool_names)
            async with aiosqlite.connect(self._db_path) as db:
                await db.execute(
                    """INSERT INTO tool_sequences
                       (agent_id, task_type, tool_sequence, execution_count, first_seen, last_seen, fingerprint, status)
                       VALUES (?, ?, ?, 1, ?, ?, ?, 'active')
                       ON CONFLICT(agent_id, task_type, fingerprint) DO UPDATE SET
                           execution_count = execution_count + 1,
                           last_seen = excluded.last_seen""",
                    (agent_id, task_type, tool_seq_json, now, now, fingerprint),
                )
                await db.commit()
                async with db.execute(
                    "SELECT execution_count FROM tool_sequences WHERE agent_id=? AND task_type=? AND fingerprint=?",
                    (agent_id, task_type, fingerprint),
                ) as cursor:
                    row = await cursor.fetchone()
            from core.config import settings

            if row and row[0] >= settings.n8n_pattern_threshold:
                return row[0]
            return None
        except Exception as exc:
            logger.warning("EffectivenessStore record_sequence failed (non-critical): %s", exc)
            return None

    async def create_suggestion(
        self,
        agent_id: str,
        task_type: str,
        fingerprint: str,
        tool_names: list[str],
        execution_count: int,
    ) -> None:
        """Write a suggestion row with status='pending'. Never raises."""
        if not AIOSQLITE_AVAILABLE:
            return
        try:
            import json

            await self._ensure_db()
            tokens_saved_estimate = execution_count * 1000
            async with aiosqlite.connect(self._db_path) as db:
                await db.execute(
                    """INSERT OR IGNORE INTO workflow_suggestions
                       (agent_id, task_type, fingerprint, tool_sequence, execution_count,
                        tokens_saved_estimate, suggested_at, status)
                       VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')""",
                    (
                        agent_id,
                        task_type,
                        fingerprint,
                        json.dumps(tool_names),
                        execution_count,
                        tokens_saved_estimate,
                        time.time(),
                    ),
                )
                await db.commit()
        except Exception as exc:
            logger.warning("EffectivenessStore create_suggestion failed (non-critical): %s", exc)

    async def get_pending_suggestions(self, agent_id: str) -> list[dict]:
        """Return never-injected suggestions for an agent. Never raises."""
        if not AIOSQLITE_AVAILABLE:
            return []
        try:
            await self._ensure_db()
            async with aiosqlite.connect(self._db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    """SELECT fingerprint, tool_sequence, execution_count, tokens_saved_estimate, task_type
                       FROM workflow_suggestions
                       WHERE agent_id=? AND status='pending'
                       ORDER BY execution_count DESC LIMIT 3""",
                    (agent_id,),
                ) as cursor:
                    rows = await cursor.fetchall()
            return [dict(r) for r in rows]
        except Exception as exc:
            logger.warning("EffectivenessStore get_pending_suggestions failed: %s", exc)
            return []

    async def mark_suggestion_status(self, fingerprint: str, agent_id: str, status: str) -> None:
        """Update suggestion status (pending -> suggested -> dismissed/created). Never raises."""
        if not AIOSQLITE_AVAILABLE:
            return
        try:
            await self._ensure_db()
            async with aiosqlite.connect(self._db_path) as db:
                await db.execute(
                    "UPDATE workflow_suggestions SET status=? WHERE fingerprint=? AND agent_id=?",
                    (status, fingerprint, agent_id),
                )
                await db.commit()
        except Exception as exc:
            logger.warning("EffectivenessStore mark_suggestion_status failed: %s", exc)

    async def record_workflow_mapping(
        self,
        agent_id: str,
        fingerprint: str,
        workflow_id: str,
        webhook_url: str,
        template: str,
    ) -> None:
        """Record a workflow mapping. Never raises."""
        if not AIOSQLITE_AVAILABLE:
            return
        try:
            await self._ensure_db()
            async with aiosqlite.connect(self._db_path) as db:
                await db.execute(
                    """INSERT INTO workflow_mappings
                       (agent_id, fingerprint, workflow_id, webhook_url, template,
                        created_at, last_triggered, trigger_count, status)
                       VALUES (?, ?, ?, ?, ?, ?, 0.0, 0, 'active')""",
                    (agent_id, fingerprint, workflow_id, webhook_url, template, time.time()),
                )
                await db.commit()
            await self.mark_suggestion_status(fingerprint, agent_id, "created")
        except Exception as exc:
            logger.warning("EffectivenessStore record_workflow_mapping failed: %s", exc)


# Phase 43: Shared store singleton for cross-module access
_shared_effectiveness_store: "EffectivenessStore | None" = None


def set_shared_store(store: "EffectivenessStore | None") -> None:
    """Register the shared EffectivenessStore instance for cross-module access."""
    global _shared_effectiveness_store
    _shared_effectiveness_store = store


def get_shared_store() -> "EffectivenessStore | None":
    """Return the shared EffectivenessStore instance, or None if not set."""
    return _shared_effectiveness_store
