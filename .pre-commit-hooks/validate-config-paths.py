#!/usr/bin/env python3
"""Validate config files for platform-correct paths (no Windows paths on Linux)."""

import json
import sys
from pathlib import Path


def validate_mcp_json(path: Path) -> list[str]:
    """Validate .mcp.json for Windows paths on Linux."""
    errors = []
    try:
        with open(path) as f:
            data = json.load(f)
    except Exception as e:
        return [f"Failed to parse {path}: {e}"]

    servers = data.get("mcpServers", {})
    for name, config in servers.items():
        # Check command
        cmd = config.get("command", "")
        if isinstance(cmd, str) and ("\\" in cmd or "C:" in cmd or "c:" in cmd):
            errors.append(f"{path}: mcpServers.{name}.command has Windows path: {cmd}")
        elif isinstance(cmd, list):
            for part in cmd:
                if isinstance(part, str) and ("\\" in part or "C:" in part or "c:" in part):
                    errors.append(
                        f"{path}: mcpServers.{name}.command part has Windows path: {part}"
                    )

        # Check args
        args = config.get("args", [])
        if isinstance(args, list):
            for arg in args:
                if isinstance(arg, str) and ("\\" in arg or "C:" in arg or "c:" in arg):
                    errors.append(f"{path}: mcpServers.{name}.args has Windows path: {arg}")

        # Check env
        env = config.get("env", {})
        for key, val in env.items():
            if isinstance(val, str) and ("\\" in val or "C:" in val or "c:" in val):
                errors.append(f"{path}: mcpServers.{name}.env.{key} has Windows path: {val}")

    return errors


def validate_opencode_json(path: Path) -> list[str]:
    """Validate opencode.json for Windows paths on Linux."""
    errors = []
    try:
        with open(path) as f:
            data = json.load(f)
    except Exception as e:
        return [f"Failed to parse {path}: {e}"]

    # Check mcp.servers
    mcp = data.get("mcp", {})
    servers = mcp.get("servers", {})
    for name, config in servers.items():
        cmd = config.get("command", [])
        if isinstance(cmd, list):
            for part in cmd:
                if isinstance(part, str) and ("\\" in part or "C:" in part or "c:" in part):
                    errors.append(f"{path}: mcp.servers.{name}.command has Windows path: {part}")

        env = config.get("environment", {})
        for key, val in env.items():
            if isinstance(val, str) and ("\\" in val or "C:" in val or "c:" in val):
                errors.append(
                    f"{path}: mcp.servers.{name}.environment.{key} has Windows path: {val}"
                )

    return errors


def main():
    all_errors = []

    # Check .mcp.json files
    for mcp_path in Path(".").rglob(".mcp.json"):
        # Skip node_modules, .git, etc.
        if any(part in mcp_path.parts for part in ("node_modules", ".git", ".venv", "__pycache__")):
            continue
        all_errors.extend(validate_mcp_json(mcp_path))

    # Check opencode.json files
    for oc_path in Path(".").rglob("opencode.json"):
        if any(part in oc_path.parts for part in ("node_modules", ".git", ".venv", "__pycache__")):
            continue
        all_errors.extend(validate_opencode_json(oc_path))

    if all_errors:
        print("Config path validation failed:", file=sys.stderr)
        for err in all_errors:
            print(f"  {err}", file=sys.stderr)
        return 1

    print("Config path validation passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
