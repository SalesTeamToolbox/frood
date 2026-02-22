"""Tests for enhanced memory backends: Qdrant, Redis, and Consolidation."""

import json
import tempfile
import time
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import asdict

from memory.qdrant_store import QdrantStore, QdrantConfig, QDRANT_AVAILABLE
from memory.redis_session import RedisSessionBackend, RedisConfig, REDIS_AVAILABLE
from memory.consolidation import ConsolidationPipeline, ConversationSummary
from memory.session import SessionManager, SessionMessage
from memory.store import MemoryStore
from memory.embeddings import EmbeddingStore


# ── Qdrant Backend Tests ──────────────────────────────────────────────────


class TestQdrantConfig:
    def test_default_config(self):
        config = QdrantConfig()
        assert config.url == ""
        assert config.collection_prefix == "agent42"
        assert config.vector_dim == 1536

    def test_custom_config(self):
        config = QdrantConfig(
            url="http://localhost:6333",
            api_key="test-key",
            collection_prefix="myapp",
        )
        assert config.url == "http://localhost:6333"
        assert config.api_key == "test-key"
        assert config.collection_prefix == "myapp"


class TestQdrantStoreUnavailable:
    """Tests when qdrant-client is not installed."""

    def test_unavailable_without_library(self):
        with patch("memory.qdrant_store.QDRANT_AVAILABLE", False):
            store = QdrantStore(QdrantConfig())
            assert store.is_available is False

    def test_search_returns_empty_when_unavailable(self):
        with patch("memory.qdrant_store.QDRANT_AVAILABLE", False):
            store = QdrantStore(QdrantConfig())
            results = store.search("memory", [0.1] * 1536)
            assert results == []

    def test_upsert_returns_zero_when_unavailable(self):
        with patch("memory.qdrant_store.QDRANT_AVAILABLE", False):
            store = QdrantStore(QdrantConfig())
            count = store.upsert_vectors(
                "memory", ["test"], [[0.1] * 1536]
            )
            assert count == 0


@pytest.mark.skipif(not QDRANT_AVAILABLE, reason="qdrant-client not installed")
class TestQdrantStoreWithMock:
    """Tests with a mocked Qdrant client."""

    def setup_method(self):
        self.config = QdrantConfig(collection_prefix="test")
        self.store = QdrantStore(self.config)
        # Replace client with mock
        self.mock_client = MagicMock()
        self.store._client = self.mock_client

        # Mock get_collections to return empty
        mock_collections = MagicMock()
        mock_collections.collections = []
        self.mock_client.get_collections.return_value = mock_collections

    def test_is_available(self):
        assert self.store.is_available is True

    def test_collection_name(self):
        assert self.store._collection_name("memory") == "test_memory"
        assert self.store._collection_name("history") == "test_history"

    def test_upsert_vectors(self):
        self.store.upsert_vectors(
            "memory",
            ["hello world", "test text"],
            [[0.1] * 1536, [0.2] * 1536],
            [{"source": "memory"}, {"source": "memory"}],
        )
        assert self.mock_client.upsert.called

    def test_search_returns_formatted_results(self):
        # Mock search response
        mock_hit = MagicMock()
        mock_hit.payload = {
            "text": "Python is great",
            "source": "memory",
            "section": "tech",
            "timestamp": 1234567890.0,
        }
        mock_hit.score = 0.95
        self.mock_client.search.return_value = [mock_hit]

        results = self.store.search("memory", [0.1] * 1536, top_k=5)
        assert len(results) == 1
        assert results[0]["text"] == "Python is great"
        assert results[0]["source"] == "memory"
        assert results[0]["score"] == 0.95

    def test_clear_collection(self):
        self.store.clear_collection("memory")
        assert self.mock_client.delete_collection.called

    def test_collection_count(self):
        mock_info = MagicMock()
        mock_info.points_count = 42
        self.mock_client.get_collection.return_value = mock_info
        count = self.store.collection_count("memory")
        assert count == 42


# ── Redis Backend Tests ──────────────────────────────────────────────────


class TestRedisConfig:
    def test_default_config(self):
        config = RedisConfig()
        assert config.url == ""
        assert config.session_ttl_days == 7
        assert config.embedding_cache_ttl_hours == 24

    def test_custom_config(self):
        config = RedisConfig(
            url="redis://localhost:6379/1",
            password="secret",
            session_ttl_days=14,
        )
        assert config.url == "redis://localhost:6379/1"
        assert config.session_ttl_days == 14


class TestRedisSessionUnavailable:
    """Tests when redis is not installed."""

    def test_unavailable_without_library(self):
        with patch("memory.redis_session.REDIS_AVAILABLE", False):
            backend = RedisSessionBackend(RedisConfig())
            assert backend.is_available is False

    def test_get_history_returns_none_when_unavailable(self):
        with patch("memory.redis_session.REDIS_AVAILABLE", False):
            backend = RedisSessionBackend(RedisConfig())
            assert backend.get_history("discord", "ch1") is None

    def test_get_cached_embedding_returns_none_when_unavailable(self):
        with patch("memory.redis_session.REDIS_AVAILABLE", False):
            backend = RedisSessionBackend(RedisConfig())
            assert backend.get_cached_embedding("test") is None


@pytest.mark.skipif(not REDIS_AVAILABLE, reason="redis not installed")
class TestRedisSessionWithMock:
    """Tests with a mocked Redis client."""

    def setup_method(self):
        self.config = RedisConfig(url="redis://localhost:6379/0")
        self.backend = RedisSessionBackend(self.config)
        # Replace client with mock
        self.mock_client = MagicMock()
        self.backend._client = self.mock_client

    def test_is_available(self):
        assert self.backend.is_available is True

    def test_add_message(self):
        msg = {"role": "user", "content": "hello", "timestamp": time.time()}
        self.backend.add_message("discord", "ch1", msg)
        assert self.mock_client.pipeline.called

    def test_get_history_cache_miss(self):
        self.mock_client.exists.return_value = False
        result = self.backend.get_history("discord", "ch1")
        assert result is None

    def test_get_history_cache_hit(self):
        self.mock_client.exists.return_value = True
        self.mock_client.lrange.return_value = [
            json.dumps({"role": "user", "content": "hi", "timestamp": 1.0}),
            json.dumps({"role": "assistant", "content": "hello!", "timestamp": 2.0}),
        ]
        result = self.backend.get_history("discord", "ch1")
        assert len(result) == 2
        assert result[0]["role"] == "user"
        assert result[1]["role"] == "assistant"

    def test_clear_session(self):
        self.backend.clear_session("discord", "ch1")
        assert self.mock_client.delete.called

    def test_embedding_cache_miss(self):
        self.mock_client.get.return_value = None
        result = self.backend.get_cached_embedding("test text")
        assert result is None

    def test_embedding_cache_hit(self):
        self.mock_client.get.return_value = json.dumps([0.1, 0.2, 0.3])
        result = self.backend.get_cached_embedding("test text")
        assert result == [0.1, 0.2, 0.3]

    def test_cache_embedding(self):
        self.backend.cache_embedding("test text", [0.1, 0.2, 0.3])
        assert self.mock_client.setex.called

    def test_memory_version(self):
        self.mock_client.get.return_value = "5"
        assert self.backend.get_memory_version() == 5

    def test_increment_memory_version(self):
        self.mock_client.incr.return_value = 6
        assert self.backend.increment_memory_version() == 6


# ── Consolidation Pipeline Tests ─────────────────────────────────────────


class TestConsolidationPipeline:
    def test_unavailable_without_router(self):
        pipeline = ConsolidationPipeline()
        assert pipeline.is_available is False

    def test_unavailable_without_embeddings(self):
        pipeline = ConsolidationPipeline(model_router=MagicMock())
        assert pipeline.is_available is False

    def test_available_with_router_and_embeddings(self):
        mock_embeddings = MagicMock()
        mock_embeddings.is_available = True
        pipeline = ConsolidationPipeline(
            model_router=MagicMock(),
            embedding_store=mock_embeddings,
        )
        assert pipeline.is_available is True

    def test_extract_topics(self):
        summary = """## Summary
Some stuff happened.

## Key Topics
- Python programming
- Database design
- API integration

## Important Details
- Uses PostgreSQL
"""
        topics = ConsolidationPipeline._extract_topics(summary)
        assert len(topics) == 3
        assert "Python programming" in topics
        assert "Database design" in topics
        assert "API integration" in topics

    def test_extract_topics_empty(self):
        topics = ConsolidationPipeline._extract_topics("No topics here.")
        assert topics == []

    @pytest.mark.asyncio
    async def test_summarize_messages(self):
        mock_router = MagicMock()
        mock_router.complete = AsyncMock(return_value=(
            "## Summary\nDiscussed Python project.\n\n"
            "## Key Topics\n- Python\n- Testing\n\n"
            "## Important Details\n- Uses pytest"
        ))

        mock_embeddings = MagicMock()
        mock_embeddings.is_available = True

        pipeline = ConsolidationPipeline(
            model_router=mock_router,
            embedding_store=mock_embeddings,
        )

        messages = [
            {"role": "user", "content": "Let's discuss Python", "timestamp": 1.0},
            {"role": "assistant", "content": "Sure! What about it?", "timestamp": 2.0},
        ]

        summary = await pipeline.summarize_messages(messages, "discord", "ch1")
        assert summary is not None
        assert summary.channel_type == "discord"
        assert summary.message_count == 2
        assert "Python" in summary.topics

    @pytest.mark.asyncio
    async def test_summarize_empty_messages(self):
        pipeline = ConsolidationPipeline(model_router=MagicMock())
        result = await pipeline.summarize_messages([], "test", "ch1")
        assert result is None


# ── Integration Tests: Session Manager with Redis ────────────────────────


class TestSessionManagerWithRedis:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_session_manager_without_redis(self):
        """SessionManager works normally without Redis backend."""
        mgr = SessionManager(self.tmpdir)
        msg = SessionMessage(role="user", content="hello")
        mgr.add_message("test", "ch1", msg)
        history = mgr.get_history("test", "ch1")
        assert len(history) == 1
        assert history[0].content == "hello"

    def test_session_manager_with_unavailable_redis(self):
        """SessionManager degrades gracefully with unavailable Redis."""
        mock_redis = MagicMock()
        mock_redis.is_available = False

        mgr = SessionManager(self.tmpdir, redis_backend=mock_redis)
        msg = SessionMessage(role="user", content="hello")
        mgr.add_message("test", "ch1", msg)
        history = mgr.get_history("test", "ch1")
        assert len(history) == 1

    def test_clear_session_clears_redis(self):
        """Clearing a session also clears Redis cache."""
        mock_redis = MagicMock()
        mock_redis.is_available = True

        mgr = SessionManager(self.tmpdir, redis_backend=mock_redis)
        msg = SessionMessage(role="user", content="hello")
        mgr.add_message("test", "ch1", msg)
        mgr.clear_session("test", "ch1")

        mock_redis.clear_session.assert_called_with("test", "ch1")


# ── Integration Tests: MemoryStore with backends ─────────────────────────


class TestMemoryStoreWithBackends:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_memory_store_without_backends(self):
        """MemoryStore works normally without Qdrant/Redis."""
        store = MemoryStore(self.tmpdir)
        assert "Agent42 Memory" in store.read_memory()
        store.log_event("test", "Test event")
        assert "test" in store.read_history()

    def test_memory_store_with_qdrant(self):
        """MemoryStore initializes embeddings with Qdrant backend."""
        mock_qdrant = MagicMock()
        mock_qdrant.is_available = True

        with patch.dict("os.environ", {}, clear=True):
            store = MemoryStore(self.tmpdir, qdrant_store=mock_qdrant)
            assert store.embeddings._qdrant is mock_qdrant

    def test_memory_store_with_redis(self):
        """MemoryStore initializes embeddings with Redis backend."""
        mock_redis = MagicMock()
        mock_redis.is_available = True

        with patch.dict("os.environ", {}, clear=True):
            store = MemoryStore(self.tmpdir, redis_backend=mock_redis)
            assert store.embeddings._redis is mock_redis

    def test_update_memory_increments_redis_version(self):
        """Updating memory notifies Redis for cache invalidation."""
        mock_redis = MagicMock()
        mock_redis.is_available = True

        with patch.dict("os.environ", {}, clear=True):
            store = MemoryStore(self.tmpdir, redis_backend=mock_redis)
            store.update_memory("# New Content")
            mock_redis.increment_memory_version.assert_called_once()


# ── Integration Tests: EmbeddingStore with backends ──────────────────────


class TestEmbeddingStoreWithBackends:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.store_path = Path(self.tmpdir) / "embeddings.json"

    def test_embedding_store_without_backends(self):
        """EmbeddingStore works normally without Qdrant/Redis."""
        store = EmbeddingStore(self.store_path)
        assert store.qdrant_available is False

    def test_embedding_store_qdrant_available(self):
        """qdrant_available property reflects Qdrant status."""
        mock_qdrant = MagicMock()
        mock_qdrant.is_available = True
        store = EmbeddingStore(self.store_path, qdrant_store=mock_qdrant)
        assert store.qdrant_available is True

    @pytest.mark.asyncio
    async def test_embed_text_caches_in_redis(self):
        """embed_text should cache results in Redis."""
        mock_redis = MagicMock()
        mock_redis.is_available = True
        mock_redis.get_cached_embedding.return_value = None  # Cache miss

        store = EmbeddingStore(self.store_path, redis_backend=mock_redis)
        store._client = MagicMock()
        store._model = "test-model"

        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=[0.1, 0.2, 0.3])]
        store._client.embeddings = MagicMock()
        store._client.embeddings.create = AsyncMock(return_value=mock_response)

        vector = await store.embed_text("hello")
        assert vector == [0.1, 0.2, 0.3]

        # Should have cached the result
        mock_redis.cache_embedding.assert_called_once_with("hello", [0.1, 0.2, 0.3])

    @pytest.mark.asyncio
    async def test_embed_text_uses_redis_cache(self):
        """embed_text should return cached result from Redis."""
        mock_redis = MagicMock()
        mock_redis.is_available = True
        mock_redis.get_cached_embedding.return_value = [0.4, 0.5, 0.6]

        store = EmbeddingStore(self.store_path, redis_backend=mock_redis)
        store._client = MagicMock()
        store._model = "test-model"

        vector = await store.embed_text("hello")
        assert vector == [0.4, 0.5, 0.6]

        # Should NOT have called the API
        store._client.embeddings.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_search_uses_qdrant_when_available(self):
        """search should use Qdrant backend when available."""
        mock_qdrant = MagicMock()
        mock_qdrant.is_available = True
        mock_qdrant.search.return_value = [
            {"text": "result from qdrant", "source": "memory", "section": "test", "score": 0.9, "metadata": {}}
        ]

        store = EmbeddingStore(self.store_path, qdrant_store=mock_qdrant)
        store._client = MagicMock()
        store._model = "test-model"

        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=[0.1] * 1536)]
        store._client.embeddings = MagicMock()
        store._client.embeddings.create = AsyncMock(return_value=mock_response)

        results = await store.search("test query", top_k=5)
        assert len(results) >= 1
        # Qdrant search was called
        assert mock_qdrant.search.called

    @pytest.mark.asyncio
    async def test_search_falls_back_to_json(self):
        """search should fall back to JSON when Qdrant unavailable."""
        from memory.embeddings import EmbeddingEntry

        store = EmbeddingStore(self.store_path)
        store._client = MagicMock()
        store._model = "test-model"
        store._entries = [
            EmbeddingEntry(
                text="Python is great", vector=[1.0, 0.0],
                source="memory", section="tech"
            ),
        ]
        store._loaded = True

        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=[0.9, 0.1])]
        store._client.embeddings = MagicMock()
        store._client.embeddings.create = AsyncMock(return_value=mock_response)

        results = await store.search("programming", top_k=5)
        assert len(results) == 1
        assert results[0]["text"] == "Python is great"


# ── Tests for Gap 7: Embedding cache hash length ──────────────────────────


class TestEmbeddingCacheHashLength:
    """Verify embedding cache uses full SHA-256 to avoid collisions."""

    def test_cache_key_uses_full_hash(self):
        """Cache key should use full 64-char SHA-256 hex, not truncated."""
        import hashlib

        # Create backend with a mock client directly
        config = RedisConfig(url="redis://localhost:6379/0")
        backend = RedisSessionBackend.__new__(RedisSessionBackend)
        backend.config = config
        backend._session_ttl = config.session_ttl_days * 86400
        backend._embed_ttl = config.embedding_cache_ttl_hours * 3600
        backend._client = MagicMock()

        backend.cache_embedding("test text", [0.1, 0.2])

        # Get the key that was passed to setex
        call_args = backend._client.setex.call_args
        key = call_args[0][0]  # First positional arg is the key

        # Extract the hash portion (after "agent42:embed_cache:")
        hash_part = key.split(":")[-1]
        # Full SHA-256 is 64 hex chars
        assert len(hash_part) == 64


# ── Tests for Gap 8: Batch embed with Redis cache ─────────────────────────


class TestBatchEmbedWithCache:
    """Verify embed_texts() uses Redis cache for individual items."""

    @pytest.mark.asyncio
    async def test_embed_texts_uses_cache(self):
        """embed_texts should check Redis cache and skip cached items."""
        mock_redis = MagicMock()
        mock_redis.is_available = True
        # First text is cached, second is not
        mock_redis.get_cached_embedding.side_effect = [
            [0.1, 0.2, 0.3],  # Cache hit for "cached text"
            None,              # Cache miss for "uncached text"
        ]

        store = EmbeddingStore(
            Path(tempfile.mkdtemp()) / "embeddings.json",
            redis_backend=mock_redis,
        )
        store._client = MagicMock()
        store._model = "test-model"

        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=[0.4, 0.5, 0.6])]
        store._client.embeddings = MagicMock()
        store._client.embeddings.create = AsyncMock(return_value=mock_response)

        vectors = await store.embed_texts(["cached text", "uncached text"])

        assert vectors[0] == [0.1, 0.2, 0.3]  # From cache
        assert vectors[1] == [0.4, 0.5, 0.6]  # From API

        # API should only be called once (for the uncached text)
        store._client.embeddings.create.assert_called_once()
        # The uncached result should be cached
        mock_redis.cache_embedding.assert_called_once_with(
            "uncached text", [0.4, 0.5, 0.6]
        )

    @pytest.mark.asyncio
    async def test_embed_texts_all_cached(self):
        """embed_texts should skip API entirely when all texts are cached."""
        mock_redis = MagicMock()
        mock_redis.is_available = True
        mock_redis.get_cached_embedding.side_effect = [
            [0.1, 0.2],
            [0.3, 0.4],
        ]

        store = EmbeddingStore(
            Path(tempfile.mkdtemp()) / "embeddings.json",
            redis_backend=mock_redis,
        )
        store._client = MagicMock()
        store._model = "test-model"
        store._client.embeddings = MagicMock()
        store._client.embeddings.create = AsyncMock()

        vectors = await store.embed_texts(["a", "b"])

        assert vectors == [[0.1, 0.2], [0.3, 0.4]]
        # API should NOT have been called
        store._client.embeddings.create.assert_not_called()


# ── Tests for Gap 10: Qdrant point ID format ──────────────────────────────


class TestQdrantPointIdFormat:
    """Verify point IDs are valid UUIDs for Qdrant compatibility."""

    def test_point_id_is_valid_uuid(self):
        """_make_point_id should return a valid UUID string."""
        import uuid
        config = QdrantConfig()
        store = QdrantStore(config)
        point_id = store._make_point_id("test text", "memory")
        # Should be parseable as a UUID
        parsed = uuid.UUID(point_id)
        assert str(parsed) == point_id

    def test_point_id_is_deterministic(self):
        """Same input should always produce the same UUID."""
        config = QdrantConfig()
        store = QdrantStore(config)
        id1 = store._make_point_id("hello world", "memory")
        id2 = store._make_point_id("hello world", "memory")
        assert id1 == id2

    def test_different_inputs_produce_different_ids(self):
        """Different inputs should produce different UUIDs."""
        config = QdrantConfig()
        store = QdrantStore(config)
        id1 = store._make_point_id("text a", "memory")
        id2 = store._make_point_id("text b", "memory")
        assert id1 != id2
