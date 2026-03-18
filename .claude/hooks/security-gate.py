#!/usr/bin/env python3
# hook_event: PreToolUse
# hook_matcher: Write|Edit|Bash
# hook_timeout: 10
"""PreToolUse security gate -- blocks edits to security-sensitive files.

This hook runs BEFORE Write, Edit, and Bash operations.  If the target
file is in the shared SECURITY_FILES registry the hook exits with code 2
(block), forcing the developer to explicitly approve before the change
is applied.

Hook protocol
-------------
- Receives JSON on stdin: { hook_event_name, tool_name, tool_input }
- Output to stderr is shown to Claude as feedback
- Exit code 0 = allow
- Exit code 2 = block (requires user approval to continue)
"""

import json
import os
import re
import sys

# Ensure the hooks directory is on the import path so we can reach
# security_config even when the cwd is the project root.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from security_config import SECURITY_FILES, is_security_file


def _check_bash_command(command: str) -> tuple:
    """Check if a Bash command targets a security file with rm or mv.

    Returns
    -------
    tuple of (bool, str, str)
        (is_match, matched_path, description)
    """
    for sec_path, description in SECURITY_FILES.items():
        # Escape dots for regex, use both basename and relative path
        basename = os.path.basename(sec_path)
        for name in (sec_path, basename):
            escaped = re.escape(name)
            # Match: rm, rm -f, rm -rf, rm -r, mv  followed by the filename
            pattern = rf"(?:rm|mv)\s+(?:-[a-zA-Z]*\s+)*\S*{escaped}"
            if re.search(pattern, command):
                return (True, sec_path, description)
    return (False, "", "")


def main():
    # Parse event JSON from stdin
    try:
        event = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError, ValueError):
        # Don't block on bad input
        sys.exit(0)

    tool_name = event.get("tool_name", "")
    tool_input = event.get("tool_input", {})

    # --- Write / Edit tools ---
    if tool_name in ("Write", "Edit", "write", "edit"):
        file_path = tool_input.get("file_path", "")
        if not file_path:
            sys.exit(0)

        is_match, matched_path, description = is_security_file(file_path)
        if is_match:
            print(
                f"[security-gate] BLOCKED: {file_path} ({description}) -- approve to continue",
                file=sys.stderr,
            )
            sys.exit(2)

        sys.exit(0)

    # --- Bash tool ---
    if tool_name in ("Bash", "bash"):
        command = tool_input.get("command", "")
        if not command:
            sys.exit(0)

        is_match, matched_path, description = _check_bash_command(command)
        if is_match:
            print(
                f"[security-gate] BLOCKED: Bash command targets security file "
                f"{matched_path} ({description}) -- approve to continue",
                file=sys.stderr,
            )
            sys.exit(2)

        sys.exit(0)

    # Any other tool -- allow
    sys.exit(0)


if __name__ == "__main__":
    main()
