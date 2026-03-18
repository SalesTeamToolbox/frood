#!/usr/bin/env python3
# hook_event: PostToolUse
# hook_matcher: Write|Edit
# hook_timeout: 30
"""Security monitor hook — flags security-sensitive changes for review.

Triggered on PostToolUse for Write/Edit operations. Checks if changes
affect security-critical files and scans for dangerous patterns.

Security file definitions are imported from security_config.py (shared
with the PreToolUse security-gate.py hook).

Hook protocol:
- Receives JSON on stdin with hook_event_name, tool_name, tool_input, tool_output
- Output to stderr is shown to Claude as feedback
- Exit code 0 = allow (advisory warnings, never blocks)
"""

import json
import os
import re
import sys

# Import shared security file registry
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from security_config import is_security_file

# Dangerous patterns to check for in file content
DANGEROUS_PATTERNS = [
    {
        "pattern": r"enabled\s*=\s*False",
        "context": ["sandbox", "filter", "security", "rate_limit"],
        "warning": "Security feature appears to be disabled (enabled=False)",
    },
    {
        "pattern": r"os\.system\s*\(",
        "context": [],
        "warning": "os.system() call detected — use sandboxed shell tool instead",
    },
    {
        "pattern": r"subprocess\.run\([^)]*shell\s*=\s*True",
        "context": [],
        "warning": "subprocess.run(shell=True) detected — use CommandFilter for validation",
    },
    {
        "pattern": r"0\.0\.0\.0",
        "context": ["host", "bind", "listen", "default"],
        "warning": "Binding to 0.0.0.0 — ensure nginx/firewall is configured",
    },
    {
        "pattern": r'(api_key|password|secret|token)\s*=\s*["\'][^"\']{8,}',
        "context": [],
        "warning": "Possible hardcoded credential detected",
    },
    {
        "pattern": r"CORS_ALLOWED_ORIGINS.*\*",
        "context": [],
        "warning": "Wildcard CORS origin — allows any domain to make API calls",
    },
    {
        "pattern": r"verify\s*=\s*False",
        "context": ["ssl", "tls", "https", "cert"],
        "warning": "SSL verification disabled — vulnerable to MITM attacks",
    },
    {
        "pattern": r"# noqa:\s*S",
        "context": [],
        "warning": "Security linting rule suppressed — verify this is intentional",
    },
    {
        "pattern": r"eval\s*\(",
        "context": [],
        "warning": "eval() call detected — potential code injection risk",
    },
    {
        "pattern": r"exec\s*\(",
        "context": [],
        "warning": "exec() call detected — potential code injection risk",
    },
    {
        "pattern": r"__import__\s*\(",
        "context": [],
        "warning": "__import__() call detected — potential code injection risk",
    },
    {
        "pattern": r"pickle\.loads?\s*\(",
        "context": [],
        "warning": "pickle deserialization detected — potential arbitrary code execution",
    },
]


def scan_content(content, file_path=""):
    """Scan content for dangerous patterns."""
    warnings = []
    file_lower = file_path.lower()

    for check in DANGEROUS_PATTERNS:
        matches = re.findall(check["pattern"], content, re.IGNORECASE)
        if not matches:
            continue

        # If context keywords specified, check if they appear in the file path or content
        if check["context"]:
            context_found = any(
                ctx in file_lower or ctx in content.lower() for ctx in check["context"]
            )
            if not context_found:
                continue

        warnings.append(check["warning"])

    return warnings


def main():
    try:
        event = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    tool_name = event.get("tool_name", "")
    tool_input = event.get("tool_input", {})

    # Only process Write/Edit operations
    if tool_name not in ("Write", "Edit", "write", "edit"):
        sys.exit(0)

    file_path = tool_input.get("file_path", "")
    if not file_path:
        sys.exit(0)

    warnings = []

    # Check if this is a security-critical file
    is_match, _, sec_desc = is_security_file(file_path)
    if is_match:
        warnings.append(f"SECURITY-CRITICAL FILE: {sec_desc}")

    # Scan the content for dangerous patterns
    content = tool_input.get("content", "")
    new_string = tool_input.get("new_string", "")
    scan_text = content or new_string or ""

    if scan_text:
        pattern_warnings = scan_content(scan_text, file_path)
        warnings.extend(pattern_warnings)

    # Output warnings
    if warnings:
        print("\n[security-monitor] Security review flags:", file=sys.stderr)
        print(f"  File: {file_path}", file=sys.stderr)
        for w in warnings:
            print(f"  WARNING: {w}", file=sys.stderr)
        print(
            "  Action: Review these changes carefully before committing.",
            file=sys.stderr,
        )

    sys.exit(0)


if __name__ == "__main__":
    main()
