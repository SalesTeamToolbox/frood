#!/usr/bin/env python3
"""Shared security file registry -- single source of truth.

This module defines the canonical list of security-sensitive files in the
Frood codebase.  Both the PreToolUse gate (security-gate.py) and the
PostToolUse monitor (security-monitor.py) import from here so there is
exactly one place to add, remove, or rename a protected path.

Dependency-free: stdlib only.
"""

# Security-critical files -- changes here warrant extra scrutiny.
# Keys are relative paths (or suffixes) matched against tool_input file_path.
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
    ".env": "Production secrets and credentials",
    "core/encryption.py": "Encryption key management",
}


def is_security_file(file_path: str) -> tuple:
    """Check whether *file_path* refers to a security-sensitive file.

    Returns
    -------
    tuple of (bool, str, str)
        (is_match, matched_registry_key, description)
        When there is no match the latter two elements are empty strings.
    """
    for sec_path, description in SECURITY_FILES.items():
        if file_path.endswith(sec_path) or sec_path in file_path:
            return (True, sec_path, description)
    return (False, "", "")
