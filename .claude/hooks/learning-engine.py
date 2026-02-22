#!/usr/bin/env python3
"""Learning engine hook — records development patterns from sessions.

Triggered on Stop event. Analyzes the session to extract:
1. File paths commonly worked on together
2. Error patterns that were resolved
3. Recurring task types that could become skills

Updates .claude/learned-patterns.json with accumulated data.

Hook protocol:
- Receives JSON on stdin with hook_event_name, project_dir
- Output to stderr is shown to Claude as feedback
- Exit code 0 = allow (always allows)
"""

import json
import os
import sys
from datetime import datetime, timezone


DEFAULT_PATTERNS = {
    "version": 1,
    "sessions": 0,
    "file_co_occurrences": {},
    "task_type_frequency": {},
    "vocabulary": {},
    "skill_candidates": [],
    "last_updated": None,
}

SKILL_CANDIDATE_THRESHOLD = 3  # Pattern must occur 3+ times to suggest a skill


def load_patterns(project_dir):
    """Load existing learned patterns or create defaults."""
    path = os.path.join(project_dir, ".claude", "learned-patterns.json")
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                data = json.load(f)
                # Ensure all keys exist (forward compatibility)
                for key, default in DEFAULT_PATTERNS.items():
                    if key not in data:
                        data[key] = default
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return dict(DEFAULT_PATTERNS)


def save_patterns(project_dir, patterns):
    """Save learned patterns to disk."""
    path = os.path.join(project_dir, ".claude", "learned-patterns.json")
    patterns["last_updated"] = datetime.now(timezone.utc).isoformat()

    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        with open(path, "w") as f:
            json.dump(patterns, f, indent=2)
    except OSError as e:
        print(f"[learning-engine] Failed to save patterns: {e}", file=sys.stderr)


def extract_session_data(event):
    """Extract useful data from the session event."""
    data = {
        "files_touched": set(),
        "task_types": set(),
        "had_errors": False,
    }

    # Extract from tool uses in the session
    tool_uses = event.get("tool_uses", [])
    for tool_use in tool_uses:
        tool_name = tool_use.get("tool_name", "")
        tool_input = tool_use.get("tool_input", {})

        # Track files touched
        file_path = tool_input.get("file_path", "") or tool_input.get("path", "")
        if file_path:
            # Normalize to relative path
            project_dir = event.get("project_dir", "")
            if project_dir and file_path.startswith(project_dir):
                file_path = file_path[len(project_dir):].lstrip("/")
            data["files_touched"].add(file_path)

        # Detect task types from file paths
        if file_path:
            if "test" in file_path:
                data["task_types"].add("testing")
            elif "security" in file_path or "sandbox" in file_path:
                data["task_types"].add("security")
            elif file_path.startswith("tools/"):
                data["task_types"].add("tool_development")
            elif file_path.startswith("skills/"):
                data["task_types"].add("skill_development")
            elif file_path.startswith("dashboard/"):
                data["task_types"].add("dashboard")
            elif file_path.startswith("providers/"):
                data["task_types"].add("provider")

        # Check for errors
        tool_output = tool_use.get("tool_output", {})
        if isinstance(tool_output, dict) and tool_output.get("is_error"):
            data["had_errors"] = True

    return data


def update_patterns(patterns, session_data):
    """Update learned patterns with session data."""
    patterns["sessions"] += 1

    # Update file co-occurrences
    files = sorted(session_data["files_touched"])
    for i, f1 in enumerate(files):
        for f2 in files[i + 1:]:
            key = f"{f1}|{f2}"
            patterns["file_co_occurrences"][key] = (
                patterns["file_co_occurrences"].get(key, 0) + 1
            )

    # Update task type frequency
    for task_type in session_data["task_types"]:
        patterns["task_type_frequency"][task_type] = (
            patterns["task_type_frequency"].get(task_type, 0) + 1
        )

    # Check for skill candidates
    for task_type, count in patterns["task_type_frequency"].items():
        if count >= SKILL_CANDIDATE_THRESHOLD:
            existing = [c["type"] for c in patterns["skill_candidates"]]
            if task_type not in existing:
                patterns["skill_candidates"].append({
                    "type": task_type,
                    "occurrences": count,
                    "suggested_at": datetime.now(timezone.utc).isoformat(),
                })

    # Cap co-occurrence dict size to prevent unbounded growth
    if len(patterns["file_co_occurrences"]) > 500:
        # Keep only the top 250 most common pairs
        sorted_pairs = sorted(
            patterns["file_co_occurrences"].items(),
            key=lambda x: x[1],
            reverse=True,
        )
        patterns["file_co_occurrences"] = dict(sorted_pairs[:250])

    return patterns


def main():
    try:
        event = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    # Only run on Stop events
    if event.get("hook_event_name") != "Stop":
        sys.exit(0)

    project_dir = event.get("project_dir", ".")

    # Load existing patterns
    patterns = load_patterns(project_dir)

    # Extract session data
    session_data = extract_session_data(event)

    # Update patterns
    patterns = update_patterns(patterns, session_data)

    # Save updated patterns
    save_patterns(project_dir, patterns)

    # Report new skill candidates
    new_candidates = [
        c for c in patterns["skill_candidates"]
        if c["occurrences"] == SKILL_CANDIDATE_THRESHOLD
    ]
    if new_candidates:
        print("\n[learning-engine] New skill candidates detected:", file=sys.stderr)
        for c in new_candidates:
            print(
                f"  - {c['type']} (occurred {c['occurrences']}+ times)",
                file=sys.stderr,
            )
        print(
            "  Consider creating a skill in skills/builtins/ for these patterns.",
            file=sys.stderr,
        )

    # Report summary
    if session_data["files_touched"]:
        print(
            f"[learning-engine] Session #{patterns['sessions']}: "
            f"{len(session_data['files_touched'])} files, "
            f"{len(session_data['task_types'])} task types recorded.",
            file=sys.stderr,
        )

    sys.exit(0)


if __name__ == "__main__":
    main()
