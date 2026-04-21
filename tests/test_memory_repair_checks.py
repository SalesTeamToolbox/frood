"""Tests for deterministic Phase 1 memory-repair checks."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from memory.repair.adapters import ClaudeCodeAdapter
from memory.repair.checks import (
    dangling_link_check,
    exact_duplicate_check,
    orphan_file_check,
    run_checks,
)
from memory.repair.models import IndexEntry, IndexModel


def _write(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")


def _memory_file(path: Path, name: str, description: str, body: str = "body") -> None:
    _write(
        path,
        f"---\nname: {name}\ndescription: {description}\ntype: project\n---\n\n{body}\n",
    )


class TestDanglingLinkCheck:
    def test_emits_drop_for_missing_target(self):
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            index = IndexModel.from_entries(
                project / "MEMORY.md",
                [IndexEntry(title="Gone", target="gone.md", description="x")],
            )
            ops = dangling_link_check("claude_code", project, index)
            assert len(ops) == 1
            assert ops[0].kind == "repair_index_drop"
            assert ops[0].extra["entry_target"] == "gone.md"
            assert ops[0].confidence == 1.0

    def test_no_ops_when_target_exists(self):
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            _memory_file(project / "kept.md", "kept", "k")
            index = IndexModel.from_entries(
                project / "MEMORY.md",
                [IndexEntry(title="Kept", target="kept.md", description="k")],
            )
            assert dangling_link_check("claude_code", project, index) == []

    def test_no_ops_when_index_missing(self):
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            assert dangling_link_check("claude_code", project, None) == []


class TestOrphanFileCheck:
    @pytest.mark.asyncio
    async def test_emits_add_for_unreferenced_file(self):
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            orphan = project / "orphan.md"
            _memory_file(orphan, "Orphan memory", "an orphan")
            index = IndexModel.from_entries(project / "MEMORY.md", [])
            ops = await orphan_file_check("claude_code", project, index, [orphan])
            assert len(ops) == 1
            assert ops[0].kind == "repair_index_add"
            assert ops[0].extra["entry_target"] == "orphan.md"
            assert ops[0].extra["entry_title"] == "Orphan memory"
            assert ops[0].extra["entry_description"] == "an orphan"

    @pytest.mark.asyncio
    async def test_skips_inline_prose_mention(self):
        """File mentioned in MEMORY.md prose (not as a link) must not be flagged.

        Reproduces the synergicdealerportal false positive: MEMORY.md said
        ``See `feedback_ssh_skill.md` `` in prose but our link-only regex
        flagged the file as orphan every run.
        """
        from memory.repair.adapters import _parse_index

        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            f = project / "feedback_ssh_skill.md"
            _memory_file(f, "SSH skill", "s")
            raw = (
                "# Project memory\n\n"
                "## Access\n\n"
                "- All agents MUST use the `synergic-ssh` skill. "
                "See `feedback_ssh_skill.md` for details.\n"
            )
            index = _parse_index(project / "MEMORY.md", raw)
            assert await orphan_file_check("claude_code", project, index, [f]) == []

    @pytest.mark.asyncio
    async def test_no_ops_when_file_already_indexed(self):
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            f = project / "known.md"
            _memory_file(f, "Known", "k")
            index = IndexModel.from_entries(
                project / "MEMORY.md",
                [IndexEntry(title="Known", target="known.md", description="k")],
            )
            assert await orphan_file_check("claude_code", project, index, [f]) == []


class TestExactDuplicateCheck:
    @pytest.mark.asyncio
    async def test_detects_exact_duplicate_keeps_older(self):
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            older = project / "a.md"
            newer = project / "b.md"
            body = "---\nname: A\n---\n\nshared body text\n"
            _write(older, body)
            _write(newer, body)
            # Force distinct mtimes: older first
            import os

            os.utime(older, (1000, 1000))
            os.utime(newer, (2000, 2000))

            ops = await exact_duplicate_check("claude_code", [older, newer])
            assert len(ops) == 1
            assert ops[0].kind == "delete_file"
            assert ops[0].target == newer
            assert ops[0].extra["keeper"] == str(older)

    @pytest.mark.asyncio
    async def test_frontmatter_differences_still_dedupe(self):
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            a = project / "a.md"
            b = project / "b.md"
            _write(a, "---\nname: A\n---\n\nexact same body\n")
            _write(b, "---\nname: B different\n---\n\nexact same body\n")
            import os

            os.utime(a, (1000, 1000))
            os.utime(b, (2000, 2000))
            ops = await exact_duplicate_check("claude_code", [a, b])
            assert len(ops) == 1
            assert ops[0].target == b

    @pytest.mark.asyncio
    async def test_no_ops_when_bodies_differ(self):
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            a = project / "a.md"
            b = project / "b.md"
            _write(a, "alpha body")
            _write(b, "bravo body")
            assert await exact_duplicate_check("claude_code", [a, b]) == []


class TestRunChecks:
    @pytest.mark.asyncio
    async def test_combines_all_three_checks(self):
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            orphan = project / "orphan.md"
            dup_a = project / "dupa.md"
            dup_b = project / "dupb.md"
            _memory_file(orphan, "orphan", "o")
            dup_body = "same body sha"
            _write(dup_a, dup_body)
            _write(dup_b, dup_body)
            import os

            os.utime(dup_a, (1000, 1000))
            os.utime(dup_b, (2000, 2000))

            index = IndexModel.from_entries(
                project / "MEMORY.md",
                [IndexEntry(title="Missing", target="missing.md", description="m")],
            )
            adapter = ClaudeCodeAdapter()
            ops = await run_checks(adapter, project, index, [orphan, dup_a, dup_b])
            kinds = sorted(op.kind for op in ops)
            assert "repair_index_drop" in kinds
            assert "repair_index_add" in kinds
            assert "delete_file" in kinds
