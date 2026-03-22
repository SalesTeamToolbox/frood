"""Tests for effectiveness tracking (Phase 21: EFFT-01 through EFFT-05)."""

import asyncio
import os
from pathlib import Path

import pytest


class TestEffectivenessStore:
    """EFFT-01, EFFT-04, EFFT-05: EffectivenessStore SQLite operations."""

    @pytest.mark.asyncio
    async def test_record_writes_correct_schema(self, tmp_path):
        """EFFT-01: record() writes all required columns."""
        from memory.effectiveness import EffectivenessStore

        store = EffectivenessStore(tmp_path / "test.db")
        await store.record(
            tool_name="shell",
            task_type="coding",
            task_id="abc-123",
            success=True,
            duration_ms=42.5,
        )
        import aiosqlite

        async with aiosqlite.connect(tmp_path / "test.db") as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM tool_invocations") as cursor:
                rows = await cursor.fetchall()
        assert len(rows) == 1
        row = dict(rows[0])
        assert row["tool_name"] == "shell"
        assert row["task_type"] == "coding"
        assert row["task_id"] == "abc-123"
        assert row["success"] == 1
        assert row["duration_ms"] == pytest.approx(42.5)
        assert row["ts"] > 0

    @pytest.mark.asyncio
    async def test_record_multiple_rows(self, tmp_path):
        """Multiple record() calls produce multiple rows."""
        from memory.effectiveness import EffectivenessStore

        store = EffectivenessStore(tmp_path / "test.db")
        for i in range(5):
            await store.record("tool_a", "coding", f"task-{i}", True, 10.0 + i)
        import aiosqlite

        async with aiosqlite.connect(tmp_path / "test.db") as db:
            async with db.execute("SELECT COUNT(*) FROM tool_invocations") as cursor:
                count = (await cursor.fetchone())[0]
        assert count == 5

    @pytest.mark.asyncio
    async def test_record_failure_stored_as_zero(self, tmp_path):
        """success=False stored as integer 0."""
        from memory.effectiveness import EffectivenessStore

        store = EffectivenessStore(tmp_path / "test.db")
        await store.record("tool_a", "coding", "task-1", False, 100.0)
        import aiosqlite

        async with aiosqlite.connect(tmp_path / "test.db") as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT success FROM tool_invocations") as cursor:
                row = await cursor.fetchone()
        assert dict(row)["success"] == 0

    @pytest.mark.asyncio
    async def test_graceful_degradation_unwritable(self, tmp_path):
        """EFFT-05: record() with unwritable path does not raise."""
        from memory.effectiveness import EffectivenessStore

        store = EffectivenessStore(tmp_path / "no_such_dir" / "sub" / "deep" / "test.db")
        # Sabotage the path to something that cannot be created
        store._db_path = (
            Path("/dev/null/impossible/test.db")
            if os.name != "nt"
            else Path("Z:\\nonexistent\\test.db")
        )
        # Should not raise
        await store.record("tool_a", "coding", "task-1", True, 10.0)
        assert store._available is False

    @pytest.mark.asyncio
    async def test_graceful_degradation_missing_dir(self, tmp_path):
        """record() creates parent directories if they don't exist."""
        from memory.effectiveness import EffectivenessStore

        db_path = tmp_path / "subdir" / "deep" / "test.db"
        store = EffectivenessStore(db_path)
        await store.record("tool_a", "coding", "task-1", True, 10.0)
        assert db_path.exists()
        assert store._available is True

    @pytest.mark.asyncio
    async def test_aggregation_query(self, tmp_path):
        """EFFT-04: get_aggregated_stats returns correct success_rate and avg_duration."""
        from memory.effectiveness import EffectivenessStore

        store = EffectivenessStore(tmp_path / "test.db")
        # 3 successes + 1 failure for tool_a/coding
        await store.record("tool_a", "coding", "t1", True, 10.0)
        await store.record("tool_a", "coding", "t1", True, 20.0)
        await store.record("tool_a", "coding", "t1", True, 30.0)
        await store.record("tool_a", "coding", "t1", False, 40.0)
        stats = await store.get_aggregated_stats()
        assert len(stats) == 1
        assert stats[0]["tool_name"] == "tool_a"
        assert stats[0]["task_type"] == "coding"
        assert stats[0]["invocations"] == 4
        assert stats[0]["success_rate"] == pytest.approx(0.75)
        assert stats[0]["avg_duration_ms"] == pytest.approx(25.0)

    @pytest.mark.asyncio
    async def test_aggregation_filtered_by_tool(self, tmp_path):
        """get_aggregated_stats(tool_name=...) filters correctly."""
        from memory.effectiveness import EffectivenessStore

        store = EffectivenessStore(tmp_path / "test.db")
        await store.record("tool_a", "coding", "t1", True, 10.0)
        await store.record("tool_b", "coding", "t1", True, 20.0)
        stats = await store.get_aggregated_stats(tool_name="tool_a")
        assert len(stats) == 1
        assert stats[0]["tool_name"] == "tool_a"

    @pytest.mark.asyncio
    async def test_aggregation_filtered_by_task_type(self, tmp_path):
        """get_aggregated_stats(task_type=...) filters correctly."""
        from memory.effectiveness import EffectivenessStore

        store = EffectivenessStore(tmp_path / "test.db")
        await store.record("tool_a", "coding", "t1", True, 10.0)
        await store.record("tool_a", "debugging", "t2", True, 20.0)
        stats = await store.get_aggregated_stats(task_type="coding")
        assert len(stats) == 1
        assert stats[0]["task_type"] == "coding"

    @pytest.mark.asyncio
    async def test_is_available_after_success(self, tmp_path):
        """is_available returns True after successful record."""
        from memory.effectiveness import EffectivenessStore

        store = EffectivenessStore(tmp_path / "test.db")
        await store.record("tool_a", "coding", "t1", True, 10.0)
        assert store.is_available is True

    @pytest.mark.asyncio
    async def test_get_task_records(self, tmp_path):
        """get_task_records returns all records for a task_id."""
        from memory.effectiveness import EffectivenessStore

        store = EffectivenessStore(tmp_path / "test.db")
        await store.record("tool_a", "coding", "task-42", True, 10.0)
        await store.record("tool_b", "coding", "task-42", False, 20.0)
        await store.record("tool_a", "coding", "task-99", True, 30.0)
        records = await store.get_task_records("task-42")
        assert len(records) == 2
        assert all(r["task_id"] == "task-42" for r in records)


class TestEffectivenessRecommendations:
    """RETR-05, RETR-06: EffectivenessStore.get_recommendations() method."""

    @pytest.mark.asyncio
    async def test_returns_top_tools_by_success_rate(self, tmp_path):
        """RETR-05: Returns tools ranked by success_rate DESC."""
        from memory.effectiveness import EffectivenessStore

        store = EffectivenessStore(tmp_path / "test.db")
        # tool_a: 5/5 = 100% success
        for _ in range(5):
            await store.record("tool_a", "coding", "t1", True, 10.0)
        # tool_b: 4/5 = 80% success
        for _ in range(4):
            await store.record("tool_b", "coding", "t1", True, 20.0)
        await store.record("tool_b", "coding", "t1", False, 20.0)
        # tool_c: 3/5 = 60% success
        for _ in range(3):
            await store.record("tool_c", "coding", "t1", True, 15.0)
        for _ in range(2):
            await store.record("tool_c", "coding", "t1", False, 15.0)
        recs = await store.get_recommendations("coding", min_observations=5, top_k=3)
        assert len(recs) == 3
        assert recs[0]["tool_name"] == "tool_a"
        assert recs[0]["success_rate"] == pytest.approx(1.0)
        assert recs[1]["tool_name"] == "tool_b"
        assert recs[1]["success_rate"] == pytest.approx(0.8)
        assert recs[2]["tool_name"] == "tool_c"
        assert recs[2]["success_rate"] == pytest.approx(0.6)

    @pytest.mark.asyncio
    async def test_excludes_tools_below_min_observations(self, tmp_path):
        """RETR-06: Tools with < min_observations are excluded."""
        from memory.effectiveness import EffectivenessStore

        store = EffectivenessStore(tmp_path / "test.db")
        # tool_a: 5 invocations (meets threshold)
        for _ in range(5):
            await store.record("tool_a", "coding", "t1", True, 10.0)
        # tool_b: 3 invocations (below threshold of 5)
        for _ in range(3):
            await store.record("tool_b", "coding", "t1", True, 10.0)
        recs = await store.get_recommendations("coding", min_observations=5)
        assert len(recs) == 1
        assert recs[0]["tool_name"] == "tool_a"

    @pytest.mark.asyncio
    async def test_tie_break_by_avg_duration(self, tmp_path):
        """D-08: Identical success_rate ties broken by avg_duration_ms ASC (faster wins)."""
        from memory.effectiveness import EffectivenessStore

        store = EffectivenessStore(tmp_path / "test.db")
        # tool_slow: 100% success, 200ms avg
        for _ in range(5):
            await store.record("tool_slow", "coding", "t1", True, 200.0)
        # tool_fast: 100% success, 50ms avg
        for _ in range(5):
            await store.record("tool_fast", "coding", "t1", True, 50.0)
        recs = await store.get_recommendations("coding", min_observations=5)
        assert len(recs) == 2
        assert recs[0]["tool_name"] == "tool_fast"
        assert recs[1]["tool_name"] == "tool_slow"

    @pytest.mark.asyncio
    async def test_empty_db_returns_empty_list(self, tmp_path):
        """RETR-06: No data returns [] silently."""
        from memory.effectiveness import EffectivenessStore

        store = EffectivenessStore(tmp_path / "test.db")
        recs = await store.get_recommendations("coding", min_observations=5)
        assert recs == []

    @pytest.mark.asyncio
    async def test_top_k_cap(self, tmp_path):
        """D-10: At most top_k results returned even when more tools qualify."""
        from memory.effectiveness import EffectivenessStore

        store = EffectivenessStore(tmp_path / "test.db")
        for i in range(5):
            tool_name = f"tool_{i}"
            for _ in range(5):
                await store.record(tool_name, "coding", "t1", True, 10.0 + i)
        recs = await store.get_recommendations("coding", min_observations=5, top_k=3)
        assert len(recs) == 3

    @pytest.mark.asyncio
    async def test_graceful_degradation_bad_path(self, tmp_path):
        """Returns [] without raising on unwritable DB path."""
        from memory.effectiveness import EffectivenessStore

        store = EffectivenessStore(tmp_path / "test.db")
        import os

        store._db_path = (
            Path("/dev/null/impossible/test.db")
            if os.name != "nt"
            else Path("Z:\\nonexistent\\test.db")
        )
        recs = await store.get_recommendations("coding")
        assert recs == []


class TestToolRegistryTracking:
    """EFFT-02: ToolRegistry fire-and-forget tracking."""

    @pytest.mark.asyncio
    async def test_execute_records_to_effectiveness_store(self, tmp_path):
        """ToolRegistry.execute() fires a background task to record."""
        from memory.effectiveness import EffectivenessStore
        from tools.base import Tool, ToolResult
        from tools.registry import ToolRegistry

        class DummyTool(Tool):
            @property
            def name(self):
                return "dummy"

            @property
            def description(self):
                return "test"

            @property
            def parameters(self):
                return {"type": "object", "properties": {}}

            async def execute(self, **kwargs):
                return ToolResult(output="ok")

        store = EffectivenessStore(tmp_path / "test.db")
        registry = ToolRegistry(effectiveness_store=store)
        registry.register(DummyTool())

        result = await registry.execute("dummy")
        assert result.success is True

        # Give the background task time to complete
        await asyncio.sleep(0.2)

        import aiosqlite

        async with aiosqlite.connect(tmp_path / "test.db") as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM tool_invocations") as cursor:
                rows = await cursor.fetchall()
        assert len(rows) == 1
        row = dict(rows[0])
        assert row["tool_name"] == "dummy"
        assert row["success"] == 1
        assert row["duration_ms"] > 0

    @pytest.mark.asyncio
    async def test_execute_returns_before_record_completes(self, tmp_path):
        """EFFT-02: Tool result returns immediately, not after SQLite write."""
        import time

        from memory.effectiveness import EffectivenessStore
        from tools.base import Tool, ToolResult
        from tools.registry import ToolRegistry

        class FastTool(Tool):
            @property
            def name(self):
                return "fast"

            @property
            def description(self):
                return "test"

            @property
            def parameters(self):
                return {"type": "object", "properties": {}}

            async def execute(self, **kwargs):
                return ToolResult(output="fast")

        store = EffectivenessStore(tmp_path / "test.db")
        registry = ToolRegistry(effectiveness_store=store)
        registry.register(FastTool())

        start = time.perf_counter_ns()
        result = await registry.execute("fast")
        elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000

        assert result.output == "fast"
        # Tool execution + return should be well under 50ms
        # (SQLite write would add 3-15ms if awaited)
        assert elapsed_ms < 50

    @pytest.mark.asyncio
    async def test_execute_records_failure(self, tmp_path):
        """Failed tool executions are also recorded with success=0."""
        from memory.effectiveness import EffectivenessStore
        from tools.base import Tool
        from tools.registry import ToolRegistry

        class FailTool(Tool):
            @property
            def name(self):
                return "fail"

            @property
            def description(self):
                return "test"

            @property
            def parameters(self):
                return {"type": "object", "properties": {}}

            async def execute(self, **kwargs):
                raise ValueError("intentional failure")

        store = EffectivenessStore(tmp_path / "test.db")
        registry = ToolRegistry(effectiveness_store=store)
        registry.register(FailTool())

        result = await registry.execute("fail")
        assert result.success is False

        await asyncio.sleep(0.2)

        import aiosqlite

        async with aiosqlite.connect(tmp_path / "test.db") as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM tool_invocations") as cursor:
                rows = await cursor.fetchall()
        assert len(rows) == 1
        assert dict(rows[0])["success"] == 0

    @pytest.mark.asyncio
    async def test_execute_without_store_works(self):
        """ToolRegistry without effectiveness_store still executes tools normally."""
        from tools.base import Tool, ToolResult
        from tools.registry import ToolRegistry

        class SimpleTool(Tool):
            @property
            def name(self):
                return "simple"

            @property
            def description(self):
                return "test"

            @property
            def parameters(self):
                return {"type": "object", "properties": {}}

            async def execute(self, **kwargs):
                return ToolResult(output="ok")

        registry = ToolRegistry()
        registry.register(SimpleTool())
        result = await registry.execute("simple")
        assert result.output == "ok"
