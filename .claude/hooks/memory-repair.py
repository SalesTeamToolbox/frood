#!/usr/bin/env python3
# hook_event: PostCompact|Stop
# hook_matcher: *
# hook_timeout: 5
"""Memory-repair hook — triggers the repair worker after compaction + on Stop.

Fires on:
- PostCompact: always (Claude Code just reshaped context — ideal repair moment)
- Stop: only every Nth invocation, gated by a counter in
  ``.frood/memory-repair-status.json``. N defaults to 5 and is controlled by
  MEMORY_REPAIR_STOP_TRIGGER_COUNT in Settings.

Stdlib-only; spawns a detached worker so CC is never blocked. Mirrors the
cc-memory-sync.py shim pattern.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
STATUS_FILE = REPO_ROOT / ".frood" / "memory-repair-status.json"


def _load_status() -> dict:
    try:
        if STATUS_FILE.exists():
            return json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_status(status: dict) -> None:
    try:
        STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATUS_FILE.write_text(json.dumps(status, indent=2), encoding="utf-8")
    except Exception:
        pass


def _should_fire(hook_event: str) -> bool:
    """Decide whether to spawn the worker for this hook tick.

    PostCompact -> always fire.
    Stop        -> fire only when the stdlib-maintained counter hits the
                   configured threshold, then reset it.
    """
    if hook_event == "PostCompact":
        return True
    if hook_event != "Stop":
        return False

    try:
        trigger = int(os.getenv("MEMORY_REPAIR_STOP_TRIGGER_COUNT", "5"))
    except ValueError:
        trigger = 5
    trigger = max(1, trigger)

    status = _load_status()
    count = int(status.get("runs_since_last_trigger") or 0) + 1
    if count >= trigger:
        status["runs_since_last_trigger"] = 0
        _save_status(status)
        return True
    status["runs_since_last_trigger"] = count
    _save_status(status)
    return False


def main() -> None:
    try:
        event = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    if os.getenv("MEMORY_REPAIR_ENABLED", "true").lower() not in ("true", "1", "yes"):
        sys.exit(0)

    hook_event = event.get("hook_event_name", "")
    if not _should_fire(hook_event):
        sys.exit(0)

    worker = Path(__file__).parent / "memory-repair-worker.py"
    if not worker.exists():
        sys.exit(0)

    creation_flags = 0
    if sys.platform == "win32":
        creation_flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP

    try:
        subprocess.Popen(
            [sys.executable, str(worker), hook_event],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=(sys.platform != "win32"),
            creationflags=creation_flags,
        )
        print(
            f"[frood-memory] Repair: scanning CC memory (background, {hook_event})", file=sys.stderr
        )
    except Exception:
        pass

    sys.exit(0)


if __name__ == "__main__":
    main()
