"""Tests for frood.py data directory auto-migration (DATA-02)."""

from unittest.mock import patch


class TestDataDirMigration:
    """Test _migrate_data_dir() in frood.py."""

    def _run_migrate(self, tmp_path):
        """Run _migrate_data_dir() with the project root pointing at tmp_path."""
        import frood

        # Patch Path(__file__).parent inside _migrate_data_dir to point at tmp_path.
        # The function calls Path(__file__).parent where __file__ is frood.__file__.
        # We patch frood.__file__ so that Path(__file__).parent == tmp_path.
        fake_file = str(tmp_path / "frood.py")
        with patch.object(frood, "__file__", fake_file):
            frood._migrate_data_dir()

    def test_migrate_when_only_old_exists(self, tmp_path, capsys):
        """When .agent42/ exists and .frood/ does not, rename it and print message."""
        old_dir = tmp_path / ".agent42"
        old_dir.mkdir()
        (old_dir / "test.txt").write_text("data")

        self._run_migrate(tmp_path)

        # .agent42/ should be gone and .frood/ should exist with content
        assert not old_dir.exists(), ".agent42/ should have been moved"
        new_dir = tmp_path / ".frood"
        assert new_dir.exists(), ".frood/ should have been created"
        assert (new_dir / "test.txt").read_text() == "data", "File contents should be preserved"

        # Stderr should contain migration message
        captured = capsys.readouterr()
        assert "[frood]" in captured.err
        assert "migrated" in captured.err.lower() or ".agent42" in captured.err

    def test_both_exist_uses_new(self, tmp_path, capsys):
        """When both .agent42/ and .frood/ exist, keep both and print warning to stderr."""
        old_dir = tmp_path / ".agent42"
        old_dir.mkdir()
        (old_dir / "old.txt").write_text("old data")

        new_dir = tmp_path / ".frood"
        new_dir.mkdir()
        (new_dir / "new.txt").write_text("new data")

        self._run_migrate(tmp_path)

        # Both directories should still exist (no deletion)
        assert old_dir.exists(), ".agent42/ should NOT have been deleted"
        assert new_dir.exists(), ".frood/ should still exist"
        assert (new_dir / "new.txt").read_text() == "new data", ".frood/ contents unchanged"

        # Stderr should contain WARNING
        captured = capsys.readouterr()
        assert "[frood]" in captured.err
        assert "WARNING" in captured.err or "both" in captured.err.lower()

    def test_neither_exists_noop(self, tmp_path, capsys):
        """When neither .agent42/ nor .frood/ exists, do nothing silently."""
        self._run_migrate(tmp_path)

        # Nothing should have been created
        assert not (tmp_path / ".agent42").exists()
        assert not (tmp_path / ".frood").exists()

        # No stderr output
        captured = capsys.readouterr()
        assert captured.err == "", f"Expected no stderr output, got: {captured.err!r}"

    def test_only_new_exists_noop(self, tmp_path, capsys):
        """When only .frood/ exists (already migrated), do nothing silently."""
        new_dir = tmp_path / ".frood"
        new_dir.mkdir()
        (new_dir / "data.txt").write_text("frood data")

        self._run_migrate(tmp_path)

        # .frood/ should still exist with original contents
        assert new_dir.exists()
        assert (new_dir / "data.txt").read_text() == "frood data"

        # No stderr output
        captured = capsys.readouterr()
        assert captured.err == "", f"Expected no stderr output, got: {captured.err!r}"
