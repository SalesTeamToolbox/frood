"""
Semantic memory — vector embeddings for meaning-based search.

Embedding providers (resolution order):
1. Local ONNX (onnxruntime + tokenizers) — runs entirely on-device, no API key,
   ~23 MB RAM instead of ~1 GB for PyTorch. Uses all-MiniLM-L6-v2 (384 dims).
2. OpenAI API — text-embedding-3-small (1536 dims). Requires OPENAI_API_KEY.
3. Disabled — falls back to grep-based search.

Vector store backends:
1. Qdrant backend (preferred) — HNSW-indexed search, payload filtering,
   persistence, and scalability. Supports server or embedded mode.
2. JSON backend (fallback) — Pure-Python cosine similarity with JSON
   file storage. Works everywhere, no extra dependencies.

Embedding cache via Redis (optional) — avoids redundant API calls for
repeated queries.
"""

import json
import logging
import math
import os
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

logger = logging.getLogger("agent42.memory.embeddings")

# Strips [ISO_TIMESTAMP SHORT_UUID] tags from bullet lines before embedding.
# Example: "- [2026-03-24T14:22:10Z a4f7b2c1] some text" → "- some text"
_ENTRY_TAG_RE = re.compile(r"\[(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z) ([0-9a-f]{8})\] ")

# ── Local ONNX embedding support ──────────────────────────────────────────
LOCAL_MODEL_NAME = "all-MiniLM-L6-v2"
LOCAL_VECTOR_DIM = 384

try:
    import onnxruntime  # noqa: F401
    from tokenizers import Tokenizer  # noqa: F401

    LOCAL_EMBEDDINGS_AVAILABLE = True
except ImportError:
    LOCAL_EMBEDDINGS_AVAILABLE = False

# Embedding models available on API providers
EMBEDDING_MODELS = {
    "openai": "text-embedding-3-small",  # OpenAI — cheap, 1536 dims
    "openrouter": "openai/text-embedding-3-small",  # Via OpenRouter
}


@dataclass
class EmbeddingEntry:
    """A text chunk with its embedding vector."""

    text: str
    vector: list[float]
    source: str = ""  # "memory" or "history"
    section: str = ""  # Section heading or event type
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


def _find_onnx_model_dir() -> Path | None:
    """Locate the ONNX model directory.

    Checks:
    1. .agent42/models/all-MiniLM-L6-v2/ (project-local)
    2. ~/.agent42/models/all-MiniLM-L6-v2/ (global)
    """
    candidates = [
        Path(os.environ.get("AGENT42_WORKSPACE", ".")) / ".agent42" / "models" / LOCAL_MODEL_NAME,
    ]
    try:
        candidates.append(Path.home() / ".agent42" / "models" / LOCAL_MODEL_NAME)
    except RuntimeError:
        pass  # HOME not set (e.g. in tests with clear=True)
    for p in candidates:
        tokenizer_path = p / "tokenizer.json"
        model_path = p / "onnx" / "model.onnx"
        if tokenizer_path.exists() and model_path.exists():
            return p
    return None


class _OnnxEmbedder:
    """Lightweight ONNX-based text embedder (~23 MB RAM vs ~1 GB for PyTorch)."""

    def __init__(self, model_dir: Path):
        import numpy as np
        import onnxruntime as ort
        from tokenizers import Tokenizer

        self._np = np
        self._tokenizer = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        self._tokenizer.enable_padding(pad_id=0, pad_token="[PAD]")
        self._tokenizer.enable_truncation(max_length=256)
        self._session = ort.InferenceSession(
            str(model_dir / "onnx" / "model.onnx"),
            providers=["CPUExecutionProvider"],
        )
        self.dim = 384  # all-MiniLM-L6-v2

    def encode(self, text: str) -> list[float]:
        """Encode a single text to a normalized embedding vector."""
        return self.encode_batch([text])[0]

    def encode_batch(self, texts: list[str]) -> list[list[float]]:
        """Encode multiple texts to normalized embedding vectors."""
        np = self._np
        encoded = self._tokenizer.encode_batch(texts)

        input_ids = np.array([e.ids for e in encoded], dtype=np.int64)
        attention_mask = np.array([e.attention_mask for e in encoded], dtype=np.int64)
        token_type_ids = np.zeros_like(input_ids)

        outputs = self._session.run(
            None,
            {
                "input_ids": input_ids,
                "attention_mask": attention_mask,
                "token_type_ids": token_type_ids,
            },
        )

        # Mean pooling + L2 normalize
        token_embeddings = outputs[0]
        mask_expanded = attention_mask[:, :, np.newaxis].astype(np.float32)
        summed = np.sum(token_embeddings * mask_expanded, axis=1)
        counts = np.clip(mask_expanded.sum(axis=1), 1e-9, None)
        embeddings = summed / counts
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        embeddings = embeddings / norms

        return embeddings.tolist()


class EmbeddingStore:
    """Pluggable vector store for semantic memory search.

    Uses Qdrant when available (HNSW-indexed), falls back to JSON
    (linear scan). Optionally caches embeddings in Redis.

    Resolution order for embedding API:
    1. EMBEDDING_MODEL + EMBEDDING_PROVIDER env vars (explicit config)
    2. Local ONNX model (no API key, no network, ~23 MB RAM)
    3. OpenAI (if OPENAI_API_KEY is set)
    4. Disabled — falls back to grep search
    """

    def __init__(self, store_path: str | Path, qdrant_store=None, redis_backend=None):
        self.store_path = Path(store_path)
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self._entries: list[EmbeddingEntry] = []
        self._client = None  # AsyncOpenAI — lazy import
        self._onnx_model: _OnnxEmbedder | None = None
        self._model: str = ""
        self._vector_dim: int = 0
        self._loaded = False
        self._qdrant = qdrant_store
        self._redis = redis_backend
        self._provider_resolved = False  # Lazy — don't load model until needed

    def _resolve_provider(self):
        """Find the best available embedding provider.

        Resolution order:
        1. Explicit EMBEDDING_MODEL + EMBEDDING_PROVIDER env vars
        2. Local ONNX model (no API key needed, lightweight)
        3. OpenAI API (if OPENAI_API_KEY is set)
        4. Disabled — falls back to grep search
        """
        # Explicit override
        explicit_model = os.getenv("EMBEDDING_MODEL")
        explicit_provider = os.getenv("EMBEDDING_PROVIDER", "").lower()

        if explicit_model and explicit_provider != "local":
            base_url, api_key = self._provider_config(explicit_provider)
            if api_key:
                from openai import AsyncOpenAI

                self._client = AsyncOpenAI(base_url=base_url, api_key=api_key)
                self._model = explicit_model
                self._vector_dim = 1536
                logger.info(
                    f"Embeddings: using {explicit_model} via {explicit_provider or 'openai'}"
                )
                return

        # Auto-detect: prefer local ONNX (no API key, no network, low memory)
        if LOCAL_EMBEDDINGS_AVAILABLE:
            model_dir = _find_onnx_model_dir()
            if model_dir:
                try:
                    self._onnx_model = _OnnxEmbedder(model_dir)
                    self._model = LOCAL_MODEL_NAME
                    self._vector_dim = self._onnx_model.dim
                    logger.info(
                        f"Embeddings: ONNX model {LOCAL_MODEL_NAME} ({self._vector_dim} dims, ~23 MB)"
                    )
                    return
                except Exception as e:
                    logger.warning(f"Embeddings: ONNX model failed to load: {e}")

        # Fallback: try API providers
        for provider, model in [("openai", EMBEDDING_MODELS["openai"])]:
            base_url, api_key = self._provider_config(provider)
            if api_key:
                from openai import AsyncOpenAI

                self._model = model
                self._vector_dim = 1536
                self._client = AsyncOpenAI(base_url=base_url, api_key=api_key)
                logger.info(f"Embeddings: auto-detected {provider}, using {model}")
                return

        logger.info("Embeddings: no provider available — semantic search disabled")

    @staticmethod
    def _provider_config(provider: str) -> tuple[str, str]:
        """Return (base_url, api_key) for a provider name."""
        configs = {
            "openai": ("https://api.openai.com/v1", os.getenv("OPENAI_API_KEY", "")),
            "openrouter": ("https://openrouter.ai/api/v1", os.getenv("OPENROUTER_API_KEY", "")),
        }
        return configs.get(provider, ("https://api.openai.com/v1", ""))

    def _ensure_provider(self):
        """Lazy-load the embedding provider on first use (avoids OOM at startup)."""
        if not self._provider_resolved:
            self._provider_resolved = True
            self._resolve_provider()

    @property
    def is_available(self) -> bool:
        """Whether semantic search is available (local model or API)."""
        self._ensure_provider()
        return self._onnx_model is not None or self._client is not None

    @property
    def vector_dim(self) -> int:
        """Dimension of the embedding vectors produced by the current provider."""
        self._ensure_provider()
        return self._vector_dim

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
            self._entries.sort(key=lambda e: e.timestamp)
            self._entries = self._entries[-self.MAX_JSON_ENTRIES :]
            logger.info(f"JSON embedding store evicted to {self.MAX_JSON_ENTRIES} entries")
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

        Uses local ONNX model if available, otherwise falls back to API.
        Checks Redis cache first for API calls.
        """
        if not self.is_available:
            raise RuntimeError("No embedding provider configured")

        # Local ONNX model — fast, no network, no cache needed
        if self._onnx_model is not None:
            import asyncio

            return await asyncio.to_thread(self._onnx_model.encode, text)

        # API path — check Redis cache first
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
        """Batch-embed multiple texts.

        Uses local ONNX model for batch encoding if available,
        otherwise falls back to API with Redis cache support.
        """
        if not self.is_available:
            raise RuntimeError("No embedding provider configured")

        # Local ONNX model — batch encode is very efficient
        if self._onnx_model is not None:
            import asyncio

            return await asyncio.to_thread(self._onnx_model.encode_batch, texts)

        # API path — with Redis cache
        use_cache = self._redis and self._redis.is_available
        vectors: list[list[float] | None] = [None] * len(texts)
        uncached_indices: list[int] = []

        if use_cache:
            for i, text in enumerate(texts):
                cached = self._redis.get_cached_embedding(text)
                if cached is not None:
                    vectors[i] = cached
                else:
                    uncached_indices.append(i)
        else:
            uncached_indices = list(range(len(texts)))

        if uncached_indices:
            uncached_texts = [texts[i] for i in uncached_indices]
            api_vectors: list[list[float]] = []
            for i in range(0, len(uncached_texts), 100):
                batch = uncached_texts[i : i + 100]
                response = await self._client.embeddings.create(
                    model=self._model,
                    input=batch,
                )
                api_vectors.extend([d.embedding for d in response.data])

            for idx, vec in zip(uncached_indices, api_vectors):
                vectors[idx] = vec
                if use_cache:
                    self._redis.cache_embedding(texts[idx], vec)

        return vectors  # type: ignore[return-value]

    async def add_entry(
        self, text: str, source: str = "", section: str = "", metadata: dict | None = None
    ):
        """Embed and store a single text entry."""
        from core.task_context import get_task_context

        self._load()
        vector = await self.embed_text(text)

        effective_metadata = dict(metadata or {})
        task_id, task_type = get_task_context()
        if task_id is not None:
            effective_metadata["task_id"] = task_id
        if task_type is not None:
            effective_metadata["task_type"] = task_type

        entry = EmbeddingEntry(
            text=text,
            vector=vector,
            source=source,
            section=section,
            timestamp=time.time(),
            metadata=effective_metadata,
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

    async def search(
        self,
        query: str,
        top_k: int = 5,
        source_filter: str = "",
        collection: str = "",
        task_type_filter: str = "",
    ) -> list[dict]:
        """Semantic search: find the most relevant entries for a query.

        When Qdrant is available, uses HNSW-indexed search with payload
        filtering. Falls back to JSON linear scan if Qdrant is unavailable
        **or if the Qdrant search fails at runtime**.
        """
        # Prefer Qdrant when available
        if self._qdrant and self._qdrant.is_available:
            try:
                query_vector = await self.embed_text(query)
                return self._search_qdrant(
                    query_vector, top_k, source_filter, collection, task_type_filter
                )
            except Exception as e:
                logger.warning("Qdrant search failed, falling through to JSON fallback: %s", e)

        # Fallback: JSON linear scan
        self._load()
        if not self._entries:
            return []
        query_vector = await self.embed_text(query)
        return self._search_json(query_vector, top_k, source_filter)

    def _search_qdrant(
        self,
        query_vector: list[float],
        top_k: int,
        source_filter: str,
        collection: str,
        task_type_filter: str = "",
    ) -> list[dict]:
        """Search via Qdrant backend. Raises on failure so caller can fall back."""
        from memory.qdrant_store import QdrantStore

        if collection:
            return self._qdrant.search(
                collection,
                query_vector,
                top_k=top_k,
                source_filter=source_filter,
                task_type_filter=task_type_filter,
            )

        memory_results = self._qdrant.search(
            QdrantStore.MEMORY,
            query_vector,
            top_k=top_k,
            source_filter=source_filter,
            task_type_filter=task_type_filter,
        )
        history_results = self._qdrant.search(
            QdrantStore.HISTORY,
            query_vector,
            top_k=top_k,
            source_filter=source_filter,
            task_type_filter=task_type_filter,
        )

        combined = memory_results + history_results
        combined.sort(key=lambda x: x["score"], reverse=True)
        return combined[:top_k]

    def _search_json(
        self,
        query_vector: list[float],
        top_k: int,
        source_filter: str,
    ) -> list[dict]:
        """Fallback: JSON linear scan with cosine similarity."""
        self._load()
        if not self._entries:
            return []

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
        """Index the contents of MEMORY.md for semantic search."""
        chunks = self._split_into_chunks(memory_text, source="memory")
        if not chunks:
            return 0

        texts = [c["text"] for c in chunks]
        vectors = await self.embed_texts(texts)

        if self._qdrant and self._qdrant.is_available:
            try:
                from core.task_context import get_task_context
                from memory.qdrant_store import QdrantStore

                self._qdrant.clear_collection(QdrantStore.MEMORY)
                payloads = [{"source": "memory", "section": c.get("section", "")} for c in chunks]

                # Inject task context if available
                task_id, task_type = get_task_context()
                if task_id is not None or task_type is not None:
                    for payload in payloads:
                        if task_id is not None:
                            payload["task_id"] = task_id
                        if task_type is not None:
                            payload["task_type"] = task_type

                count = self._qdrant.upsert_vectors(QdrantStore.MEMORY, texts, vectors, payloads)
                logger.info(f"Indexed {count} memory chunks -> Qdrant")
                return count
            except Exception as e:
                logger.warning("Qdrant index_memory failed, falling back to JSON: %s", e)

        # Fallback: JSON store
        self._load()
        self._entries = [e for e in self._entries if e.source != "memory"]

        for chunk, vector in zip(chunks, vectors):
            self._entries.append(
                EmbeddingEntry(
                    text=chunk["text"],
                    vector=vector,
                    source="memory",
                    section=chunk.get("section", ""),
                    timestamp=time.time(),
                )
            )

        self._save()
        logger.info(f"Indexed {len(chunks)} memory chunks -> JSON")
        return len(chunks)

    async def index_history_entry(self, event_type: str, summary: str, details: str = ""):
        """Index a single history event for semantic search."""
        text = f"{event_type}: {summary}"
        if details:
            text += f"\n{details}"

        if self._qdrant and self._qdrant.is_available:
            try:
                from core.task_context import get_task_context
                from memory.qdrant_store import QdrantStore

                vector = await self.embed_text(text)
                payload = {"source": "history", "section": event_type}

                # Inject task context if available
                task_id, task_type = get_task_context()
                if task_id is not None:
                    payload["task_id"] = task_id
                if task_type is not None:
                    payload["task_type"] = task_type

                self._qdrant.upsert_single(
                    QdrantStore.HISTORY,
                    text,
                    vector,
                    payload,
                )
                return
            except Exception as e:
                logger.warning("Qdrant index_history failed, falling back to JSON: %s", e)

        await self.add_entry(text, source="history", section=event_type)

    async def search_conversations(
        self,
        query: str,
        top_k: int = 5,
        channel_filter: str = "",
        time_after: float = 0.0,
    ) -> list[dict]:
        """Search across conversation summaries. Requires Qdrant."""
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
    def _split_into_chunks(text: str, source: str = "", min_chunk_len: int = 20) -> list[dict]:
        """Split markdown text into meaningful chunks by section.

        Strips [ISO_TIMESTAMP SHORT_UUID] tags from bullet lines before embedding
        so that the identifier prefix does not pollute semantic search vectors.
        """
        chunks = []
        current_section = ""
        current_lines: list[str] = []

        for line in text.split("\n"):
            # Strip UUID entry tags from bullet lines before indexing
            stripped = _ENTRY_TAG_RE.sub("", line)
            if stripped.startswith("## "):
                if current_lines:
                    content = "\n".join(current_lines).strip()
                    if len(content) >= min_chunk_len:
                        chunks.append(
                            {"text": content, "section": current_section, "source": source}
                        )
                current_section = stripped.lstrip("#").strip()
                current_lines = [stripped]
            elif stripped.startswith("# "):
                if current_lines:
                    content = "\n".join(current_lines).strip()
                    if len(content) >= min_chunk_len:
                        chunks.append(
                            {"text": content, "section": current_section, "source": source}
                        )
                current_section = stripped.lstrip("#").strip()
                current_lines = [stripped]
            else:
                current_lines.append(stripped)

        if current_lines:
            content = "\n".join(current_lines).strip()
            if len(content) >= min_chunk_len:
                chunks.append({"text": content, "section": current_section, "source": source})

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
