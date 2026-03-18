#!/usr/bin/env python3
# hook_event: PostToolUse
# hook_event: Stop
# hook_timeout: 10
"""Auto-reindex jcodemunch when structural file changes or drift are detected.

Handles two event types:

1. **Stop event** — Checks if Python files were created or deleted during the
   session, which indicates refactoring that would make the jcodemunch index
   stale. First attempt blocks (exit 2) and tells Claude to re-index. Second
   attempt allows (exit 0) via marker file.

2. **PostToolUse event** — Checks jcodemunch get_symbol responses for
   content_verified=false, indicating source code has drifted since indexing.
   Emits an advisory re-index recommendation (always exit 0, never blocks).

Hook protocol:
- Receives JSON on stdin with hook_event_name, project_dir, tool_uses/tool_output
- Output to stderr is shown to Claude as feedback
- Exit code 0 = allow, exit code 2 = block (Stop structural changes only)
"""

import json
import os
import re
import sys
import time

# Threshold: how many structural changes (creates/deletes) trigger re-index
STRUCTURAL_CHANGE_THRESHOLD = 1

# Marker file to prevent infinite blocking
MARKER_FILENAME = ".jcodemunch-reindex-pending"

# Stats file written by jcodemunch-token-tracker.py
STATS_FILENAME = ".jcodemunch-stats.json"


def format_tokens(count):
    """Format token count for display."""
    if count >= 1000:
        return f"{count / 1000:.1f}K"
    return str(count)


def print_session_summary(stats_path):
    """Print jcodemunch usage summary for the session."""
    try:
        with open(stats_path) as f:
            stats = json.load(f)
    except (OSError, json.JSONDecodeError):
        return

    calls = stats.get("calls", 0)
    if calls == 0:
        return

    saved = stats.get("tokens_saved", 0)
    used = stats.get("tokens_used", 0)
    files = stats.get("files_targeted", 0)
    breakdown = stats.get("tool_breakdown", {})

    print(
        f"\n{'=' * 52}\n"
        f"  jcodemunch Session Summary\n"
        f"{'=' * 52}\n"
        f"  Calls:          {calls}\n"
        f"  Files targeted: {files}\n"
        f"  Tokens used:    ~{format_tokens(used)}\n"
        f"  Tokens saved:   ~{format_tokens(saved)}\n"
        f"{'─' * 52}",
        file=sys.stderr,
    )

    if breakdown:
        print("  Breakdown:", file=sys.stderr)
        for tool, data in sorted(breakdown.items()):
            print(
                f"    {tool}: {data['calls']} call(s), ~{format_tokens(data['saved'])} saved",
                file=sys.stderr,
            )

    # Savings percentage
    total_would_have = used + saved
    if total_would_have > 0:
        pct = (saved / total_would_have) * 100
        print(
            f"{'─' * 52}\n"
            f"  Efficiency: {pct:.0f}% token reduction vs full file reads\n"
            f"{'=' * 52}\n",
            file=sys.stderr,
        )

    # Clean up stats file after reporting
    try:
        os.remove(stats_path)
    except OSError:
        pass


def normalize_path(path, project_dir):
    """Normalize a file path to a project-relative POSIX-style path."""
    if sys.platform == "win32" and re.match(r"^/([a-zA-Z])/", path):
        path = path[1].upper() + ":" + path[2:]
    path = os.path.normpath(path)
    project_dir = os.path.normpath(project_dir)
    if path.startswith(project_dir):
        path = path[len(project_dir) :].lstrip(os.sep)
    return path.replace("\\", "/")


def check_drift(tool_name, tool_output):
    """Check if a jcodemunch get_symbol response indicates source drift.

    Returns True if tool_name contains 'get_symbol' and tool_output has
    _meta.content_verified explicitly set to False. Returns False for all
    other cases (non-get_symbol tools, missing _meta, malformed output).

    Args:
        tool_name: The MCP tool name (e.g. 'mcp__jcodemunch__get_symbol').
        tool_output: The tool response (dict, JSON string, or other).

    Returns:
        True if drift detected, False otherwise.
    """
    if "get_symbol" not in (tool_name or ""):
        return False

    # Parse JSON string if needed
    if isinstance(tool_output, str):
        try:
            tool_output = json.loads(tool_output)
        except (json.JSONDecodeError, TypeError):
            return False

    if not isinstance(tool_output, dict):
        return False

    meta = tool_output.get("_meta", {})
    if not isinstance(meta, dict):
        return False

    return meta.get("content_verified") is False


def extract_structural_changes(event, project_dir):
    """Extract created and deleted Python files from tool_uses."""
    created = set()
    deleted = set()

    for tool_use in event.get("tool_uses", []):
        tool_name = tool_use.get("tool_name", "")
        tool_input = tool_use.get("tool_input", {})

        # Write tool = new file created
        if tool_name == "Write":
            file_path = tool_input.get("file_path", "")
            if file_path and file_path.endswith(".py"):
                created.add(normalize_path(file_path, project_dir))

        # Bash commands that delete/move files
        if tool_name == "Bash":
            cmd = tool_input.get("command", "")
            if any(kw in cmd for kw in ["rm ", "mv ", "git mv", "rename"]):
                deleted.add(cmd)  # approximate — just need to know it happened

    return created, deleted


def main():
    try:
        event = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    hook_event = event.get("hook_event_name", "")
    project_dir = event.get("project_dir", ".")

    # Handle PostToolUse: drift detection for jcodemunch get_symbol responses
    if hook_event == "PostToolUse":
        tool_name = event.get("tool_name", "")
        if "jcodemunch" in tool_name:
            tool_output = event.get("tool_output", {})
            if check_drift(tool_name, tool_output):
                file_info = ""
                if isinstance(tool_output, dict):
                    file_info = tool_output.get("file_path", "")
                if sys.platform == "win32" and re.match(r"^/([a-zA-Z])/", project_dir):
                    project_dir = project_dir[1].upper() + ":" + project_dir[2:]
                project_dir = os.path.normpath(project_dir)
                print(
                    f"[jcodemunch] Source drift detected"
                    f"{' in ' + file_info if file_info else ''}! "
                    "Index is stale. Consider re-indexing:\n"
                    "  Call mcp__jcodemunch__index_folder with:\n"
                    f'    path: "{project_dir}"\n'
                    "    incremental: true",
                    file=sys.stderr,
                )
        sys.exit(0)  # Advisory only, never block

    # Existing Stop event handling continues below
    if hook_event != "Stop":
        sys.exit(0)

    project_dir = event.get("project_dir", ".")
    if sys.platform == "win32" and re.match(r"^/([a-zA-Z])/", project_dir):
        project_dir = project_dir[1].upper() + ":" + project_dir[2:]
    project_dir = os.path.normpath(project_dir)

    claude_dir = os.path.join(project_dir, ".claude")
    marker_path = os.path.join(claude_dir, MARKER_FILENAME)
    stats_path = os.path.join(claude_dir, STATS_FILENAME)

    # Print session summary if stats exist
    print_session_summary(stats_path)

    # If marker exists, this is the second stop attempt — allow it
    if os.path.exists(marker_path):
        try:
            os.remove(marker_path)
        except OSError:
            pass
        print(
            "[jcodemunch] Re-index marker cleared — proceeding with stop.",
            file=sys.stderr,
        )
        sys.exit(0)

    # Check for structural changes
    created, deleted = extract_structural_changes(event, project_dir)

    structural_count = len(created) + len(deleted)

    if structural_count < STRUCTURAL_CHANGE_THRESHOLD:
        sys.exit(0)

    # Structural changes detected — block and ask for re-index
    print(
        f"\n[jcodemunch] Structural changes detected: "
        f"{len(created)} file(s) created, {len(deleted)} delete/move operation(s).",
        file=sys.stderr,
    )

    if created:
        for f in sorted(created)[:10]:
            print(f"  + {f}", file=sys.stderr)

    print(
        "\n[jcodemunch] Please re-index before stopping:\n"
        "  Call mcp__jcodemunch__index_folder with:\n"
        f'    path: "{project_dir}"\n'
        "    incremental: true\n",
        file=sys.stderr,
    )

    # Write marker so next stop attempt passes through
    try:
        with open(marker_path, "w") as f:
            f.write(str(time.time()))
    except OSError:
        pass

    # Block the stop
    sys.exit(2)


if __name__ == "__main__":
    main()
