"""
Node Sync — bidirectional memory sync between Frood nodes.

Syncs MEMORY.md and HISTORY.md between local and remote nodes via SSH/rsync.
After sync, re-indexes vectors on the target so semantic search reflects
the updated content.

Sync strategy:
- Markdown files are the source of truth (not Qdrant vectors)
- Vectors are re-derived after sync via reindex_memory()
- HISTORY.md uses append-merge (events from both nodes combined)
- MEMORY.md uses entry-level union merge keyed by UUID (lossless, conflict-resistant)
"""

import asyncio
import logging
import re
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from tools.base import Tool, ToolResult

logger = logging.getLogger("frood.tools.node_sync")

DEFAULT_REMOTE = "agent42-prod"
MEMORY_FILES = ["MEMORY.md", "HISTORY.md"]
REMOTE_MEMORY_DIR = "~/agent42/.frood/memory"

# ── Entry-level merge helpers ─────────────────────────────────────────────────
# Matches UUID-prefixed bullets: - [ISO_TS SHORT_UUID] content
_ENTRY_RE = re.compile(r"^- \[(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z) ([0-9a-f]{8})\] (.+)$")
# Matches YAML frontmatter block
_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
# Matches old-format bullets (no UUID prefix)
_NO_UUID_RE = re.compile(r"^(- )(?!\[)(.+)$")
# Deterministic UUID5 namespace (shared with memory.store and memory_tool)
_UUID5_NAMESPACE = uuid.UUID("a42a42a4-2a42-4a42-a42a-42a42a42a42a")


def _parse_memory_entries(content: str) -> dict:
    """Parse UUID-format bullets into {short_uuid: {ts, content, section}}.

    Lines without UUID format (plain bullets, headings, blank lines) are ignored.
    CRLF line endings are normalised to LF before parsing.
    """
    entries = {}
    current_section = ""
    for line in content.replace("\r\n", "\n").splitlines():
        if line.startswith("## "):
            current_section = line[3:].strip()
        elif m := _ENTRY_RE.match(line):
            ts, short_id, text = m.group(1), m.group(2), m.group(3)
            entries[short_id] = {"ts": ts, "content": text, "section": current_section}
    return entries


def _resolve_entry_conflict(local: dict, remote: dict) -> dict:
    """Resolve same-UUID different-content conflict: newest wins, older becomes history note."""
    if local["ts"] >= remote["ts"]:
        winner, loser = dict(local), remote
    else:
        winner, loser = dict(remote), local
    winner["content"] = winner["content"] + f"\n  > [prev: {loser['ts']}] {loser['content']}"
    return winner


def _rebuild_memory(local_content: str, merged_entries: dict) -> str:
    """Rebuild MEMORY.md from merged entries, preserving local section order.

    - Sections from local file keep their original order.
    - Remote-only sections are appended at the end.
    - Frontmatter is preserved from local.
    - Entries with no section are placed at the end.
    """
    content = local_content.replace("\r\n", "\n")

    # Extract frontmatter if present
    frontmatter = ""
    fm_match = _FRONTMATTER_RE.match(content)
    if fm_match:
        frontmatter = fm_match.group(0)
        content = content[fm_match.end() :]

    # Parse local section order and header lines (lines before first ## section)
    local_sections: list[str] = []
    header_lines: list[str] = []
    in_header = True
    for line in content.splitlines():
        if line.startswith("## "):
            in_header = False
            section_name = line[3:].strip()
            if section_name not in local_sections:
                local_sections.append(section_name)
        elif in_header:
            header_lines.append(line)

    # Collect remote-only sections from merged entries
    all_sections = list(local_sections)
    for entry in merged_entries.values():
        sec = entry["section"]
        if sec and sec not in all_sections:
            all_sections.append(sec)

    # Group entries by section
    entries_by_section: dict[str, list] = {}
    for eid, entry in merged_entries.items():
        sec = entry["section"] or ""
        entries_by_section.setdefault(sec, []).append((eid, entry))

    # Rebuild output
    lines: list[str] = []
    if frontmatter:
        lines.append(frontmatter.rstrip("\n"))
    if header_lines:
        lines.extend(header_lines)

    for section in all_sections:
        lines.append(f"\n## {section}\n")
        for eid, entry in entries_by_section.get(section, []):
            lines.append(f"- [{entry['ts']} {eid}] {entry['content']}")

    # Entries with no section (placed at end)
    for eid, entry in entries_by_section.get("", []):
        lines.append(f"- [{entry['ts']} {eid}] {entry['content']}")

    return "\n".join(lines) + "\n"


class NodeSyncTool(Tool):
    """Sync memory between Frood nodes."""

    requires = ["memory_store", "workspace"]

    def __init__(self, memory_store=None, workspace="", **kwargs):
        self._memory_store = memory_store
        self._workspace = workspace

    @property
    def name(self):
        return "node_sync"

    @property
    def description(self):
        return (
            "Sync memory between Frood nodes (laptop and VPS). "
            "Push sends local memories to remote. Pull fetches remote memories. "
            "Merge combines both, keeping all unique content."
        )

    @property
    def parameters(self):
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["push", "pull", "merge", "status", "migrate"],
                    "description": "push (local->remote), pull (remote->local), merge (bidirectional), status (show diff), migrate (convert old-format bullets to UUID format)",
                },
                "host": {
                    "type": "string",
                    "description": "SSH host alias or user@host (default: agent42-prod)",
                },
                "dry_run": {
                    "type": "boolean",
                    "description": "Preview changes without applying (default: false)",
                },
            },
            "required": ["action"],
        }

    async def execute(self, action="", host="", dry_run=False, **kwargs):
        if not action:
            return ToolResult(output="", error="action is required", success=False)

        host = host or DEFAULT_REMOTE
        local_dir = self._get_local_memory_dir()

        if not local_dir.exists():
            return ToolResult(
                output="", error=f"Local memory dir not found: {local_dir}", success=False
            )

        if action == "status":
            return await self._status(host, local_dir)
        elif action == "push":
            return await self._push(host, local_dir, dry_run)
        elif action == "pull":
            return await self._pull(host, local_dir, dry_run)
        elif action == "merge":
            return await self._merge(host, local_dir, dry_run)
        elif action == "migrate":
            return await self._migrate_action(local_dir, dry_run)
        else:
            return ToolResult(output="", error=f"Unknown action: {action}", success=False)

    def _get_local_memory_dir(self):
        workspace = Path(self._workspace) if self._workspace else Path(".")
        return workspace / ".frood" / "memory"

    async def _run_ssh(self, host, command, timeout=15):
        try:
            proc = await asyncio.create_subprocess_exec(
                "ssh",
                host,
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return proc.returncode, stdout.decode(errors="replace"), stderr.decode(errors="replace")
        except TimeoutError:
            return -1, "", "SSH command timed out"
        except Exception as e:
            return -1, "", str(e)

    async def _run_rsync(self, src, dst, dry_run=False, timeout=30):
        args = ["rsync", "-avz", "--checksum"]
        if dry_run:
            args.append("--dry-run")
        args.extend([src, dst])

        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return proc.returncode, stdout.decode(errors="replace"), stderr.decode(errors="replace")
        except TimeoutError:
            return -1, "", "rsync timed out"
        except Exception as e:
            return -1, "", str(e)

    async def _status(self, host, local_dir):
        lines = ["## Node Sync Status\n"]

        lines.append("### Local Node")
        for fname in MEMORY_FILES:
            fpath = local_dir / fname
            if fpath.exists():
                stat = fpath.stat()
                mtime = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime))
                lines.append(f"  - {fname}: {stat.st_size:,} bytes, modified {mtime}")
            else:
                lines.append(f"  - {fname}: not found")

        lines.append(f"\n### Remote Node ({host})")
        rc, stdout, stderr = await self._run_ssh(
            host, f"ls -la {REMOTE_MEMORY_DIR}/MEMORY.md {REMOTE_MEMORY_DIR}/HISTORY.md 2>/dev/null"
        )
        if rc == 0 and stdout.strip():
            for line in stdout.strip().split("\n"):
                parts = line.split()
                if len(parts) >= 9:
                    size = parts[4]
                    date = f"{parts[5]} {parts[6]} {parts[7]}"
                    name = parts[-1].split("/")[-1]
                    lines.append(f"  - {name}: {size} bytes, {date}")
        elif stderr:
            lines.append(f"  - Error: {stderr.strip()}")
        else:
            lines.append("  - No memory files found on remote")

        rc2, _, _ = await self._run_ssh(host, "echo ok")
        lines.append("\n### Connectivity")
        lines.append(f"  - SSH to {host}: {'connected' if rc2 == 0 else 'FAILED'}")

        return ToolResult(output="\n".join(lines), success=True)

    async def _push(self, host, local_dir, dry_run):
        results = []
        for fname in MEMORY_FILES:
            src = str(local_dir / fname)
            dst = f"{host}:{REMOTE_MEMORY_DIR}/{fname}"
            rc, stdout, stderr = await self._run_rsync(src, dst, dry_run=dry_run)
            if rc == 0:
                results.append(f"  - {fname}: {'would sync' if dry_run else 'synced'}")
            else:
                results.append(f"  - {fname}: FAILED ({stderr.strip()[:100]})")

        if not dry_run:
            rc, _, stderr = await self._run_ssh(
                host,
                "cd ~/agent42 && .venv/bin/python -c \"import asyncio; from memory.store import MemoryStore; s = MemoryStore('.frood/memory'); asyncio.run(s.reindex_memory()); print('Re-indexed')\"",
                timeout=30,
            )
            if rc == 0:
                results.append("  - Remote re-index: done")
            else:
                results.append(f"  - Remote re-index: skipped ({stderr.strip()[:80]})")

        action_label = "Push (dry run)" if dry_run else "Push"
        header = f"## {action_label}: local -> {host}\n"
        return ToolResult(output=header + "\n".join(results), success=True)

    async def _pull(self, host, local_dir, dry_run):
        results = []
        for fname in MEMORY_FILES:
            src = f"{host}:{REMOTE_MEMORY_DIR}/{fname}"
            dst = str(local_dir / fname)
            rc, stdout, stderr = await self._run_rsync(src, dst, dry_run=dry_run)
            if rc == 0:
                results.append(f"  - {fname}: {'would sync' if dry_run else 'synced'}")
            else:
                results.append(f"  - {fname}: FAILED ({stderr.strip()[:100]})")

        if not dry_run and self._memory_store:
            try:
                await self._memory_store.reindex_memory()
                results.append("  - Local re-index: done")
            except Exception as e:
                results.append(f"  - Local re-index: skipped ({e})")

        action_label = "Pull (dry run)" if dry_run else "Pull"
        header = f"## {action_label}: {host} -> local\n"
        return ToolResult(output=header + "\n".join(results), success=True)

    async def _merge(self, host, local_dir, dry_run):
        """Entry-level union merge of MEMORY.md + append-merge of HISTORY.md."""
        results = []

        # --- MEMORY.md: entry-level union merge ---
        local_memory = local_dir / "MEMORY.md"
        local_content = ""
        if local_memory.exists():
            local_content = local_memory.read_text(encoding="utf-8")

        # Fetch remote content via SSH cat (not rsync/stat)
        rc, remote_content, stderr = await self._run_ssh(
            host, f"cat {REMOTE_MEMORY_DIR}/MEMORY.md", timeout=15
        )
        remote_content = remote_content.replace("\r\n", "\n")  # normalize CRLF

        if rc != 0 or not remote_content.strip():
            # Remote missing or empty — push local to remote
            if local_content.strip() and not dry_run:
                await self._run_rsync(str(local_memory), f"{host}:{REMOTE_MEMORY_DIR}/MEMORY.md")
            results.append(
                f"  - MEMORY.md: remote {'missing' if rc != 0 else 'empty'} "
                f"-> {'would push local' if dry_run else 'pushed local'}"
            )
        else:
            local_entries = _parse_memory_entries(local_content)
            remote_entries = _parse_memory_entries(remote_content)

            # Union merge
            merged: dict = {}
            all_uuids = set(local_entries) | set(remote_entries)
            conflicts = 0
            for uid in all_uuids:
                l = local_entries.get(uid)
                r = remote_entries.get(uid)
                if l and r:
                    if l["content"] == r["content"]:
                        merged[uid] = l  # identical
                    else:
                        merged[uid] = _resolve_entry_conflict(l, r)
                        conflicts += 1
                elif l:
                    merged[uid] = l
                else:
                    merged[uid] = r

            # Rebuild the file
            merged_content = _rebuild_memory(local_content, merged)

            new_from_remote = len(set(remote_entries) - set(local_entries))
            new_from_local = len(set(local_entries) - set(remote_entries))

            if not dry_run:
                local_memory.write_text(merged_content, encoding="utf-8")
                # Push merged result to remote
                await self._run_rsync(str(local_memory), f"{host}:{REMOTE_MEMORY_DIR}/MEMORY.md")

            conflict_note = f", {conflicts} conflict(s) resolved" if conflicts else ""
            results.append(
                f"  - MEMORY.md: {'would merge' if dry_run else 'merged'} "
                f"({new_from_remote} from remote, {new_from_local} from local{conflict_note})"
            )

        # --- HISTORY.md: append-merge unique entries (unchanged from previous strategy) ---
        local_history = local_dir / "HISTORY.md"
        if local_history.exists():
            rc, remote_hist, _ = await self._run_ssh(host, f"cat {REMOTE_MEMORY_DIR}/HISTORY.md")
            if rc == 0 and remote_hist.strip():
                local_hist = local_history.read_text(encoding="utf-8")
                local_entries_h = set(e.strip() for e in local_hist.split("\n---\n") if e.strip())
                remote_entries_h = set(e.strip() for e in remote_hist.split("\n---\n") if e.strip())
                new_from_remote_h = remote_entries_h - local_entries_h
                new_from_local_h = local_entries_h - remote_entries_h

                if new_from_remote_h or new_from_local_h:
                    merged_h = local_entries_h | remote_entries_h
                    merged_hist = "\n---\n".join(sorted(merged_h))
                    if not dry_run:
                        local_history.write_text(merged_hist, encoding="utf-8")
                        await self._run_rsync(
                            str(local_history),
                            f"{host}:{REMOTE_MEMORY_DIR}/HISTORY.md",
                        )
                    results.append(
                        f"  - HISTORY.md: {'would merge' if dry_run else 'merged'} "
                        f"({len(new_from_remote_h)} from remote, {len(new_from_local_h)} from local)"
                    )
                else:
                    results.append("  - HISTORY.md: in sync")

        # Re-index after merge
        if not dry_run:
            if self._memory_store:
                try:
                    await self._memory_store.reindex_memory()
                    results.append("  - Local re-index: done")
                except Exception as e:
                    results.append(f"  - Local re-index: skipped ({e})")

            rc, _, _ = await self._run_ssh(
                host,
                "cd ~/agent42 && .venv/bin/python -c \"import asyncio; from memory.store import MemoryStore; s = MemoryStore('.frood/memory'); asyncio.run(s.reindex_memory()); print('done')\"",
                timeout=30,
            )
            results.append(f"  - Remote re-index: {'done' if rc == 0 else 'skipped'}")

        action_label = "Merge (dry run)" if dry_run else "Merge"
        header = f"## {action_label}: bidirectional sync with {host}\n"
        return ToolResult(output=header + "\n".join(results), success=True)

    async def _migrate_action(self, local_dir, dry_run):
        """Migrate old-format MEMORY.md bullets to UUID format (per D-11)."""
        memory_path = local_dir / "MEMORY.md"
        if not memory_path.exists():
            return ToolResult(output="No MEMORY.md found.", success=False)

        content = memory_path.read_text(encoding="utf-8")
        namespace = uuid.UUID("a42a42a4-2a42-4a42-a42a-42a42a42a42a")
        ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        count = 0
        result_lines = []

        for line in content.splitlines():
            m = _NO_UUID_RE.match(line)
            if m:
                text = m.group(2)
                short_id = uuid.uuid5(namespace, text).hex[:8]
                new_line = f"- [{ts} {short_id}] {text}"
                result_lines.append(new_line)
                count += 1
                if dry_run:
                    logger.info("Would migrate: '%s' -> '%s'", line[:60], new_line[:60])
            else:
                result_lines.append(line)

        if dry_run:
            return ToolResult(
                output=f"Dry run: would migrate {count} old-format entries in MEMORY.md.",
                success=True,
            )

        migrated = "\n".join(result_lines)
        memory_path.write_text(migrated, encoding="utf-8")

        # Write sentinel
        sentinel = local_dir / ".migration_v1"
        sentinel.write_text("migrated\n", encoding="utf-8")

        return ToolResult(
            output=f"Migrated {count} entries to UUID format in MEMORY.md.",
            success=True,
        )
