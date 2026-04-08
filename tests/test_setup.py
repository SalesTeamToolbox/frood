"""Tests for setup.sh helper scripts — SETUP-01 through SETUP-05."""

import io
import json
import os
import sys
import unittest.mock as mock

import pytest

# Ensure project root is on sys.path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.jcodemunch_index import index_project
from scripts.setup_helpers import (
    _detect_project_context,
    check_health,
    generate_claude_md_section,
    generate_full_claude_md,
    generate_mcp_config,
    print_health_report,
    read_hook_metadata,
    register_hooks,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fake_venv(tmp_path):
    """Create a fake venv python so generate_mcp_config thinks venv exists.

    Creates the platform-correct path: .venv/Scripts/python.exe on Windows,
    .venv/bin/python on Linux/macOS.
    """
    import sys as _sys

    if _sys.platform == "win32":
        python_path = tmp_path / ".venv" / "Scripts" / "python.exe"
    else:
        python_path = tmp_path / ".venv" / "bin" / "python"
    python_path.parent.mkdir(parents=True, exist_ok=True)
    python_path.touch()
    return str(python_path)


def _make_hook_file(directory, filename, events, matcher=None, timeout=None):
    """Write a minimal hook file with frontmatter to directory/filename."""
    directory = os.fspath(directory)
    os.makedirs(directory, exist_ok=True)
    lines = ["#!/usr/bin/env python3\n"]
    for event in events:
        lines.append(f"# hook_event: {event}\n")
    if matcher is not None:
        lines.append(f"# hook_matcher: {matcher}\n")
    if timeout is not None:
        lines.append(f"# hook_timeout: {timeout}\n")
    lines.append('"""Hook docstring."""\n')
    lines.append("pass\n")
    path = os.path.join(directory, filename)
    with open(path, "w") as f:
        f.writelines(lines)
    return path


# ---------------------------------------------------------------------------
# TestMcpConfigGeneration
# ---------------------------------------------------------------------------


class TestMcpConfigGeneration:
    """SETUP-01: .mcp.json generated with Agent42 MCP server entry."""

    def test_generates_mcp_json_with_agent42_entry(self, tmp_path):
        """Fresh generation creates .mcp.json with agent42 server pointing to venv python."""
        venv_python = _make_fake_venv(tmp_path)
        generate_mcp_config(str(tmp_path))

        mcp_path = tmp_path / ".mcp.json"
        assert mcp_path.exists(), ".mcp.json not created"
        config = json.loads(mcp_path.read_text())
        assert "frood" in config["mcpServers"]
        assert config["mcpServers"]["frood"]["command"] == venv_python

    def test_includes_all_six_servers_when_ssh_alias_provided(self, tmp_path):
        """With SSH alias, all 6 servers appear in generated config."""
        _make_fake_venv(tmp_path)
        generate_mcp_config(str(tmp_path), ssh_alias="myserver")

        config = json.loads((tmp_path / ".mcp.json").read_text())
        servers = config["mcpServers"]
        assert len(servers) == 6, f"Expected 6 servers, got {len(servers)}: {list(servers)}"
        assert "frood-remote" in servers

    def test_omits_agent42_remote_when_no_ssh_alias(self, tmp_path):
        """Without SSH alias, agent42-remote is not in generated config."""
        _make_fake_venv(tmp_path)
        generate_mcp_config(str(tmp_path))

        config = json.loads((tmp_path / ".mcp.json").read_text())
        servers = config["mcpServers"]
        assert "frood-remote" not in servers
        assert len(servers) == 5

    def test_agent42_env_vars_set_correctly(self, tmp_path):
        """agent42 entry has FROOD_WORKSPACE, REDIS_URL, QDRANT_URL."""
        _make_fake_venv(tmp_path)
        generate_mcp_config(str(tmp_path))

        config = json.loads((tmp_path / ".mcp.json").read_text())
        env = config["mcpServers"]["frood"]["env"]
        assert env["FROOD_WORKSPACE"] == str(tmp_path)
        assert env["REDIS_URL"] == "redis://localhost:6379/0"
        assert env["QDRANT_URL"] == "http://localhost:6333"


# ---------------------------------------------------------------------------
# TestMcpConfigMerge
# ---------------------------------------------------------------------------


class TestMcpConfigMerge:
    """SETUP-01 + SETUP-04: Merge leaves existing entries untouched."""

    def test_preserves_existing_non_agent42_servers(self, tmp_path):
        """Pre-existing servers not in our set are left untouched."""
        _make_fake_venv(tmp_path)
        existing = {"mcpServers": {"my-custom-server": {"command": "node", "args": ["server.js"]}}}
        (tmp_path / ".mcp.json").write_text(json.dumps(existing))

        generate_mcp_config(str(tmp_path))

        config = json.loads((tmp_path / ".mcp.json").read_text())
        assert "my-custom-server" in config["mcpServers"]
        assert config["mcpServers"]["my-custom-server"] == {
            "command": "node",
            "args": ["server.js"],
        }

    def test_does_not_overwrite_existing_agent42_entry_with_valid_path(self, tmp_path):
        """If agent42 already exists with valid command path, skip it."""
        venv_python = _make_fake_venv(tmp_path)
        existing_entry = {
            "command": venv_python,
            "args": [str(tmp_path / "mcp_server.py")],
            "env": {"FROOD_WORKSPACE": str(tmp_path), "CUSTOM_VAR": "kept"},
        }
        existing = {"mcpServers": {"frood": existing_entry}}
        (tmp_path / ".mcp.json").write_text(json.dumps(existing))

        generate_mcp_config(str(tmp_path))

        config = json.loads((tmp_path / ".mcp.json").read_text())
        # Custom env var should still be present since entry was not replaced
        assert config["mcpServers"]["frood"]["env"].get("CUSTOM_VAR") == "kept"

    def test_replaces_agent42_entry_with_invalid_path(self, tmp_path):
        """If agent42 exists but command path is non-existent, replace it."""
        _make_fake_venv(tmp_path)
        existing = {
            "mcpServers": {
                "agent42": {
                    "command": "/nonexistent/path/to/python",
                    "args": ["mcp_server.py"],
                    "env": {},
                }
            }
        }
        (tmp_path / ".mcp.json").write_text(json.dumps(existing))

        generate_mcp_config(str(tmp_path))

        config = json.loads((tmp_path / ".mcp.json").read_text())
        cmd = config["mcpServers"]["frood"]["command"]
        assert cmd != "/nonexistent/path/to/python", "Stale path was not replaced"
        # On Windows basename is python.exe, on Linux/macOS it is python
        assert os.path.basename(cmd) in ("python", "python.exe")


# ---------------------------------------------------------------------------
# TestHookFrontmatter
# ---------------------------------------------------------------------------


class TestHookFrontmatter:
    """SETUP-02: Hook frontmatter parsing."""

    def test_reads_single_event_hook(self, tmp_path):
        """Parses # hook_event: PostToolUse from a hook file."""
        hook_path = str(tmp_path / "test_hook.py")
        with open(hook_path, "w") as f:
            f.write("#!/usr/bin/env python3\n")
            f.write("# hook_event: PostToolUse\n")
            f.write("# hook_matcher: Write|Edit\n")
            f.write("# hook_timeout: 30\n")
            f.write('"""Hook."""\n')

        result = read_hook_metadata(hook_path)
        assert len(result) == 1
        assert result[0]["event"] == "PostToolUse"
        assert result[0]["matcher"] == "Write|Edit"
        assert result[0]["timeout"] == 30

    def test_reads_multi_event_hook(self, tmp_path):
        """Parses two # hook_event: lines from jcodemunch-reindex.py."""
        hook_path = str(tmp_path / "multi_event.py")
        with open(hook_path, "w") as f:
            f.write("#!/usr/bin/env python3\n")
            f.write("# hook_event: PostToolUse\n")
            f.write("# hook_event: Stop\n")
            f.write("# hook_timeout: 10\n")
            f.write('"""Hook."""\n')

        result = read_hook_metadata(hook_path)
        assert len(result) == 2
        events = [r["event"] for r in result]
        assert "PostToolUse" in events
        assert "Stop" in events

    def test_reads_matcher(self, tmp_path):
        """Parses # hook_matcher: Write|Edit from a hook file."""
        hook_path = str(tmp_path / "hook.py")
        with open(hook_path, "w") as f:
            f.write("#!/usr/bin/env python3\n")
            f.write("# hook_event: PostToolUse\n")
            f.write("# hook_matcher: Write|Edit\n")
            f.write('"""Hook."""\n')

        result = read_hook_metadata(hook_path)
        assert result[0]["matcher"] == "Write|Edit"

    def test_reads_timeout(self, tmp_path):
        """Parses # hook_timeout: 45 from a hook file."""
        hook_path = str(tmp_path / "hook.py")
        with open(hook_path, "w") as f:
            f.write("#!/usr/bin/env python3\n")
            f.write("# hook_event: Stop\n")
            f.write("# hook_timeout: 45\n")
            f.write('"""Hook."""\n')

        result = read_hook_metadata(hook_path)
        assert result[0]["timeout"] == 45

    def test_skips_non_hook_files(self, tmp_path):
        """Files without # hook_event: are skipped (e.g., security_config.py)."""
        hook_path = str(tmp_path / "security_config.py")
        with open(hook_path, "w") as f:
            f.write("#!/usr/bin/env python3\n")
            f.write("# This is a config module, not a hook\n")
            f.write('"""Config."""\n')
            f.write("SETTING = True\n")

        result = read_hook_metadata(hook_path)
        assert result == []


# ---------------------------------------------------------------------------
# TestHookRegistration
# ---------------------------------------------------------------------------


class TestHookRegistration:
    """SETUP-02: .claude/settings.json patched with all Agent42 hooks."""

    def test_registers_all_hooks_from_frontmatter(self, tmp_path):
        """All hooks with # hook_event: lines get registered under correct event keys."""
        hooks_dir = tmp_path / ".claude" / "hooks"
        _make_hook_file(str(hooks_dir), "hook_a.py", ["PostToolUse"], matcher="Write")
        _make_hook_file(str(hooks_dir), "hook_b.py", ["Stop"])

        settings_path = tmp_path / ".claude" / "settings.json"
        settings_path.write_text("{}")

        register_hooks(str(tmp_path))

        config = json.loads(settings_path.read_text())
        hooks = config.get("hooks", {})
        assert "PostToolUse" in hooks
        assert "Stop" in hooks

    def test_hook_command_uses_absolute_path(self, tmp_path):
        """Hook command format: cd /abs/path && python .claude/hooks/script.py"""
        hooks_dir = tmp_path / ".claude" / "hooks"
        _make_hook_file(str(hooks_dir), "myhook.py", ["Stop"])

        settings_path = tmp_path / ".claude" / "settings.json"
        settings_path.write_text("{}")

        register_hooks(str(tmp_path))

        config = json.loads(settings_path.read_text())
        stop_hooks = config["hooks"]["Stop"]
        # Find the command for our hook
        all_commands = []
        for block in stop_hooks:
            for h in block.get("hooks", []):
                all_commands.append(h["command"])

        assert any(str(tmp_path) in cmd for cmd in all_commands), (
            f"Absolute path not in any command: {all_commands}"
        )

    def test_hook_timeout_from_frontmatter(self, tmp_path):
        """Timeout value matches # hook_timeout: from hook file."""
        hooks_dir = tmp_path / ".claude" / "hooks"
        _make_hook_file(str(hooks_dir), "timed_hook.py", ["Stop"], timeout=60)

        settings_path = tmp_path / ".claude" / "settings.json"
        settings_path.write_text("{}")

        register_hooks(str(tmp_path))

        config = json.loads(settings_path.read_text())
        stop_blocks = config["hooks"]["Stop"]
        timeouts = []
        for block in stop_blocks:
            for h in block.get("hooks", []):
                timeouts.append(h["timeout"])

        assert 60 in timeouts, f"Expected timeout 60, got {timeouts}"

    def test_multi_event_hook_registered_to_both_events(self, tmp_path):
        """jcodemunch-reindex.py appears under both PostToolUse and Stop."""
        hooks_dir = tmp_path / ".claude" / "hooks"
        _make_hook_file(str(hooks_dir), "dual_hook.py", ["PostToolUse", "Stop"])

        settings_path = tmp_path / ".claude" / "settings.json"
        settings_path.write_text("{}")

        register_hooks(str(tmp_path))

        config = json.loads(settings_path.read_text())
        hooks = config.get("hooks", {})
        assert "PostToolUse" in hooks, "PostToolUse not registered"
        assert "Stop" in hooks, "Stop not registered"

        # Verify dual_hook.py command appears under both events
        def find_script_in_event(event_name, script_name):
            for block in hooks.get(event_name, []):
                for h in block.get("hooks", []):
                    if script_name in h["command"]:
                        return True
            return False

        assert find_script_in_event("PostToolUse", "dual_hook.py"), "Not in PostToolUse"
        assert find_script_in_event("Stop", "dual_hook.py"), "Not in Stop"


# ---------------------------------------------------------------------------
# TestHookMerge
# ---------------------------------------------------------------------------


class TestHookMerge:
    """SETUP-02 + SETUP-04: Hook merge leaves existing entries untouched."""

    def test_preserves_existing_hook_entries(self, tmp_path):
        """Pre-existing hooks not from Agent42 are left untouched."""
        hooks_dir = tmp_path / ".claude" / "hooks"
        _make_hook_file(str(hooks_dir), "agent_hook.py", ["Stop"])

        settings_path = tmp_path / ".claude" / "settings.json"
        existing = {
            "hooks": {
                "PreToolUse": [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": "cd /other && python custom.py",
                                "timeout": 10,
                            }
                        ]
                    }
                ]
            }
        }
        settings_path.write_text(json.dumps(existing))

        register_hooks(str(tmp_path))

        config = json.loads(settings_path.read_text())
        # Pre-existing entry should still be there
        assert "PreToolUse" in config["hooks"]
        pre_blocks = config["hooks"]["PreToolUse"]
        all_commands = [h["command"] for block in pre_blocks for h in block.get("hooks", [])]
        assert any("custom.py" in cmd for cmd in all_commands), "Pre-existing hook was removed"

    def test_does_not_duplicate_already_registered_hooks(self, tmp_path):
        """Running registration twice does not create duplicate entries."""
        hooks_dir = tmp_path / ".claude" / "hooks"
        _make_hook_file(str(hooks_dir), "my_hook.py", ["Stop"])

        settings_path = tmp_path / ".claude" / "settings.json"
        settings_path.write_text("{}")

        register_hooks(str(tmp_path))
        register_hooks(str(tmp_path))

        config = json.loads(settings_path.read_text())
        stop_blocks = config["hooks"]["Stop"]
        all_commands = [h["command"] for block in stop_blocks for h in block.get("hooks", [])]

        # Count occurrences of my_hook.py
        count = sum(1 for cmd in all_commands if "my_hook.py" in cmd)
        assert count == 1, f"Hook registered {count} times instead of 1"


# ---------------------------------------------------------------------------
# TestJcodemunchIndex
# ---------------------------------------------------------------------------


class TestJcodemunchIndex:
    """SETUP-03: jcodemunch indexing via MCP JSON-RPC."""

    def test_sends_initialize_then_index_folder(self, tmp_path):
        """Script sends MCP initialize followed by tools/call index_folder."""
        # Mock subprocess.Popen to capture stdin.write calls
        written_lines = []

        mock_proc = mock.MagicMock()
        mock_proc.stdin = mock.MagicMock()

        # Capture write calls
        def capture_write(data):
            written_lines.append(data)

        mock_proc.stdin.write.side_effect = capture_write

        # Simulate stdout returning a successful index_folder response (id=2)
        success_response = (
            json.dumps({"jsonrpc": "2.0", "id": 2, "result": {"indexed": True}}) + "\n"
        )
        mock_proc.stdout = io.StringIO(success_response)

        with (
            mock.patch("subprocess.Popen", return_value=mock_proc),
            mock.patch("shutil.which", return_value="/usr/bin/uvx"),
        ):
            result = index_project(str(tmp_path))

        # Parse the written messages
        messages = []
        for line in written_lines:
            stripped = line.strip()
            if stripped:
                try:
                    messages.append(json.loads(stripped))
                except json.JSONDecodeError:
                    pass

        methods = [m.get("method") for m in messages]
        assert "initialize" in methods, f"initialize not sent; messages: {methods}"
        assert "tools/call" in methods, f"tools/call not sent; messages: {methods}"

        # Verify index_folder tool name
        tool_calls = [m for m in messages if m.get("method") == "tools/call"]
        assert any(tc["params"]["name"] == "index_folder" for tc in tool_calls)

    def test_uses_correct_project_path(self, tmp_path):
        """index_folder arguments.path is the project directory."""
        written_lines = []

        mock_proc = mock.MagicMock()
        mock_proc.stdin.write.side_effect = lambda data: written_lines.append(data)

        success_response = (
            json.dumps({"jsonrpc": "2.0", "id": 2, "result": {"indexed": True}}) + "\n"
        )
        mock_proc.stdout = io.StringIO(success_response)

        with (
            mock.patch("subprocess.Popen", return_value=mock_proc),
            mock.patch("shutil.which", return_value="/usr/bin/uvx"),
        ):
            index_project(str(tmp_path))

        messages = []
        for line in written_lines:
            stripped = line.strip()
            if stripped:
                try:
                    messages.append(json.loads(stripped))
                except json.JSONDecodeError:
                    pass

        tool_calls = [m for m in messages if m.get("method") == "tools/call"]
        assert len(tool_calls) >= 1
        path_arg = tool_calls[0]["params"]["arguments"]["path"]
        assert os.path.basename(path_arg) == os.path.basename(str(tmp_path)), (
            f"path_arg={path_arg!r} does not match tmp_path={tmp_path!s}"
        )


# ---------------------------------------------------------------------------
# TestJcodemunchIndexFailure
# ---------------------------------------------------------------------------


class TestJcodemunchIndexFailure:
    """SETUP-03: Indexing failure is warning, not hard error."""

    def test_returns_false_on_timeout(self):
        """Timeout during indexing returns False (not exception)."""
        mock_proc = mock.MagicMock()
        mock_proc.stdin = mock.MagicMock()

        # stdout never yields anything (simulates hang)
        mock_proc.stdout = iter([])

        with (
            mock.patch("subprocess.Popen", return_value=mock_proc),
            mock.patch("shutil.which", return_value="/usr/bin/uvx"),
        ):
            result = index_project("/tmp/test", timeout=1)

        assert result is False

    def test_returns_false_on_missing_uvx(self):
        """Missing uvx command returns False (not exception)."""
        with (
            mock.patch("shutil.which", return_value=None),
            mock.patch("subprocess.run", side_effect=FileNotFoundError("pip not found")),
        ):
            result = index_project("/tmp/test")

        assert result is False


# ---------------------------------------------------------------------------
# TestIdempotency
# ---------------------------------------------------------------------------


class TestIdempotency:
    """SETUP-04: Re-running does not overwrite existing configuration."""

    def test_mcp_config_idempotent(self, tmp_path):
        """Running MCP config generation twice produces identical output."""
        _make_fake_venv(tmp_path)

        generate_mcp_config(str(tmp_path))
        first = json.loads((tmp_path / ".mcp.json").read_text())

        generate_mcp_config(str(tmp_path))
        second = json.loads((tmp_path / ".mcp.json").read_text())

        assert first == second, "Second run changed .mcp.json content"

    def test_hook_registration_idempotent(self, tmp_path):
        """Running hook registration twice produces identical output."""
        hooks_dir = tmp_path / ".claude" / "hooks"
        _make_hook_file(str(hooks_dir), "idem_hook.py", ["Stop"], timeout=30)

        settings_path = tmp_path / ".claude" / "settings.json"
        settings_path.write_text("{}")

        register_hooks(str(tmp_path))
        first = json.loads(settings_path.read_text())

        register_hooks(str(tmp_path))
        second = json.loads(settings_path.read_text())

        assert first == second, "Second registration changed settings.json content"


# ---------------------------------------------------------------------------
# TestHealthReport
# ---------------------------------------------------------------------------


class TestHealthReport:
    """SETUP-05: Post-setup health report."""

    def test_reports_all_five_services(self):
        """Health report checks MCP server, jcodemunch, Qdrant, Redis, Claude Code CLI."""
        # Mock all subprocess and urllib calls to return unhealthy
        with (
            mock.patch("subprocess.run", side_effect=FileNotFoundError("not found")),
            mock.patch("urllib.request.urlopen", side_effect=OSError("refused")),
        ):
            results = check_health("/tmp/test")

        names = [r["name"] for r in results]
        assert "MCP Server" in names
        assert "jcodemunch" in names
        assert "Qdrant" in names
        assert "Redis" in names
        assert "Claude Code CLI" in names
        assert len(results) == 5

    def test_pass_format(self, capsys):
        """Healthy service shows [✓] ServiceName: healthy."""
        healthy = [
            {
                "name": "MCP Server",
                "healthy": True,
                "detail": "healthy",
                "fix": "",
                "level": "error",
            }
        ]
        print_health_report(healthy)
        captured = capsys.readouterr()
        assert "[✓]" in captured.out
        assert "MCP Server" in captured.out

    def test_fail_format_with_fix_hint(self, capsys):
        """Unhealthy service shows [✗] ServiceName: reason → Fix: command."""
        unhealthy = [
            {
                "name": "Qdrant",
                "healthy": False,
                "detail": "Connection refused",
                "fix": "Start Qdrant",
                "level": "warn",
            }
        ]
        print_health_report(unhealthy)
        captured = capsys.readouterr()
        assert "[✗]" in captured.out
        assert "Fix:" in captured.out
        assert "Qdrant" in captured.out

    def test_summary_line(self, capsys):
        """Report ends with 'Setup complete. X/5 services healthy.'"""
        results = [
            {
                "name": "MCP Server",
                "healthy": True,
                "detail": "healthy",
                "fix": "",
                "level": "error",
            },
            {
                "name": "jcodemunch",
                "healthy": False,
                "detail": "not found",
                "fix": "install uv",
                "level": "error",
            },
            {
                "name": "Qdrant",
                "healthy": False,
                "detail": "refused",
                "fix": "start qdrant",
                "level": "warn",
            },
            {"name": "Redis", "healthy": True, "detail": "healthy", "fix": "", "level": "warn"},
            {
                "name": "Claude Code CLI",
                "healthy": True,
                "detail": "healthy",
                "fix": "",
                "level": "error",
            },
        ]
        print_health_report(results)
        captured = capsys.readouterr()
        assert "services healthy" in captured.out
        assert "3/5" in captured.out


# ---------------------------------------------------------------------------
# TestClaudeMdGeneration
# ---------------------------------------------------------------------------


class TestClaudeMdGeneration:
    """INTEG-01 through INTEG-03: CLAUDE.md memory section generation."""

    def test_creates_claude_md_when_absent(self, tmp_path):
        """Creates CLAUDE.md with markers and frood_memory when no file exists."""
        generate_claude_md_section(str(tmp_path))
        claude_md = tmp_path / "CLAUDE.md"
        assert claude_md.exists()
        content = claude_md.read_text()
        assert "<!-- BEGIN FROOD MEMORY -->" in content
        assert "<!-- END FROOD MEMORY -->" in content
        assert "frood_memory" in content

    def test_appends_to_existing_claude_md(self, tmp_path):
        """Appends managed section to existing CLAUDE.md, preserving user content."""
        (tmp_path / "CLAUDE.md").write_text("# My Project\n\nExisting content.\n")
        generate_claude_md_section(str(tmp_path))
        content = (tmp_path / "CLAUDE.md").read_text()
        assert "My Project" in content
        assert "Existing content." in content
        assert "frood_memory" in content

    def test_idempotent_on_rerun(self, tmp_path):
        """Calling generate_claude_md_section twice produces identical file content."""
        generate_claude_md_section(str(tmp_path))
        first = (tmp_path / "CLAUDE.md").read_text()
        generate_claude_md_section(str(tmp_path))
        second = (tmp_path / "CLAUDE.md").read_text()
        assert first == second

    def test_replaces_managed_section_on_rerun(self, tmp_path):
        """Old content between markers is replaced; new template content is present."""
        (tmp_path / "CLAUDE.md").write_text(
            "# Project\n\n<!-- BEGIN FROOD MEMORY -->\nOLD CONTENT\n<!-- END FROOD MEMORY -->\n"
        )
        generate_claude_md_section(str(tmp_path))
        content = (tmp_path / "CLAUDE.md").read_text()
        assert "OLD CONTENT" not in content
        assert "frood_memory" in content

    def test_preserves_content_outside_markers(self, tmp_path):
        """Content before and after markers is preserved; only inside is replaced."""
        (tmp_path / "CLAUDE.md").write_text(
            "# My Project\n\nBefore section.\n\n"
            "<!-- BEGIN FROOD MEMORY -->\nOLD\n<!-- END FROOD MEMORY -->\n\n"
            "After section.\n"
        )
        generate_claude_md_section(str(tmp_path))
        content = (tmp_path / "CLAUDE.md").read_text()
        assert "Before section." in content
        assert "After section." in content
        assert "OLD" not in content

    def test_template_contains_search_instruction(self, tmp_path):
        """Generated CLAUDE.md contains action=\"search\" — verifies INTEG-01."""
        generate_claude_md_section(str(tmp_path))
        content = (tmp_path / "CLAUDE.md").read_text()
        assert 'action="search"' in content

    def test_template_contains_store_and_log(self, tmp_path):
        """Generated CLAUDE.md contains action=\"store\" and action=\"log\" — verifies INTEG-02."""
        generate_claude_md_section(str(tmp_path))
        content = (tmp_path / "CLAUDE.md").read_text()
        assert 'action="store"' in content
        assert 'action="log"' in content


# ---------------------------------------------------------------------------
# TestMcpHealthProbe
# ---------------------------------------------------------------------------


class TestMcpHealthProbe:
    """SETUP-05: MCP server health check via --health flag."""

    def test_health_flag_exits_zero_on_success(self):
        """python mcp_server.py --health exits 0 when server can initialize."""
        pytest.skip("Integration test — run manually")

    def test_health_flag_exits_nonzero_on_failure(self):
        """python mcp_server.py --health exits 1 on import/config error."""
        pytest.skip("Integration test — run manually")


# ---------------------------------------------------------------------------
# TestWindowsCompat
# ---------------------------------------------------------------------------


class TestWindowsCompat:
    """SETUP-06: Windows Git Bash compatibility — platform-aware venv paths."""

    def test_venv_python_returns_scripts_on_win32(self):
        """On win32, _venv_python returns .venv/Scripts/python.exe path."""
        from scripts.setup_helpers import _venv_python

        with mock.patch("scripts.setup_helpers.sys") as mock_sys:
            mock_sys.platform = "win32"
            result = _venv_python("/project")

        assert result == os.path.join("/project", ".venv", "Scripts", "python.exe")

    def test_venv_python_returns_bin_on_linux(self):
        """On linux, _venv_python returns .venv/bin/python path."""
        from scripts.setup_helpers import _venv_python

        with mock.patch("scripts.setup_helpers.sys") as mock_sys:
            mock_sys.platform = "linux"
            result = _venv_python("/project")

        assert result == os.path.join("/project", ".venv", "bin", "python")

    def test_mcp_config_uses_venv_python_win32(self, tmp_path):
        """On win32, generate_mcp_config writes .mcp.json with Scripts/python.exe path."""
        # Create the Windows-style venv python path
        scripts_python = tmp_path / ".venv" / "Scripts" / "python.exe"
        scripts_python.parent.mkdir(parents=True, exist_ok=True)
        scripts_python.touch()

        with mock.patch("scripts.setup_helpers.sys") as mock_sys:
            mock_sys.platform = "win32"
            generate_mcp_config(str(tmp_path))

        config = json.loads((tmp_path / ".mcp.json").read_text())
        command = config["mcpServers"]["frood"]["command"]
        assert "Scripts" in command and "python.exe" in command, (
            f"Expected Scripts/python.exe in command, got: {command}"
        )

    def test_mcp_config_uses_venv_python_linux(self, tmp_path):
        """On linux, generate_mcp_config writes .mcp.json with .venv/bin/python path."""
        # Create the Linux-style venv python path
        bin_python = tmp_path / ".venv" / "bin" / "python"
        bin_python.parent.mkdir(parents=True, exist_ok=True)
        bin_python.touch()

        with mock.patch("scripts.setup_helpers.sys") as mock_sys:
            mock_sys.platform = "linux"
            generate_mcp_config(str(tmp_path))

        config = json.loads((tmp_path / ".mcp.json").read_text())
        command = config["mcpServers"]["frood"]["command"]
        # Normalize to forward slashes for cross-platform comparison
        command_normalized = command.replace("\\", "/")
        assert ".venv/bin/python" in command_normalized, (
            f"Expected .venv/bin/python in command, got: {command}"
        )

    def test_health_check_uses_platform_venv_path(self, tmp_path):
        """check_health calls subprocess with platform-correct venv python path."""
        captured_calls = []

        def capture_run(args, **kwargs):
            captured_calls.append(args)
            result = mock.MagicMock()
            result.returncode = 0
            result.stderr = b""
            return result

        with (
            mock.patch("scripts.setup_helpers.sys") as mock_sys,
            mock.patch("subprocess.run", side_effect=capture_run),
            mock.patch("urllib.request.urlopen", side_effect=OSError("refused")),
        ):
            mock_sys.platform = "win32"
            check_health(str(tmp_path))

        # Find the MCP server call (first subprocess.run call with venv python)
        mcp_calls = [c for c in captured_calls if len(c) >= 1 and "mcp_server" in str(c)]
        assert len(mcp_calls) >= 1, f"No MCP server call found in: {captured_calls}"
        mcp_cmd = mcp_calls[0]
        assert "Scripts" in str(mcp_cmd) and "python.exe" in str(mcp_cmd), (
            f"Expected Scripts/python.exe in MCP call, got: {mcp_cmd}"
        )


# ---------------------------------------------------------------------------
# TestProjectContext
# ---------------------------------------------------------------------------


class TestProjectContext:
    """SETUP-07: Project context detection for CLAUDE.md generation."""

    def test_detect_project_name_from_directory(self, tmp_path):
        """_detect_project_context returns project_name equal to directory basename."""
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(returncode=1, stdout="")
            ctx = _detect_project_context(str(tmp_path))
        assert ctx["project_name"] == tmp_path.name

    def test_detect_project_name_from_git_remote_https(self, tmp_path):
        """When git remote returns HTTPS URL, project_name is extracted from repo name."""
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(
                returncode=0, stdout="https://github.com/org/myrepo.git\n"
            )
            ctx = _detect_project_context(str(tmp_path))
        assert ctx["project_name"] == "myrepo"

    def test_detect_project_name_from_git_remote_ssh(self, tmp_path):
        """When git remote returns SSH URL, project_name is extracted from repo name."""
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(
                returncode=0, stdout="git@github.com:org/myrepo.git\n"
            )
            ctx = _detect_project_context(str(tmp_path))
        assert ctx["project_name"] == "myrepo"

    def test_detect_jcodemunch_repo_id(self, tmp_path):
        """_detect_project_context returns jcodemunch_repo as 'local/{project_name}'."""
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(
                returncode=0, stdout="https://github.com/org/coolproject.git\n"
            )
            ctx = _detect_project_context(str(tmp_path))
        assert ctx["jcodemunch_repo"] == "local/coolproject"

    def test_detect_active_workstream(self, tmp_path):
        """When .planning/workstreams/my-ws/STATE.md contains 'status: active', returns it."""
        ws_dir = tmp_path / ".planning" / "workstreams" / "my-ws"
        ws_dir.mkdir(parents=True)
        (ws_dir / "STATE.md").write_text("---\nstatus: active\n---\n# State\n")

        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(returncode=1, stdout="")
            ctx = _detect_project_context(str(tmp_path))
        assert ctx["active_workstream"] == "my-ws"

    def test_detect_no_workstream(self, tmp_path):
        """When no .planning/ directory exists, active_workstream is None."""
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(returncode=1, stdout="")
            ctx = _detect_project_context(str(tmp_path))
        assert ctx["active_workstream"] is None


# ---------------------------------------------------------------------------
# TestClaudeMdFull
# ---------------------------------------------------------------------------


def _mock_git_https(tmp_path):
    """Return a mock subprocess.run that returns an HTTPS git remote URL."""
    result = mock.MagicMock(returncode=0, stdout=f"https://github.com/org/{tmp_path.name}.git\n")
    return result


class TestClaudeMdFull:
    """SETUP-07: Full CLAUDE.md template generation with project-aware content."""

    def _run_generate(self, tmp_path):
        """Helper: run generate_full_claude_md with mocked git remote."""
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = _mock_git_https(tmp_path)
            generate_full_claude_md(str(tmp_path))

    def test_full_claude_md_creates_file_with_hook_protocol(self, tmp_path):
        """generate_full_claude_md() creates CLAUDE.md with Agent42 Hook Protocol section."""
        self._run_generate(tmp_path)
        content = (tmp_path / "CLAUDE.md").read_text()
        assert "## Agent42 Hook Protocol" in content

    def test_full_claude_md_contains_memory_instructions(self, tmp_path):
        """Generated CLAUDE.md contains frood_memory tool instructions."""
        self._run_generate(tmp_path)
        content = (tmp_path / "CLAUDE.md").read_text()
        assert "frood_memory" in content

    def test_full_claude_md_contains_project_name(self, tmp_path):
        """Generated CLAUDE.md contains the detected project name."""
        self._run_generate(tmp_path)
        content = (tmp_path / "CLAUDE.md").read_text()
        assert tmp_path.name in content

    def test_full_claude_md_contains_jcodemunch_repo(self, tmp_path):
        """Generated CLAUDE.md contains 'local/{project_name}' jcodemunch repo ID."""
        self._run_generate(tmp_path)
        content = (tmp_path / "CLAUDE.md").read_text()
        assert f"local/{tmp_path.name}" in content

    def test_full_claude_md_merges_into_existing(self, tmp_path):
        """When CLAUDE.md exists with user content, merge preserves user content."""
        (tmp_path / "CLAUDE.md").write_text("# My Existing Project\n\nUser content here.\n")
        self._run_generate(tmp_path)
        content = (tmp_path / "CLAUDE.md").read_text()
        assert "My Existing Project" in content
        assert "User content here." in content
        assert "## Agent42 Hook Protocol" in content

    def test_full_claude_md_idempotent(self, tmp_path):
        """Running generate_full_claude_md() twice produces identical file content."""
        self._run_generate(tmp_path)
        first = (tmp_path / "CLAUDE.md").read_text()
        self._run_generate(tmp_path)
        second = (tmp_path / "CLAUDE.md").read_text()
        assert first == second

    def test_full_claude_md_contains_pitfalls(self, tmp_path):
        """Generated CLAUDE.md contains a Common Pitfalls section."""
        self._run_generate(tmp_path)
        content = (tmp_path / "CLAUDE.md").read_text()
        assert "## Common Pitfalls" in content

    def test_full_claude_md_contains_testing_standards(self, tmp_path):
        """Generated CLAUDE.md contains Testing Standards or pytest reference."""
        self._run_generate(tmp_path)
        content = (tmp_path / "CLAUDE.md").read_text()
        assert "## Testing Standards" in content or "pytest" in content

    def test_full_claude_md_contains_codebase_navigation(self, tmp_path):
        """Generated CLAUDE.md contains Codebase Navigation section."""
        self._run_generate(tmp_path)
        content = (tmp_path / "CLAUDE.md").read_text()
        assert "## Codebase Navigation" in content

    def test_full_claude_md_preserves_outside_markers(self, tmp_path):
        """Content before and after existing markers is preserved during merge."""
        (tmp_path / "CLAUDE.md").write_text(
            "# Header\n\nBefore.\n\n"
            "<!-- BEGIN FROOD MEMORY -->\nOLD CONTENT\n<!-- END FROOD MEMORY -->\n\n"
            "After.\n"
        )
        self._run_generate(tmp_path)
        content = (tmp_path / "CLAUDE.md").read_text()
        assert "Before." in content
        assert "After." in content
        assert "OLD CONTENT" not in content

    def test_full_claude_md_contains_hook_table_rows(self, tmp_path):
        """Generated CLAUDE.md hook protocol includes UserPromptSubmit and Stop rows."""
        self._run_generate(tmp_path)
        content = (tmp_path / "CLAUDE.md").read_text()
        assert "UserPromptSubmit" in content
        assert "Stop" in content

    def test_full_claude_md_existing_markers_replaced(self, tmp_path):
        """Old managed block is fully replaced when markers already exist."""
        (tmp_path / "CLAUDE.md").write_text(
            "# Project\n\n<!-- BEGIN FROOD MEMORY -->\nSTALE\n<!-- END FROOD MEMORY -->\n"
        )
        self._run_generate(tmp_path)
        content = (tmp_path / "CLAUDE.md").read_text()
        assert "STALE" not in content
        assert "frood_memory" in content

    def test_full_claude_md_project_section_included(self, tmp_path):
        """Generated CLAUDE.md has a Project section with the project name."""
        self._run_generate(tmp_path)
        content = (tmp_path / "CLAUDE.md").read_text()
        assert "## Project" in content

    def test_full_claude_md_contains_quick_reference(self, tmp_path):
        """Generated CLAUDE.md contains a Quick Reference section with setup commands."""
        self._run_generate(tmp_path)
        content = (tmp_path / "CLAUDE.md").read_text()
        assert "pytest" in content or "Quick Reference" in content or "## Testing" in content
