"""
Two-layer persistent memory system with optional semantic search.

Inspired by Nanobot's MEMORY.md + HISTORY.md pattern:
- MEMORY.md: Consolidated facts, preferences, and learnings (editable)
- HISTORY.md: Append-only chronological event log (grep-searchable)
- embeddings.json: Vector embeddings for semantic search (auto-managed)

Enhanced storage backends (optional, auto-detected):
- Qdrant: HNSW-indexed vector search for sub-ms semantic retrieval
- Redis: Session caching, embedding cache, cross-instance sharing

Semantic search is enabled automatically when any embedding-capable API
key is configured (OpenAI or OpenRouter). Falls back to grep when no
embedding API is available.
"""

import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from memory.embeddings import EmbeddingStore

logger = logging.getLogger("agent42.memory")


class MemoryStore:
    """Persistent two-layer memory with semantic search support.

    Optionally integrates with Qdrant (vector DB) and Redis (cache)
    for enhanced search and performance. Falls back to file-based
    storage when these services are unavailable.
    """

    def __init__(self, workspace_dir: str | Path, qdrant_store=None,
                 redis_backend=None):
        self.workspace_dir = Path(workspace_dir)
        self.memory_path = self.workspace_dir / "MEMORY.md"
        self.history_path = self.workspace_dir / "HISTORY.md"
        self._qdrant = qdrant_store
        self._redis = redis_backend
        self.embeddings = EmbeddingStore(
            self.workspace_dir / "embeddings.json",
            qdrant_store=qdrant_store,
            redis_backend=redis_backend,
        )
        self._ensure_files()

    def _ensure_files(self):
        """Create memory files if they don't exist."""
        self.workspace_dir.mkdir(parents=True, exist_ok=True)

        if not self.memory_path.exists():
            self.memory_path.write_text(
                "# Agent42 Memory\n\n"
                "Consolidated knowledge and learnings from agent interactions.\n\n"
                "## User Preferences\n\n"
                "## Project Conventions\n\n"
                "## Common Patterns\n\n"
            )

        if not self.history_path.exists():
            self.history_path.write_text(
                "# Agent42 History\n\n"
                "Chronological log of significant events.\n\n"
            )

    # -- MEMORY.md (consolidated facts) --

    def read_memory(self) -> str:
        """Read the current memory."""
        return self.memory_path.read_text(encoding="utf-8")

    def update_memory(self, content: str):
        """Replace the entire memory contents."""
        self.memory_path.write_text(content, encoding="utf-8")
        # Notify Redis of memory change (cache invalidation)
        if self._redis and self._redis.is_available:
            self._redis.increment_memory_version()
        logger.info("Memory updated")

    def append_to_section(self, section: str, content: str):
        """Append content under a specific section heading."""
        memory = self.read_memory()
        marker = f"## {section}"

        if marker in memory:
            # Insert after the section heading
            idx = memory.index(marker) + len(marker)
            # Find end of line
            nl = memory.index("\n", idx) if "\n" in memory[idx:] else len(memory)
            memory = memory[:nl] + f"\n- {content}" + memory[nl:]
        else:
            # Add new section
            memory += f"\n## {section}\n\n- {content}\n"

        self.update_memory(memory)

    # -- HISTORY.md (append-only event log) --

    def read_history(self) -> str:
        """Read the full history."""
        return self.history_path.read_text(encoding="utf-8")

    # Maximum size for history file before rotation (1MB)
    MAX_HISTORY_SIZE = 1_000_000

    def log_event(self, event_type: str, summary: str, details: str = ""):
        """Append an event to the history log. Rotates if the file is too large."""
        self._rotate_history_if_needed()

        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        entry = f"### [{timestamp}] {event_type}\n{summary}\n"
        if details:
            entry += f"\n{details}\n"
        entry += "\n---\n\n"

        with open(self.history_path, "a", encoding="utf-8") as f:
            f.write(entry)

        logger.debug(f"History logged: {event_type} — {summary}")

    def _rotate_history_if_needed(self):
        """Rotate history file if it exceeds MAX_HISTORY_SIZE."""
        if not self.history_path.exists():
            return
        try:
            size = self.history_path.stat().st_size
            if size > self.MAX_HISTORY_SIZE:
                content = self.history_path.read_text(encoding="utf-8")
                midpoint = len(content) // 2
                boundary = content.find("\n---\n", midpoint)
                if boundary > 0:
                    archived = content[:boundary + 5]
                    kept = content[boundary + 5:]
                else:
                    kept = content[midpoint:]
                    archived = content[:midpoint]

                archive_path = self.history_path.with_suffix(".old.md")
                archive_path.write_text(archived, encoding="utf-8")
                self.history_path.write_text(
                    "# Agent42 History (rotated)\n\n" + kept,
                    encoding="utf-8",
                )
                logger.info(f"History rotated: {size} -> {len(kept)} bytes")
        except Exception as e:
            logger.warning(f"History rotation failed: {e}")

    def search_history(self, query: str) -> list[str]:
        """Search history for entries matching a query (grep-like)."""
        history = self.read_history()
        results = []
        for line in history.split("\n"):
            if query.lower() in line.lower():
                results.append(line)
        return results

    # -- Semantic search (embeddings-powered) --

    @property
    def semantic_available(self) -> bool:
        """Whether semantic search is available (embedding API configured)."""
        return self.embeddings.is_available

    async def semantic_search(self, query: str, top_k: int = 5,
                              source: str = "") -> list[dict]:
        """Search memory and history using semantic similarity.

        Falls back to grep-based search if no embedding API is configured.
        Returns list of {text, source, section, score}.
        """
        if not self.embeddings.is_available:
            # Graceful fallback to grep
            grep_results = self.search_history(query)
            return [
                {"text": line, "source": "history", "section": "", "score": 0.0}
                for line in grep_results[:top_k]
            ]
        return await self.embeddings.search(query, top_k=top_k, source_filter=source)

    async def reindex_memory(self):
        """Re-index MEMORY.md for semantic search.

        Call this after updating memory contents.
        """
        if not self.embeddings.is_available:
            return 0
        memory = self.read_memory()
        return await self.embeddings.index_memory(memory)

    async def log_event_semantic(self, event_type: str, summary: str,
                                 details: str = ""):
        """Log an event and index it for semantic search.

        Use this instead of log_event() when semantic indexing is desired.
        """
        self.log_event(event_type, summary, details)
        if self.embeddings.is_available:
            await self.embeddings.index_history_entry(event_type, summary, details)

    # -- Context building --

    def build_context(self, max_memory_lines: int = 50, max_history_lines: int = 20) -> str:
        """Build memory context for inclusion in agent prompts."""
        parts = []

        # Include memory
        memory = self.read_memory()
        memory_lines = memory.split("\n")
        if len(memory_lines) > max_memory_lines:
            memory_lines = memory_lines[:max_memory_lines]
            memory_lines.append("... (memory truncated)")
        parts.append("## Persistent Memory\n")
        parts.append("\n".join(memory_lines))

        # Include recent history
        history = self.read_history()
        history_lines = history.split("\n")
        if history_lines:
            recent = history_lines[-max_history_lines:]
            parts.append("\n## Recent History\n")
            parts.append("\n".join(recent))

        return "\n".join(parts)

    async def build_context_semantic(self, query: str, top_k: int = 5,
                                     max_memory_lines: int = 50) -> str:
        """Build context augmented with semantically relevant memory.

        When a query is provided, includes the most relevant memory chunks
        instead of just recent history. Also searches past conversations
        when Qdrant is available.

        Falls back to build_context() if semantic search is unavailable.
        """
        if not self.embeddings.is_available:
            return self.build_context(max_memory_lines=max_memory_lines)

        parts = []

        # Always include current memory
        memory = self.read_memory()
        memory_lines = memory.split("\n")
        if len(memory_lines) > max_memory_lines:
            memory_lines = memory_lines[:max_memory_lines]
            memory_lines.append("... (memory truncated)")
        parts.append("## Persistent Memory\n")
        parts.append("\n".join(memory_lines))

        # Add semantically relevant context from memory + history
        results = await self.embeddings.search(query, top_k=top_k)
        if results:
            parts.append("\n## Relevant Context (semantic search)\n")
            for r in results:
                score_pct = int(r["score"] * 100)
                parts.append(f"**[{r['source']}/{r['section']}]** ({score_pct}% match)")
                parts.append(r["text"])
                parts.append("")

        # Add relevant past conversations (Qdrant only)
        conv_results = await self.embeddings.search_conversations(
            query, top_k=3,
        )
        if conv_results:
            parts.append("\n## Related Past Conversations\n")
            for r in conv_results:
                score_pct = int(r["score"] * 100)
                channel = r.get("metadata", {}).get("channel_type", "unknown")
                parts.append(f"**[{channel}]** ({score_pct}% match)")
                # Truncate long conversation summaries
                text = r["text"]
                if len(text) > 500:
                    text = text[:500] + "..."
                parts.append(text)
                parts.append("")

        return "\n".join(parts)
