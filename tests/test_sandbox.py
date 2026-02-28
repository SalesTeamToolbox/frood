"""Tests for Phase 1: WorkspaceSandbox."""

import os
import tempfile
from pathlib import Path

import pytest

from core.sandbox import SandboxViolation, WorkspaceSandbox

_TEST_WORKSPACE = os.path.join(tempfile.gettempdir(), "test_workspace")


class TestWorkspaceSandbox:
    def setup_method(self):
        self.sandbox = WorkspaceSandbox(_TEST_WORKSPACE, enabled=True)

    def test_resolve_relative_path(self):
        resolved = self.sandbox.resolve_path("subdir/file.txt")
        assert str(resolved).startswith(_TEST_WORKSPACE)

    def test_block_path_traversal(self):
        with pytest.raises(SandboxViolation):
            self.sandbox.resolve_path("../../etc/passwd")

    def test_block_absolute_path_outside(self):
        with pytest.raises(SandboxViolation):
            self.sandbox.resolve_path("/etc/passwd")

    def test_allow_path_inside(self):
        resolved = self.sandbox.resolve_path("src/main.py")
        assert resolved == Path(os.path.join(_TEST_WORKSPACE, "src", "main.py"))

    def test_check_path_returns_bool(self):
        assert self.sandbox.check_path("safe/file.txt") is True
        assert self.sandbox.check_path("../../etc/passwd") is False

    def test_disabled_sandbox_allows_all(self):
        disabled = WorkspaceSandbox(
            os.path.join(tempfile.gettempdir(), "test"), enabled=False
        )
        resolved = disabled.resolve_path("/etc/passwd")
        # On Windows, Path("/etc/passwd") resolves to C:/etc/passwd
        assert str(resolved).replace("\\", "/").endswith("/etc/passwd")

    def test_validate_multiple_paths(self):
        paths = self.sandbox.validate_paths("a.txt", "b/c.txt")
        assert len(paths) == 2

    def test_validate_paths_raises_on_violation(self):
        with pytest.raises(SandboxViolation):
            self.sandbox.validate_paths("ok.txt", "../../bad.txt")
