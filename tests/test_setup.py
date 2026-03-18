"""Tests for setup.sh helper scripts — SETUP-01 through SETUP-05."""

import pytest


class TestMcpConfigGeneration:
    """SETUP-01: .mcp.json generated with Agent42 MCP server entry."""

    def test_generates_mcp_json_with_agent42_entry(self, tmp_path):
        """Fresh generation creates .mcp.json with agent42 server pointing to venv python."""
        pytest.skip("Stub — implemented in Plan 02")

    def test_includes_all_six_servers_when_ssh_alias_provided(self, tmp_path):
        """With SSH alias, all 6 servers appear in generated config."""
        pytest.skip("Stub — implemented in Plan 02")

    def test_omits_agent42_remote_when_no_ssh_alias(self, tmp_path):
        """Without SSH alias, agent42-remote is not in generated config."""
        pytest.skip("Stub — implemented in Plan 02")

    def test_agent42_env_vars_set_correctly(self, tmp_path):
        """agent42 entry has AGENT42_WORKSPACE, REDIS_URL, QDRANT_URL."""
        pytest.skip("Stub — implemented in Plan 02")


class TestMcpConfigMerge:
    """SETUP-01 + SETUP-04: Merge leaves existing entries untouched."""

    def test_preserves_existing_non_agent42_servers(self, tmp_path):
        """Pre-existing servers not in our set are left untouched."""
        pytest.skip("Stub — implemented in Plan 02")

    def test_does_not_overwrite_existing_agent42_entry_with_valid_path(self, tmp_path):
        """If agent42 already exists with valid command path, skip it."""
        pytest.skip("Stub — implemented in Plan 02")

    def test_replaces_agent42_entry_with_invalid_path(self, tmp_path):
        """If agent42 exists but command path is non-existent, replace it."""
        pytest.skip("Stub — implemented in Plan 02")


class TestHookRegistration:
    """SETUP-02: .claude/settings.json patched with all Agent42 hooks."""

    def test_registers_all_hooks_from_frontmatter(self, tmp_path):
        """All hooks with # hook_event: lines get registered under correct event keys."""
        pytest.skip("Stub — implemented in Plan 02")

    def test_hook_command_uses_absolute_path(self, tmp_path):
        """Hook command format: cd /abs/path && python .claude/hooks/script.py"""
        pytest.skip("Stub — implemented in Plan 02")

    def test_hook_timeout_from_frontmatter(self, tmp_path):
        """Timeout value matches # hook_timeout: from hook file."""
        pytest.skip("Stub — implemented in Plan 02")

    def test_multi_event_hook_registered_to_both_events(self, tmp_path):
        """jcodemunch-reindex.py appears under both PostToolUse and Stop."""
        pytest.skip("Stub — implemented in Plan 02")


class TestHookMerge:
    """SETUP-02 + SETUP-04: Hook merge leaves existing entries untouched."""

    def test_preserves_existing_hook_entries(self, tmp_path):
        """Pre-existing hooks not from Agent42 are left untouched."""
        pytest.skip("Stub — implemented in Plan 02")

    def test_does_not_duplicate_already_registered_hooks(self, tmp_path):
        """Running registration twice does not create duplicate entries."""
        pytest.skip("Stub — implemented in Plan 02")


class TestHookFrontmatter:
    """SETUP-02: Hook frontmatter parsing."""

    def test_reads_single_event_hook(self, tmp_path):
        """Parses # hook_event: PostToolUse from a hook file."""
        pytest.skip("Stub — implemented in Plan 02")

    def test_reads_multi_event_hook(self, tmp_path):
        """Parses two # hook_event: lines from jcodemunch-reindex.py."""
        pytest.skip("Stub — implemented in Plan 02")

    def test_reads_matcher(self, tmp_path):
        """Parses # hook_matcher: Write|Edit from a hook file."""
        pytest.skip("Stub — implemented in Plan 02")

    def test_reads_timeout(self, tmp_path):
        """Parses # hook_timeout: 30 from a hook file."""
        pytest.skip("Stub — implemented in Plan 02")

    def test_skips_non_hook_files(self, tmp_path):
        """Files without # hook_event: are skipped (e.g., security_config.py)."""
        pytest.skip("Stub — implemented in Plan 02")


class TestJcodemunchIndex:
    """SETUP-03: jcodemunch indexing via MCP JSON-RPC."""

    def test_sends_initialize_then_index_folder(self, tmp_path):
        """Script sends MCP initialize followed by tools/call index_folder."""
        pytest.skip("Stub — implemented in Plan 03")

    def test_uses_correct_project_path(self, tmp_path):
        """index_folder arguments.path is the project directory."""
        pytest.skip("Stub — implemented in Plan 03")


class TestJcodemunchIndexFailure:
    """SETUP-03: Indexing failure is warning, not hard error."""

    def test_returns_false_on_timeout(self):
        """Timeout during indexing returns False (not exception)."""
        pytest.skip("Stub — implemented in Plan 03")

    def test_returns_false_on_missing_uvx(self):
        """Missing uvx command returns False (not exception)."""
        pytest.skip("Stub — implemented in Plan 03")


class TestIdempotency:
    """SETUP-04: Re-running does not overwrite existing configuration."""

    def test_mcp_config_idempotent(self, tmp_path):
        """Running MCP config generation twice produces identical output."""
        pytest.skip("Stub — implemented in Plan 02")

    def test_hook_registration_idempotent(self, tmp_path):
        """Running hook registration twice produces identical output."""
        pytest.skip("Stub — implemented in Plan 02")


class TestHealthReport:
    """SETUP-05: Post-setup health report."""

    def test_reports_all_five_services(self):
        """Health report checks MCP server, jcodemunch, Qdrant, Redis, Claude Code CLI."""
        pytest.skip("Stub — implemented in Plan 03")

    def test_pass_format(self):
        """Healthy service shows [✓] ServiceName: healthy."""
        pytest.skip("Stub — implemented in Plan 03")

    def test_fail_format_with_fix_hint(self):
        """Unhealthy service shows [✗] ServiceName: reason → Fix: command."""
        pytest.skip("Stub — implemented in Plan 03")

    def test_summary_line(self):
        """Report ends with 'Setup complete. X/5 services healthy.'"""
        pytest.skip("Stub — implemented in Plan 03")


class TestMcpHealthProbe:
    """SETUP-05: MCP server health check via --health flag."""

    def test_health_flag_exits_zero_on_success(self):
        """python mcp_server.py --health exits 0 when server can initialize."""
        pytest.skip("Stub — implemented in Plan 02")

    def test_health_flag_exits_nonzero_on_failure(self):
        """python mcp_server.py --health exits 1 on import/config error."""
        pytest.skip("Stub — implemented in Plan 02")
