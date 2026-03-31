"""Tests for migrate.py — Migration CLI for Agent42 -> Paperclip."""

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import aiosqlite
import pytest


def make_mock_point(
    id="orig-id-1",
    text="hello world",
    source="memory",
    agent_id="agent-abc",
    company_id="old-comp",
):
    return SimpleNamespace(
        id=id,
        vector=[0.1] * 1536,
        payload={
            "text": text,
            "source": source,
            "agent_id": agent_id,
            "company_id": company_id,
        },
    )


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------


class TestBuildParser:
    def test_build_parser_required_args(self):
        from migrate import build_parser

        parser = build_parser()
        # All 4 required args present — should succeed
        args = parser.parse_args(
            [
                "--agent42-db",
                "/tmp/eff.db",
                "--qdrant-url",
                "http://localhost:6333",
                "--target-qdrant-url",
                "http://localhost:6334",
                "--paperclip-company-id",
                "comp-123",
            ]
        )
        assert args.agent42_db == "/tmp/eff.db"
        assert args.qdrant_url == "http://localhost:6333"
        assert args.target_qdrant_url == "http://localhost:6334"
        assert args.paperclip_company_id == "comp-123"

        # Missing any one required arg raises SystemExit
        required_combos = [
            ["--qdrant-url", "u", "--target-qdrant-url", "u", "--paperclip-company-id", "c"],
            ["--agent42-db", "d", "--target-qdrant-url", "u", "--paperclip-company-id", "c"],
            ["--agent42-db", "d", "--qdrant-url", "u", "--paperclip-company-id", "c"],
            ["--agent42-db", "d", "--qdrant-url", "u", "--target-qdrant-url", "u"],
        ]
        for combo in required_combos:
            with pytest.raises(SystemExit):
                parser.parse_args(combo)

    def test_missing_collection_prefix_flag(self):
        from migrate import build_parser

        parser = build_parser()
        # Default collection prefix
        args = parser.parse_args(
            [
                "--agent42-db",
                "d",
                "--qdrant-url",
                "u",
                "--target-qdrant-url",
                "u2",
                "--paperclip-company-id",
                "c",
            ]
        )
        assert args.collection_prefix == "agent42"

        # Custom collection prefix
        args2 = parser.parse_args(
            [
                "--agent42-db",
                "d",
                "--qdrant-url",
                "u",
                "--target-qdrant-url",
                "u2",
                "--paperclip-company-id",
                "c",
                "--collection-prefix",
                "custom",
            ]
        )
        assert args2.collection_prefix == "custom"


# ---------------------------------------------------------------------------
# remap_point tests
# ---------------------------------------------------------------------------


class TestRemapPoint:
    def test_remap_point_sets_company_id(self):
        from migrate import remap_point

        pt = make_mock_point(agent_id="agent-xyz", company_id="old-comp")
        result = remap_point(pt, "new-company-123")

        assert result.payload["company_id"] == "new-company-123"
        assert result.payload["agent_id"] == "agent-xyz"

    def test_remap_point_regenerates_uuid5(self):
        from migrate import remap_point

        pt = make_mock_point(id="orig-id-1")
        result = remap_point(pt, "comp-1")

        # Must be a valid UUID string
        parsed = uuid.UUID(result.id)
        assert str(parsed) == result.id

        # Must differ from original
        assert result.id != "orig-id-1"

    def test_remap_point_uuid5_deterministic(self):
        from migrate import remap_point

        pt1 = make_mock_point()
        pt2 = make_mock_point()

        r1 = remap_point(pt1, "comp-1")
        r2 = remap_point(pt2, "comp-1")

        assert r1.id == r2.id


# ---------------------------------------------------------------------------
# migrate_collection tests
# ---------------------------------------------------------------------------


class TestMigrateCollection:
    def test_migrate_qdrant_remaps_company_id(self):
        from migrate import migrate_collection

        points = [
            make_mock_point(id=f"id-{i}", text=f"text-{i}", company_id="old") for i in range(3)
        ]

        src = MagicMock()
        src.scroll.return_value = (points, None)

        dst = MagicMock()

        total = asyncio.get_event_loop().run_until_complete(
            migrate_collection(src, dst, "agent42_memory", "target-comp", 100, False)
        )

        assert total == 3
        dst.upsert.assert_called_once()
        upserted = dst.upsert.call_args[1]["points"]
        assert len(upserted) == 3
        for p in upserted:
            assert p.payload["company_id"] == "target-comp"

    def test_dry_run_no_writes(self):
        from migrate import migrate_collection

        points = [make_mock_point(id="id-1")]

        src = MagicMock()
        src.scroll.return_value = (points, None)

        dst = MagicMock()

        total = asyncio.get_event_loop().run_until_complete(
            migrate_collection(src, dst, "agent42_memory", "target-comp", 100, True)
        )

        assert total == 1
        src.scroll.assert_called_once()
        dst.upsert.assert_not_called()


# ---------------------------------------------------------------------------
# migrate_effectiveness tests
# ---------------------------------------------------------------------------


class TestMigrateEffectiveness:
    def test_migrate_effectiveness_preserves_agent_id(self, tmp_path):
        from migrate import migrate_effectiveness

        src_db = str(tmp_path / "source.db")
        dst_db = str(tmp_path / "target.db")

        async def _run():
            # Create source DB with schema and insert rows
            async with aiosqlite.connect(src_db) as db:
                await db.execute("""
                    CREATE TABLE tool_invocations (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        tool_name TEXT NOT NULL,
                        task_type TEXT NOT NULL,
                        task_id TEXT NOT NULL,
                        success INTEGER NOT NULL,
                        duration_ms REAL NOT NULL,
                        ts REAL NOT NULL,
                        agent_id TEXT DEFAULT ''
                    )
                """)
                await db.execute("""
                    CREATE TABLE routing_decisions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        run_id TEXT NOT NULL,
                        agent_id TEXT NOT NULL,
                        company_id TEXT NOT NULL DEFAULT '',
                        provider TEXT NOT NULL,
                        model TEXT NOT NULL,
                        tier TEXT NOT NULL,
                        task_category TEXT NOT NULL,
                        ts REAL NOT NULL
                    )
                """)
                await db.execute("""
                    CREATE TABLE spend_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        agent_id TEXT NOT NULL,
                        company_id TEXT NOT NULL DEFAULT '',
                        provider TEXT NOT NULL,
                        model TEXT NOT NULL,
                        input_tokens INTEGER NOT NULL DEFAULT 0,
                        output_tokens INTEGER NOT NULL DEFAULT 0,
                        cost_usd REAL NOT NULL DEFAULT 0.0,
                        hour_bucket TEXT NOT NULL,
                        ts REAL NOT NULL
                    )
                """)
                await db.execute("""
                    CREATE TABLE run_transcripts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        run_id TEXT NOT NULL UNIQUE,
                        agent_id TEXT NOT NULL,
                        company_id TEXT NOT NULL DEFAULT '',
                        task_type TEXT NOT NULL DEFAULT '',
                        summary TEXT NOT NULL,
                        extracted INTEGER NOT NULL DEFAULT 0,
                        ts REAL NOT NULL
                    )
                """)
                # Insert test data
                await db.execute(
                    "INSERT INTO tool_invocations (tool_name, task_type, task_id, success, duration_ms, ts, agent_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    ("shell", "coding", "t-1", 1, 42.5, 1000.0, "agent-abc"),
                )
                await db.execute(
                    "INSERT INTO tool_invocations (tool_name, task_type, task_id, success, duration_ms, ts, agent_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    ("search", "research", "t-2", 1, 100.0, 2000.0, "agent-xyz"),
                )
                await db.execute(
                    "INSERT INTO routing_decisions (run_id, agent_id, company_id, provider, model, tier, task_category, ts) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    ("run-1", "agent-abc", "old-comp", "openai", "gpt-4o", "L1", "coding", 1000.0),
                )
                await db.execute(
                    "INSERT INTO spend_history (agent_id, company_id, provider, model, input_tokens, output_tokens, cost_usd, hour_bucket, ts) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        "agent-abc",
                        "old-comp",
                        "openai",
                        "gpt-4o",
                        500,
                        200,
                        0.01,
                        "2026-03-31T22",
                        1000.0,
                    ),
                )
                await db.execute(
                    "INSERT INTO run_transcripts (run_id, agent_id, company_id, task_type, summary, extracted, ts) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    ("run-1", "agent-abc", "old-comp", "coding", "Did stuff", 0, 1000.0),
                )
                await db.commit()

            # Run migration
            counts = await migrate_effectiveness(src_db, dst_db)

            # Verify target DB
            async with aiosqlite.connect(dst_db) as db:
                db.row_factory = aiosqlite.Row
                # Check tool_invocations
                cursor = await db.execute("SELECT agent_id FROM tool_invocations ORDER BY id")
                rows = await cursor.fetchall()
                assert [r["agent_id"] for r in rows] == ["agent-abc", "agent-xyz"]

                # Check routing_decisions
                cursor = await db.execute("SELECT agent_id FROM routing_decisions")
                rows = await cursor.fetchall()
                assert [r["agent_id"] for r in rows] == ["agent-abc"]

                # Check spend_history
                cursor = await db.execute("SELECT agent_id FROM spend_history")
                rows = await cursor.fetchall()
                assert [r["agent_id"] for r in rows] == ["agent-abc"]

                # Check run_transcripts
                cursor = await db.execute("SELECT agent_id FROM run_transcripts")
                rows = await cursor.fetchall()
                assert [r["agent_id"] for r in rows] == ["agent-abc"]

            assert counts["tool_invocations"] == 2
            assert counts["routing_decisions"] == 1
            assert counts["spend_history"] == 1
            assert counts["run_transcripts"] == 1

        asyncio.get_event_loop().run_until_complete(_run())
