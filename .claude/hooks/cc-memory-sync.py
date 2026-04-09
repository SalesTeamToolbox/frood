#!/usr/bin/env python3
# hook_event: PostToolUse
# hook_matcher: Write|Edit
# hook_timeout: 5
"""CC memory auto-sync hook — detects CC memory file writes and spawns worker.

Triggered on PostToolUse for Write/Edit operations. When a CC memory file
(~/.claude/projects/*/memory/*.md) is written, spawns a detached background
worker to embed the content with ONNX and upsert it to Qdrant.

This file uses ONLY Python stdlib — zero Frood imports — so startup is < 5ms.

Hook protocol:
- Receives JSON on stdin with hook_event_name, tool_name, tool_input
- Output to stderr is shown to Claude as feedback
- Exit code 0 = always allow (SYNC-04: Qdrant unavailability never blocks CC)
"""

import json
import subprocess
import sys
from pathlib import Path


def is_cc_memory_file(file_path: str) -> bool:
    """Check if file_path is a Claude Code memory file.

    Matches paths matching: ~/.claude/projects/*/memory/*.md
    Works with both Windows (backslash) and Unix (forward-slash) paths.

    Returns True if:
    - Path contains a `.claude` component
    - Followed immediately by `projects`
    - Then any project name
    - Then `memory`
    - And the file has a .md extension
    """
    if not file_path:
        return False

    try:
        p = Path(file_path)
    except (TypeError, ValueError):
        return False

    # Must be a .md file
    if p.suffix.lower() != ".md":
        return False

    # Split into parts and find ".claude"
    parts = p.parts
    try:
        idx = parts.index(".claude")
    except ValueError:
        return False

    # Need at least: .claude / projects / <proj> / memory / <file>
    # So idx + 4 must be valid (the file itself is the last part)
    if idx + 4 >= len(parts):
        return False

    # Verify structure: .claude/projects/<proj>/memory/
    if parts[idx + 1] != "projects":
        return False
    # parts[idx + 2] is the project name (any)
    if parts[idx + 3] != "memory":
        return False

    return True


def main():
    try:
        event = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    tool_name = event.get("tool_name", "")
    if tool_name not in ("Write", "Edit"):
        sys.exit(0)

    tool_input = event.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    if not file_path or not is_cc_memory_file(file_path):
        sys.exit(0)

    # Resolve worker path relative to this hook file
    worker = Path(__file__).parent / "cc-memory-sync-worker.py"
    if not worker.exists():
        sys.exit(0)

    filename = Path(file_path).name

    # Spawn detached subprocess so CC Write tool is never blocked
    creation_flags = 0
    if sys.platform == "win32":
        creation_flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP

    try:
        subprocess.Popen(
            [sys.executable, str(worker), file_path],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=(sys.platform != "win32"),
            creationflags=creation_flags,
        )
        print(
            f"[frood-memory] Sync: embedding {filename} to Qdrant (background)", file=sys.stderr
        )
    except Exception:
        print(f"[frood-memory] Sync: failed to spawn worker for {filename}", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
