"""
MemoryTool — explicit read/write access to the persistent memory system.

Without this tool the agent can *see* memory context injected into its prompt
but has no way to *write* new memories.  The memory skill describes the memory
system, but previously there was no corresponding tool — the agent would claim
"stored in MEMORY.md" without actually writing anything.

Operations:
  store   — persist a fact, preference, or learning to MEMORY.md
  recall  — read the current memory (optionally search by query)
  log     — append an event to HISTORY.md
  search  — search memory and history for a keyword/phrase
"""

import logging

from tools.base import Tool, ToolResult

logger = logging.getLogger("agent42.tools.memory")


class MemoryTool(Tool):
    """Read/write persistent memory (MEMORY.md + HISTORY.md).

    This tool gives the agent explicit access to the two-layer memory
    system so it can store user-requested information and recall it in
    later sessions.

    Requires ``memory_store`` from ToolContext injection.
    """

    requires = ["memory_store"]

    def __init__(self, memory_store=None, **kwargs):
        self._store = memory_store

    @property
    def name(self) -> str:
        return "memory"

    @property
    def description(self) -> str:
        return (
            "Read and write persistent memory. "
            "Use 'store' to save facts, preferences, or learnings to MEMORY.md. "
            "Use 'recall' to retrieve the current memory contents. "
            "Use 'log' to record an event in the chronological HISTORY.md. "
            "Use 'search' to find specific past information by keyword or phrase."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["store", "recall", "log", "search"],
                    "description": (
                        "store: save information to MEMORY.md under a section; "
                        "recall: read current memory contents; "
                        "log: append an event to HISTORY.md; "
                        "search: search memory and history by keyword"
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
            },
            "required": ["action"],
        }

    async def execute(
        self,
        action: str = "recall",
        section: str = "",
        content: str = "",
        event_type: str = "note",
        **kwargs,
    ) -> ToolResult:
        if not self._store:
            return ToolResult(
                output="Memory system is not initialized.",
                error="No memory store available.",
                success=False,
            )

        if action == "store":
            return self._handle_store(section, content)
        elif action == "recall":
            return self._handle_recall()
        elif action == "log":
            return self._handle_log(event_type, content)
        elif action == "search":
            return self._handle_search(content)
        else:
            return ToolResult(
                output=f"Unknown action: {action}. Use store, recall, log, or search.",
                success=False,
            )

    def _handle_store(self, section: str, content: str) -> ToolResult:
        if not content or not content.strip():
            return ToolResult(
                output="No content provided. Specify what to remember.",
                success=False,
            )
        section = section.strip() or "General"
        content = content.strip()

        try:
            self._store.append_to_section(section, content)
            logger.info("Memory stored: [%s] %s", section, content[:80])
            return ToolResult(output=f"Stored in memory under '{section}': {content}")
        except Exception as e:
            logger.error("Failed to store memory: %s", e)
            return ToolResult(
                output=f"Failed to store memory: {e}",
                error=str(e),
                success=False,
            )

    def _handle_recall(self) -> ToolResult:
        try:
            memory = self._store.read_memory()
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

    def _handle_log(self, event_type: str, content: str) -> ToolResult:
        if not content or not content.strip():
            return ToolResult(
                output="No content provided. Specify the event summary.",
                success=False,
            )
        event_type = event_type.strip() or "note"
        content = content.strip()

        try:
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

    def _handle_search(self, query: str) -> ToolResult:
        if not query or not query.strip():
            return ToolResult(
                output="No search query provided.",
                success=False,
            )
        query = query.strip()

        try:
            # Search both memory content and history
            results = []

            # Grep-search memory
            memory = self._store.read_memory()
            for line in memory.splitlines():
                if query.lower() in line.lower():
                    results.append(f"[memory] {line.strip()}")

            # Grep-search history
            history_matches = self._store.search_history(query)
            for match in history_matches[:10]:
                results.append(f"[history] {match.strip()}")

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
