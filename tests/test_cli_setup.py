"""Phase 01 cross-CLI setup — named acceptance test suite (TEST-01..TEST-04).

This file is the locked acceptance suite named in the requirements doc (TEST-01
through TEST-04) and is graded by file name + test content. It exercises the
full feature end-to-end against realistic fixtures.

Task 1 coverage (this commit):
- TEST-01: merge idempotency for both Claude Code and OpenCode config shapes
- TEST-02: wire → unwire round-trip byte-identical

Task 2 (added in the next commit) extends this file with TEST-03 (manifest
defaults) + TEST-04 (``frood_skill`` list/load) plus a circular-import guard.

The file complements the per-module unit suites created in plans 01-01..01-05
(``test_user_frood_dir.py``, ``test_skill_bridge.py``, ``test_cli_setup_core.py``,
``test_cli_setup_command.py``, ``test_cli_setup_dashboard.py``). Those tests
drill down into individual modules; this suite is integration-level, asserting
cross-module scenarios through the public APIs the feature exports.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Shared helpers + fixtures
# ---------------------------------------------------------------------------
def _sha(p: Path) -> str:
    """SHA-256 of the file contents (bytes, not text)."""
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _redirect_home(monkeypatch, tmp_path: Path) -> Path:
    """Force Path.home() → tmp_path for this test's duration.

    Uses ``classmethod`` form because ``Path.home`` is a classmethod on Path,
    and monkeypatching it as a plain lambda would lose the bound-cls behaviour
    on Windows where HOMEDRIVE+HOMEPATH is consulted internally by some paths.
    """
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    return tmp_path


# ---------- Claude Code fixture ----------
@pytest.fixture
def cc_fixture(tmp_path, monkeypatch):
    """Realistic ``~/.claude/settings.json`` pre-wire fixture.

    Matches the shape the plan calls out verbatim (env, model, permissions,
    plus a pre-existing jcodemunch MCP server) so the merge + round-trip
    assertions are exercised against something a real user could have on disk.
    """
    _redirect_home(monkeypatch, tmp_path)
    claude = tmp_path / ".claude"
    claude.mkdir()
    settings = claude / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "env": {"CC_TELEMETRY": "off"},
                "model": "claude-sonnet-4-6-20260217",
                "mcpServers": {"jcodemunch": {"command": "node", "args": ["jcodemunch.js"]}},
                "permissions": {"allow": ["Bash", "Read"]},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return settings


# ---------- OpenCode fixture ----------
@pytest.fixture
def opencode_fixture(tmp_path):
    """Realistic ``opencode.json`` + ``AGENTS.md`` pre-wire fixture.

    Matches the shape from the plan's interfaces block: provider, instructions,
    an existing MCP server, server block, and a real AGENTS.md body.
    """
    proj = tmp_path / "proj1"
    proj.mkdir()
    (proj / "opencode.json").write_text(
        json.dumps(
            {
                "provider": {"openai": {"models": {"gpt-4": {"temperature": 0.2}}}},
                "instructions": ["AGENTS.md"],
                "mcp": {
                    "some-existing": {
                        "type": "local",
                        "command": ["echo", "hi"],
                    }
                },
                "server": {"host": "localhost"},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (proj / "AGENTS.md").write_text(
        "# Project conventions\n\nFollow the project style guide. Be concise.\n",
        encoding="utf-8",
    )
    return proj


@pytest.fixture
def opencode_fixture_no_agents(tmp_path):
    """OpenCode project whose AGENTS.md does NOT exist pre-wire.

    Validates the ``wire creates AGENTS.md → unwire deletes it`` pair — the
    byte-identical round-trip for this case means ``AGENTS.md.exists()`` is
    ``False`` both before wire and after unwire.
    """
    proj = tmp_path / "proj-fresh"
    proj.mkdir()
    (proj / "opencode.json").write_text(
        json.dumps({"provider": {}, "mcp": {}}, indent=2),
        encoding="utf-8",
    )
    return proj


# ===========================================================================
# TEST-01 — merge idempotency for both Claude Code and OpenCode config shapes
# ===========================================================================
def test_claude_code_merge_idempotent(cc_fixture):
    """Wiring Claude Code twice is a no-op on the second run.

    Hash of ``settings.json`` after the first wire MUST equal the hash after
    the second wire — no new MCP entry, no shuffled keys, no added whitespace.
    """
    from core.cli_setup import ClaudeCodeSetup

    settings = cc_fixture
    adapter = ClaudeCodeSetup(root=settings.parent.parent)

    adapter.wire()
    sha_after_first = _sha(settings)

    result2 = adapter.wire()
    assert result2.get("changed") is False, f"second wire should be no-op: {result2}"
    assert _sha(settings) == sha_after_first, "second wire must not change bytes"


def test_claude_code_merge_preserves_non_frood_keys(cc_fixture):
    """env, model, permissions, and the jcodemunch MCP entry all survive wire."""
    from core.cli_setup import ClaudeCodeSetup

    settings = cc_fixture
    ClaudeCodeSetup(root=settings.parent.parent).wire()

    data = json.loads(settings.read_text(encoding="utf-8"))

    assert data["env"] == {"CC_TELEMETRY": "off"}
    assert data["model"] == "claude-sonnet-4-6-20260217"
    assert data["permissions"] == {"allow": ["Bash", "Read"]}
    # Pre-existing MCP server is still there + frood was added alongside
    assert "jcodemunch" in data["mcpServers"]
    assert data["mcpServers"]["jcodemunch"] == {
        "command": "node",
        "args": ["jcodemunch.js"],
    }
    assert "frood" in data["mcpServers"]


def test_opencode_merge_idempotent(opencode_fixture):
    """Wiring OpenCode twice is a no-op: opencode.json AND AGENTS.md hashes stable."""
    from core.cli_setup import OpenCodeSetup

    oj = opencode_fixture / "opencode.json"
    am = opencode_fixture / "AGENTS.md"
    adapter = OpenCodeSetup(project_paths=[opencode_fixture])

    adapter.wire()
    sha_oj_first = _sha(oj)
    sha_am_first = _sha(am)

    result2 = adapter.wire()
    assert result2.get("changed") is False, f"second wire should be no-op: {result2}"
    assert _sha(oj) == sha_oj_first, "opencode.json bytes drifted on second wire"
    assert _sha(am) == sha_am_first, "AGENTS.md bytes drifted on second wire"


def test_opencode_merge_preserves_providers(opencode_fixture):
    """provider / instructions / server / pre-existing mcp entry all survive wire."""
    from core.cli_setup import OpenCodeSetup

    oj = opencode_fixture / "opencode.json"
    OpenCodeSetup(project_paths=[opencode_fixture]).wire()

    data = json.loads(oj.read_text(encoding="utf-8"))

    # Deep-equal subtrees the user cared about
    assert data["provider"] == {"openai": {"models": {"gpt-4": {"temperature": 0.2}}}}
    assert data["instructions"] == ["AGENTS.md"]
    assert data["server"] == {"host": "localhost"}
    # Existing MCP entry preserved exactly; frood added alongside
    assert data["mcp"]["some-existing"] == {
        "type": "local",
        "command": ["echo", "hi"],
    }
    assert "frood" in data["mcp"]


# ===========================================================================
# TEST-02 — wire → unwire byte-identical round-trip (both CLI shapes)
# ===========================================================================
def test_claude_code_roundtrip_byte_identical(cc_fixture):
    """SAFE-02: wire → unwire → settings.json bytes match pre-wire exactly."""
    from core.cli_setup import ClaudeCodeSetup

    settings = cc_fixture
    orig = settings.read_bytes()

    adapter = ClaudeCodeSetup(root=settings.parent.parent)
    adapter.wire()
    assert settings.read_bytes() != orig, "wire must actually modify settings.json"

    adapter.unwire()
    assert settings.read_bytes() == orig, "unwire must restore byte-identical"

    # The backup sibling must be cleaned up after a successful restore.
    backups = list(settings.parent.glob("settings.json.bak-*"))
    assert backups == [], f"backup should be removed after unwire: {backups}"


def test_opencode_roundtrip_byte_identical(opencode_fixture):
    """Both opencode.json AND AGENTS.md round-trip byte-identical through wire/unwire."""
    from core.cli_setup import OpenCodeSetup

    oj = opencode_fixture / "opencode.json"
    am = opencode_fixture / "AGENTS.md"
    orig_oj = oj.read_bytes()
    orig_am = am.read_bytes()

    adapter = OpenCodeSetup(project_paths=[opencode_fixture])
    adapter.wire()
    assert oj.read_bytes() != orig_oj, "wire must modify opencode.json"
    assert am.read_bytes() != orig_am, "wire must modify AGENTS.md"

    adapter.unwire()
    assert oj.read_bytes() == orig_oj, "opencode.json not byte-identical after unwire"
    assert am.read_bytes() == orig_am, "AGENTS.md not byte-identical after unwire"


def test_opencode_wire_without_agents_md_creates_and_removes(opencode_fixture_no_agents):
    """When AGENTS.md is absent pre-wire, wire creates it and unwire removes it.

    This is the byte-identical round-trip for the "file did not exist" case —
    a missing file is the canonical pre-state and unwire must return to it.
    """
    from core.cli_setup import MARKER_BEGIN, MARKER_END, OpenCodeSetup

    am = opencode_fixture_no_agents / "AGENTS.md"
    assert not am.exists(), "fixture sanity: AGENTS.md must be absent pre-wire"

    adapter = OpenCodeSetup(project_paths=[opencode_fixture_no_agents])
    adapter.wire()

    assert am.exists(), "wire must create AGENTS.md when absent"
    created = am.read_text(encoding="utf-8")
    assert MARKER_BEGIN in created
    assert MARKER_END in created

    adapter.unwire()
    assert not am.exists(), "unwire must delete AGENTS.md when wire created it"
