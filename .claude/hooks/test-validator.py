#!/usr/bin/env python3
"""Smart test validator hook — runs targeted tests on changed files only.

Triggered on Stop event. Instead of running the full 1797-test suite every time,
it:
1. Extracts which Python files were modified during the session (from tool_uses)
2. Maps source files to their corresponding test files
3. Runs only affected tests (or skips if no testable source changed)
4. Checks test coverage only for newly created source files

Ruff lint/format is NOT run here — format-on-write.py handles that on every
PostToolUse Write/Edit, so repeating it on Stop is redundant.

Typical Stop time: ~2-5s (targeted tests) vs ~60-120s (full suite).

Hook protocol:
- Receives JSON on stdin with hook_event_name, project_dir, tool_uses
- Output to stderr is shown to Claude as feedback
- Exit code 0 = allow (advisory — warns but doesn't block)
"""

import json
import os
import re
import subprocess
import sys

# Directories that should have test coverage
COVERED_DIRS = {"core", "agents", "tools", "providers", "memory", "dashboard"}

# Files that affect everything — if these change, run full suite
GLOBAL_IMPACT_FILES = {
    "conftest.py",
    "tests/conftest.py",
    "core/config.py",
    "core/__init__.py",
    "agents/__init__.py",
    "tools/__init__.py",
    "tools/base.py",
    "providers/__init__.py",
    "agent42.py",
}

# Max test files to run in targeted mode before falling back to full suite
MAX_TARGETED_TEST_FILES = 12


def normalize_path(path, project_dir):
    """Normalize a file path to a project-relative POSIX-style path."""
    # Handle Git Bash /c/... paths on Windows
    if sys.platform == "win32" and re.match(r"^/([a-zA-Z])/", path):
        path = path[1].upper() + ":" + path[2:]
    path = os.path.normpath(path)
    project_dir = os.path.normpath(project_dir)
    if path.startswith(project_dir):
        path = path[len(project_dir):].lstrip(os.sep)
    return path.replace("\\", "/")


def extract_modified_files(event, project_dir):
    """Extract Python files modified during the session from tool_uses."""
    modified = set()
    created = set()

    for tool_use in event.get("tool_uses", []):
        tool_name = tool_use.get("tool_name", "")
        if tool_name not in ("Write", "Edit", "NotebookEdit"):
            continue

        tool_input = tool_use.get("tool_input", {})
        file_path = tool_input.get("file_path", "") or tool_input.get("path", "")
        if not file_path or not file_path.endswith(".py"):
            continue

        rel = normalize_path(file_path, project_dir)
        modified.add(rel)

        # Write = potentially new file (created)
        if tool_name == "Write":
            created.add(rel)

    return modified, created


def map_source_to_tests(source_files, project_dir):
    """Map source files to their corresponding test files.

    Strategy:
    - core/foo.py → tests/test_foo.py
    - agents/bar.py → tests/test_bar.py
    - tools/baz.py → tests/test_baz.py (or tests/test_tools.py)
    - tests/test_x.py → tests/test_x.py (already a test file)
    """
    test_files = set()
    tests_dir = os.path.join(project_dir, "tests")

    for src in source_files:
        parts = src.replace("\\", "/").split("/")

        # Already a test file
        if src.startswith("tests/"):
            full = os.path.join(project_dir, src)
            if os.path.isfile(full):
                test_files.add(src)
            continue

        # Skip non-covered directories
        if not parts or parts[0] not in COVERED_DIRS:
            continue

        # Skip __init__.py and private modules
        basename = parts[-1]
        if basename.startswith("__"):
            continue

        module_name = basename[:-3]  # strip .py

        # Primary: tests/test_{module_name}.py
        candidate = os.path.join(tests_dir, f"test_{module_name}.py")
        if os.path.isfile(candidate):
            test_files.add(f"tests/test_{module_name}.py")
            continue

        # Fallback: tests/test_{directory}.py (grouped test file)
        dir_name = parts[0]
        grouped = os.path.join(tests_dir, f"test_{dir_name}.py")
        if os.path.isfile(grouped):
            test_files.add(f"tests/test_{dir_name}.py")
            continue

        # No test file found — will be caught by coverage check

    return test_files


def check_global_impact(modified_files):
    """Check if any modified file has global impact (warrants full suite)."""
    for f in modified_files:
        if f in GLOBAL_IMPACT_FILES:
            return f
    return None


def check_test_coverage_for_new_files(created_files, project_dir):
    """Check if newly created source modules have test files."""
    missing = []
    tests_dir = os.path.join(project_dir, "tests")

    for src in created_files:
        parts = src.replace("\\", "/").split("/")
        if not parts or parts[0] not in COVERED_DIRS:
            continue
        if parts[-1].startswith("_"):
            continue
        if src.startswith("tests/"):
            continue

        module_name = parts[-1][:-3]
        test_file = os.path.join(tests_dir, f"test_{module_name}.py")
        grouped = os.path.join(tests_dir, f"test_{parts[0]}.py")

        if not os.path.exists(test_file) and not os.path.exists(grouped):
            missing.append(src)

    return missing


def run_tests(project_dir, test_files=None):
    """Run pytest on specific test files, or full suite if None."""
    cmd = [sys.executable, "-m", "pytest"]

    if test_files:
        cmd.extend(sorted(test_files))
    else:
        cmd.append("tests/")

    cmd.extend(["-x", "-q", "--tb=short"])

    timeout = 30 if test_files else 90

    try:
        result = subprocess.run(
            cmd,
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        label = "targeted" if test_files else "full"
        return 1, "", f"Test suite timed out ({timeout}s limit, {label} mode)"
    except FileNotFoundError:
        return -1, "", "pytest not found"


def main():
    try:
        event = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    if event.get("hook_event_name") != "Stop":
        sys.exit(0)

    project_dir = event.get("project_dir", ".")
    if sys.platform == "win32" and re.match(r"^/([a-zA-Z])/", project_dir):
        project_dir = project_dir[1].upper() + ":" + project_dir[2:]
    project_dir = os.path.normpath(project_dir)

    # 1. Extract what changed
    modified, created = extract_modified_files(event, project_dir)

    if not modified:
        print("[test-validator] No Python files modified — skipping tests.", file=sys.stderr)
        sys.exit(0)

    print(
        f"[test-validator] {len(modified)} Python file(s) modified this session.",
        file=sys.stderr,
    )

    # 2. Check for global-impact files
    global_trigger = check_global_impact(modified)
    if global_trigger:
        print(
            f"[test-validator] Global-impact file changed ({global_trigger}) — running full suite.",
            file=sys.stderr,
        )
        return_code, stdout, stderr = run_tests(project_dir)
    else:
        # 3. Map to test files
        test_files = map_source_to_tests(modified, project_dir)

        if not test_files:
            print(
                "[test-validator] No corresponding test files found — skipping.",
                file=sys.stderr,
            )
            # Still check coverage for new files
            missing = check_test_coverage_for_new_files(created, project_dir)
            if missing:
                print(
                    f"[test-validator] New file(s) without tests: {', '.join(missing)}",
                    file=sys.stderr,
                )
            sys.exit(0)

        if len(test_files) > MAX_TARGETED_TEST_FILES:
            print(
                f"[test-validator] {len(test_files)} test files affected — running full suite.",
                file=sys.stderr,
            )
            return_code, stdout, stderr = run_tests(project_dir)
        else:
            print(
                f"[test-validator] Running {len(test_files)} targeted test file(s): "
                f"{', '.join(sorted(test_files))}",
                file=sys.stderr,
            )
            return_code, stdout, stderr = run_tests(project_dir, test_files)

    # 4. Report results
    if return_code == 0:
        lines = stdout.strip().split("\n")
        summary = lines[-1] if lines else "All tests passed"
        print(f"[test-validator] PASSED: {summary}", file=sys.stderr)
    elif return_code == -1:
        print(f"[test-validator] SKIP: {stderr}", file=sys.stderr)
    else:
        print("[test-validator] FAILED:", file=sys.stderr)
        output_lines = (stdout + stderr).strip().split("\n")
        for line in output_lines[-15:]:
            print(f"  {line}", file=sys.stderr)

    # 5. Coverage check for newly created files only
    if created:
        missing = check_test_coverage_for_new_files(created, project_dir)
        if missing:
            print(
                f"\n[test-validator] New module(s) without test coverage:",
                file=sys.stderr,
            )
            for m in missing:
                print(f"  - {m}", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
