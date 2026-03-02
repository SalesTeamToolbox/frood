"""Tests for core.git_auth — GIT_ASKPASS context manager."""

import os
import sys
from pathlib import Path

import pytest

from core.git_auth import git_askpass_env


class TestGitAskpassEnv:
    """Test the GIT_ASKPASS context manager."""

    def test_creates_script_with_token(self):
        """Script is created, contains the token, and is cleaned up."""
        base_env = {"PATH": os.environ.get("PATH", ""), "HOME": "/tmp"}
        with git_askpass_env("ghp_test123", base_env) as env:
            script_path = env["GIT_ASKPASS"]
            assert os.path.exists(script_path)
            content = Path(script_path).read_text()
            assert "ghp_test123" in content
            assert env["GIT_TERMINAL_PROMPT"] == "0"
        # Script should be cleaned up
        assert not os.path.exists(script_path)

    def test_empty_token_noop(self):
        """Empty token returns base env unchanged."""
        base_env = {"PATH": "/usr/bin", "CUSTOM": "value"}
        with git_askpass_env("", base_env) as env:
            assert "GIT_ASKPASS" not in env
            assert env["CUSTOM"] == "value"

    def test_none_base_env_uses_os_environ(self):
        """None base_env defaults to os.environ copy."""
        with git_askpass_env("mytoken") as env:
            assert "GIT_ASKPASS" in env
            # Should have inherited from os.environ
            assert "PATH" in env

    def test_script_extension(self):
        """Verify correct extension for platform."""
        with git_askpass_env("token123") as env:
            script = env["GIT_ASKPASS"]
            if sys.platform == "win32":
                assert script.endswith(".bat")
            else:
                assert script.endswith(".sh")

    def test_cleanup_on_exception(self):
        """Script is cleaned up even if an exception occurs inside the context."""
        script_path = None
        with pytest.raises(ValueError):
            with git_askpass_env("token") as env:
                script_path = env["GIT_ASKPASS"]
                assert os.path.exists(script_path)
                raise ValueError("test error")
        assert script_path is not None
        assert not os.path.exists(script_path)
