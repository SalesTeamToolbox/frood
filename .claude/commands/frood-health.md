---
description: Frood health check — runs setup health checks via scripts/setup_helpers.py health
argument-hint: "<project-dir>"  # defaults to the Frood repo root
---

Frood health check. Runs the setup health checks via
`scripts/setup_helpers.py health <project-dir>`, reporting on the Frood
installation's health (venv, config, MCP, hooks, indexes, etc.).

**Usage:**
```
/frood-health [project-dir]
/frood-health --help
```

Example:
```
/frood-health /home/user/projects/frood
```

This runs `python scripts/setup_helpers.py health <project-dir>` from the
Frood repo root. `project-dir` defaults to the Frood repo root when omitted.
