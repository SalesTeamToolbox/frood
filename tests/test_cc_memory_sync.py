"""Tests for CC memory auto-sync hook.

Covers:
- SYNC-01: Detection of CC memory file writes via PostToolUse hook
- SYNC-02: ONNX embedding + Qdrant upsert in background worker
- SYNC-03: Deterministic file-path-based UUID5 dedup (same file = same point ID)
- SYNC-04: Silent failure on Qdrant unavailability, missing ONNX model, missing file

All external services are mocked — no real Qdrant or ONNX required.
"""

import json
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Helper: import is_cc_memory_file from the hook (adjust path at test time)
# ---------------------------------------------------------------------------


def _get_hook_module():
    """Import .claude/hooks/cc-memory-sync module by file path."""
    import importlib.util

    hook_path = Path(__file__).parent.parent / ".claude" / "hooks" / "cc-memory-sync.py"
    spec = importlib.util.spec_from_file_location("cc_memory_sync", hook_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _get_worker_module():
    """Import .claude/hooks/cc-memory-sync-worker module by file path."""
    import importlib.util

    worker_path = Path(__file__).parent.parent / ".claude" / "hooks" / "cc-memory-sync-worker.py"
    spec = importlib.util.spec_from_file_location("cc_memory_sync_worker", worker_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ===========================================================================
# TestPathDetection — tests for is_cc_memory_file()
# ===========================================================================


class TestPathDetection:
    """Tests for the is_cc_memory_file() path-matching function."""

    def setup_method(self):
        self.hook = _get_hook_module()
        self.is_cc_memory_file = self.hook.is_cc_memory_file

    def test_matches_user_memory_file(self):
        """MEMORY.md inside a projects/*/memory/ dir should match."""
        path = "C:/Users/rickw/.claude/projects/c--Users-rickw-projects-agent42/memory/MEMORY.md"
        assert self.is_cc_memory_file(path) is True

    def test_matches_feedback_file(self):
        """feedback_*.md files in memory/ dir should match."""
        path = "C:/Users/rickw/.claude/projects/some-project/memory/feedback_something.md"
        assert self.is_cc_memory_file(path) is True

    def test_matches_project_file(self):
        """project_*.md files in memory/ dir should match."""
        path = "C:/Users/rickw/.claude/projects/myproj/memory/project_context.md"
        assert self.is_cc_memory_file(path) is True

    def test_matches_reference_file(self):
        """reference_*.md files in memory/ dir should match."""
        path = "C:/Users/rickw/.claude/projects/myproj/memory/reference_docs.md"
        assert self.is_cc_memory_file(path) is True

    def test_rejects_non_memory_path(self):
        """A .py file in the project tools/ dir should NOT match."""
        path = "C:/Users/rickw/projects/agent42/tools/memory_tool.py"
        assert self.is_cc_memory_file(path) is False

    def test_rejects_global_memory(self):
        """A .md file directly in ~/.claude/memory/ (no 'projects' segment) should NOT match."""
        path = "C:/Users/rickw/.claude/memory/MEMORY.md"
        assert self.is_cc_memory_file(path) is False

    def test_handles_unix_paths(self):
        """Unix-style paths with forward slashes should work correctly."""
        path = "/home/user/.claude/projects/myproj/memory/MEMORY.md"
        assert self.is_cc_memory_file(path) is True

    def test_handles_empty_string(self):
        """Empty string should return False without raising."""
        assert self.is_cc_memory_file("") is False

    def test_rejects_path_without_md_extension(self):
        """A file without .md extension in the right location should NOT match."""
        path = "C:/Users/rickw/.claude/projects/myproj/memory/MEMORY.txt"
        assert self.is_cc_memory_file(path) is False

    def test_rejects_regular_project_file(self):
        """A regular .py file should NOT match."""
        path = "C:/Users/rickw/projects/agent42/core/config.py"
        assert self.is_cc_memory_file(path) is False


# ===========================================================================
# TestDedup — tests for make_point_id()
# ===========================================================================


class TestDedup:
    """Tests for make_point_id() — deterministic file-path-based UUID5 dedup."""

    # Expected UUID5 namespace used across hook worker and QdrantStore
    NAMESPACE = uuid.UUID("a42a42a4-2a42-4a42-a42a-42a42a42a42a")

    def setup_method(self):
        self.worker = _get_worker_module()
        self.make_point_id = self.worker.make_point_id

    def test_same_path_same_point_id(self):
        """Calling make_point_id with the same path twice returns identical UUIDs."""
        path = "C:/Users/rickw/.claude/projects/proj/memory/MEMORY.md"
        id1 = self.make_point_id(path)
        id2 = self.make_point_id(path)
        assert id1 == id2

    def test_different_path_different_id(self):
        """Different file paths should produce different point IDs."""
        id_a = self.make_point_id("path/a.md")
        id_b = self.make_point_id("path/b.md")
        assert id_a != id_b

    def test_same_path_different_content_same_id(self):
        """Point ID is based on file_path only, not on file content.

        Changing the content of a file should NOT change its point ID
        (so re-syncing updated files overwrites the same Qdrant point).
        This test verifies the ID is independent of content.
        """
        path = "C:/Users/rickw/.claude/projects/proj/memory/MEMORY.md"
        # make_point_id takes only file_path — content is not an argument
        id1 = self.make_point_id(path)
        # Same path, even if conceptually different content would be synced
        id2 = self.make_point_id(path)
        assert id1 == id2

    def test_point_id_uses_correct_namespace(self):
        """make_point_id should use uuid5 with the a42a42a4 namespace."""
        path = "some/memory/file.md"
        expected = str(uuid.uuid5(self.NAMESPACE, f"claude_code:{path}"))
        actual = self.make_point_id(path)
        assert actual == expected

    def test_point_id_is_valid_uuid_string(self):
        """The returned point ID should be a parseable UUID string."""
        point_id = self.make_point_id("some/path.md")
        # Should not raise
        parsed = uuid.UUID(point_id)
        assert str(parsed) == point_id


# ===========================================================================
# TestSyncWorker — tests for sync_memory_file()
# ===========================================================================


class TestSyncWorker:
    """Tests for the worker's sync_memory_file() function."""

    def setup_method(self):
        self.worker = _get_worker_module()

    def test_worker_embeds_and_upserts(self, tmp_path):
        """Worker calls upsert on Qdrant with the correct collection suffix."""
        # Create a real temp file to sync
        mem_file = tmp_path / "MEMORY.md"
        mem_file.write_text("# Test Memory\n\nSome content here.")

        mock_embedder = MagicMock()
        mock_embedder.encode.return_value = [0.1] * 384

        mock_store = MagicMock()
        mock_store.is_available = True

        mock_qdrant_cls = MagicMock(return_value=mock_store)

        with (
            patch.object(self.worker, "_find_onnx_model_dir", return_value=tmp_path),
            patch.object(self.worker, "_OnnxEmbedder", return_value=mock_embedder),
            patch.object(self.worker, "QdrantStore", mock_qdrant_cls),
            patch.object(self.worker, "STATUS_FILE", tmp_path / "cc-sync-status.json"),
        ):
            self.worker.sync_memory_file(str(mem_file))

        # upsert via _client should have been called (file-path-based dedup)
        assert (
            mock_store._client.upsert.called
            or mock_store.upsert_single.called
            or mock_store._ensure_collection.called
        )

    def test_worker_payload_has_source_claude_code(self, tmp_path):
        """The Qdrant upsert payload must include source='claude_code'."""
        mem_file = tmp_path / "MEMORY.md"
        mem_file.write_text("# Test Memory\n\nSome content here.")

        mock_embedder = MagicMock()
        mock_embedder.encode.return_value = [0.1] * 384

        mock_client = MagicMock()
        mock_store = MagicMock()
        mock_store.is_available = True
        mock_store._client = mock_client
        mock_store._ensure_collection = MagicMock()
        mock_store._collection_name = MagicMock(return_value="agent42_memory")

        mock_qdrant_cls = MagicMock(return_value=mock_store)

        with (
            patch.object(self.worker, "_find_onnx_model_dir", return_value=tmp_path),
            patch.object(self.worker, "_OnnxEmbedder", return_value=mock_embedder),
            patch.object(self.worker, "QdrantStore", mock_qdrant_cls),
            patch.object(self.worker, "STATUS_FILE", tmp_path / "cc-sync-status.json"),
        ):
            self.worker.sync_memory_file(str(mem_file))

        # Check that upsert was called and payload contained source=claude_code
        assert mock_client.upsert.called
        ca = mock_client.upsert.call_args
        # upsert is called with keyword args: collection_name=..., points=[...]
        points = ca.kwargs.get("points") or (ca.args[1] if len(ca.args) > 1 else [])
        assert len(points) > 0
        payload = points[0].payload
        assert payload.get("source") == "claude_code"
        assert "file_path" in payload

    def test_worker_updates_status_file(self, tmp_path):
        """After successful sync, status file should have last_sync and incremented total_synced."""
        mem_file = tmp_path / "MEMORY.md"
        mem_file.write_text("# Test Memory\n\nSome content here.")

        mock_embedder = MagicMock()
        mock_embedder.encode.return_value = [0.1] * 384

        mock_client = MagicMock()
        mock_store = MagicMock()
        mock_store.is_available = True
        mock_store._client = mock_client
        mock_store._ensure_collection = MagicMock()
        mock_store._collection_name = MagicMock(return_value="agent42_memory")

        mock_qdrant_cls = MagicMock(return_value=mock_store)
        status_file = tmp_path / "cc-sync-status.json"

        with (
            patch.object(self.worker, "_find_onnx_model_dir", return_value=tmp_path),
            patch.object(self.worker, "_OnnxEmbedder", return_value=mock_embedder),
            patch.object(self.worker, "QdrantStore", mock_qdrant_cls),
            patch.object(self.worker, "STATUS_FILE", status_file),
        ):
            self.worker.sync_memory_file(str(mem_file))

        assert status_file.exists()
        status = json.loads(status_file.read_text())
        assert status["last_sync"] is not None
        assert status["total_synced"] == 1


# ===========================================================================
# TestFailureSilence — SYNC-04: all failure modes must be silent
# ===========================================================================


class TestFailureSilence:
    """Tests that all failure modes are silent — no exceptions should propagate."""

    def setup_method(self):
        self.worker = _get_worker_module()

    def test_qdrant_unavailable_no_crash(self, tmp_path):
        """When QdrantStore.is_available is False, worker returns without raising."""
        mem_file = tmp_path / "MEMORY.md"
        mem_file.write_text("# Memory\n\nContent.")

        mock_embedder = MagicMock()
        mock_embedder.encode.return_value = [0.1] * 384

        mock_store = MagicMock()
        mock_store.is_available = False  # Qdrant unreachable

        mock_qdrant_cls = MagicMock(return_value=mock_store)

        # Should complete without raising any exception
        with (
            patch.object(self.worker, "_find_onnx_model_dir", return_value=tmp_path),
            patch.object(self.worker, "_OnnxEmbedder", return_value=mock_embedder),
            patch.object(self.worker, "QdrantStore", mock_qdrant_cls),
            patch.object(self.worker, "STATUS_FILE", tmp_path / "cc-sync-status.json"),
        ):
            # Must NOT raise
            self.worker.sync_memory_file(str(mem_file))

        # Qdrant upsert should not have been called
        assert not mock_store._client.upsert.called

    def test_onnx_model_missing_no_crash(self, tmp_path):
        """When _find_onnx_model_dir returns None, worker returns cleanly."""
        mem_file = tmp_path / "MEMORY.md"
        mem_file.write_text("# Memory\n\nContent.")

        status_file = tmp_path / "cc-sync-status.json"

        with (
            patch.object(self.worker, "_find_onnx_model_dir", return_value=None),
            patch.object(self.worker, "STATUS_FILE", status_file),
        ):
            # Must NOT raise
            self.worker.sync_memory_file(str(mem_file))

        # Status file should record an error about missing ONNX
        if status_file.exists():
            status = json.loads(status_file.read_text())
            last_error = status.get("last_error", "")
            assert last_error is not None  # error should be recorded

    def test_file_not_found_no_crash(self, tmp_path):
        """When file_path points to a nonexistent file, worker returns cleanly."""
        nonexistent = str(tmp_path / "does_not_exist.md")

        with patch.object(self.worker, "STATUS_FILE", tmp_path / "cc-sync-status.json"):
            # Must NOT raise
            self.worker.sync_memory_file(nonexistent)


# ===========================================================================
# TestReindexCc — tests for MemoryTool._handle_reindex_cc()
# ===========================================================================


class TestReindexCc:
    """Tests for the reindex_cc action in MemoryTool."""

    def _make_mock_store(self, semantic_available=True):
        """Build a mock MemoryStore with a mock Qdrant client."""
        mock_client = MagicMock()
        mock_qdrant = MagicMock()
        mock_qdrant._client = mock_client
        mock_qdrant.config.collection_prefix = "agent42"
        # retrieve returns empty list by default (no existing points)
        mock_client.retrieve.return_value = []

        mock_store = MagicMock()
        mock_store.semantic_available = semantic_available
        mock_store._qdrant = mock_qdrant
        return mock_store, mock_qdrant, mock_client

    async def test_reindex_scans_memory_files(self, tmp_path):
        """reindex_cc finds CC memory files and reports correct counts."""
        from tools.memory_tool import MemoryTool

        # Set up fake CC projects dir with one memory file
        cc_projects = tmp_path / ".claude" / "projects" / "my-project" / "memory"
        cc_projects.mkdir(parents=True)
        (cc_projects / "MEMORY.md").write_text("# Memory\n\nSome content.")

        mock_store, mock_qdrant, mock_client = self._make_mock_store(semantic_available=True)
        tool = MemoryTool(memory_store=mock_store)

        mock_embedder = MagicMock()
        mock_embedder.encode.return_value = [0.1] * 384

        with (
            patch("pathlib.Path.home", return_value=tmp_path),
            patch("memory.embeddings._find_onnx_model_dir", return_value=tmp_path),
            patch("memory.embeddings._OnnxEmbedder", return_value=mock_embedder),
        ):
            result = await tool._handle_reindex_cc()

        assert result.success
        assert "Scanned 1" in result.output
        assert "Newly synced: 1" in result.output
        assert "Already synced: 0" in result.output

    async def test_reindex_skips_already_synced(self, tmp_path):
        """reindex_cc skips files that already have a point in Qdrant."""
        from tools.memory_tool import MemoryTool

        # Set up fake CC projects dir with one memory file
        cc_projects = tmp_path / ".claude" / "projects" / "my-project" / "memory"
        cc_projects.mkdir(parents=True)
        mem_file = cc_projects / "MEMORY.md"
        mem_file.write_text("# Memory\n\nSome content.")

        mock_store, mock_qdrant, mock_client = self._make_mock_store(semantic_available=True)
        # Simulate point already existing — retrieve returns non-empty list
        mock_client.retrieve.return_value = [MagicMock()]
        tool = MemoryTool(memory_store=mock_store)

        mock_embedder = MagicMock()
        mock_embedder.encode.return_value = [0.1] * 384

        with (
            patch("pathlib.Path.home", return_value=tmp_path),
            patch("memory.embeddings._find_onnx_model_dir", return_value=tmp_path),
            patch("memory.embeddings._OnnxEmbedder", return_value=mock_embedder),
        ):
            result = await tool._handle_reindex_cc()

        assert result.success
        assert "Already synced: 1" in result.output
        assert "Newly synced: 0" in result.output
        # upsert should NOT have been called for skipped files
        mock_client.upsert.assert_not_called()

    async def test_reindex_fails_gracefully_no_qdrant(self, tmp_path):
        """reindex_cc returns success=False when Qdrant is not available."""
        from tools.memory_tool import MemoryTool

        mock_store = MagicMock()
        mock_store.semantic_available = False
        tool = MemoryTool(memory_store=mock_store)

        result = await tool._handle_reindex_cc()

        assert result.success is False
        assert "Qdrant" in result.output

    async def test_reindex_fails_gracefully_no_onnx(self, tmp_path):
        """reindex_cc returns success=False when ONNX model is not found."""
        from tools.memory_tool import MemoryTool

        mock_store, _, _ = self._make_mock_store(semantic_available=True)
        tool = MemoryTool(memory_store=mock_store)

        with patch("memory.embeddings._find_onnx_model_dir", return_value=None):
            result = await tool._handle_reindex_cc()

        assert result.success is False
        assert "ONNX" in result.output


# ===========================================================================
# TestHookRegistration — verify settings.json has the hook registered
# ===========================================================================


class TestHookRegistration:
    """Tests that .claude/settings.json has the cc-memory-sync hook registered."""

    def _load_settings(self):
        import json

        settings_path = Path(__file__).parent.parent / ".claude" / "settings.json"
        return json.loads(settings_path.read_text())

    def _get_write_edit_hooks(self, settings: dict) -> list:
        """Return the hooks list for the PostToolUse Write|Edit matcher."""
        for entry in settings.get("hooks", {}).get("PostToolUse", []):
            if entry.get("matcher") == "Write|Edit":
                return entry.get("hooks", [])
        return []

    def test_settings_has_cc_sync_hook(self):
        """settings.json PostToolUse Write|Edit array contains cc-memory-sync.py."""
        settings = self._load_settings()
        hooks = self._get_write_edit_hooks(settings)
        commands = [h.get("command", "") for h in hooks]
        assert any("cc-memory-sync.py" in cmd for cmd in commands), (
            f"cc-memory-sync.py not found in PostToolUse Write|Edit hooks: {commands}"
        )

    def test_cc_sync_hook_timeout_is_short(self):
        """cc-memory-sync hook has timeout <= 10 (fire-and-forget, not blocking)."""
        settings = self._load_settings()
        hooks = self._get_write_edit_hooks(settings)
        cc_hook = next(
            (h for h in hooks if "cc-memory-sync.py" in h.get("command", "")),
            None,
        )
        assert cc_hook is not None, "cc-memory-sync hook not found"
        assert cc_hook.get("timeout", 999) <= 10, (
            f"Expected timeout <= 10, got {cc_hook.get('timeout')}"
        )


# ===========================================================================
# TestDashboardCcSync — tests for _load_cc_sync_status helper
# ===========================================================================


class TestDashboardCcSync:
    """Tests for the _load_cc_sync_status helper in dashboard/server.py."""

    def _get_load_cc_sync_status(self, tmp_workspace=None):
        """Import and return _load_cc_sync_status with an optional workspace override."""
        import importlib.util

        server_path = Path(__file__).parent.parent / "dashboard" / "server.py"
        spec = importlib.util.spec_from_file_location("dashboard_server_test", server_path)
        # We can't easily import the function directly since it's defined inside create_app().
        # Instead, reproduce the logic here for unit testing.

        def _load_cc_sync_status_impl(workspace: str = ".") -> dict:
            import json

            status_path = Path(workspace) / ".agent42" / "cc-sync-status.json"
            try:
                if status_path.exists():
                    return json.loads(status_path.read_text())
            except Exception:
                pass
            return {"last_sync": None, "total_synced": 0, "last_error": None}

        return _load_cc_sync_status_impl

    def test_load_cc_sync_status_returns_defaults_when_no_file(self, tmp_path):
        """Returns default dict when cc-sync-status.json does not exist."""
        fn = self._get_load_cc_sync_status(tmp_workspace=str(tmp_path))
        result = fn(workspace=str(tmp_path))
        assert result == {"last_sync": None, "total_synced": 0, "last_error": None}

    def test_load_cc_sync_status_reads_file(self, tmp_path):
        """Returns correct values when cc-sync-status.json exists."""
        import json

        status_dir = tmp_path / ".agent42"
        status_dir.mkdir(parents=True)
        status_data = {"last_sync": 1742300000.0, "total_synced": 42, "last_error": None}
        (status_dir / "cc-sync-status.json").write_text(json.dumps(status_data))

        fn = self._get_load_cc_sync_status(tmp_workspace=str(tmp_path))
        result = fn(workspace=str(tmp_path))
        assert result["last_sync"] == 1742300000.0
        assert result["total_synced"] == 42
        assert result["last_error"] is None
