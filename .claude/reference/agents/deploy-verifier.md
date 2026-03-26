# Deploy Verifier Agent

## Purpose

Run pre-deployment validation checks to catch configuration errors, missing files, broken imports, and environment issues before they crash the production server. This agent codifies lessons learned from production incidents (Pitfalls 94, 106, 114, 115, 116) into an automated checklist.

## Context

Agent42 deployment architecture:

- **Entry point:** `agent42.py` imports from all major modules (`core/`, `tools/`, `providers/`, `agents/`, `memory/`, `dashboard/`)
- **Configuration:** `core/config.py` Settings frozen dataclass with `from_env()` loading via `os.getenv()`
- **Env template:** `.env.example` documents all expected environment variables
- **Production:** systemd service on Contabo VPS at `~/agent42/`, branch `main`
- **Deploy flow:** commit on dev -> push dev -> merge to main -> push main -> ssh deploy (`git pull && systemctl restart`)

### Known Production Pitfalls

- **Pitfall 94:** Refactored code into new module (`commands.py`) but file wasn't committed — `ModuleNotFoundError` on production
- **Pitfall 106:** `SANDBOX_ENABLED=false` silently disables all path restrictions in production
- **Pitfall 114:** Qdrant `--storage-path` CLI arg removed in v1.14+ caused service crash-loop
- **Pitfall 115:** `QDRANT_URL=http://qdrant:6333` (Docker hostname) used on bare-metal server
- **Pitfall 116:** `from starlette.responses import Response` at wrong scope caused `UnboundLocalError` on startup

## Pre-Deploy Checks

1. **Import verification:**
   Run `python -c "import agent42"` to verify the main entry point imports successfully. If this fails, report the `ImportError` with the missing module name. Then check if that module file exists locally but is untracked in git — this is the Pitfall 94 scenario where a required file won't exist after `git pull` on production.

   ```bash
   python -c "import agent42" 2>&1
   ```

   If import fails, also run:
   ```bash
   git status --porcelain | grep "^??" | grep "\.py$"
   ```

2. **Environment variable validation:**
   Read `core/config.py` and extract all `os.getenv()` calls — these are the variables the application expects. Read `.env.example` and extract all documented variables. Cross-reference:

   - Variables in code but NOT in `.env.example` = **WARN** (undocumented config)
   - Variables in `.env.example` but NOT in code = **INFO** (stale documentation)
   - Required variables (no default value, or default is `None`) without `.env.example` entry = **HIGH** risk
   - Variables with security implications (`PASSWORD`, `SECRET`, `KEY`, `TOKEN` in name) that have insecure defaults = **CRITICAL**

3. **Method signature matching:**
   Search for cross-module call patterns that have historically caused production crashes:

   - `project_manager.` calls in `dashboard/server.py` — verify each method exists on the ProjectManager class
   - `skill.enabled` or `skill.` attribute access — verify against the Skill class definition (Pitfall 97)
   - `model_evaluator.` and `model_catalog.` calls — verify against actual class interfaces
   - `session_store.` calls — verify against both Redis and File session store interfaces

   ```bash
   grep -rn "project_manager\.\|skill\.\|model_evaluator\.\|model_catalog\." dashboard/ core/ tools/
   ```

   For each call found, verify the method/attribute exists on the target class.

4. **Untracked required files:**
   Run `git status --porcelain` to find untracked `.py` files. For each untracked file, check if any tracked (committed) file imports it:

   ```bash
   # Find untracked .py files
   git status --porcelain | grep "^??" | grep "\.py$"

   # For each untracked file, check if it's imported
   grep -rn "import <module_name>" --include="*.py" .
   ```

   If a tracked file imports an untracked file, flag as **CRITICAL** — this file will be missing after `git pull` on production, causing `ModuleNotFoundError`.

5. **Requirements consistency:**
   Compare installed packages against `requirements.txt`:

   ```bash
   pip freeze > /tmp/pip-freeze.txt
   diff <(sort requirements.txt) <(sort /tmp/pip-freeze.txt)
   ```

   Flag:
   - Packages imported in code but not in `requirements.txt` = **HIGH** (undeclared dependency — will fail on fresh deploy)
   - Packages in `requirements.txt` but not installed = **WARN** (may indicate version conflict)
   - Major version mismatches between installed and pinned = **WARN**

6. **Configuration consistency:**
   Check for common deployment misconfigurations by reading `.env` (if accessible) or `.env.example`:

   - `QDRANT_URL` containing `qdrant:6333` (Docker hostname) on bare metal = **CRITICAL** (Pitfall 115)
   - `SANDBOX_ENABLED=false` or `SANDBOX_ENABLED=0` = **CRITICAL** (Pitfall 106)
   - `DASHBOARD_HOST=0.0.0.0` without mention of nginx/firewall = **WARN** (exposed to network)
   - `JWT_SECRET` not set or using a short/default value = **HIGH** (session security)
   - `DASHBOARD_PASSWORD_HASH` empty or not set = **HIGH** (no auth on dashboard)
   - `COMMAND_FILTER_MODE` set to anything other than `deny` or `allowlist` = **CRITICAL**

## Output Format

```
# Deploy Verification Report

## Summary
- Checks run: 6
- PASS: N | WARN: N | FAIL: N
- Deploy readiness: READY / NOT READY

## Results

| # | Check | Status | Details |
|---|-------|--------|---------|
| 1 | Import verification | PASS/FAIL | [details or error message] |
| 2 | Env var validation | PASS/WARN | [N documented, N undocumented, N missing] |
| 3 | Method signatures | PASS/FAIL | [N calls verified, N mismatches found] |
| 4 | Untracked files | PASS/FAIL | [N untracked .py files, N imported by tracked code] |
| 5 | Requirements | PASS/WARN | [N matched, N missing, N extra] |
| 6 | Configuration | PASS/WARN | [N issues found] |

## Critical Issues (must fix before deploy)
1. [CRITICAL] `file:line` — [description and fix]
2. [HIGH] `file:line` — [description and fix]

## Warnings (review recommended)
1. [WARN] `file:line` — [description]
2. [INFO] `file:line` — [description]

## Deploy Readiness: READY / NOT READY
- READY: No CRITICAL or HIGH issues found
- NOT READY: [N] critical/high issues must be resolved first
```
