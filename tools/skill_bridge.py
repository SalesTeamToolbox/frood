"""`frood_skill` MCP bridge — on-demand inventory + loader for cross-CLI parity.

Claude Code users drive their workflows through `/use` + a warehouse of skills,
commands, and agents in `~/.claude/*-warehouse/`. OpenCode (and other MCP-capable
CLIs) have no native equivalent. This tool exposes the same inventory via MCP so
every CLI can reach the warehouse on-demand without paying the context cost of
loading it all up front.

Exposed actions:
  * ``action="list"``   — returns a JSON dict with five inventory slices:
    ``{skills, commands, agents, personas, frood_skills}``.
  * ``action="load"``   — returns the full markdown/config body for a single
    named item (first match wins across all five slices).

Both actions honour two flags from ``~/.frood/cli.yaml``:
  * ``warehouse.include_claude_warehouse`` (default True) — gates the three
    warehouse slices (skills, commands, agents).
  * ``warehouse.include_frood_builtins``   (default True) — gates personas and
    frood_skills (Frood's built-in slice).

Every filesystem-facing read is wrapped so a missing directory degrades to an
empty slice rather than crashing (MCP-05). The tool registers under the name
``skill``; ``to_mcp_schema`` prefixes it with ``frood_`` so MCP clients see the
final name ``frood_skill`` (MCP-01 locked).
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from tools.base import Tool, ToolResult

logger = logging.getLogger("frood.tools.skill_bridge")


# ---------------------------------------------------------------------------
# Source-category labels (used in both `list` entries and `load` responses)
# ---------------------------------------------------------------------------
_SRC_SKILLS = "claude-warehouse/skills"
_SRC_COMMANDS = "claude-warehouse/commands"
_SRC_AGENTS = "claude-warehouse/agents"
_SRC_PERSONAS = "frood-builtin/personas"
_SRC_FROOD_SKILLS = "frood-builtin/skills"


class SkillBridgeTool(Tool):
    """MCP bridge exposing Claude Code warehouse + Frood built-ins on-demand."""

    def __init__(self) -> None:
        # ``self.name`` MUST be "skill" so the MCP prefix ("frood_") produces the
        # final external name "frood_skill" per CONTEXT.md D-02 / MCP-01.
        self._name = "skill"

    # ------------------------------------------------------------------
    # Tool ABC surface
    # ------------------------------------------------------------------
    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return (
            "List or load Claude Code warehouse items (skills, commands, agents) "
            "and Frood built-ins (personas, skills) on-demand. Gated by "
            "~/.frood/cli.yaml warehouse flags. Use action='list' for the full "
            "inventory, action='load' with a name for the full markdown body."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "load"],
                    "description": "'list' returns the inventory dict; 'load' returns a single item's body.",
                },
                "name": {
                    "type": "string",
                    "description": "Required when action='load'. Name of the skill/command/agent/persona/frood_skill.",
                    "default": "",
                },
            },
            "required": ["action"],
        }

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------
    async def execute(self, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action", "")
        if action not in ("list", "load"):
            return ToolResult(
                success=False,
                error=f"action must be 'list' or 'load', got {action!r}",
            )

        flags = _load_flags()

        if action == "list":
            inventory = await asyncio.to_thread(_discover_all, flags)
            return ToolResult(success=True, output=json.dumps(inventory, indent=2))

        # action == "load"
        name = kwargs.get("name", "")
        if not name:
            return ToolResult(success=False, error="name required for action=load")

        # Path-traversal guard — names are flat identifiers, never paths.
        if any(ch in name for ch in ("/", "\\")) or ".." in name:
            return ToolResult(success=False, error="invalid name")

        return await asyncio.to_thread(_load_one, name, flags)


# ---------------------------------------------------------------------------
# Flag loading (graceful fallback if the manifest module misbehaves)
# ---------------------------------------------------------------------------
def _load_flags() -> dict[str, bool]:
    """Return the two warehouse flags as a simple dict.

    Defaults to both flags True — per CLAUDE.md graceful-degradation rule, any
    failure to read the manifest must not disable the tool.
    """
    try:
        from core.user_frood_dir import load_manifest

        manifest = load_manifest()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("load_manifest() failed (%s); using default flags", exc)
        return {"include_claude_warehouse": True, "include_frood_builtins": True}

    warehouse = manifest.get("warehouse") if isinstance(manifest, dict) else None
    if not isinstance(warehouse, dict):
        warehouse = {}

    return {
        "include_claude_warehouse": bool(warehouse.get("include_claude_warehouse", True)),
        "include_frood_builtins": bool(warehouse.get("include_frood_builtins", True)),
    }


# ---------------------------------------------------------------------------
# Warehouse discovery (synchronous workers — called via asyncio.to_thread)
# ---------------------------------------------------------------------------
def _warehouse_root() -> Path:
    return Path.home() / ".claude"


def _discover_skills() -> list[dict[str, str]]:
    """List warehoused skills: each subdir of ``skills-warehouse/`` containing SKILL.md."""
    root = _warehouse_root() / "skills-warehouse"
    out: list[dict[str, str]] = []
    try:
        if not root.is_dir():
            return out
        for entry in sorted(root.iterdir()):
            if not entry.is_dir():
                continue
            skill_md = entry / "SKILL.md"
            if skill_md.exists():
                out.append(
                    {
                        "name": entry.name,
                        "source": _SRC_SKILLS,
                        "path": str(skill_md),
                    }
                )
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Warehouse skill discovery failed: %s", exc)
        return []
    return out


def _discover_commands() -> list[dict[str, str]]:
    """List warehoused commands: every ``*.md`` under ``commands-warehouse/``, recursive."""
    root = _warehouse_root() / "commands-warehouse"
    out: list[dict[str, str]] = []
    try:
        if not root.is_dir():
            return out
        for path in sorted(root.rglob("*.md")):
            if not path.is_file():
                continue
            out.append(
                {
                    "name": path.stem,
                    "source": _SRC_COMMANDS,
                    "path": str(path),
                }
            )
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Warehouse command discovery failed: %s", exc)
        return []
    return out


def _discover_agents() -> list[dict[str, str]]:
    """List warehoused agents: every ``*.md`` directly under ``agents-warehouse/``."""
    root = _warehouse_root() / "agents-warehouse"
    out: list[dict[str, str]] = []
    try:
        if not root.is_dir():
            return out
        for path in sorted(root.glob("*.md")):
            if not path.is_file():
                continue
            out.append(
                {
                    "name": path.stem,
                    "source": _SRC_AGENTS,
                    "path": str(path),
                }
            )
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Warehouse agent discovery failed: %s", exc)
        return []
    return out


def _discover_personas() -> list[dict[str, str]]:
    """List Frood built-in personas (keys of ``BUILTIN_PERSONAS``)."""
    try:
        from tools.persona_tool import BUILTIN_PERSONAS
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Persona import failed: %s", exc)
        return []
    return [
        {"name": key, "source": _SRC_PERSONAS, "title": value.get("title", "")}
        for key, value in sorted(BUILTIN_PERSONAS.items())
    ]


def _discover_frood_skills() -> list[dict[str, str]]:
    """List Frood built-in skills via SkillLoader (reuse, no re-parsing).

    Replicates the discovery logic in ``mcp_server._load_skills`` without
    creating an import cycle with mcp_server itself.
    """
    try:
        from skills.loader import SkillLoader

        # Match mcp_server._load_skills() directory list.
        frood_root = Path(__file__).resolve().parent.parent
        workspace = Path.cwd().resolve()
        skill_dirs = [
            frood_root / "skills" / "builtins",
            frood_root / "skills" / "workspace",
            workspace / ".claude" / "skills",
            workspace / "custom_skills",
        ]
        loader = SkillLoader(skill_dirs)
        loader.load_all()
        return [
            {
                "name": s.name,
                "source": _SRC_FROOD_SKILLS,
                "description": s.description or "",
            }
            for s in loader.all_skills()
        ]
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Frood skill discovery failed: %s", exc)
        return []


def _discover_all(flags: dict[str, bool]) -> dict[str, list[dict[str, str]]]:
    """Build the full five-slice inventory dict, honouring manifest flags."""
    if flags.get("include_claude_warehouse", True):
        skills = _discover_skills()
        commands = _discover_commands()
        agents = _discover_agents()
    else:
        skills, commands, agents = [], [], []

    if flags.get("include_frood_builtins", True):
        personas = _discover_personas()
        frood_skills = _discover_frood_skills()
    else:
        personas, frood_skills = [], []

    return {
        "skills": skills,
        "commands": commands,
        "agents": agents,
        "personas": personas,
        "frood_skills": frood_skills,
    }


# ---------------------------------------------------------------------------
# Loader (synchronous worker — called via asyncio.to_thread)
# ---------------------------------------------------------------------------
def _load_one(name: str, flags: dict[str, bool]) -> ToolResult:
    """Resolve ``name`` across all enabled slices and return its full body.

    Lookup order mirrors the inventory order in `_discover_all`:
    warehouse skills → commands → agents → personas → frood_skills.
    First match wins.
    """
    # --- Warehouse (gated) ------------------------------------------------
    if flags.get("include_claude_warehouse", True):
        for entry in _discover_skills():
            if entry["name"] == name:
                body = _read_text(Path(entry["path"]))
                if body is None:
                    return ToolResult(
                        success=False,
                        error=f"could not read {entry['path']}",
                    )
                return _ok(name, entry["source"], body)

        for entry in _discover_commands():
            if entry["name"] == name:
                body = _read_text(Path(entry["path"]))
                if body is None:
                    return ToolResult(
                        success=False,
                        error=f"could not read {entry['path']}",
                    )
                return _ok(name, entry["source"], body)

        for entry in _discover_agents():
            if entry["name"] == name:
                body = _read_text(Path(entry["path"]))
                if body is None:
                    return ToolResult(
                        success=False,
                        error=f"could not read {entry['path']}",
                    )
                return _ok(name, entry["source"], body)

    # --- Built-ins (gated) ------------------------------------------------
    if flags.get("include_frood_builtins", True):
        try:
            from tools.persona_tool import BUILTIN_PERSONAS

            if name in BUILTIN_PERSONAS:
                body = json.dumps(BUILTIN_PERSONAS[name], indent=2)
                return _ok(name, _SRC_PERSONAS, body)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Persona lookup failed for %r: %s", name, exc)

        # Frood built-in skills via SkillLoader (reuse).
        try:
            from skills.loader import SkillLoader

            frood_root = Path(__file__).resolve().parent.parent
            workspace = Path.cwd().resolve()
            skill_dirs = [
                frood_root / "skills" / "builtins",
                frood_root / "skills" / "workspace",
                workspace / ".claude" / "skills",
                workspace / "custom_skills",
            ]
            loader = SkillLoader(skill_dirs)
            loader.load_all()
            skill = loader.get(name)
            if skill is not None:
                return _ok(name, _SRC_FROOD_SKILLS, skill.instructions or "")
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Frood skill lookup failed for %r: %s", name, exc)

    return ToolResult(success=False, error=f"not found: {name}")


def _ok(name: str, source: str, body: str) -> ToolResult:
    """Wrap a successful load response as a JSON-encoded ToolResult."""
    return ToolResult(
        success=True,
        output=json.dumps({"name": name, "source": source, "body": body}, indent=2),
    )


def _read_text(path: Path) -> str | None:
    """Read UTF-8 text, returning None on any I/O error (graceful degradation)."""
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not read %s: %s", path, exc)
        return None
