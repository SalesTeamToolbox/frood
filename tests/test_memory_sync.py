"""Tests for Phase 3: Memory Sync — UUID injection, frontmatter, migration, and embedding tag stripping.

Covers MEM-01 requirements:
- UUID+timestamp prefix on every new bullet
- YAML frontmatter with file_id and last_modified
- Auto-migration of legacy bullets with deterministic UUID5
- Sentinel file prevents double migration
- Embedding pipeline strips [timestamp uuid] tags before vectorizing
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
