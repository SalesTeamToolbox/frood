#!/usr/bin/env python3
# hook_event: Stop
# hook_timeout: 15
"""Session handoff hook — captures session state for auto-resume continuity.

Triggered on Stop event. Extracts what happened during the session (files
modified, tools used, errors) and writes/updates .claude/handoff.json so
the auto-resume wrapper script can build an informed resume prompt.

Also captures conversation context (user prompts accumulated during the session
+ tool usage summaries) so that the next session can recall what was discussed.
This is critical for surviving context window clears — when Claude suggests
"clear context and come back with your choice", the options and discussion
are preserved in handoff.json and surfaced by memory-recall.py.

Also detects GSD planning state (.planning/ directory) to provide
phase-level context for GSD workflow resumption.

Hook protocol:
- Receives JSON on stdin with hook_event_name, project_dir, tool_uses
- Output to stderr is shown to Claude as feedback
- Exit code 0 = allow (always allows)
"""

import glob
import json
import os
import re
import sys
from datetime import UTC, datetime


def normalize_path(path):
    """Normalize Git Bash /c/... paths to Windows C:\\... on Windows."""
    if sys.platform == "win32" and re.match(r"^/([a-zA-Z])/", path):
        path = path[1].upper() + ":" + path[2:]
    return os.path.normpath(path)


def load_handoff(project_dir):
    """Load existing handoff state or return defaults."""
    path = os.path.join(project_dir, ".claude", "handoff.json")
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return None


def save_handoff(project_dir, handoff):
    """Save handoff state to disk."""
    path = os.path.join(project_dir, ".claude", "handoff.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        with open(path, "w") as f:
            json.dump(handoff, f, indent=2)
    except OSError as e:
        print(f"[session-handoff] Failed to save handoff: {e}", file=sys.stderr)


def extract_session_data(event, project_dir):
    """Extract useful data from the session's tool uses."""
    files_modified = set()
    files_read = set()
    tools_used = {}
    had_errors = False
    bash_commands = []

    for tool_use in event.get("tool_uses", []):
        tool_name = tool_use.get("tool_name", "")
        tool_input = tool_use.get("tool_input", {})
        tool_output = tool_use.get("tool_output", {})

        # Count tool usage
        tools_used[tool_name] = tools_used.get(tool_name, 0) + 1

        # Track file paths
        file_path = tool_input.get("file_path", "") or tool_input.get("path", "")
        if file_path:
            file_path = normalize_path(file_path)
            # Normalize to relative path
            if project_dir and file_path.startswith(project_dir):
                file_path = file_path[len(project_dir) :].lstrip("/\\")

            if tool_name in ("Write", "Edit", "NotebookEdit"):
                files_modified.add(file_path)
            elif tool_name == "Read":
                files_read.add(file_path)

        # Track bash commands (for context)
        if tool_name == "Bash":
            cmd = tool_input.get("command", "")
            if cmd and len(cmd) < 200:
                bash_commands.append(cmd)

        # Track errors
        if isinstance(tool_output, dict) and tool_output.get("is_error"):
            had_errors = True

    return {
        "files_modified": sorted(files_modified),
        "files_read": sorted(files_read),
        "tools_used": tools_used,
        "had_errors": had_errors,
        "bash_commands": bash_commands[-10:],  # Last 10 commands
    }


def detect_gsd_state(project_dir):
    """Detect GSD planning state if .planning/ directory exists."""
    planning_dir = os.path.join(project_dir, ".planning")
    if not os.path.isdir(planning_dir):
        return None

    gsd = {
        "planning_dir": ".planning",
        "project_name": None,
        "roadmap_exists": False,
        "phases": [],
        "current_phase": None,
        "config": None,
    }

    # Read config.json
    config_path = os.path.join(planning_dir, "config.json")
    if os.path.exists(config_path):
        try:
            with open(config_path) as f:
                gsd["config"] = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass

    # Read PROJECT.md title
    project_path = os.path.join(planning_dir, "PROJECT.md")
    if os.path.exists(project_path):
        try:
            with open(project_path) as f:
                first_line = f.readline().strip()
                if first_line.startswith("# "):
                    gsd["project_name"] = first_line[2:].strip()
        except OSError:
            pass

    # Check for ROADMAP.md
    roadmap_path = os.path.join(planning_dir, "ROADMAP.md")
    gsd["roadmap_exists"] = os.path.exists(roadmap_path)

    # Detect phase directories (pattern: NN-name or NN.N-name)
    phase_pattern = os.path.join(planning_dir, "[0-9]*")
    for phase_dir in sorted(glob.glob(phase_pattern)):
        if os.path.isdir(phase_dir):
            phase_name = os.path.basename(phase_dir)
            phase_info = {
                "name": phase_name,
                "has_plan": False,
                "has_state": False,
                "status": "unknown",
            }

            if os.path.exists(os.path.join(phase_dir, "PLAN.md")):
                phase_info["has_plan"] = True
            if os.path.exists(os.path.join(phase_dir, "STATE.md")):
                phase_info["has_state"] = True

            # Try to detect phase status from STATE.md
            state_path = os.path.join(phase_dir, "STATE.md")
            if os.path.exists(state_path):
                try:
                    with open(state_path) as f:
                        content = f.read(500)
                        if (
                            "status: completed" in content.lower()
                            or "## completed" in content.lower()
                        ):
                            phase_info["status"] = "completed"
                        elif (
                            "status: in_progress" in content.lower()
                            or "## in progress" in content.lower()
                        ):
                            phase_info["status"] = "in_progress"
                except OSError:
                    pass

            # Check VERIFICATION.md for completion
            verify_path = os.path.join(phase_dir, "VERIFICATION.md")
            if os.path.exists(verify_path):
                phase_info["status"] = "verified"

            gsd["phases"].append(phase_info)

    # Determine current phase (last non-completed phase)
    for phase in gsd["phases"]:
        if phase["status"] not in ("completed", "verified"):
            gsd["current_phase"] = phase["name"]
            break

    # If all phases are done, mark the last one
    if not gsd["current_phase"] and gsd["phases"]:
        gsd["current_phase"] = gsd["phases"][-1]["name"]

    return gsd


def detect_completion(session_data, gsd_state):
    """Heuristic to detect if work appears complete."""
    # If GSD exists and all phases are completed/verified
    if gsd_state and gsd_state.get("phases"):
        all_done = all(p["status"] in ("completed", "verified") for p in gsd_state["phases"])
        if all_done:
            return True

    # If no files were modified and no bash commands ran, session was likely idle
    if not session_data["files_modified"] and not session_data["bash_commands"]:
        return False  # Inconclusive, not complete

    return False  # Default: assume not complete


def read_conversation_buffer(project_dir):
    """Read and consume the conversation buffer written by conversation-accumulator.py.

    Returns list of prompt entries and deletes the buffer file.
    """

    buffer_path = os.path.join(project_dir, ".agent42", "conversation-buffer.jsonl")
    if not os.path.exists(buffer_path):
        return []

    entries = []
    try:
        with open(buffer_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except OSError:
        return []

    # Delete the buffer after reading (consumed)
    try:
        os.unlink(buffer_path)
    except OSError:
        pass

    return entries


def extract_tool_summaries(event):
    """Extract meaningful assistant-side context from tool calls.

    Captures tool interactions that reveal what Claude was doing/discussing,
    especially AskUserQuestion calls (which contain presented options) and
    key tool outputs that show the conversation flow.
    """
    summaries = []

    for tool_use in event.get("tool_uses", []):
        tool_name = tool_use.get("tool_name", "")
        tool_input = tool_use.get("tool_input", {})
        tool_output = tool_use.get("tool_output", {})

        # AskUserQuestion — captures presented options (the key missing piece)
        if tool_name == "AskUserQuestion":
            question = tool_input.get("question", "")
            options = tool_input.get("options", [])
            header = tool_input.get("header", "")
            if question:
                summary = f"[Asked] {header}: {question}" if header else f"[Asked] {question}"
                if options:
                    opt_labels = []
                    for opt in options:
                        if isinstance(opt, dict):
                            opt_labels.append(opt.get("label", str(opt)))
                        else:
                            opt_labels.append(str(opt))
                    summary += f" Options: {', '.join(opt_labels)}"

                # Capture the user's response
                if isinstance(tool_output, dict):
                    response = tool_output.get("result", tool_output.get("text", ""))
                elif isinstance(tool_output, str):
                    response = tool_output
                else:
                    response = ""
                if response:
                    summary += f" -> User chose: {str(response)[:200]}"

                summaries.append(
                    {
                        "role": "assistant",
                        "content": summary[:500],
                        "type": "question",
                    }
                )

        # TodoWrite — shows what tasks were planned
        elif tool_name == "TodoWrite":
            todos = tool_input.get("todos", [])
            if todos:
                task_names = [t.get("content", "")[:80] for t in todos[:5]]
                summaries.append(
                    {
                        "role": "assistant",
                        "content": f"[Tasks planned] {'; '.join(task_names)}",
                        "type": "planning",
                    }
                )

        # Agent — shows what subagents were spawned
        elif tool_name == "Agent":
            desc = tool_input.get("description", "")
            if desc:
                summaries.append(
                    {
                        "role": "assistant",
                        "content": f"[Agent spawned] {desc}",
                        "type": "delegation",
                    }
                )

    return summaries


def build_conversation_context(user_prompts, tool_summaries, max_entries=20):
    """Merge user prompts and tool summaries into a conversation timeline.

    Returns a list of entries sorted by timestamp (or insertion order for
    tool summaries), capped at max_entries.
    """
    import time as _time

    timeline = []

    # Add user prompts with timestamps
    for entry in user_prompts:
        timeline.append(
            {
                "role": "user",
                "content": entry.get("content", "")[:1000],
                "timestamp": entry.get("timestamp", 0),
            }
        )

    # Tool summaries don't have timestamps — assign them based on position
    # They represent what happened between user prompts
    if tool_summaries:
        # Space them evenly between first and last user prompt timestamps
        if user_prompts:
            t_start = user_prompts[0].get("timestamp", _time.time() - 3600)
            t_end = user_prompts[-1].get("timestamp", _time.time())
        else:
            t_end = _time.time()
            t_start = t_end - 3600

        interval = (t_end - t_start) / max(len(tool_summaries) + 1, 1)
        for i, summary in enumerate(tool_summaries):
            summary["timestamp"] = t_start + interval * (i + 1)
            timeline.append(summary)

    # Sort by timestamp and cap
    timeline.sort(key=lambda x: x.get("timestamp", 0))
    return timeline[-max_entries:]


def main():
    try:
        event = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    if event.get("hook_event_name") != "Stop":
        sys.exit(0)

    project_dir = normalize_path(event.get("project_dir", "."))

    # Load existing handoff (created by the wrapper script)
    handoff = load_handoff(project_dir)
    if handoff is None:
        # No handoff file = not running under auto-resume wrapper
        # Still create one for informational purposes
        handoff = {
            "version": 1,
            "created": datetime.now(UTC).isoformat(),
            "original_prompt": None,
            "session_count": 0,
            "status": "unknown",
        }

    # Extract session data
    session_data = extract_session_data(event, project_dir)

    # Detect GSD state
    gsd_state = detect_gsd_state(project_dir)

    # Detect completion
    is_complete = detect_completion(session_data, gsd_state)

    # ── Build conversation context ────────────────────────────────────────
    # Read user prompts accumulated during the session
    user_prompts = read_conversation_buffer(project_dir)

    # Extract assistant-side context from tool calls
    tool_summaries = extract_tool_summaries(event)

    # Merge into a conversation timeline
    conversation_context = build_conversation_context(user_prompts, tool_summaries)

    # Update handoff
    handoff["updated"] = datetime.now(UTC).isoformat()
    handoff["session_count"] = handoff.get("session_count", 0) + 1
    handoff["status"] = "completed" if is_complete else "in_progress"
    handoff["last_session"] = {
        "files_modified": session_data["files_modified"],
        "files_read": session_data["files_read"][:20],  # Cap to avoid bloat
        "tools_used": session_data["tools_used"],
        "had_errors": session_data["had_errors"],
        "bash_commands": session_data["bash_commands"],
    }

    # Store conversation context (the key new field)
    if conversation_context:
        handoff["conversation_context"] = conversation_context

    # Accumulate files modified across all sessions
    all_modified = set(handoff.get("all_files_modified", []))
    all_modified.update(session_data["files_modified"])
    handoff["all_files_modified"] = sorted(all_modified)

    if gsd_state:
        handoff["gsd"] = gsd_state

    save_handoff(project_dir, handoff)

    # Report to Claude
    session_num = handoff["session_count"]
    n_files = len(session_data["files_modified"])
    n_context = len(conversation_context)
    status = handoff["status"]
    print(
        f"[session-handoff] Session #{session_num}: {n_files} files modified, "
        f"{n_context} conversation entries captured, status={status}",
        file=sys.stderr,
    )

    if gsd_state and gsd_state.get("current_phase"):
        print(
            f"[session-handoff] GSD phase: {gsd_state['current_phase']}",
            file=sys.stderr,
        )

    sys.exit(0)


if __name__ == "__main__":
    main()
