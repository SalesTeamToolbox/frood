"""Tests for SkillBridgeTool — the `frood_skill` MCP cross-CLI bridge.

Covers:
  - action="list" returns the five-key inventory dict
  - Missing warehouse directories degrade to empty slices (no crash)
  - warehouse.include_claude_warehouse=False → warehouse categories empty
  - warehouse.include_frood_builtins=False → personas + frood_skills empty
  - action="load" returns the markdown body for a real warehouse entry
  - action="load" on a missing name returns an error ToolResult
  - action="load" rejects path-traversal names
  - SkillBridgeTool is registered in mcp_server._build_registry with tool name "skill"
    (which becomes "frood_skill" after the MCP prefix is applied)

All filesystem-facing tests redirect Path.home() to a tmp_path via monkeypatch so
the real `~/.claude/*-warehouse/` dirs aren't touched and tests pass on Windows.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _redirect_home(monkeypatch, tmp_path: Path) -> Path:
    """Force Path.home() → tmp_path for the duration of the test."""
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    return tmp_path


def _make_warehouse_fixtures(home: Path) -> None:
    """Create a realistic skills/commands/agents warehouse under `home/.claude/*-warehouse/`."""
    skills = home / ".claude" / "skills-warehouse" / "demo"
    skills.mkdir(parents=True, exist_ok=True)
    (skills / "SKILL.md").write_text("# Demo skill\n\nhello world", encoding="utf-8")

    commands = home / ".claude" / "commands-warehouse"
    commands.mkdir(parents=True, exist_ok=True)
    (commands / "demo-cmd.md").write_text("# demo-cmd\n\nA demo command.", encoding="utf-8")

    agents = home / ".claude" / "agents-warehouse"
    agents.mkdir(parents=True, exist_ok=True)
    (agents / "demo-agent.md").write_text("# demo-agent\n\nA demo agent.", encoding="utf-8")


# ---------------------------------------------------------------------------
# Tests — action="list"
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_list_returns_five_keys(monkeypatch, tmp_path):
    """`action="list"` returns a JSON dict with all five inventory categories."""
    from tools.skill_bridge import SkillBridgeTool

    home = _redirect_home(monkeypatch, tmp_path)
    _make_warehouse_fixtures(home)

    tool = SkillBridgeTool()
    result = await tool.execute(action="list")

    assert result.success is True, result.error
    payload = json.loads(result.output)
    for key in ("skills", "commands", "agents", "personas", "frood_skills"):
        assert key in payload, f"missing key {key!r} in list output: {payload}"
        assert isinstance(payload[key], list)


@pytest.mark.asyncio
async def test_missing_warehouse_returns_empty_slices(monkeypatch, tmp_path):
    """No `~/.claude/*-warehouse/` dirs anywhere → warehouse slices empty, no crash (MCP-05)."""
    from tools.skill_bridge import SkillBridgeTool

    _redirect_home(monkeypatch, tmp_path)
    # Intentionally: no warehouse fixtures at all.

    tool = SkillBridgeTool()
    result = await tool.execute(action="list")

    assert result.success is True, result.error
    payload = json.loads(result.output)
    assert payload["skills"] == []
    assert payload["commands"] == []
    assert payload["agents"] == []
    # Built-ins may still be non-empty (they ship with Frood).


@pytest.mark.asyncio
async def test_manifest_disables_claude_warehouse(monkeypatch, tmp_path):
    """warehouse.include_claude_warehouse=False → skills/commands/agents empty even with dirs present."""
    from core.user_frood_dir import save_manifest
    from tools.skill_bridge import SkillBridgeTool

    home = _redirect_home(monkeypatch, tmp_path)
    _make_warehouse_fixtures(home)

    save_manifest(
        {
            "clis": {"claude-code": {"enabled": True}, "opencode": {"enabled": True}},
            "warehouse": {
                "include_claude_warehouse": False,
                "include_frood_builtins": True,
            },
        }
    )

    tool = SkillBridgeTool()
    result = await tool.execute(action="list")

    assert result.success is True
    payload = json.loads(result.output)
    assert payload["skills"] == []
    assert payload["commands"] == []
    assert payload["agents"] == []


@pytest.mark.asyncio
async def test_manifest_disables_builtins(monkeypatch, tmp_path):
    """warehouse.include_frood_builtins=False → personas and frood_skills empty."""
    from core.user_frood_dir import save_manifest
    from tools.skill_bridge import SkillBridgeTool

    _redirect_home(monkeypatch, tmp_path)

    save_manifest(
        {
            "clis": {"claude-code": {"enabled": True}, "opencode": {"enabled": True}},
            "warehouse": {
                "include_claude_warehouse": True,
                "include_frood_builtins": False,
            },
        }
    )

    tool = SkillBridgeTool()
    result = await tool.execute(action="list")

    assert result.success is True
    payload = json.loads(result.output)
    assert payload["personas"] == []
    assert payload["frood_skills"] == []


# ---------------------------------------------------------------------------
# Tests — action="load"
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_load_warehouse_skill(monkeypatch, tmp_path):
    """`action="load" name="demo"` returns the SKILL.md body for a warehoused skill."""
    from tools.skill_bridge import SkillBridgeTool

    home = _redirect_home(monkeypatch, tmp_path)
    _make_warehouse_fixtures(home)

    tool = SkillBridgeTool()
    result = await tool.execute(action="load", name="demo")

    assert result.success is True, result.error
    payload = json.loads(result.output)
    assert payload["name"] == "demo"
    assert "hello world" in payload["body"]
    assert "claude-warehouse" in payload["source"]


@pytest.mark.asyncio
async def test_load_not_found_returns_error(monkeypatch, tmp_path):
    """`action="load"` on an unknown name returns ToolResult(success=False)."""
    from tools.skill_bridge import SkillBridgeTool

    _redirect_home(monkeypatch, tmp_path)

    tool = SkillBridgeTool()
    result = await tool.execute(action="load", name="nonexistent-xyz-123")

    assert result.success is False
    assert "not found" in result.error.lower()


@pytest.mark.asyncio
async def test_load_rejects_path_traversal(monkeypatch, tmp_path):
    """`action="load" name="../../etc/passwd"` must be rejected as invalid."""
    from tools.skill_bridge import SkillBridgeTool

    _redirect_home(monkeypatch, tmp_path)

    tool = SkillBridgeTool()
    result = await tool.execute(action="load", name="../../etc/passwd")

    assert result.success is False
    assert "invalid name" in result.error.lower()

    # Also reject forward-slash and backslash forms.
    for bad in ("foo/bar", "foo\\bar"):
        r = await tool.execute(action="load", name=bad)
        assert r.success is False, f"{bad!r} should be rejected"
        assert "invalid name" in r.error.lower()


@pytest.mark.asyncio
async def test_load_without_name_returns_error(monkeypatch, tmp_path):
    """`action="load"` without a name kwarg must fail cleanly (not crash)."""
    from tools.skill_bridge import SkillBridgeTool

    _redirect_home(monkeypatch, tmp_path)

    tool = SkillBridgeTool()
    result = await tool.execute(action="load")

    assert result.success is False
    assert "name" in result.error.lower()


# ---------------------------------------------------------------------------
# Tests — MCP server registration (Task 2)
# ---------------------------------------------------------------------------
def test_registered_in_mcp_server():
    """SkillBridgeTool must be registered in `_build_registry` under the name "skill".

    After the MCP prefix ("frood") is applied by `to_mcp_schema`, the final
    tool name visible to MCP clients becomes "frood_skill" (MCP-01 locked).
    """
    from mcp_server import _build_registry

    registry = _build_registry()
    names = [t["name"] for t in registry.list_tools()]
    assert "skill" in names, f"`skill` tool not found in MCP registry; got: {names}"
