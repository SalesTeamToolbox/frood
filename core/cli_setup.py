"""CLI-config wiring engines for Frood's cross-CLI setup feature.

This module owns the file-mutating logic that wires Frood into the native MCP
configuration of every CLI Frood supports. It is consumed by two downstream
surfaces that MUST share the same code path:

  * ``frood cli-setup`` subcommand (Plan 01-04)
  * Dashboard ``/api/cli-setup/*`` endpoints (Plan 01-05)

Safety contract (SAFE-01..SAFE-03 from the phase REQUIREMENTS):

  * SAFE-01 — every CLI config file receives a timestamped ``.bak-<ts>`` sibling
    on the FIRST write. Subsequent writes reuse that backup (no duplicates).
  * SAFE-02 — ``wire`` → ``unwire`` is a byte-identical round-trip: when a
    backup exists, unwire restores from it (so JSON key ordering, whitespace,
    and trailing newlines all survive perfectly).
  * SAFE-03 — wire only ADDS the ``frood`` entry. It never removes, renames, or
    disables other MCP servers, providers, instructions, or top-level settings.
    Unwire only removes the ``frood`` entry (via restore-from-backup).

Bootstrap-level sync I/O is acceptable here (precedent: core/key_store.py,
core/portability.py). The async-I/O rule in CLAUDE.md applies to the running
tool loop — wiring is a one-shot operation that runs before the loop is alive
AND also runs inside sync CLI/CommandHandler code paths.
"""

from __future__ import annotations

import copy
import datetime
import json
import logging
import os
import shutil
import sys
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from core.user_frood_dir import load_manifest

logger = logging.getLogger("frood.cli_setup")


# ---------------------------------------------------------------------------
# Module-level constants — shared between adapters and exported for downstream
# CLI/dashboard layers to reference in their own documentation.
# ---------------------------------------------------------------------------

#: ``strftime`` format used for backup siblings (``opencode.json.bak-20260417T120000``).
BACKUP_SUFFIX_FMT = "%Y%m%dT%H%M%S"

#: HTML comment markers used to delimit Frood's note inside AGENTS.md.
#: Marker-delimited so unwire can remove the block cleanly without touching the
#: user's own instructions.
MARKER_BEGIN = "<!-- frood:cli-setup:begin -->"
MARKER_END = "<!-- frood:cli-setup:end -->"

#: Body text injected between MARKER_BEGIN / MARKER_END into AGENTS.md. Keep in
#: sync with 01-CONTEXT.md's locked text — downstream docs quote this verbatim.
AGENTS_NOTE_BODY = (
    "Frood warehouse tools are available via the `frood_skill` MCP tool.\n"
    'Use `frood_skill(action="list")` to discover skills/commands/agents; '
    '`frood_skill(action="load", name="<name>")` to load one.'
)

#: Frood's MCP entry for Claude Code's ``~/.claude/settings.json`` `mcpServers`.
#: ``sys.executable`` keeps the binding pinned to the interpreter that installed
#: Frood — works across venvs, pyenvs, and global installs.
FROOD_MCP_ENTRY_CLAUDE: dict[str, Any] = {
    "command": sys.executable,
    "args": ["-m", "mcp_server"],
    "env": {},
}

#: Frood's MCP entry for OpenCode's project-local ``opencode.json`` `mcp` map.
#: OpenCode uses a different schema than Claude Code — it wraps command in an
#: array and includes ``type: "local"`` + ``enabled``.
FROOD_MCP_ENTRY_OPENCODE: dict[str, Any] = {
    "type": "local",
    "command": [sys.executable, "-m", "mcp_server"],
    "enabled": True,
}


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------
def _now_ts() -> str:
    """Current UTC-ish timestamp in BACKUP_SUFFIX_FMT. Local time is fine here —
    the backup is a sibling of a user file; matching wall-clock is more useful
    than strictly-UTC for humans eyeballing the directory."""
    return datetime.datetime.now().strftime(BACKUP_SUFFIX_FMT)


def _atomic_write_text(path: Path, content: str) -> None:
    """Write ``content`` to ``path`` atomically via tempfile + os.replace.

    Prevents half-written files if the process dies mid-write. Mirrors the
    pattern used in core/portability.py.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    # delete=False because we're doing our own atomic rename.
    tmp_fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(content)
        os.replace(tmp_name, path)
    except Exception:
        # Best-effort cleanup — if replace failed, the temp file is stale.
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _find_existing_backup(target: Path) -> Path | None:
    """Return the earliest existing ``target.name.bak-<ts>`` sibling, or None."""
    if not target.parent.exists():
        return None
    candidates = sorted(target.parent.glob(f"{target.name}.bak-*"))
    return candidates[0] if candidates else None


def _write_backup_if_first(target: Path) -> Path | None:
    """SAFE-01: create ``target.bak-<ts>`` ONLY if no prior backup exists.

    Returns the backup Path (either just-created or pre-existing). If the target
    doesn't exist yet (first wire into an absent file), returns None — there's
    nothing to back up, and unwire will detect this case by backup absence and
    delete the created file instead of restoring.
    """
    if not target.exists():
        return None
    existing = _find_existing_backup(target)
    if existing is not None:
        logger.debug("Reusing existing backup %s for %s", existing, target)
        return existing
    backup = target.with_name(f"{target.name}.bak-{_now_ts()}")
    shutil.copy2(target, backup)
    logger.info("Created backup %s", backup)
    return backup


def _restore_from_backup(target: Path, backup: Path) -> None:
    """Restore ``target`` from ``backup`` and remove the backup.

    Used by unwire to guarantee byte-identical round-trip: the pre-wire bytes
    are on disk verbatim, so we replace the modified target with them and clean
    up. If target didn't exist pre-wire (no backup passed), callers use
    ``_delete_if_created`` instead.
    """
    shutil.copy2(backup, target)
    try:
        backup.unlink()
    except OSError as exc:
        logger.warning("Could not remove backup %s: %s", backup, exc)


# ---------------------------------------------------------------------------
# Adapter ABC
# ---------------------------------------------------------------------------
class CliAdapter(ABC):
    """Common contract every per-CLI engine must satisfy.

    Downstream code (CLI subcommand, dashboard endpoints) treats every CLI
    uniformly via this interface; concrete adapters add CLI-specific fields to
    their return dicts but always satisfy the base keys documented below.
    """

    #: Short identifier used by dispatch helpers and manifest keys.
    name: str = ""

    @abstractmethod
    def detect(self) -> dict[str, Any]:
        """Return ``{"installed": bool, "wired": bool, ...}``."""

    @abstractmethod
    def wire(self) -> dict[str, Any]:
        """Idempotently merge Frood into this CLI's config.

        Returns ``{"changed": bool, "backup": Optional[Path], "targets": [...]}``.
        ``changed=False`` means no-op (already wired); ``backup`` is the backup
        path used (new or pre-existing) when a file was actually modified.
        """

    @abstractmethod
    def unwire(self) -> dict[str, Any]:
        """Reverse ``wire``. Returns ``{"changed": bool, "targets": [...]}``.

        When a backup sibling exists, restore from it for byte-identical
        round-trip; otherwise remove the ``frood`` entry in-place.
        """


# ---------------------------------------------------------------------------
# Claude Code adapter
# ---------------------------------------------------------------------------
class ClaudeCodeSetup(CliAdapter):
    """Wires Frood into ``<root>/.claude/settings.json`` under ``mcpServers``.

    SAFE-03: only the ``frood`` key in ``mcpServers`` is ever touched. Every
    other top-level setting — ``other_key``, ``env``, ``permissions`` — plus
    every other ``mcpServers.*`` entry is preserved byte-for-byte via the
    backup-restore unwire path.
    """

    name = "claude-code"

    def __init__(self, root: Path | None = None) -> None:
        self._root = Path(root) if root is not None else Path.home()
        self._settings = self._root / ".claude" / "settings.json"

    # -- internal helpers --------------------------------------------------
    @property
    def settings_path(self) -> Path:
        return self._settings

    def _load_settings(self) -> dict[str, Any]:
        if not self._settings.exists():
            return {}
        try:
            text = self._settings.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("Could not read %s: %s", self._settings, exc)
            return {}
        if not text.strip():
            return {}
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            logger.warning("Malformed %s: %s — treating as empty", self._settings, exc)
            return {}
        if not isinstance(data, dict):
            logger.warning(
                "%s must be a JSON object; got %s — treating as empty",
                self._settings,
                type(data).__name__,
            )
            return {}
        return data

    def _write_settings(self, data: dict[str, Any]) -> None:
        _atomic_write_text(self._settings, json.dumps(data, indent=2) + "\n")

    # -- public API --------------------------------------------------------
    def detect(self) -> dict[str, Any]:
        claude_dir = self._root / ".claude"
        installed = claude_dir.exists()
        wired = False
        if self._settings.exists():
            data = self._load_settings()
            wired = "frood" in data.get("mcpServers", {})
        return {
            "installed": installed,
            "wired": wired,
            "settings_path": str(self._settings),
        }

    def wire(self) -> dict[str, Any]:
        """Merge FROOD_MCP_ENTRY_CLAUDE into settings.mcpServers.frood.

        SAFE-03 note: only the `frood` key is added. `mcpServers` siblings and
        all other top-level keys are preserved byte-for-byte on unwire via the
        backup-restore path.
        """
        desired = copy.deepcopy(FROOD_MCP_ENTRY_CLAUDE)
        current = self._load_settings()
        existing_mcp = current.get("mcpServers", {})

        # Idempotency — deep-equal means no write, no new backup.
        if existing_mcp.get("frood") == desired:
            logger.debug("Claude Code already wired (deep-equal); no-op")
            return {
                "changed": False,
                "backup": _find_existing_backup(self._settings),
                "targets": [str(self._settings)],
            }

        # Ensure parent dir exists so we can write even if .claude/ was missing.
        self._settings.parent.mkdir(parents=True, exist_ok=True)
        backup = _write_backup_if_first(self._settings)

        merged = copy.deepcopy(current)
        merged.setdefault("mcpServers", {})["frood"] = desired
        self._write_settings(merged)

        return {
            "changed": True,
            "backup": backup,
            "targets": [str(self._settings)],
        }

    def unwire(self) -> dict[str, Any]:
        """Remove the `frood` MCP entry.

        SAFE-03 note: only the `frood` key is removed. If a `.bak-*` sibling
        exists, it is restored verbatim (byte-identical round-trip). Else the
        `frood` key is deleted in place — leaves other keys untouched.
        """
        if not self._settings.exists():
            return {"changed": False, "targets": [str(self._settings)]}

        backup = _find_existing_backup(self._settings)
        if backup is not None:
            # Preferred path — SAFE-02 demands byte-identical, and only a
            # straight file copy guarantees that.
            _restore_from_backup(self._settings, backup)
            return {"changed": True, "targets": [str(self._settings)]}

        # Fallback: no backup (wire was called into an absent file, or user
        # deleted the backup manually). Remove the `frood` key in place.
        data = self._load_settings()
        mcp = data.get("mcpServers", {})
        if "frood" not in mcp:
            return {"changed": False, "targets": [str(self._settings)]}
        del mcp["frood"]
        if not mcp:
            # If mcpServers is now empty we still leave it — removing the key
            # could delete something the user had pre-wire that we can't
            # reconstruct without the backup.
            pass
        self._write_settings(data)
        return {"changed": True, "targets": [str(self._settings)]}


# ---------------------------------------------------------------------------
# OpenCode adapter
# ---------------------------------------------------------------------------
def _discover_default_project_paths() -> list[Path]:
    """Fallback when manifest says ``projects: "auto"`` (or is absent).

    Per Claude's Discretion (plan 01-03): shallow scan of ``cwd.parent`` for
    sibling directories containing ``opencode.json``. This is the cheapest,
    most predictable behavior — users with non-default project layouts can
    opt into an explicit list via ``~/.frood/cli.yaml``.
    """
    root = Path.cwd().parent
    if not root.exists():
        return []
    discovered: list[Path] = []
    try:
        for entry in root.iterdir():
            if entry.is_dir() and (entry / "opencode.json").exists():
                discovered.append(entry)
    except OSError as exc:
        logger.warning("Shallow OpenCode project scan failed in %s: %s", root, exc)
    return discovered


def _resolve_project_paths(
    project_paths: list[Path] | None,
    manifest: dict[str, Any] | None,
) -> list[Path]:
    """Order of precedence: explicit argument > manifest list > auto-discovery."""
    if project_paths:
        return [Path(p) for p in project_paths]
    mf = manifest if manifest is not None else load_manifest()
    opencode_cfg = mf.get("clis", {}).get("opencode", {})
    projects = opencode_cfg.get("projects")
    if isinstance(projects, list):
        return [Path(p) for p in projects]
    # "auto", missing, or any non-list value falls through to discovery.
    return _discover_default_project_paths()


class OpenCodeSetup(CliAdapter):
    """Wires Frood into each project's ``opencode.json`` + ``AGENTS.md``.

    SAFE-03: only ``mcp.frood`` inside opencode.json and the marker-delimited
    block inside AGENTS.md are ever touched. Providers, instructions, server
    settings, pre-existing MCP servers, and AGENTS.md content above/below the
    marker block are preserved byte-for-byte via the backup-restore unwire
    path.
    """

    name = "opencode"

    def __init__(
        self,
        project_paths: list[Path] | None = None,
        manifest: dict[str, Any] | None = None,
    ) -> None:
        self._project_paths = _resolve_project_paths(project_paths, manifest)

    @property
    def project_paths(self) -> list[Path]:
        return list(self._project_paths)

    # -- per-project file helpers -----------------------------------------
    @staticmethod
    def _oc_json(project: Path) -> Path:
        return project / "opencode.json"

    @staticmethod
    def _agents_md(project: Path) -> Path:
        return project / "AGENTS.md"

    @staticmethod
    def _read_opencode(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("Could not read %s: %s", path, exc)
            return {}
        if not text.strip():
            return {}
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            logger.warning("Malformed %s: %s — treating as empty", path, exc)
            return {}
        if not isinstance(data, dict):
            logger.warning(
                "%s must be a JSON object; got %s — treating as empty",
                path,
                type(data).__name__,
            )
            return {}
        return data

    @classmethod
    def _write_opencode(cls, path: Path, data: dict[str, Any]) -> None:
        _atomic_write_text(path, json.dumps(data, indent=2) + "\n")

    # -- detect ------------------------------------------------------------
    def detect(self) -> dict[str, Any]:
        projects: list[dict[str, Any]] = []
        any_installed = False
        any_wired = False
        for path in self._project_paths:
            oc_json = self._oc_json(path)
            installed = oc_json.exists()
            wired = False
            if installed:
                data = self._read_opencode(oc_json)
                wired = "frood" in data.get("mcp", {})
            projects.append(
                {
                    "path": str(path),
                    "installed": installed,
                    "wired": wired,
                }
            )
            any_installed = any_installed or installed
            any_wired = any_wired or wired
        return {
            "installed": any_installed,
            "wired": any_wired,
            "projects": projects,
        }

    # -- wire --------------------------------------------------------------
    def wire(self) -> dict[str, Any]:
        """Merge frood into each project's opencode.json + AGENTS.md.

        SAFE-03 note: only mcp.frood is touched inside opencode.json, and only
        the marker-delimited block is added to AGENTS.md. Every other key /
        user-written text survives the wire -> unwire round-trip via backup
        restoration.
        """
        targets: list[str] = []
        backups: list[Path] = []
        any_changed = False

        for project in self._project_paths:
            changed_oc = self._wire_opencode_json(project)
            changed_md = self._wire_agents_md(project)
            if changed_oc["changed"]:
                any_changed = True
                if changed_oc["backup"] is not None:
                    backups.append(changed_oc["backup"])
            if changed_md["changed"]:
                any_changed = True
                if changed_md["backup"] is not None:
                    backups.append(changed_md["backup"])
            targets.extend([str(self._oc_json(project)), str(self._agents_md(project))])

        return {
            "changed": any_changed,
            "backup": backups[0] if backups else None,
            "backups": backups,
            "targets": targets,
        }

    def _wire_opencode_json(self, project: Path) -> dict[str, Any]:
        oc_json = self._oc_json(project)
        desired = copy.deepcopy(FROOD_MCP_ENTRY_OPENCODE)
        current = self._read_opencode(oc_json)
        existing_mcp = current.get("mcp", {})

        if existing_mcp.get("frood") == desired:
            return {
                "changed": False,
                "backup": _find_existing_backup(oc_json),
            }

        oc_json.parent.mkdir(parents=True, exist_ok=True)
        backup = _write_backup_if_first(oc_json)
        merged = copy.deepcopy(current) if current else {}
        merged.setdefault("mcp", {})["frood"] = desired
        self._write_opencode(oc_json, merged)
        return {"changed": True, "backup": backup}

    def _wire_agents_md(self, project: Path) -> dict[str, Any]:
        agents_md = self._agents_md(project)
        block = f"{MARKER_BEGIN}\n{AGENTS_NOTE_BODY}\n{MARKER_END}\n"

        if agents_md.exists():
            text = agents_md.read_text(encoding="utf-8")
            if MARKER_BEGIN in text and MARKER_END in text:
                # Already wired — no-op, no new backup.
                return {
                    "changed": False,
                    "backup": _find_existing_backup(agents_md),
                }
            backup = _write_backup_if_first(agents_md)
            # Preserve exactly one blank separator between user content and our
            # block; without this a file that doesn't end in "\n" would result
            # in a concatenated opening line.
            separator = "" if text.endswith("\n") else "\n"
            new_text = text + separator + block
            _atomic_write_text(agents_md, new_text)
            return {"changed": True, "backup": backup}

        # File absent — create with just the block. No backup possible (nothing
        # to back up); unwire detects this by backup absence and deletes the
        # file instead of restoring.
        _atomic_write_text(agents_md, block)
        return {"changed": True, "backup": None}

    # -- unwire ------------------------------------------------------------
    def unwire(self) -> dict[str, Any]:
        """Reverse wire for each project. Byte-identical round-trip via backup
        restore when available; else in-place removal of the touched region.

        SAFE-03 note: only the frood mcp key and the marker-delimited AGENTS.md
        block are removed. Everything else survives.
        """
        any_changed = False
        targets: list[str] = []

        for project in self._project_paths:
            if self._unwire_opencode_json(project):
                any_changed = True
            if self._unwire_agents_md(project):
                any_changed = True
            targets.extend([str(self._oc_json(project)), str(self._agents_md(project))])

        return {"changed": any_changed, "targets": targets}

    def _unwire_opencode_json(self, project: Path) -> bool:
        oc_json = self._oc_json(project)
        if not oc_json.exists():
            return False
        backup = _find_existing_backup(oc_json)
        if backup is not None:
            _restore_from_backup(oc_json, backup)
            return True
        data = self._read_opencode(oc_json)
        mcp = data.get("mcp", {})
        if "frood" not in mcp:
            return False
        del mcp["frood"]
        self._write_opencode(oc_json, data)
        return True

    def _unwire_agents_md(self, project: Path) -> bool:
        agents_md = self._agents_md(project)
        if not agents_md.exists():
            return False
        backup = _find_existing_backup(agents_md)
        if backup is not None:
            # Byte-identical restore — also removes any USER content appended
            # after our block. That content is preserved by running the in-place
            # removal BEFORE restore: detect if the current file has content
            # after the end marker and re-append it post-restore.
            text = agents_md.read_text(encoding="utf-8")
            tail = self._extract_post_marker_tail(text)
            _restore_from_backup(agents_md, backup)
            if tail:
                # Re-append the user's post-marker additions with a single
                # newline separator. This preserves their edits without
                # reintroducing any of our own content.
                restored = agents_md.read_text(encoding="utf-8")
                separator = "" if restored.endswith("\n") else "\n"
                _atomic_write_text(agents_md, restored + separator + tail)
            return True
        # No backup — in-place removal. File was created by wire OR the user
        # nuked the backup. Detect by checking if non-marker content exists.
        text = agents_md.read_text(encoding="utf-8")
        cleaned = self._strip_marker_block(text)
        if cleaned == text:
            return False
        if not cleaned.strip():
            # File had ONLY our block → we created it; remove the file.
            agents_md.unlink()
            return True
        _atomic_write_text(agents_md, cleaned)
        return True

    @staticmethod
    def _strip_marker_block(text: str) -> str:
        """Remove everything from MARKER_BEGIN through MARKER_END, inclusive.

        Also consumes exactly one trailing newline after the end marker (that
        newline was added by wire as part of the block). If the removal leaves
        a leading separator newline that wire inserted, strip that too so the
        in-place case approximates the restore result.
        """
        start = text.find(MARKER_BEGIN)
        if start == -1:
            return text
        end = text.find(MARKER_END, start)
        if end == -1:
            return text
        end_idx = end + len(MARKER_END)
        # Consume one trailing newline after the end marker if present.
        if end_idx < len(text) and text[end_idx] == "\n":
            end_idx += 1
        # Drop up to one separator newline that wire inserted between user
        # content and our block.
        pre = text[:start]
        if pre.endswith("\n\n"):
            # User content already ended with a newline; wire added a single
            # newline separator. Remove only the one wire added.
            pre = pre[:-1]
        return pre + text[end_idx:]

    @classmethod
    def _extract_post_marker_tail(cls, text: str) -> str:
        """Return content AFTER the end marker — used to preserve user edits
        made between wire and unwire when restoring from backup."""
        end = text.find(MARKER_END)
        if end == -1:
            return ""
        end_idx = end + len(MARKER_END)
        if end_idx < len(text) and text[end_idx] == "\n":
            end_idx += 1
        return text[end_idx:]


# ---------------------------------------------------------------------------
# Dispatch helpers — the CLI subcommand and dashboard endpoints consume these.
# ---------------------------------------------------------------------------
def _build_adapter(cli: str, manifest: dict[str, Any] | None = None) -> CliAdapter:
    if cli == "claude-code":
        return ClaudeCodeSetup()
    if cli == "opencode":
        return OpenCodeSetup(manifest=manifest)
    raise ValueError(f"Unknown CLI: {cli!r}")


def detect_all(manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return detection state for every CLI flagged ``enabled`` in the manifest.

    Shape::

        {
            "claude-code": {"installed": bool, "wired": bool, "settings_path": str},
            "opencode":    {"installed": bool, "wired": bool, "projects": [...]},
        }

    CLIs disabled in the manifest are still surfaced (installed/wired still
    reported) so the dashboard can render a full inventory; downstream UI is
    responsible for hiding disabled entries if desired.
    """
    mf = manifest if manifest is not None else load_manifest()
    result: dict[str, Any] = {}
    for cli_name in ("claude-code", "opencode"):
        adapter = _build_adapter(cli_name, mf)
        state = adapter.detect()
        cli_cfg = mf.get("clis", {}).get(cli_name, {})
        state["enabled"] = bool(cli_cfg.get("enabled", True))
        result[cli_name] = state
    return result


def wire_cli(cli: str, manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    """Wire a single CLI by name. Returns the adapter's wire() result dict."""
    return _build_adapter(cli, manifest).wire()


def unwire_cli(cli: str, manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    """Reverse wire_cli. Returns the adapter's unwire() result dict."""
    return _build_adapter(cli, manifest).unwire()


__all__ = [
    "AGENTS_NOTE_BODY",
    "BACKUP_SUFFIX_FMT",
    "FROOD_MCP_ENTRY_CLAUDE",
    "FROOD_MCP_ENTRY_OPENCODE",
    "MARKER_BEGIN",
    "MARKER_END",
    "ClaudeCodeSetup",
    "CliAdapter",
    "OpenCodeSetup",
    "detect_all",
    "unwire_cli",
    "wire_cli",
]
