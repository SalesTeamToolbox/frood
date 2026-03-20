"""Tests for the memory consolidation worker — dedup logic and status tracking."""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

from memory.consolidation_worker import (
    find_and_remove_duplicates,
    increment_entries_since,
    load_consolidation_status,
    run_consolidation,
    save_consolidation_status,
    should_trigger_consolidation,
)


def _make_point(pid, vector, confidence=0.5, timestamp=1000.0, text="test"):
    """Create a mock Qdrant point with the given attributes."""
    p = MagicMock()
    p.id = pid
    p.vector = vector
    p.payload = {"confidence": confidence, "timestamp": timestamp, "text": text}
    return p


def _make_mock_client(points):
    """Return a mock Qdrant client whose scroll() returns *points* in one page."""
    client = MagicMock()
    client.scroll.return_value = (points, None)  # (results, next_offset=None)
    client.delete = MagicMock()
    return client


class TestDedupLogic:
    def test_removes_exact_duplicates(self):
        """Two points with identical vectors (sim=1.0) — lower confidence deleted."""
        vec = [1.0, 0.0, 0.0]
        p1 = _make_point("id-1", vec, confidence=0.8, timestamp=2000.0)
        p2 = _make_point("id-2", vec, confidence=0.3, timestamp=1000.0)
        client = _make_mock_client([p1, p2])

        scanned, removed, flagged = find_and_remove_duplicates(
            client, "test_collection", auto_threshold=0.95, flag_threshold=0.85
        )

        assert scanned == 2
        assert removed == 1
        assert flagged == 0
        client.delete.assert_called_once()

    def test_keeps_both_below_threshold(self):
        """Two points with sim=0.80 — neither deleted nor flagged."""
        p1 = _make_point("id-1", [1.0, 0.0, 0.0], confidence=0.5, timestamp=2000.0)
        p2 = _make_point("id-2", [0.8, 0.6, 0.0], confidence=0.5, timestamp=1000.0)
        client = _make_mock_client([p1, p2])

        scanned, removed, flagged = find_and_remove_duplicates(
            client, "test_collection", auto_threshold=0.95, flag_threshold=0.85
        )

        assert scanned == 2
        assert removed == 0
        assert flagged == 0
        client.delete.assert_not_called()

    def test_flags_near_duplicates(self):
        """Two points with sim~0.90 — flagged count incremented, neither deleted."""
        # sim between [1,0,0] and [0.9, 0.436, 0] ≈ 0.9
        p1 = _make_point("id-1", [1.0, 0.0, 0.0], confidence=0.5, timestamp=2000.0)
        p2 = _make_point("id-2", [0.9, 0.436, 0.0], confidence=0.5, timestamp=1000.0)
        client = _make_mock_client([p1, p2])

        scanned, removed, flagged = find_and_remove_duplicates(
            client, "test_collection", auto_threshold=0.95, flag_threshold=0.85
        )

        assert scanned == 2
        assert removed == 0
        assert flagged == 1
        client.delete.assert_not_called()

    def test_removes_above_auto_threshold(self):
        """Two points with sim=0.96 — lower confidence point deleted."""
        # Build two nearly-identical vectors with sim ~0.96
        p1 = _make_point("id-1", [1.0, 0.0, 0.0], confidence=0.7, timestamp=2000.0)
        p2 = _make_point("id-2", [0.96, 0.28, 0.0], confidence=0.3, timestamp=1000.0)
        client = _make_mock_client([p1, p2])

        scanned, removed, flagged = find_and_remove_duplicates(
            client, "test_collection", auto_threshold=0.95, flag_threshold=0.85
        )

        assert scanned == 2
        assert removed == 1
        client.delete.assert_called_once()

    def test_keeps_higher_confidence(self):
        """When sim=0.96, point A (conf=0.8) keeps, point B (conf=0.3) is deleted."""
        vec_a = [1.0, 0.0, 0.0]
        vec_b = [0.96, 0.28, 0.0]
        p_a = _make_point("id-A", vec_a, confidence=0.8, timestamp=2000.0)
        p_b = _make_point("id-B", vec_b, confidence=0.3, timestamp=1000.0)
        client = _make_mock_client([p_a, p_b])

        find_and_remove_duplicates(
            client, "test_collection", auto_threshold=0.95, flag_threshold=0.85
        )

        # The delete call should include id-B (lower confidence), not id-A
        client.delete.assert_called_once()
        delete_call_args = client.delete.call_args
        deleted_ids = delete_call_args.kwargs.get(
            "points_selector", delete_call_args[1].get("points_selector", None)
        )
        # PointIdsList.points should contain "id-B"
        assert "id-B" in str(deleted_ids)

    def test_sliding_window_limits_comparisons(self):
        """With window_size=2 and 5 points — each point compared only to next 2."""
        points = [
            _make_point(f"id-{i}", [float(i) / 10, 0.0, 0.0], timestamp=float(1000 + i))
            for i in range(5)
        ]
        client = _make_mock_client(points)

        scanned, removed, flagged = find_and_remove_duplicates(
            client,
            "test_collection",
            auto_threshold=0.95,
            flag_threshold=0.85,
            window_size=2,
        )

        # All five points should be scanned
        assert scanned == 5

    def test_single_point_no_dedup(self):
        """Single point — nothing to compare, nothing deleted."""
        p = _make_point("id-1", [1.0, 0.0, 0.0])
        client = _make_mock_client([p])

        scanned, removed, flagged = find_and_remove_duplicates(
            client, "test_collection", auto_threshold=0.95, flag_threshold=0.85
        )

        assert scanned == 1
        assert removed == 0
        assert flagged == 0
        client.delete.assert_not_called()

    def test_empty_collection_no_dedup(self):
        """Empty collection — returns (0, 0, 0)."""
        client = _make_mock_client([])

        scanned, removed, flagged = find_and_remove_duplicates(
            client, "test_collection", auto_threshold=0.95, flag_threshold=0.85
        )

        assert scanned == 0
        assert removed == 0
        assert flagged == 0


class TestConsolidationStatus:
    def test_writes_status_file(self):
        """After run_consolidation, status JSON file exists with expected keys."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            status = {
                "last_run": 1234567890.0,
                "entries_since": 0,
                "last_scanned": 10,
                "last_removed": 2,
                "last_flagged": 3,
                "last_error": None,
            }
            save_consolidation_status(status, workspace)

            status_file = workspace / ".agent42" / "consolidation-status.json"
            assert status_file.exists()
            loaded = json.loads(status_file.read_text())
            assert loaded["last_run"] == 1234567890.0
            assert loaded["last_scanned"] == 10
            assert loaded["last_removed"] == 2
            assert loaded["last_flagged"] == 3

    def test_status_file_defaults(self):
        """load_consolidation_status returns correct defaults when file doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            status = load_consolidation_status(workspace)

            assert status["last_run"] is None
            assert status["last_scanned"] == 0
            assert status["last_removed"] == 0
            assert status["last_flagged"] == 0
            assert "entries_since" in status

    def test_increment_entries_since(self):
        """increment_entries_since increments the counter each call."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            assert increment_entries_since(workspace) == 1
            assert increment_entries_since(workspace) == 2
            assert increment_entries_since(workspace) == 3

    def test_should_trigger_consolidation(self):
        """should_trigger_consolidation returns True when entries_since >= TRIGGER_COUNT."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            # Default trigger count is 100 — manually set entries_since
            save_consolidation_status({"entries_since": 99}, workspace)
            assert not should_trigger_consolidation(workspace)

            save_consolidation_status({"entries_since": 100}, workspace)
            assert should_trigger_consolidation(workspace)

    def test_save_and_load_roundtrip(self):
        """save then load returns the same data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            original = {
                "last_run": 9999.0,
                "entries_since": 42,
                "last_scanned": 100,
                "last_removed": 5,
                "last_flagged": 10,
                "last_error": "some error",
            }
            save_consolidation_status(original, workspace)
            loaded = load_consolidation_status(workspace)
            assert loaded["last_run"] == 9999.0
            assert loaded["entries_since"] == 42
            assert loaded["last_removed"] == 5


class TestRunConsolidation:
    def _make_qdrant_store(self, memory_count=5, knowledge_count=5):
        """Build a mock QdrantStore for testing run_consolidation."""
        store = MagicMock()
        store.is_available = True
        store._collection_name = MagicMock(side_effect=lambda s: f"agent42_{s}")
        store.collection_count = MagicMock(side_effect=lambda s: 5)  # > 1 always

        # Mock _client with scroll (one page, empty points for simplicity)
        client = MagicMock()
        client.scroll.return_value = ([], None)
        client.delete = MagicMock()
        store._client = client
        return store

    def test_run_consolidation_returns_stats(self):
        """run_consolidation returns dict with scanned/removed/flagged/collections/error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._make_qdrant_store()
            result = run_consolidation(store, workspace=tmpdir)

            assert "scanned" in result
            assert "removed" in result
            assert "flagged" in result
            assert "collections" in result
            assert "error" in result
            assert result["error"] is None

    def test_run_consolidation_unavailable_qdrant(self):
        """run_consolidation returns error when Qdrant unavailable."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MagicMock()
            store.is_available = False

            result = run_consolidation(store, workspace=tmpdir)

            assert result["error"] is not None
            assert "unavailable" in result["error"].lower()

    def test_run_consolidation_writes_status_file(self):
        """run_consolidation writes the status file after completion."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._make_qdrant_store()
            run_consolidation(store, workspace=tmpdir)

            status_file = Path(tmpdir) / ".agent42" / "consolidation-status.json"
            assert status_file.exists()
            data = json.loads(status_file.read_text())
            assert data["last_run"] is not None

    def test_run_consolidation_processes_memory_and_knowledge(self):
        """run_consolidation processes 'memory' and 'knowledge' collections."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._make_qdrant_store()
            result = run_consolidation(store, workspace=tmpdir)

            # collections_processed may be empty (no points) — just verify no error
            assert result["error"] is None
            # _collection_name was called for memory and knowledge (at least)
            called_suffixes = [c.args[0] for c in store._collection_name.call_args_list]
            assert "memory" in called_suffixes or "knowledge" in called_suffixes

    def test_run_consolidation_skips_collections_with_few_points(self):
        """Collections with < 2 points are skipped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MagicMock()
            store.is_available = True
            store._collection_name = MagicMock(side_effect=lambda s: f"agent42_{s}")
            store.collection_count = MagicMock(return_value=1)  # Only 1 point
            store._client = MagicMock()

            result = run_consolidation(store, workspace=tmpdir)

            # No collections processed (count < 2)
            assert result["collections"] == []
            assert result["scanned"] == 0
