"""Harness adapters for the memory repair pipeline.

Each adapter abstracts one agent harness's flat-file memory layout (Claude Code,
Codex, OpenCode, ...). Phase 1 ships only `ClaudeCodeAdapter`; the Protocol is
defined now so future adapters plug in without refactors.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Protocol

import aiofiles

from memory.repair.models import IndexEntry, IndexLine, IndexModel

# Matches the namespace used by .claude/hooks/cc-memory-sync-worker.py
# (SYNC-03). Keeping it identical guarantees that any flat-file write the
# repair agent performs will overwrite the same Qdrant point that the sync
# hook wrote originally.
_CC_UUID5_NAMESPACE = uuid.UUID("a42a42a4-2a42-4a42-a42a-42a42a42a42a")

_INDEX_LINK_RE = re.compile(r"-\s*\[([^\]]+)\]\(([^)]+)\)(?:\s+[—-]\s*(.*))?")


class HarnessAdapter(Protocol):
    """Discover and read flat-file memory for a specific agent harness."""

    harness_name: str

    async def list_projects(self) -> list[Path]:
        """Return the list of per-project memory directories on disk."""
        ...

    async def list_memory_files(self, project: Path) -> list[Path]:
        """Return the non-index memory files for one project."""
        ...

    async def read_index(self, project: Path) -> IndexModel | None:
        """Parse the MEMORY.md index file for one project, or None if absent."""
        ...

    async def write_index(self, project: Path, index: IndexModel) -> None:
        """Serialize an IndexModel back to the project's MEMORY.md file."""
        ...

    def qdrant_point_id(self, file_path: Path) -> str:
        """Return the Qdrant point ID the sync hook would use for this file."""
        ...


class ClaudeCodeAdapter:
    """Adapter for the Claude Code flat-file memory system.

    Memory lives under ``~/.claude/projects/<slug>/memory/`` with ``MEMORY.md``
    as the index and one ``*.md`` file per memory entry.
    """

    harness_name = "claude_code"

    def __init__(self, home: Path | None = None) -> None:
        self._home = home or Path.home()

    @property
    def root(self) -> Path:
        return self._home / ".claude" / "projects"

    async def list_projects(self) -> list[Path]:
        if not self.root.exists():
            return []
        return sorted(p / "memory" for p in self.root.iterdir() if (p / "memory").is_dir())

    async def list_memory_files(self, project: Path) -> list[Path]:
        if not project.exists():
            return []
        return sorted(p for p in project.glob("*.md") if p.name != "MEMORY.md")

    async def read_index(self, project: Path) -> IndexModel | None:
        index_path = project / "MEMORY.md"
        if not index_path.exists():
            return None
        async with aiofiles.open(index_path, encoding="utf-8") as f:
            raw = await f.read()
        return _parse_index(index_path, raw)

    async def write_index(self, project: Path, index: IndexModel) -> None:
        index_path = project / "MEMORY.md"
        body = _serialize_index(index)
        index_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(index_path, "w", encoding="utf-8") as f:
            await f.write(body)

    def qdrant_point_id(self, file_path: Path) -> str:
        content = f"claude_code:{file_path}"
        return str(uuid.uuid5(_CC_UUID5_NAMESPACE, content))


def _parse_index(path: Path, raw: str) -> IndexModel:
    """Parse MEMORY.md line by line, tagging each link line with an IndexEntry.

    Non-link lines (headings, prose, inline bullets) are preserved verbatim so a
    round-trip parse/serialize leaves the file byte-equivalent (modulo trailing
    newline normalization).
    """
    lines: list[IndexLine] = []
    for raw_line in raw.splitlines():
        m = _INDEX_LINK_RE.match(raw_line.strip())
        if m:
            entry = IndexEntry(
                title=m.group(1).strip(),
                target=m.group(2).strip(),
                description=(m.group(3) or "").strip(),
                raw=raw_line,
            )
            lines.append(IndexLine(text=raw_line, entry=entry))
        else:
            lines.append(IndexLine(text=raw_line))
    # Preserve the original file's trailing-newline semantics — if the source
    # had a terminal newline, store it as an empty trailing line.
    if raw.endswith("\n"):
        lines.append(IndexLine(text=""))
    return IndexModel(path=path, lines=lines)


def _serialize_index(index: IndexModel) -> str:
    return "\n".join(ln.text for ln in index.lines)
