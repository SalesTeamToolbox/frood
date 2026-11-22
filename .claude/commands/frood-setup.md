---
description: Frood setup — one-time local setup after cloning; delegates to bash setup.sh
argument-hint: "[sync-auth|create-shortcut|generate-claude-md|--quiet]"  # full setup by default
---

Frood setup. Delegates to `bash setup.sh`, run once after cloning.

**Usage:**
```
/frood-setup
/frood-setup sync-auth        # sync CC credentials to remote VPS
/frood-setup create-shortcut  # create desktop shortcut for Frood
/frood-setup generate-claude-md  # generate CLAUDE.md with Frood conventions
/frood-setup --quiet          # quiet mode (for install-server.sh)
/frood-setup --help
```

This runs `bash setup.sh [subcommand]` from the Frood repo root. The default
(full setup) detects the platform, creates the venv, installs dependencies,
runs jcodemunch indexing, and runs health checks via
`scripts/setup_helpers.py health <PROJECT_DIR>`.

After setup: `source .venv/bin/activate && python frood.py`, then open
http://localhost:8000.
