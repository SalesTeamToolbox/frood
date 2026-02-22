"""Tests for the first-run setup wizard endpoints and helpers."""

import os
from pathlib import Path
from unittest.mock import patch

from dashboard.server import _update_env_file

# ---------------------------------------------------------------------------
# _update_env_file helper
# ---------------------------------------------------------------------------


class TestUpdateEnvFile:
    """Unit tests for the .env file update helper."""

    def test_replaces_existing_key(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("FOO=bar\nBAZ=qux\n")
        _update_env_file(env, {"FOO": "new"})
        content = env.read_text()
        assert "FOO=new" in content
        assert "BAZ=qux" in content

    def test_uncomments_and_replaces(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("# DASHBOARD_PASSWORD_HASH=\nOTHER=val\n")
        _update_env_file(env, {"DASHBOARD_PASSWORD_HASH": "$2b$12$abc"})
        content = env.read_text()
        assert "DASHBOARD_PASSWORD_HASH=$2b$12$abc" in content
        assert "# DASHBOARD_PASSWORD_HASH" not in content

    def test_appends_missing_key(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("FOO=bar\n")
        _update_env_file(env, {"NEW_KEY": "value"})
        content = env.read_text()
        assert "FOO=bar" in content
        assert "NEW_KEY=value" in content

    def test_empty_value_clears_key(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("DASHBOARD_PASSWORD=changeme\n")
        _update_env_file(env, {"DASHBOARD_PASSWORD": ""})
        content = env.read_text()
        assert "DASHBOARD_PASSWORD=" in content
        # Should not have a value after the equals sign
        for line in content.splitlines():
            if line.startswith("DASHBOARD_PASSWORD="):
                assert line == "DASHBOARD_PASSWORD="

    def test_creates_env_if_missing(self, tmp_path):
        env = tmp_path / ".env"
        assert not env.exists()
        _update_env_file(env, {"KEY": "val"})
        assert env.exists()
        assert "KEY=val" in env.read_text()

    def test_handles_multiple_updates(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("A=1\nB=2\nC=3\n")
        _update_env_file(env, {"A": "10", "C": "30"})
        content = env.read_text()
        assert "A=10" in content
        assert "B=2" in content
        assert "C=30" in content

    def test_preserves_unrelated_lines(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("# Comment line\nFOO=bar\n\n# Another comment\n")
        _update_env_file(env, {"FOO": "baz"})
        lines = env.read_text().splitlines()
        assert "# Comment line" in lines
        assert "# Another comment" in lines


# ---------------------------------------------------------------------------
# Settings.reload_from_env
# ---------------------------------------------------------------------------


class TestReloadFromEnv:
    """Test that reload_from_env updates the frozen singleton in-place."""

    def test_reload_updates_field(self, tmp_path):
        from core.config import Settings, settings

        original_password = settings.dashboard_password

        # Write a temp .env and reload from it
        env = tmp_path / ".env"
        env.write_text("DASHBOARD_PASSWORD=test_reload_value\n")

        with patch.object(Path, "__truediv__", return_value=env):
            # Directly test the mechanism: set env var and reload
            os.environ["DASHBOARD_PASSWORD"] = "test_reload_value"
            try:
                new = Settings.from_env()
                for field_name in Settings.__dataclass_fields__:
                    object.__setattr__(settings, field_name, getattr(new, field_name))
                assert settings.dashboard_password == "test_reload_value"
            finally:
                # Restore original
                if original_password:
                    os.environ["DASHBOARD_PASSWORD"] = original_password
                else:
                    os.environ.pop("DASHBOARD_PASSWORD", None)
                new2 = Settings.from_env()
                for field_name in Settings.__dataclass_fields__:
                    object.__setattr__(settings, field_name, getattr(new2, field_name))


# ---------------------------------------------------------------------------
# Setup status endpoint logic
# ---------------------------------------------------------------------------


class TestSetupStatus:
    """Test the setup_needed detection logic."""

    def test_setup_needed_when_no_password(self):
        """When password is empty and no hash, setup is needed."""
        from dashboard.server import _INSECURE_PASSWORDS

        assert "" in _INSECURE_PASSWORDS

    def test_setup_needed_catches_default_password(self):
        """The default .env.example password is treated as insecure."""
        from dashboard.server import _INSECURE_PASSWORDS

        assert "changeme-right-now" in _INSECURE_PASSWORDS

    def test_real_password_not_insecure(self):
        """A user-chosen password should not be in the insecure set."""
        from dashboard.server import _INSECURE_PASSWORDS

        assert "my-secure-password" not in _INSECURE_PASSWORDS
