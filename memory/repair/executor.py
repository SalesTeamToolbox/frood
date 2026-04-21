"""Apply RepairPlan operations against a harness's flat-file memory.

Dry-run by default. Every destructive op snapshots the affected files to
``<snapshot_dir>/<ts>/`` before mutating, and writes one audit-log line per
op to ``<audit_log>`` (JSONL).
"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import aiofiles

from memory.repair.adapters import HarnessAdapter
from memory.repair.models import (
    IndexEntry,
    IndexModel,
    RepairAuditRecord,
    RepairOp,
    RepairPlan,
)


class RepairExecutor:
    """Execute a RepairPlan with snapshot + audit log + dry-run support."""

    def __init__(
        self,
        adapter: HarnessAdapter,
        workspace: Path,
        snapshot_dir: Path,
        audit_log: Path,
        dry_run: bool = True,
    ) -> None:
        self._adapter = adapter
        self._workspace = workspace
        self._snapshot_root = snapshot_dir
        self._audit_log = audit_log
        self._dry_run = dry_run
        self._run_snapshot_dir: Path | None = None

    @property
    def snapshot_dir(self) -> Path | None:
        return self._run_snapshot_dir

    async def apply(self, plan: RepairPlan) -> tuple[int, int, int]:
        """Apply each op in the plan; return (applied, flagged, skipped) counts."""

        applied = 0
        flagged = 0
        skipped = 0

        index_cache: dict[Path, IndexModel] = {}

        for op in plan.ops:
            try:
                did_apply, did_flag = await self._apply_op(op, plan, index_cache)
            except _RepairSkip as exc:
                skipped += 1
                await self._write_audit(op, applied_flag=False, extra_rationale=str(exc))
                continue

            if did_apply:
                applied += 1
            elif did_flag:
                flagged += 1
            else:
                skipped += 1

        for index_path, index in index_cache.items():
            if self._dry_run:
                continue
            project_dir = index_path.parent
            await self._adapter.write_index(project_dir, index)

        return applied, flagged, skipped

    async def _apply_op(
        self,
        op: RepairOp,
        plan: RepairPlan,
        index_cache: dict[Path, IndexModel],
    ) -> tuple[bool, bool]:
        if op.decided_by == "llm":
            await self._write_audit(op, applied_flag=False)
            return False, True

        if op.kind == "repair_index_drop":
            return await self._apply_index_drop(op, plan, index_cache)
        if op.kind == "repair_index_add":
            return await self._apply_index_add(op, plan, index_cache)
        if op.kind == "delete_file":
            return await self._apply_delete_file(op)

        raise _RepairSkip(f"unsupported op kind in Phase 1: {op.kind}")

    async def _apply_index_drop(
        self,
        op: RepairOp,
        plan: RepairPlan,
        index_cache: dict[Path, IndexModel],
    ) -> tuple[bool, bool]:
        index = await self._load_index(op.target, plan.project_root, index_cache)
        entry_target = op.extra.get("entry_target", "")
        before_hash = _hash_bytes(_serialize_entries(index))
        index.remove_entry(entry_target)
        after_hash = _hash_bytes(_serialize_entries(index))

        if self._dry_run:
            await self._write_audit(
                op, applied_flag=False, before_hash=before_hash, after_hash=after_hash
            )
            return False, True

        await self._snapshot(op.target)
        await self._write_audit(
            op, applied_flag=True, before_hash=before_hash, after_hash=after_hash
        )
        return True, False

    async def _apply_index_add(
        self,
        op: RepairOp,
        plan: RepairPlan,
        index_cache: dict[Path, IndexModel],
    ) -> tuple[bool, bool]:
        index = await self._load_index(op.target, plan.project_root, index_cache)
        entry_target = op.extra.get("entry_target", "")
        entry_title = op.extra.get("entry_title", "")
        entry_description = op.extra.get("entry_description", "")

        if any(e.target == entry_target for e in index.entries):
            raise _RepairSkip(f"entry {entry_target!r} already in index")

        before_hash = _hash_bytes(_serialize_entries(index))
        index.add_entry(
            IndexEntry(
                title=entry_title,
                target=entry_target,
                description=entry_description,
            )
        )
        after_hash = _hash_bytes(_serialize_entries(index))

        if self._dry_run:
            await self._write_audit(
                op, applied_flag=False, before_hash=before_hash, after_hash=after_hash
            )
            return False, True

        await self._snapshot(op.target)
        await self._write_audit(
            op, applied_flag=True, before_hash=before_hash, after_hash=after_hash
        )
        return True, False

    async def _apply_delete_file(self, op: RepairOp) -> tuple[bool, bool]:
        if not op.target.exists():
            raise _RepairSkip(f"target {op.target} no longer exists")

        before_hash = await _file_sha256(op.target)

        if self._dry_run:
            await self._write_audit(op, applied_flag=False, before_hash=before_hash)
            return False, True

        await self._snapshot(op.target)
        op.target.unlink()
        await self._write_audit(op, applied_flag=True, before_hash=before_hash, after_hash=None)
        return True, False

    async def _load_index(
        self,
        index_path: Path,
        project_root: Path,
        cache: dict[Path, IndexModel],
    ) -> IndexModel:
        if index_path in cache:
            return cache[index_path]
        loaded = await self._adapter.read_index(project_root)
        if loaded is None:
            loaded = IndexModel(path=index_path, lines=[])
        cache[index_path] = loaded
        return loaded

    async def _snapshot(self, target: Path) -> None:
        if not target.exists():
            return
        if self._run_snapshot_dir is None:
            ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
            self._run_snapshot_dir = self._snapshot_root / ts
            self._run_snapshot_dir.mkdir(parents=True, exist_ok=True)
        try:
            rel = target.resolve().relative_to(Path.home().resolve())
            dest = self._run_snapshot_dir / rel
        except ValueError:
            dest = self._run_snapshot_dir / target.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, dest)

    async def _write_audit(
        self,
        op: RepairOp,
        applied_flag: bool,
        before_hash: str | None = None,
        after_hash: str | None = None,
        extra_rationale: str = "",
    ) -> None:
        record = RepairAuditRecord(
            ts=datetime.now(UTC),
            kind=op.kind,
            target=str(op.target),
            before_hash=before_hash,
            after_hash=after_hash,
            confidence=op.confidence,
            decided_by=op.decided_by,
            rationale=op.rationale + (f" | {extra_rationale}" if extra_rationale else ""),
            dry_run=self._dry_run,
            applied=applied_flag,
            snapshot_dir=str(self._run_snapshot_dir) if self._run_snapshot_dir else None,
        )
        self._audit_log.parent.mkdir(parents=True, exist_ok=True)
        line = record.model_dump_json() + "\n"
        async with aiofiles.open(self._audit_log, "a", encoding="utf-8") as f:
            await f.write(line)


class _RepairSkip(Exception):
    """Raised when an op should be skipped (not applied, not flagged)."""


def _serialize_entries(index: IndexModel) -> bytes:
    return json.dumps(
        [e.model_dump() for e in index.entries],
        sort_keys=True,
    ).encode("utf-8")


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


async def _file_sha256(path: Path) -> str:
    async with aiofiles.open(path, "rb") as f:
        data = await f.read()
    return hashlib.sha256(data).hexdigest()
