"""Work order management for the cowork system.

Work orders define tasks that can be executed autonomously on a remote
VPS running Claude Code with Frood MCP. Stored as JSON files in
.planning/work-orders/.

Usage (CLI):
    python -m core.work_order create --branch feat/x --prompt "Build caching"
    python -m core.work_order list
    python -m core.work_order get <id>
    python -m core.work_order update <id> --status completed
    python -m core.work_order recall <id>
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

WORK_ORDERS_DIR = ".planning/work-orders"

# Valid status transitions
VALID_TRANSITIONS = {
    "pending": ["in-progress", "cancelled"],
    "in-progress": ["completed", "recalled", "failed", "pending"],
    "completed": [],
    "recalled": ["pending"],  # can re-queue after recall
    "failed": ["pending"],  # can retry
    "cancelled": ["pending"],
}


@dataclass
class WorkOrderConstraints:
    max_turns: int = 30
    max_sessions: int = 10
    no_touch: list[str] = field(default_factory=list)
    must_run: str = "python -m pytest tests/ -x -q"
    timeout_minutes: int = 120


@dataclass
class WorkOrderProgress:
    sessions_completed: int = 0
    files_modified: list[str] = field(default_factory=list)
    commits: list[str] = field(default_factory=list)
    last_update: str = ""
    error: str = ""


@dataclass
class WorkOrder:
    id: str
    status: str = "pending"
    branch: str = ""
    prompt: str = ""
    plan_path: str = ""
    acceptance_criteria: list[str] = field(default_factory=list)
    constraints: WorkOrderConstraints = field(default_factory=WorkOrderConstraints)
    progress: WorkOrderProgress = field(default_factory=WorkOrderProgress)
    created: str = ""
    updated: str = ""
    created_by: str = "laptop"
    recalled_at: str = ""

    def __post_init__(self):
        now = datetime.now(UTC).isoformat()
        if not self.created:
            self.created = now
        if not self.updated:
            self.updated = now

    def transition(self, new_status: str) -> None:
        allowed = VALID_TRANSITIONS.get(self.status, [])
        if new_status not in allowed:
            raise ValueError(
                f"Cannot transition from '{self.status}' to '{new_status}'. Allowed: {allowed}"
            )
        self.status = new_status
        self.updated = datetime.now(UTC).isoformat()
        if new_status == "recalled":
            self.recalled_at = self.updated

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> WorkOrder:
        constraints = WorkOrderConstraints(**data.pop("constraints", {}))
        progress = WorkOrderProgress(**data.pop("progress", {}))
        return cls(constraints=constraints, progress=progress, **data)

    def save(self, base_dir: str = ".") -> Path:
        """Save work order to JSON file."""
        wo_dir = Path(base_dir) / WORK_ORDERS_DIR
        wo_dir.mkdir(parents=True, exist_ok=True)
        path = wo_dir / f"{self.id}.json"
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)
        return path

    @classmethod
    def load(cls, wo_id: str, base_dir: str = ".") -> WorkOrder:
        """Load work order from JSON file."""
        path = Path(base_dir) / WORK_ORDERS_DIR / f"{wo_id}.json"
        if not path.exists():
            raise FileNotFoundError(f"Work order not found: {path}")
        with open(path) as f:
            return cls.from_dict(json.load(f))

    @staticmethod
    def list_all(base_dir: str = ".", status_filter: str | None = None) -> list[WorkOrder]:
        """List all work orders, optionally filtered by status."""
        wo_dir = Path(base_dir) / WORK_ORDERS_DIR
        if not wo_dir.exists():
            return []
        orders = []
        for path in sorted(wo_dir.glob("*.json")):
            if path.name.startswith("."):
                continue
            try:
                with open(path) as f:
                    wo = WorkOrder.from_dict(json.load(f))
                if status_filter is None or wo.status == status_filter:
                    orders.append(wo)
            except (json.JSONDecodeError, TypeError, KeyError):
                continue
        return orders

    def build_prompt(self) -> str:
        """Build the prompt string for Claude Code execution."""
        parts = []

        if self.plan_path:
            parts.append(f"Read the plan at `{self.plan_path}` and execute it phase by phase.")
        elif self.prompt:
            parts.append(self.prompt)

        if self.acceptance_criteria:
            parts.append("\n## Acceptance Criteria")
            for criterion in self.acceptance_criteria:
                parts.append(f"- {criterion}")

        if self.constraints.must_run:
            parts.append(f"\nAfter each significant change, run: `{self.constraints.must_run}`")

        if self.constraints.no_touch:
            parts.append(
                "\n## Do NOT modify these files:\n"
                + "\n".join(f"- `{f}`" for f in self.constraints.no_touch)
            )

        parts.append(
            "\nCommit after each completed phase or logical unit of work. "
            "Use descriptive commit messages."
        )

        parts.append(
            "\nWhen ALL work is complete and tests pass, create a file "
            "`.claude/handoff-complete` containing 'done'."
        )

        return "\n".join(parts)


# ── CLI ─────────────────────────────────────────────────────────────


def cmd_create(args):
    wo_id = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    wo = WorkOrder(
        id=wo_id,
        branch=args.branch or "",
        prompt=args.prompt or "",
        plan_path=args.plan or "",
        acceptance_criteria=args.criteria or [],
        constraints=WorkOrderConstraints(
            max_turns=args.max_turns,
            max_sessions=args.max_sessions,
            no_touch=args.no_touch or [],
            must_run=args.must_run,
            timeout_minutes=args.timeout,
        ),
    )
    path = wo.save(args.base_dir)
    print(json.dumps({"id": wo.id, "path": str(path), "status": wo.status}))


def cmd_list(args):
    orders = WorkOrder.list_all(args.base_dir, args.status)
    for wo in orders:
        print(f"{wo.id}  {wo.status:12s}  {wo.branch:30s}  {wo.prompt[:50]}")


def cmd_get(args):
    wo = WorkOrder.load(args.id, args.base_dir)
    print(json.dumps(wo.to_dict(), indent=2))


def cmd_update(args):
    wo = WorkOrder.load(args.id, args.base_dir)
    if args.status:
        wo.transition(args.status)
    if args.error:
        wo.progress.error = args.error
    if args.add_commit:
        wo.progress.commits.append(args.add_commit)
    if args.add_file:
        if args.add_file not in wo.progress.files_modified:
            wo.progress.files_modified.append(args.add_file)
    if args.sessions is not None:
        wo.progress.sessions_completed = args.sessions
    wo.progress.last_update = datetime.now(UTC).isoformat()
    wo.save(args.base_dir)
    print(json.dumps({"id": wo.id, "status": wo.status}))


def cmd_recall(args):
    wo = WorkOrder.load(args.id, args.base_dir)
    wo.transition("recalled")
    wo.save(args.base_dir)
    print(json.dumps({"id": wo.id, "status": "recalled", "recalled_at": wo.recalled_at}))


def cmd_prompt(args):
    """Output the built prompt for a work order (used by daemon)."""
    wo = WorkOrder.load(args.id, args.base_dir)
    print(wo.build_prompt())


def main():
    parser = argparse.ArgumentParser(description="Work order management")
    parser.add_argument("--base-dir", default=".", help="Repository root")
    sub = parser.add_subparsers(dest="command", required=True)

    # create
    p = sub.add_parser("create")
    p.add_argument("--branch", default="")
    p.add_argument("--prompt", default="")
    p.add_argument("--plan", default="")
    p.add_argument("--criteria", nargs="*")
    p.add_argument("--no-touch", nargs="*")
    p.add_argument("--must-run", default="python -m pytest tests/ -x -q")
    p.add_argument("--max-turns", type=int, default=30)
    p.add_argument("--max-sessions", type=int, default=10)
    p.add_argument("--timeout", type=int, default=120)
    p.set_defaults(func=cmd_create)

    # list
    p = sub.add_parser("list")
    p.add_argument("--status", default=None)
    p.set_defaults(func=cmd_list)

    # get
    p = sub.add_parser("get")
    p.add_argument("id")
    p.set_defaults(func=cmd_get)

    # update
    p = sub.add_parser("update")
    p.add_argument("id")
    p.add_argument("--status", default=None)
    p.add_argument("--error", default=None)
    p.add_argument("--add-commit", default=None)
    p.add_argument("--add-file", default=None)
    p.add_argument("--sessions", type=int, default=None)
    p.set_defaults(func=cmd_update)

    # recall
    p = sub.add_parser("recall")
    p.add_argument("id")
    p.set_defaults(func=cmd_recall)

    # prompt
    p = sub.add_parser("prompt")
    p.add_argument("id")
    p.set_defaults(func=cmd_prompt)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
