#!/usr/bin/env python3
# hook_event: Stop
# hook_matcher: *
# hook_timeout: 10
"""Cleanup orphaned subagent processes on session stop.

Finds claude.exe processes running with --permission-mode bypassPermissions
that have no active parent session, and terminates them.

Hook protocol:
- Runs on Stop event
- Output to stderr is shown to Claude as feedback
- Exit code 0 = success
"""

import subprocess
import sys


def get_claude_processes():
    """Get all claude.exe processes with their PIDs and command lines."""
    try:
        result = subprocess.run(
            [
                "wmic",
                "process",
                "where",
                "name='claude.exe'",
                "get",
                "ProcessId,ParentProcessId,CommandLine",
                "/format:csv",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        processes = []
        for line in result.stdout.strip().split("\n"):
            line = line.strip()
            if not line or line.startswith("Node"):
                continue
            parts = line.split(",")
            if len(parts) >= 4:
                cmd = ",".join(parts[1:-2])
                ppid = parts[-2]
                pid = parts[-1]
                processes.append({"pid": pid, "ppid": ppid, "cmd": cmd})
        return processes
    except Exception:
        return []


def get_running_pids():
    """Get set of all running PIDs."""
    try:
        result = subprocess.run(
            ["wmic", "process", "get", "ProcessId", "/format:csv"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        pids = set()
        for line in result.stdout.strip().split("\n"):
            line = line.strip()
            if not line or line.startswith("Node"):
                continue
            parts = line.split(",")
            if len(parts) >= 2:
                pids.add(parts[-1].strip())
        return pids
    except Exception:
        return set()


def main():
    # Only run on Windows
    if sys.platform != "win32" and not sys.platform.startswith("cygwin"):
        return

    processes = get_claude_processes()
    running_pids = get_running_pids()

    # Find subagent processes (bypassPermissions, no --resume flag)
    subagents = []
    for proc in processes:
        cmd = proc["cmd"]
        if "bypassPermissions" in cmd and "--resume" not in cmd:
            subagents.append(proc)

    if not subagents:
        return

    # Find orphans: subagents whose parent PID is no longer running
    # (or whose parent is not a claude.exe session)
    session_pids = set()
    for proc in processes:
        if "--resume" in proc["cmd"]:
            session_pids.add(proc["pid"])

    orphans = []
    for sa in subagents:
        if sa["ppid"] not in running_pids or sa["ppid"] not in session_pids:
            orphans.append(sa)

    if orphans:
        killed = 0
        for orphan in orphans:
            try:
                subprocess.run(
                    ["taskkill", "/PID", orphan["pid"], "/F"], capture_output=True, timeout=5
                )
                killed += 1
            except Exception:
                pass

        if killed:
            print(f"Cleaned up {killed} orphaned subagent process(es)", file=sys.stderr)


if __name__ == "__main__":
    main()
