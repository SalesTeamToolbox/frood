#!/usr/bin/env python3
"""Format-on-write hook — auto-formats Python files after every Write/Edit.

Triggered on PostToolUse for Write/Edit operations on .py files.
Runs `ruff format` and `ruff check --fix` immediately so lint/format
issues are caught and corrected before they accumulate into CI failures.

Hook protocol:
- Receives JSON on stdin with hook_event_name, tool_name, tool_input
- Output to stderr is shown to Claude as feedback
- Exit code 0 = allow (always allows; auto-fixes rather than blocking)
"""

import json
import os
import shutil
import subprocess
import sys


def find_ruff(project_dir: str) -> str | None:
    """Locate the ruff executable, preferring the project venv."""
    candidates = [
        os.path.join(project_dir, ".venv", "bin", "ruff"),
        os.path.join(project_dir, "venv", "bin", "ruff"),
        shutil.which("ruff"),
    ]
    for path in candidates:
        if path and os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


def run_ruff(ruff: str, args: list[str], cwd: str) -> tuple[int, str, str]:
    try:
        result = subprocess.run(
            [ruff, *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return 1, "", "ruff timed out"
    except OSError as e:
        return 1, "", str(e)


def main():
    try:
        event = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    tool_name = event.get("tool_name", "")
    if tool_name not in ("Write", "Edit"):
        sys.exit(0)

    tool_input = event.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    # Only process Python files
    if not file_path.endswith(".py"):
        sys.exit(0)

    if not os.path.isfile(file_path):
        sys.exit(0)

    project_dir = event.get("project_dir", os.path.dirname(file_path))

    ruff = find_ruff(project_dir)
    if not ruff:
        print("[format-on-write] ruff not found — skipping auto-format", file=sys.stderr)
        sys.exit(0)

    # Auto-format the file
    fmt_code, _, fmt_err = run_ruff(ruff, ["format", file_path], project_dir)
    if fmt_code != 0:
        print(f"[format-on-write] ruff format error: {fmt_err.strip()}", file=sys.stderr)

    # Auto-fix lint issues
    fix_code, fix_out, fix_err = run_ruff(
        ruff, ["check", "--fix", "--exit-zero", file_path], project_dir
    )

    # Report unfixable lint issues (ruff check without --fix to get remaining)
    lint_code, lint_out, _ = run_ruff(ruff, ["check", file_path], project_dir)
    if lint_code != 0 and lint_out.strip():
        rel = os.path.relpath(file_path, project_dir)
        print(f"[format-on-write] Lint issues in {rel}:", file=sys.stderr)
        for line in lint_out.strip().splitlines()[:10]:
            print(f"  {line}", file=sys.stderr)
        print(
            "  Fix these before committing (`ruff check --fix .`)",
            file=sys.stderr,
        )
    else:
        rel = os.path.relpath(file_path, project_dir)
        print(f"[format-on-write] {rel} formatted and lint-clean", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
