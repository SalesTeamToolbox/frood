"""
Qdrant vector database backend for semantic memory.

Replaces the JSON-backed linear-scan vector store with Qdrant's HNSW
indexing for sub-millisecond semantic search. Supports two modes:

1. Server mode: connects to a Qdrant server via URL (Docker/Cloud)
2. Embedded mode: uses qdrant-client's local file storage (no server needed)

Falls back gracefully when qdrant-client is not installed — callers should
check `is_available` before using.
"""

import logging
import time
import uuid
from dataclasses import dataclass

logger = logging.getLogger("frood.memory.qdrant")

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
    local_path: str = ".frood/qdrant"  # Path for embedded storage
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

    # How long (seconds) to cache a successful health check before re-probing
    _HEALTH_CHECK_TTL = 60.0
    # How long (seconds) to suppress re-probing after a failed health check
    _HEALTH_FAIL_TTL = 15.0

    def __init__(self, config: QdrantConfig):
        self.config = config
        self._client: QdrantClient | None = None
        self._initialized_collections: set[str] = set()
        # Health-check cache: avoids hammering the server on every call
        self._last_health_check: float = 0.0
        self._last_health_ok: bool = False

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
                logger.info(f"Qdrant backend: connecting to server at {config.url}")
            else:
                # Embedded mode: local file storage
                self._client = QdrantClient(path=config.local_path)
                logger.info(f"Qdrant backend: using embedded storage at {config.local_path}")
        except Exception as e:
            logger.warning(f"Qdrant backend: failed to connect — {e}")
            self._client = None

    def _check_health(self) -> bool:
        """Probe the Qdrant server for actual connectivity.

        Results are cached for ``_HEALTH_CHECK_TTL`` (success) or
        ``_HEALTH_FAIL_TTL`` (failure) seconds to avoid per-call overhead.
        Embedded mode always returns True (no network needed).
        """
        if self._client is None:
            return False

        # Embedded mode — always reachable, no network
        if not self.config.url:
            return True

        now = time.time()
        ttl = self._HEALTH_CHECK_TTL if self._last_health_ok else self._HEALTH_FAIL_TTL
        if now - self._last_health_check < ttl:
            return self._last_health_ok

        try:
            # Lightweight probe — get_collections is the cheapest RPC
            self._client.get_collections()
            self._last_health_ok = True
            logger.debug("Qdrant health check: OK")
        except Exception as e:
            self._last_health_ok = False
            logger.warning("Qdrant health check failed: %s", e)

        self._last_health_check = now
        return self._last_health_ok

    @property
    def is_available(self) -> bool:
        """Whether the Qdrant backend is connected and actually reachable."""
        return self._check_health()

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

            # Create payload indexes for task metadata (MEMORY and HISTORY only)
            # create_payload_index() is idempotent — safe on existing collections
            if suffix in (self.MEMORY, self.HISTORY):
                self._ensure_task_indexes(name)
            if suffix == self.KNOWLEDGE:
                self._ensure_knowledge_indexes(name)

        except Exception as e:
            logger.error(f"Qdrant: failed to ensure collection '{name}': {e}")

    def _ensure_task_indexes(self, collection_name: str):
        """Create payload indexes for task_type, task_id, agent_id, company_id, and run_id (idempotent)."""
        from qdrant_client.models import KeywordIndexParams, PayloadSchemaType

        try:
            self._client.create_payload_index(
                collection_name=collection_name,
                field_name="task_type",
                field_schema=PayloadSchemaType.KEYWORD,
            )
            self._client.create_payload_index(
                collection_name=collection_name,
                field_name="task_id",
                field_schema=PayloadSchemaType.KEYWORD,
            )
            self._client.create_payload_index(
                collection_name=collection_name,
                field_name="agent_id",
                field_schema=KeywordIndexParams(type="keyword", is_tenant=True),
            )
            self._client.create_payload_index(
                collection_name=collection_name,
                field_name="company_id",
                field_schema=KeywordIndexParams(type="keyword", is_tenant=True),
            )
            self._client.create_payload_index(
                collection_name=collection_name,
                field_name="run_id",
                field_schema=PayloadSchemaType.KEYWORD,
            )
        except Exception as e:
            logger.warning("Qdrant: task payload index creation failed (non-critical): %s", e)

    def _ensure_knowledge_indexes(self, collection_name: str):
        """Create payload indexes for learning_type, category, agent_id, company_id, and run_id on KNOWLEDGE collection (idempotent)."""
        from qdrant_client.models import KeywordIndexParams, PayloadSchemaType

        try:
            self._client.create_payload_index(
                collection_name=collection_name,
                field_name="learning_type",
                field_schema=PayloadSchemaType.KEYWORD,
            )
            self._client.create_payload_index(
                collection_name=collection_name,
                field_name="category",
                field_schema=PayloadSchemaType.KEYWORD,
            )
            self._client.create_payload_index(
                collection_name=collection_name,
                field_name="agent_id",
                field_schema=KeywordIndexParams(type="keyword", is_tenant=True),
            )
            self._client.create_payload_index(
                collection_name=collection_name,
                field_name="company_id",
                field_schema=KeywordIndexParams(type="keyword", is_tenant=True),
            )
            self._client.create_payload_index(
                collection_name=collection_name,
                field_name="run_id",
                field_schema=PayloadSchemaType.KEYWORD,
            )
        except Exception as e:
            logger.warning("Qdrant: knowledge payload index creation failed (non-critical): %s", e)

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
            logger.debug(f"Qdrant: upserted {len(points)} points to '{name}'")
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
        return self.upsert_vectors(collection_suffix, [text], [vector], [payload or {}]) > 0

    # -- Search operations --

    def search(
        self,
        collection_suffix: str,
        query_vector: list[float],
        top_k: int = 5,
        source_filter: str = "",
        channel_filter: str = "",
        time_after: float = 0.0,
        task_type_filter: str = "",
        task_id_filter: str = "",
    ) -> list[dict]:
        """Semantic search in a collection.

        Args:
            collection_suffix: Which collection to search
            query_vector: The embedding vector of the query
            top_k: Number of results to return
            source_filter: Filter by source field
            channel_filter: Filter by channel_type field
            time_after: Only return results after this timestamp
            task_type_filter: Filter by task_type field (e.g. "coding")
            task_id_filter: Filter by task_id field (UUID string)

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
            conditions.append(FieldCondition(key="source", match=MatchValue(value=source_filter)))
        if channel_filter:
            conditions.append(
                FieldCondition(key="channel_type", match=MatchValue(value=channel_filter))
            )
        if time_after > 0:
            conditions.append(FieldCondition(key="timestamp", range=Range(gte=time_after)))
        if task_type_filter:
            conditions.append(
                FieldCondition(key="task_type", match=MatchValue(value=task_type_filter))
            )
        if task_id_filter:
            conditions.append(FieldCondition(key="task_id", match=MatchValue(value=task_id_filter)))

        query_filter = Filter(must=conditions) if conditions else None

        try:
            response = self._client.query_points(
                collection_name=name,
                query=query_vector,
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
                for hit in response.points
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

    # -- Lifecycle operations (Phase 3D) --

    def update_payload(
        self,
        collection_suffix: str,
        point_id: str,
        updates: dict,
    ) -> bool:
        """Update payload fields on an existing point.

        Used for lifecycle tracking: recall_count, last_recalled, confidence, status.
        """
        if not self._client:
            return False

        name = self._collection_name(collection_suffix)
        try:
            self._client.set_payload(
                collection_name=name,
                payload=updates,
                points=[point_id],
            )
            return True
        except Exception as e:
            logger.warning(f"Qdrant: payload update failed for '{name}': {e}")
            return False

    def record_recall(self, collection_suffix: str, point_ids: list[str]):
        """Record that these points were recalled (returned in a search).

        Increments recall_count, updates last_recalled timestamp,
        and slightly boosts confidence.
        """
        if not self._client:
            return

        name = self._collection_name(collection_suffix)
        now = time.time()

        for pid in point_ids:
            try:
                # Retrieve current payload to increment recall_count
                points = self._client.retrieve(
                    collection_name=name,
                    ids=[pid],
                    with_payload=True,
                    with_vectors=False,
                )
                if not points:
                    continue

                payload = points[0].payload or {}
                recall_count = payload.get("recall_count", 0) + 1
                old_confidence = payload.get("confidence", 0.5)
                # Boost confidence slightly on each recall (capped at 1.0)
                new_confidence = min(1.0, old_confidence + 0.05)

                self._client.set_payload(
                    collection_name=name,
                    payload={
                        "recall_count": recall_count,
                        "last_recalled": now,
                        "confidence": round(new_confidence, 3),
                    },
                    points=[pid],
                )
            except Exception as e:
                logger.debug(f"Qdrant: recall tracking failed for {pid}: {e}")

    def set_status(
        self,
        collection_suffix: str,
        point_id: str,
        status: str,
    ) -> bool:
        """Set the status of a memory point ('active', 'forgotten')."""
        return self.update_payload(collection_suffix, point_id, {"status": status})

    def strengthen_point(
        self,
        collection_suffix: str,
        point_id: str,
        boost: float = 0.1,
    ) -> bool:
        """Explicitly strengthen a memory (user confirmed it was useful).

        Boosts confidence by `boost` (capped at 1.0).
        """
        if not self._client:
            return False

        name = self._collection_name(collection_suffix)
        try:
            points = self._client.retrieve(
                collection_name=name,
                ids=[point_id],
                with_payload=True,
                with_vectors=False,
            )
            if not points:
                return False

            payload = points[0].payload or {}
            old_confidence = payload.get("confidence", 0.5)
            new_confidence = min(1.0, old_confidence + boost)

            self._client.set_payload(
                collection_name=name,
                payload={
                    "confidence": round(new_confidence, 3),
                    "last_recalled": time.time(),
                },
                points=[point_id],
            )
            return True
        except Exception as e:
            logger.warning(f"Qdrant: strengthen failed for {point_id}: {e}")
            return False

    def search_with_lifecycle(
        self,
        collection_suffix: str,
        query_vector: list[float],
        top_k: int = 5,
        source_filter: str = "",
        project_filter: str = "",
        include_global: bool = True,
        exclude_forgotten: bool = True,
        task_type_filter: str = "",
        task_id_filter: str = "",
    ) -> list[dict]:
        """Search with lifecycle-aware scoring.

        Adjusts cosine similarity scores based on:
        - confidence: higher confidence = higher score
        - recall_count: frequently recalled = slight boost
        - decay: memories not recalled in 30+ days get a penalty
        - status: forgotten memories are excluded

        Returns results with both raw and adjusted scores.
        """
        if not self._client:
            return []

        self._ensure_collection(collection_suffix)
        name = self._collection_name(collection_suffix)

        # Build filters
        conditions = []
        if source_filter:
            conditions.append(FieldCondition(key="source", match=MatchValue(value=source_filter)))
        if exclude_forgotten:
            # Exclude points with status="forgotten"
            # Note: points without a status field are treated as active
            conditions.append(
                FieldCondition(
                    key="status",
                    match=MatchValue(value="forgotten"),
                )
            )
            # We want NOT forgotten, so we use must_not
            forgotten_filter = Filter(
                must_not=[
                    FieldCondition(
                        key="status",
                        match=MatchValue(value="forgotten"),
                    )
                ]
            )
            # Merge with source filter
            if source_filter:
                forgotten_filter.must = [
                    FieldCondition(key="source", match=MatchValue(value=source_filter))
                ]
        else:
            forgotten_filter = None

        # Project scoping
        if project_filter and not include_global:
            proj_condition = FieldCondition(key="project", match=MatchValue(value=project_filter))
            if forgotten_filter:
                forgotten_filter.must = forgotten_filter.must or []
                forgotten_filter.must.append(proj_condition)
            else:
                forgotten_filter = Filter(must=[proj_condition])
        elif project_filter and include_global:
            # Include both project-specific and global memories
            proj_condition = Filter(
                should=[
                    FieldCondition(key="project", match=MatchValue(value=project_filter)),
                    FieldCondition(key="project", match=MatchValue(value="global")),
                    FieldCondition(key="project", match=MatchValue(value="")),
                ]
            )
            if forgotten_filter:
                forgotten_filter.must = forgotten_filter.must or []
                # We need to express OR for project — use a nested filter
                # Qdrant Filter supports must + should at the same level
                forgotten_filter.should = proj_condition.should
            else:
                forgotten_filter = proj_condition

        # Task-type and task-id filtering (append to whatever filter was built)
        task_conditions = []
        if task_type_filter:
            task_conditions.append(
                FieldCondition(key="task_type", match=MatchValue(value=task_type_filter))
            )
        if task_id_filter:
            task_conditions.append(
                FieldCondition(key="task_id", match=MatchValue(value=task_id_filter))
            )

        if task_conditions:
            if forgotten_filter:
                forgotten_filter.must = (forgotten_filter.must or []) + task_conditions
            else:
                # Also add to conditions list for the fallback path
                conditions.extend(task_conditions)

        query_filter = (
            forgotten_filter
            if forgotten_filter
            else (Filter(must=conditions) if conditions else None)
        )

        try:
            # Fetch more results than needed so we can re-rank
            fetch_k = min(top_k * 3, 50)
            response = self._client.query_points(
                collection_name=name,
                query=query_vector,
                limit=fetch_k,
                query_filter=query_filter,
            )

            now = time.time()
            results = []
            for hit in response.points:
                payload = hit.payload or {}
                raw_score = hit.score

                # Lifecycle adjustments
                confidence = payload.get("confidence", 0.5)
                recall_count = payload.get("recall_count", 0)
                last_recalled = payload.get("last_recalled", 0)

                # Confidence weight: range [0.6, 1.1]
                confidence_weight = 0.6 + 0.5 * confidence

                # Recall boost: frequently recalled memories get a small boost
                # max +20% for 10+ recalls
                recall_boost = 1.0 + 0.02 * min(recall_count, 10)

                # Decay penalty: memories not recalled in >30 days get penalized
                # max -15% for very old, never-recalled memories
                if last_recalled > 0:
                    days_since_recall = (now - last_recalled) / 86400
                else:
                    # Never recalled — use creation timestamp
                    created = payload.get("timestamp", now)
                    days_since_recall = (now - created) / 86400

                if days_since_recall > 30:
                    decay = max(0.85, 1.0 - 0.005 * (days_since_recall - 30))
                else:
                    decay = 1.0

                adjusted_score = raw_score * confidence_weight * recall_boost * decay

                results.append(
                    {
                        "text": payload.get("text", ""),
                        "source": payload.get("source", ""),
                        "section": payload.get("section", ""),
                        "project": payload.get("project", ""),
                        "score": round(adjusted_score, 4),
                        "raw_score": round(raw_score, 4),
                        "confidence": confidence,
                        "recall_count": recall_count,
                        "point_id": hit.id,
                        "metadata": {
                            k: v
                            for k, v in payload.items()
                            if k
                            not in (
                                "text",
                                "source",
                                "section",
                                "timestamp",
                                "confidence",
                                "recall_count",
                                "last_recalled",
                                "status",
                                "project",
                            )
                        },
                    }
                )

            # Re-sort by adjusted score
            results.sort(key=lambda x: x["score"], reverse=True)
            return results[:top_k]

        except Exception as e:
            logger.error(f"Qdrant: lifecycle search failed for '{name}': {e}")
            return []

    def find_by_text(
        self,
        collection_suffix: str,
        query_vector: list[float],
        text_substring: str,
        top_k: int = 5,
    ) -> list[dict]:
        """Find points matching a text substring (for forget/correct operations).

        Uses vector search + post-filter by text content.
        """
        if not self._client:
            return []

        self._ensure_collection(collection_suffix)
        name = self._collection_name(collection_suffix)

        try:
            response = self._client.query_points(
                collection_name=name,
                query=query_vector,
                limit=top_k * 3,  # Over-fetch for filtering
            )

            results = []
            text_lower = text_substring.lower()
            for hit in response.points:
                payload = hit.payload or {}
                hit_text = payload.get("text", "")
                if text_lower in hit_text.lower():
                    results.append(
                        {
                            "text": hit_text,
                            "point_id": hit.id,
                            "score": round(hit.score, 4),
                            "collection": collection_suffix,
                        }
                    )
                    if len(results) >= top_k:
                        break

            return results
        except Exception as e:
            logger.error(f"Qdrant: find_by_text failed: {e}")
            return []

    def close(self):
        """Close the Qdrant client connection."""
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None
