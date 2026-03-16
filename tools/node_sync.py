"""
Node Sync — bidirectional memory sync between Agent42 nodes.

Syncs MEMORY.md and HISTORY.md between local and remote nodes via SSH/rsync.
After sync, re-indexes vectors on the target so semantic search reflects
the updated content.

Sync strategy:
- Markdown files are the source of truth (not Qdrant vectors)
- Vectors are re-derived after sync via reindex_memory()
- HISTORY.md uses append-merge (events from both nodes combined)
- MEMORY.md uses timestamp-wins (most recently modified version wins)
"""

import asyncio
import logging
import time
from pathlib import Path

from tools.base import Tool, ToolResult

logger = logging.getLogger("agent42.tools.node_sync")

DEFAULT_REMOTE = "agent42-prod"
MEMORY_FILES = ["MEMORY.md", "HISTORY.md"]
REMOTE_MEMORY_DIR = "~/agent42/.agent42/memory"


class NodeSyncTool(Tool):
    """Sync memory between Agent42 nodes."""

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
            "Sync memory between Agent42 nodes (laptop and VPS). "
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
                    "enum": ["push", "pull", "merge", "status"],
                    "description": "push (local->remote), pull (remote->local), merge (bidirectional), status (show diff)",
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
        else:
            return ToolResult(output="", error=f"Unknown action: {action}", success=False)

    def _get_local_memory_dir(self):
        workspace = Path(self._workspace) if self._workspace else Path(".")
        return workspace / ".agent42" / "memory"

    async def _run_ssh(self, host, command, timeout=15):
        try:
            proc = await asyncio.create_subprocess_exec(
                "ssh", host, command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return proc.returncode, stdout.decode(errors="replace"), stderr.decode(errors="replace")
        except asyncio.TimeoutError:
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
        except asyncio.TimeoutError:
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
            host,
            f"ls -la {REMOTE_MEMORY_DIR}/MEMORY.md {REMOTE_MEMORY_DIR}/HISTORY.md 2>/dev/null"
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
        lines.append(f"\n### Connectivity")
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
                "cd ~/agent42 && .venv/bin/python -c \"import asyncio; from memory.store import MemoryStore; s = MemoryStore('.agent42/memory'); asyncio.run(s.reindex_memory()); print('Re-indexed')\"",
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
        results = []

        rc, stdout, _ = await self._run_ssh(
            host,
            f"stat -c '%Y %s' {REMOTE_MEMORY_DIR}/MEMORY.md {REMOTE_MEMORY_DIR}/HISTORY.md 2>/dev/null"
        )
        if rc != 0:
            return ToolResult(output="", error="Cannot reach remote node", success=False)

        remote_stats = stdout.strip().split("\n")

        # MEMORY.md: newest wins
        local_memory = local_dir / "MEMORY.md"
        if local_memory.exists() and len(remote_stats) >= 1:
            local_mtime = local_memory.stat().st_mtime
            remote_parts = remote_stats[0].split()
            remote_mtime = float(remote_parts[0]) if remote_parts else 0

            if local_mtime > remote_mtime:
                if not dry_run:
                    await self._run_rsync(str(local_memory), f"{host}:{REMOTE_MEMORY_DIR}/MEMORY.md")
                results.append(f"  - MEMORY.md: local is newer -> {'would push' if dry_run else 'pushed'}")
            elif remote_mtime > local_mtime:
                if not dry_run:
                    await self._run_rsync(f"{host}:{REMOTE_MEMORY_DIR}/MEMORY.md", str(local_memory))
                results.append(f"  - MEMORY.md: remote is newer -> {'would pull' if dry_run else 'pulled'}")
            else:
                results.append("  - MEMORY.md: in sync")

        # HISTORY.md: append-merge unique entries
        local_history = local_dir / "HISTORY.md"
        if local_history.exists():
            rc, remote_content, _ = await self._run_ssh(
                host, f"cat {REMOTE_MEMORY_DIR}/HISTORY.md"
            )
            if rc == 0 and remote_content.strip():
                local_content = local_history.read_text(encoding="utf-8")

                local_entries = set(e.strip() for e in local_content.split("\n---\n") if e.strip())
                remote_entries = set(e.strip() for e in remote_content.split("\n---\n") if e.strip())

                new_from_remote = remote_entries - local_entries
                new_from_local = local_entries - remote_entries

                if new_from_remote or new_from_local:
                    merged = local_entries | remote_entries
                    merged_content = "\n---\n".join(sorted(merged))

                    if not dry_run:
                        local_history.write_text(merged_content, encoding="utf-8")
                        await self._run_rsync(str(local_history), f"{host}:{REMOTE_MEMORY_DIR}/HISTORY.md")

                    results.append(
                        f"  - HISTORY.md: merged ({len(new_from_remote)} from remote, "
                        f"{len(new_from_local)} from local)"
                    )
                else:
                    results.append("  - HISTORY.md: in sync")

        if not dry_run:
            if self._memory_store:
                try:
                    await self._memory_store.reindex_memory()
                    results.append("  - Local re-index: done")
                except Exception as e:
                    results.append(f"  - Local re-index: skipped ({e})")

            rc, _, _ = await self._run_ssh(
                host,
                "cd ~/agent42 && .venv/bin/python -c \"import asyncio; from memory.store import MemoryStore; s = MemoryStore('.agent42/memory'); asyncio.run(s.reindex_memory()); print('done')\"",
                timeout=30,
            )
            results.append(f"  - Remote re-index: {'done' if rc == 0 else 'skipped'}")

        action_label = "Merge (dry run)" if dry_run else "Merge"
        header = f"## {action_label}: bidirectional sync with {host}\n"
        return ToolResult(output=header + "\n".join(results), success=True)
