#!/usr/bin/env python3
"""Context loader hook — detects work type and loads relevant context.

Triggered on UserPromptSubmit. Analyzes the prompt to detect what area of
the codebase is being worked on, then outputs relevant patterns and lessons
from .claude/lessons.md to stderr for Claude to use.

Hook protocol:
- Receives JSON on stdin with hook_event_name, project_dir, user_prompt
- Output to stderr is shown to Claude as feedback
- Exit code 0 = allow (always allow for this hook)
"""

import json
import os
import sys

# Work type detection keywords mapped to lessons.md sections
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
        "section": "Security Patterns",
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
        "section": "Tool Development",
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
        "section": "Testing Patterns",
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
        "section": "Provider Patterns",
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
        "section": "Skill Development",
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
        "section": "Async Patterns",
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
        "section": "Configuration Patterns",
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
        "section": "Dashboard Patterns",
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
        "section": "Memory Patterns",
    },
}


def detect_work_types(prompt_text, tool_input=None):
    """Detect work types from prompt text and tool input."""
    detected = set()
    text = (prompt_text or "").lower()

    for work_type, config in WORK_TYPE_KEYWORDS.items():
        # Check keywords in prompt
        for keyword in config["keywords"]:
            if keyword.lower() in text:
                detected.add(work_type)
                break

        # Check file paths if tool input has them
        if tool_input:
            file_path = tool_input.get("file_path", "") or tool_input.get("path", "")
            for pattern in config["files"]:
                if pattern and file_path and pattern in file_path:
                    detected.add(work_type)
                    break

    return detected


def load_lessons(project_dir, sections):
    """Load relevant sections from lessons.md."""
    lessons_path = os.path.join(project_dir, ".claude", "lessons.md")
    if not os.path.exists(lessons_path):
        return ""

    try:
        with open(lessons_path) as f:
            content = f.read()
    except OSError:
        return ""

    # Extract relevant sections
    relevant = []
    current_section = None
    current_lines = []

    for line in content.split("\n"):
        if line.startswith("## "):
            if current_section and current_section in sections:
                relevant.extend(current_lines)
            current_section = line[3:].strip()
            current_lines = [line]
        else:
            current_lines.append(line)

    # Don't forget the last section
    if current_section and current_section in sections:
        relevant.extend(current_lines)

    return "\n".join(relevant).strip()


def main():
    try:
        event = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    project_dir = event.get("project_dir", ".")
    prompt = ""

    # Extract prompt text from the event
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

    if not work_types:
        sys.exit(0)

    # Load relevant lessons
    sections = set()
    for wt in work_types:
        config = WORK_TYPE_KEYWORDS.get(wt, {})
        if "section" in config:
            sections.add(config["section"])

    lessons = load_lessons(project_dir, sections)

    if lessons:
        print(
            f"[context-loader] Detected work types: {', '.join(sorted(work_types))}",
            file=sys.stderr,
        )
        print(f"[context-loader] Relevant patterns:\n{lessons}", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
