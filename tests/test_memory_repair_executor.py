"""Tests for RepairExecutor — dry-run, apply, snapshot, audit log."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from memory.repair.adapters import ClaudeCodeAdapter
from memory.repair.executor import RepairExecutor
from memory.repair.models import IndexEntry, RepairOp, RepairPlan


def _seed_project(home: Path, slug: str = "proj") -> Path:
    mem = home / ".claude" / "projects" / slug / "memory"
    mem.mkdir(parents=True)
    return mem


def _index_entry(title: str, target: str) -> IndexEntry:
    return IndexEntry(title=title, target=target, description=title.lower())


class TestDryRun:
    @pytest.mark.asyncio
    async def test_dry_run_does_not_mutate_files(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            mem = _seed_project(home)
            duplicate = mem / "dup.md"
            duplicate.write_text("will not be deleted in dry run")

            adapter = ClaudeCodeAdapter(home=home)
            snapshot_dir = home / "snaps"
            audit = home / "audit.jsonl"
            executor = RepairExecutor(
                adapter=adapter,
                workspace=home,
                snapshot_dir=snapshot_dir,
                audit_log=audit,
                dry_run=True,
            )
            plan = RepairPlan(
                harness="claude_code",
                project_root=mem,
                ops=[
                    RepairOp(
                        kind="delete_file",
                        target=duplicate,
                        rationale="dup",
                        confidence=1.0,
                    )
                ],
            )
            applied, flagged, skipped = await executor.apply(plan)
            assert applied == 0
            assert flagged == 1
            assert duplicate.exists()
            # Audit log still written
            assert audit.exists()
            lines = audit.read_text().strip().splitlines()
            assert len(lines) == 1
            record = json.loads(lines[0])
            assert record["dry_run"] is True
            assert record["applied"] is False


class TestApply:
    @pytest.mark.asyncio
    async def test_apply_deletes_file_and_snapshots_it(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            mem = _seed_project(home)
            duplicate = mem / "dup.md"
            duplicate.write_text("delete me")

            adapter = ClaudeCodeAdapter(home=home)
            snapshot_dir = home / "snaps"
            audit = home / "audit.jsonl"
            executor = RepairExecutor(
                adapter=adapter,
                workspace=home,
                snapshot_dir=snapshot_dir,
                audit_log=audit,
                dry_run=False,
            )
            plan = RepairPlan(
                harness="claude_code",
                project_root=mem,
                ops=[
                    RepairOp(
                        kind="delete_file",
                        target=duplicate,
                        rationale="dup",
                        confidence=1.0,
                    )
                ],
            )
            applied, flagged, skipped = await executor.apply(plan)
            assert applied == 1
            assert flagged == 0
            assert not duplicate.exists()
            # Snapshot dir has the file
            snapshots = list(snapshot_dir.rglob("dup.md"))
            assert snapshots, "expected snapshot of deleted file"
            assert snapshots[0].read_text() == "delete me"

    @pytest.mark.asyncio
    async def test_apply_index_drop_removes_entry(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            mem = _seed_project(home)
            index_path = mem / "MEMORY.md"
            index_path.write_text(
                "- [Alpha](a.md) — first\n- [Bravo](b.md) — second\n",
                encoding="utf-8",
            )
            (mem / "b.md").write_text("b body")  # only b exists

            adapter = ClaudeCodeAdapter(home=home)
            executor = RepairExecutor(
                adapter=adapter,
                workspace=home,
                snapshot_dir=home / "snaps",
                audit_log=home / "audit.jsonl",
                dry_run=False,
            )
            plan = RepairPlan(
                harness="claude_code",
                project_root=mem,
                ops=[
                    RepairOp(
                        kind="repair_index_drop",
                        target=index_path,
                        rationale="dangling",
                        confidence=1.0,
                        extra={"entry_target": "a.md", "entry_title": "Alpha"},
                    )
                ],
            )
            applied, flagged, skipped = await executor.apply(plan)
            assert applied == 1
            text = index_path.read_text()
            assert "a.md" not in text
            assert "b.md" in text

    @pytest.mark.asyncio
    async def test_apply_index_add_inserts_entry(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            mem = _seed_project(home)
            index_path = mem / "MEMORY.md"
            index_path.write_text("- [A](a.md) — a\n", encoding="utf-8")
            (mem / "a.md").write_text("a")
            (mem / "orphan.md").write_text("o")

            adapter = ClaudeCodeAdapter(home=home)
            executor = RepairExecutor(
                adapter=adapter,
                workspace=home,
                snapshot_dir=home / "snaps",
                audit_log=home / "audit.jsonl",
                dry_run=False,
            )
            plan = RepairPlan(
                harness="claude_code",
                project_root=mem,
                ops=[
                    RepairOp(
                        kind="repair_index_add",
                        target=index_path,
                        rationale="orphan",
                        confidence=1.0,
                        extra={
                            "entry_target": "orphan.md",
                            "entry_title": "Orphan memory",
                            "entry_description": "discovered on disk",
                        },
                    )
                ],
            )
            applied, flagged, skipped = await executor.apply(plan)
            assert applied == 1
            text = index_path.read_text()
            assert "orphan.md" in text
            assert "Orphan memory" in text


class TestLLMFlagging:
    @pytest.mark.asyncio
    async def test_llm_op_always_flagged_never_applied(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            mem = _seed_project(home)
            f = mem / "x.md"
            f.write_text("x")

            adapter = ClaudeCodeAdapter(home=home)
            executor = RepairExecutor(
                adapter=adapter,
                workspace=home,
                snapshot_dir=home / "snaps",
                audit_log=home / "audit.jsonl",
                dry_run=False,  # even with apply enabled
            )
            plan = RepairPlan(
                harness="claude_code",
                project_root=mem,
                ops=[
                    RepairOp(
                        kind="delete_file",
                        target=f,
                        rationale="llm thinks so",
                        confidence=1.0,
                        decided_by="llm",
                    )
                ],
            )
            applied, flagged, skipped = await executor.apply(plan)
            assert applied == 0
            assert flagged == 1
            assert f.exists()
