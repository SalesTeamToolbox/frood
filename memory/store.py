"""
Two-layer persistent memory system.

Inspired by Nanobot's MEMORY.md + HISTORY.md pattern:
- MEMORY.md: Consolidated facts, preferences, and learnings (editable)
- HISTORY.md: Append-only chronological event log (grep-searchable)
"""

import logging
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("agent42.memory")


class MemoryStore:
    """Persistent two-layer memory for cross-task learning."""

    def __init__(self, workspace_dir: str | Path):
        self.workspace_dir = Path(workspace_dir)
        self.memory_path = self.workspace_dir / "MEMORY.md"
        self.history_path = self.workspace_dir / "HISTORY.md"
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

    def log_event(self, event_type: str, summary: str, details: str = ""):
        """Append an event to the history log."""
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        entry = f"### [{timestamp}] {event_type}\n{summary}\n"
        if details:
            entry += f"\n{details}\n"
        entry += "\n---\n\n"

        with open(self.history_path, "a", encoding="utf-8") as f:
            f.write(entry)

        logger.debug(f"History logged: {event_type} — {summary}")

    def search_history(self, query: str) -> list[str]:
        """Search history for entries matching a query (grep-like)."""
        history = self.read_history()
        results = []
        for line in history.split("\n"):
            if query.lower() in line.lower():
                results.append(line)
        return results

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
