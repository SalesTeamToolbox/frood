"""
File watcher tool — monitor files and directories for changes.

Inspired by Aider's file watching capability. Detects file modifications,
creations, and deletions and can trigger actions on change.
"""

import hashlib
import logging
import os
import time

from tools.base import Tool, ToolResult

logger = logging.getLogger("agent42.tools.file_watcher")


class FileWatcherTool(Tool):
    """Watch files/directories for changes and report modifications."""

    def __init__(self, workspace_path: str = "."):
        self._workspace = workspace_path
        self._snapshots: dict[str, dict[str, str]] = {}  # watch_id -> {path: hash}
        self._watches: dict[str, dict] = {}  # watch_id -> config

    @property
    def name(self) -> str:
        return "file_watcher"

    @property
    def description(self) -> str:
        return (
            "Monitor files and directories for changes. Take a snapshot, then "
            "check for modifications later. Reports added, modified, and deleted files."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["snapshot", "check", "diff", "list"],
                    "description": "Watcher action: snapshot (save state), check (compare), diff (show changes), list (show watches)",
                },
                "watch_id": {
                    "type": "string",
                    "description": "Identifier for this watch (default: 'default')",
                    "default": "default",
                },
                "path": {
                    "type": "string",
                    "description": "File or directory to watch (default: workspace root)",
                    "default": "",
                },
                "extensions": {
                    "type": "string",
                    "description": "Comma-separated file extensions to watch (e.g., '.py,.js')",
                    "default": "",
                },
            },
            "required": ["action"],
        }

    async def execute(
        self,
        action: str = "",
        watch_id: str = "default",
        path: str = "",
        extensions: str = "",
        **kwargs,
    ) -> ToolResult:
        if not action:
            return ToolResult(error="Action is required", success=False)

        target = os.path.join(self._workspace, path) if path else self._workspace
        ext_filter = set(e.strip() for e in extensions.split(",")) if extensions else None

        if action == "snapshot":
            return self._take_snapshot(watch_id, target, ext_filter)
        elif action == "check":
            return self._check_changes(watch_id, target, ext_filter)
        elif action == "diff":
            return self._show_diff(watch_id, target, ext_filter)
        elif action == "list":
            return self._list_watches()
        else:
            return ToolResult(error=f"Unknown action: {action}", success=False)

    def _collect_hashes(self, target: str, ext_filter: set | None) -> dict[str, str]:
        """Collect file hashes for the target path."""
        hashes = {}
        skip_dirs = {".git", "node_modules", "__pycache__", ".venv", "venv"}

        if os.path.isfile(target):
            hashes[target] = self._file_hash(target)
            return hashes

        for root, dirs, files in os.walk(target):
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            for fname in files:
                if ext_filter:
                    ext = os.path.splitext(fname)[1]
                    if ext not in ext_filter:
                        continue
                full = os.path.join(root, fname)
                try:
                    rel = os.path.relpath(full, self._workspace)
                except ValueError:
                    rel = full
                hashes[rel] = self._file_hash(full)
        return hashes

    @staticmethod
    def _file_hash(filepath: str) -> str:
        try:
            h = hashlib.md5(usedforsecurity=False)  # nosec B324
            with open(filepath, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    h.update(chunk)
            return h.hexdigest()
        except (OSError, PermissionError):
            return "error"

    def _take_snapshot(self, watch_id: str, target: str, ext_filter: set | None) -> ToolResult:
        hashes = self._collect_hashes(target, ext_filter)
        self._snapshots[watch_id] = hashes
        self._watches[watch_id] = {
            "target": target,
            "ext_filter": list(ext_filter) if ext_filter else None,
            "timestamp": time.time(),
            "file_count": len(hashes),
        }
        return ToolResult(
            output=f"Snapshot '{watch_id}' taken: {len(hashes)} files tracked.",
            success=True,
        )

    def _check_changes(self, watch_id: str, target: str, ext_filter: set | None) -> ToolResult:
        if watch_id not in self._snapshots:
            return ToolResult(
                error=f"No snapshot found for '{watch_id}'. Take a snapshot first.", success=False
            )

        old = self._snapshots[watch_id]
        current = self._collect_hashes(target, ext_filter)

        added = set(current.keys()) - set(old.keys())
        deleted = set(old.keys()) - set(current.keys())
        modified = {f for f in set(current.keys()) & set(old.keys()) if current[f] != old[f]}

        if not added and not deleted and not modified:
            return ToolResult(
                output=f"No changes detected since snapshot '{watch_id}'.", success=True
            )

        lines = [f"## Changes since snapshot '{watch_id}'\n"]
        if added:
            lines.append(f"### Added ({len(added)})")
            for f in sorted(added)[:50]:
                lines.append(f"  + {f}")
            lines.append("")
        if modified:
            lines.append(f"### Modified ({len(modified)})")
            for f in sorted(modified)[:50]:
                lines.append(f"  ~ {f}")
            lines.append("")
        if deleted:
            lines.append(f"### Deleted ({len(deleted)})")
            for f in sorted(deleted)[:50]:
                lines.append(f"  - {f}")
            lines.append("")

        lines.append(
            f"**Total:** {len(added)} added, {len(modified)} modified, {len(deleted)} deleted"
        )
        return ToolResult(output="\n".join(lines), success=True)

    def _show_diff(self, watch_id: str, target: str, ext_filter: set | None) -> ToolResult:
        """Same as check but with file content diffs for modified files."""
        # Delegate to check for now — full diff would require storing file contents
        return self._check_changes(watch_id, target, ext_filter)

    def _list_watches(self) -> ToolResult:
        if not self._watches:
            return ToolResult(output="No active watches.", success=True)

        lines = ["## Active Watches\n"]
        for wid, config in self._watches.items():
            age = time.time() - config["timestamp"]
            age_str = f"{age:.0f}s ago" if age < 120 else f"{age / 60:.0f}m ago"
            lines.append(f"- **{wid}**: {config['file_count']} files, snapshot {age_str}")
        return ToolResult(output="\n".join(lines), success=True)
