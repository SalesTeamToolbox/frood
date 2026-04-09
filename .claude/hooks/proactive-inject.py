#!/usr/bin/env python3
# hook_event: UserPromptSubmit
# hook_timeout: 10
"""Proactive learning injection hook — surfaces relevant past learnings at task start.

Triggered on UserPromptSubmit. Infers the task type from prompt keywords, then
fetches relevant past learnings from the Frood API and injects them into
Claude's context via stderr.

Behavior:
- Infers task_type from prompt keywords (no LLM call)
- Fetches top-3 learnings with score >= 0.80 from /api/learnings/retrieve
- Injects once per session (session guard file prevents re-injection)
- Skips slash commands, very short prompts, and unknown task types
- Always exits 0 (never blocks the prompt)

Hook protocol:
- Receives JSON on stdin: {hook_event_name, project_dir, user_prompt, session_id, ...}
- Output to stderr is shown to Claude as context
- Exit code 0 = allow (always allow)
"""

import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# ── Configuration ────────────────────────────────────────────────────────────
MIN_PROMPT_LEN = 15
MAX_OUTPUT_CHARS = 2000
DASHBOARD_URL = os.environ.get("FROOD_DASHBOARD_URL", "http://127.0.0.1:8000")
INJECTION_GUARD_DIR = os.environ.get("FROOD_DATA_DIR", ".frood")

# Task type keyword mappings for prompt-based inference (no LLM needed)
# app_create uses multi-word phrases and must be checked first for priority
TASK_TYPE_KEYWORDS = {
    "app_create": [
        "flask app",
        "django app",
        "react app",
        "vue app",
        "fastapi app",
        "scaffold",
        "boilerplate",
        "starter",
        "new project",
        "new app",
    ],
    "coding": [
        "implement",
        "create",
        "build",
        "add",
        "endpoint",
        "api",
        "function",
        "class",
        "module",
        "component",
        "route",
        "handler",
        "middleware",
        "schema",
        "model",
        "migration",
    ],
    "debugging": [
        "fix",
        "bug",
        "debug",
        "error",
        "crash",
        "broken",
        "failing",
        "issue",
        "wrong",
        "trace",
        "stack",
        "exception",
        "diagnose",
        "investigate",
    ],
    "research": [
        "research",
        "compare",
        "evaluate",
        "analyze",
        "explore",
        "study",
        "review",
        "assess",
        "benchmark",
    ],
    "content": [
        "write",
        "document",
        "readme",
        "docs",
        "blog",
        "content",
        "copy",
        "text",
        "article",
    ],
    "strategy": [
        "plan",
        "design",
        "architect",
        "roadmap",
        "strategy",
        "structure",
        "organize",
        "refactor",
    ],
    "marketing": [
        "marketing",
        "seo",
        "campaign",
        "audience",
        "brand",
        "promotion",
    ],
}

# Tie-breaking priority order (lower index = higher priority)
_TIE_PRIORITY = [
    "coding",
    "debugging",
    "strategy",
    "research",
    "content",
    "marketing",
    "app_create",
]


def infer_task_type(prompt: str) -> str:
    """Infer task type from prompt text using keyword matching.

    Args:
        prompt: The raw user prompt string.

    Returns:
        A TaskType string value (e.g. "coding", "debugging") or "" if no type detected.
    """
    if not prompt or len(prompt) < MIN_PROMPT_LEN:
        return ""

    text = prompt.lower()

    # Check app_create first — multi-word phrases take priority over single keywords
    for phrase in TASK_TYPE_KEYWORDS["app_create"]:
        if phrase in text:
            return "app_create"

    # Count keyword matches for all other types
    scores: dict[str, int] = {}
    for task_type, keywords in TASK_TYPE_KEYWORDS.items():
        if task_type == "app_create":
            continue
        count = sum(1 for kw in keywords if kw in text)
        if count > 0:
            scores[task_type] = count

    if not scores:
        return ""

    # Find max score
    max_score = max(scores.values())
    candidates = [t for t, s in scores.items() if s == max_score]

    if len(candidates) == 1:
        return candidates[0]

    # Tie-break by priority order
    for preferred in _TIE_PRIORITY:
        if preferred in candidates:
            return preferred

    # Fallback: return first candidate alphabetically
    return sorted(candidates)[0]


def _guard_file_path(project_dir: str) -> Path:
    """Return the path to the session injection guard file."""
    return Path(project_dir) / INJECTION_GUARD_DIR / "injection-done.json"


def is_injection_done(project_dir: str, session_id: str) -> bool:
    """Check if injection was already done for this session.

    Args:
        project_dir: The project root directory.
        session_id: The current session identifier.

    Returns:
        True if injection was already done for this exact session_id.
    """
    guard_file = _guard_file_path(project_dir)
    if not guard_file.exists():
        return False

    try:
        data = json.loads(guard_file.read_text(encoding="utf-8"))
        return data.get("session_id") == session_id
    except (json.JSONDecodeError, OSError, Exception):
        return False


def mark_injection_done(project_dir: str, session_id: str) -> None:
    """Write the session guard file to prevent re-injection.

    Args:
        project_dir: The project root directory.
        session_id: The current session identifier.
    """
    try:
        guard_file = _guard_file_path(project_dir)
        guard_file.parent.mkdir(parents=True, exist_ok=True)
        guard_file.write_text(
            json.dumps({"session_id": session_id, "ts": time.time()}),
            encoding="utf-8",
        )
    except Exception:
        pass  # Non-critical — never raise


def fetch_learnings(query: str, task_type: str) -> list:
    """Fetch relevant past learnings from the Frood API.

    Args:
        query: The user prompt text to use as semantic query (first 500 chars).
        task_type: The inferred task type string.

    Returns:
        List of result dicts from /api/learnings/retrieve, or [] on any error.
    """
    try:
        params = urllib.parse.urlencode(
            {
                "task_type": task_type,
                "query": query,
                "top_k": 3,
                "min_score": 0.80,
            }
        )
        url = f"{DASHBOARD_URL}/api/learnings/retrieve?{params}"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        return data.get("results", [])
    except Exception:
        return []


def format_injection_output(results: list, task_type: str) -> str:
    """Format the learning injection output for stderr.

    Args:
        results: List of learning result dicts (each with 'score' and 'text').
        task_type: The task type string used for retrieval.

    Returns:
        Formatted string truncated to MAX_OUTPUT_CHARS.
    """
    header = (
        f"[frood-learnings] Injecting {len(results)} past learnings for task_type={task_type}"
    )
    lines = [header]

    for r in results:
        score = r.get("score", 0.0)
        text = r.get("text", "").strip()
        lines.append(f"  - [{score:.0%}] {text}")

    lines.append("(Proactive injection \u2014 these are past learnings relevant to this task type)")

    output = "\n".join(lines)
    if len(output) > MAX_OUTPUT_CHARS:
        output = output[:MAX_OUTPUT_CHARS]

    return output


def fetch_recommendations(task_type: str) -> list:
    """Fetch tool recommendations from the Frood API.

    Args:
        task_type: The inferred task type string.

    Returns:
        List of recommendation dicts from /api/recommendations/retrieve, or [] on any error.
    """
    try:
        params = urllib.parse.urlencode({"task_type": task_type, "top_k": 3})
        url = f"{DASHBOARD_URL}/api/recommendations/retrieve?{params}"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        return data.get("recommendations", [])
    except Exception:
        return []


def format_recommendations_output(recs: list, task_type: str) -> str:
    """Format recommendations as a compact ranked list for stderr.

    Args:
        recs: List of recommendation dicts (each with tool_name, success_rate, avg_duration_ms).
        task_type: The task type string used for retrieval.

    Returns:
        Formatted string truncated to MAX_OUTPUT_CHARS, or "" if no recommendations.
    """
    if not recs:
        return ""
    lines = [f"[frood-recommendations] Top tools for {task_type}:"]
    for i, r in enumerate(recs, 1):
        name = r.get("tool_name", "?")
        rate = r.get("success_rate", 0.0)
        dur = r.get("avg_duration_ms", 0.0)
        lines.append(f"  {i}. {name} ({rate:.0%} success, {dur:.0f}ms avg)")
    output = "\n".join(lines)
    if len(output) > MAX_OUTPUT_CHARS:
        output = output[:MAX_OUTPUT_CHARS]
    return output


def main():
    """Main hook entry point. Always exits 0."""
    try:
        event = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError, Exception):
        sys.exit(0)

    project_dir = event.get("project_dir", ".")
    prompt = event.get("user_prompt", "")

    # Skip slash commands
    if prompt.strip().startswith("/"):
        sys.exit(0)

    # Skip very short prompts
    if len(prompt.strip()) < MIN_PROMPT_LEN:
        sys.exit(0)

    # Determine session identifier
    session_id = event.get("session_id", "")
    if not session_id:
        # Derive stable session identifier from project_dir hash
        session_id = hashlib.md5(project_dir.encode()).hexdigest()[:16]

    # Session-once guard — skip if already injected this session
    if is_injection_done(project_dir, session_id):
        sys.exit(0)

    # Infer task type from prompt keywords
    task_type = infer_task_type(prompt)
    if not task_type:
        sys.exit(0)

    # Fetch learnings from API (existing)
    learnings = fetch_learnings(prompt[:500], task_type)

    # Fetch recommendations from API (new — per D-01, D-03)
    recs = fetch_recommendations(task_type)

    # Exit early only if BOTH are empty
    if not learnings and not recs:
        sys.exit(0)

    # Emit learnings block to stderr (if any)
    if learnings:
        learnings_output = format_injection_output(learnings, task_type)
        print(learnings_output, file=sys.stderr)

    # Emit recommendations block to stderr as separate section (per D-07)
    if recs:
        recs_output = format_recommendations_output(recs, task_type)
        if recs_output:
            print(recs_output, file=sys.stderr)

    # Mark injection as done for this session (after BOTH calls per D-03)
    mark_injection_done(project_dir, session_id)

    sys.exit(0)


if __name__ == "__main__":
    main()
