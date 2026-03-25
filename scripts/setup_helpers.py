#!/usr/bin/env python3
"""Setup helper library for Agent42 + Claude Code environment configuration.

Provides Python helpers for MCP config generation, hook registration, and health
probes. All JSON config manipulation happens here — never in bash.

Callable as a module (import) or via CLI subcommands:
    python3 scripts/setup_helpers.py mcp-config <project_dir> [<ssh_alias>]
    python3 scripts/setup_helpers.py register-hooks <project_dir>
    python3 scripts/setup_helpers.py health <project_dir>

Uses only Python stdlib — no external dependencies required.
"""

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request


def _venv_python(project_dir: str) -> str:
    """Return the correct venv python executable path for the current platform."""
    if sys.platform == "win32":
        return os.path.join(project_dir, ".venv", "Scripts", "python.exe")
    return os.path.join(project_dir, ".venv", "bin", "python")


# ---------------------------------------------------------------------------
# Server template definitions
# ---------------------------------------------------------------------------


def _make_agent42_entry(project_dir: str, venv_python: str) -> dict:
    return {
        "command": venv_python,
        "args": [os.path.join(project_dir, "mcp_server.py")],
        "env": {
            "AGENT42_WORKSPACE": project_dir,
            "REDIS_URL": "redis://localhost:6379/0",
            "QDRANT_URL": "http://localhost:6333",
        },
    }


def _make_agent42_remote_entry(ssh_alias: str) -> dict:
    return {
        "command": "ssh",
        "args": [
            ssh_alias,
            "cd ~/agent42 && AGENT42_WORKSPACE=~/agent42 .venv/bin/python mcp_server.py",
        ],
        "env": {},
    }


_STATIC_SERVERS = {
    "jcodemunch": {
        "command": "uvx",
        "args": ["jcodemunch-mcp"],
        "env": {},
    },
    "context7": {
        "command": "npx",
        "args": ["-y", "@upstash/context7-mcp@latest"],
        "env": {},
    },
    "github": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-github"],
        "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_PERSONAL_ACCESS_TOKEN}"},
    },
    "playwright": {
        "command": "npx",
        "args": ["-y", "@anthropic/mcp-server-playwright"],
        "env": {},
    },
}


# ---------------------------------------------------------------------------
# CLAUDE.md memory section template
# ---------------------------------------------------------------------------

_CLAUDE_MD_BEGIN = "<!-- BEGIN AGENT42 MEMORY -->"
_CLAUDE_MD_END = "<!-- END AGENT42 MEMORY -->"

CLAUDE_MD_TEMPLATE = """\
<!-- BEGIN AGENT42 MEMORY -->
## Agent42 Memory

Agent42 provides a persistent, semantically-searchable memory layer via the `agent42_memory`
MCP tool. These instructions configure Claude Code to use Agent42 as its primary memory system.

### When to search memory

ALWAYS call `agent42_memory` with action `search` before answering any question that
could draw on past project decisions, user preferences, debugging history, or architectural
choices. Do not rely solely on your context window or built-in memory files.

```
agent42_memory(action="search", content="<your query>")
```

### When to store

After learning something important -- a user preference, a project decision, a fix for
a recurring bug -- call `agent42_memory` with action `store` IN ADDITION to any
built-in memory write. This ensures the information is searchable by semantic meaning,
not just file name.

```
agent42_memory(action="store", section="<Category>", content="<what to remember>")
```

### When to log

After completing a significant task or resolving a non-obvious problem, call
`agent42_memory` with action `log` to record the event in the project timeline.

```
agent42_memory(action="log", event_type="task_completed", content="<summary>")
```
<!-- END AGENT42 MEMORY -->
"""


def _detect_project_context(project_dir: str) -> dict:
    """Detect project name, jcodemunch repo ID, and active GSD workstream.

    Args:
        project_dir: Absolute path to the project root.

    Returns:
        Dict with keys: project_name, jcodemunch_repo, active_workstream, venv_python.
    """
    project_name = os.path.basename(os.path.abspath(project_dir))

    # Try to get a better name from git remote
    try:
        result = subprocess.run(
            ["git", "-C", project_dir, "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            url = result.stdout.strip()
            # Handle SSH: git@github.com:org/repo.git
            # Handle HTTPS: https://github.com/org/repo.git
            if ":" in url and not url.startswith("http"):
                repo_part = url.split(":")[-1]
            else:
                repo_part = url
            name = repo_part.split("/")[-1].removesuffix(".git")
            if name:
                project_name = name
    except Exception:
        pass

    jcodemunch_repo = f"local/{project_name}"

    active_workstream = None
    workstreams_dir = os.path.join(project_dir, ".planning", "workstreams")
    if os.path.isdir(workstreams_dir):
        for ws_name in sorted(os.listdir(workstreams_dir)):
            state_path = os.path.join(workstreams_dir, ws_name, "STATE.md")
            if os.path.isfile(state_path):
                try:
                    with open(state_path, encoding="utf-8") as f:
                        content = f.read()
                    if "status: active" in content or "status: in-progress" in content:
                        active_workstream = ws_name
                        break
                except OSError:
                    continue

    return {
        "project_name": project_name,
        "jcodemunch_repo": jcodemunch_repo,
        "active_workstream": active_workstream,
        "venv_python": _venv_python(project_dir),
    }


# ---------------------------------------------------------------------------
# Full CLAUDE.md template for consumer projects using Agent42 as MCP server
# ---------------------------------------------------------------------------

_FULL_CLAUDE_MD_TEMPLATE = """\
## Quick Reference

```bash
python -m pytest tests/ -x -q    # Run tests (stop on first failure)
python -m pytest tests/ -v        # Verbose: see all test names
```

---

## Codebase Navigation (jcodemunch)

This project is indexed by jcodemunch MCP server (`{jcodemunch_repo}`).
**Use jcodemunch tools before reading files** to understand structure and find the right code:

| When you need to... | Use this tool |
|----------------------|---------------|
| Understand a module before editing | `get_file_outline` — shows all classes, functions, signatures |
| Find where something is defined | `search_symbols` — search by name across the codebase |
| Explore a directory's structure | `get_file_tree` with `path_prefix` |
| Read a specific symbol's code | `get_symbol` — returns the full source of a function/class |
| Find text patterns across files | `search_text` — grep-like search across indexed files |
| Re-index after major changes | `index_folder` with `incremental: true` |

**Repo identifier:** `{jcodemunch_repo}` (use this as the `repo` parameter in all jcodemunch calls)

---

## Agent42 Hook Protocol

Agent42 registers Claude Code hooks that run automatically during development sessions.
No manual activation required — hooks are registered by `bash setup.sh`.

| Hook Trigger | What It Does For You |
|--------------|----------------------|
| UserPromptSubmit | Surfaces relevant memories and past decisions before Claude responds |
| UserPromptSubmit | Loads task-type-specific lessons and reference docs |
| PreToolUse (Write/Edit) | Blocks edits to security-sensitive files (requires approval) |
| PostToolUse (Write/Edit) | Auto-formats Python files, embeds learnings into Qdrant |
| Stop | Captures session state, runs tests, records patterns for future sessions |
| SessionStart | Syncs Claude Code credentials to configured remote nodes |

**Hook protocol details:**
- Hooks receive JSON on stdin with `hook_event_name`, `project_dir`, and event-specific data
- Output to stderr is shown to Claude as feedback
- Exit code 0 = allow, exit code 2 = block (for PreToolUse hooks)

---

## Agent42 Memory

Agent42 provides a persistent, semantically-searchable memory layer via the `agent42_memory`
MCP tool. These instructions configure Claude Code to use Agent42 as its primary memory system.

### When to search memory

ALWAYS call `agent42_memory` with action `search` before answering any question that
could draw on past project decisions, user preferences, debugging history, or architectural
choices. Do not rely solely on your context window or built-in memory files.

```
agent42_memory(action="search", content="<your query>")
```

### When to store

After learning something important — a user preference, a project decision, a fix for
a recurring bug — call `agent42_memory` with action `store` IN ADDITION to any
built-in memory write. This ensures the information is searchable by semantic meaning,
not just file name.

```
agent42_memory(action="store", section="<Category>", content="<what to remember>")
```

### When to log

After completing a significant task or resolving a non-obvious problem, call
`agent42_memory` with action `log` to record the event in the project timeline.

```
agent42_memory(action="log", event_type="task_completed", content="<summary>")
```

---

## Testing Standards

Run tests before and after any change to confirm a green baseline:

```bash
python -m pytest tests/ -x -q              # Quick: stop on first failure
python -m pytest tests/ -v                  # Verbose: see all test names
python -m pytest tests/test_foo.py -v       # Single file
python -m pytest tests/ -k "test_name"      # Filter by name
```

**Test writing conventions:**
- Every new module needs a corresponding `tests/test_*.py` file
- Use `pytest-asyncio` for async tests (`asyncio_mode = "auto"` in pyproject.toml)
- Use `tmp_path` fixture for filesystem tests — never hardcode `/tmp` paths
- Use class-based organization: `class TestClassName` with descriptive method names
- Mock external services (APIs, databases) — never hit real services in tests
- Name tests: `test_<function>_<scenario>_<expected>`

---

## Common Pitfalls

| # | Area | Pitfall | Correct Pattern |
|---|------|---------|-----------------|
| 1 | Async | Blocking I/O in async functions blocks the entire event loop | Use `aiofiles` for file I/O, `httpx.AsyncClient` for HTTP, `asyncio`-native queue ops |
| 2 | Config | Mutable global config modified at runtime causes race conditions | Use frozen dataclasses for config — `@dataclass(frozen=True)`; load once at import time |
| 3 | Tests | Hardcoding `/tmp` paths makes tests fail on Windows | Use pytest `tmp_path` fixture — cross-platform, auto-cleaned |
| 4 | Tests | Running real external services in tests makes CI flaky | Mock all external calls: `mock.patch("subprocess.run")`, `mock.patch("urllib.request.urlopen")` |
| 5 | Deploy | Local changes block `git checkout main` during deploy | Always `git stash` or commit WIP before deploying; check `git status` first |
| 6 | Security | Plaintext secrets in env vars logged at DEBUG level | Never log API keys, passwords, or tokens — even at DEBUG; use `***` masking |
| 7 | Security | Path traversal via `../` in user-supplied file paths | Validate all file paths with `os.path.abspath()` and check they're inside allowed root |
| 8 | Windows | `python3` command not found on Windows | Use `python` on Windows; detect with `sys.platform == 'win32'` |
| 9 | Windows | CRLF line endings in bash scripts cause `$'\\r': command not found` | Set `.gitattributes` with `*.sh text eol=lf`; strip CRLF with `sed -i 's/\\r$//'` before running |
| 10 | Memory | Agent claims to remember things not in context | Use `agent42_memory(action="search", ...)` before answering; only reference actual retrieved content |
| 11 | Memory | Storing memories without semantic search defeats the purpose | Always use `action="store"` with a descriptive `section` so memories are retrievable by topic |
| 12 | Imports | Circular imports cause `ImportError` at startup | Move shared utilities to a separate module; avoid importing from `__init__.py` that imports from submodules |
| 13 | Errors | Bare `except:` swallows all exceptions including `KeyboardInterrupt` | Use `except Exception:` minimum; prefer specific exception types; always log the error |
| 14 | CLI | Script assumes it's run from project root but cwd varies | Use `os.path.dirname(os.path.abspath(__file__))` to get script's own directory |
| 15 | Git | Force-pushing to main/master destroys teammates' history | Never `git push --force` to shared branches; use `--force-with-lease` if absolutely necessary |
| 16 | Deps | Installing dependencies globally breaks other projects | Always use a virtualenv (`.venv/`); activate before installing: `source .venv/bin/activate` |
| 17 | Perf | Synchronous subprocess calls in hot paths add latency | Use `asyncio.create_subprocess_exec` for async subprocess; or run in thread pool |
| 18 | jcodemunch | Reading entire files costs tokens when only a function is needed | Use `get_symbol("ClassName.method_name")` instead of reading the whole file |
| 19 | jcodemunch | Index goes stale after adding new files or major refactors | Re-index with `index_folder(incremental=true)` after structural changes |
| 20 | Setup | `bash setup.sh` run from wrong directory fails silently | `setup.sh` uses `PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"` — always run from repo root |

---

## Project

**{project_name}**{active_workstream_line}

**jcodemunch repo:** `{jcodemunch_repo}`
"""


def generate_full_claude_md(project_dir: str) -> None:
    """Generate or merge a full CLAUDE.md template with Agent42 conventions.

    If CLAUDE.md does not exist, creates it from template.
    If CLAUDE.md exists, merges Agent42 sections using marker boundaries.
    Prints a summary of what changed.

    Args:
        project_dir: Absolute path to the project root.
    """
    import difflib

    ctx = _detect_project_context(project_dir)
    active_ws_line = ""
    if ctx["active_workstream"]:
        active_ws_line = f"\n**Active workstream:** {ctx['active_workstream']}"

    template_content = _FULL_CLAUDE_MD_TEMPLATE.format(
        project_name=ctx["project_name"],
        jcodemunch_repo=ctx["jcodemunch_repo"],
        active_workstream_line=active_ws_line,
        venv_python=ctx["venv_python"],
    )

    # Wrap in markers for merge
    managed_block = f"{_CLAUDE_MD_BEGIN}\n{template_content}\n{_CLAUDE_MD_END}\n"

    claude_md_path = os.path.join(project_dir, "CLAUDE.md")

    if os.path.isfile(claude_md_path):
        with open(claude_md_path, encoding="utf-8") as f:
            original = f.read()
    else:
        original = ""

    if _CLAUDE_MD_BEGIN in original and _CLAUDE_MD_END in original:
        # Replace content between markers
        before = original[: original.index(_CLAUDE_MD_BEGIN)]
        after = original[original.index(_CLAUDE_MD_END) + len(_CLAUDE_MD_END) :]
        if after.startswith("\n"):
            after = after[1:]
        new_content = before + managed_block + after
    elif original:
        # Append to existing file
        new_content = original.rstrip("\n") + "\n\n" + managed_block
    else:
        # Create from scratch
        new_content = f"# {ctx['project_name']} — CLAUDE.md\n\n" + managed_block

    # Diff summary
    if original:
        original_lines = original.splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)
        diff = list(difflib.unified_diff(original_lines, new_lines, n=0))
        if diff:
            added = sum(1 for line in diff if line.startswith("+") and not line.startswith("+++"))
            removed = sum(1 for line in diff if line.startswith("-") and not line.startswith("---"))
            print(f"  CLAUDE.md updated: +{added} lines, -{removed} lines")
        else:
            print("  CLAUDE.md already up to date - no changes")
    else:
        print(f"  CLAUDE.md created for {ctx['project_name']}")

    with open(claude_md_path, "w", encoding="utf-8") as f:
        f.write(new_content)


def generate_claude_md_section(project_dir: str) -> None:
    """Append or replace the Agent42 memory section in CLAUDE.md.

    If CLAUDE.md does not exist, creates it with a minimal header and the
    managed section. If it exists, finds the marker pair and replaces
    everything between them. If markers are not found, appends the section.

    Args:
        project_dir: Absolute path to the project root.
    """
    claude_md_path = os.path.join(project_dir, "CLAUDE.md")

    if os.path.isfile(claude_md_path):
        with open(claude_md_path, encoding="utf-8") as f:
            original = f.read()
    else:
        original = "# CLAUDE.md\n\n"

    if _CLAUDE_MD_BEGIN in original and _CLAUDE_MD_END in original:
        before = original[: original.index(_CLAUDE_MD_BEGIN)]
        after = original[original.index(_CLAUDE_MD_END) + len(_CLAUDE_MD_END) :]
        # Strip at most one leading newline from after to avoid accumulating blank lines
        if after.startswith("\n"):
            after = after[1:]
        new_content = before + CLAUDE_MD_TEMPLATE + after
    else:
        new_content = original.rstrip("\n") + "\n\n" + CLAUDE_MD_TEMPLATE

    with open(claude_md_path, "w", encoding="utf-8") as f:
        f.write(new_content)


# ---------------------------------------------------------------------------
# read_hook_metadata
# ---------------------------------------------------------------------------


def read_hook_metadata(hook_path: str) -> list:
    """Read hook_event/hook_matcher/hook_timeout frontmatter from a hook file.

    Parses leading comment lines (lines starting with '#') before the first
    non-comment, non-blank line. Returns a list of registration dicts — one
    per ``# hook_event:`` declaration.

    Most hooks return 1 item. jcodemunch-reindex.py returns 2 (PostToolUse + Stop).

    Returns:
        List of dicts with keys: event (str), matcher (str|None), timeout (int).
        Empty list if no hook_event declarations are found.
    """
    events = []
    matcher = None
    timeout = 30  # default

    with open(hook_path) as f:
        for line in f:
            stripped = line.strip()
            # Stop at first line that isn't a comment (but allow blank lines)
            if stripped == "":
                continue
            if not stripped.startswith("#"):
                break
            if stripped.startswith("# hook_event:"):
                events.append(stripped.split(":", 1)[1].strip())
            elif stripped.startswith("# hook_matcher:"):
                raw = stripped.split(":", 1)[1].strip()
                matcher = raw if raw else None
            elif stripped.startswith("# hook_timeout:"):
                try:
                    timeout = int(stripped.split(":", 1)[1].strip())
                except ValueError:
                    pass

    return [{"event": ev, "matcher": matcher, "timeout": timeout} for ev in events]


# ---------------------------------------------------------------------------
# generate_mcp_config
# ---------------------------------------------------------------------------


def generate_mcp_config(project_dir: str, ssh_alias: str | None = None) -> None:
    """Generate or merge .mcp.json in project_dir.

    Merge strategy:
    - Load existing .mcp.json if present and valid JSON; otherwise start fresh.
    - For each of the 6 servers, add if missing.
    - For agent42 specifically: replace if the command path no longer exists on disk.
    - For all other servers: never overwrite an existing entry.
    - agent42-remote is only added when ssh_alias is non-empty.

    Args:
        project_dir: Absolute path to the project root.
        ssh_alias:   SSH config alias for the remote node (optional).
    """
    mcp_path = os.path.join(project_dir, ".mcp.json")
    venv_python = _venv_python(project_dir)

    # Load existing config or start fresh
    config = {"mcpServers": {}}
    if os.path.isfile(mcp_path):
        try:
            with open(mcp_path) as f:
                loaded = json.load(f)
            if isinstance(loaded, dict) and "mcpServers" in loaded:
                config = loaded
        except (json.JSONDecodeError, OSError):
            pass  # Corrupt file — start fresh

    servers = config.setdefault("mcpServers", {})

    # -- agent42 (replace if command path is stale) -------------------------
    if "agent42" in servers:
        existing_cmd = servers["agent42"].get("command", "")
        if not os.path.isfile(existing_cmd):
            # Stale path (e.g., from another machine) — replace it
            servers["agent42"] = _make_agent42_entry(project_dir, venv_python)
        # else: valid path exists — skip (never overwrite)
    else:
        servers["agent42"] = _make_agent42_entry(project_dir, venv_python)

    # -- agent42-remote (only when ssh_alias is provided) ------------------
    if ssh_alias:
        if "agent42-remote" not in servers:
            servers["agent42-remote"] = _make_agent42_remote_entry(ssh_alias)

    # -- Static servers (never overwrite) -----------------------------------
    for name, entry in _STATIC_SERVERS.items():
        if name not in servers:
            servers[name] = entry

    os.makedirs(project_dir, exist_ok=True)
    with open(mcp_path, "w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")


# ---------------------------------------------------------------------------
# register_hooks
# ---------------------------------------------------------------------------


def register_hooks(project_dir: str) -> None:
    """Read all .py hook files and merge their registrations into settings.json.

    Reads every .py file in project_dir/.claude/hooks/, calls read_hook_metadata()
    on each, then merges into project_dir/.claude/settings.json.

    Merge strategy:
    - Preserve the 'permissions' key (never touch it).
    - Group hook registrations by (event, matcher) tuple.
    - Idempotent: if a command containing the script filename already exists in
      a registration block, skip it.
    - Writes result with 2-space indentation and a trailing newline.

    Args:
        project_dir: Absolute path to the project root.
    """
    hooks_dir = os.path.join(project_dir, ".claude", "hooks")
    settings_path = os.path.join(project_dir, ".claude", "settings.json")

    # Load existing settings or start fresh
    config = {}
    if os.path.isfile(settings_path):
        try:
            with open(settings_path) as f:
                config = json.load(f)
        except (json.JSONDecodeError, OSError):
            config = {}

    existing_hooks = config.get("hooks", {})

    if not os.path.isdir(hooks_dir):
        return  # Nothing to register

    # Collect all hook scripts and their metadata
    hook_files = sorted(
        f
        for f in os.listdir(hooks_dir)
        if f.endswith(".py") and os.path.isfile(os.path.join(hooks_dir, f))
    )

    # For each hook file with frontmatter, accumulate (event, matcher) -> [commands]
    # Structure: {event: {matcher: [command_entries]}}
    pending: dict = {}

    for filename in hook_files:
        hook_path = os.path.join(hooks_dir, filename)
        try:
            registrations = read_hook_metadata(hook_path)
        except (OSError, UnicodeDecodeError):
            continue

        for reg in registrations:
            event = reg["event"]
            matcher = reg["matcher"]
            timeout = reg["timeout"]

            # Build the command string (Linux forward-slash convention)
            hook_rel = f".claude/hooks/{filename}"
            command_str = f"cd {project_dir} && python {hook_rel}"

            pending.setdefault(event, {}).setdefault(matcher, []).append(
                {"type": "command", "command": command_str, "timeout": timeout}
            )

    # Merge pending into existing_hooks
    for event, matcher_map in pending.items():
        event_list = existing_hooks.setdefault(event, [])

        for matcher, new_entries in matcher_map.items():
            # Find an existing registration block that matches (event, matcher)
            target_block = None
            for block in event_list:
                block_matcher = block.get("matcher")
                if block_matcher == matcher:
                    target_block = block
                    break

            if target_block is None:
                # Create a new registration block
                target_block = {"hooks": []}
                if matcher is not None:
                    target_block["matcher"] = matcher
                event_list.append(target_block)

            existing_cmds = target_block.setdefault("hooks", [])

            for entry in new_entries:
                # Idempotency: skip if script filename already in any command
                script_name = entry["command"].split("/")[-1]
                already_registered = any(
                    script_name in existing["command"] for existing in existing_cmds
                )
                if not already_registered:
                    existing_cmds.append(entry)

    config["hooks"] = existing_hooks

    # Ensure settings directory exists
    os.makedirs(os.path.dirname(settings_path), exist_ok=True)

    with open(settings_path, "w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")


# ---------------------------------------------------------------------------
# check_health
# ---------------------------------------------------------------------------


def check_health(project_dir: str) -> list:
    """Run 5 health probes and return results.

    Probes (in order):
    1. MCP Server — runs mcp_server.py --health, expects exit 0
    2. jcodemunch — runs uvx jcodemunch-mcp --help, expects exit 0
    3. Qdrant — HTTP GET http://localhost:6333/healthz, expects HTTP 200
    4. Redis — runs redis-cli ping, expects stdout to contain PONG
    5. Claude Code CLI — runs claude --version, expects exit 0

    Each probe is wrapped in try/except. Any exception = unhealthy.

    Args:
        project_dir: Absolute path to the project root.

    Returns:
        List of dicts with keys: name, healthy, detail, fix, level.
        level is 'error' (red) or 'warn' (yellow).
    """
    venv_python = _venv_python(project_dir)
    mcp_server_path = os.path.join(project_dir, "mcp_server.py")
    results = []

    # -- 1. MCP Server -------------------------------------------------------
    try:
        proc = subprocess.run(
            [venv_python, mcp_server_path, "--health"],
            capture_output=True,
            timeout=10,
        )
        if proc.returncode == 0:
            results.append(
                {
                    "name": "MCP Server",
                    "healthy": True,
                    "detail": "healthy",
                    "fix": "",
                    "level": "error",
                }
            )
        else:
            stderr_text = proc.stderr.decode(errors="replace").strip()
            results.append(
                {
                    "name": "MCP Server",
                    "healthy": False,
                    "detail": stderr_text or f"exited {proc.returncode}",
                    "fix": "Check .venv and mcp_server.py imports",
                    "level": "error",
                }
            )
    except Exception as e:
        results.append(
            {
                "name": "MCP Server",
                "healthy": False,
                "detail": str(e),
                "fix": "Check .venv and mcp_server.py imports",
                "level": "error",
            }
        )

    # -- 2. jcodemunch -------------------------------------------------------
    try:
        proc = subprocess.run(
            ["uvx", "jcodemunch-mcp", "--help"],
            capture_output=True,
            timeout=15,
        )
        if proc.returncode == 0:
            results.append(
                {
                    "name": "jcodemunch",
                    "healthy": True,
                    "detail": "healthy",
                    "fix": "",
                    "level": "error",
                }
            )
        else:
            stderr_text = proc.stderr.decode(errors="replace").strip()
            results.append(
                {
                    "name": "jcodemunch",
                    "healthy": False,
                    "detail": stderr_text or f"exited {proc.returncode}",
                    "fix": "pip install uv && uvx jcodemunch-mcp",
                    "level": "error",
                }
            )
    except Exception as e:
        results.append(
            {
                "name": "jcodemunch",
                "healthy": False,
                "detail": str(e),
                "fix": "pip install uv && uvx jcodemunch-mcp",
                "level": "error",
            }
        )

    # -- 3. Qdrant -----------------------------------------------------------
    try:
        response = urllib.request.urlopen("http://localhost:6333/healthz", timeout=5)
        if response.status == 200:
            results.append(
                {"name": "Qdrant", "healthy": True, "detail": "healthy", "fix": "", "level": "warn"}
            )
        else:
            results.append(
                {
                    "name": "Qdrant",
                    "healthy": False,
                    "detail": f"HTTP {response.status}",
                    "fix": "Start Qdrant: qdrant or docker run qdrant/qdrant",
                    "level": "warn",
                }
            )
    except Exception as e:
        results.append(
            {
                "name": "Qdrant",
                "healthy": False,
                "detail": str(e),
                "fix": "Start Qdrant: qdrant or docker run qdrant/qdrant",
                "level": "warn",
            }
        )

    # -- 4. Redis ------------------------------------------------------------
    try:
        proc = subprocess.run(
            ["redis-cli", "ping"],
            capture_output=True,
            timeout=5,
        )
        stdout_text = proc.stdout.decode(errors="replace").strip()
        if "PONG" in stdout_text:
            results.append(
                {"name": "Redis", "healthy": True, "detail": "healthy", "fix": "", "level": "warn"}
            )
        else:
            results.append(
                {
                    "name": "Redis",
                    "healthy": False,
                    "detail": stdout_text or "no PONG response",
                    "fix": "Start Redis: sudo systemctl start redis",
                    "level": "warn",
                }
            )
    except Exception as e:
        results.append(
            {
                "name": "Redis",
                "healthy": False,
                "detail": str(e),
                "fix": "Start Redis: sudo systemctl start redis",
                "level": "warn",
            }
        )

    # -- 5. Claude Code CLI --------------------------------------------------
    try:
        proc = subprocess.run(
            ["claude", "--version"],
            capture_output=True,
            timeout=5,
        )
        if proc.returncode == 0:
            results.append(
                {
                    "name": "Claude Code CLI",
                    "healthy": True,
                    "detail": "healthy",
                    "fix": "",
                    "level": "error",
                }
            )
        else:
            stderr_text = proc.stderr.decode(errors="replace").strip()
            results.append(
                {
                    "name": "Claude Code CLI",
                    "healthy": False,
                    "detail": stderr_text or f"exited {proc.returncode}",
                    "fix": "Install Claude Code: https://docs.anthropic.com/claude-code",
                    "level": "error",
                }
            )
    except Exception as e:
        results.append(
            {
                "name": "Claude Code CLI",
                "healthy": False,
                "detail": str(e),
                "fix": "Install Claude Code: https://docs.anthropic.com/claude-code",
                "level": "error",
            }
        )

    return results


# ---------------------------------------------------------------------------
# print_health_report
# ---------------------------------------------------------------------------


def print_health_report(results: list) -> None:
    """Print colored terminal health report using ANSI escape codes.

    Args:
        results: List of result dicts from check_health().
    """
    GREEN = "\033[0;32m"
    RED = "\033[0;31m"
    YELLOW = "\033[1;33m"
    RESET = "\033[0m"

    for r in results:
        if r["healthy"]:
            print(f"{GREEN}[✓]{RESET} {r['name']}: healthy")
        else:
            color = RED if r["level"] == "error" else YELLOW
            print(f"{color}[✗]{RESET} {r['name']}: {r['detail']} → Fix: {r['fix']}")

    healthy_count = sum(1 for r in results if r["healthy"])
    total = len(results)
    print(f"\nSetup complete. {healthy_count}/{total} services healthy.")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""

    if cmd == "mcp-config":
        if len(sys.argv) < 3:
            print(f"Usage: {sys.argv[0]} mcp-config <project_dir> [<ssh_alias>]")
            sys.exit(1)
        project_dir = sys.argv[2]
        ssh_alias = sys.argv[3] if len(sys.argv) > 3 else None
        generate_mcp_config(project_dir, ssh_alias)

    elif cmd == "register-hooks":
        if len(sys.argv) < 3:
            print(f"Usage: {sys.argv[0]} register-hooks <project_dir>")
            sys.exit(1)
        project_dir = sys.argv[2]
        register_hooks(project_dir)

    elif cmd == "health":
        if len(sys.argv) < 3:
            print(f"Usage: {sys.argv[0]} health <project_dir>")
            sys.exit(1)
        project_dir = sys.argv[2]
        results = check_health(project_dir)
        print_health_report(results)
        healthy_count = sum(1 for r in results if r["healthy"])
        sys.exit(0 if healthy_count >= 3 else 1)

    elif cmd == "claude-md":
        if len(sys.argv) < 3:
            print(f"Usage: {sys.argv[0]} claude-md <project_dir>")
            sys.exit(1)
        project_dir = sys.argv[2]
        generate_claude_md_section(project_dir)

    elif cmd == "generate-claude-md":
        if len(sys.argv) < 3:
            print(f"Usage: {sys.argv[0]} generate-claude-md <project_dir>")
            sys.exit(1)
        project_dir = sys.argv[2]
        generate_full_claude_md(project_dir)

    else:
        print(
            f"Usage: {sys.argv[0]} {{mcp-config|register-hooks|health|claude-md|generate-claude-md}} <project_dir> [options]"
        )
        sys.exit(1)
