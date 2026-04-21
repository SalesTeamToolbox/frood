"""Orchestrator for the memory repair pipeline.

Call `run_repair()` with a harness adapter and it will:
  1. Discover every per-project memory directory for that harness.
  2. Run every deterministic check against each project.
  3. Hand the resulting RepairPlan to RepairExecutor for snapshot/apply/audit.
  4. Return a RepairResult + update `.frood/memory-repair-status.json`.

Graceful degradation: any per-project failure is logged into the result's
error field and the worker moves on; it never raises past the caller.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path

from memory.repair.adapters import ClaudeCodeAdapter, HarnessAdapter
from memory.repair.checks import run_checks
from memory.repair.executor import RepairExecutor
from memory.repair.models import RepairPlan, RepairResult

logger = logging.getLogger("frood.memory.repair.worker")


def _status_file_path(workspace: str | Path = ".") -> Path:
    return Path(workspace) / ".frood" / "memory-repair-status.json"


def load_repair_status(workspace: str | Path = ".") -> dict:
    path = _status_file_path(workspace)
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {
        "last_run": None,
        "runs_since_last_trigger": 0,
        "last_ops_applied": 0,
        "last_ops_flagged": 0,
        "last_error": None,
    }


def save_repair_status(workspace: str | Path, status: dict) -> None:
    path = _status_file_path(workspace)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(status, indent=2), encoding="utf-8")
    except Exception:
        pass


def build_adapter(harness: str) -> HarnessAdapter:
    if harness == "claude_code":
        return ClaudeCodeAdapter()
    raise ValueError(f"Unsupported harness: {harness!r} (Phase 1 ships claude_code only)")


async def run_repair(
    adapter: HarnessAdapter | None = None,
    *,
    harness: str = "claude_code",
    dry_run: bool = True,
    workspace: str | Path = ".",
    snapshot_dir: str | Path = ".frood/memory-repair-snapshots",
    audit_log: str | Path = ".frood/memory-repair-log.jsonl",
    enable_semantic: bool = False,
    enable_llm: bool = False,
    auto_threshold: float = 0.95,
    flag_threshold: float = 0.85,
) -> RepairResult:
    """Run the deterministic repair pipeline against one harness."""

    started = datetime.now(UTC)
    adapter = adapter or build_adapter(harness)
    workspace_path = Path(workspace)
    snapshot_path = _resolve_under(workspace_path, snapshot_dir)
    audit_path = _resolve_under(workspace_path, audit_log)

    executor = RepairExecutor(
        adapter=adapter,
        workspace=workspace_path,
        snapshot_dir=snapshot_path,
        audit_log=audit_path,
        dry_run=dry_run,
    )

    total_proposed = 0
    total_applied = 0
    total_flagged = 0
    total_skipped = 0
    plans_scanned = 0
    last_error: str | None = None

    try:
        projects = await adapter.list_projects()
    except Exception as exc:
        logger.warning("memory-repair: list_projects failed: %s", exc)
        return RepairResult(
            harness=adapter.harness_name,
            dry_run=dry_run,
            started_at=started,
            finished_at=datetime.now(UTC),
            error=str(exc),
        )

    for project in projects:
        plans_scanned += 1
        try:
            index = await adapter.read_index(project)
            files = await adapter.list_memory_files(project)
            ops = await run_checks(
                adapter,
                project,
                index,
                files,
                enable_semantic=enable_semantic,
                enable_llm=enable_llm,
                auto_threshold=auto_threshold,
                flag_threshold=flag_threshold,
            )
        except Exception as exc:
            logger.warning("memory-repair: scan failed for %s: %s", project, exc)
            last_error = f"scan {project}: {exc}"
            continue

        if not ops:
            continue

        plan = RepairPlan(harness=adapter.harness_name, project_root=project, ops=ops)
        total_proposed += len(ops)
        try:
            applied, flagged, skipped = await executor.apply(plan)
        except Exception as exc:
            logger.warning("memory-repair: apply failed for %s: %s", project, exc)
            last_error = f"apply {project}: {exc}"
            continue

        total_applied += applied
        total_flagged += flagged
        total_skipped += skipped

    finished = datetime.now(UTC)

    _update_status(
        workspace_path,
        applied=total_applied,
        flagged=total_flagged,
        error=last_error,
    )

    return RepairResult(
        harness=adapter.harness_name,
        dry_run=dry_run,
        started_at=started,
        finished_at=finished,
        plans_scanned=plans_scanned,
        ops_proposed=total_proposed,
        ops_applied=total_applied,
        ops_flagged=total_flagged,
        ops_skipped=total_skipped,
        snapshot_dir=str(executor.snapshot_dir) if executor.snapshot_dir else None,
        error=last_error,
    )


def should_trigger_repair(workspace: str | Path, trigger_count: int) -> bool:
    """Return True if this Stop tick should invoke the repair worker."""

    status = load_repair_status(workspace)
    count = int(status.get("runs_since_last_trigger") or 0) + 1
    status["runs_since_last_trigger"] = count
    save_repair_status(workspace, status)
    return count >= max(1, trigger_count)


def _resolve_under(workspace: Path, maybe_rel: str | Path) -> Path:
    p = Path(maybe_rel)
    return p if p.is_absolute() else (workspace / p)


def _update_status(
    workspace: Path,
    applied: int,
    flagged: int,
    error: str | None,
) -> None:
    status = load_repair_status(workspace)
    status["last_run"] = time.time()
    status["last_ops_applied"] = applied
    status["last_ops_flagged"] = flagged
    status["last_error"] = error
    status["runs_since_last_trigger"] = 0
    save_repair_status(workspace, status)
