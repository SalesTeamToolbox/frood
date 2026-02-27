"""
Project-scoped memory — gives each project its own memory namespace.

Every project gets its own MEMORY.md and HISTORY.md under a per-project
directory, plus Qdrant entries tagged with ``project_id`` for scoped
semantic search.  Standalone tasks (no project_id) fall through to the
global MemoryStore with zero behavior change.

Memory budget strategy:
  1. Project memory is queried first (higher relevance).
  2. Remaining budget is filled from global memory (cross-project learning).

This ensures agents working on a project see prior task learnings, reviewer
feedback, and conventions specific to that project, while still benefiting
from global lessons.
"""

import logging
from pathlib import Path

from memory.store import MemoryStore

logger = logging.getLogger("agent42.memory.project")


class ProjectMemoryStore:
    """Per-project memory with automatic fallback to global MemoryStore.

    Files per project:
        {base_dir}/projects/{project_id}/MEMORY.md
        {base_dir}/projects/{project_id}/HISTORY.md
        {base_dir}/projects/{project_id}/embeddings.json

    When the optional Qdrant backend is available, entries include
    ``project_id`` in the payload metadata so searches can be filtered.
    """

    def __init__(
        self,
        project_id: str,
        base_dir: str | Path,
        global_store: MemoryStore,
        qdrant_store=None,
        redis_backend=None,
    ):
        self.project_id = project_id
        self._global = global_store

        # Each project gets its own MemoryStore rooted in a project subdir.
        project_dir = Path(base_dir) / "projects" / project_id
        self._store = MemoryStore(
            workspace_dir=project_dir,
            qdrant_store=qdrant_store,
            redis_backend=redis_backend,
        )
        logger.info("Project memory initialized: %s → %s", project_id, project_dir)

    # -- Delegations to the per-project MemoryStore --

    def read_memory(self) -> str:
        """Read the project-specific memory."""
        return self._store.read_memory()

    def update_memory(self, content: str):
        """Replace the project memory contents."""
        self._store.update_memory(content)

    def append_to_section(self, section: str, content: str):
        """Append to a section in project memory."""
        self._store.append_to_section(section, content)

    def log_event(self, event_type: str, summary: str, details: str = ""):
        """Log an event to the project history."""
        self._store.log_event(event_type, summary, details)

    async def log_event_semantic(self, event_type: str, summary: str, details: str = ""):
        """Log an event and index it for semantic search (project-scoped)."""
        await self._store.log_event_semantic(event_type, summary, details)

    def search_history(self, query: str) -> list[str]:
        """Search the project history."""
        return self._store.search_history(query)

    @property
    def semantic_available(self) -> bool:
        return self._store.semantic_available

    # -- Merged context assembly --

    def build_context(
        self,
        max_memory_lines: int = 50,
        max_history_lines: int = 20,
    ) -> str:
        """Build context from BOTH project memory AND relevant global memory.

        Project memory uses ~60% of the line budget; global gets the rest.
        """
        project_memory_budget = int(max_memory_lines * 0.6)
        global_memory_budget = max_memory_lines - project_memory_budget

        project_history_budget = int(max_history_lines * 0.6)
        global_history_budget = max_history_lines - project_history_budget

        parts = []

        # Project-specific memory (higher priority)
        project_ctx = self._store.build_context(
            max_memory_lines=project_memory_budget,
            max_history_lines=project_history_budget,
        )
        if project_ctx.strip():
            parts.append(f"## Project Memory (project: {self.project_id})\n")
            parts.append(project_ctx)

        # Global memory (cross-project learning)
        global_ctx = self._global.build_context(
            max_memory_lines=global_memory_budget,
            max_history_lines=global_history_budget,
        )
        if global_ctx.strip():
            parts.append("\n## Global Memory (cross-project)\n")
            parts.append(global_ctx)

        return "\n".join(parts)

    async def build_context_semantic(
        self,
        query: str,
        top_k: int = 5,
        max_memory_lines: int = 50,
    ) -> str:
        """Semantic search scoped to project, with global fallback.

        Searches project memory first (project_id filter), then fills
        remaining slots from global memory.
        """
        if not self._store.semantic_available:
            return self.build_context(max_memory_lines=max_memory_lines)

        parts = []

        # Always include project memory text
        project_memory = self._store.read_memory()
        project_lines = project_memory.split("\n")
        project_budget = int(max_memory_lines * 0.6)
        if len(project_lines) > project_budget:
            project_lines = project_lines[:project_budget]
            project_lines.append("... (project memory truncated)")
        parts.append(f"## Project Memory (project: {self.project_id})\n")
        parts.append("\n".join(project_lines))

        # Project-scoped semantic search
        project_k = max(top_k // 2, 2)
        global_k = top_k - project_k

        try:
            project_results = await self._store.semantic_search(query, top_k=project_k)
        except Exception as e:
            logger.warning("Project semantic search failed: %s", e)
            project_results = []

        if project_results:
            parts.append(f"\n## Relevant Project Context (project: {self.project_id})\n")
            for r in project_results:
                score_pct = int(r["score"] * 100)
                parts.append(f"**[{r['source']}/{r['section']}]** ({score_pct}% match)")
                parts.append(r["text"])
                parts.append("")

        # Global semantic search (cross-project learning)
        try:
            global_results = await self._global.semantic_search(query, top_k=global_k)
        except Exception as e:
            logger.warning("Global semantic search failed: %s", e)
            global_results = []

        if global_results:
            parts.append("\n## Relevant Global Context (cross-project)\n")
            for r in global_results:
                score_pct = int(r["score"] * 100)
                parts.append(f"**[{r['source']}/{r['section']}]** ({score_pct}% match)")
                parts.append(r["text"])
                parts.append("")

        return "\n".join(parts)
