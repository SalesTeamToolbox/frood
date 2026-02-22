#!/usr/bin/env python3
"""Test validator hook — validates tests pass at session end.

Triggered on Stop event. Runs the test suite and checks that new modules
have corresponding test files.

Hook protocol:
- Receives JSON on stdin with hook_event_name, project_dir
- Output to stderr is shown to Claude as feedback
- Exit code 0 = allow (advisory — warns but doesn't block)
"""

import json
import os
import subprocess
import sys


# Directories that should have test coverage
COVERED_DIRS = ["core", "agents", "tools", "providers"]


def check_test_coverage(project_dir):
    """Check if source modules have corresponding test files."""
    missing_tests = []

    for dir_name in COVERED_DIRS:
        source_dir = os.path.join(project_dir, dir_name)
        tests_dir = os.path.join(project_dir, "tests")

        if not os.path.isdir(source_dir):
            continue

        for fname in os.listdir(source_dir):
            if not fname.endswith(".py"):
                continue
            if fname.startswith("_"):
                continue

            module_name = fname[:-3]  # Remove .py
            test_file = os.path.join(tests_dir, f"test_{module_name}.py")

            # Check for test file with exact name or partial match
            if not os.path.exists(test_file):
                # Also check for grouped test files (e.g., test_tools.py covers tools/*)
                grouped = os.path.join(tests_dir, f"test_{dir_name}.py")
                if not os.path.exists(grouped):
                    missing_tests.append(f"{dir_name}/{fname}")

    return missing_tests


def run_tests(project_dir):
    """Run the test suite and return results."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/", "-x", "-q", "--tb=short"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=120,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return 1, "", "Test suite timed out (120s limit)"
    except FileNotFoundError:
        return -1, "", "pytest not found — install with: pip install pytest pytest-asyncio"


def main():
    try:
        event = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    project_dir = event.get("project_dir", ".")

    # Only run on Stop events
    if event.get("hook_event_name") != "Stop":
        sys.exit(0)

    print("\n[test-validator] Running test suite...", file=sys.stderr)

    # Run tests
    return_code, stdout, stderr = run_tests(project_dir)

    if return_code == 0:
        # Extract summary line from pytest output
        lines = stdout.strip().split("\n")
        summary = lines[-1] if lines else "All tests passed"
        print(f"[test-validator] PASSED: {summary}", file=sys.stderr)
    elif return_code == -1:
        print(f"[test-validator] SKIP: {stderr}", file=sys.stderr)
    else:
        print("[test-validator] FAILED: Some tests did not pass.", file=sys.stderr)
        # Show last 20 lines of output for context
        output_lines = (stdout + stderr).strip().split("\n")
        for line in output_lines[-20:]:
            print(f"  {line}", file=sys.stderr)

    # Check test coverage for new modules
    missing = check_test_coverage(project_dir)
    if missing:
        print(
            f"\n[test-validator] Modules without dedicated test files ({len(missing)}):",
            file=sys.stderr,
        )
        for m in missing[:10]:  # Show first 10
            print(f"  - {m}", file=sys.stderr)
        if len(missing) > 10:
            print(f"  ... and {len(missing) - 10} more", file=sys.stderr)

    # Always allow (advisory only)
    sys.exit(0)


if __name__ == "__main__":
    main()
