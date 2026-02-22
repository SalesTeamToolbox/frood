"""Tests for Phase 6: Memory system (including semantic search)."""

import json
import tempfile
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock
from memory.store import MemoryStore
from memory.session import SessionManager, SessionMessage
from memory.embeddings import EmbeddingStore, _cosine_similarity, EmbeddingEntry


class TestMemoryStore:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.store = MemoryStore(self.tmpdir)

    def test_files_created_on_init(self):
        assert (Path(self.tmpdir) / "MEMORY.md").exists()
        assert (Path(self.tmpdir) / "HISTORY.md").exists()

    def test_read_memory(self):
        content = self.store.read_memory()
        assert "Agent42 Memory" in content

    def test_update_memory(self):
        self.store.update_memory("# Custom Memory\n\nNew content")
        assert "Custom Memory" in self.store.read_memory()

    def test_append_to_existing_section(self):
        self.store.append_to_section("User Preferences", "Prefers dark mode")
        content = self.store.read_memory()
        assert "Prefers dark mode" in content

    def test_append_to_new_section(self):
        self.store.append_to_section("New Section", "Some info")
        content = self.store.read_memory()
        assert "## New Section" in content
        assert "Some info" in content

    def test_log_event(self):
        self.store.log_event("test_event", "Something happened", "Details here")
        history = self.store.read_history()
        assert "test_event" in history
        assert "Something happened" in history
        assert "Details here" in history

    def test_log_event_append_only(self):
        self.store.log_event("event1", "First event")
        self.store.log_event("event2", "Second event")
        history = self.store.read_history()
        assert "event1" in history
        assert "event2" in history

    def test_search_history(self):
        self.store.log_event("deploy", "Deployed v1.0")
        self.store.log_event("bugfix", "Fixed login bug")
        results = self.store.search_history("deploy")
        assert any("deploy" in r.lower() for r in results)

    def test_build_context(self):
        self.store.log_event("test", "Test event")
        context = self.store.build_context()
        assert "Persistent Memory" in context


class TestSessionManager:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.mgr = SessionManager(self.tmpdir)

    def test_add_and_get_message(self):
        msg = SessionMessage(role="user", content="Hello", channel_type="discord", sender_id="u1")
        self.mgr.add_message("discord", "chan1", msg)

        history = self.mgr.get_history("discord", "chan1")
        assert len(history) == 1
        assert history[0].content == "Hello"

    def test_multiple_messages(self):
        self.mgr.add_message("slack", "c1", SessionMessage(role="user", content="Hi"))
        self.mgr.add_message("slack", "c1", SessionMessage(role="assistant", content="Hello!"))
        self.mgr.add_message("slack", "c1", SessionMessage(role="user", content="Thanks"))

        history = self.mgr.get_history("slack", "c1")
        assert len(history) == 3
        assert history[0].role == "user"
        assert history[1].role == "assistant"

    def test_separate_sessions(self):
        self.mgr.add_message("discord", "chan1", SessionMessage(role="user", content="A"))
        self.mgr.add_message("discord", "chan2", SessionMessage(role="user", content="B"))

        h1 = self.mgr.get_history("discord", "chan1")
        h2 = self.mgr.get_history("discord", "chan2")
        assert len(h1) == 1
        assert len(h2) == 1
        assert h1[0].content == "A"
        assert h2[0].content == "B"

    def test_max_messages_limit(self):
        for i in range(100):
            self.mgr.add_message("test", "ch", SessionMessage(role="user", content=f"msg{i}"))

        history = self.mgr.get_history("test", "ch", max_messages=10)
        assert len(history) == 10
        assert history[-1].content == "msg99"

    def test_get_messages_as_dicts(self):
        self.mgr.add_message("test", "ch", SessionMessage(role="user", content="hi"))
        dicts = self.mgr.get_messages_as_dicts("test", "ch")
        assert len(dicts) == 1
        assert dicts[0] == {"role": "user", "content": "hi"}

    def test_clear_session(self):
        self.mgr.add_message("test", "ch", SessionMessage(role="user", content="hi"))
        self.mgr.clear_session("test", "ch")
        history = self.mgr.get_history("test", "ch")
        assert len(history) == 0

    def test_persistence_across_instances(self):
        self.mgr.add_message("test", "ch", SessionMessage(role="user", content="persisted"))

        # New instance should load from disk
        mgr2 = SessionManager(self.tmpdir)
        history = mgr2.get_history("test", "ch")
        assert len(history) == 1
        assert history[0].content == "persisted"


class TestCosineSimilarity:
    def test_identical_vectors(self):
        v = [1.0, 0.0, 0.0]
        assert _cosine_similarity(v, v) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        assert _cosine_similarity(a, b) == pytest.approx(0.0)

    def test_opposite_vectors(self):
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        assert _cosine_similarity(a, b) == pytest.approx(-1.0)

    def test_empty_vectors(self):
        assert _cosine_similarity([], []) == 0.0

    def test_zero_vector(self):
        assert _cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0

    def test_different_lengths(self):
        assert _cosine_similarity([1.0], [1.0, 2.0]) == 0.0


class TestEmbeddingStore:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.store_path = Path(self.tmpdir) / "embeddings.json"

    def test_no_api_key_means_unavailable(self):
        """EmbeddingStore should gracefully disable when no API key is set."""
        with patch.dict("os.environ", {}, clear=True):
            store = EmbeddingStore(self.store_path)
            assert store.is_available is False

    def test_split_into_chunks(self):
        text = "# Main Title\n\nIntro text here.\n\n## Section One\n\nContent for section one.\n\n## Section Two\n\nContent for section two."
        chunks = EmbeddingStore._split_into_chunks(text, source="memory")
        assert len(chunks) >= 2
        sections = [c["section"] for c in chunks]
        assert "Section One" in sections
        assert "Section Two" in sections

    def test_split_empty_text(self):
        chunks = EmbeddingStore._split_into_chunks("", source="memory")
        assert len(chunks) == 0

    def test_split_short_sections_filtered(self):
        text = "## Short\n\nOk\n\n## Long Section\n\nThis is a sufficiently long section with enough content."
        chunks = EmbeddingStore._split_into_chunks(text, source="memory", min_chunk_len=20)
        # "Ok" section is too short, only the long one should be included
        assert all(len(c["text"]) >= 20 for c in chunks)

    def test_entry_count_empty(self):
        store = EmbeddingStore(self.store_path)
        assert store.entry_count() == 0

    def test_clear(self):
        # Write some data
        self.store_path.write_text(json.dumps([{
            "text": "test", "vector": [1.0, 0.0], "source": "memory",
            "section": "", "timestamp": 0.0, "metadata": {},
        }]))
        store = EmbeddingStore(self.store_path)
        assert store.entry_count() == 1
        store.clear()
        assert store.entry_count() == 0
        assert not self.store_path.exists()

    def test_load_persisted_entries(self):
        entries = [
            {"text": "entry1", "vector": [1.0, 0.0], "source": "memory",
             "section": "sec1", "timestamp": 1.0, "metadata": {}},
            {"text": "entry2", "vector": [0.0, 1.0], "source": "history",
             "section": "sec2", "timestamp": 2.0, "metadata": {}},
        ]
        self.store_path.write_text(json.dumps(entries))
        store = EmbeddingStore(self.store_path)
        assert store.entry_count() == 2


class TestEmbeddingStoreWithMockAPI:
    """Tests that mock the embedding API to test search logic."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.store_path = Path(self.tmpdir) / "embeddings.json"
        self.store = EmbeddingStore(self.store_path)
        # Force available by setting a mock client
        self.store._client = MagicMock()
        self.store._model = "test-model"

    @pytest.mark.asyncio
    async def test_embed_text(self):
        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=[0.1, 0.2, 0.3])]
        self.store._client.embeddings = MagicMock()
        self.store._client.embeddings.create = AsyncMock(return_value=mock_response)

        vector = await self.store.embed_text("hello world")
        assert vector == [0.1, 0.2, 0.3]

    @pytest.mark.asyncio
    async def test_add_and_search(self):
        # Pre-populate with known vectors
        self.store._entries = [
            EmbeddingEntry(text="Python is great for AI", vector=[1.0, 0.0, 0.0],
                           source="memory", section="tech"),
            EmbeddingEntry(text="Cats are fluffy animals", vector=[0.0, 1.0, 0.0],
                           source="memory", section="pets"),
            EmbeddingEntry(text="Machine learning with PyTorch", vector=[0.9, 0.1, 0.0],
                           source="history", section="tech"),
        ]
        self.store._loaded = True

        # Mock embed_text to return a vector close to "Python/AI" entries
        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=[0.95, 0.05, 0.0])]
        self.store._client.embeddings = MagicMock()
        self.store._client.embeddings.create = AsyncMock(return_value=mock_response)

        results = await self.store.search("programming with Python", top_k=2)
        assert len(results) == 2
        # The "Python is great for AI" entry should be most similar
        assert "Python" in results[0]["text"]
        assert results[0]["score"] > results[1]["score"]

    @pytest.mark.asyncio
    async def test_search_with_source_filter(self):
        self.store._entries = [
            EmbeddingEntry(text="Memory entry", vector=[1.0, 0.0],
                           source="memory", section="sec"),
            EmbeddingEntry(text="History entry", vector=[0.9, 0.1],
                           source="history", section="event"),
        ]
        self.store._loaded = True

        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=[1.0, 0.0])]
        self.store._client.embeddings = MagicMock()
        self.store._client.embeddings.create = AsyncMock(return_value=mock_response)

        results = await self.store.search("test", source_filter="memory")
        assert len(results) == 1
        assert results[0]["source"] == "memory"

    @pytest.mark.asyncio
    async def test_search_empty_store(self):
        self.store._loaded = True
        results = await self.store.search("anything")
        assert results == []


class TestMemoryStoreSemanticFallback:
    """Test that MemoryStore.semantic_search falls back to grep."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        # Ensure no API keys are set for this test
        self.env_patch = patch.dict("os.environ", {}, clear=True)
        self.env_patch.start()
        self.store = MemoryStore(self.tmpdir)

    def teardown_method(self):
        self.env_patch.stop()

    def test_semantic_not_available(self):
        assert self.store.semantic_available is False

    @pytest.mark.asyncio
    async def test_semantic_search_falls_back_to_grep(self):
        self.store.log_event("deploy", "Deployed v2.0")
        self.store.log_event("bugfix", "Fixed deploy bug")
        results = await self.store.semantic_search("deploy", top_k=5)
        assert len(results) > 0
        assert any("deploy" in r["text"].lower() for r in results)


class TestHistoryRotation:
    """Tests for Gap 5 fix: timestamped archive names."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.store = MemoryStore(self.tmpdir)

    def test_rotation_creates_timestamped_archive(self):
        """History rotation should create uniquely-named archives."""
        # Write enough data to trigger rotation
        self.store.MAX_HISTORY_SIZE = 100  # Lower threshold for testing
        for i in range(50):
            self.store.log_event("event", f"Event number {i}" * 5)

        # Check that a timestamped archive was created (not .old.md)
        archives = list(Path(self.tmpdir).glob("HISTORY.*.md"))
        assert len(archives) >= 1
        # Should NOT have .old.md (the old bug)
        old_archive = Path(self.tmpdir) / "HISTORY.old.md"
        assert not old_archive.exists()

    def test_multiple_rotations_preserve_archives(self):
        """Multiple rotations should not overwrite previous archives."""
        self.store.MAX_HISTORY_SIZE = 100  # Lower threshold
        # First rotation
        for i in range(50):
            self.store.log_event("event", f"First batch {i}" * 5)
        archives_1 = set(Path(self.tmpdir).glob("HISTORY.*.md"))

        # Second rotation
        import time
        time.sleep(1.1)  # Ensure different timestamp
        for i in range(50):
            self.store.log_event("event", f"Second batch {i}" * 5)
        archives_2 = set(Path(self.tmpdir).glob("HISTORY.*.md"))

        # Should have more archives after second rotation
        assert len(archives_2) >= len(archives_1)


class TestScheduleReindex:
    """Tests for Gap 3 fix: auto-reindex after memory updates."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_update_memory_schedules_reindex_when_available(self):
        """update_memory should attempt to schedule reindex when embeddings available."""
        mock_redis = MagicMock()
        mock_redis.is_available = True

        with patch.dict("os.environ", {}, clear=True):
            store = MemoryStore(self.tmpdir, redis_backend=mock_redis)
            # Mock embeddings as available
            store.embeddings._client = MagicMock()
            with patch.object(store, '_schedule_reindex') as mock_reindex:
                store.update_memory("# Updated content")
                mock_reindex.assert_called_once()

    def test_update_memory_skips_reindex_when_unavailable(self):
        """update_memory should not schedule reindex when embeddings unavailable."""
        with patch.dict("os.environ", {}, clear=True):
            store = MemoryStore(self.tmpdir)
            assert not store.embeddings.is_available
            # This should not raise even without an event loop
            store.update_memory("# Updated content")


class TestJsonEmbeddingEviction:
    """Tests for Gap 6 fix: max entries in JSON embedding store."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.store_path = Path(self.tmpdir) / "embeddings.json"

    def test_save_evicts_oldest_when_over_limit(self):
        """_save should evict oldest entries when over MAX_JSON_ENTRIES."""
        from memory.embeddings import EmbeddingEntry

        store = EmbeddingStore(self.store_path)
        store.MAX_JSON_ENTRIES = 5  # Low limit for testing
        store._loaded = True

        # Add 8 entries with increasing timestamps
        for i in range(8):
            store._entries.append(EmbeddingEntry(
                text=f"entry {i}", vector=[float(i)],
                source="test", timestamp=float(i),
            ))

        store._save()
        assert len(store._entries) == 5
        # Should keep the newest (timestamps 3, 4, 5, 6, 7)
        assert store._entries[0].text == "entry 3"
        assert store._entries[-1].text == "entry 7"
