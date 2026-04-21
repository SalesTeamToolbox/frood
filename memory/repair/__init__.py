"""Automated memory repair pipeline (Phase 1: deterministic CC flat-file checks)."""

from memory.repair.adapters import ClaudeCodeAdapter, HarnessAdapter
from memory.repair.models import (
    IndexEntry,
    IndexModel,
    RepairAuditRecord,
    RepairOp,
    RepairPlan,
    RepairResult,
)
from memory.repair.worker import (
    build_adapter,
    load_repair_status,
    run_repair,
    save_repair_status,
    should_trigger_repair,
)

__all__ = [
    "ClaudeCodeAdapter",
    "HarnessAdapter",
    "IndexEntry",
    "IndexModel",
    "RepairAuditRecord",
    "RepairOp",
    "RepairPlan",
    "RepairResult",
    "build_adapter",
    "load_repair_status",
    "run_repair",
    "save_repair_status",
    "should_trigger_repair",
]
