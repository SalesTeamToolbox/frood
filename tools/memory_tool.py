"""
MemoryTool — explicit read/write access to the persistent memory system.

Without this tool the agent can *see* memory context injected into its prompt
but has no way to *write* new memories.  The memory skill describes the memory
system, but previously there was no corresponding tool — the agent would claim
"stored in MEMORY.md" without actually writing anything.

Operations:
  store    — persist a fact, preference, or learning to MEMORY.md
  recall   — read the current memory (optionally search by query)
  log      — append an event to HISTORY.md
  search   — search memory and history for a keyword/phrase
  forget   — remove a specific section or entry from MEMORY.md
  correct  — update/replace content in a memory section
"""

import logging

from tools.base import Tool, ToolResult

logger = logging.getLogger("frood.tools.memory")

# Semantic similarity thresholds for deduplication
DEDUP_THRESHOLD = 0.90  # >= this = near-duplicate, skip or merge
DEDUP_SEARCH_THRESHOLD = 0.85  # >= this in results = collapse duplicates


def _deduplicate_results(
    results: list[str], threshold: float = DEDUP_SEARCH_THRESHOLD
) -> list[str]:
    """Remove near-duplicate entries from search results by text similarity.

    Uses simple token overlap (Jaccard) since we don't want to call the
    embedding model just to deduplicate a handful of result strings.
    """
    if len(results) <= 1:
        return results

    def _jaccard(a: str, b: str) -> float:
        sa = set(a.lower().split())
        sb = set(b.lower().split())
        if not sa or not sb:
            return 0.0
        return len(sa & sb) / len(sa | sb)

    # Extract the text portion (after the [tag] prefix) for comparison
    def _text_of(entry: str) -> str:
        idx = entry.find("] ")
        return entry[idx + 2 :] if idx >= 0 else entry

    kept: list[str] = []
    for entry in results:
        text = _text_of(entry)
        is_dup = False
        for existing in kept:
            if _jaccard(text, _text_of(existing)) >= threshold:
                is_dup = True
                break
        if not is_dup:
            kept.append(entry)
    return kept


class MemoryTool(Tool):
    """Read/write persistent memory (MEMORY.md + HISTORY.md).

    This tool gives the agent explicit access to the two-layer memory
    system so it can store user-requested information and recall it in
    later sessions.

    Requires ``memory_store`` from ToolContext injection.
    """

    requires = ["memory_store", "project_memory_factory"]

    def __init__(self, memory_store=None, project_memory_factory=None, **kwargs):
        self._store = memory_store
        self._project_factory = project_memory_factory

    def _get_store(self, project: str = "global"):
        """Route to project-scoped or global store based on project parameter."""
        if project and project != "global" and self._project_factory:
            return self._project_factory(project)
        if project and project != "global" and not self._project_factory:
            logger.warning(
                "project_memory_factory not registered; project='%s' will use global store. "
                "Project namespace isolation is not active.",
                project,
            )
        return self._store

    @property
    def name(self) -> str:
        return "memory"

    @property
    def description(self) -> str:
        return (
            "Read and write persistent memory with lifecycle management. "
            "Use 'store' to save facts, preferences, or learnings to MEMORY.md. "
            "Use 'recall' to retrieve the current memory contents. "
            "Use 'log' to record an event in the chronological HISTORY.md. "
            "Use 'search' to find specific past information by keyword or phrase. "
            "Use 'forget' to remove a section from MEMORY.md and mark as forgotten in Qdrant. "
            "Use 'correct' to replace content in a specific memory section. "
            "Use 'strengthen' to confirm a recalled memory was useful (boosts confidence)."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "store",
                        "recall",
                        "log",
                        "search",
                        "forget",
                        "correct",
                        "strengthen",
                        "reindex_cc",
                        "consolidate",
                        "repair",
                    ],
                    "description": (
                        "store: save information to MEMORY.md under a section; "
                        "recall: read current memory contents; "
                        "log: append an event to HISTORY.md; "
                        "search: search memory and history by keyword; "
                        "forget: remove a section from MEMORY.md and mark forgotten in Qdrant; "
                        "correct: replace content in a memory section; "
                        "strengthen: confirm a recalled memory was useful (boosts confidence); "
                        "reindex_cc: scan all Claude Code memory files and sync missing ones to Qdrant; "
                        "consolidate: run dedup consolidation on Qdrant memory (removes duplicates, flags near-matches); "
                        "repair: scan a harness's flat-file memory for dangling index links, orphan files, and exact duplicates (dry-run default)"
                    ),
                },
                "section": {
                    "type": "string",
                    "description": (
                        "Section heading in MEMORY.md to store under "
                        "(e.g. 'User Preferences', 'Project Conventions', 'Common Patterns'). "
                        "Required for 'store' action."
                    ),
                },
                "content": {
                    "type": "string",
                    "description": (
                        "The content to store or log. For 'store': the fact or preference. "
                        "For 'log': a summary of the event. For 'search': the search query."
                    ),
                },
                "event_type": {
                    "type": "string",
                    "description": (
                        "Category for 'log' action (e.g. 'user_request', "
                        "'task_completed', 'decision', 'error'). Defaults to 'note'."
                    ),
                },
                "project": {
                    "type": "string",
                    "description": (
                        "Project scope for the memory. Use 'global' for cross-project "
                        "memories, or a project name for project-specific ones. "
                        "Defaults to 'global'."
                    ),
                },
                "harness": {
                    "type": "string",
                    "description": (
                        "Harness whose flat-file memory to repair (for 'repair' action). "
                        "Phase 1 supports 'claude_code' only. Defaults to 'claude_code'."
                    ),
                },
                "dry_run": {
                    "type": "boolean",
                    "description": (
                        "For 'repair' action: when true (default) nothing is mutated, "
                        "only the audit log is written. Set false to apply changes."
                    ),
                },
            },
            "required": ["action"],
        }

    async def execute(
        self,
        action: str = "recall",
        section: str = "",
        content: str = "",
        event_type: str = "note",
        project: str = "global",
        harness: str = "claude_code",
        dry_run: bool = True,
        **kwargs,
    ) -> ToolResult:
        if action == "repair":
            return await self._handle_repair(harness=harness, dry_run=dry_run)

        if not self._store:
            return ToolResult(
                output="Memory system is not initialized.",
                error="No memory store available.",
                success=False,
            )

        if action == "store":
            return await self._handle_store(section, content, project)
        elif action == "recall":
            return self._handle_recall(project)
        elif action == "log":
            return await self._handle_log(event_type, content)
        elif action == "search":
            return await self._handle_search(content, project)
        elif action == "forget":
            return await self._handle_forget(section, content)
        elif action == "correct":
            return await self._handle_correct(section, content)
        elif action == "strengthen":
            return await self._handle_strengthen(content)
        elif action == "reindex_cc":
            return await self._handle_reindex_cc()
        elif action == "consolidate":
            return await self._handle_consolidate()
        else:
            return ToolResult(
                output=f"Unknown action: {action}. Use store, recall, log, search, forget, correct, strengthen, reindex_cc, consolidate, or repair.",
                success=False,
            )

    async def _handle_repair(self, harness: str, dry_run: bool) -> ToolResult:
        from core.config import settings
        from memory.repair import build_adapter, run_repair

        if not settings.memory_repair_enabled:
            return ToolResult(
                output="Memory repair is disabled (MEMORY_REPAIR_ENABLED=false).",
                success=False,
            )

        try:
            adapter = build_adapter(harness)
        except ValueError as exc:
            return ToolResult(output=str(exc), success=False)

        effective_dry_run = dry_run or not settings.memory_repair_apply
        result = await run_repair(
            adapter=adapter,
            harness=harness,
            dry_run=effective_dry_run,
            snapshot_dir=settings.memory_repair_snapshot_dir,
            audit_log=settings.memory_repair_audit_log,
        )
        summary = (
            f"memory-repair [{harness}] mode={'dry-run' if result.dry_run else 'apply'} "
            f"scanned={result.plans_scanned} proposed={result.ops_proposed} "
            f"applied={result.ops_applied} flagged={result.ops_flagged} "
            f"skipped={result.ops_skipped}"
        )
        if result.error:
            summary += f" last_error={result.error}"
        return ToolResult(output=summary, success=result.error is None)

    async def _handle_store(
        self, section: str, content: str, project: str = "global"
    ) -> ToolResult:
        if not content or not content.strip():
            return ToolResult(
                output="No content provided. Specify what to remember.",
                success=False,
            )
        section = section.strip() or "General"
        content = content.strip()

        try:
            store = self._get_store(project)

            # Write-time dedup: check if a near-duplicate already exists
            if store.semantic_available:
                try:
                    existing = await store.semantic_search(content, top_k=1)
                    if existing:
                        top = existing[0]
                        score = top.get("score", 0)
                        if score >= DEDUP_THRESHOLD:
                            existing_text = top.get("text", top.get("summary", ""))
                            logger.info(
                                "Duplicate memory detected (score=%.2f), skipping: %s",
                                score,
                                content[:80],
                            )
                            return ToolResult(
                                output=(
                                    f"Memory already exists (similarity {score:.0%}): "
                                    f"{existing_text[:200]}"
                                )
                            )
                except Exception as e:
                    logger.debug("Dedup check failed, storing anyway: %s", e)

            # 1. Write to MEMORY.md (flat file, always works)
            store.append_to_section(section, content)

            # 2. Index in Qdrant for semantic search (if available)
            semantic_indexed = False
            if self._store.semantic_available:
                try:
                    # Include lifecycle metadata for new memories

                    metadata = {
                        "confidence": 0.5,
                        "recall_count": 0,
                        "last_recalled": 0,
                        "status": "active",
                        "project": project,
                    }
                    await self._store.log_event_semantic(
                        event_type="memory",
                        summary=f"[{section}] {content}",
                        details=content,
                    )
                    # Update the just-stored point with lifecycle metadata
                    if self._store._qdrant and self._store._qdrant.is_available:
                        from memory.qdrant_store import QdrantStore

                        query_vector = await self._store.embeddings.embed_text(
                            f"[{section}] {content}"
                        )
                        hits = self._store._qdrant.find_by_text(
                            QdrantStore.HISTORY, query_vector, content[:50], top_k=1
                        )
                        if hits:
                            self._store._qdrant.update_payload(
                                QdrantStore.HISTORY, hits[0]["point_id"], metadata
                            )
                    semantic_indexed = True
                except Exception as e:
                    logger.warning("Semantic indexing failed (stored in flat file): %s", e)

            # 3. Reindex MEMORY.md into Qdrant memory collection
            # (_schedule_reindex is fire-and-forget and may not complete
            #  before MCP response is sent — do an explicit await here)
            if self._store.semantic_available:
                try:
                    await self._store.reindex_memory()
                except Exception as e:
                    logger.warning("Memory reindex failed (non-critical): %s", e)

            mode = "semantic + file" if semantic_indexed else "file only"
            logger.info("Memory stored (%s): [%s] %s", mode, section, content[:80])

            # Check if consolidation should trigger (fire-and-forget background task)
            if semantic_indexed:
                try:
                    from memory.consolidation_worker import (
                        increment_entries_since,
                        should_trigger_consolidation,
                    )

                    increment_entries_since()
                    if should_trigger_consolidation():
                        import asyncio

                        from memory.consolidation_worker import run_consolidation

                        async def _bg_consolidate():
                            try:
                                await asyncio.to_thread(run_consolidation, self._store._qdrant)
                            except Exception as _bg_err:
                                logger.warning("Background consolidation failed: %s", _bg_err)

                        try:
                            loop = asyncio.get_running_loop()
                            loop.create_task(_bg_consolidate())
                        except RuntimeError:
                            pass
                except Exception:
                    pass  # Consolidation check is non-critical

            return ToolResult(output=f"Stored in memory under '{section}': {content}")
        except Exception as e:
            logger.error("Failed to store memory: %s", e)
            return ToolResult(
                output=f"Failed to store memory: {e}",
                error=str(e),
                success=False,
            )

    def _handle_recall(self, project: str = "global") -> ToolResult:
        try:
            store = self._get_store(project)
            memory = store.read_memory()
            if not memory or not memory.strip():
                return ToolResult(output="Memory is empty. Nothing stored yet.")
            return ToolResult(output=memory)
        except Exception as e:
            logger.error("Failed to read memory: %s", e)
            return ToolResult(
                output=f"Failed to read memory: {e}",
                error=str(e),
                success=False,
            )

    async def _handle_log(self, event_type: str, content: str) -> ToolResult:
        if not content or not content.strip():
            return ToolResult(
                output="No content provided. Specify the event summary.",
                success=False,
            )
        event_type = event_type.strip() or "note"
        content = content.strip()

        try:
            # Use semantic indexing so history entries get vectorized in Qdrant
            if self._store.semantic_available:
                await self._store.log_event_semantic(event_type, content)
            else:
                self._store.log_event(event_type, content)
            logger.info("History logged: [%s] %s", event_type, content[:80])
            return ToolResult(output=f"Event logged to history: [{event_type}] {content}")
        except Exception as e:
            logger.error("Failed to log event: %s", e)
            return ToolResult(
                output=f"Failed to log event: {e}",
                error=str(e),
                success=False,
            )

    async def _handle_forget(self, section: str, content: str = "") -> ToolResult:
        if not section and not content:
            return ToolResult(
                output="Provide a section name or content to forget.",
                success=False,
            )

        forgotten_qdrant = 0
        section = (section or "").strip()
        content = (content or "").strip()

        try:
            # 1. Remove from flat file (by section)
            if section:
                memory = self._store.read_memory()
                lines = memory.split("\n")
                new_lines = []
                skip = False

                for line in lines:
                    if line.startswith("## "):
                        heading = line[3:].strip()
                        if heading.lower() == section.lower():
                            skip = True
                            continue
                        else:
                            skip = False
                    if not skip:
                        new_lines.append(line)

                new_content = "\n".join(new_lines).strip() + "\n"
                self._store.update_memory(new_content)

            # 2. Mark as forgotten in Qdrant (by content or section name)
            search_term = content or section
            if search_term:
                forgotten_qdrant = await self._store.forget_semantic(search_term)

            self._store._schedule_reindex()
            parts = []
            if section:
                parts.append(f"Removed section '{section}' from MEMORY.md")
            if forgotten_qdrant:
                parts.append(f"Marked {forgotten_qdrant} entries as forgotten in Qdrant")
            result = ". ".join(parts) or "Nothing to forget."

            logger.info(
                "Memory forgotten: section=%s content=%s qdrant=%d",
                section,
                content[:50],
                forgotten_qdrant,
            )
            return ToolResult(output=result)
        except Exception as e:
            logger.error("Failed to forget memory: %s", e)
            return ToolResult(
                output=f"Failed to forget: {e}",
                error=str(e),
                success=False,
            )

    async def _handle_correct(self, section: str, content: str) -> ToolResult:
        if not section or not section.strip():
            return ToolResult(
                output="No section specified. Provide the section name to correct.",
                success=False,
            )
        if not content or not content.strip():
            return ToolResult(
                output="No content provided. Provide the corrected information.",
                success=False,
            )
        section = section.strip()
        content = content.strip()

        try:
            # 1. Update flat file
            memory = self._store.read_memory()
            lines = memory.split("\n")
            new_lines = []
            replaced = False
            skip = False

            for line in lines:
                if line.startswith("## "):
                    heading = line[3:].strip()
                    if heading.lower() == section.lower():
                        new_lines.append(f"## {section}")
                        new_lines.append(content)
                        new_lines.append("")
                        skip = True
                        replaced = True
                        continue
                    else:
                        skip = False
                if not skip:
                    new_lines.append(line)

            if not replaced:
                new_lines.append(f"\n## {section}")
                new_lines.append(content)
                new_lines.append("")

            new_content = "\n".join(new_lines).strip() + "\n"
            self._store.update_memory(new_content)

            # 2. Forget old entries in Qdrant and re-index
            await self._store.forget_semantic(section)
            self._store._schedule_reindex()

            logger.info("Memory corrected: [%s] %s", section, content[:80])
            action = "Corrected" if replaced else "Created"
            return ToolResult(output=f"{action} memory section '{section}': {content}")
        except Exception as e:
            logger.error("Failed to correct memory: %s", e)
            return ToolResult(
                output=f"Failed to correct memory: {e}",
                error=str(e),
                success=False,
            )

    async def _handle_strengthen(self, content: str) -> ToolResult:
        """Strengthen memories matching the content (user confirms they were useful)."""
        if not content or not content.strip():
            return ToolResult(
                output="No content provided. Describe the memory to strengthen.",
                success=False,
            )
        content = content.strip()

        try:
            count = await self._store.strengthen_memory(content)
            if count > 0:
                logger.info("Strengthened %d memories matching: %s", count, content[:80])
                return ToolResult(
                    output=f"Strengthened {count} memory(s) matching '{content[:100]}'. "
                    f"Their confidence has been boosted."
                )
            else:
                return ToolResult(
                    output=f"No matching memories found to strengthen for '{content[:100]}'."
                )
        except Exception as e:
            logger.error("Failed to strengthen memory: %s", e)
            return ToolResult(
                output=f"Failed to strengthen: {e}",
                error=str(e),
                success=False,
            )

    async def _handle_search(self, query: str, project: str = "") -> ToolResult:
        if not query or not query.strip():
            return ToolResult(
                output="No search query provided.",
                success=False,
            )
        query = query.strip()

        try:
            results = []
            store = self._get_store(project)

            # 1. Semantic search via Qdrant (finds by meaning, not keywords)
            # Uses lifecycle-aware scoring when available
            if self._store.semantic_available:
                semantic_hits = await self._store.semantic_search(query, top_k=5, project=project)
                for hit in semantic_hits:
                    score = hit.get("score", 0)
                    text = hit.get("text", hit.get("summary", ""))
                    source = hit.get("source", "memory")
                    confidence = hit.get("confidence")
                    recall_count = hit.get("recall_count")
                    # Build metadata string — always show lifecycle fields when present
                    meta_parts = [f"relevance={score:.2f}"]
                    if confidence is not None:
                        meta_parts.append(f"conf={confidence:.2f}")
                    if recall_count is not None:
                        meta_parts.append(f"recalls={recall_count}")
                    meta = " ".join(meta_parts)
                    if text:
                        results.append(f"[{source} {meta}] {text.strip()}")

            # 2. Keyword fallback — search project-scoped memory text
            memory = store.read_memory()
            for line in memory.splitlines():
                line_stripped = line.strip()
                if line_stripped and query.lower() in line_stripped.lower():
                    entry = f"[keyword] {line_stripped}"
                    if entry not in results:
                        results.append(entry)

            # 3. History keyword search (project-scoped)
            history_matches = store.search_history(query)
            for match in history_matches[:10]:
                results.append(f"[history] {match.strip()}")

            # Deduplicate near-identical results
            results = _deduplicate_results(results)

            if not results:
                return ToolResult(output=f"No results found for '{query}' in memory or history.")

            return ToolResult(
                output=f"Found {len(results)} result(s) for '{query}':\n\n"
                + "\n".join(results[:20])
            )
        except Exception as e:
            logger.error("Memory search failed: %s", e)
            return ToolResult(
                output=f"Search failed: {e}",
                error=str(e),
                success=False,
            )

    async def _handle_reindex_cc(self) -> ToolResult:
        """Scan all CC memory files for all projects and sync missing ones to Qdrant."""
        import time
        import uuid
        from pathlib import Path

        from memory.embeddings import _find_onnx_model_dir, _OnnxEmbedder

        # Check prerequisites
        if not self._store or not self._store.semantic_available:
            return ToolResult(
                output="Qdrant is not available. Cannot reindex.",
                success=False,
            )

        model_dir = _find_onnx_model_dir()
        if not model_dir:
            return ToolResult(
                output="ONNX model not found. Cannot generate embeddings for reindex.",
                success=False,
            )

        try:
            embedder = _OnnxEmbedder(model_dir)
        except Exception as e:
            return ToolResult(
                output=f"Failed to load ONNX model: {e}",
                success=False,
            )

        # Scan all CC memory files
        cc_base = Path.home() / ".claude" / "projects"
        if not cc_base.exists():
            return ToolResult(
                output="No Claude Code projects directory found at ~/.claude/projects/"
            )

        memory_files = list(cc_base.glob("*/memory/*.md"))
        if not memory_files:
            return ToolResult(output="No Claude Code memory files found.")

        # UUID5 namespace (must match worker's make_point_id)
        namespace = uuid.UUID("a42a42a4-2a42-4a42-a42a-42a42a42a42a")
        qdrant = self._store._qdrant
        synced = 0
        skipped = 0
        errors = 0

        for mf in memory_files:
            try:
                content = mf.read_text(encoding="utf-8")
                if not content.strip():
                    skipped += 1
                    continue

                # Check if already in Qdrant (by deterministic point ID)
                point_id = str(uuid.uuid5(namespace, f"claude_code:{mf}"))

                # Try to retrieve the point — if it exists, skip
                try:
                    from qdrant_client.models import PointStruct

                    existing = qdrant._client.retrieve(
                        collection_name=f"{qdrant.config.collection_prefix}_memory",
                        ids=[point_id],
                    )
                    if existing:
                        skipped += 1
                        continue
                except Exception:
                    pass  # Collection may not exist yet — proceed with upsert

                # Embed and upsert
                vector = embedder.encode(content[:2000])
                payload = {
                    "source": "claude_code",
                    "file_path": str(mf),
                    "section": mf.stem,
                }
                full_payload = {"text": content, "timestamp": time.time(), **payload}
                try:
                    from qdrant_client.models import PointStruct
                except ImportError:
                    return ToolResult(
                        output="qdrant-client not installed. Cannot reindex.",
                        success=False,
                    )
                point = PointStruct(id=point_id, vector=vector, payload=full_payload)
                qdrant._ensure_collection("memory")
                col_name = f"{qdrant.config.collection_prefix}_memory"
                qdrant._client.upsert(collection_name=col_name, points=[point])
                synced += 1
            except Exception as e:
                logger.warning("reindex_cc: failed to sync %s: %s", mf, e)
                errors += 1

        result_parts = [
            f"Scanned {len(memory_files)} CC memory file(s).",
            f"Newly synced: {synced}",
            f"Already synced: {skipped}",
        ]
        if errors:
            result_parts.append(f"Errors: {errors}")

        return ToolResult(output="\n".join(result_parts))

    async def _handle_consolidate(self) -> ToolResult:
        """Trigger an on-demand memory consolidation pass (QUAL-01).

        Scans the Qdrant memory and knowledge collections for near-duplicate
        vectors (cosine similarity >= CONSOLIDATION_AUTO_THRESHOLD) and removes
        the lower-confidence duplicate.  Near-duplicates in the
        [CONSOLIDATION_FLAG_THRESHOLD, auto) range are counted but not deleted.
        """
        if not self._store or not self._store._qdrant or not self._store._qdrant.is_available:
            return ToolResult(
                output="Qdrant is not available. Consolidation requires Qdrant.",
                success=False,
            )
        try:
            import asyncio

            from memory.consolidation_worker import run_consolidation

            result = await asyncio.to_thread(run_consolidation, self._store._qdrant)
            if result.get("error"):
                return ToolResult(
                    output=f"Consolidation failed: {result['error']}",
                    success=False,
                )

            # Log the consolidation event to Qdrant history (non-critical)
            if self._store.semantic_available and result["removed"] > 0:
                try:
                    await self._store.log_event_semantic(
                        "consolidation",
                        f"Removed {result['removed']} duplicates from {', '.join(result.get('collections', []))}",
                    )
                except Exception:
                    pass

            return ToolResult(
                output=(
                    f"Consolidation complete: scanned {result['scanned']} entries, "
                    f"removed {result['removed']} duplicate(s), "
                    f"flagged {result['flagged']} near-duplicate(s)."
                )
            )
        except Exception as e:
            logger.error("Consolidation failed: %s", e)
            return ToolResult(output=f"Consolidation failed: {e}", success=False)
