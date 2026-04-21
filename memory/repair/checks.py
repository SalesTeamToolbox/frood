"""Deterministic repair checks for Phase 1.

Each check inspects a (harness, project) pair and returns a list of RepairOp
proposals. No LLM calls here — that's Phase 2.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import aiofiles

from memory.repair.adapters import HarnessAdapter
from memory.repair.models import IndexModel, RepairOp

_FRONTMATTER_RE = re.compile(r"^---\n.*?\n---\n", re.DOTALL)
_INLINE_FILENAME_RE = re.compile(r"[A-Za-z0-9_\-\.]+\.md")


def _extract_filename_mentions(text: str) -> set[str]:
    """Return every ``*.md`` filename token appearing anywhere in ``text``.

    Catches inline prose references like ``See `foo.md` `` or ``per foo.md`` that
    a link-only regex would miss.
    """
    return set(_INLINE_FILENAME_RE.findall(text))


async def _read_body(path: Path) -> str:
    async with aiofiles.open(path, encoding="utf-8") as f:
        return await f.read()


def _strip_frontmatter(text: str) -> str:
    return _FRONTMATTER_RE.sub("", text, count=1)


def _normalized_hash(text: str) -> str:
    normalized = re.sub(r"\s+", " ", _strip_frontmatter(text)).strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _parse_frontmatter(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return result
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" in line:
            key, _, value = line.partition(":")
            result[key.strip()] = value.strip()
    return result


async def run_checks(
    adapter: HarnessAdapter,
    project: Path,
    index: IndexModel | None,
    files: list[Path],
) -> list[RepairOp]:
    """Run all Phase 1 checks against one project and return proposed ops."""

    ops: list[RepairOp] = []
    ops.extend(dangling_link_check(adapter.harness_name, project, index))
    ops.extend(await orphan_file_check(adapter.harness_name, project, index, files))
    ops.extend(await exact_duplicate_check(adapter.harness_name, files))
    return ops


def dangling_link_check(
    harness: str,
    project: Path,
    index: IndexModel | None,
) -> list[RepairOp]:
    """Emit repair_index_drop for every index entry whose target file is missing."""

    if index is None:
        return []
    ops: list[RepairOp] = []
    for entry in index.entries:
        target_path = (project / entry.target).resolve()
        if not target_path.exists():
            ops.append(
                RepairOp(
                    kind="repair_index_drop",
                    target=index.path,
                    rationale=(
                        f"MEMORY.md points to {entry.target!r} but that file "
                        "does not exist on disk."
                    ),
                    confidence=1.0,
                    harness=harness,
                    extra={"entry_target": entry.target, "entry_title": entry.title},
                )
            )
    return ops


async def orphan_file_check(
    harness: str,
    project: Path,
    index: IndexModel | None,
    files: list[Path],
) -> list[RepairOp]:
    """Emit repair_index_add for every memory file not referenced by the index.

    "Referenced" means the filename appears anywhere in MEMORY.md — either as a
    proper ``- [title](file.md)`` link entry OR in prose (e.g. ``see `file.md` ``).
    Inline prose mentions are treated as valid references so a second pass does
    not re-flag them every run.
    """

    indexed_targets: set[str] = set()
    mentioned_anywhere: set[str] = set()
    if index is not None:
        for entry in index.entries:
            indexed_targets.add(Path(entry.target).name)
            indexed_targets.add(entry.target)
        for ln in index.lines:
            for tok in _extract_filename_mentions(ln.text):
                mentioned_anywhere.add(tok)

    ops: list[RepairOp] = []
    for f in files:
        if f.name in indexed_targets or str(f.relative_to(project)) in indexed_targets:
            continue
        if f.name in mentioned_anywhere:
            continue
        body = await _read_body(f)
        fm = _parse_frontmatter(body)
        title = fm.get("name") or f.stem.replace("_", " ")
        description = fm.get("description", "")
        ops.append(
            RepairOp(
                kind="repair_index_add",
                target=(index.path if index is not None else project / "MEMORY.md"),
                rationale=(
                    f"Memory file {f.name!r} exists on disk but is not referenced by MEMORY.md."
                ),
                confidence=1.0,
                harness=harness,
                extra={
                    "entry_target": f.name,
                    "entry_title": title,
                    "entry_description": description,
                },
            )
        )
    return ops


async def exact_duplicate_check(
    harness: str,
    files: list[Path],
) -> list[RepairOp]:
    """Emit delete_file for each redundant copy of an exact-duplicate pair.

    "Exact duplicate" = identical sha256 of the body after stripping YAML
    frontmatter and collapsing whitespace. Ties broken by mtime: the older
    file is kept, newer duplicates are proposed for deletion (newer writes
    are more likely to be the auto-generated re-statement).
    """

    hash_map: dict[str, list[tuple[Path, float]]] = {}
    for f in files:
        body = await _read_body(f)
        digest = _normalized_hash(body)
        hash_map.setdefault(digest, []).append((f, f.stat().st_mtime))

    ops: list[RepairOp] = []
    for digest, group in hash_map.items():
        if len(group) < 2:
            continue
        group.sort(key=lambda pair: pair[1])  # oldest first
        keeper, _ = group[0]
        for dup, _ in group[1:]:
            ops.append(
                RepairOp(
                    kind="delete_file",
                    target=dup,
                    rationale=(
                        f"Normalized body of {dup.name!r} is byte-identical to "
                        f"{keeper.name!r} (sha256={digest[:12]}...). Keeping "
                        "the older file."
                    ),
                    confidence=1.0,
                    harness=harness,
                    extra={"keeper": str(keeper), "digest": digest},
                )
            )
    return ops
