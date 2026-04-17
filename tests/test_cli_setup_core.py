"""Safety-focused tests for core.cli_setup — CLI config wiring engines.

Exercises SAFE-01 (timestamped backups on first write), SAFE-02 (byte-identical
wire → unwire round-trip), and SAFE-03 (never touch user's other MCP servers
or settings keys).

Every test builds a realistic fixture inside ``tmp_path`` — we NEVER touch the
real ``~/.claude/settings.json`` or the user's real OpenCode projects. Adapters
accept an explicit ``root`` / ``project_paths`` argument so they can be redirected
fully.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def cc_root_with_settings(tmp_path: Path) -> Path:
    """A fake Claude Code home root with a pre-existing settings.json.

    Shape mirrors the real user file: a top-level ``other_key`` that must be
    preserved, plus an existing non-Frood MCP server entry.
    """
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    settings = claude_dir / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "other_key": "keep",
                "mcpServers": {"other-server": {"command": "node", "args": ["other.js"]}},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def cc_root_bare(tmp_path: Path) -> Path:
    """A Claude Code home root with the .claude dir but no settings.json yet.

    Uses a subdirectory so tests that request both ``cc_root_with_settings``
    and ``cc_root_bare`` don't collide on ``tmp_path/.claude``.
    """
    bare = tmp_path / "bare-home"
    bare.mkdir()
    (bare / ".claude").mkdir()
    return bare


@pytest.fixture
def opencode_project(tmp_path: Path) -> Path:
    """A realistic OpenCode project with opencode.json + AGENTS.md pre-existing."""
    proj = tmp_path / "proj1"
    proj.mkdir()
    (proj / "opencode.json").write_text(
        json.dumps(
            {
                "provider": {"openai": {"models": {"gpt-4": {}}}},
                "mcp": {"existing": {"type": "local", "command": ["echo"]}},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (proj / "AGENTS.md").write_text("# Project rules\n\nBe careful.\n", encoding="utf-8")
    return proj


@pytest.fixture
def opencode_project_no_agents(tmp_path: Path) -> Path:
    """OpenCode project WITHOUT an AGENTS.md — wire should create it."""
    proj = tmp_path / "proj-noagents"
    proj.mkdir()
    (proj / "opencode.json").write_text(
        json.dumps({"provider": {}, "mcp": {}}, indent=2) + "\n",
        encoding="utf-8",
    )
    return proj


# ---------------------------------------------------------------------------
# Claude Code adapter — safety + merge semantics
# ---------------------------------------------------------------------------
def test_claude_code_wire_creates_backup_before_first_write(cc_root_with_settings):
    """SAFE-01: first wire writes .bak-<ts>; second wire does NOT duplicate."""
    from core.cli_setup import ClaudeCodeSetup

    settings = cc_root_with_settings / ".claude" / "settings.json"
    adapter = ClaudeCodeSetup(root=cc_root_with_settings)

    # First wire — backup must appear
    result1 = adapter.wire()
    assert result1["changed"] is True
    backups = list((cc_root_with_settings / ".claude").glob("settings.json.bak-*"))
    assert len(backups) == 1, f"Expected exactly one backup, found {backups}"
    assert result1["backup"] == backups[0]

    # Settings file was modified
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert "frood" in data["mcpServers"]

    # Second wire — no new backup, and changed=False (idempotent)
    result2 = adapter.wire()
    assert result2["changed"] is False
    backups_after = list((cc_root_with_settings / ".claude").glob("settings.json.bak-*"))
    assert len(backups_after) == 1, "Second wire must not create another backup"


def test_claude_code_wire_preserves_other_keys(cc_root_with_settings):
    """SAFE-03: pre-existing keys + other MCP servers survive wiring."""
    from core.cli_setup import ClaudeCodeSetup

    settings = cc_root_with_settings / ".claude" / "settings.json"
    ClaudeCodeSetup(root=cc_root_with_settings).wire()

    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["other_key"] == "keep"
    assert "other-server" in data["mcpServers"]
    assert data["mcpServers"]["other-server"]["command"] == "node"
    assert "frood" in data["mcpServers"]


def test_claude_code_wire_idempotent(cc_root_with_settings):
    """Running wire twice yields byte-identical file content."""
    from core.cli_setup import ClaudeCodeSetup

    settings = cc_root_with_settings / ".claude" / "settings.json"
    adapter = ClaudeCodeSetup(root=cc_root_with_settings)

    adapter.wire()
    snapshot = settings.read_bytes()
    adapter.wire()
    assert settings.read_bytes() == snapshot, "wire() must be byte-identical on re-run"


def test_claude_code_unwire_byte_identical_roundtrip(cc_root_with_settings):
    """SAFE-02: wire → unwire → bytes match the original pre-wire file."""
    from core.cli_setup import ClaudeCodeSetup

    settings = cc_root_with_settings / ".claude" / "settings.json"
    original = settings.read_bytes()

    adapter = ClaudeCodeSetup(root=cc_root_with_settings)
    adapter.wire()
    adapter.unwire()

    assert settings.read_bytes() == original, "unwire must restore settings.json byte-for-byte"
    # Backup sibling must be cleaned up after a clean restore
    backups = list((cc_root_with_settings / ".claude").glob("settings.json.bak-*"))
    assert backups == [], f"Backup should be removed after restore, found: {backups}"


def test_unwire_does_not_disable_other_mcp_servers(cc_root_with_settings):
    """SAFE-03: pre-existing 'other-server' MCP entry survives wire→unwire cycle."""
    from core.cli_setup import ClaudeCodeSetup

    settings = cc_root_with_settings / ".claude" / "settings.json"
    adapter = ClaudeCodeSetup(root=cc_root_with_settings)

    adapter.wire()
    adapter.unwire()

    data = json.loads(settings.read_text(encoding="utf-8"))
    assert "other-server" in data["mcpServers"]
    assert "frood" not in data["mcpServers"]


def test_claude_code_detect_reports_state(cc_root_with_settings, cc_root_bare):
    """detect() returns {installed, wired} reflecting current state."""
    from core.cli_setup import ClaudeCodeSetup

    # With pre-existing settings, not yet wired
    adapter = ClaudeCodeSetup(root=cc_root_with_settings)
    state = adapter.detect()
    assert state["installed"] is True
    assert state["wired"] is False

    # After wire, detect reports wired=True
    adapter.wire()
    state_after = adapter.detect()
    assert state_after["installed"] is True
    assert state_after["wired"] is True

    # Bare .claude dir (no settings.json yet) — installed=True (dir exists), wired=False
    bare_state = ClaudeCodeSetup(root=cc_root_bare).detect()
    assert bare_state["installed"] is True
    assert bare_state["wired"] is False


# ---------------------------------------------------------------------------
# OpenCode adapter — opencode.json merge + AGENTS.md marker block
# ---------------------------------------------------------------------------
def test_opencode_wire_merges_into_mcp_key(opencode_project):
    """Wiring preserves provider block AND existing mcp entries; adds frood."""
    from core.cli_setup import OpenCodeSetup

    oc_json = opencode_project / "opencode.json"
    OpenCodeSetup(project_paths=[opencode_project]).wire()

    data = json.loads(oc_json.read_text(encoding="utf-8"))
    assert "existing" in data["mcp"]
    assert "frood" in data["mcp"]
    assert data["mcp"]["frood"]["type"] == "local"
    # Provider block untouched
    assert data["provider"] == {"openai": {"models": {"gpt-4": {}}}}


def test_opencode_wire_adds_agents_md_block(opencode_project):
    """Wire appends marker-delimited block to AGENTS.md; idempotent on re-run."""
    from core.cli_setup import MARKER_BEGIN, MARKER_END, OpenCodeSetup

    agents_md = opencode_project / "AGENTS.md"
    original_text = agents_md.read_text(encoding="utf-8")
    adapter = OpenCodeSetup(project_paths=[opencode_project])

    adapter.wire()
    after_first = agents_md.read_text(encoding="utf-8")
    assert MARKER_BEGIN in after_first
    assert MARKER_END in after_first
    # Pre-existing content preserved verbatim at the top
    assert after_first.startswith(original_text)

    adapter.wire()
    after_second = agents_md.read_text(encoding="utf-8")
    assert after_first == after_second, "Re-running wire must not duplicate block"
    # Exactly one marker pair
    assert after_second.count(MARKER_BEGIN) == 1
    assert after_second.count(MARKER_END) == 1


def test_opencode_wire_creates_agents_md_if_absent(opencode_project_no_agents):
    """When AGENTS.md is absent, wire creates it with just the marker block."""
    from core.cli_setup import MARKER_BEGIN, MARKER_END, OpenCodeSetup

    agents_md = opencode_project_no_agents / "AGENTS.md"
    assert not agents_md.exists()

    OpenCodeSetup(project_paths=[opencode_project_no_agents]).wire()
    assert agents_md.exists()
    text = agents_md.read_text(encoding="utf-8")
    assert MARKER_BEGIN in text
    assert MARKER_END in text


def test_opencode_unwire_removes_marker_block_only(opencode_project):
    """Text above/below the marker block is preserved byte-for-byte after unwire."""
    from core.cli_setup import OpenCodeSetup

    agents_md = opencode_project / "AGENTS.md"
    # Add some content AFTER initial, then wire (which appends markers)
    # Then add more content AFTER markers, then unwire — content before and after
    # markers must be identical byte-for-byte to their pre-unwire form.
    original = agents_md.read_text(encoding="utf-8")
    adapter = OpenCodeSetup(project_paths=[opencode_project])

    adapter.wire()
    # Simulate user adding content after the marker block
    with agents_md.open("a", encoding="utf-8") as fh:
        fh.write("\n## User's own rules\n\nStay tidy.\n")

    snapshot_extra = "\n## User's own rules\n\nStay tidy.\n"
    adapter.unwire()

    final_text = agents_md.read_text(encoding="utf-8")
    # The pre-wire content must be intact, plus whatever the user appended
    assert original in final_text
    assert snapshot_extra in final_text
    # Markers must be gone
    from core.cli_setup import MARKER_BEGIN, MARKER_END

    assert MARKER_BEGIN not in final_text
    assert MARKER_END not in final_text


def test_opencode_unwire_byte_identical_roundtrip(opencode_project):
    """SAFE-02: wire → unwire returns opencode.json + AGENTS.md to exact bytes."""
    from core.cli_setup import OpenCodeSetup

    oc_json = opencode_project / "opencode.json"
    agents_md = opencode_project / "AGENTS.md"
    orig_oc = oc_json.read_bytes()
    orig_agents = agents_md.read_bytes()

    adapter = OpenCodeSetup(project_paths=[opencode_project])
    adapter.wire()
    adapter.unwire()

    assert oc_json.read_bytes() == orig_oc, "opencode.json must round-trip byte-identical"
    assert agents_md.read_bytes() == orig_agents, "AGENTS.md must round-trip byte-identical"


def test_opencode_detect_reports_state(opencode_project):
    """detect() surfaces per-project installed + wired booleans."""
    from core.cli_setup import OpenCodeSetup

    adapter = OpenCodeSetup(project_paths=[opencode_project])
    state = adapter.detect()
    assert state["installed"] is True
    assert state["wired"] is False
    assert isinstance(state["projects"], list)
    assert len(state["projects"]) == 1
    assert state["projects"][0]["installed"] is True
    assert state["projects"][0]["wired"] is False

    adapter.wire()
    after = adapter.detect()
    assert after["wired"] is True
    assert after["projects"][0]["wired"] is True


def test_opencode_wire_backup_created_for_both_targets(opencode_project):
    """SAFE-01: first wire creates a .bak-<ts> for BOTH opencode.json and AGENTS.md."""
    from core.cli_setup import OpenCodeSetup

    OpenCodeSetup(project_paths=[opencode_project]).wire()
    oc_backups = list(opencode_project.glob("opencode.json.bak-*"))
    agents_backups = list(opencode_project.glob("AGENTS.md.bak-*"))
    assert len(oc_backups) == 1
    assert len(agents_backups) == 1
