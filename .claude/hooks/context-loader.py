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
        "section": None,
    },
}

# Map work types to reference files loaded from .claude/reference/
# NOTE: pitfalls-archive.md is handled separately via filtered loading — do NOT
# include it here. Only small, targeted reference files belong in this dict.
REFERENCE_FILES = {
    "tools": ["terminology.md", "new-components.md", "conventions.md"],
    "skills": ["terminology.md", "new-components.md", "conventions.md"],
    "providers": ["terminology.md", "new-components.md"],
    "config": ["configuration.md"],
    "dashboard": ["terminology.md"],
    "deployment": ["deployment.md", "configuration.md"],
    "security": ["terminology.md"],
    "memory": ["terminology.md"],
    "structure": ["project-structure.md", "terminology.md"],
    "testing": [],
    "async": [],
}

# Map work types to relevant pitfall Area values for filtered loading.
# Each work type pulls only the pitfall rows whose Area column matches.
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

# Maximum characters for reference doc output (prevents unbounded injection)
MAX_REFERENCE_CHARS = 6000  # ~1,500 tokens

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

    content = _cached_read(lessons_path)
    if not content:
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


def _filter_pitfalls(content, work_types):
    """Filter pitfalls-archive.md to only rows matching detected work types.

    Parses the markdown table and returns only the header + rows whose Area
    column matches the PITFALL_AREAS for the detected work types.

    Returns empty string if no rows match.
    """
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
        # Capture header row and separator
        if stripped.startswith("| #") or stripped.startswith("|---"):
            header_lines.append(stripped)
            continue
        # Parse Area column (column index 2 after split)
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
    return "\n".join(result_lines)


def load_reference_files(project_dir, work_types):
    """Load relevant reference files for detected work types.

    Small reference files are loaded in full. pitfalls-archive.md is filtered
    to only include rows matching the detected work types' areas.
    Total output is capped at MAX_REFERENCE_CHARS (~1,500 tokens).
    """
    ref_dir = os.path.join(project_dir, ".claude", "reference")
    if not os.path.isdir(ref_dir):
        return ""

    # Collect small reference files
    files_to_load = set()
    for wt in work_types:
        for fname in REFERENCE_FILES.get(wt, []):
            files_to_load.add(fname)

    # Filtered pitfalls first — these are the most actionable reference
    pitfalls_path = os.path.join(ref_dir, "pitfalls-archive.md")
    parts = []
    if os.path.exists(pitfalls_path):
        pitfalls_content = _cached_read(pitfalls_path)
        if pitfalls_content:
            filtered = _filter_pitfalls(pitfalls_content, work_types)
            if filtered:
                parts.append(filtered)

    # Then append smaller reference files with remaining budget
    for fname in sorted(files_to_load):
        path = os.path.join(ref_dir, fname)
        if os.path.exists(path):
            content = _cached_read(path)
            if content:
                parts.append(content.strip())

    if not parts:
        return ""

    output = "\n\n".join(parts)
    if len(output) > MAX_REFERENCE_CHARS:
        output = output[:MAX_REFERENCE_CHARS] + "\n... (truncated)"
    return output


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

    # GSD nudge for multi-step prompts (per D-06, D-10)
    if "gsd" in work_types:
        _emit_gsd_nudge(prompt, project_dir)
        work_types.discard("gsd")

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


def _emit_gsd_nudge(prompt, project_dir):
    """Suggest GSD for multi-step prompts when not already in a GSD session.

    Per D-06: One-line stderr nudge, not intrusive.
    Per D-10: Secondary mechanism — the always-on skill is primary.
    """
    if not prompt or len(prompt.strip()) < 30:
        return
    stripped = prompt.strip()
    if stripped.startswith("/"):
        return
    # Skip trivial question patterns per D-02
    trivial_starts = ("what ", "how ", "why ", "explain ", "show me ", "what's ")
    if any(stripped.lower().startswith(t) for t in trivial_starts):
        return
    # Skip if GSD session already active per D-13
    active_ws = os.path.join(project_dir, ".planning", "active-workstream")
    if os.path.exists(active_ws):
        try:
            with open(active_ws) as f:
                if f.read().strip():
                    return  # Active workstream — no nudge
        except OSError:
            pass
    print(
        "[agent42] Tip: This looks like a multi-step task \u2014 "
        "/gsd:new-project or /gsd:quick available",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
