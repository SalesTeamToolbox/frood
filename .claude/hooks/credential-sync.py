#!/usr/bin/env python3
# hook_event: SessionStart
# hook_timeout: 15
"""Sync Claude Code credentials to remote VPS on session start.

Checks if the remote node has stale or missing CC credentials and
syncs the local ~/.claude/.credentials.json if needed. Runs silently
in the background — only outputs to stderr on actual sync or errors.

Requires SSH alias configured (reads from .env FROOD_SSH_ALIAS or
defaults to 'frood-prod').

Hook protocol:
- Receives JSON on stdin with hook_event_name, project_dir
- Output to stderr is shown to Claude as feedback
- Exit code 0 = always allow
"""

import json
import os
import subprocess
import sys
import time


def main():
    try:
        hook_data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        hook_data = {}

    project_dir = hook_data.get("project_dir", os.getcwd())

    # Load SSH alias from .env or default
    ssh_alias = os.environ.get("FROOD_SSH_ALIAS", "")
    if not ssh_alias:
        env_path = os.path.join(project_dir, ".env")
        if os.path.isfile(env_path):
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("FROOD_SSH_ALIAS="):
                        ssh_alias = line.split("=", 1)[1].strip().strip("\"'")
                        break
    if not ssh_alias:
        ssh_alias = "frood-prod"

    # Check if local credentials exist
    local_creds = os.path.expanduser("~/.claude/.credentials.json")
    if not os.path.isfile(local_creds):
        return  # No local credentials, nothing to sync

    # Read local credentials to get expiry
    try:
        with open(local_creds) as f:
            local_data = json.load(f)
        local_expiry = local_data.get("claudeAiOauth", {}).get("expiresAt", 0)
    except (json.JSONDecodeError, OSError):
        return  # Can't read local credentials

    if not local_expiry:
        return  # No OAuth data

    # Check remote credentials expiry (fast SSH command)
    try:
        result = subprocess.run(
            [
                "ssh",
                "-o",
                "ConnectTimeout=5",
                "-o",
                "BatchMode=yes",
                ssh_alias,
                "python3 -c \"import json; d=json.load(open(\\\"$HOME/.claude/.credentials.json\\\")); print(d.get('claudeAiOauth',{}).get('expiresAt',0))\" 2>/dev/null || echo 0",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        remote_expiry = int(result.stdout.strip() or "0")
    except (subprocess.TimeoutExpired, ValueError, OSError):
        remote_expiry = 0

    # Sync if: remote has no credentials, remote is expired, or local is newer
    now_ms = int(time.time() * 1000)
    needs_sync = False
    reason = ""

    if remote_expiry == 0:
        needs_sync = True
        reason = "no remote credentials"
    elif remote_expiry < now_ms:
        needs_sync = True
        reason = "remote credentials expired"
    elif local_expiry > remote_expiry + 60000:  # Local is >1min newer
        needs_sync = True
        reason = "local credentials are newer"

    if not needs_sync:
        return  # Remote is fine

    # Sync via scp
    try:
        result = subprocess.run(
            [
                "scp",
                "-o",
                "ConnectTimeout=5",
                "-o",
                "BatchMode=yes",
                local_creds,
                f"{ssh_alias}:~/.claude/.credentials.json",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0:
            print(
                f"CC credentials synced to {ssh_alias} ({reason})",
                file=sys.stderr,
            )
        else:
            print(
                f"CC credential sync failed: {result.stderr.strip()[:100]}",
                file=sys.stderr,
            )
    except subprocess.TimeoutExpired:
        print("CC credential sync timed out", file=sys.stderr)
    except OSError as e:
        print(f"CC credential sync error: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
