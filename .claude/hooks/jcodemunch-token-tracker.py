#!/usr/bin/env python3
"""Track token savings from jcodemunch usage vs full file reads.

Triggered on PostToolUse for all tool calls. Filters to jcodemunch MCP
tools only. Estimates tokens saved by comparing jcodemunch response size
against what a full file read would have cost.

Writes running stats to .claude/.jcodemunch-stats.json for VS Code
status bar pickup.

Hook protocol:
- Receives JSON on stdin with hook_event_name, tool_name, tool_input, tool_output
- Output to stderr is shown to Claude as feedback
- Exit code 0 = allow (advisory, never blocks)
"""

import json
import os
import re
import sys
import time

STATS_FILENAME = ".jcodemunch-stats.json"
CHARS_PER_TOKEN = 4  # Standard approximation


def normalize_path(path):
    """Normalize Git Bash /c/... paths on Windows."""
    if sys.platform == "win32" and re.match(r"^/([a-zA-Z])/", path):
        path = path[1].upper() + ":" + path[2:]
    return os.path.normpath(path)


def get_file_size(project_dir, rel_path):
    """Get file size in characters. Returns 0 if file not found."""
    full_path = os.path.join(project_dir, rel_path.replace("/", os.sep))
    try:
        with open(full_path, "r", encoding="utf-8", errors="replace") as f:
            return len(f.read())
    except (OSError, UnicodeDecodeError):
        return 0


def estimate_tokens(char_count):
    """Estimate token count from character count."""
    return max(1, char_count // CHARS_PER_TOKEN)


def load_stats(stats_path):
    """Load existing session stats or create new ones."""
    try:
        with open(stats_path, "r") as f:
            stats = json.load(f)
            # Reset if older than 6 hours (new session)
            if time.time() - stats.get("session_start", 0) > 21600:
                return new_stats()
            return stats
    except (OSError, json.JSONDecodeError):
        return new_stats()


def new_stats():
    return {
        "session_start": time.time(),
        "last_updated": time.time(),
        "calls": 0,
        "tokens_used": 0,
        "tokens_avoided": 0,
        "tokens_saved": 0,
        "files_targeted": 0,
        "tool_breakdown": {},
    }


def save_stats(stats_path, stats):
    stats["last_updated"] = time.time()
    try:
        os.makedirs(os.path.dirname(stats_path), exist_ok=True)
        with open(stats_path, "w") as f:
            json.dump(stats, f, indent=2)
    except OSError:
        pass


def format_tokens(count):
    """Format token count for display."""
    if count >= 1000:
        return f"{count / 1000:.1f}K"
    return str(count)


def estimate_savings(tool_name, tool_input, tool_output, project_dir):
    """Estimate tokens used vs tokens that would have been used with Read.

    Returns (tokens_used, tokens_avoided) where:
    - tokens_used: tokens in the jcodemunch response
    - tokens_avoided: tokens that would have been consumed reading full files
    """
    output_str = str(tool_output) if tool_output else ""
    tokens_used = estimate_tokens(len(output_str))

    short_name = tool_name.replace("mcp__jcodemunch__", "")

    if short_name in ("get_file_outline", "get_symbol", "get_symbols"):
        # These target specific files — compare to full file read
        file_path = tool_input.get("file_path", "")
        if file_path:
            file_chars = get_file_size(project_dir, file_path)
            tokens_avoided = estimate_tokens(file_chars)
        else:
            # get_symbols uses symbol_ids which contain file paths
            symbol_ids = tool_input.get("symbol_ids", [])
            files_seen = set()
            total_chars = 0
            for sid in symbol_ids:
                # Symbol IDs typically contain the file path
                parts = sid.split("::")
                if parts:
                    fp = parts[0]
                    if fp not in files_seen:
                        files_seen.add(fp)
                        total_chars += get_file_size(project_dir, fp)
            tokens_avoided = estimate_tokens(total_chars) if total_chars else tokens_used * 3

    elif short_name == "search_symbols":
        # Search returns targeted results vs reading all matching files
        # Estimate: user would have read ~5 files to find what they needed
        tokens_avoided = tokens_used * 5

    elif short_name == "search_text":
        # Text search vs grep + reading matching files
        tokens_avoided = tokens_used * 4

    elif short_name == "get_file_tree":
        # Tree view vs reading directory + opening files to understand structure
        tokens_avoided = tokens_used * 3

    elif short_name == "get_repo_outline":
        # Repo overview vs exploring multiple directories
        tokens_avoided = tokens_used * 4

    else:
        # index_folder, index_repo, list_repos, invalidate_cache
        # These are maintenance — no direct savings comparison
        tokens_avoided = 0

    return tokens_used, tokens_avoided


def main():
    try:
        event = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    tool_name = event.get("tool_name", "")

    # Only process jcodemunch MCP tool calls
    if "jcodemunch" not in tool_name:
        sys.exit(0)

    tool_input = event.get("tool_input", {})
    tool_output = event.get("tool_output", {})

    project_dir = event.get("project_dir", ".")
    project_dir = normalize_path(project_dir)

    # Calculate savings
    tokens_used, tokens_avoided = estimate_savings(
        tool_name, tool_input, tool_output, project_dir
    )
    tokens_saved = max(0, tokens_avoided - tokens_used)

    # Load and update stats
    claude_dir = os.path.join(project_dir, ".claude")
    stats_path = os.path.join(claude_dir, STATS_FILENAME)
    stats = load_stats(stats_path)

    short_name = tool_name.replace("mcp__jcodemunch__", "")
    stats["calls"] += 1
    stats["tokens_used"] += tokens_used
    stats["tokens_avoided"] += tokens_avoided
    stats["tokens_saved"] += tokens_saved

    if short_name in ("get_file_outline", "get_symbol", "get_symbols"):
        stats["files_targeted"] += 1

    breakdown = stats.get("tool_breakdown", {})
    if short_name not in breakdown:
        breakdown[short_name] = {"calls": 0, "saved": 0}
    breakdown[short_name]["calls"] += 1
    breakdown[short_name]["saved"] += tokens_saved
    stats["tool_breakdown"] = breakdown

    save_stats(stats_path, stats)

    # Output to Claude Code terminal
    if tokens_saved > 0:
        print(
            f"[jcodemunch] {short_name}: ~{format_tokens(tokens_used)} tokens used, "
            f"~{format_tokens(tokens_saved)} saved | "
            f"Session total: ~{format_tokens(stats['tokens_saved'])} saved "
            f"across {stats['calls']} calls",
            file=sys.stderr,
        )

    sys.exit(0)


if __name__ == "__main__":
    main()
