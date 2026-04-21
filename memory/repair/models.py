"""Pydantic models for the memory repair pipeline."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

RepairKind = Literal[
    "repair_index_drop",
    "repair_index_add",
    "delete_file",
    "mark_superseded",
    "merge",
    "strengthen",
    "correct",
]

DecidedBy = Literal["deterministic", "llm"]


class IndexEntry(BaseModel):
    """A single entry in a harness MEMORY.md index file."""

    target: str
    title: str = ""
    description: str = ""
    raw: str = ""


class IndexLine(BaseModel):
    """A single line of the MEMORY.md index, optionally carrying an entry.

    Every line of the source file is preserved verbatim so non-link content
    (section headings, standalone bullets, prose notes) round-trips cleanly.
    """

    text: str = ""
    entry: IndexEntry | None = None


class IndexModel(BaseModel):
    """Parsed representation of a harness MEMORY.md index.

    Internally line-preserving — the serializer emits every stored line in
    order, so non-entry text (section headers, inline bullets, prose) is not
    lost by a parse/serialize round-trip.
    """

    path: Path
    lines: list[IndexLine] = Field(default_factory=list)

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @property
    def entries(self) -> list[IndexEntry]:
        return [ln.entry for ln in self.lines if ln.entry is not None]

    def remove_entry(self, target: str) -> bool:
        """Drop the first line whose entry matches ``target``. Returns True if removed."""
        for i, ln in enumerate(self.lines):
            if ln.entry is not None and ln.entry.target == target:
                del self.lines[i]
                return True
        return False

    def add_entry(self, entry: IndexEntry) -> None:
        """Append a new entry line to the end of the index."""
        suffix = f" — {entry.description}" if entry.description else ""
        text = entry.raw or f"- [{entry.title}]({entry.target}){suffix}"
        self.lines.append(IndexLine(text=text, entry=entry))

    @classmethod
    def from_entries(cls, path: Path, entries: list[IndexEntry], preamble: str = "") -> IndexModel:
        """Build a minimal IndexModel from a flat list of entries (test helper)."""
        lines: list[IndexLine] = []
        if preamble:
            for chunk in preamble.rstrip().splitlines():
                lines.append(IndexLine(text=chunk))
        for entry in entries:
            suffix = f" — {entry.description}" if entry.description else ""
            text = entry.raw or f"- [{entry.title}]({entry.target}){suffix}"
            lines.append(IndexLine(text=text, entry=entry))
        return cls(path=path, lines=lines)


class RepairOp(BaseModel):
    """A single repair operation proposed by a check."""

    kind: RepairKind
    target: Path
    rationale: str
    confidence: float = Field(ge=0.0, le=1.0)
    decided_by: DecidedBy = "deterministic"
    harness: str = "claude_code"
    extra: dict = Field(default_factory=dict)

    model_config = ConfigDict(arbitrary_types_allowed=True)


class RepairPlan(BaseModel):
    """Collection of repair operations for one harness/project pair."""

    harness: str
    project_root: Path
    ops: list[RepairOp] = Field(default_factory=list)

    model_config = ConfigDict(arbitrary_types_allowed=True)


class LLMJudgment(BaseModel):
    """Structured output from an LLM-judged repair decision.

    Produced by memory.repair.llm_judge. Always treated as flag-for-review —
    the executor never auto-applies LLM-originated ops in Phase 1-3.
    """

    verdict: Literal["supersede", "merge", "none"] = "none"
    rationale: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    keeper_target: str = ""  # filename of the survivor (for supersede/merge)
    provider: str = ""  # which LLM provider returned the judgment


class RepairAuditRecord(BaseModel):
    """One line in the repair audit log."""

    ts: datetime
    kind: RepairKind
    target: str
    before_hash: str | None = None
    after_hash: str | None = None
    confidence: float
    decided_by: DecidedBy
    rationale: str
    dry_run: bool
    applied: bool
    snapshot_dir: str | None = None


class RepairResult(BaseModel):
    """Outcome of a run_repair() invocation."""

    harness: str
    dry_run: bool
    started_at: datetime
    finished_at: datetime
    plans_scanned: int = 0
    ops_proposed: int = 0
    ops_applied: int = 0
    ops_flagged: int = 0
    ops_skipped: int = 0
    snapshot_dir: str | None = None
    error: str | None = None
