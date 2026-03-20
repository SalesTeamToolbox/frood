#!/usr/bin/env python3
# hook_event: UserPromptSubmit
# hook_timeout: 30
"""Context loader hook — detects work type and loads relevant context.

Triggered on UserPromptSubmit. Analyzes the prompt to detect what area of
the codebase is being worked on, then outputs relevant patterns and lessons
from .claude/lessons.md and reference docs from .claude/reference/ to stderr
for Claude to use.

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
        "section": "Deployment Patterns",
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
        "section": None,
    },
}

# Map work types to reference files loaded from .claude/reference/
REFERENCE_FILES = {
    "tools": ["terminology.md", "new-components.md", "conventions.md", "pitfalls-archive.md"],
    "skills": ["terminology.md", "new-components.md", "conventions.md"],
    "providers": ["terminology.md", "new-components.md", "pitfalls-archive.md"],
    "config": ["configuration.md", "pitfalls-archive.md"],
    "dashboard": ["terminology.md", "pitfalls-archive.md"],
    "deployment": ["deployment.md", "configuration.md", "pitfalls-archive.md"],
    "security": ["terminology.md", "pitfalls-archive.md"],
    "memory": ["terminology.md", "pitfalls-archive.md"],
    "structure": ["project-structure.md", "terminology.md"],
    "testing": ["pitfalls-archive.md"],
    "async": ["pitfalls-archive.md"],
}

# Map work types to jcodemunch MCP tool call recommendations.
# repo_id is NOT included here — it is injected by emit_jcodemunch_guidance().
JCODEMUNCH_GUIDANCE = {
    "tools": [
        {
            "tool": "search_symbols",
            "params": {"query": "Tool", "kind": "class", "file_pattern": "tools/**/*.py"},
            "purpose": "Understand existing tool API surface before making changes",
        },
        {
            "tool": "get_file_outline",
            "params": {"file_path": "tools/base.py"},
            "purpose": "Review Tool/ToolExtension ABC interface",
        },
    ],
    "security": [
        {
            "tool": "search_symbols",
            "params": {"query": "sandbox", "file_pattern": "core/**/*.py"},
            "purpose": "Map security-related symbols before editing",
        },
    ],
    "providers": [
        {
            "tool": "get_file_outline",
            "params": {"file_path": "providers/registry.py"},
            "purpose": "Review ProviderSpec/ModelSpec patterns",
        },
    ],
    "config": [
        {
            "tool": "get_file_outline",
            "params": {"file_path": "core/config.py"},
            "purpose": "Review Settings dataclass and from_env() pattern",
        },
    ],
    "dashboard": [
        {
            "tool": "search_symbols",
            "params": {"query": "endpoint", "file_pattern": "dashboard/**/*.py"},
            "purpose": "Find dashboard API endpoints before modifying routes",
        },
    ],
    "memory": [
        {
            "tool": "search_symbols",
            "params": {"query": "memory", "file_pattern": "memory/**/*.py"},
            "purpose": "Map memory subsystem symbols before editing",
        },
    ],
    "skills": [
        {
            "tool": "get_file_outline",
            "params": {"file_path": "skills/loader.py"},
            "purpose": "Review SkillLoader interface and loading patterns",
        },
    ],
    "testing": [
        {
            "tool": "search_symbols",
            "params": {"query": "conftest", "file_pattern": "tests/**/*.py"},
            "purpose": "Find shared fixtures and test utilities",
        },
    ],
}


def emit_jcodemunch_guidance(work_types, repo_id="local/agent42"):
    """Generate jcodemunch MCP tool call recommendations for detected work types.

    Collects guidance items for all detected work types, deduplicates by
    (tool, key_param) tuple, and returns a list of formatted guidance strings.

    Does NOT print — returns the strings for the caller to emit.

    Args:
        work_types: Set of detected work type strings.
        repo_id: The jcodemunch repository identifier to inject into params.

    Returns:
        List of formatted guidance strings (one per recommended MCP call).
    """
    if not work_types:
        return []

    seen = set()
    guidance_items = []

    for wt in sorted(work_types):
        for item in JCODEMUNCH_GUIDANCE.get(wt, []):
            # Build dedup key from tool name + distinguishing param
            params = item["params"]
            key_param = params.get("file_path") or params.get("query", "")
            dedup_key = (item["tool"], key_param)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            # Build parameter string with repo_id injected
            all_params = {"repo": repo_id}
            all_params.update(params)
            param_lines = "\n".join(f"      {k}: {json.dumps(v)}" for k, v in all_params.items())
            guidance_items.append(
                f"{item['purpose']}:\n    mcp__jcodemunch__{item['tool']} with:\n{param_lines}"
            )

    return guidance_items


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


def load_reference_files(project_dir, work_types):
    """Load relevant reference files for detected work types."""
    ref_dir = os.path.join(project_dir, ".claude", "reference")
    if not os.path.isdir(ref_dir):
        return ""

    files_to_load = set()
    for wt in work_types:
        for fname in REFERENCE_FILES.get(wt, []):
            files_to_load.add(fname)

    if not files_to_load:
        return ""

    parts = []
    for fname in sorted(files_to_load):
        path = os.path.join(ref_dir, fname)
        if os.path.exists(path):
            try:
                with open(path) as f:
                    parts.append(f.read().strip())
            except OSError:
                continue

    return "\n\n".join(parts)


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
        section = config.get("section") if isinstance(config, dict) else None
        if section:
            sections.add(section)

    lessons = load_lessons(project_dir, sections)

    # Load relevant reference files
    references = load_reference_files(project_dir, work_types)

    if lessons or references:
        print(
            f"[context-loader] Detected work types: {', '.join(sorted(work_types))}",
            file=sys.stderr,
        )
        if lessons:
            print(f"[context-loader] Relevant patterns:\n{lessons}", file=sys.stderr)
        if references:
            print(f"[context-loader] Reference docs:\n{references}", file=sys.stderr)

    # Emit jcodemunch MCP tool call guidance
    guidance = emit_jcodemunch_guidance(work_types)
    if guidance:
        numbered = "\n".join(f"  {i + 1}. {g}" for i, g in enumerate(guidance))
        print(
            f"[context-loader] jcodemunch guidance -- run these before starting work:\n{numbered}",
            file=sys.stderr,
        )

    # Memory storage reminder — nudge Claude to persist important findings
    _emit_memory_nudge(prompt)

    sys.exit(0)


def _emit_memory_nudge(prompt):
    """Remind Claude to store important discoveries via agent42_memory.

    Triggers on prompts that suggest knowledge-producing work (debugging,
    investigating, deploying, fixing, configuring). Skips trivial prompts
    and slash commands.
    """
    if not prompt or len(prompt.strip()) < 20:
        return
    if prompt.strip().startswith("/"):
        return

    text = prompt.lower()
    # Detect prompts likely to produce store-worthy knowledge
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
        "agent42_memory MCP tool with action=store so it's available in future sessions.",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
