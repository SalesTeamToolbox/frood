"""Tests for ClaudeCodeAdapter — file discovery, UUID5 parity, index I/O."""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest

from memory.repair.adapters import ClaudeCodeAdapter
from memory.repair.models import IndexEntry, IndexModel


def _layout(home: Path, project_slug: str = "c--Users-example") -> Path:
    project = home / ".claude" / "projects" / project_slug / "memory"
    project.mkdir(parents=True)
    return project


class TestListing:
    @pytest.mark.asyncio
    async def test_list_projects_finds_memory_dirs(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            mem = _layout(home, "proj-a")
            _layout(home, "proj-b")
            # a project without memory/ dir should be skipped
            no_mem = home / ".claude" / "projects" / "no-mem"
            no_mem.mkdir()

            adapter = ClaudeCodeAdapter(home=home)
            projects = await adapter.list_projects()
            assert len(projects) == 2
            assert mem in projects

    @pytest.mark.asyncio
    async def test_list_memory_files_excludes_index(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            mem = _layout(home)
            (mem / "MEMORY.md").write_text("- [x](x.md)\n")
            (mem / "a.md").write_text("a")
            (mem / "b.md").write_text("b")
            adapter = ClaudeCodeAdapter(home=home)
            files = await adapter.list_memory_files(mem)
            names = sorted(f.name for f in files)
            assert names == ["a.md", "b.md"]


class TestUUID5Parity:
    def test_matches_cc_memory_sync_worker_exactly(self):
        """The adapter MUST use the same namespace+content format as the sync hook.

        If these drift, repair-written memory files would upsert to a different
        Qdrant point than the sync hook produced, breaking idempotent overwrite.
        """
        import sys

        hook_path = Path(__file__).resolve().parent.parent / ".claude" / "hooks"
        sys.path.insert(0, str(hook_path))
        try:
            import importlib.util

            spec = importlib.util.spec_from_file_location(
                "cc_sync_worker",
                str(hook_path / "cc-memory-sync-worker.py"),
            )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)  # type: ignore[union-attr]
        finally:
            sys.path.remove(str(hook_path))

        sample_path = Path("/tmp/.claude/projects/c--foo/memory/bar.md")
        adapter = ClaudeCodeAdapter()
        # The hook receives the argv string form; the adapter receives a Path.
        # Both must agree on str(Path) (which picks OS-native separators).
        assert adapter.qdrant_point_id(sample_path) == mod.make_point_id(str(sample_path))

    def test_deterministic(self):
        adapter = ClaudeCodeAdapter()
        p = Path("/tmp/.claude/projects/x/memory/y.md")
        assert adapter.qdrant_point_id(p) == adapter.qdrant_point_id(p)
        # Must be a valid UUID
        uuid.UUID(adapter.qdrant_point_id(p))


class TestIndexIO:
    @pytest.mark.asyncio
    async def test_roundtrip_preserves_entries(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            mem = _layout(home)
            (mem / "MEMORY.md").write_text(
                "# Project memory\n\n"
                "- [Alpha](a.md) — first memory\n"
                "- [Bravo](b.md) — second memory\n",
                encoding="utf-8",
            )
            adapter = ClaudeCodeAdapter(home=home)
            index = await adapter.read_index(mem)
            assert index is not None
            assert len(index.entries) == 2
            assert index.entries[0].target == "a.md"
            assert index.entries[0].title == "Alpha"
            assert index.entries[0].description == "first memory"

            await adapter.write_index(mem, index)
            text = (mem / "MEMORY.md").read_text(encoding="utf-8")
            assert "a.md" in text and "b.md" in text

    @pytest.mark.asyncio
    async def test_read_index_missing_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            mem = _layout(home)
            adapter = ClaudeCodeAdapter(home=home)
            assert await adapter.read_index(mem) is None

    @pytest.mark.asyncio
    async def test_roundtrip_preserves_non_link_sections(self):
        """Regression: MEMORY.md with section headings + inline bullets must round-trip.

        Reproduces the data-loss bug found during the agent42 migration where
        serializer dropped everything that wasn't a `- [title](target)` link.
        """
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            mem = _layout(home)
            original = (
                "# Project memory\n"
                "\n"
                "## User Preferences\n"
                "\n"
                "- **Deploy workflow**: commit -> push -> deploy\n"
                "\n"
                "## Architecture\n"
                "\n"
                "- [Rebrand](rebrand.md) — was Agent42\n"
                "- **ONNX over PyTorch**: ~25MB not ~1GB\n"
                "\n"
                "## Gotchas\n"
                "\n"
                "- Windows CRLF breaks bash\n"
            )
            (mem / "MEMORY.md").write_text(original, encoding="utf-8")
            adapter = ClaudeCodeAdapter(home=home)
            idx = await adapter.read_index(mem)
            assert idx is not None
            await adapter.write_index(mem, idx)
            after = (mem / "MEMORY.md").read_text(encoding="utf-8")
            # Every section header and inline bullet must survive
            for substring in [
                "## User Preferences",
                "**Deploy workflow**: commit -> push -> deploy",
                "## Architecture",
                "**ONNX over PyTorch**: ~25MB not ~1GB",
                "## Gotchas",
                "Windows CRLF breaks bash",
                "[Rebrand](rebrand.md)",
            ]:
                assert substring in after, f"lost {substring!r} on round-trip"

    @pytest.mark.asyncio
    async def test_write_index_adds_new_entry(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            mem = _layout(home)
            adapter = ClaudeCodeAdapter(home=home)
            idx = IndexModel.from_entries(
                mem / "MEMORY.md",
                [IndexEntry(title="New", target="new.md", description="just added")],
            )
            await adapter.write_index(mem, idx)
            text = (mem / "MEMORY.md").read_text(encoding="utf-8")
            assert "[New](new.md)" in text
            assert "just added" in text
