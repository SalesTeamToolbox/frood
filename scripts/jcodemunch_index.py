#!/usr/bin/env python3
"""Index a project directory via jcodemunch MCP JSON-RPC over stdio.

Usage: python scripts/jcodemunch_index.py <project_dir> [--timeout=120]

Exit codes:
  0 — indexing succeeded
  1 — indexing failed (timeout, uvx missing, protocol error)
"""

import json
import os
import shutil
import subprocess
import sys
import threading


def ensure_uvx():
    """Check uvx is available; install uv via pip if not."""
    if shutil.which("uvx"):
        return True
    # Try installing uv via pip (using the venv's pip if available)
    pip = os.path.join(os.path.dirname(sys.executable), "pip")
    if not os.path.isfile(pip):
        pip = "pip"
    try:
        subprocess.run([pip, "install", "uv"], capture_output=True, timeout=60)
        return shutil.which("uvx") is not None
    except Exception:
        return False


def index_project(project_dir: str, timeout: int = 120) -> bool:
    """Send MCP initialize + index_folder to jcodemunch-mcp.

    Spawns `uvx jcodemunch-mcp` as a subprocess, performs the MCP handshake,
    and calls tools/call index_folder. Returns True on success, False on any
    failure (timeout, missing uvx, protocol error).

    Args:
        project_dir: Absolute or relative path to index.
        timeout:     Seconds to wait for the index_folder response.

    Returns:
        True if indexing succeeded, False otherwise.
    """
    if not ensure_uvx():
        print("ERROR: uvx not found and could not be installed", file=sys.stderr)
        return False

    try:
        proc = subprocess.Popen(
            ["uvx", "jcodemunch-mcp"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except Exception as e:
        print(f"ERROR: could not start jcodemunch-mcp: {e}", file=sys.stderr)
        return False

    # MCP initialize (id=1)
    init_msg = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "agent42-setup", "version": "1.0"},
        },
    }
    # Notification: initialized (no id — no response expected)
    notif_msg = {
        "jsonrpc": "2.0",
        "method": "notifications/initialized",
        "params": {},
    }
    # tools/call index_folder (id=2)
    call_msg = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "index_folder",
            "arguments": {"path": os.path.abspath(project_dir), "incremental": False},
        },
    }

    try:
        proc.stdin.write(json.dumps(init_msg) + "\n")
        proc.stdin.write(json.dumps(notif_msg) + "\n")
        proc.stdin.write(json.dumps(call_msg) + "\n")
        proc.stdin.flush()
    except BrokenPipeError:
        print("ERROR: jcodemunch-mcp process died during write", file=sys.stderr)
        proc.kill()
        return False

    # Read responses with timeout — wait for id=2 (index_folder response)
    success = False

    def read_responses():
        nonlocal success
        try:
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                    if msg.get("id") == 2:
                        # index_folder response
                        if "result" in msg:
                            success = True
                        elif "error" in msg:
                            print(f"ERROR: {msg['error']}", file=sys.stderr)
                        return
                except json.JSONDecodeError:
                    continue
        except Exception:
            pass

    reader = threading.Thread(target=read_responses, daemon=True)
    reader.start()
    reader.join(timeout=timeout)

    if reader.is_alive():
        print(f"ERROR: jcodemunch indexing timed out after {timeout}s", file=sys.stderr)
        proc.kill()
        return False

    try:
        proc.stdin.close()
    except Exception:
        pass
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()

    return success


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <project_dir> [--timeout=120]", file=sys.stderr)
        sys.exit(1)

    project_dir = sys.argv[1]
    timeout = 120
    for arg in sys.argv[2:]:
        if arg.startswith("--timeout="):
            try:
                timeout = int(arg.split("=", 1)[1])
            except ValueError:
                pass

    if index_project(project_dir, timeout):
        print("jcodemunch indexing complete")
        sys.exit(0)
    else:
        print("jcodemunch indexing failed", file=sys.stderr)
        sys.exit(1)
