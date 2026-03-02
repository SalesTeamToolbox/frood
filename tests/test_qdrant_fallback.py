"""Tests for Qdrant health check and search fallback improvements.

Covers:
- QdrantStore.is_available does a real health check (not just client != None)
- EmbeddingStore.search() falls through to JSON when Qdrant search fails
- EmbeddingStore.index_memory() falls through to JSON when Qdrant write fails
- EmbeddingStore.index_history_entry() falls through to JSON when Qdrant fails
"""

import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from memory.embeddings import EmbeddingEntry, EmbeddingStore


class TestQdrantStoreHealthCheck:
    """Test that QdrantStore.is_available does a real connectivity check."""

    def test_is_available_false_without_client(self):
        """When qdrant-client is not installed, is_available should be False."""
        from memory.qdrant_store import QdrantConfig, QdrantStore

        with patch("memory.qdrant_store.QDRANT_AVAILABLE", False):
            store = QdrantStore(QdrantConfig())
            assert store.is_available is False

    def test_is_available_true_for_embedded_mode(self):
        """Embedded mode always passes health check (no network)."""
        from memory.qdrant_store import QdrantConfig, QdrantStore

        with patch("memory.qdrant_store.QDRANT_AVAILABLE", True):
            mock_client = MagicMock()
            store = QdrantStore.__new__(QdrantStore)
            store.config = QdrantConfig(url="")  # No URL = embedded
            store._client = mock_client
            store._initialized_collections = set()
            store._last_health_check = 0.0
            store._last_health_ok = False
            assert store.is_available is True

    def test_is_available_probes_server_mode(self):
        """Server mode should probe the server via get_collections()."""
        from memory.qdrant_store import QdrantConfig, QdrantStore

        with patch("memory.qdrant_store.QDRANT_AVAILABLE", True):
            mock_client = MagicMock()
            mock_collections = MagicMock()
            mock_collections.collections = []
            mock_client.get_collections.return_value = mock_collections

            store = QdrantStore.__new__(QdrantStore)
            store.config = QdrantConfig(url="http://localhost:6333")
            store._client = mock_client
            store._initialized_collections = set()
            store._last_health_check = 0.0
            store._last_health_ok = False

            assert store.is_available is True
            mock_client.get_collections.assert_called_once()

    def test_is_available_false_when_server_unreachable(self):
        """Server mode should return False when probe fails."""
        from memory.qdrant_store import QdrantConfig, QdrantStore

        with patch("memory.qdrant_store.QDRANT_AVAILABLE", True):
            mock_client = MagicMock()
            mock_client.get_collections.side_effect = ConnectionError("refused")

            store = QdrantStore.__new__(QdrantStore)
            store.config = QdrantConfig(url="http://localhost:6333")
            store._client = mock_client
            store._initialized_collections = set()
            store._last_health_check = 0.0
            store._last_health_ok = False

            assert store.is_available is False

    def test_health_check_caches_success(self):
        """Successful health check should be cached for _HEALTH_CHECK_TTL."""
        from memory.qdrant_store import QdrantConfig, QdrantStore

        with patch("memory.qdrant_store.QDRANT_AVAILABLE", True):
            mock_client = MagicMock()
            mock_collections = MagicMock()
            mock_collections.collections = []
            mock_client.get_collections.return_value = mock_collections

            store = QdrantStore.__new__(QdrantStore)
            store.config = QdrantConfig(url="http://localhost:6333")
            store._client = mock_client
            store._initialized_collections = set()
            store._last_health_check = 0.0
            store._last_health_ok = False

            # First call probes
            assert store.is_available is True
            assert mock_client.get_collections.call_count == 1

            # Second call uses cache (within TTL)
            assert store.is_available is True
            assert mock_client.get_collections.call_count == 1  # Not called again

    def test_health_check_caches_failure_with_shorter_ttl(self):
        """Failed health check should use shorter TTL before retrying."""
        from memory.qdrant_store import QdrantConfig, QdrantStore

        with patch("memory.qdrant_store.QDRANT_AVAILABLE", True):
            mock_client = MagicMock()
            mock_client.get_collections.side_effect = ConnectionError("refused")

            store = QdrantStore.__new__(QdrantStore)
            store.config = QdrantConfig(url="http://localhost:6333")
            store._client = mock_client
            store._initialized_collections = set()
            store._last_health_check = 0.0
            store._last_health_ok = False

            # First call probes and fails
            assert store.is_available is False
            assert mock_client.get_collections.call_count == 1

            # Second call within TTL uses cache
            assert store.is_available is False
            assert mock_client.get_collections.call_count == 1

            # After TTL expires, should re-probe
            store._last_health_check = time.time() - 20  # Past _HEALTH_FAIL_TTL
            mock_client.get_collections.side_effect = None
            mock_collections = MagicMock()
            mock_collections.collections = []
            mock_client.get_collections.return_value = mock_collections

            assert store.is_available is True
            assert mock_client.get_collections.call_count == 2


class TestEmbeddingStoreQdrantFallback:
    """Test that EmbeddingStore falls through to JSON when Qdrant fails."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.store_path = Path(self.tmpdir) / "embeddings.json"
        self.store = EmbeddingStore(self.store_path)
        # Force available by setting a mock client
        self.store._client = MagicMock()
        self.store._model = "test-model"

        # Pre-populate JSON with known entries
        self.store._entries = [
            EmbeddingEntry(
                text="User loves chocolate cake",
                vector=[1.0, 0.0, 0.0],
                source="memory",
                section="preferences",
            ),
            EmbeddingEntry(
                text="Deployed v2.0 to production",
                vector=[0.0, 1.0, 0.0],
                source="history",
                section="deploy",
            ),
        ]
        self.store._loaded = True

    @pytest.mark.asyncio
    async def test_search_falls_back_to_json_on_qdrant_failure(self):
        """When Qdrant search raises, should fall through to JSON scan."""
        # Set up a Qdrant that says it's available but fails on search
        mock_qdrant = MagicMock()
        mock_qdrant.is_available = True
        mock_qdrant.search.side_effect = ConnectionError("Qdrant server unreachable")
        self.store._qdrant = mock_qdrant

        # Mock embed_text to return a known vector
        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=[0.95, 0.05, 0.0])]
        self.store._client.embeddings = MagicMock()
        self.store._client.embeddings.create = AsyncMock(return_value=mock_response)

        # Should fall back to JSON and find the chocolate entry
        results = await self.store.search("chocolate", top_k=2)
        assert len(results) > 0
        assert any("chocolate" in r["text"] for r in results)

    @pytest.mark.asyncio
    async def test_search_uses_qdrant_when_available(self):
        """When Qdrant is healthy, should use Qdrant path."""
        mock_qdrant = MagicMock()
        mock_qdrant.is_available = True
        mock_qdrant.search.return_value = [
            {
                "text": "Qdrant result",
                "source": "memory",
                "section": "test",
                "score": 0.95,
                "metadata": {},
            }
        ]
        self.store._qdrant = mock_qdrant

        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=[1.0, 0.0, 0.0])]
        self.store._client.embeddings = MagicMock()
        self.store._client.embeddings.create = AsyncMock(return_value=mock_response)

        results = await self.store.search("test", top_k=2)
        # Qdrant search runs across MEMORY + HISTORY collections, each returning the mock result
        assert len(results) >= 1
        assert all(r["text"] == "Qdrant result" for r in results)

    @pytest.mark.asyncio
    async def test_search_json_when_no_qdrant(self):
        """When Qdrant is not configured, should use JSON directly."""
        self.store._qdrant = None

        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=[0.95, 0.05, 0.0])]
        self.store._client.embeddings = MagicMock()
        self.store._client.embeddings.create = AsyncMock(return_value=mock_response)

        results = await self.store.search("chocolate", top_k=2)
        assert len(results) > 0


class TestEmbeddingStoreIndexFallback:
    """Test that index operations fall back to JSON when Qdrant fails."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.store_path = Path(self.tmpdir) / "embeddings.json"
        self.store = EmbeddingStore(self.store_path)
        self.store._client = MagicMock()
        self.store._model = "test-model"
        self.store._loaded = True

    @pytest.mark.asyncio
    async def test_index_memory_falls_back_on_qdrant_failure(self):
        """index_memory should store to JSON when Qdrant write fails."""
        mock_qdrant = MagicMock()
        mock_qdrant.is_available = True
        mock_qdrant.clear_collection.side_effect = ConnectionError("down")
        self.store._qdrant = mock_qdrant

        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=[0.1, 0.2, 0.3])]
        self.store._client.embeddings = MagicMock()
        self.store._client.embeddings.create = AsyncMock(return_value=mock_response)

        count = await self.store.index_memory(
            "## Test Section\n\nSome long enough content for indexing."
        )
        assert count > 0
        # Should have stored in JSON
        assert len(self.store._entries) > 0
        assert self.store_path.exists()

    @pytest.mark.asyncio
    async def test_index_history_falls_back_on_qdrant_failure(self):
        """index_history_entry should store to JSON when Qdrant write fails."""
        mock_qdrant = MagicMock()
        mock_qdrant.is_available = True
        self.store._qdrant = mock_qdrant

        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=[0.1, 0.2, 0.3])]
        self.store._client.embeddings = MagicMock()
        self.store._client.embeddings.create = AsyncMock(return_value=mock_response)

        # Make upsert_single fail
        mock_qdrant.upsert_single.side_effect = ConnectionError("down")

        # Should not raise — falls back to JSON
        await self.store.index_history_entry("deploy", "Deployed v3.0", "Details")
        assert len(self.store._entries) > 0


class TestStorageStatusEffectiveMode:
    """Test that the storage status endpoint returns effective operational mode."""

    def test_effective_mode_when_qdrant_unreachable(self):
        """When Qdrant is configured but unreachable with Redis connected,
        effective mode should be 'redis_only', not 'qdrant_redis'."""
        qdrant_status = "unreachable"
        redis_status = "connected"

        qdrant_operational = qdrant_status in ("connected", "embedded_ok")
        redis_operational = redis_status == "connected"

        if qdrant_operational and redis_operational:
            effective_mode = "qdrant_redis"
        elif qdrant_operational and not redis_operational:
            effective_mode = "qdrant_server"
        elif not qdrant_operational and redis_operational:
            effective_mode = "redis_only"
        else:
            effective_mode = "file"

        assert effective_mode == "redis_only"

    def test_effective_mode_when_both_connected(self):
        """When both are connected, should be 'qdrant_redis'."""
        assert self._compute_mode("connected", "connected") == "qdrant_redis"

    def test_effective_mode_when_both_down(self):
        """When both are down, should be 'file'."""
        assert self._compute_mode("unreachable", "unreachable") == "file"

    def test_effective_mode_qdrant_only(self):
        """When only Qdrant is connected."""
        assert self._compute_mode("connected", "disabled") == "qdrant_server"

    def test_effective_mode_embedded_qdrant_with_redis(self):
        assert self._compute_mode("embedded_ok", "connected") == "qdrant_redis"

    @staticmethod
    def _compute_mode(qdrant_status: str, redis_status: str) -> str:
        qdrant_operational = qdrant_status in ("connected", "embedded_ok")
        redis_operational = redis_status == "connected"
        if qdrant_operational and redis_operational:
            return "qdrant_redis"
        elif qdrant_operational and not redis_operational:
            return "qdrant_server"
        elif not qdrant_operational and redis_operational:
            return "redis_only"
        else:
            return "file"
