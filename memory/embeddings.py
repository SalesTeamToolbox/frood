"""
Semantic memory — vector embeddings for meaning-based search.

Uses any OpenAI-compatible embedding API (OpenAI or OpenRouter) with a
pluggable vector store backend:

1. Qdrant backend (preferred) — HNSW-indexed search, payload filtering,
   persistence, and scalability. Supports server or embedded mode.
2. JSON backend (fallback) — Pure-Python cosine similarity with JSON
   file storage. Works everywhere, no extra dependencies.

Embedding cache via Redis (optional) — avoids redundant API calls for
repeated queries.

Gracefully degrades to grep-based search when no embedding API is configured.
"""

import json
import logging
import math
import os
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

from openai import AsyncOpenAI

logger = logging.getLogger("agent42.memory.embeddings")

# Embedding models available on common providers
EMBEDDING_MODELS = {
    "openai": "text-embedding-3-small",       # OpenAI — cheap, 1536 dims
    "openrouter": "openai/text-embedding-3-small",  # Via OpenRouter
}


@dataclass
class EmbeddingEntry:
    """A text chunk with its embedding vector."""
    text: str
    vector: list[float]
    source: str = ""        # "memory" or "history"
    section: str = ""       # Section heading or event type
    timestamp: float = 0.0
    metadata: dict = field(default_factory=dict)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Pure-Python cosine similarity. No numpy needed."""
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class EmbeddingStore:
    """Pluggable vector store for semantic memory search.

    Uses Qdrant when available (HNSW-indexed), falls back to JSON
    (linear scan). Optionally caches embeddings in Redis.

    Resolution order for embedding API:
    1. EMBEDDING_MODEL + EMBEDDING_PROVIDER env vars (explicit config)
    2. OpenAI (if OPENAI_API_KEY is set)
    3. OpenRouter (if OPENROUTER_API_KEY is set)
    4. Disabled — falls back to grep search
    """

    def __init__(self, store_path: str | Path, qdrant_store=None, redis_backend=None):
        self.store_path = Path(store_path)
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self._entries: list[EmbeddingEntry] = []
        self._client: AsyncOpenAI | None = None
        self._model: str = ""
        self._loaded = False
        self._qdrant = qdrant_store  # QdrantStore instance (optional)
        self._redis = redis_backend  # RedisSessionBackend instance (optional)
        self._resolve_provider()

    def _resolve_provider(self):
        """Find the best available embedding API."""
        # Explicit override
        explicit_model = os.getenv("EMBEDDING_MODEL")
        explicit_provider = os.getenv("EMBEDDING_PROVIDER", "").lower()

        if explicit_model:
            self._model = explicit_model
            base_url, api_key = self._provider_config(explicit_provider)
            if api_key:
                self._client = AsyncOpenAI(base_url=base_url, api_key=api_key)
                logger.info(f"Embeddings: using {explicit_model} via {explicit_provider or 'openai'}")
                return

        # Auto-detect: try providers in order of preference
        for provider, model in [
            ("openai", EMBEDDING_MODELS["openai"]),
            ("openrouter", EMBEDDING_MODELS["openrouter"]),
        ]:
            base_url, api_key = self._provider_config(provider)
            if api_key:
                self._model = model
                self._client = AsyncOpenAI(base_url=base_url, api_key=api_key)
                logger.info(f"Embeddings: auto-detected {provider}, using {model}")
                return

        logger.info("Embeddings: no API configured — semantic search disabled, using grep fallback")

    @staticmethod
    def _provider_config(provider: str) -> tuple[str, str]:
        """Return (base_url, api_key) for a provider name."""
        configs = {
            "openai": ("https://api.openai.com/v1", os.getenv("OPENAI_API_KEY", "")),
            "openrouter": ("https://openrouter.ai/api/v1", os.getenv("OPENROUTER_API_KEY", "")),
        }
        return configs.get(provider, ("https://api.openai.com/v1", ""))

    @property
    def is_available(self) -> bool:
        """Whether semantic search is available."""
        return self._client is not None

    def _load(self):
        """Load entries from disk."""
        if self._loaded:
            return
        self._loaded = True
        if not self.store_path.exists():
            return
        try:
            data = json.loads(self.store_path.read_text(encoding="utf-8"))
            self._entries = [EmbeddingEntry(**e) for e in data]
            logger.debug(f"Loaded {len(self._entries)} embedding entries")
        except (json.JSONDecodeError, TypeError, KeyError) as e:
            logger.warning(f"Failed to load embeddings: {e}")
            self._entries = []

    # Maximum entries before evicting oldest (prevents unbounded JSON growth)
    MAX_JSON_ENTRIES = 5000

    def _save(self):
        """Persist entries to disk. Evicts oldest entries if over limit."""
        if len(self._entries) > self.MAX_JSON_ENTRIES:
            # Keep newest entries, sorted by timestamp
            self._entries.sort(key=lambda e: e.timestamp)
            self._entries = self._entries[-self.MAX_JSON_ENTRIES:]
            logger.info(
                f"JSON embedding store evicted to {self.MAX_JSON_ENTRIES} entries"
            )
        data = [asdict(e) for e in self._entries]
        self.store_path.write_text(
            json.dumps(data, ensure_ascii=False),
            encoding="utf-8",
        )

    @property
    def qdrant_available(self) -> bool:
        """Whether the Qdrant backend is available for search."""
        return self._qdrant is not None and self._qdrant.is_available

    async def embed_text(self, text: str) -> list[float]:
        """Get the embedding vector for a text string.

        Checks Redis cache first, falls back to API call, then caches result.
        """
        if not self._client:
            raise RuntimeError("No embedding API configured")

        # Check Redis cache
        if self._redis and self._redis.is_available:
            cached = self._redis.get_cached_embedding(text)
            if cached is not None:
                return cached

        response = await self._client.embeddings.create(
            model=self._model,
            input=text,
        )
        vector = response.data[0].embedding

        # Cache in Redis
        if self._redis and self._redis.is_available:
            self._redis.cache_embedding(text, vector)

        return vector

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Batch-embed multiple texts with Redis cache support.

        Checks Redis cache for each text first, only sends uncached texts
        to the API. Caches new results on return.
        """
        if not self._client:
            raise RuntimeError("No embedding API configured")

        use_cache = self._redis and self._redis.is_available
        vectors: list[list[float] | None] = [None] * len(texts)
        uncached_indices: list[int] = []

        # Check cache for each text
        if use_cache:
            for i, text in enumerate(texts):
                cached = self._redis.get_cached_embedding(text)
                if cached is not None:
                    vectors[i] = cached
                else:
                    uncached_indices.append(i)
        else:
            uncached_indices = list(range(len(texts)))

        # Batch-embed uncached texts
        if uncached_indices:
            uncached_texts = [texts[i] for i in uncached_indices]
            api_vectors: list[list[float]] = []
            for i in range(0, len(uncached_texts), 100):
                batch = uncached_texts[i:i + 100]
                response = await self._client.embeddings.create(
                    model=self._model,
                    input=batch,
                )
                api_vectors.extend([d.embedding for d in response.data])

            # Fill in results and cache
            for idx, vec in zip(uncached_indices, api_vectors):
                vectors[idx] = vec
                if use_cache:
                    self._redis.cache_embedding(texts[idx], vec)

        return vectors  # type: ignore[return-value]

    async def add_entry(self, text: str, source: str = "", section: str = "",
                        metadata: dict | None = None):
        """Embed and store a single text entry."""
        self._load()
        vector = await self.embed_text(text)
        entry = EmbeddingEntry(
            text=text,
            vector=vector,
            source=source,
            section=section,
            timestamp=time.time(),
            metadata=metadata or {},
        )
        self._entries.append(entry)
        self._save()
        return entry

    async def add_entries(self, items: list[dict]):
        """Batch-add multiple entries. Each dict has: text, source, section, metadata."""
        self._load()
        texts = [item["text"] for item in items]
        vectors = await self.embed_texts(texts)

        for item, vector in zip(items, vectors):
            entry = EmbeddingEntry(
                text=item["text"],
                vector=vector,
                source=item.get("source", ""),
                section=item.get("section", ""),
                timestamp=time.time(),
                metadata=item.get("metadata", {}),
            )
            self._entries.append(entry)

        self._save()
        return len(items)

    async def search(self, query: str, top_k: int = 5,
                     source_filter: str = "",
                     collection: str = "") -> list[dict]:
        """Semantic search: find the most relevant entries for a query.

        When Qdrant is available, uses HNSW-indexed search with payload
        filtering. Falls back to JSON linear scan otherwise.

        Args:
            query: Search query text
            top_k: Number of results
            source_filter: Filter by source field
            collection: Qdrant collection suffix (default: searches memory+history)

        Returns list of {text, source, section, score, metadata}.
        """
        # Prefer Qdrant when available
        if self._qdrant and self._qdrant.is_available:
            from memory.qdrant_store import QdrantStore

            query_vector = await self.embed_text(query)

            if collection:
                return self._qdrant.search(
                    collection, query_vector, top_k=top_k,
                    source_filter=source_filter,
                )

            # Search across memory and history collections
            memory_results = self._qdrant.search(
                QdrantStore.MEMORY, query_vector, top_k=top_k,
                source_filter=source_filter,
            )
            history_results = self._qdrant.search(
                QdrantStore.HISTORY, query_vector, top_k=top_k,
                source_filter=source_filter,
            )

            # Merge and re-sort by score
            combined = memory_results + history_results
            combined.sort(key=lambda x: x["score"], reverse=True)
            return combined[:top_k]

        # Fallback: JSON linear scan
        self._load()
        if not self._entries:
            return []

        query_vector = await self.embed_text(query)

        scored = []
        for entry in self._entries:
            if source_filter and entry.source != source_filter:
                continue
            score = _cosine_similarity(query_vector, entry.vector)
            scored.append((score, entry))

        scored.sort(key=lambda x: x[0], reverse=True)

        return [
            {
                "text": entry.text,
                "source": entry.source,
                "section": entry.section,
                "score": round(score, 4),
                "metadata": entry.metadata,
            }
            for score, entry in scored[:top_k]
        ]

    async def index_memory(self, memory_text: str):
        """Index the contents of MEMORY.md for semantic search.

        Splits by sections and indexes each section as a chunk.
        Writes to Qdrant when available, otherwise to JSON.
        """
        chunks = self._split_into_chunks(memory_text, source="memory")
        if not chunks:
            return 0

        texts = [c["text"] for c in chunks]
        vectors = await self.embed_texts(texts)

        # Store in Qdrant if available
        if self._qdrant and self._qdrant.is_available:
            from memory.qdrant_store import QdrantStore

            self._qdrant.clear_collection(QdrantStore.MEMORY)
            payloads = [
                {"source": "memory", "section": c.get("section", "")}
                for c in chunks
            ]
            count = self._qdrant.upsert_vectors(
                QdrantStore.MEMORY, texts, vectors, payloads
            )
            logger.info(f"Indexed {count} memory chunks → Qdrant")
            return count

        # Fallback: JSON store
        self._load()
        self._entries = [e for e in self._entries if e.source != "memory"]

        for chunk, vector in zip(chunks, vectors):
            self._entries.append(EmbeddingEntry(
                text=chunk["text"],
                vector=vector,
                source="memory",
                section=chunk.get("section", ""),
                timestamp=time.time(),
            ))

        self._save()
        logger.info(f"Indexed {len(chunks)} memory chunks → JSON")
        return len(chunks)

    async def index_history_entry(self, event_type: str, summary: str,
                                  details: str = ""):
        """Index a single history event for semantic search.

        Writes to Qdrant when available, otherwise to JSON.
        """
        text = f"{event_type}: {summary}"
        if details:
            text += f"\n{details}"

        # Store in Qdrant if available
        if self._qdrant and self._qdrant.is_available:
            from memory.qdrant_store import QdrantStore

            vector = await self.embed_text(text)
            self._qdrant.upsert_single(
                QdrantStore.HISTORY,
                text,
                vector,
                {"source": "history", "section": event_type},
            )
            return

        # Fallback: JSON store
        await self.add_entry(text, source="history", section=event_type)

    async def search_conversations(
        self,
        query: str,
        top_k: int = 5,
        channel_filter: str = "",
        time_after: float = 0.0,
    ) -> list[dict]:
        """Search across conversation summaries and messages.

        Requires Qdrant — returns empty list if unavailable.
        """
        if not self._qdrant or not self._qdrant.is_available:
            return []

        query_vector = await self.embed_text(query)
        return self._qdrant.search_conversations(
            query_vector,
            top_k=top_k,
            channel_filter=channel_filter,
            time_after=time_after,
        )

    @staticmethod
    def _split_into_chunks(text: str, source: str = "",
                           min_chunk_len: int = 20) -> list[dict]:
        """Split markdown text into meaningful chunks by section."""
        chunks = []
        current_section = ""
        current_lines: list[str] = []

        for line in text.split("\n"):
            if line.startswith("## "):
                # Flush previous section
                if current_lines:
                    content = "\n".join(current_lines).strip()
                    if len(content) >= min_chunk_len:
                        chunks.append({
                            "text": content,
                            "section": current_section,
                            "source": source,
                        })
                current_section = line.lstrip("#").strip()
                current_lines = [line]
            elif line.startswith("# "):
                # Top-level heading — start fresh
                if current_lines:
                    content = "\n".join(current_lines).strip()
                    if len(content) >= min_chunk_len:
                        chunks.append({
                            "text": content,
                            "section": current_section,
                            "source": source,
                        })
                current_section = line.lstrip("#").strip()
                current_lines = [line]
            else:
                current_lines.append(line)

        # Flush last section
        if current_lines:
            content = "\n".join(current_lines).strip()
            if len(content) >= min_chunk_len:
                chunks.append({
                    "text": content,
                    "section": current_section,
                    "source": source,
                })

        return chunks

    def entry_count(self) -> int:
        """Number of stored embedding entries."""
        self._load()
        return len(self._entries)

    def clear(self):
        """Clear all stored embeddings."""
        self._entries = []
        self._loaded = True
        if self.store_path.exists():
            self.store_path.unlink()
