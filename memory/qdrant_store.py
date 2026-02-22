"""
Qdrant vector database backend for semantic memory.

Replaces the JSON-backed linear-scan vector store with Qdrant's HNSW
indexing for sub-millisecond semantic search. Supports two modes:

1. Server mode: connects to a Qdrant server via URL (Docker/Cloud)
2. Embedded mode: uses qdrant-client's local file storage (no server needed)

Falls back gracefully when qdrant-client is not installed — callers should
check `is_available` before using.
"""

import hashlib
import logging
import time
import uuid
from dataclasses import dataclass, field

logger = logging.getLogger("agent42.memory.qdrant")

# Vector dimensions for text-embedding-3-small
VECTOR_DIM = 1536

try:
    from qdrant_client import QdrantClient
    from qdrant_client.models import (
        Distance,
        FieldCondition,
        Filter,
        MatchValue,
        PointStruct,
        Range,
        VectorParams,
    )

    QDRANT_AVAILABLE = True
except ImportError:
    QDRANT_AVAILABLE = False
    logger.debug("qdrant-client not installed — Qdrant backend unavailable")


@dataclass
class QdrantConfig:
    """Configuration for Qdrant connection."""

    url: str = ""  # Empty = use embedded/local mode
    api_key: str = ""
    collection_prefix: str = "agent42"
    local_path: str = ".agent42/qdrant"  # Path for embedded storage
    vector_dim: int = VECTOR_DIM


class QdrantStore:
    """Qdrant-backed vector store with collection management.

    Collections created:
    - {prefix}_memory: MEMORY.md chunks (facts, preferences, learnings)
    - {prefix}_history: HISTORY.md events (chronological log)
    - {prefix}_conversations: Session message embeddings (cross-session search)
    - {prefix}_knowledge: Learner-generated patterns and lessons
    """

    # Collection suffixes
    MEMORY = "memory"
    HISTORY = "history"
    CONVERSATIONS = "conversations"
    KNOWLEDGE = "knowledge"

    def __init__(self, config: QdrantConfig):
        self.config = config
        self._client: "QdrantClient | None" = None
        self._initialized_collections: set[str] = set()

        if not QDRANT_AVAILABLE:
            logger.info("Qdrant backend: qdrant-client not installed, unavailable")
            return

        try:
            if config.url:
                # Server mode: connect to Qdrant server
                kwargs = {"url": config.url, "timeout": 10}
                if config.api_key:
                    kwargs["api_key"] = config.api_key
                self._client = QdrantClient(**kwargs)
                logger.info(f"Qdrant backend: connected to server at {config.url}")
            else:
                # Embedded mode: local file storage
                self._client = QdrantClient(path=config.local_path)
                logger.info(
                    f"Qdrant backend: using embedded storage at {config.local_path}"
                )
        except Exception as e:
            logger.warning(f"Qdrant backend: failed to connect — {e}")
            self._client = None

    @property
    def is_available(self) -> bool:
        """Whether the Qdrant backend is connected and usable."""
        return self._client is not None

    def _collection_name(self, suffix: str) -> str:
        """Get the full collection name with prefix."""
        return f"{self.config.collection_prefix}_{suffix}"

    def _ensure_collection(self, suffix: str):
        """Create a collection if it doesn't exist yet."""
        if not self._client or suffix in self._initialized_collections:
            return

        name = self._collection_name(suffix)
        try:
            collections = self._client.get_collections().collections
            existing = {c.name for c in collections}

            if name not in existing:
                self._client.create_collection(
                    collection_name=name,
                    vectors_config=VectorParams(
                        size=self.config.vector_dim,
                        distance=Distance.COSINE,
                    ),
                )
                logger.info(f"Qdrant: created collection '{name}'")

            self._initialized_collections.add(suffix)
        except Exception as e:
            logger.error(f"Qdrant: failed to ensure collection '{name}': {e}")

    def _make_point_id(self, text: str, source: str = "") -> str:
        """Generate a deterministic UUID point ID from text content.

        Qdrant expects UUID or integer IDs. We use uuid5 with a SHA-256-based
        namespace to produce valid, deterministic UUIDs.
        """
        content = f"{source}:{text}"
        # Use a fixed namespace derived from "agent42" for deterministic UUIDs
        namespace = uuid.UUID("a42a42a4-2a42-4a42-a42a-42a42a42a42a")
        return str(uuid.uuid5(namespace, content))

    # -- Upsert operations --

    def upsert_vectors(
        self,
        collection_suffix: str,
        texts: list[str],
        vectors: list[list[float]],
        payloads: list[dict] | None = None,
    ) -> int:
        """Store text+vector pairs in a collection.

        Args:
            collection_suffix: One of MEMORY, HISTORY, CONVERSATIONS, KNOWLEDGE
            texts: The text chunks
            vectors: Corresponding embedding vectors
            payloads: Optional metadata dicts for each entry

        Returns:
            Number of points upserted.
        """
        if not self._client:
            return 0

        self._ensure_collection(collection_suffix)
        name = self._collection_name(collection_suffix)

        if payloads is None:
            payloads = [{}] * len(texts)

        points = []
        for text, vector, payload in zip(texts, vectors, payloads):
            point_id = self._make_point_id(text, payload.get("source", ""))
            full_payload = {
                "text": text,
                "timestamp": time.time(),
                **payload,
            }
            points.append(
                PointStruct(
                    id=point_id,
                    vector=vector,
                    payload=full_payload,
                )
            )

        try:
            # Batch in chunks of 100
            for i in range(0, len(points), 100):
                batch = points[i : i + 100]
                self._client.upsert(collection_name=name, points=batch)
            logger.debug(
                f"Qdrant: upserted {len(points)} points to '{name}'"
            )
            return len(points)
        except Exception as e:
            logger.error(f"Qdrant: upsert failed for '{name}': {e}")
            return 0

    def upsert_single(
        self,
        collection_suffix: str,
        text: str,
        vector: list[float],
        payload: dict | None = None,
    ) -> bool:
        """Store a single text+vector pair."""
        return self.upsert_vectors(
            collection_suffix, [text], [vector], [payload or {}]
        ) > 0

    # -- Search operations --

    def search(
        self,
        collection_suffix: str,
        query_vector: list[float],
        top_k: int = 5,
        source_filter: str = "",
        channel_filter: str = "",
        time_after: float = 0.0,
    ) -> list[dict]:
        """Semantic search in a collection.

        Args:
            collection_suffix: Which collection to search
            query_vector: The embedding vector of the query
            top_k: Number of results to return
            source_filter: Filter by source field
            channel_filter: Filter by channel_type field
            time_after: Only return results after this timestamp

        Returns:
            List of {text, source, section, score, metadata} dicts.
        """
        if not self._client:
            return []

        self._ensure_collection(collection_suffix)
        name = self._collection_name(collection_suffix)

        # Build filters
        conditions = []
        if source_filter:
            conditions.append(
                FieldCondition(
                    key="source", match=MatchValue(value=source_filter)
                )
            )
        if channel_filter:
            conditions.append(
                FieldCondition(
                    key="channel_type", match=MatchValue(value=channel_filter)
                )
            )
        if time_after > 0:
            conditions.append(
                FieldCondition(key="timestamp", range=Range(gte=time_after))
            )

        query_filter = Filter(must=conditions) if conditions else None

        try:
            results = self._client.search(
                collection_name=name,
                query_vector=query_vector,
                limit=top_k,
                query_filter=query_filter,
            )

            return [
                {
                    "text": hit.payload.get("text", ""),
                    "source": hit.payload.get("source", ""),
                    "section": hit.payload.get("section", ""),
                    "score": round(hit.score, 4),
                    "metadata": {
                        k: v
                        for k, v in hit.payload.items()
                        if k not in ("text", "source", "section", "timestamp")
                    },
                }
                for hit in results
            ]
        except Exception as e:
            logger.error(f"Qdrant: search failed for '{name}': {e}")
            return []

    def search_conversations(
        self,
        query_vector: list[float],
        top_k: int = 5,
        channel_filter: str = "",
        time_after: float = 0.0,
    ) -> list[dict]:
        """Search across all conversation sessions."""
        return self.search(
            self.CONVERSATIONS,
            query_vector,
            top_k=top_k,
            channel_filter=channel_filter,
            time_after=time_after,
        )

    # -- Collection management --

    def clear_collection(self, collection_suffix: str) -> bool:
        """Delete all points in a collection (recreates it)."""
        if not self._client:
            return False

        name = self._collection_name(collection_suffix)
        try:
            self._client.delete_collection(name)
            self._initialized_collections.discard(collection_suffix)
            self._ensure_collection(collection_suffix)
            logger.info(f"Qdrant: cleared collection '{name}'")
            return True
        except Exception as e:
            logger.error(f"Qdrant: failed to clear '{name}': {e}")
            return False

    def collection_count(self, collection_suffix: str) -> int:
        """Get the number of points in a collection."""
        if not self._client:
            return 0

        name = self._collection_name(collection_suffix)
        try:
            info = self._client.get_collection(name)
            return info.points_count or 0
        except Exception:
            return 0

    def close(self):
        """Close the Qdrant client connection."""
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None
