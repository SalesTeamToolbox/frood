#!/usr/bin/env python3
# hook_event: Stop
# hook_timeout: 15
"""Associative memory learning hook — captures learnings from each session.

Triggered on Stop. Analyzes what happened in the conversation and stores
new knowledge in Agent42's memory system for future recall.

Completes the associative memory cycle:
- memory-recall.py (UserPromptSubmit) → surfaces relevant past knowledge
- memory-learn.py (Stop) → captures new knowledge for future recall

Hook protocol:
- Receives JSON on stdin: {hook_event_name, project_dir, stop_reason, ...}
- Output to stderr for logging
- Exit code 0 = allow
"""

import json
import os
import sys
import time
from pathlib import Path


def extract_session_summary(event):
    """Extract a meaningful summary from the stop event.

    Claude Code Stop events provide: hook_event_name, project_dir, stop_reason,
    and optionally transcript_summary. They do NOT include tool_results or
    messages (those were from the old Agent42 standalone pipeline).

    Strategy:
    1. Use transcript_summary if CC provides it (best quality)
    2. Use tool_results/messages if present (Agent42 standalone mode)
    3. Fall back to recent git changes (always available)
    """
    parts = []

    # ── Strategy 1: CC transcript summary (highest quality) ───────────
    transcript = event.get("transcript_summary", "")
    if isinstance(transcript, str) and len(transcript.strip()) > 10:
        parts.append(f"Summary: {transcript.strip()[:300]}")

    # ── Strategy 2: Agent42 standalone event fields (legacy) ──────────
    if not parts:
        tool_results = event.get("tool_results", [])
        if isinstance(tool_results, list) and tool_results:
            tools_used = set()
            files_modified = set()
            for tr in tool_results:
                if not isinstance(tr, dict):
                    continue
                tool_name = tr.get("tool_name", "")
                if tool_name:
                    tools_used.add(tool_name)
                tool_input = tr.get("tool_input", {})
                if isinstance(tool_input, dict):
                    fp = tool_input.get("file_path", "") or tool_input.get("path", "")
                    if fp and tool_name in (
                        "Write",
                        "Edit",
                        "agent42_write_file",
                        "agent42_edit_file",
                    ):
                        files_modified.add(os.path.basename(fp))

            if tools_used:
                parts.append(f"Tools: {', '.join(sorted(tools_used)[:10])}")
            if files_modified:
                parts.append(f"Modified: {', '.join(sorted(files_modified)[:10])}")

        messages = event.get("messages", [])
        if isinstance(messages, list) and messages:
            for msg in reversed(messages):
                if msg.get("role") == "assistant":
                    content = msg.get("content", "")
                    if isinstance(content, str) and len(content) > 20:
                        first_line = content.split("\n")[0][:200]
                        parts.append(f"Summary: {first_line}")
                        break

    # ── Strategy 3: Git changes fallback (always works) ───────────────
    if not parts:
        parts = _git_summary(event.get("project_dir", "."))

    # ── Include stop reason as metadata ───────────────────────────────
    stop_reason = event.get("stop_reason", "")
    if stop_reason and stop_reason != "end_turn":
        parts.append(f"stop_reason={stop_reason}")

    return " | ".join(parts) if parts else ""


def _git_summary(project_dir):
    """Build a session summary from recent git activity."""
    import subprocess

    parts = []
    try:
        # Get files changed since last commit (unstaged + staged)
        result = subprocess.run(
            ["git", "diff", "--stat", "HEAD"],
            capture_output=True,
            text=True,
            cwd=project_dir,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            # Last line of --stat is the summary line
            lines = result.stdout.strip().split("\n")
            stat_line = lines[-1].strip() if lines else ""
            changed_files = [l.split("|")[0].strip() for l in lines[:-1] if "|" in l]
            if changed_files:
                parts.append(f"Modified: {', '.join(changed_files[:8])}")
            if stat_line:
                parts.append(f"Changes: {stat_line}")
    except Exception:
        pass

    if not parts:
        try:
            # Fall back to most recent commit message
            result = subprocess.run(
                ["git", "log", "-1", "--oneline"],
                capture_output=True,
                text=True,
                cwd=project_dir,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                parts.append(f"Last commit: {result.stdout.strip()[:150]}")
        except Exception:
            pass

    return parts


def main():
    try:
        event = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    project_dir = event.get("project_dir", ".")

    summary = extract_session_summary(event)
    if not summary:
        sys.exit(0)

    # ── Append to HISTORY.md ─────────────────────────────────────────────
    memory_dir = Path(project_dir) / ".agent42" / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)

    history_path = memory_dir / "HISTORY.md"
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")

    entry = f"\n---\n[{timestamp}] {summary}\n"

    try:
        with open(history_path, "a", encoding="utf-8") as f:
            f.write(entry)
    except Exception as e:
        print(f"[memory-learn] Failed to write history: {e}", file=sys.stderr)
        sys.exit(0)

    # ── Index via search service HTTP API (avoids loading model in hook) ──
    search_url = os.environ.get("AGENT42_SEARCH_URL", "http://127.0.0.1:6380")
    try:
        import urllib.request

        data = json.dumps({"text": summary, "section": "session", "action": "index"}).encode()
        req = urllib.request.Request(
            f"{search_url}/index",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            resp.read()
        print("[memory-learn] Indexed session in semantic store", file=sys.stderr)
    except Exception:
        pass  # Search service not running — file-based history still works

    print(f"[memory-learn] Captured: {summary[:100]}", file=sys.stderr)
    sys.exit(0)


if __name__ == "__main__":
    main()
