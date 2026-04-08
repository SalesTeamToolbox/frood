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

import asyncio
import logging
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

from memory.embeddings import EmbeddingStore

logger = logging.getLogger("frood.memory")

# ── UUID entry format constants ──────────────────────────────────────────────
# Matches: [2026-03-24T14:22:10Z a4f7b2c1] at start of bullet content
_ENTRY_TAG_RE = re.compile(r"^\[(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z) ([0-9a-f]{8})\] ")
# Matches bullet lines that do NOT already have a UUID prefix (old format)
_ENTRY_NO_UUID_RE = re.compile(r"^(- )(?!\[)(.+)$")
# Matches YAML frontmatter block at start of file
_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
# Lock for async migration to prevent concurrent runs
_MIGRATION_LOCK = asyncio.Lock()
# Deterministic UUID namespace (reused from memory_tool.py and cc-memory-sync-worker.py)
_UUID5_NAMESPACE = uuid.UUID("a42a42a4-2a42-4a42-a42a-42a42a42a42a")


def _make_entry_prefix() -> str:
    """Generate a [ISO_TIMESTAMP SHORT_UUID] prefix for new bullet entries."""
    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    short_id = uuid.uuid4().hex[:8]
    return f"[{ts} {short_id}]"


class MemoryStore:
    """Persistent two-layer memory with semantic search support.

    Optionally integrates with Qdrant (vector DB) and Redis (cache)
    for enhanced search and performance. Falls back to file-based
    storage when these services are unavailable.
    """

    def __init__(self, workspace_dir: str | Path, qdrant_store=None, redis_backend=None):
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
                "# Agent42 History\n\nChronological log of significant events.\n\n"
            )

    # -- UUID identity helpers --

    def _ensure_uuid_frontmatter(self, content: str) -> str:
        """Ensure YAML frontmatter with file_id and last_modified is present.

        Preserves existing file_id (stable identity across updates).
        Updates last_modified on every call.
        If the new content has no frontmatter, tries to recover file_id from
        the existing on-disk file to maintain identity across full replacements.
        """
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        m = _FRONTMATTER_RE.match(content)
        if m:
            # Content already has frontmatter — preserve file_id
            existing = m.group(1)
            file_id = None
            for line in existing.splitlines():
                if line.startswith("file_id:"):
                    file_id = line.split(":", 1)[1].strip()
                    break
            if not file_id:
                file_id = uuid.uuid4().hex
            new_fm = f"---\nfile_id: {file_id}\nlast_modified: {now}\n---\n"
            return new_fm + content[m.end() :]
        else:
            # Content has no frontmatter — try to recover file_id from disk
            file_id = None
            if self.memory_path.exists():
                try:
                    existing_content = self.memory_path.read_text(encoding="utf-8")
                    em = _FRONTMATTER_RE.match(existing_content)
                    if em:
                        for line in em.group(1).splitlines():
                            if line.startswith("file_id:"):
                                file_id = line.split(":", 1)[1].strip()
                                break
                except OSError:
                    pass
            if not file_id:
                file_id = uuid.uuid4().hex
            return f"---\nfile_id: {file_id}\nlast_modified: {now}\n---\n{content}"

    async def _maybe_migrate(self):
        """Auto-migrate old-format bullets (no UUID) to UUID format.

        Uses UUID5 from content hash for deterministic IDs — both nodes independently
        arrive at the same UUIDs for the same content.
        Guards against concurrent migration with a lock + sentinel file.
        """
        sentinel = self.workspace_dir / ".migration_v1"
        if sentinel.exists():
            return
        async with _MIGRATION_LOCK:
            if sentinel.exists():
                return  # Another coroutine migrated while we waited
            if not self.memory_path.exists():
                return
            content = self.memory_path.read_text(encoding="utf-8")
            ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

            def _migrate_line(line: str) -> str:
                m = _ENTRY_NO_UUID_RE.match(line)
                if not m:
                    return line
                text = m.group(2)
                short_id = uuid.uuid5(_UUID5_NAMESPACE, text).hex[:8]
                return f"- [{ts} {short_id}] {text}"

            migrated = "\n".join(_migrate_line(line) for line in content.splitlines())
            migrated = self._ensure_uuid_frontmatter(migrated)
            self.memory_path.write_text(migrated, encoding="utf-8")
            sentinel.write_text("migrated\n", encoding="utf-8")
            logger.info("MEMORY.md migrated to UUID format")

    # -- MEMORY.md (consolidated facts) --

    def read_memory(self) -> str:
        """Read the current memory, triggering auto-migration of legacy format if needed."""
        # Check sentinel (sync fast-path: sentinel exists = skip migration entirely)
        sentinel = self.workspace_dir / ".migration_v1"
        if not sentinel.exists() and self.memory_path.exists():
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._maybe_migrate())
            except RuntimeError:
                # No running event loop — run synchronously
                asyncio.run(self._maybe_migrate())
        return self.memory_path.read_text(encoding="utf-8")

    def update_memory(self, content: str):
        """Replace the entire memory contents.

        Ensures YAML frontmatter (file_id + last_modified) is present.
        Schedules an async reindex of embeddings if semantic search is available.
        """
        content = self._ensure_uuid_frontmatter(content)
        self.memory_path.write_text(content, encoding="utf-8")
        # Notify Redis of memory change (cache invalidation)
        if self._redis and self._redis.is_available:
            self._redis.increment_memory_version()
        # Schedule reindex so semantic search stays current
        self._schedule_reindex()
        logger.info("Memory updated")

    def _schedule_reindex(self):
        """Schedule an async reindex of memory embeddings (fire-and-forget)."""
        if not self.embeddings.is_available:
            return

        import asyncio

        async def _reindex():
            try:
                count = await self.reindex_memory()
                logger.debug(f"Auto-reindexed {count} memory chunks")
            except Exception as e:
                logger.warning(f"Auto-reindex failed (non-critical): {e}")

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_reindex())
        except RuntimeError:
            # No running event loop — run synchronously
            try:
                asyncio.run(_reindex())
            except Exception as e:
                logger.debug(f"Sync reindex failed (non-critical): {e}")

    def append_to_section(self, section: str, content: str):
        """Append content under a specific section heading."""
        memory = self.read_memory()
        marker = f"## {section}"

        if marker in memory:
            # Insert after the section heading
            idx = memory.index(marker) + len(marker)
            # Find end of line
            nl = memory.index("\n", idx) if "\n" in memory[idx:] else len(memory)
            prefix = _make_entry_prefix()
            memory = memory[:nl] + f"\n- {prefix} {content}" + memory[nl:]
        else:
            # Add new section
            prefix = _make_entry_prefix()
            memory += f"\n## {section}\n\n- {prefix} {content}\n"

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

        timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
        entry = f"### [{timestamp}] {event_type}\n{summary}\n"
        if details:
            entry += f"\n{details}\n"
        entry += "\n---\n\n"

        with open(self.history_path, "a", encoding="utf-8") as f:
            f.write(entry)

        logger.debug(f"History logged: {event_type} — {summary}")

    def _rotate_history_if_needed(self):
        """Rotate history file if it exceeds MAX_HISTORY_SIZE.

        Archives use timestamped filenames to prevent overwriting previous
        rotations (e.g. HISTORY.2026-02-22T15-30-00.md).
        """
        if not self.history_path.exists():
            return
        try:
            size = self.history_path.stat().st_size
            if size > self.MAX_HISTORY_SIZE:
                content = self.history_path.read_text(encoding="utf-8")
                midpoint = len(content) // 2
                boundary = content.find("\n---\n", midpoint)
                if boundary == -1:
                    # Search backward from midpoint for nearest entry separator
                    boundary = content.rfind("\n---\n", 0, midpoint)
                if boundary > 0:
                    archived = content[: boundary + 5]
                    kept = content[boundary + 5 :]
                else:
                    # No separator found; split at nearest newline to avoid mid-entry corruption
                    nl = content.find("\n", midpoint)
                    if nl == -1:
                        nl = midpoint
                    kept = content[nl + 1 :]
                    archived = content[: nl + 1]

                ts = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%S")
                archive_name = self.history_path.stem + f".{ts}.md"
                archive_path = self.history_path.parent / archive_name
                archive_path.write_text(archived, encoding="utf-8")
                self.history_path.write_text(
                    "# Agent42 History (rotated)\n\n" + kept,
                    encoding="utf-8",
                )
                logger.info(
                    f"History rotated: {size} -> {len(kept)} bytes, archived to {archive_name}"
                )
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

    async def semantic_search(
        self,
        query: str,
        top_k: int = 5,
        source: str = "",
        project: str = "",
        lifecycle_aware: bool = True,
        task_type: str = "",
    ) -> list[dict]:
        """Search memory and history using semantic similarity.

        When lifecycle_aware=True and Qdrant is available, uses lifecycle-adjusted
        scoring (confidence, recall_count, decay). Also records that returned
        memories were recalled (for strengthening).

        Falls back to grep-based search if no embedding API is configured.
        Returns list of {text, source, section, score, ...}.
        """
        if not self.embeddings.is_available:
            # Graceful fallback to grep
            grep_results = self.search_history(query)
            return [
                {"text": line, "source": "history", "section": "", "score": 0.0}
                for line in grep_results[:top_k]
            ]

        # Use lifecycle-aware search when Qdrant is available
        if lifecycle_aware and self._qdrant and self._qdrant.is_available:
            try:
                query_vector = await self.embeddings.embed_text(query)
                from memory.qdrant_store import QdrantStore

                # Search across memory and history with lifecycle scoring
                memory_results = self._qdrant.search_with_lifecycle(
                    QdrantStore.MEMORY,
                    query_vector,
                    top_k=top_k,
                    source_filter=source,
                    project_filter=project,
                    task_type_filter=task_type,
                )
                history_results = self._qdrant.search_with_lifecycle(
                    QdrantStore.HISTORY,
                    query_vector,
                    top_k=top_k,
                    source_filter=source,
                    project_filter=project,
                    task_type_filter=task_type,
                )

                # Merge and re-sort by adjusted score
                combined = memory_results + history_results
                combined.sort(key=lambda x: x["score"], reverse=True)
                results = combined[:top_k]

                # Record recalls (fire-and-forget)
                self._record_recalls(results)

                return results
            except Exception as e:
                logger.warning("Lifecycle search failed, falling back: %s", e)

        # Standard (non-lifecycle) search
        return await self.embeddings.search(
            query, top_k=top_k, source_filter=source, task_type_filter=task_type
        )

    def _record_recalls(self, results: list[dict]):
        """Record that these memories were recalled (updates Qdrant metadata)."""
        if not self._qdrant or not self._qdrant.is_available:
            return

        from memory.qdrant_store import QdrantStore

        for r in results:
            point_id = r.get("point_id")
            source = r.get("source", "")
            if not point_id:
                continue

            collection = QdrantStore.MEMORY if source == "memory" else QdrantStore.HISTORY
            try:
                self._qdrant.record_recall(collection, [point_id])
            except Exception:
                pass  # Non-critical

    async def strengthen_memory(self, query: str, boost: float = 0.1) -> int:
        """Strengthen memories matching the query (user confirmed useful).

        Returns number of memories strengthened.
        """
        if not self._qdrant or not self._qdrant.is_available or not self.embeddings.is_available:
            return 0

        from memory.qdrant_store import QdrantStore

        query_vector = await self.embeddings.embed_text(query)
        count = 0

        for collection in [QdrantStore.MEMORY, QdrantStore.HISTORY]:
            results = self._qdrant.search_with_lifecycle(collection, query_vector, top_k=3)
            for r in results:
                point_id = r.get("point_id")
                if point_id and r.get("score", 0) > 0.7:
                    if self._qdrant.strengthen_point(collection, point_id, boost):
                        count += 1

        return count

    async def forget_semantic(self, query: str) -> int:
        """Mark memories matching the query as forgotten in Qdrant.

        Forgotten memories are excluded from future searches but not deleted.
        Returns number of memories forgotten.
        """
        if not self._qdrant or not self._qdrant.is_available or not self.embeddings.is_available:
            return 0

        from memory.qdrant_store import QdrantStore

        query_vector = await self.embeddings.embed_text(query)
        count = 0

        for collection in [QdrantStore.MEMORY, QdrantStore.HISTORY]:
            results = self._qdrant.find_by_text(collection, query_vector, query, top_k=5)
            for r in results:
                point_id = r.get("point_id")
                if point_id:
                    if self._qdrant.set_status(collection, point_id, "forgotten"):
                        count += 1

        return count

    async def reindex_memory(self):
        """Re-index MEMORY.md for semantic search.

        Call this after updating memory contents.
        Reads raw file content directly to avoid triggering migration in
        the middle of an update_memory() → _schedule_reindex() cycle.
        """
        if not self.embeddings.is_available:
            return 0
        # Use raw file read to avoid triggering auto-migration during reindex
        memory = self.memory_path.read_text(encoding="utf-8") if self.memory_path.exists() else ""
        return await self.embeddings.index_memory(memory)

    async def log_event_semantic(self, event_type: str, summary: str, details: str = ""):
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

    async def build_context_semantic(
        self, query: str, top_k: int = 5, max_memory_lines: int = 50, task_type: str = ""
    ) -> str:
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

        # Add semantically relevant context from memory + history.
        # Gracefully degrade to non-semantic context if the embedding API
        # fails at runtime (e.g. invalid key, provider outage).
        try:
            results = await self.embeddings.search(query, top_k=top_k, task_type_filter=task_type)
        except Exception as e:
            logger.warning("Semantic search failed, falling back to basic context: %s", e)
            return self.build_context(max_memory_lines=max_memory_lines)

        if results:
            parts.append("\n## Relevant Context (semantic search)\n")
            for r in results:
                score_pct = int(r["score"] * 100)
                parts.append(f"**[{r['source']}/{r['section']}]** ({score_pct}% match)")
                parts.append(r["text"])
                parts.append("")

        # Add relevant past conversations (Qdrant only)
        try:
            conv_results = await self.embeddings.search_conversations(
                query,
                top_k=3,
            )
        except Exception as e:
            logger.warning("Conversation search failed: %s", e)
            conv_results = []
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


async def build_conversational_memory_context(
    memory_store: "MemoryStore | None",
    query: str,
    timeout: float = 5.0,
    max_memory_lines: int = 30,
    max_history_lines: int = 10,
    top_k: int = 3,
) -> str:
    """Build lightweight memory context for conversational (non-task) responses.

    Uses smaller budgets and a timeout on semantic search to keep latency low.
    Returns empty string on failure (never raises).
    """
    if not memory_store:
        return ""

    import asyncio

    try:
        if memory_store.semantic_available:
            return await asyncio.wait_for(
                memory_store.build_context_semantic(
                    query=query,
                    top_k=top_k,
                    max_memory_lines=max_memory_lines,
                ),
                timeout=timeout,
            )
        else:
            return memory_store.build_context(
                max_memory_lines=max_memory_lines,
                max_history_lines=max_history_lines,
            )
    except Exception as e:
        logger.warning("Conversational memory context failed: %s", e)
        try:
            return memory_store.build_context(
                max_memory_lines=max_memory_lines,
                max_history_lines=max_history_lines,
            )
        except Exception:
            return ""
