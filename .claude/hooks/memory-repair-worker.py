#!/usr/bin/env python3
"""Memory-repair worker — imports Frood and calls memory.repair.run_repair.

Spawned as a detached background process by memory-repair.py. Respects
MEMORY_REPAIR_APPLY to decide dry-run vs apply. All failures are silent — the
repair worker itself records errors into .frood/memory-repair-status.json.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

script_dir = Path(__file__).resolve().parent
project_dir = script_dir.parent.parent
sys.path.insert(0, str(project_dir))


async def _main() -> None:
    try:
        from memory.repair import run_repair
    except Exception:
        return

    apply = os.getenv("MEMORY_REPAIR_APPLY", "false").lower() in ("true", "1", "yes")
    harnesses = os.getenv("MEMORY_REPAIR_HARNESSES", "claude_code").split(",")
    snapshot_dir = os.getenv("MEMORY_REPAIR_SNAPSHOT_DIR", ".frood/memory-repair-snapshots")
    audit_log = os.getenv("MEMORY_REPAIR_AUDIT_LOG", ".frood/memory-repair-log.jsonl")

    for harness in (h.strip() for h in harnesses if h.strip()):
        try:
            await run_repair(
                harness=harness,
                dry_run=not apply,
                workspace=project_dir,
                snapshot_dir=snapshot_dir,
                audit_log=audit_log,
            )
        except Exception:
            pass  # Silent — status file records the error


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except Exception:
        pass
