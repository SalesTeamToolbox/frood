#!/usr/bin/env python3
"""Validate pyproject.toml ruff config for common issues."""

import sys
import tomllib


def main():
    with open("pyproject.toml", "rb") as f:
        data = tomllib.load(f)

    select = data.get("tool", {}).get("ruff", {}).get("lint", {}).get("select", [])

    # Check for removed rule
    if "RUF059" in select:
        print("ERROR: RUF059 in select list - this rule was removed in ruff 0.6.0", file=sys.stderr)
        return 1

    # Check that common RUF rules are present
    required = {"RUF001", "RUF005", "RUF006", "RUF012", "RUF013", "RUF015"}
    missing = required - set(select)
    if missing:
        print(f"ERROR: Missing required RUF rules in select: {missing}", file=sys.stderr)
        return 1

    print("pyproject.toml ruff config validated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
