#!/usr/bin/env python3
# hook_event: UserPromptSubmit
# hook_timeout: 15
"""Context loader hook — lightweight, high-value context injection.

Triggered on UserPromptSubmit. Detects work type from prompt keywords, then
emits only high-value context to stderr:
1. Filtered pitfalls (only rows matching work type, not the full 26KB archive)
2. GSD nudge (for multi-step prompts not already in a GSD session)
3. Memory nudge (reminder to store discoveries during knowledge-producing work)

Reference docs (terminology, conventions, etc.) are NOT injected — Claude can
read them on-demand via the pointers in CLAUDE.md. Lessons are folded into
reference docs. This keeps per-prompt injection under ~800 tokens.

Hook protocol:
- Receives JSON on stdin with hook_event_name, project_dir, user_prompt
- Output to stderr is shown to Claude as feedback
- Exit code 0 = allow (always allow for this hook)
"""

import json
import os
import sys

# Module-level mtime-based file cache: path -> (mtime, content)
_file_cache: dict[str, tuple[float, str]] = {}


def _cached_read(path: str) -> str:
    """Read a file, using cached content if mtime is unchanged."""
    try:
        mtime = os.stat(path).st_mtime
    except OSError:
        return ""
    if path in _file_cache:
        cached_mtime, cached_content = _file_cache[path]
        if cached_mtime == mtime:
            return cached_content
    try:
        with open(path, encoding="utf-8") as f:
            content = f.read()
    except OSError:
        return ""
    _file_cache[path] = (mtime, content)
    return content


# Work type detection keywords (section field kept for backward compat but unused)
WORK_TYPE_KEYWORDS = {
    "security": {
        "keywords": [
            "sandbox",
            "command_filter",
            "approval_gate",
            "auth",
            "rate_limit",
            "url_policy",
            "security",
            "permission",
            "token",
            "password",
            "jwt",
            "credential",
            "encrypt",
            "ssrf",
            "injection",
            "xss",
        ],
        "files": [
            "core/sandbox.py",
            "core/command_filter.py",
            "core/approval_gate.py",
            "dashboard/auth.py",
            "core/rate_limiter.py",
            "core/url_policy.py",
            "tools/shell.py",
            "core/security_scanner.py",
        ],
    },
    "tools": {
        "keywords": [
            "tool",
            "execute",
            "ToolResult",
            "registry",
            "register",
            "to_schema",
            "parameters",
        ],
        "files": ["tools/"],
    },
    "testing": {
        "keywords": [
            "test",
            "pytest",
            "fixture",
            "mock",
            "assert",
            "conftest",
            "coverage",
            "test_",
        ],
        "files": ["tests/"],
    },
    "providers": {
        "keywords": [
            "provider",
            "model",
            "openrouter",
            "openai",
            "anthropic",
            "deepseek",
            "gemini",
            "vllm",
            "ProviderSpec",
            "ModelSpec",
            "spending",
            "api_key",
        ],
        "files": ["providers/"],
    },
    "skills": {
        "keywords": [
            "skill",
            "SKILL.md",
            "frontmatter",
            "task_type",
            "builtin",
            "workspace",
            "loader",
        ],
        "files": ["skills/"],
    },
    "async": {
        "keywords": [
            "async",
            "await",
            "asyncio",
            "aiofiles",
            "coroutine",
            "event_loop",
            "gather",
            "TaskGroup",
        ],
        "files": [],
    },
    "config": {
        "keywords": [
            "config",
            "settings",
            "env",
            "environment",
            "Settings",
            "from_env",
            ".env",
        ],
        "files": ["core/config.py", ".env.example"],
    },
    "dashboard": {
        "keywords": [
            "dashboard",
            "fastapi",
            "websocket",
            "jwt",
            "login",
            "api",
            "endpoint",
            "route",
        ],
        "files": ["dashboard/"],
    },
    "memory": {
        "keywords": [
            "memory",
            "session",
            "embedding",
            "qdrant",
            "redis",
            "semantic",
            "vector",
            "consolidat",
        ],
        "files": ["memory/"],
    },
    "deployment": {
        "keywords": [
            "deploy",
            "install",
            "nginx",
            "systemd",
            "docker",
            "production",
            "server",
            "compose",
        ],
        "files": ["deploy/", "Dockerfile", "docker-compose.yml"],
    },
    "structure": {
        "keywords": [
            "structure",
            "architecture",
            "overview",
            "onboarding",
            "where is",
            "find file",
            "project layout",
        ],
        "files": [],
    },
    "gsd": {
        "keywords": [
            "build",
            "create",
            "implement",
            "refactor",
            "add feature",
            "set up",
            "migrate",
            "convert",
            "redesign",
            "scaffold",
            "flask app",
            "django",
            "react app",
            "vue app",
            "fastapi app",
            "plan",
            "roadmap",
            "milestone",
            "phases",
            "workstream",
        ],
        "files": [],
    },
}

# Map work types to relevant pitfall Area values for filtered loading.
PITFALL_AREAS = {
    "tools": {"Tools", "Extensions", "Registry", "Import"},
    "security": {"Security", "Auth", "JWT", "Shell", "Subprocess"},
    "providers": {"Providers", "Registry", "Catalog", "Tokens"},
    "config": {"Config", "Init", "Init Order", "Startup"},
    "dashboard": {"Dashboard", "Auth", "JWT", "Frontend", "Server"},
    "deployment": {"Deploy", "Server", "Startup", "Config"},
    "memory": {"Memory", "Embeddings", "Search", "Context"},
    "testing": {"Tests", "AppTest", "Formatting"},
    "async": {"Async", "Subprocess"},
    "skills": set(),
    "structure": set(),
}

# Maximum characters for pitfalls output
MAX_PITFALLS_CHARS = 4000  # ~1,000 tokens


def detect_work_types(prompt_text, tool_input=None):
    """Detect work types from prompt text and tool input."""
    detected = set()
    text = (prompt_text or "").lower()

    for work_type, config in WORK_TYPE_KEYWORDS.items():
        for keyword in config["keywords"]:
            if keyword.lower() in text:
                detected.add(work_type)
                break

        if tool_input:
            file_path = tool_input.get("file_path", "") or tool_input.get("path", "")
            for pattern in config["files"]:
                if pattern and file_path and pattern in file_path:
                    detected.add(work_type)
                    break

    return detected


def _filter_pitfalls(content, work_types):
    """Filter pitfalls-archive.md to only rows matching detected work types."""
    relevant_areas = set()
    for wt in work_types:
        relevant_areas.update(PITFALL_AREAS.get(wt, set()))

    if not relevant_areas:
        return ""

    lines = content.split("\n")
    header_lines = []
    matching_rows = []

    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        if stripped.startswith("| #") or stripped.startswith("|---"):
            header_lines.append(stripped)
            continue
        parts = [p.strip() for p in stripped.split("|")]
        if len(parts) >= 4:
            area = parts[2]
            if area in relevant_areas:
                matching_rows.append(stripped)

    if not matching_rows:
        return ""

    result_lines = [f"# Relevant Pitfalls ({len(matching_rows)} of 124)"]
    result_lines.extend(header_lines)
    result_lines.extend(matching_rows)

    output = "\n".join(result_lines)
    if len(output) > MAX_PITFALLS_CHARS:
        output = output[:MAX_PITFALLS_CHARS] + "\n... (truncated)"
    return output


def load_filtered_pitfalls(project_dir, work_types):
    """Load only the relevant pitfalls for detected work types."""
    pitfalls_path = os.path.join(project_dir, ".claude", "reference", "pitfalls-archive.md")
    if not os.path.exists(pitfalls_path):
        return ""
    content = _cached_read(pitfalls_path)
    if not content:
        return ""
    return _filter_pitfalls(content, work_types)


def main():
    try:
        event = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    project_dir = event.get("project_dir", ".")
    prompt = ""

    if "user_prompt" in event:
        prompt = event["user_prompt"]
    elif "messages" in event:
        for msg in reversed(event["messages"]):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, str):
                    prompt = content
                elif isinstance(content, list):
                    prompt = " ".join(c.get("text", "") for c in content if isinstance(c, dict))
                break

    # Detect work types
    work_types = detect_work_types(prompt)

    # GSD nudge for multi-step prompts
    if "gsd" in work_types:
        _emit_gsd_nudge(prompt, project_dir)
        work_types.discard("gsd")

    if not work_types:
        # Even without work types, check for memory nudge
        _emit_memory_nudge(prompt)
        sys.exit(0)

    # Emit filtered pitfalls (only matching rows)
    pitfalls = load_filtered_pitfalls(project_dir, work_types)
    if pitfalls:
        print(
            f"[context-loader] Detected work types: {', '.join(sorted(work_types))}",
            file=sys.stderr,
        )
        print(f"[context-loader] Pitfalls:\n{pitfalls}", file=sys.stderr)

    # Memory storage reminder
    _emit_memory_nudge(prompt)

    sys.exit(0)


def _emit_memory_nudge(prompt):
    """Remind Claude to store important discoveries via frood_memory."""
    if not prompt or len(prompt.strip()) < 20:
        return
    if prompt.strip().startswith("/"):
        return

    text = prompt.lower()
    knowledge_signals = [
        "fix",
        "debug",
        "deploy",
        "config",
        "setup",
        "investigate",
        "why",
        "how does",
        "figure out",
        "diagnose",
        "resolve",
        "integrate",
        "migrate",
        "upgrade",
        "refactor",
    ]
    if not any(signal in text for signal in knowledge_signals):
        return

    print(
        "[context-loader] Memory reminder: If you discover something non-obvious "
        "during this task (a fix, a gotcha, a config detail), store it using the "
        "frood_memory MCP tool with action=store so it's available in future sessions.",
        file=sys.stderr,
    )


def _emit_gsd_nudge(prompt, project_dir):
    """Suggest GSD for multi-step prompts when not already in a GSD session."""
    if not prompt or len(prompt.strip()) < 30:
        return
    stripped = prompt.strip()
    if stripped.startswith("/"):
        return
    trivial_starts = ("what ", "how ", "why ", "explain ", "show me ", "what's ")
    if any(stripped.lower().startswith(t) for t in trivial_starts):
        return
    active_ws = os.path.join(project_dir, ".planning", "active-workstream")
    if os.path.exists(active_ws):
        try:
            with open(active_ws) as f:
                if f.read().strip():
                    return
        except OSError:
            pass
    print(
        "[frood] Tip: This looks like a multi-step task \u2014 "
        "/gsd:new-project or /gsd:quick available",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
