"""
Semantic memory — vector embeddings for meaning-based search.

Uses any OpenAI-compatible embedding API (OpenRouter, NVIDIA, OpenAI, etc.)
and a lightweight JSON-backed vector store. No heavy deps (no numpy, no faiss).

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
    "nvidia": "nvidia/nv-embedqa-e5-v5",      # NVIDIA — free tier
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
    """JSON-backed vector store for semantic memory search.

    Resolution order for embedding API:
    1. EMBEDDING_MODEL + EMBEDDING_PROVIDER env vars (explicit config)
    2. OpenAI (if OPENAI_API_KEY is set)
    3. OpenRouter (if OPENROUTER_API_KEY is set)
    4. NVIDIA (if NVIDIA_API_KEY is set)
    5. Disabled — falls back to grep search
    """

    def __init__(self, store_path: str | Path):
        self.store_path = Path(store_path)
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self._entries: list[EmbeddingEntry] = []
        self._client: AsyncOpenAI | None = None
        self._model: str = ""
        self._loaded = False
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
            ("nvidia", EMBEDDING_MODELS["nvidia"]),
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
            "nvidia": ("https://integrate.api.nvidia.com/v1", os.getenv("NVIDIA_API_KEY", "")),
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

    def _save(self):
        """Persist entries to disk."""
        data = [asdict(e) for e in self._entries]
        self.store_path.write_text(
            json.dumps(data, ensure_ascii=False),
            encoding="utf-8",
        )

    async def embed_text(self, text: str) -> list[float]:
        """Get the embedding vector for a text string."""
        if not self._client:
            raise RuntimeError("No embedding API configured")

        response = await self._client.embeddings.create(
            model=self._model,
            input=text,
        )
        return response.data[0].embedding

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Batch-embed multiple texts."""
        if not self._client:
            raise RuntimeError("No embedding API configured")

        # Batch in chunks of 100 (API limits)
        vectors = []
        for i in range(0, len(texts), 100):
            batch = texts[i:i + 100]
            response = await self._client.embeddings.create(
                model=self._model,
                input=batch,
            )
            vectors.extend([d.embedding for d in response.data])
        return vectors

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
                     source_filter: str = "") -> list[dict]:
        """Semantic search: find the most relevant entries for a query.

        Returns list of {text, source, section, score, metadata}.
        """
        self._load()
        if not self._entries:
            return []

        query_vector = await self.embed_text(query)

        # Score all entries
        scored = []
        for entry in self._entries:
            if source_filter and entry.source != source_filter:
                continue
            score = _cosine_similarity(query_vector, entry.vector)
            scored.append((score, entry))

        # Sort by score descending
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
        """
        self._load()
        # Remove old memory entries
        self._entries = [e for e in self._entries if e.source != "memory"]

        # Split into sections
        chunks = self._split_into_chunks(memory_text, source="memory")
        if not chunks:
            return 0

        texts = [c["text"] for c in chunks]
        vectors = await self.embed_texts(texts)

        for chunk, vector in zip(chunks, vectors):
            self._entries.append(EmbeddingEntry(
                text=chunk["text"],
                vector=vector,
                source="memory",
                section=chunk.get("section", ""),
                timestamp=time.time(),
            ))

        self._save()
        logger.info(f"Indexed {len(chunks)} memory chunks")
        return len(chunks)

    async def index_history_entry(self, event_type: str, summary: str,
                                  details: str = ""):
        """Index a single history event for semantic search."""
        text = f"{event_type}: {summary}"
        if details:
            text += f"\n{details}"
        await self.add_entry(text, source="history", section=event_type)

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
