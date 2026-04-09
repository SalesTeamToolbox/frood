#!/usr/bin/env python3
# hook_event: Stop
# hook_timeout: 30
"""Effectiveness learning hook — extracts structured learnings from sessions.

Triggered on Stop. Uses instructor + Pydantic to extract structured learnings
from the session, then calls Agent42's HTTP API to persist them.

Complements (does NOT replace) existing hooks:
- learning-engine.py: file co-occurrences, task type frequency, skill candidates
- memory-learn.py: raw session summary to HISTORY.md

This hook adds: LLM-extracted structured learnings with quarantine fields.

Hook protocol:
- Receives JSON on stdin: {hook_event_name, project_dir, stop_reason, tool_results, messages, ...}
- Output to stderr for logging
- Exit code 0 = allow (always allows)
"""

import json
import os
import sys
from pathlib import Path


def count_tool_calls(event):
    """Count total tool calls in the session."""
    tool_results = event.get("tool_results", [])
    if isinstance(tool_results, list):
        return len(tool_results)
    return 0


def count_file_modifications(event):
    """Count file-modifying tool calls (Write, Edit)."""
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


def get_tool_names(event):
    """Extract unique tool names from the session."""
    tool_results = event.get("tool_results", [])
    if not isinstance(tool_results, list):
        return []
    names = set()
    for tr in tool_results:
        if isinstance(tr, dict):
            name = tr.get("tool_name", "")
            if name:
                names.add(name)
    return sorted(names)[:15]  # Cap at 15


def get_modified_files(event):
    """Extract file paths modified during the session."""
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
    return sorted(files)[:15]  # Cap at 15


def get_last_assistant_message(event):
    """Extract the last assistant message as session summary."""
    messages = event.get("messages", [])
    if not isinstance(messages, list):
        return ""
    for msg in reversed(messages):
        if isinstance(msg, dict) and msg.get("role") == "assistant":
            content = msg.get("content", "")
            if isinstance(content, str) and len(content) > 20:
                return content[:2000]  # Cap for LLM prompt
    return ""


def read_task_context(project_dir):
    """Read task_id and task_type from the cross-process bridge file.

    Returns (task_id, task_type) or (generated_uuid, "general") if file not found.
    """
    import uuid

    task_file = Path(project_dir) / ".frood" / "current-task.json"
    try:
        if task_file.exists():
            data = json.loads(task_file.read_text(encoding="utf-8"))
            return data.get("task_id", str(uuid.uuid4())), data.get("task_type", "general")
    except Exception:
        pass
    return str(uuid.uuid4()), "general"


def extract_learning_with_instructor(session_summary, tools_used, files_modified, task_type):
    """Use instructor + Pydantic to extract a structured learning.

    Returns dict with learning fields or None on failure.
    Falls back gracefully if instructor is not installed or API call fails.
    """
    try:
        import instructor
        from openai import OpenAI
        from pydantic import BaseModel, Field
    except ImportError:
        print(
            "[effectiveness-learn] instructor/openai/pydantic not installed, skipping extraction",
            file=sys.stderr,
        )
        return None

    class ExtractedLearning(BaseModel):
        outcome: str = Field(description="One of: success, failure, partial")
        summary: str = Field(description="1-2 sentence description of what happened")
        key_insight: str = Field(
            description="The durable learning — what to remember for future similar tasks"
        )

    # Use Gemini Flash via OpenRouter (same provider routing as existing hooks)
    api_key = os.environ.get("OPENROUTER_API_KEY", "") or os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        # Try OpenAI as fallback
        api_key = os.environ.get("OPENAI_API_KEY", "")
        base_url = None
    else:
        base_url = "https://openrouter.ai/api/v1"

    if not api_key:
        print("[effectiveness-learn] No API key for extraction, skipping", file=sys.stderr)
        return None

    prompt = f"""Analyze this development session and extract a structured learning.

Task type: {task_type}
Tools used: {", ".join(tools_used)}
Files modified: {", ".join(files_modified)}

Session summary:
{session_summary}

Extract:
1. outcome: Was this session successful, a failure, or partial?
2. summary: What happened in 1-2 sentences?
3. key_insight: What's the durable lesson learned that would help in future similar tasks?

Be specific and actionable. If the session was trivial, say so briefly."""

    try:
        client_kwargs = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url
        client = instructor.from_openai(OpenAI(**client_kwargs), mode=instructor.Mode.JSON)
        learning = client.chat.completions.create(
            model="google/gemini-2.0-flash-001" if base_url else "gpt-4o-mini",
            response_model=ExtractedLearning,
            max_retries=2,
            messages=[{"role": "user", "content": prompt}],
        )
        return {
            "outcome": learning.outcome,
            "summary": learning.summary,
            "key_insight": learning.key_insight,
        }
    except Exception as e:
        print(f"[effectiveness-learn] Extraction failed: {e}", file=sys.stderr)
        return None


def persist_learning(learning_data, task_id, task_type, tools_used, files_modified):
    """Call Agent42's HTTP API to persist the learning entry."""
    import urllib.request

    dashboard_url = os.environ.get("FROOD_DASHBOARD_URL", "http://127.0.0.1:8000")

    payload = {
        "task_type": task_type,
        "task_id": task_id,
        "outcome": learning_data["outcome"],
        "summary": learning_data["summary"],
        "key_insight": learning_data["key_insight"],
        "tools_used": tools_used,
        "files_modified": files_modified,
    }

    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{dashboard_url}/api/effectiveness/learn",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
        print(
            f"[effectiveness-learn] Persisted: {result.get('event_type', 'unknown')}",
            file=sys.stderr,
        )
        return True
    except Exception as e:
        print(f"[effectiveness-learn] Persist failed (non-critical): {e}", file=sys.stderr)
        return False


def main():
    try:
        event = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    # ── Trivial session guard (LEARN-05: skip noise) ─────────────────────
    tool_call_count = count_tool_calls(event)
    file_mod_count = count_file_modifications(event)

    if tool_call_count < 2 or file_mod_count < 1:
        print(
            f"[effectiveness-learn] Skipped: {tool_call_count} tool calls, {file_mod_count} file mods",
            file=sys.stderr,
        )
        sys.exit(0)

    # ── Gather session data ──────────────────────────────────────────────
    project_dir = event.get("project_dir", ".")
    task_id, task_type = read_task_context(project_dir)
    tools_used = get_tool_names(event)
    files_modified = get_modified_files(event)
    session_summary = get_last_assistant_message(event)

    if not session_summary:
        print("[effectiveness-learn] No assistant message found, skipping", file=sys.stderr)
        sys.exit(0)

    # ── LLM extraction ───────────────────────────────────────────────────
    learning = extract_learning_with_instructor(
        session_summary, tools_used, files_modified, task_type
    )

    if not learning:
        print("[effectiveness-learn] Extraction returned nothing, skipping", file=sys.stderr)
        sys.exit(0)

    # ── Persist to Agent42 ───────────────────────────────────────────────
    persist_learning(learning, task_id, task_type, tools_used, files_modified)

    print(
        f"[effectiveness-learn] Done: [{task_type}][{task_id[:8]}...][{learning['outcome']}]",
        file=sys.stderr,
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
