#!/usr/bin/env python3
# hook_event: UserPromptSubmit
# hook_timeout: 5
"""Conversation accumulator hook — captures user prompts for session context persistence.

Triggered on UserPromptSubmit. Appends each user prompt (with timestamp) to a
JSONL buffer file so that session-handoff.py can build a conversation_context
snapshot at session end. This ensures conversation decisions survive context clears.

The buffer file is consumed and deleted by session-handoff.py on Stop events.

Hook protocol:
- Receives JSON on stdin: {hook_event_name, project_dir, user_prompt, session_id, ...}
- Output to stderr is shown to Claude as context
- Exit code 0 = allow (always allow)
"""

import json
import os
import sys
import time

# Buffer file — consumed by session-handoff.py on Stop
BUFFER_FILENAME = "conversation-buffer.jsonl"
MAX_BUFFER_ENTRIES = 30  # Keep last N prompts per session
MAX_PROMPT_CHARS = 2000  # Truncate very long prompts
MIN_PROMPT_LEN = 5  # Skip trivially short prompts


def get_buffer_path(project_dir):
    """Return path to the conversation buffer file."""
    return os.path.join(project_dir, ".agent42", BUFFER_FILENAME)


def append_prompt(buffer_path, prompt, session_id):
    """Append a user prompt entry to the JSONL buffer."""
    os.makedirs(os.path.dirname(buffer_path), exist_ok=True)

    entry = {
        "role": "user",
        "content": prompt[:MAX_PROMPT_CHARS],
        "timestamp": time.time(),
        "session_id": session_id,
    }

    # Read existing entries for rotation
    entries = []
    if os.path.exists(buffer_path):
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
            entries = []

    entries.append(entry)

    # Rotate: keep only last MAX_BUFFER_ENTRIES
    if len(entries) > MAX_BUFFER_ENTRIES:
        entries = entries[-MAX_BUFFER_ENTRIES:]

    # Write back atomically
    try:
        tmp_path = buffer_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")
        os.replace(tmp_path, buffer_path)
    except OSError:
        # Non-critical — never block the prompt
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def main():
    try:
        event = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    project_dir = event.get("project_dir", ".")
    prompt = event.get("user_prompt", "").strip()
    session_id = event.get("session_id", "")

    # Skip very short or slash-command prompts
    if len(prompt) < MIN_PROMPT_LEN:
        sys.exit(0)
    if prompt.startswith("/"):
        sys.exit(0)

    buffer_path = get_buffer_path(project_dir)
    append_prompt(buffer_path, prompt, session_id)

    sys.exit(0)


if __name__ == "__main__":
    main()
