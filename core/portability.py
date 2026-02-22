"""
Agent42 portability — backup, restore, and clone operations.

Provides archive-based data portability for migration between hosts,
disaster recovery, and multi-node deployment.

Usage (via CLI):
    python agent42.py backup -o /tmp
    python agent42.py restore /tmp/agent42-backup-20260222-143000.tar.gz --target /new/path
    python agent42.py clone -o /tmp
"""

import json
import logging
import os
import re
import shutil
import stat
import tarfile
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger("agent42.portability")

MANIFEST_FILENAME = "manifest.json"
ARCHIVE_VERSION = 1

# Env var keys whose values should be redacted in clone templates
_SECRET_KEY_PATTERN = re.compile(r"_(KEY|TOKEN|PASSWORD|SECRET|HASH)$", re.IGNORECASE)

# Data categories and their relative paths (from the Agent42 installation root)
_BACKUP_CATEGORIES: dict[str, list[str]] = {
    "config": [".env.example", "requirements.txt", "setup.sh"],
    "state": ["tasks.json", "cron_jobs.json"],
    "memory": [".agent42/memory"],
    "sessions": [".agent42/sessions"],
    "audit": [".agent42/approvals.jsonl", ".agent42/devices.jsonl"],
    "secrets": [".env", ".agent42/settings.json"],
    "media": [".agent42/outputs", ".agent42/templates", ".agent42/images"],
    "qdrant": [".agent42/qdrant"],
    "skills": ["skills/workspace"],
}

# Categories always included in a clone package
_CLONE_CATEGORIES = {"config"}

# Source code paths to include in clone packages
_CLONE_SOURCE_PATTERNS: list[str] = [
    "agent42.py",
    "core",
    "tools",
    "agents",
    "memory",
    "channels",
    "providers",
    "dashboard",
    "skills/builtins",
    "skills/__init__.py",
    "skills/loader.py",
]

# Empty dirs to scaffold in a clone package
_CLONE_SCAFFOLD_DIRS: list[str] = [
    ".agent42/memory",
    ".agent42/sessions",
    ".agent42/outputs",
    ".agent42/templates",
    ".agent42/images",
]


@dataclass
class ArchiveManifest:
    """Metadata about a backup/clone archive."""

    version: int = ARCHIVE_VERSION
    created_at: str = ""
    archive_type: str = ""  # "backup" or "clone"
    categories: list[str] = field(default_factory=list)
    source_path: str = ""
    file_count: int = 0
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ArchiveManifest":
        known = {k for k in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


def _copy_path(src: Path, dst: Path) -> int:
    """Copy a file or directory tree, returning the number of files copied."""
    if not src.exists():
        return 0
    if src.is_file():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src), str(dst))
        return 1
    # Directory
    count = 0
    for item in src.rglob("*"):
        if item.is_file():
            rel = item.relative_to(src)
            target = dst / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(item), str(target))
            count += 1
    return count


def _sanitize_env_line(line: str) -> str:
    """Replace secret values with CHANGE_ME in a .env line."""
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return line
    if "=" not in stripped:
        return line
    key = stripped.split("=", 1)[0].strip()
    if _SECRET_KEY_PATTERN.search(key):
        return f"{key}=CHANGE_ME\n"
    return line


def _create_env_template(env_path: Path, template_path: Path) -> None:
    """Create a sanitized .env.template from a .env file."""
    if not env_path.exists():
        return
    lines = env_path.read_text().splitlines(keepends=True)
    sanitized = [_sanitize_env_line(line) for line in lines]
    template_path.parent.mkdir(parents=True, exist_ok=True)
    template_path.write_text("".join(sanitized))


def _resolve_worktree_dir() -> Path:
    """Resolve the worktree directory from env or default."""
    env_dir = os.environ.get("AGENT42_WORKTREE_DIR", "")
    if env_dir:
        return Path(env_dir).expanduser().resolve()
    return Path.home() / ".agent42" / "worktrees"


def create_backup(
    base_path: str,
    output_path: str,
    include_worktrees: bool = False,
) -> str:
    """Create a full backup archive of Agent42 data.

    Args:
        base_path: The Agent42 installation root directory.
        output_path: Directory where the archive will be written.
        include_worktrees: Whether to include git worktrees.

    Returns:
        Path to the created archive file.
    """
    base = Path(base_path).resolve()
    out_dir = Path(output_path).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    archive_name = f"agent42-backup-{timestamp}.tar.gz"

    staging = Path(tempfile.mkdtemp(prefix="agent42-backup-"))
    try:
        file_count = 0
        categories_included = []

        for category, paths in _BACKUP_CATEGORIES.items():
            cat_count = 0
            for rel_path in paths:
                src = base / rel_path
                dst = staging / rel_path
                cat_count += _copy_path(src, dst)
            if cat_count > 0:
                categories_included.append(category)
                file_count += cat_count

        # Worktrees (opt-in)
        if include_worktrees:
            wt_dir = _resolve_worktree_dir()
            if wt_dir.exists():
                dst = staging / "worktrees"
                count = _copy_path(wt_dir, dst)
                if count > 0:
                    categories_included.append("worktrees")
                    file_count += count

        # Write manifest
        manifest = ArchiveManifest(
            version=ARCHIVE_VERSION,
            created_at=datetime.now(UTC).isoformat(),
            archive_type="backup",
            categories=categories_included,
            source_path=str(base),
            file_count=file_count,
        )
        manifest_path = staging / MANIFEST_FILENAME
        manifest_path.write_text(json.dumps(manifest.to_dict(), indent=2))

        # Create tar.gz
        archive_path = out_dir / archive_name
        with tarfile.open(str(archive_path), "w:gz") as tar:
            for item in staging.rglob("*"):
                arcname = str(item.relative_to(staging))
                tar.add(str(item), arcname=arcname)

        logger.info(
            "Backup created: %s (%d files, categories: %s)",
            archive_path,
            file_count,
            ", ".join(categories_included),
        )
        return str(archive_path)

    finally:
        shutil.rmtree(staging, ignore_errors=True)


def restore_backup(
    archive_path: str,
    target_path: str,
    skip_secrets: bool = False,
) -> ArchiveManifest:
    """Restore Agent42 data from a backup archive.

    Args:
        archive_path: Path to the .tar.gz backup archive.
        target_path: Directory to restore into.
        skip_secrets: If True, skip restoring .env and settings.json.

    Returns:
        The archive manifest.

    Raises:
        FileNotFoundError: If the archive does not exist.
        ValueError: If the archive is invalid or has an incompatible version.
    """
    archive = Path(archive_path).resolve()
    if not archive.exists():
        raise FileNotFoundError(f"Archive not found: {archive}")

    target = Path(target_path).resolve()
    target.mkdir(parents=True, exist_ok=True)

    extract_dir = Path(tempfile.mkdtemp(prefix="agent42-restore-"))
    try:
        # Extract archive
        with tarfile.open(str(archive), "r:gz") as tar:
            tar.extractall(path=str(extract_dir), filter="data")

        # Read and validate manifest
        manifest_path = extract_dir / MANIFEST_FILENAME
        if not manifest_path.exists():
            raise ValueError("Invalid archive: missing manifest.json")

        manifest_data = json.loads(manifest_path.read_text())
        manifest = ArchiveManifest.from_dict(manifest_data)

        if manifest.version > ARCHIVE_VERSION:
            raise ValueError(
                f"Archive version {manifest.version} is newer than supported "
                f"version {ARCHIVE_VERSION}"
            )

        if manifest.archive_type != "backup":
            raise ValueError(f"Expected archive_type 'backup', got '{manifest.archive_type}'")

        # Secret paths to skip if requested
        secret_paths = {".env", ".agent42/settings.json"}

        # Copy files from extracted archive to target
        for item in extract_dir.rglob("*"):
            if item.is_file() and item.name != MANIFEST_FILENAME:
                rel = item.relative_to(extract_dir)
                rel_str = str(rel)

                if skip_secrets and rel_str in secret_paths:
                    logger.info("Skipping secret file: %s", rel_str)
                    continue

                dest = target / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(item), str(dest))

                # Restore restrictive permissions for settings.json
                if rel_str == ".agent42/settings.json":
                    os.chmod(str(dest), stat.S_IRUSR | stat.S_IWUSR)  # 0o600

        logger.info(
            "Restored backup to %s (categories: %s)",
            target,
            ", ".join(manifest.categories),
        )
        return manifest

    finally:
        shutil.rmtree(extract_dir, ignore_errors=True)


def create_clone(
    base_path: str,
    output_path: str,
    include_skills: bool = False,
) -> str:
    """Create a clone package for deploying Agent42 to a new node.

    Includes source code and config templates but excludes state, memory,
    and secrets. Secrets in .env are replaced with CHANGE_ME placeholders.

    Args:
        base_path: The Agent42 installation root directory.
        output_path: Directory where the archive will be written.
        include_skills: Whether to include user-installed skills.

    Returns:
        Path to the created archive file.
    """
    base = Path(base_path).resolve()
    out_dir = Path(output_path).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    archive_name = f"agent42-clone-{timestamp}.tar.gz"

    staging = Path(tempfile.mkdtemp(prefix="agent42-clone-"))
    try:
        file_count = 0
        categories_included = []

        # Config files
        for rel_path in _BACKUP_CATEGORIES["config"]:
            src = base / rel_path
            dst = staging / rel_path
            file_count += _copy_path(src, dst)
        categories_included.append("config")

        # Source code
        for pattern in _CLONE_SOURCE_PATTERNS:
            src = base / pattern
            dst = staging / pattern
            file_count += _copy_path(src, dst)
        categories_included.append("source")

        # Sanitized .env template
        env_src = base / ".env"
        if env_src.exists():
            _create_env_template(env_src, staging / ".env.template")
            file_count += 1
            categories_included.append("env_template")

        # User-installed skills (opt-in)
        if include_skills:
            src = base / "skills" / "workspace"
            if src.exists():
                dst = staging / "skills" / "workspace"
                count = _copy_path(src, dst)
                if count > 0:
                    categories_included.append("skills")
                    file_count += count

        # Create empty directory scaffold
        for dir_path in _CLONE_SCAFFOLD_DIRS:
            scaffold = staging / dir_path
            scaffold.mkdir(parents=True, exist_ok=True)
            # Add a .gitkeep so tar preserves the empty directory
            (scaffold / ".gitkeep").write_text("")
            file_count += 1

        # Write manifest
        manifest = ArchiveManifest(
            version=ARCHIVE_VERSION,
            created_at=datetime.now(UTC).isoformat(),
            archive_type="clone",
            categories=categories_included,
            source_path=str(base),
            file_count=file_count,
            notes="Secrets redacted. Edit .env.template and rename to .env before running setup.sh.",
        )
        manifest_path = staging / MANIFEST_FILENAME
        manifest_path.write_text(json.dumps(manifest.to_dict(), indent=2))

        # Create tar.gz
        archive_path = out_dir / archive_name
        with tarfile.open(str(archive_path), "w:gz") as tar:
            for item in staging.rglob("*"):
                arcname = str(item.relative_to(staging))
                tar.add(str(item), arcname=arcname)

        logger.info(
            "Clone package created: %s (%d files, categories: %s)",
            archive_path,
            file_count,
            ", ".join(categories_included),
        )
        return str(archive_path)

    finally:
        shutil.rmtree(staging, ignore_errors=True)
