"""Tests for jcodemunch guidance emission in context-loader hook.

Validates that the context-loader hook emits structured jcodemunch MCP tool
call recommendations to stderr based on detected work types.
"""

import importlib
import io
import json
import os
import sys

import pytest

# Import context-loader as a module (it has a hyphen, so use importlib)
HOOK_DIR = os.path.join(os.path.dirname(__file__), "..", ".claude", "hooks")


def _import_context_loader():
    """Import context-loader.py as a module."""
    spec = importlib.util.spec_from_file_location(
        "context_loader",
        os.path.join(HOOK_DIR, "context-loader.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def context_loader():
    """Import and return the context-loader module."""
    return _import_context_loader()


class TestEmitJcodemunchGuidance:
    """Tests for the emit_jcodemunch_guidance function."""

    def test_tools_work_type_emits_search_symbols(self, context_loader):
        """Test 1: tools work type produces search_symbols guidance."""
        guidance = context_loader.emit_jcodemunch_guidance({"tools"}, repo_id="local/agent42")
        assert len(guidance) > 0
        # Should contain search_symbols with Tool query
        combined = "\n".join(guidance)
        assert "search_symbols" in combined
        assert "Tool" in combined
        assert "tools/**/*.py" in combined

    def test_security_work_type_emits_search_symbols(self, context_loader):
        """Test 2: security work type produces search_symbols guidance."""
        guidance = context_loader.emit_jcodemunch_guidance({"security"}, repo_id="local/agent42")
        assert len(guidance) > 0
        combined = "\n".join(guidance)
        assert "search_symbols" in combined
        assert "sandbox" in combined
        assert "core/**/*.py" in combined

    def test_providers_work_type_emits_get_file_outline(self, context_loader):
        """Test 3: providers work type produces get_file_outline guidance."""
        guidance = context_loader.emit_jcodemunch_guidance({"providers"}, repo_id="local/agent42")
        assert len(guidance) > 0
        combined = "\n".join(guidance)
        assert "get_file_outline" in combined
        assert "providers/registry.py" in combined

    def test_no_work_types_returns_empty(self, context_loader):
        """Test 4: empty work types returns empty list."""
        guidance = context_loader.emit_jcodemunch_guidance(set(), repo_id="local/agent42")
        assert guidance == []

    def test_multiple_work_types_combined_no_duplicates(self, context_loader):
        """Test 5: multiple work types produce combined guidance without duplicates."""
        guidance = context_loader.emit_jcodemunch_guidance(
            {"tools", "security", "providers"}, repo_id="local/agent42"
        )
        assert len(guidance) > 0
        # Should have items from all three work types
        combined = "\n".join(guidance)
        assert "tools/**/*.py" in combined
        assert "core/**/*.py" in combined
        assert "providers/registry.py" in combined
        # Check no exact duplicates (same string repeated)
        assert len(guidance) == len(set(guidance))

    def test_repo_id_injected_into_guidance(self, context_loader):
        """Test: repo_id parameter is injected into guidance strings."""
        guidance = context_loader.emit_jcodemunch_guidance({"tools"}, repo_id="custom/repo")
        combined = "\n".join(guidance)
        assert "custom/repo" in combined
        assert "local/agent42" not in combined

    def test_all_eight_work_types_have_guidance(self, context_loader):
        """Test: at least 8 work types produce guidance."""
        work_types_with_guidance = 0
        for wt in [
            "tools",
            "security",
            "providers",
            "config",
            "dashboard",
            "memory",
            "skills",
            "testing",
        ]:
            guidance = context_loader.emit_jcodemunch_guidance({wt}, repo_id="local/agent42")
            if len(guidance) > 0:
                work_types_with_guidance += 1
        assert work_types_with_guidance >= 8

    def test_main_integration_emits_jcodemunch_to_stderr(self, context_loader):
        """Test 6: full main() integration test with jcodemunch guidance in stderr."""
        event = {
            "hook_event_name": "UserPromptSubmit",
            "project_dir": os.path.dirname(HOOK_DIR),
            "user_prompt": "fix the shell tool",
        }

        # Capture stderr
        old_stdin = sys.stdin
        old_stderr = sys.stderr
        try:
            sys.stdin = io.StringIO(json.dumps(event))
            sys.stderr = io.StringIO()
            with pytest.raises(SystemExit) as exc_info:
                context_loader.main()
            assert exc_info.value.code == 0
            stderr_output = sys.stderr.getvalue()
        finally:
            sys.stdin = old_stdin
            sys.stderr = old_stderr

        # "fix the shell tool" should detect "tools" work type and emit guidance
        assert "jcodemunch" in stderr_output
        assert "mcp__jcodemunch__search_symbols" in stderr_output
