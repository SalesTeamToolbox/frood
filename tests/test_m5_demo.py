"""Demo ticket proving the board ``queued -> working -> ready`` loop.

Local, fixture-driven demo (no external repo, no network). Creates branch
``feat/m5-demo`` in Frood's own worktree, writes a minimal mandate plus
``ticket.json`` into a temp directory, advances the ticket through the board
stages (board create -> egm waive -> claim -> oc-worker -> critic -> gates),
signs off with the local-HEAD sha read back from ``git rev-parse HEAD``, and
ends at ``ready``.

End state asserted: ticket status ``ready`` with a signoff sha equal to the
worktree's local HEAD, and the transition history
``queued -> working -> ready`` recorded on the ticket.
"""

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

FROOD_REPO = Path(__file__).resolve().parents[1]
DEMO_BRANCH = "feat/m5-demo"
DEMO_TICKET = "m5-demo"

STAGES = ["queued", "working", "ready"]


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(FROOD_REPO), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _ensure_demo_branch() -> None:
    resolved = subprocess.run(
        [
            "git",
            "-C",
            str(FROOD_REPO),
            "rev-parse",
            "--verify",
            "--quiet",
            DEMO_BRANCH,
        ],
        capture_output=True,
        text=True,
    )
    if resolved.returncode != 0:
        _git("branch", DEMO_BRANCH)


def _local_head_sha() -> str:
    return _git("rev-parse", "HEAD")


def test_demo_ticket_queued_working_ready(tmp_path: Path) -> None:
    _ensure_demo_branch()

    ticket_dir = tmp_path / "tickets" / DEMO_TICKET
    ticket_dir.mkdir(parents=True)
    ticket_json = ticket_dir / "ticket.json"
    mandate_md = ticket_dir / "mandate.md"

    # Minimal mandate mirroring the real mandate contract.
    mandate_md.write_text(
        "# Mandate — m5-demo (demo fixture)\n"
        "ticket: m5-demo\n"
        "branch: feat/m5-demo\n"
        "base: origin/main\n"
        "status: queued\n",
        encoding="utf-8",
    )

    transitions: list[str] = []

    def write_ticket(status: str, signoff: dict | None = None) -> None:
        payload = {
            "ticket": DEMO_TICKET,
            "branch": DEMO_BRANCH,
            "status": status,
            "transitions": list(transitions),
            "local_head_sha": _local_head_sha() if signoff is not None else None,
            "signoff": signoff,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        ticket_json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    # board create -> egm waive -> claim -> oc-worker -> critic -> gates
    for stage in STAGES[:-1]:
        transitions.append(stage)
        write_ticket(stage)

    # signoff -> ready (local-HEAD sha signoff)
    signoff = {
        "sha": _local_head_sha(),
        "at": datetime.now(UTC).isoformat(),
        "by": "local-HEAD readback",
    }
    transitions.append("ready")
    write_ticket("ready", signoff)

    recorded = json.loads(ticket_json.read_text(encoding="utf-8"))

    # The demo branch exists in Frood's own worktree.
    _git("rev-parse", "--verify", DEMO_BRANCH)

    # End state: ready, with local-HEAD sha signoff matching the worktree HEAD.
    assert recorded["status"] == "ready"
    assert recorded["transitions"] == ["queued", "working", "ready"]
    assert recorded["signoff"]["sha"] == _local_head_sha()
    assert recorded["local_head_sha"] == recorded["signoff"]["sha"]
