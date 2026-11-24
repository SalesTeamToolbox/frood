"""Phase 01 cross-CLI setup — named acceptance test suite (TEST-01..TEST-04).

This file is the locked acceptance suite named in the requirements doc (TEST-01
through TEST-04) and is graded by file name + test content. It exercises the
full feature end-to-end against realistic fixtures, covering:

- TEST-01: merge idempotency for both Claude Code and OpenCode config shapes
- TEST-02: wire → unwire round-trip byte-identical
- TEST-03: manifest parser with missing keys → defaults fill gaps
- TEST-04: ``frood_skill list`` and ``load`` return expected inventory against
  a fixture warehouse

The file complements the per-module unit suites created in plans 01-01..01-05
(``test_user_frood_dir.py``, ``test_skill_bridge.py``, ``test_cli_setup_core.py``,
``test_cli_setup_command.py``, ``test_cli_setup_dashboard.py``). Those tests
drill down into individual modules; this suite is integration-level, asserting
cross-module scenarios through the public APIs the feature exports.
"""

from __future__ import annotations

import asyncio
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


# ---------- Fake warehouse fixture (TEST-04) ----------
@pytest.fixture
def fake_warehouse(tmp_path, monkeypatch):
    """Set up a realistic warehouse + ~/.frood/ dir inside ``tmp_path``.

    Layout (per plan interfaces block):

    - ``<home>/.claude/skills-warehouse/demo-skill/SKILL.md``
    - ``<home>/.claude/commands-warehouse/demo-cmd.md``
    - ``<home>/.claude/agents-warehouse/demo-agent.md``
    - ``<home>/.frood/`` (empty — manifest auto-created by load_manifest)
    """
    _redirect_home(monkeypatch, tmp_path)
    cc = tmp_path / ".claude"
    (cc / "skills-warehouse" / "demo-skill").mkdir(parents=True)
    (cc / "skills-warehouse" / "demo-skill" / "SKILL.md").write_text(
        "---\nname: demo-skill\n---\nHello from demo.\n",
        encoding="utf-8",
    )
    (cc / "commands-warehouse").mkdir()
    (cc / "commands-warehouse" / "demo-cmd.md").write_text(
        "# demo-cmd\nDo the thing.\n",
        encoding="utf-8",
    )
    (cc / "agents-warehouse").mkdir()
    (cc / "agents-warehouse" / "demo-agent.md").write_text(
        "# demo-agent\nAgent persona.\n",
        encoding="utf-8",
    )
    (tmp_path / ".frood").mkdir()
    return tmp_path


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


# ===========================================================================
# TEST-03 — manifest parser: missing keys → defaults (regression pin for CLI-03)
# ===========================================================================
def test_manifest_missing_file_fills_defaults(tmp_path, monkeypatch):
    """CLI-03: absent ~/.frood/cli.yaml → load_manifest returns DEFAULT_MANIFEST
    and writes the file to disk so subsequent reads see the same shape."""
    from core.user_frood_dir import DEFAULT_MANIFEST, load_manifest

    _redirect_home(monkeypatch, tmp_path)

    result = load_manifest()
    assert result == DEFAULT_MANIFEST, "missing file must produce defaults"

    # load_manifest writes the defaults so users can discover + edit them.
    manifest_file = tmp_path / ".frood" / "cli.yaml"
    assert manifest_file.exists(), "first load must persist defaults to disk"


def test_manifest_partial_keys_fill_defaults(tmp_path, monkeypatch):
    """CLI-03: partial manifest on disk → missing keys backfilled from defaults.

    Writes the minimum useful manifest (claude-code disabled only) and asserts
    every other key — opencode.enabled, warehouse.include_claude_warehouse,
    warehouse.include_frood_builtins — is populated by the parser, not absent.
    """
    from core.user_frood_dir import load_manifest

    _redirect_home(monkeypatch, tmp_path)
    frood_dir = tmp_path / ".frood"
    frood_dir.mkdir()

    # Write a partial manifest directly — single top-level toggle, nothing else.
    # PyYAML is already installed in the venv, so this is a valid YAML file.
    partial_yaml = "clis:\n  claude-code:\n    enabled: false\n"
    (frood_dir / "cli.yaml").write_text(partial_yaml, encoding="utf-8")

    result = load_manifest()

    # User override wins for the key they set
    assert result["clis"]["claude-code"]["enabled"] is False

    # Every other key was filled from DEFAULT_MANIFEST
    assert result["clis"]["opencode"]["enabled"] is True
    assert result["clis"]["opencode"]["projects"] == "auto"
    assert result["warehouse"]["include_claude_warehouse"] is True
    assert result["warehouse"]["include_frood_builtins"] is True


def test_manifest_malformed_falls_back_to_defaults(tmp_path, monkeypatch):
    """CLI-03 edge: garbage on disk → parser logs a warning and returns defaults.

    Pins the "malformed file must never crash" invariant — the module's
    contract is graceful-degradation, and this suite is the last line of
    defense if a future refactor breaks that.
    """
    from core.user_frood_dir import DEFAULT_MANIFEST, load_manifest

    _redirect_home(monkeypatch, tmp_path)
    frood_dir = tmp_path / ".frood"
    frood_dir.mkdir()
    # Invalid YAML + invalid JSON — parser must fail cleanly.
    (frood_dir / "cli.yaml").write_text(
        "!! this is {unbalanced\nnonsense: [1, 2,\n",
        encoding="utf-8",
    )

    result = load_manifest()
    assert result == DEFAULT_MANIFEST, "malformed file must yield defaults"


# ===========================================================================
# TEST-04 — frood_skill list / load against a fixture warehouse
# ===========================================================================
def test_frood_skill_list_against_fixture_warehouse(fake_warehouse):
    """`SkillBridgeTool(action='list')` discovers the fixture warehouse entries.

    Asserts the three warehouse slices each contain the expected name from the
    fixture layout — this is the canonical TEST-04 shape.
    """
    from tools.skill_bridge import SkillBridgeTool

    tool = SkillBridgeTool()
    result = asyncio.run(tool.execute(action="list"))

    assert result.success, f"execute failed: {result.error}"
    inventory = json.loads(result.output)

    assert any(s["name"] == "demo-skill" for s in inventory["skills"]), (
        f"demo-skill missing from skills slice: {inventory['skills']}"
    )
    assert any(c["name"] == "demo-cmd" for c in inventory["commands"]), (
        f"demo-cmd missing from commands slice: {inventory['commands']}"
    )
    assert any(a["name"] == "demo-agent" for a in inventory["agents"]), (
        f"demo-agent missing from agents slice: {inventory['agents']}"
    )


def test_frood_skill_load_against_fixture_warehouse(fake_warehouse):
    """`SkillBridgeTool(action='load', name='demo-skill')` returns the SKILL.md body."""
    from tools.skill_bridge import SkillBridgeTool

    tool = SkillBridgeTool()
    result = asyncio.run(tool.execute(action="load", name="demo-skill"))

    assert result.success, f"load failed: {result.error}"
    loaded = json.loads(result.output)
    assert loaded["name"] == "demo-skill"
    assert "Hello from demo." in loaded["body"]
    # Source label identifies the slice — warehouse skills, not persona/builtin.
    assert "claude-warehouse" in loaded["source"]


def test_frood_skill_respects_manifest_flags(fake_warehouse):
    """warehouse.include_claude_warehouse=False hides skills/commands/agents
    even when the fixture dirs are present.

    Pins the manifest-gating contract (MCP-04) at the integration layer —
    lets us catch a regression where cli_setup silently forgets the flag.
    """
    from core.user_frood_dir import save_manifest
    from tools.skill_bridge import SkillBridgeTool

    save_manifest(
        {
            "clis": {
                "claude-code": {"enabled": True},
                "opencode": {"enabled": True, "projects": "auto"},
            },
            "warehouse": {
                "include_claude_warehouse": False,
                "include_frood_builtins": False,
            },
        }
    )

    tool = SkillBridgeTool()
    result = asyncio.run(tool.execute(action="list"))

    assert result.success, f"execute failed: {result.error}"
    inventory = json.loads(result.output)
    # All five slices empty when both flags are False
    assert inventory["skills"] == []
    assert inventory["commands"] == []
    assert inventory["agents"] == []
    assert inventory["personas"] == []
    assert inventory["frood_skills"] == []


# ===========================================================================
# Circular-import regression guard — all four public modules import cleanly
# ===========================================================================
def test_full_suite_imports_cleanly():
    """Importing every module this phase ships must not trigger circular imports.

    Each previous plan added a new public module; this test imports them all
    in one shot so any future reorg that introduces a cycle (e.g. a new
    ``tools/skill_bridge`` import from ``core/cli_setup``) fails loudly here.
    """
    # Core bootstrap modules
    # CLI command handler (Plan 04)
    from commands import CliSetupCommandHandler
    from core import cli_setup, user_frood_dir

    # MCP bridge tool
    from tools import skill_bridge

    # Sanity — these symbols are the downstream contract surface.
    assert hasattr(user_frood_dir, "load_manifest")
    assert hasattr(user_frood_dir, "save_manifest")
    assert hasattr(user_frood_dir, "DEFAULT_MANIFEST")
    assert hasattr(cli_setup, "ClaudeCodeSetup")
    assert hasattr(cli_setup, "OpenCodeSetup")
    assert hasattr(cli_setup, "detect_all")
    assert hasattr(cli_setup, "wire_cli")
    assert hasattr(cli_setup, "unwire_cli")
    assert hasattr(skill_bridge, "SkillBridgeTool")
    # CliSetupCommandHandler is an entry-point class, not a symbol on a module
    assert CliSetupCommandHandler.__name__ == "CliSetupCommandHandler"
