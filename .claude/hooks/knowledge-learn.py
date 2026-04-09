#!/usr/bin/env python3
# hook_event: Stop
# hook_timeout: 30
"""Knowledge learning hook — extracts structured learnings from CC sessions.

Triggered on Stop. Pre-extracts session data (last 20 messages, tool names,
modified files) and writes to a temp file, then spawns a detached background
worker to call Agent42's /api/knowledge/learn endpoint for LLM extraction and
Qdrant upsert.

This file uses ONLY Python stdlib — zero Agent42 imports — so startup is < 5ms.

Hook protocol:
- Receives JSON on stdin: {hook_event_name, project_dir, stop_reason, tool_results, messages, ...}
- Output to stderr for logging
- Exit code 0 = always allows (worker failure never blocks Claude Code session end)
"""

import json
import os
import subprocess
import sys
from pathlib import Path

# ── Noise guard helpers ────────────────────────────────────────────────────


def count_tool_calls(event: dict) -> int:
    """Count total tool calls in the session."""
    tool_results = event.get("tool_results", [])
    if isinstance(tool_results, list):
        return len(tool_results)
    return 0


def count_file_modifications(event: dict) -> int:
    """Count file-modifying tool calls (Write, Edit, frood_write_file, frood_edit_file)."""
    tool_results = event.get("tool_results", [])
    if not isinstance(tool_results, list):
        return 0
    count = 0
    for tr in tool_results:
        if not isinstance(tr, dict):
            continue
        tool_name = tr.get("tool_name", "")
        if tool_name in ("Write", "Edit", "frood_write_file", "frood_edit_file"):
            count += 1
    return count


# ── Session data extraction helpers ───────────────────────────────────────


def get_tool_names(event: dict) -> list:
    """Extract sorted unique tool names, capped at 15."""
    tool_results = event.get("tool_results", [])
    if not isinstance(tool_results, list):
        return []
    names = set()
    for tr in tool_results:
        if isinstance(tr, dict):
            name = tr.get("tool_name", "")
            if name:
                names.add(name)
    return sorted(names)[:15]


def get_modified_files(event: dict) -> list:
    """Extract basenames of files modified during the session, capped at 15."""
    tool_results = event.get("tool_results", [])
    if not isinstance(tool_results, list):
        return []
    files = set()
    for tr in tool_results:
        if not isinstance(tr, dict):
            continue
        tool_name = tr.get("tool_name", "")
        if tool_name not in ("Write", "Edit", "frood_write_file", "frood_edit_file"):
            continue
        tool_input = tr.get("tool_input", {})
        if isinstance(tool_input, dict):
            fp = tool_input.get("file_path", "") or tool_input.get("path", "")
            if fp:
                files.add(os.path.basename(fp))
    return sorted(files)[:15]


def get_last_messages(event: dict, n: int = 20) -> list:
    """Extract the last n messages from the session."""
    messages = event.get("messages", [])
    if not isinstance(messages, list):
        return []
    return messages[-n:]


def get_last_assistant_message(event: dict) -> str:
    """Extract the last assistant message content, capped at 2000 chars."""
    messages = event.get("messages", [])
    if not isinstance(messages, list):
        return ""
    for msg in reversed(messages):
        if isinstance(msg, dict) and msg.get("role") == "assistant":
            content = msg.get("content", "")
            if isinstance(content, str) and len(content) > 20:
                return content[:2000]
    return ""


# ── Main ───────────────────────────────────────────────────────────────────


def main():
    # Read stdin event
    try:
        event = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    # Trivial session guard — skip if not enough activity to learn from
    tool_call_count = count_tool_calls(event)
    file_mod_count = count_file_modifications(event)

    if tool_call_count < 2 or file_mod_count < 1:
        print(
            f"[knowledge-learn] Skipped: {tool_call_count} tool calls, {file_mod_count} file mods",
            file=sys.stderr,
        )
        sys.exit(0)

    # Pre-extract session data
    messages_context = get_last_messages(event, n=20)
    tools_used = get_tool_names(event)
    files_modified = get_modified_files(event)
    session_summary = get_last_assistant_message(event)
    project_dir = event.get("project_dir", ".")

    # Write pre-extracted data to temp file
    extract_data = {
        "messages_context": messages_context,
        "tools_used": tools_used,
        "files_modified": files_modified,
        "session_summary": session_summary,
        "project_dir": project_dir,
    }

    try:
        extract_dir = Path(project_dir) / ".frood"
        extract_dir.mkdir(parents=True, exist_ok=True)
        temp_file = extract_dir / f"knowledge-extract-{os.getpid()}.json"
        temp_file.write_text(json.dumps(extract_data), encoding="utf-8")
    except Exception as e:
        print(f"[knowledge-learn] Failed to write temp file: {e}", file=sys.stderr)
        sys.exit(0)

    # Resolve worker path relative to this hook file
    worker = Path(__file__).parent / "knowledge-learn-worker.py"
    if not worker.exists():
        print(f"[knowledge-learn] Worker not found: {worker}", file=sys.stderr)
        sys.exit(0)

    # Spawn detached worker — never blocks session end (fire-and-forget)
    creation_flags = 0
    if sys.platform == "win32":
        creation_flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP

    try:
        subprocess.Popen(
            [sys.executable, str(worker), str(temp_file)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=(sys.platform != "win32"),
            creationflags=creation_flags,
        )
        print(
            f"[knowledge-learn] Spawned worker for {tool_call_count} calls, {file_mod_count} mods",
            file=sys.stderr,
        )
    except Exception as e:
        print(f"[knowledge-learn] Failed to spawn worker: {e}", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
