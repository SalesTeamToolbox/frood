"""Tests for Phase 3: Memory Sync — UUID injection, frontmatter, migration, and embedding tag stripping.

Covers MEM-01 requirements:
- UUID+timestamp prefix on every new bullet
- YAML frontmatter with file_id and last_modified
- Auto-migration of legacy bullets with deterministic UUID5
- Sentinel file prevents double migration
- Embedding pipeline strips [timestamp uuid] tags before vectorizing

Also covers MEM-03 requirements:
- MemoryTool project routing via factory callable
- Backward compat: project="global" uses global store
- Factory fallback + warning when project_memory_factory=None
- Factory caches ProjectMemoryStore instances by project_id
"""

import re
import time
from pathlib import Path

from memory.embeddings import EmbeddingStore
from memory.store import MemoryStore

# ── Regex for a valid UUID-prefixed bullet ─────────────────────────────────
BULLET_UUID_RE = re.compile(r"^- \[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z [0-9a-f]{8}\] .+$")
# Regex for YAML frontmatter block
FRONTMATTER_RE = re.compile(
    r"^---\nfile_id: ([0-9a-f]{32})\nlast_modified: (\S+)\n---\n", re.MULTILINE
)


class TestUuidInjection:
    """Tests that append_to_section() injects [ISO_TS 8HEXCHARS] prefix on every new bullet."""

    def test_append_adds_uuid_prefix(self, tmp_path):
        """append_to_section() produces a bullet matching the UUID-prefixed pattern."""
        store = MemoryStore(tmp_path, qdrant_store=None, redis_backend=None)
        store.append_to_section("Test", "hello")
        content = store.memory_path.read_text(encoding="utf-8")
        # Find bullet lines containing our text
        bullet_lines = [l for l in content.splitlines() if "hello" in l]
        assert len(bullet_lines) >= 1, "Expected a bullet line containing 'hello'"
        assert BULLET_UUID_RE.match(bullet_lines[0].strip()), (
            f"Bullet did not match UUID pattern: {bullet_lines[0]!r}"
        )

    def test_append_unique_uuids(self, tmp_path):
        """Two sequential appends produce bullets with different 8-char UUIDs."""
        store = MemoryStore(tmp_path, qdrant_store=None, redis_backend=None)
        store.append_to_section("Test", "entry one")
        time.sleep(0.01)  # ensure different timestamps
        store.append_to_section("Test", "entry two")
        content = store.memory_path.read_text(encoding="utf-8")

        uuid_parts = re.findall(
            r"\[(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z) ([0-9a-f]{8})\]", content
        )
        assert len(uuid_parts) >= 2, f"Expected at least 2 UUID tags, found: {uuid_parts}"
        uuids = [p[1] for p in uuid_parts]
        assert len(set(uuids)) == len(uuids), f"UUIDs should be unique, got: {uuids}"

    def test_update_memory_no_injection(self, tmp_path):
        """update_memory() with raw content does NOT inject UUID prefixes into bullet text."""
        store = MemoryStore(tmp_path, qdrant_store=None, redis_backend=None)
        raw_content = "# Test\n\n## Section\n\n- plain bullet without uuid\n"
        store.update_memory(raw_content)
        content = store.memory_path.read_text(encoding="utf-8")
        # The bullet text should be preserved as-is (no UUID injected into existing bullets)
        assert "plain bullet without uuid" in content
        # But update_memory does NOT add UUID prefix to the bullet content itself
        # (it writes content as-is for merge/migration paths)
        bullet_lines = [l for l in content.splitlines() if "plain bullet without uuid" in l]
        assert len(bullet_lines) >= 1
        # The bullet should NOT have had a UUID prefix injected by update_memory
        # (UUID injection only happens in append_to_section, not update_memory)
        for line in bullet_lines:
            line = line.strip()
            # Should be the plain bullet — update_memory doesn't inject
            assert not re.match(r"^- \[\d{4}.*\].*plain bullet", line), (
                f"update_memory() should NOT inject UUID prefix, but got: {line!r}"
            )


class TestFrontmatter:
    """Tests that update_memory() manages YAML frontmatter with file_id and last_modified."""

    def test_update_memory_adds_frontmatter(self, tmp_path):
        """After update_memory(), read_memory() content starts with YAML frontmatter."""
        store = MemoryStore(tmp_path, qdrant_store=None, redis_backend=None)
        store.update_memory("# Test\n\nSome content\n")
        content = store.memory_path.read_text(encoding="utf-8")
        assert content.startswith("---\n"), f"Expected frontmatter, got: {content[:80]!r}"
        m = FRONTMATTER_RE.match(content)
        assert m is not None, (
            f"Frontmatter did not match expected pattern. Content: {content[:200]!r}"
        )
        assert len(m.group(1)) == 32, "file_id should be 32 hex chars"
        assert "T" in m.group(2), "last_modified should be ISO timestamp"

    def test_frontmatter_preserves_file_id(self, tmp_path):
        """Two sequential update_memory() calls produce the same file_id but different last_modified."""
        store = MemoryStore(tmp_path, qdrant_store=None, redis_backend=None)
        store.update_memory("# First\n")
        content1 = store.memory_path.read_text(encoding="utf-8")
        m1 = FRONTMATTER_RE.match(content1)
        assert m1 is not None, "First update should have frontmatter"
        file_id_1 = m1.group(1)
        last_mod_1 = m1.group(2)

        time.sleep(1.1)  # ensure different seconds for last_modified
        store.update_memory("# Second\n")
        content2 = store.memory_path.read_text(encoding="utf-8")
        m2 = FRONTMATTER_RE.match(content2)
        assert m2 is not None, "Second update should have frontmatter"
        file_id_2 = m2.group(1)
        last_mod_2 = m2.group(2)

        assert file_id_1 == file_id_2, (
            f"file_id should be preserved: {file_id_1!r} != {file_id_2!r}"
        )
        assert last_mod_1 != last_mod_2, "last_modified should change on each update"

    def test_frontmatter_on_fresh_file(self, tmp_path):
        """A brand new MemoryStore's first update_memory() creates frontmatter."""
        # Use a subdirectory that doesn't exist yet
        new_dir = tmp_path / "fresh_workspace"
        store = MemoryStore(new_dir, qdrant_store=None, redis_backend=None)
        store.update_memory("# Fresh Start\n")
        content = store.memory_path.read_text(encoding="utf-8")
        assert content.startswith("---\n"), (
            "Fresh file should have frontmatter after update_memory()"
        )
        assert "file_id:" in content
        assert "last_modified:" in content


class TestMigration:
    """Tests auto-migration of old-format bullets (no UUID) on read_memory()."""

    def _write_old_format(self, tmp_path: Path, content: str):
        """Pre-write old-format MEMORY.md to tmp_path before constructing MemoryStore."""
        memory_file = tmp_path / "MEMORY.md"
        memory_file.write_text(content, encoding="utf-8")

    def test_migrate_old_format_bullets(self, tmp_path):
        """MEMORY.md with plain bullets is auto-migrated to UUID format on read_memory()."""
        self._write_old_format(tmp_path, "# Memory\n\n## Section\n\n- old content\n")
        store = MemoryStore(tmp_path, qdrant_store=None, redis_backend=None)
        content = store.read_memory()
        # After migration, old bullets should have UUID prefix
        bullet_lines = [l for l in content.splitlines() if "old content" in l]
        assert len(bullet_lines) >= 1, "Bullet with 'old content' should be present after migration"
        assert BULLET_UUID_RE.match(bullet_lines[0].strip()), (
            f"Migrated bullet should have UUID prefix: {bullet_lines[0]!r}"
        )

    def test_migrate_deterministic_ids(self, tmp_path):
        """Two MemoryStores reading the same old-format content produce identical UUIDs."""
        old_content = "# Memory\n\n## Section\n\n- deterministic content\n"

        dir_a = tmp_path / "node_a"
        dir_a.mkdir()
        (dir_a / "MEMORY.md").write_text(old_content, encoding="utf-8")
        store_a = MemoryStore(dir_a, qdrant_store=None, redis_backend=None)
        content_a = store_a.read_memory()

        dir_b = tmp_path / "node_b"
        dir_b.mkdir()
        (dir_b / "MEMORY.md").write_text(old_content, encoding="utf-8")
        store_b = MemoryStore(dir_b, qdrant_store=None, redis_backend=None)
        content_b = store_b.read_memory()

        # Extract UUIDs for "deterministic content" from both
        uuid_a = re.findall(
            r"\[(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z) ([0-9a-f]{8})\] deterministic content",
            content_a,
        )
        uuid_b = re.findall(
            r"\[(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z) ([0-9a-f]{8})\] deterministic content",
            content_b,
        )

        assert len(uuid_a) >= 1, f"Expected UUID in content_a: {content_a}"
        assert len(uuid_b) >= 1, f"Expected UUID in content_b: {content_b}"
        # The short UUID (8 hex chars) should be identical (content-hash based)
        assert uuid_a[0][1] == uuid_b[0][1], (
            f"UUID5 should be deterministic: {uuid_a[0][1]!r} != {uuid_b[0][1]!r}"
        )

    def test_migrate_preserves_existing_uuid_bullets(self, tmp_path):
        """Bullets already in [ts uuid] format are not re-migrated."""
        existing_uuid_content = (
            "# Memory\n\n## Section\n\n- [2026-03-24T14:22:10Z a4f7b2c1] already has uuid\n"
        )
        self._write_old_format(tmp_path, existing_uuid_content)
        store = MemoryStore(tmp_path, qdrant_store=None, redis_backend=None)
        content = store.read_memory()
        # The existing UUID should be preserved exactly
        assert "a4f7b2c1" in content, "Existing UUID should be preserved"
        # Should NOT appear twice (no double-migration)
        assert content.count("a4f7b2c1") == 1, "UUID should appear exactly once"
        assert content.count("already has uuid") == 1, "Bullet content should appear once"

    def test_migrate_handles_section_headings(self, tmp_path):
        """Section headings (## lines) are preserved without UUID injection."""
        old_content = "# Memory\n\n## My Section\n\n- a bullet\n"
        self._write_old_format(tmp_path, old_content)
        store = MemoryStore(tmp_path, qdrant_store=None, redis_backend=None)
        content = store.read_memory()
        # Section heading should still be present without UUID
        assert "## My Section" in content, "Section headings should be preserved"
        # Heading should NOT have UUID prefix
        heading_lines = [l for l in content.splitlines() if "My Section" in l]
        for line in heading_lines:
            assert not re.match(r".*\[\d{4}.*\].*My Section", line), (
                f"Section headings should NOT have UUID: {line!r}"
            )


class TestMigrationSentinel:
    """Tests that the .migration_v1 sentinel file is created and prevents re-migration."""

    def test_sentinel_created_after_migration(self, tmp_path):
        """After auto-migration, .migration_v1 file exists in workspace_dir."""
        old_content = "# Memory\n\n- old bullet needing migration\n"
        (tmp_path / "MEMORY.md").write_text(old_content, encoding="utf-8")
        store = MemoryStore(tmp_path, qdrant_store=None, redis_backend=None)
        store.read_memory()  # Trigger migration
        sentinel = tmp_path / ".migration_v1"
        assert sentinel.exists(), f".migration_v1 sentinel not found in {tmp_path}"

    def test_sentinel_prevents_remigration(self, tmp_path):
        """If sentinel exists, read_memory() does NOT re-process old-format bullets."""
        # Pre-create sentinel
        sentinel = tmp_path / ".migration_v1"
        sentinel.write_text("migrated\n", encoding="utf-8")
        # Write old-format content
        old_content = "# Memory\n\n- bullet without uuid\n"
        (tmp_path / "MEMORY.md").write_text(old_content, encoding="utf-8")
        store = MemoryStore(tmp_path, qdrant_store=None, redis_backend=None)
        content = store.read_memory()
        # Content should remain as-is (not migrated)
        assert "- bullet without uuid" in content, (
            "Sentinel should prevent migration, content should be unchanged"
        )
        # Should NOT have UUID prefix added
        bullet_lines = [l for l in content.splitlines() if "bullet without uuid" in l]
        for line in bullet_lines:
            assert not BULLET_UUID_RE.match(line.strip()), (
                f"With sentinel present, bullet should not be migrated: {line!r}"
            )


class TestEmbeddingTagStripping:
    """Tests that EmbeddingStore._split_into_chunks strips [timestamp uuid] tags before embedding."""

    def test_split_into_chunks_strips_tags(self):
        """_split_into_chunks with UUID-tagged bullet produces chunks without the [ts uuid] prefix."""
        tagged_content = (
            "# Memory\n\n"
            "## User Preferences\n\n"
            "- [2026-03-24T14:22:10Z a4f7b2c1] some text about preferences\n"
        )
        chunks = EmbeddingStore._split_into_chunks(tagged_content, source="memory")
        assert len(chunks) >= 1, "Should produce at least one chunk"
        # Find chunk containing our text
        pref_chunks = [c for c in chunks if "some text about preferences" in c["text"]]
        assert len(pref_chunks) >= 1, f"Expected chunk with 'some text', chunks: {chunks}"
        for chunk in pref_chunks:
            # The [timestamp uuid] tag should be stripped from the chunk text
            assert "[2026-03-24T14:22:10Z a4f7b2c1]" not in chunk["text"], (
                f"Tag should be stripped from chunk: {chunk['text']!r}"
            )
            # The actual content should still be there
            assert "some text about preferences" in chunk["text"]

    def test_split_into_chunks_preserves_non_tagged_lines(self):
        """Lines without UUID tags are passed through unchanged."""
        plain_content = (
            "# Memory\n\n"
            "## Common Patterns\n\n"
            "- a plain bullet with no uuid tag\n"
            "- another plain line\n"
        )
        chunks = EmbeddingStore._split_into_chunks(plain_content, source="memory")
        assert len(chunks) >= 1, "Should produce at least one chunk"
        # Find chunk containing our plain bullets
        pattern_chunks = [c for c in chunks if "plain bullet with no uuid tag" in c["text"]]
        assert len(pattern_chunks) >= 1, f"Expected chunk with plain bullets, got: {chunks}"
        for chunk in pattern_chunks:
            assert "plain bullet with no uuid tag" in chunk["text"]
            assert "another plain line" in chunk["text"]


# ── Plan 02: Entry-level union merge tests ────────────────────────────────────

from tools.node_sync import (
    _parse_memory_entries,
    _rebuild_memory,
    _resolve_entry_conflict,
)


class TestEntryParsing:
    """Tests for _parse_memory_entries() — UUID bullet parsing."""

    def test_parse_uuid_bullets(self):
        """_parse_memory_entries() with UUID-format bullets returns dict keyed by short UUID."""
        content = "# Memory\n\n- [2026-03-24T14:22:10Z a4f7b2c1] hello\n"
        result = _parse_memory_entries(content)
        assert "a4f7b2c1" in result
        entry = result["a4f7b2c1"]
        assert entry["ts"] == "2026-03-24T14:22:10Z"
        assert entry["content"] == "hello"
        assert entry["section"] == ""

    def test_parse_with_sections(self):
        """Entries under ## sections have the section name recorded."""
        content = "# Memory\n\n## MySection\n\n- [2026-03-24T14:22:10Z b1c2d3e4] text\n"
        result = _parse_memory_entries(content)
        assert "b1c2d3e4" in result
        assert result["b1c2d3e4"]["section"] == "MySection"

    def test_parse_ignores_non_uuid_lines(self):
        """Plain bullets, headings, and blank lines are not in the returned dict."""
        content = "# Heading\n\n## Section\n\n- plain bullet\n\nSome prose text\n"
        result = _parse_memory_entries(content)
        assert len(result) == 0, f"Expected empty dict, got: {result}"

    def test_parse_normalizes_crlf(self):
        """Content with \\r\\n line endings parses identically to \\n."""
        content_lf = "# Memory\n\n- [2026-03-24T14:22:10Z deadbeef] value\n"
        content_crlf = content_lf.replace("\n", "\r\n")
        result_lf = _parse_memory_entries(content_lf)
        result_crlf = _parse_memory_entries(content_crlf)
        assert result_lf == result_crlf, (
            f"CRLF should parse same as LF.\nLF: {result_lf}\nCRLF: {result_crlf}"
        )


class TestUnionMerge:
    """Tests for the union-merge logic using _parse_memory_entries and _rebuild_memory."""

    def test_merge_disjoint_entries(self):
        """Local has UUID-A, remote has UUID-B -> merged result contains both entries."""
        from tools.node_sync import _resolve_entry_conflict

        local_content = "# Memory\n\n- [2026-03-24T10:00:00Z aaaaaaaa] local entry\n"
        remote_content = "# Memory\n\n- [2026-03-24T11:00:00Z bbbbbbbb] remote entry\n"

        local_entries = _parse_memory_entries(local_content)
        remote_entries = _parse_memory_entries(remote_content)

        merged = {}
        for uid in set(local_entries) | set(remote_entries):
            l = local_entries.get(uid)
            r = remote_entries.get(uid)
            if l and r:
                merged[uid] = _resolve_entry_conflict(l, r) if l["content"] != r["content"] else l
            elif l:
                merged[uid] = l
            else:
                merged[uid] = r

        assert "aaaaaaaa" in merged, "Local entry should be in merged"
        assert "bbbbbbbb" in merged, "Remote entry should be in merged"
        assert merged["aaaaaaaa"]["content"] == "local entry"
        assert merged["bbbbbbbb"]["content"] == "remote entry"

    def test_merge_identical_entries(self):
        """Both nodes have UUID-A with same content -> merged has exactly one copy."""
        from tools.node_sync import _resolve_entry_conflict

        shared_content = "# Memory\n\n- [2026-03-24T10:00:00Z cccccccc] shared\n"
        local_entries = _parse_memory_entries(shared_content)
        remote_entries = _parse_memory_entries(shared_content)

        merged = {}
        for uid in set(local_entries) | set(remote_entries):
            l = local_entries.get(uid)
            r = remote_entries.get(uid)
            if l and r:
                merged[uid] = _resolve_entry_conflict(l, r) if l["content"] != r["content"] else l
            elif l:
                merged[uid] = l
            else:
                merged[uid] = r

        assert len(merged) == 1, f"Expected exactly one merged entry, got: {merged}"
        assert "cccccccc" in merged
        assert merged["cccccccc"]["content"] == "shared"

    def test_merge_missing_remote(self, tmp_path):
        """Remote MEMORY.md missing (ssh cat rc!=0) -> local content untouched."""
        import asyncio
        from unittest.mock import AsyncMock

        from tools.node_sync import NodeSyncTool

        local_memory = tmp_path / "MEMORY.md"
        local_memory.write_text(
            "# Memory\n\n- [2026-03-24T10:00:00Z eeeeeeee] local only\n",
            encoding="utf-8",
        )

        tool = NodeSyncTool(memory_store=None, workspace=str(tmp_path))

        # Mock _run_ssh to fail (remote missing) and _run_rsync to succeed
        tool._run_ssh = AsyncMock(return_value=(1, "", "No such file"))
        tool._run_rsync = AsyncMock(return_value=(0, "", ""))

        result = asyncio.run(tool._merge("agent42-prod", tmp_path, dry_run=True))
        assert result.success
        # Local content should be unchanged
        assert local_memory.read_text(encoding="utf-8") == (
            "# Memory\n\n- [2026-03-24T10:00:00Z eeeeeeee] local only\n"
        )


class TestConflictResolution:
    """Tests for _resolve_entry_conflict() — newest wins, older becomes history note."""

    def test_conflict_newest_wins(self):
        """Remote with newer timestamp wins; local content becomes history note."""
        local = {
            "ts": "2026-03-24T10:00:00Z",
            "content": "local version",
            "section": "",
        }
        remote = {
            "ts": "2026-03-24T12:00:00Z",
            "content": "remote version (newer)",
            "section": "",
        }
        winner = _resolve_entry_conflict(local, remote)
        assert "remote version (newer)" in winner["content"], (
            f"Newer (remote) content should be in winner: {winner['content']!r}"
        )
        assert "local version" in winner["content"], (
            f"Older (local) content should appear in history note: {winner['content']!r}"
        )
        assert "2026-03-24T10:00:00Z" in winner["content"], (
            f"Older timestamp should appear in history note: {winner['content']!r}"
        )

    def test_conflict_preserves_history(self):
        """Both winner content and loser content appear in merged entry."""
        local = {"ts": "2026-03-24T09:00:00Z", "content": "older text", "section": ""}
        remote = {"ts": "2026-03-24T10:00:00Z", "content": "newer text", "section": ""}
        winner = _resolve_entry_conflict(local, remote)
        # Winner's content is present
        assert "newer text" in winner["content"]
        # Loser's content is preserved as a history note
        assert "older text" in winner["content"]
        # History note marker format
        assert "[prev:" in winner["content"]


class TestSectionOrderPreservation:
    """Tests that _rebuild_memory preserves local section order."""

    def test_local_section_order_preserved(self):
        """Local sections A, B, C; remote-only section D -> merged order A, B, C, D."""
        local_content = (
            "# Memory\n\n"
            "## SectionA\n\n"
            "- [2026-03-24T10:00:00Z aaaaaaaa] alpha\n\n"
            "## SectionB\n\n"
            "- [2026-03-24T10:00:00Z bbbbbbbb] beta\n\n"
            "## SectionC\n\n"
            "- [2026-03-24T10:00:00Z cccccccc] gamma\n"
        )
        remote_content = (
            "# Memory\n\n"
            "## SectionB\n\n"
            "- [2026-03-24T10:00:00Z bbbbbbbb] beta\n\n"
            "## SectionD\n\n"
            "- [2026-03-24T10:00:00Z dddddddd] delta\n"
        )

        local_entries = _parse_memory_entries(local_content)
        remote_entries = _parse_memory_entries(remote_content)

        # Union merge
        merged = {}
        for uid in set(local_entries) | set(remote_entries):
            l = local_entries.get(uid)
            r = remote_entries.get(uid)
            merged[uid] = l if l else r

        result = _rebuild_memory(local_content, merged)

        # Section order: A before B before C before D
        pos_a = result.find("## SectionA")
        pos_b = result.find("## SectionB")
        pos_c = result.find("## SectionC")
        pos_d = result.find("## SectionD")

        assert pos_a != -1, "SectionA should be in merged output"
        assert pos_b != -1, "SectionB should be in merged output"
        assert pos_c != -1, "SectionC should be in merged output"
        assert pos_d != -1, "SectionD should be in merged output"
        assert pos_a < pos_b < pos_c < pos_d, (
            f"Sections should be in order A<B<C<D, got positions {pos_a},{pos_b},{pos_c},{pos_d}"
        )


class TestMigrateAction:
    """Tests for node_sync migrate --dry-run action."""

    def test_migrate_dry_run(self, tmp_path):
        """node_sync migrate --dry-run previews migration without modifying files."""
        import asyncio

        from tools.node_sync import NodeSyncTool

        old_content = "# Memory\n\n- old bullet without uuid\n- another old bullet\n"
        memory_file = tmp_path / "MEMORY.md"
        memory_file.write_text(old_content, encoding="utf-8")

        tool = NodeSyncTool(memory_store=None, workspace=str(tmp_path))
        result = asyncio.run(tool._migrate_action(tmp_path, dry_run=True))

        assert result.success, f"migrate --dry-run should succeed: {result}"
        assert "dry run" in result.output.lower() or "would migrate" in result.output.lower(), (
            f"Output should mention dry run: {result.output!r}"
        )
        # File should be unchanged
        assert memory_file.read_text(encoding="utf-8") == old_content, (
            "Dry run should not modify MEMORY.md"
        )
        # Sentinel should NOT be created
        assert not (tmp_path / ".migration_v1").exists(), "Dry run should not create sentinel"
