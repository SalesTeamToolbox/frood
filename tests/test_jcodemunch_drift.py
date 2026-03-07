"""Tests for jcodemunch mid-session drift detection in jcodemunch-reindex hook.

Validates that the hook detects source code drift from PostToolUse
get_symbol responses with content_verified=false and emits re-index
recommendations.
"""

import importlib
import io
import json
import os
import sys

import pytest

# Import jcodemunch-reindex as a module (it has a hyphen, so use importlib)
HOOK_DIR = os.path.join(os.path.dirname(__file__), "..", ".claude", "hooks")


def _import_reindex_hook():
    """Import jcodemunch-reindex.py as a module."""
    spec = importlib.util.spec_from_file_location(
        "jcodemunch_reindex",
        os.path.join(HOOK_DIR, "jcodemunch-reindex.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def reindex_hook():
    """Import and return the jcodemunch-reindex module."""
    return _import_reindex_hook()


class TestCheckDrift:
    """Tests for the check_drift function."""

    def test_get_symbol_content_verified_false_returns_true(self, reindex_hook):
        """Test 1: get_symbol with content_verified=false returns True (drift)."""
        tool_output = {
            "file_path": "tools/base.py",
            "_meta": {"content_verified": False},
        }
        assert reindex_hook.check_drift("mcp__jcodemunch__get_symbol", tool_output) is True

    def test_get_symbol_content_verified_true_returns_false(self, reindex_hook):
        """Test 2: get_symbol with content_verified=true returns False (no drift)."""
        tool_output = {
            "file_path": "tools/base.py",
            "_meta": {"content_verified": True},
        }
        assert reindex_hook.check_drift("mcp__jcodemunch__get_symbol", tool_output) is False

    def test_non_get_symbol_tool_returns_false(self, reindex_hook):
        """Test 3: search_symbols (non-get_symbol) returns False regardless."""
        tool_output = {
            "_meta": {"content_verified": False},
        }
        assert reindex_hook.check_drift("mcp__jcodemunch__search_symbols", tool_output) is False

    def test_missing_meta_returns_false(self, reindex_hook):
        """Test 4: get_symbol with no _meta returns False (graceful degradation)."""
        tool_output = {
            "file_path": "tools/base.py",
            "source": "class Tool: pass",
        }
        assert reindex_hook.check_drift("mcp__jcodemunch__get_symbol", tool_output) is False

    def test_malformed_output_string_returns_false(self, reindex_hook):
        """Test 5a: string tool_output returns False."""
        assert reindex_hook.check_drift("mcp__jcodemunch__get_symbol", "some string") is False

    def test_malformed_output_none_returns_false(self, reindex_hook):
        """Test 5b: None tool_output returns False."""
        assert reindex_hook.check_drift("mcp__jcodemunch__get_symbol", None) is False

    def test_malformed_output_empty_dict_returns_false(self, reindex_hook):
        """Test 5c: empty dict tool_output returns False."""
        assert reindex_hook.check_drift("mcp__jcodemunch__get_symbol", {}) is False

    def test_json_string_output_parsed(self, reindex_hook):
        """Test: JSON string tool_output is parsed correctly."""
        tool_output = json.dumps(
            {
                "file_path": "core/sandbox.py",
                "_meta": {"content_verified": False},
            }
        )
        assert reindex_hook.check_drift("mcp__jcodemunch__get_symbol", tool_output) is True

    def test_integration_post_tool_use_drift_emits_stderr(self, reindex_hook):
        """Test 6: full integration — PostToolUse with drifted get_symbol emits re-index recommendation."""
        event = {
            "hook_event_name": "PostToolUse",
            "project_dir": os.path.dirname(HOOK_DIR),
            "tool_name": "mcp__jcodemunch__get_symbol",
            "tool_output": {
                "file_path": "tools/base.py",
                "source": "class Tool: ...",
                "_meta": {"content_verified": False},
            },
        }

        old_stdin = sys.stdin
        old_stderr = sys.stderr
        try:
            sys.stdin = io.StringIO(json.dumps(event))
            sys.stderr = io.StringIO()
            with pytest.raises(SystemExit) as exc_info:
                reindex_hook.main()
            # Must exit 0 (advisory, never block)
            assert exc_info.value.code == 0
            stderr_output = sys.stderr.getvalue()
        finally:
            sys.stdin = old_stdin
            sys.stderr = old_stderr

        assert "drift" in stderr_output.lower() or "Drift" in stderr_output
        assert "mcp__jcodemunch__index_folder" in stderr_output
        assert "incremental" in stderr_output

    def test_integration_post_tool_use_no_drift_silent(self, reindex_hook):
        """Test: PostToolUse with content_verified=true produces no drift output."""
        event = {
            "hook_event_name": "PostToolUse",
            "project_dir": os.path.dirname(HOOK_DIR),
            "tool_name": "mcp__jcodemunch__get_symbol",
            "tool_output": {
                "file_path": "tools/base.py",
                "_meta": {"content_verified": True},
            },
        }

        old_stdin = sys.stdin
        old_stderr = sys.stderr
        try:
            sys.stdin = io.StringIO(json.dumps(event))
            sys.stderr = io.StringIO()
            with pytest.raises(SystemExit) as exc_info:
                reindex_hook.main()
            assert exc_info.value.code == 0
            stderr_output = sys.stderr.getvalue()
        finally:
            sys.stdin = old_stdin
            sys.stderr = old_stderr

        assert "drift" not in stderr_output.lower()
