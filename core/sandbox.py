"""
Workspace sandboxing — restricts agent file operations to allowed directories.

Inspired by Nanobot's restrictToWorkspace pattern with _resolve_path() enforcement.
All file paths are resolved and checked against the allowed directory before any operation.
"""

import logging
from pathlib import Path

logger = logging.getLogger("agent42.sandbox")


class SandboxViolation(PermissionError):
    """Raised when an operation attempts to escape the sandbox."""

    def __init__(self, attempted_path: str, allowed_dir: str):
        super().__init__(
            f"Sandbox violation: '{attempted_path}' is outside allowed directory '{allowed_dir}'"
        )
        self.attempted_path = attempted_path
        self.allowed_dir = allowed_dir


class WorkspaceSandbox:
    """Enforces filesystem access boundaries for agent operations."""

    def __init__(self, allowed_dir: str | Path, enabled: bool = True):
        self.allowed_dir = Path(allowed_dir).resolve()
        self.enabled = enabled

    def resolve_path(self, path: str | Path) -> Path:
        """Resolve a path and verify it's within the sandbox.

        Blocks path traversal (../), absolute paths outside the allowed directory,
        null bytes in paths, and symlinks that escape the sandbox.
        """
        if not self.enabled:
            return Path(path).resolve()

        path_str = str(path)

        # Block null bytes — can bypass C-level path checks
        if "\x00" in path_str:
            raise SandboxViolation(repr(path_str), str(self.allowed_dir))

        target = Path(path_str)

        # Resolve relative paths against allowed_dir
        if not target.is_absolute():
            target = self.allowed_dir / target

        # resolve() follows symlinks to get the real path
        resolved = target.resolve()

        # Verify the resolved (real) path is within the allowed directory
        try:
            resolved.relative_to(self.allowed_dir)
        except ValueError:
            raise SandboxViolation(str(path), str(self.allowed_dir))

        # If the target exists and is a symlink, also verify the symlink target
        # This catches symlinks created after initial resolution (defense in depth)
        if target.is_symlink():
            link_target = target.resolve(strict=False)
            try:
                link_target.relative_to(self.allowed_dir)
            except ValueError:
                raise SandboxViolation(
                    f"{path} (symlink to {link_target})", str(self.allowed_dir)
                )

        return resolved

    def check_path(self, path: str | Path) -> bool:
        """Check if a path is within the sandbox without raising."""
        try:
            self.resolve_path(path)
            return True
        except SandboxViolation:
            return False

    def validate_paths(self, *paths: str | Path) -> list[Path]:
        """Resolve and validate multiple paths, raising on first violation."""
        return [self.resolve_path(p) for p in paths]
