"""Tests for Agent42 portability — backup, restore, and clone operations."""

import json
import os
import shutil
import stat
import tarfile
import tempfile

import pytest

from core.portability import (
    ARCHIVE_VERSION,
    MANIFEST_FILENAME,
    ArchiveManifest,
    _sanitize_env_line,
    create_backup,
    create_clone,
    restore_backup,
)


def _create_agent42_tree(root: str) -> None:
    """Create a representative Agent42 directory structure for testing."""
    base = os.path.join(root, ".agent42")
    os.makedirs(os.path.join(base, "memory"), exist_ok=True)
    os.makedirs(os.path.join(base, "sessions"), exist_ok=True)
    os.makedirs(os.path.join(base, "outputs"), exist_ok=True)
    os.makedirs(os.path.join(base, "templates"), exist_ok=True)
    os.makedirs(os.path.join(base, "images"), exist_ok=True)
    os.makedirs(os.path.join(base, "qdrant"), exist_ok=True)
    os.makedirs(os.path.join(root, "skills", "workspace", "my-skill"), exist_ok=True)

    # Memory files
    with open(os.path.join(base, "memory", "MEMORY.md"), "w") as f:
        f.write("# Memory\nSome learned facts.\n")
    with open(os.path.join(base, "memory", "HISTORY.md"), "w") as f:
        f.write("# History\n- 2026-01-01: event\n")
    with open(os.path.join(base, "memory", "embeddings.json"), "w") as f:
        json.dump([{"text": "test", "vector": [0.1, 0.2]}], f)

    # Sessions
    with open(os.path.join(base, "sessions", "discord_123.jsonl"), "w") as f:
        f.write('{"role": "user", "content": "hello"}\n')

    # Audit
    with open(os.path.join(base, "approvals.jsonl"), "w") as f:
        f.write('{"event": "approved", "task_id": "abc"}\n')
    with open(os.path.join(base, "devices.jsonl"), "w") as f:
        f.write('{"device_id": "dev1", "name": "laptop"}\n')

    # Secrets (with restrictive permissions)
    settings_path = os.path.join(base, "settings.json")
    with open(settings_path, "w") as f:
        json.dump({"OPENAI_API_KEY": "sk-test123"}, f)
    os.chmod(settings_path, stat.S_IRUSR | stat.S_IWUSR)

    # Root-level files
    with open(os.path.join(root, ".env"), "w") as f:
        f.write("OPENROUTER_API_KEY=or-key-123\n")
        f.write("DASHBOARD_PASSWORD=secret\n")
        f.write("DEFAULT_REPO_PATH=/home/user/myrepo\n")
        f.write("# Comment line\n")
        f.write("MAX_CONCURRENT_AGENTS=3\n")

    with open(os.path.join(root, ".env.example"), "w") as f:
        f.write("OPENROUTER_API_KEY=your-key-here\n")

    with open(os.path.join(root, "tasks.json"), "w") as f:
        json.dump([{"id": "task1", "title": "Test task"}], f)

    with open(os.path.join(root, "cron_jobs.json"), "w") as f:
        json.dump([], f)

    with open(os.path.join(root, "requirements.txt"), "w") as f:
        f.write("fastapi\nuvicorn\n")

    with open(os.path.join(root, "setup.sh"), "w") as f:
        f.write("#!/bin/bash\necho setup\n")

    # Media
    with open(os.path.join(base, "outputs", "report.txt"), "w") as f:
        f.write("Output report\n")
    with open(os.path.join(base, "images", "gen.png"), "wb") as f:
        f.write(b"\x89PNG fake data")

    # Qdrant
    with open(os.path.join(base, "qdrant", "collection.dat"), "wb") as f:
        f.write(b"qdrant data")

    # User skills
    with open(os.path.join(root, "skills", "workspace", "my-skill", "SKILL.md"), "w") as f:
        f.write("---\nname: my-skill\n---\nCustom skill.\n")


class TestArchiveManifest:
    def test_to_dict(self):
        m = ArchiveManifest(
            version=1,
            created_at="2026-02-22T00:00:00",
            archive_type="backup",
            categories=["config", "state"],
            source_path="/home/user/agent42",
            file_count=42,
        )
        d = m.to_dict()
        assert d["version"] == 1
        assert d["archive_type"] == "backup"
        assert d["file_count"] == 42
        assert "config" in d["categories"]

    def test_from_dict(self):
        d = {
            "version": 1,
            "created_at": "2026-02-22T00:00:00",
            "archive_type": "clone",
            "categories": ["config"],
            "source_path": "/tmp/test",
            "file_count": 5,
            "notes": "test note",
        }
        m = ArchiveManifest.from_dict(d)
        assert m.version == 1
        assert m.archive_type == "clone"
        assert m.notes == "test note"

    def test_from_dict_ignores_unknown_keys(self):
        d = {"version": 1, "archive_type": "backup", "unknown_field": "ignored"}
        m = ArchiveManifest.from_dict(d)
        assert m.version == 1
        assert not hasattr(m, "unknown_field")

    def test_roundtrip(self):
        original = ArchiveManifest(
            version=1,
            created_at="2026-02-22T12:00:00",
            archive_type="backup",
            categories=["config", "state", "memory"],
            source_path="/home/user/agent42",
            file_count=100,
            notes="Full backup",
        )
        restored = ArchiveManifest.from_dict(original.to_dict())
        assert restored.to_dict() == original.to_dict()


class TestSanitizeEnvLine:
    def test_redacts_api_key(self):
        assert _sanitize_env_line("OPENROUTER_API_KEY=sk-123\n") == "OPENROUTER_API_KEY=CHANGE_ME\n"

    def test_redacts_token(self):
        assert _sanitize_env_line("DISCORD_BOT_TOKEN=xyz\n") == "DISCORD_BOT_TOKEN=CHANGE_ME\n"

    def test_redacts_password(self):
        assert _sanitize_env_line("DASHBOARD_PASSWORD=secret\n") == "DASHBOARD_PASSWORD=CHANGE_ME\n"

    def test_redacts_secret(self):
        assert _sanitize_env_line("JWT_SECRET=abc123\n") == "JWT_SECRET=CHANGE_ME\n"

    def test_redacts_hash(self):
        assert (
            _sanitize_env_line("DASHBOARD_PASSWORD_HASH=$2b$...\n")
            == "DASHBOARD_PASSWORD_HASH=CHANGE_ME\n"
        )

    def test_preserves_non_secret(self):
        assert _sanitize_env_line("MAX_CONCURRENT_AGENTS=3\n") == "MAX_CONCURRENT_AGENTS=3\n"

    def test_preserves_comment(self):
        assert _sanitize_env_line("# This is a comment\n") == "# This is a comment\n"

    def test_preserves_empty_line(self):
        assert _sanitize_env_line("\n") == "\n"

    def test_preserves_path(self):
        assert (
            _sanitize_env_line("DEFAULT_REPO_PATH=/home/user/repo\n")
            == "DEFAULT_REPO_PATH=/home/user/repo\n"
        )


class TestBackup:
    def setup_method(self):
        self.source = tempfile.mkdtemp()
        self.output = tempfile.mkdtemp()
        _create_agent42_tree(self.source)

    def teardown_method(self):
        shutil.rmtree(self.source, ignore_errors=True)
        shutil.rmtree(self.output, ignore_errors=True)

    def test_backup_creates_archive(self):
        path = create_backup(self.source, self.output)
        assert os.path.exists(path)
        assert path.endswith(".tar.gz")
        assert "agent42-backup-" in os.path.basename(path)

    def test_backup_includes_manifest(self):
        path = create_backup(self.source, self.output)
        with tarfile.open(path, "r:gz") as tar:
            names = tar.getnames()
            assert MANIFEST_FILENAME in names

    def test_backup_includes_expected_categories(self):
        path = create_backup(self.source, self.output)
        with tarfile.open(path, "r:gz") as tar:
            manifest_member = tar.getmember(MANIFEST_FILENAME)
            manifest_data = json.loads(tar.extractfile(manifest_member).read())
            manifest = ArchiveManifest.from_dict(manifest_data)

        assert manifest.archive_type == "backup"
        assert manifest.version == ARCHIVE_VERSION
        assert "config" in manifest.categories
        assert "state" in manifest.categories
        assert "memory" in manifest.categories
        assert "sessions" in manifest.categories
        assert "audit" in manifest.categories
        assert "secrets" in manifest.categories
        assert "media" in manifest.categories
        assert "qdrant" in manifest.categories
        assert "skills" in manifest.categories

    def test_backup_contains_data_files(self):
        path = create_backup(self.source, self.output)
        with tarfile.open(path, "r:gz") as tar:
            names = tar.getnames()
            assert ".agent42/memory/MEMORY.md" in names
            assert "tasks.json" in names
            assert ".env" in names
            assert ".agent42/settings.json" in names
            assert ".agent42/sessions/discord_123.jsonl" in names

    def test_backup_excludes_worktrees_by_default(self):
        # Create a fake worktree dir
        wt_dir = os.path.join(self.source, "fake_worktrees")
        os.makedirs(wt_dir)
        with open(os.path.join(wt_dir, "task1.txt"), "w") as f:
            f.write("worktree data")

        path = create_backup(self.source, self.output)
        with tarfile.open(path, "r:gz") as tar:
            names = tar.getnames()
            assert not any("worktrees" in n for n in names)

    def test_backup_includes_worktrees_when_flagged(self):
        # Create a worktree directory and point env to it
        wt_dir = tempfile.mkdtemp()
        os.makedirs(os.path.join(wt_dir, "task1"), exist_ok=True)
        with open(os.path.join(wt_dir, "task1", "file.py"), "w") as f:
            f.write("print('hello')")

        old_env = os.environ.get("AGENT42_WORKTREE_DIR", "")
        os.environ["AGENT42_WORKTREE_DIR"] = wt_dir
        try:
            path = create_backup(self.source, self.output, include_worktrees=True)
            with tarfile.open(path, "r:gz") as tar:
                manifest_data = json.loads(tar.extractfile(tar.getmember(MANIFEST_FILENAME)).read())
                manifest = ArchiveManifest.from_dict(manifest_data)
                assert "worktrees" in manifest.categories
                names = tar.getnames()
                assert any("worktrees" in n for n in names)
        finally:
            os.environ["AGENT42_WORKTREE_DIR"] = old_env
            shutil.rmtree(wt_dir, ignore_errors=True)

    def test_backup_file_count_is_positive(self):
        path = create_backup(self.source, self.output)
        with tarfile.open(path, "r:gz") as tar:
            manifest_data = json.loads(tar.extractfile(tar.getmember(MANIFEST_FILENAME)).read())
            manifest = ArchiveManifest.from_dict(manifest_data)
            assert manifest.file_count > 0


class TestRestore:
    def setup_method(self):
        self.source = tempfile.mkdtemp()
        self.output = tempfile.mkdtemp()
        self.restore_dir = tempfile.mkdtemp()
        _create_agent42_tree(self.source)

    def teardown_method(self):
        shutil.rmtree(self.source, ignore_errors=True)
        shutil.rmtree(self.output, ignore_errors=True)
        shutil.rmtree(self.restore_dir, ignore_errors=True)

    def test_restore_recreates_structure(self):
        path = create_backup(self.source, self.output)
        manifest = restore_backup(path, self.restore_dir)

        assert os.path.exists(os.path.join(self.restore_dir, ".agent42", "memory", "MEMORY.md"))
        assert os.path.exists(os.path.join(self.restore_dir, "tasks.json"))
        assert os.path.exists(os.path.join(self.restore_dir, ".env"))
        assert os.path.exists(
            os.path.join(self.restore_dir, ".agent42", "sessions", "discord_123.jsonl")
        )
        assert manifest.archive_type == "backup"

    def test_restore_preserves_file_content(self):
        path = create_backup(self.source, self.output)
        restore_backup(path, self.restore_dir)

        with open(os.path.join(self.restore_dir, ".agent42", "memory", "MEMORY.md")) as f:
            assert "Some learned facts." in f.read()

        with open(os.path.join(self.restore_dir, "tasks.json")) as f:
            tasks = json.load(f)
            assert tasks[0]["id"] == "task1"

    def test_restore_preserves_settings_permissions(self):
        path = create_backup(self.source, self.output)
        restore_backup(path, self.restore_dir)

        settings_path = os.path.join(self.restore_dir, ".agent42", "settings.json")
        mode = os.stat(settings_path).st_mode
        assert mode & stat.S_IRUSR  # Owner read
        assert mode & stat.S_IWUSR  # Owner write
        assert not (mode & stat.S_IRGRP)  # No group read
        assert not (mode & stat.S_IROTH)  # No other read

    def test_restore_skip_secrets(self):
        path = create_backup(self.source, self.output)
        restore_backup(path, self.restore_dir, skip_secrets=True)

        assert not os.path.exists(os.path.join(self.restore_dir, ".env"))
        assert not os.path.exists(os.path.join(self.restore_dir, ".agent42", "settings.json"))
        # Non-secret files should still be restored
        assert os.path.exists(os.path.join(self.restore_dir, "tasks.json"))

    def test_restore_returns_manifest(self):
        path = create_backup(self.source, self.output)
        manifest = restore_backup(path, self.restore_dir)

        assert isinstance(manifest, ArchiveManifest)
        assert manifest.archive_type == "backup"
        assert manifest.version == ARCHIVE_VERSION
        assert manifest.file_count > 0

    def test_restore_rejects_missing_archive(self):
        with pytest.raises(FileNotFoundError):
            restore_backup("/nonexistent/backup.tar.gz", self.restore_dir)

    def test_restore_rejects_invalid_archive(self):
        # Create a tar.gz without manifest
        bad_archive = os.path.join(self.output, "bad.tar.gz")
        with tarfile.open(bad_archive, "w:gz") as tar:
            dummy = os.path.join(self.output, "dummy.txt")
            with open(dummy, "w") as f:
                f.write("not a backup")
            tar.add(dummy, arcname="dummy.txt")

        with pytest.raises(ValueError, match="missing manifest"):
            restore_backup(bad_archive, self.restore_dir)

    def test_restore_rejects_clone_archive(self):
        clone_path = create_clone(self.source, self.output)
        with pytest.raises(ValueError, match="Expected archive_type 'backup'"):
            restore_backup(clone_path, self.restore_dir)

    def test_restore_rejects_future_version(self):
        # Create a backup with a future version
        staging = tempfile.mkdtemp()
        manifest = {
            "version": 999,
            "archive_type": "backup",
            "categories": [],
            "created_at": "",
            "source_path": "",
            "file_count": 0,
            "notes": "",
        }
        with open(os.path.join(staging, MANIFEST_FILENAME), "w") as f:
            json.dump(manifest, f)
        future_archive = os.path.join(self.output, "future.tar.gz")
        with tarfile.open(future_archive, "w:gz") as tar:
            tar.add(os.path.join(staging, MANIFEST_FILENAME), arcname=MANIFEST_FILENAME)
        shutil.rmtree(staging)

        with pytest.raises(ValueError, match="newer than supported"):
            restore_backup(future_archive, self.restore_dir)


class TestClone:
    def setup_method(self):
        self.source = tempfile.mkdtemp()
        self.output = tempfile.mkdtemp()
        _create_agent42_tree(self.source)

    def teardown_method(self):
        shutil.rmtree(self.source, ignore_errors=True)
        shutil.rmtree(self.output, ignore_errors=True)

    def test_clone_creates_archive(self):
        path = create_clone(self.source, self.output)
        assert os.path.exists(path)
        assert path.endswith(".tar.gz")
        assert "agent42-clone-" in os.path.basename(path)

    def test_clone_includes_manifest(self):
        path = create_clone(self.source, self.output)
        with tarfile.open(path, "r:gz") as tar:
            names = tar.getnames()
            assert MANIFEST_FILENAME in names
            manifest_data = json.loads(tar.extractfile(tar.getmember(MANIFEST_FILENAME)).read())
            assert manifest_data["archive_type"] == "clone"

    def test_clone_sanitizes_env(self):
        path = create_clone(self.source, self.output)
        with tarfile.open(path, "r:gz") as tar:
            names = tar.getnames()
            assert ".env.template" in names
            # .env itself should NOT be in the clone
            assert ".env" not in names

            template_content = tar.extractfile(tar.getmember(".env.template")).read().decode()
            assert "CHANGE_ME" in template_content
            assert "or-key-123" not in template_content
            assert "secret" not in template_content
            # Non-secret values should be preserved
            assert "MAX_CONCURRENT_AGENTS=3" in template_content

    def test_clone_excludes_state_and_memory(self):
        path = create_clone(self.source, self.output)
        with tarfile.open(path, "r:gz") as tar:
            names = tar.getnames()
            assert "tasks.json" not in names
            assert ".agent42/memory/MEMORY.md" not in names
            assert ".agent42/sessions/discord_123.jsonl" not in names
            assert ".agent42/approvals.jsonl" not in names
            assert ".agent42/settings.json" not in names

    def test_clone_includes_config_files(self):
        path = create_clone(self.source, self.output)
        with tarfile.open(path, "r:gz") as tar:
            names = tar.getnames()
            assert ".env.example" in names
            assert "requirements.txt" in names
            assert "setup.sh" in names

    def test_clone_includes_empty_directory_structure(self):
        path = create_clone(self.source, self.output)
        with tarfile.open(path, "r:gz") as tar:
            names = tar.getnames()
            # Scaffold dirs should have .gitkeep files
            assert ".agent42/memory/.gitkeep" in names
            assert ".agent42/sessions/.gitkeep" in names
            assert ".agent42/outputs/.gitkeep" in names
            assert ".agent42/templates/.gitkeep" in names
            assert ".agent42/images/.gitkeep" in names

    def test_clone_excludes_skills_by_default(self):
        path = create_clone(self.source, self.output)
        with tarfile.open(path, "r:gz") as tar:
            manifest_data = json.loads(tar.extractfile(tar.getmember(MANIFEST_FILENAME)).read())
            assert "skills" not in manifest_data["categories"]

    def test_clone_includes_skills_when_flagged(self):
        path = create_clone(self.source, self.output, include_skills=True)
        with tarfile.open(path, "r:gz") as tar:
            manifest_data = json.loads(tar.extractfile(tar.getmember(MANIFEST_FILENAME)).read())
            assert "skills" in manifest_data["categories"]
            names = tar.getnames()
            assert any("skills/workspace/my-skill" in n for n in names)

    def test_clone_manifest_has_notes(self):
        path = create_clone(self.source, self.output)
        with tarfile.open(path, "r:gz") as tar:
            manifest_data = json.loads(tar.extractfile(tar.getmember(MANIFEST_FILENAME)).read())
            assert "Secrets redacted" in manifest_data["notes"]


class TestRoundTrip:
    """End-to-end: backup -> restore -> verify contents match."""

    def setup_method(self):
        self.source = tempfile.mkdtemp()
        self.output = tempfile.mkdtemp()
        self.restore_dir = tempfile.mkdtemp()
        _create_agent42_tree(self.source)

    def teardown_method(self):
        shutil.rmtree(self.source, ignore_errors=True)
        shutil.rmtree(self.output, ignore_errors=True)
        shutil.rmtree(self.restore_dir, ignore_errors=True)

    def test_roundtrip_preserves_data(self):
        archive = create_backup(self.source, self.output)
        restore_backup(archive, self.restore_dir)

        # Compare key files
        for rel in [
            ".agent42/memory/MEMORY.md",
            ".agent42/memory/HISTORY.md",
            "tasks.json",
            ".env",
            ".agent42/sessions/discord_123.jsonl",
            ".agent42/approvals.jsonl",
        ]:
            src_path = os.path.join(self.source, rel)
            dst_path = os.path.join(self.restore_dir, rel)
            assert os.path.exists(dst_path), f"Missing after restore: {rel}"
            with open(src_path) as f:
                src_content = f.read()
            with open(dst_path) as f:
                dst_content = f.read()
            assert src_content == dst_content, f"Content mismatch for {rel}"

    def test_roundtrip_preserves_binary_data(self):
        archive = create_backup(self.source, self.output)
        restore_backup(archive, self.restore_dir)

        src_img = os.path.join(self.source, ".agent42", "images", "gen.png")
        dst_img = os.path.join(self.restore_dir, ".agent42", "images", "gen.png")
        with open(src_img, "rb") as f:
            src_data = f.read()
        with open(dst_img, "rb") as f:
            dst_data = f.read()
        assert src_data == dst_data
