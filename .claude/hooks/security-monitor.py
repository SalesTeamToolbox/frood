#!/usr/bin/env python3
"""Security monitor hook — flags security-sensitive changes for review.

Triggered on PostToolUse for Write/Edit operations. Checks if changes
affect security-critical files and scans for dangerous patterns.

Hook protocol:
- Receives JSON on stdin with hook_event_name, tool_name, tool_input, tool_output
- Output to stderr is shown to Claude as feedback
- Exit code 0 = allow (advisory warnings, never blocks)
"""

import json
import re
import sys

# Security-critical files — changes here warrant extra scrutiny
SECURITY_FILES = {
    "core/sandbox.py": "Filesystem boundary enforcement",
    "core/command_filter.py": "Shell command filtering",
    "core/approval_gate.py": "Human-in-the-loop approval",
    "dashboard/auth.py": "Authentication and authorization",
    "core/rate_limiter.py": "Rate limiting",
    "core/url_policy.py": "SSRF protection",
    "tools/shell.py": "Shell command execution",
    "core/config.py": "Security setting defaults",
    "core/device_auth.py": "Device authentication",
    ".env.example": "Credential patterns and defaults",
}

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
        "pattern": r'0\.0\.0\.0',
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


def check_security_file(file_path):
    """Check if the file is security-critical."""
    for sec_path, description in SECURITY_FILES.items():
        if file_path.endswith(sec_path) or sec_path in file_path:
            return description
    return None


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
                ctx in file_lower or ctx in content.lower()
                for ctx in check["context"]
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
    sec_desc = check_security_file(file_path)
    if sec_desc:
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
