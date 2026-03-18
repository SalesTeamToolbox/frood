# Phase 1: Setup Foundation - Research

**Researched:** 2026-03-18
**Domain:** Bash setup scripting, JSON config merging, MCP JSON-RPC, shell health checks
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **MCP config generation**: Include all 6 servers (agent42, agent42-remote, jcodemunch, context7, github, playwright). Merge strategy: read existing `.mcp.json`, add missing Agent42 servers, never remove/overwrite existing entries. Create fresh only if missing.
- **SSH alias for agent42-remote**: Prompt "SSH alias for remote node (leave blank to skip)". If blank, omit `agent42-remote`.
- `agent42` entry uses `.venv/bin/python` (auto-detected absolute path) and absolute path to `mcp_server.py`.
- `AGENT42_WORKSPACE` = project root (absolute). `REDIS_URL` defaults to `redis://localhost:6379/0`. `QDRANT_URL` defaults to `http://localhost:6333`.
- **Hook registration**: Register ALL `.py` hook scripts in `.claude/hooks/`. Each script declares its event via frontmatter comment. Merge strategy: read existing `.claude/settings.json`, add missing hooks, never remove existing.
- **Hook command format**: `cd /absolute/project/path && python .claude/hooks/script.py`
- **Hook timeout**: read from hook frontmatter if present, else default 30s.
- **jcodemunch indexing**: Python helper script (`scripts/jcodemunch_index.py`) spawns `jcodemunch-mcp` as subprocess, speaks MCP JSON-RPC over stdio: `initialize` then `tools/call index_folder`. If uvx missing, auto-install via `pip install uv`.
- **Indexing inline/blocking** — not a background job. Failure is a WARN, not hard error.
- **Health report**: Terminal only (no file saved). 5 services: MCP server, jcodemunch, Qdrant, Redis, Claude Code CLI. Pass = green `[✓]`, Fail = red/yellow `[✗]` with fix hint. Qdrant/Redis failures = warnings. MCP/Claude Code CLI failures = errors.
- **Summary line**: `Setup complete. X/5 services healthy.`

### Claude's Discretion

- Exact Python JSON-RPC client implementation for jcodemunch indexing (async/sync, timeout values)
- How to probe the MCP server for health (could be `--health` flag or test stdin request)
- Exact colored output implementation (ANSI codes vs `tput`)
- Order of setup steps within setup.sh (should come after existing venv/deps steps)

### Deferred Ideas (OUT OF SCOPE)

- None — discussion stayed within phase scope
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| SETUP-01 | User can run `bash setup.sh` on Linux/VPS and have `.mcp.json` generated with Agent42 MCP server entry | MCP config generation pattern documented; merge strategy via `python -c` or helper script |
| SETUP-02 | User can run `bash setup.sh` on Linux/VPS and have `.claude/settings.json` patched to register all Agent42 hooks | Hook registration pattern documented; JSON merge via Python; frontmatter gap identified with solution |
| SETUP-03 | User can run `bash setup.sh` on Linux/VPS and have the project repo indexed by jcodemunch automatically | jcodemunch JSON-RPC subprocess pattern documented; MCP protocol verified |
| SETUP-04 | User can re-run `bash setup.sh` without overwriting existing configuration (idempotent) | Idempotency pattern already present in setup.sh; merge-not-overwrite strategy documented |
| SETUP-05 | User can see a post-setup health report confirming MCP server, jcodemunch, and Qdrant are reachable | Health probe commands documented for all 5 services; output format specified |
</phase_requirements>

---

## Summary

Phase 1 extends the existing `setup.sh` (currently 109 lines) with four new sections: MCP config generation, hook registration, jcodemunch indexing, and a health report. All heavy lifting is done in Python helper scripts called from bash — keeping shell code minimal and testable.

The most significant implementation gap found during research is that **the existing hook files have NO frontmatter comments**. The CONTEXT.md decision states hooks will declare their event via frontmatter (`# hook: PostToolUse`), but none of the 13 hook files in `.claude/hooks/` have this. The setup script cannot auto-read event types from the hooks — it must either (a) add frontmatter comments to each hook file as part of this phase, or (b) use the existing `.claude/settings.json` as a reference template during setup. The recommended approach is (a): add `# hook_event: <EventName>` and `# hook_matcher: <pattern>` comments to each hook file, then the setup script reads them. This makes the system self-describing.

The second critical finding is that `mcp_server.py` has **no `--health` flag**. It only accepts `--transport` and `--port`. The health check for the MCP server must use an alternative probe strategy.

**Primary recommendation:** Use Python for all JSON manipulation (`python3 -c` or standalone scripts in `scripts/`). Never manipulate JSON in bash. Follow the existing idempotency pattern (`if [ ! -f ... ]; then ... else info "already exists — skipping"; fi`) for both `.mcp.json` and `.claude/settings.json`.

---

## Standard Stack

### Core

| Tool | Version | Purpose | Why Standard |
|------|---------|---------|--------------|
| bash | 5.x | Setup orchestration | Already used in setup.sh; `set -e` pattern established |
| python3 | 3.11+ | JSON config merging, jcodemunch JSON-RPC helper | Already in venv; required by project |
| `python -c` or `scripts/*.py` | — | Config manipulation | Avoids `jq` dependency; python3 guaranteed present after venv step |
| subprocess (stdlib) | — | Spawn jcodemunch-mcp process | No external deps; MCP server speaks stdio |
| `redis-cli` | system | Redis health probe | Simplest probe; installed with Redis |
| `curl` | system | Qdrant HTTP health probe | Available on all Linux; `/healthz` endpoint |

### Supporting

| Tool | Version | Purpose | When to Use |
|------|---------|---------|-------------|
| `uvx` (from uv) | latest | Run jcodemunch-mcp without global install | Auto-installed if missing via `pip install uv` |
| ANSI escape codes | — | Colored health report output | Direct `\033[...]` — consistent with existing `setup.sh` color vars |
| `tput` | — | Alternative color approach | Only if ANSI direct codes prove unreliable in CI |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `python3 -c` for JSON | `jq` | `jq` not guaranteed on all VPS; Python always present after venv step |
| ANSI direct codes | `tput` | `tput` requires terminfo DB; ANSI codes match existing setup.sh pattern |
| Subprocess MCP JSON-RPC | HTTP REST API | jcodemunch-mcp only exposes stdio MCP, not HTTP |

---

## Architecture Patterns

### Recommended Project Structure

New files introduced by this phase:

```
scripts/
├── jcodemunch_index.py    # MCP JSON-RPC client: sends initialize + index_folder
└── setup_mcp_config.py   # Generates/merges .mcp.json (optional: could be inline -c)
.claude/
└── hooks/
    └── *.py               # Add # hook_event: and # hook_matcher: frontmatter to each
setup.sh                   # Extended with 4 new sections before "── Done ──"
```

### Pattern 1: JSON Merge (not overwrite)

**What:** Read existing JSON file, add missing keys, write back. Never touch keys already present.

**When to use:** All config file manipulation (`.mcp.json`, `.claude/settings.json`).

```python
# Source: project pattern (settings.json already uses this structure)
import json, os, sys

def merge_mcp_config(project_dir, venv_python, ssh_alias=None):
    mcp_path = os.path.join(project_dir, ".mcp.json")
    try:
        with open(mcp_path) as f:
            config = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        config = {"mcpServers": {}}

    servers = config.setdefault("mcpServers", {})

    # Only add if not already present
    if "agent42" not in servers:
        servers["agent42"] = {
            "command": venv_python,
            "args": [os.path.join(project_dir, "mcp_server.py")],
            "env": {
                "AGENT42_WORKSPACE": project_dir,
                "REDIS_URL": "redis://localhost:6379/0",
                "QDRANT_URL": "http://localhost:6333",
            },
        }
    # ... other servers follow same pattern

    with open(mcp_path, "w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")
```

**Idempotency guarantee:** Presence check (`if "agent42" not in servers`) before inserting.

### Pattern 2: Hook Frontmatter Parsing

**What:** Each `.py` hook file declares its event and matcher via top-of-file comments. Setup reads these to know where to register each hook.

**When to use:** Auto-discovering hook registrations without hardcoding event types in setup.sh.

```python
# Proposed frontmatter convention (to be added to each hook file):
# hook_event: PostToolUse
# hook_matcher: Write|Edit
# hook_timeout: 30

def read_hook_metadata(hook_path):
    """Read frontmatter-style comments from a hook file."""
    meta = {"event": None, "matcher": None, "timeout": 30}
    with open(hook_path) as f:
        for line in f:
            line = line.strip()
            if not line.startswith("#"):
                break  # Stop at first non-comment line
            if line.startswith("# hook_event:"):
                meta["event"] = line.split(":", 1)[1].strip()
            elif line.startswith("# hook_matcher:"):
                meta["matcher"] = line.split(":", 1)[1].strip()
            elif line.startswith("# hook_timeout:"):
                meta["timeout"] = int(line.split(":", 1)[1].strip())
    return meta
```

**IMPORTANT:** The `#!/usr/bin/env python3` shebang is line 1, so frontmatter comments go on lines 2–4 (after the shebang, before the docstring).

### Pattern 3: jcodemunch MCP JSON-RPC via Subprocess

**What:** Spawn `uvx jcodemunch-mcp` as a subprocess, write MCP protocol JSON to its stdin, read JSON responses from stdout.

**When to use:** Indexing the project repo during setup.

```python
# Source: MCP protocol specification (stdio transport)
# jcodemunch-reindex.py in this project shows the MCP tool name: "index_folder"
import json, subprocess, sys, time

def index_project(project_dir, timeout=120):
    """Send MCP initialize + index_folder to jcodemunch-mcp via stdin/stdout."""
    proc = subprocess.Popen(
        ["uvx", "jcodemunch-mcp"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    # MCP initialize handshake
    init_msg = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2024-11-05",
                           "capabilities": {}, "clientInfo": {"name": "setup", "version": "1.0"}}}
    proc.stdin.write(json.dumps(init_msg) + "\n")

    # tools/call index_folder
    call_msg = {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {"name": "index_folder",
                           "arguments": {"path": project_dir, "incremental": False}}}
    proc.stdin.write(json.dumps(call_msg) + "\n")
    proc.stdin.flush()
    proc.stdin.close()

    try:
        stdout, _ = proc.communicate(timeout=timeout)
        return proc.returncode == 0
    except subprocess.TimeoutExpired:
        proc.kill()
        return False
```

### Pattern 4: MCP Server Health Probe

**What:** The existing `mcp_server.py` has NO `--health` flag. Use a minimal MCP `initialize` request over stdin to verify the server starts and responds.

**When to use:** Health check step in post-setup report.

```python
# Probe: send MCP initialize, wait for response within 10s, check returncode/output
import subprocess, json, sys

def probe_mcp_server(python_path, server_path, workspace):
    """Send a minimal MCP initialize and verify response."""
    init_msg = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                           "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                                      "clientInfo": {"name": "healthcheck", "version": "1.0"}}})
    try:
        proc = subprocess.Popen(
            [python_path, server_path],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env={**os.environ, "AGENT42_WORKSPACE": workspace},
            text=True,
        )
        stdout, _ = proc.communicate(input=init_msg + "\n", timeout=10)
        proc.kill()  # Clean up after response
        return '"result"' in stdout or '"serverInfo"' in stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False
```

**Alternative (simpler):** `python mcp_server.py --transport sse --port 18099` in background, `curl localhost:18099/health`, kill process. Only viable if SSE transport has a health endpoint (unconfirmed).

### Anti-Patterns to Avoid

- **Parsing JSON in bash with sed/awk:** Error-prone, breaks on nested structures. Use Python.
- **`set -e` + Python scripts that exit non-zero on warnings:** Python helper scripts must exit 0 for all non-fatal conditions; print warning text and return gracefully.
- **Calling `cd` in setup.sh without returning:** The existing `cd dashboard/frontend ... cd ../..` pattern is fragile. New sections should use `(subshell)` or absolute paths.
- **Interactive prompts in quiet mode:** SSH alias prompt, and any other prompts, MUST check `$QUIET` before running. The `install-server.sh` calls `setup.sh --quiet`.
- **Backgrounding jcodemunch indexing:** CONTEXT.md says blocking/inline. The timeout must be generous (120s+) for large repos.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| JSON merge logic | Custom bash sed/awk | Python `json` stdlib | JSON nesting, unicode, whitespace — pure bash breaks silently |
| uvx installation | Custom curl/unzip script | `pip install uv` (venv pip) | uv is a Python package; venv already activated at that point |
| Color output | Custom ANSI builder | Existing `GREEN`/`YELLOW`/`RED`/`NC` vars in setup.sh | Already defined in setup.sh — reuse them |
| MCP protocol parsing | Custom line scanner | Proper JSON-RPC parsing in Python | MCP messages can span multiple JSON lines; line-by-line is fragile |

**Key insight:** The existing `setup.sh` already has color logging helpers. All new output must use `info()`, `warn()`, `error()` — never raw `echo` with inline ANSI codes.

---

## Common Pitfalls

### Pitfall 1: Hook Files Have No Frontmatter (Gap Between Intent and Reality)

**What goes wrong:** CONTEXT.md says hooks declare their event via frontmatter comment. In reality, **none of the 13 hook files have any `# hook_event:` comments**. If setup tries to `grep "^# hook_event:"`, it finds nothing and registers no hooks.

**Why it happens:** The frontmatter convention was designed during planning but not yet implemented in the hook files.

**How to avoid:** This phase must add frontmatter comments to each hook file as a prerequisite before writing the auto-discovery logic. Map from the existing `settings.json` (which is the ground truth for current hook registrations) to build the frontmatter for each file.

**Current mapping (from `.claude/settings.json`):**

| Hook File | Event | Matcher | Timeout |
|-----------|-------|---------|---------|
| `security-gate.py` | PreToolUse | Write\|Edit\|Bash | 10 |
| `context-loader.py` | UserPromptSubmit | (none) | 30 |
| `memory-recall.py` | UserPromptSubmit | (none) | 10 |
| `security-monitor.py` | PostToolUse | Write\|Edit | 30 |
| `format-on-write.py` | PostToolUse | Write\|Edit | 30 |
| `jcodemunch-token-tracker.py` | PostToolUse | (none) | 10 |
| `jcodemunch-reindex.py` | PostToolUse | (none) + Stop | 10 / 15 |
| `session-handoff.py` | Stop | (none) | 15 |
| `test-validator.py` | Stop | (none) | 45 |
| `learning-engine.py` | Stop | (none) | 15 |
| `memory-learn.py` | Stop | (none) | 15 |
| `effectiveness-learn.py` | Stop | (none) | 30 |

Note: `jcodemunch-reindex.py` is registered in BOTH PostToolUse (no matcher) AND Stop. It handles both internally via `hook_event_name` check. This means setup needs to support hooks registered to multiple events, OR the frontmatter supports multiple `# hook_event:` lines.

Note: `security_config.py` is a shared module (not a hook), and should NOT be registered as a hook — the setup script must filter it out (it has no `# hook_event:` and no MCP event trigger in its docstring).

### Pitfall 2: MCP Server Has No `--health` Flag

**What goes wrong:** The CONTEXT.md decision says probe via `python mcp_server.py --health`. The actual `mcp_server.py` only handles `--transport` and `--port`. Calling `--health` will start the full stdio server waiting for stdin — hanging indefinitely.

**Why it happens:** `--health` flag was listed as something to implement, not something that exists.

**How to avoid:** Either (a) add a `--health` flag to `mcp_server.py` that runs a quick import/config check and exits 0/1, or (b) use the subprocess stdin probe pattern (see Pattern 4). Option (a) is cleaner and testable; option (b) requires no changes to mcp_server.py but is more complex.

**Recommendation:** Add `--health` flag to `mcp_server.py` (3-5 lines). Exit 0 if server can initialize without starting transport; exit 1 on import error or config failure.

### Pitfall 3: `set -e` Kills setup.sh on Python Script Non-Zero Exit

**What goes wrong:** `scripts/jcodemunch_index.py` fails (uvx not found, timeout, network error). `set -e` in setup.sh causes immediate exit, skipping the health report and the "jcodemunch failed" warning.

**Why it happens:** `set -e` is active in setup.sh (line 6). Any non-zero subprocess exit propagates upward.

**How to avoid:** Call Python helper scripts with error capture:
```bash
if ! python3 scripts/jcodemunch_index.py "$PROJECT_DIR"; then
    warn "jcodemunch indexing failed — run manually: uvx jcodemunch-mcp"
fi
```
The `if !` pattern prevents `set -e` from triggering on failure.

### Pitfall 4: Absolute Paths on Setup Change Between Machines

**What goes wrong:** `.mcp.json` is committed to git with developer's local absolute paths (`c:\Users\rickw\...`). When a new user clones and runs `bash setup.sh`, the merge logic sees `agent42` already in `.mcp.json` (because it was committed) and skips regeneration — leaving wrong paths.

**Why it happens:** The current `.mcp.json` in the repo has Windows absolute paths. It will be present in every clone.

**How to avoid:** The merge logic must check if `agent42.command` path actually resolves to a valid file on the current machine. If the existing entry has a non-existent path, replace it (even if key already exists). Or: gitignore `.mcp.json` and always generate fresh for new clones. Check with team on preference.

**IMPORTANT:** This is a scope decision that needs resolution in the plan. The CONTEXT.md says "add if not already in mcpServers" but doesn't address stale/wrong-path entries from committed configs.

### Pitfall 5: `cd` in setup.sh Breaks Working Directory

**What goes wrong:** The existing frontend section does `cd dashboard/frontend ... cd ../..`. If a new section added before `cd ../..` fails, the script exits with cwd as `dashboard/frontend`. `set -e` fires and scripts run from wrong directory.

**Why it happens:** Fragile directory navigation.

**How to avoid:** New sections must use absolute paths. Capture `PROJECT_DIR="$(pwd)"` at the top of setup.sh and reference it everywhere. Or use a subshell: `(cd dashboard/frontend && npm install && npm run build)`.

### Pitfall 6: `--quiet` Flag Must Suppress SSH Alias Prompt

**What goes wrong:** `deploy/install-server.sh` calls `bash setup.sh --quiet`. The new SSH alias prompt appears and hangs waiting for input — blocking automated deployment.

**Why it happens:** Interactive prompts added without checking `$QUIET`.

**How to avoid:** Every new `read` command must be wrapped: `if ! $QUIET; then read -rp "SSH alias..."; fi`. In quiet mode, skip `agent42-remote` entry entirely.

---

## Code Examples

Verified patterns from codebase:

### Existing setup.sh Idempotency Pattern
```bash
# Source: setup.sh lines 77-82
if [ ! -f ".env" ]; then
    cp .env.example .env
    info "Created .env from .env.example"
else
    info ".env already exists — skipping"
fi
```
New MCP and settings sections follow this exact pattern, extended with merge logic.

### Existing Color Logging
```bash
# Source: setup.sh lines 10-18
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()    { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }
error()   { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }
```
Health report uses these directly. Pass = `info "[✓] ServiceName: healthy"`, Fail = `warn "[✗] ServiceName: reason → Fix: cmd"`.

### jcodemunch MCP Tool Name (from jcodemunch-reindex.py)
```python
# Source: .claude/hooks/jcodemunch-reindex.py (docstring + context)
# Tool: index_folder, args: { "path": str, "incremental": bool }
# Called via: mcp__jcodemunch__index_folder in Claude Code context
```

### Hook Registration JSON Structure (from .claude/settings.json)
```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [
          {
            "type": "command",
            "command": "cd /abs/path && python .claude/hooks/script.py",
            "timeout": 30
          }
        ]
      }
    ]
  }
}
```
Events with no matcher use `{"hooks": [...]}` (no `"matcher"` key). Events with matcher use `{"matcher": "...", "hooks": [...]}`.

---

## State of the Art

| Old Approach | Current Approach | Impact |
|--------------|------------------|--------|
| Manual `.mcp.json` editing | `setup.sh` generates it | One-command setup |
| Hooks manually registered in settings.json | Auto-discovered from frontmatter | New hooks added to codebase get registered on next `setup.sh` run |
| jcodemunch indexed manually via Claude Code | `setup.sh` indexes via JSON-RPC | First-run experience has working code intelligence immediately |

---

## Open Questions

1. **Should `.mcp.json` be gitignored?**
   - What we know: Current `.mcp.json` has Windows absolute paths committed. Any Linux user who clones will have a `.mcp.json` that points to the developer's Windows paths.
   - What's unclear: Whether the "merge, don't overwrite" strategy should have a "replace if paths are invalid" exception.
   - Recommendation: Add validation in the merge logic — if `agent42.command` path doesn't exist on current machine, replace the entry. This handles stale paths without requiring gitignore changes.

2. **jcodemunch-reindex.py is registered to two events (PostToolUse and Stop)**
   - What we know: The single script handles both by checking `hook_event_name` at runtime.
   - What's unclear: How frontmatter should express multi-event registration. Options: two `# hook_event:` lines, or a comma-separated value `# hook_event: PostToolUse, Stop`.
   - Recommendation: Support multi-line frontmatter (`# hook_event:` appears twice). Simpler to parse and explicit.

3. **MCP server `--health` flag: add or probe?**
   - What we know: Flag doesn't exist. Subprocess stdin probe is more complex.
   - What's unclear: Whether modifying `mcp_server.py` is in scope for this phase.
   - Recommendation: Add `--health` flag to `mcp_server.py` as part of this phase (SETUP-05 requires it). 3-5 line addition; highly testable.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 7+ with pytest-asyncio |
| Config file | `pyproject.toml` (`[tool.pytest.ini_options]`, asyncio_mode = "auto") |
| Quick run command | `python -m pytest tests/test_setup.py -x -q` |
| Full suite command | `python -m pytest tests/ -x -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|--------------|
| SETUP-01 | `.mcp.json` generated with `agent42` entry pointing to venv python | unit | `pytest tests/test_setup.py::TestMcpConfigGeneration -x` | ❌ Wave 0 |
| SETUP-01 | `.mcp.json` merge leaves existing entries untouched | unit | `pytest tests/test_setup.py::TestMcpConfigMerge -x` | ❌ Wave 0 |
| SETUP-02 | `.claude/settings.json` patched with all hook scripts from `.claude/hooks/` | unit | `pytest tests/test_setup.py::TestHookRegistration -x` | ❌ Wave 0 |
| SETUP-02 | Hook merge leaves existing hook entries untouched | unit | `pytest tests/test_setup.py::TestHookMerge -x` | ❌ Wave 0 |
| SETUP-03 | `jcodemunch_index.py` sends valid MCP JSON-RPC `initialize` + `index_folder` messages | unit | `pytest tests/test_setup.py::TestJcodemunchIndex -x` | ❌ Wave 0 |
| SETUP-03 | Indexing failure prints WARN and continues (non-zero from subprocess does not hard-exit) | unit | `pytest tests/test_setup.py::TestJcodemunchIndexFailure -x` | ❌ Wave 0 |
| SETUP-04 | Re-running config generation with existing `.mcp.json` does not overwrite existing entries | unit | `pytest tests/test_setup.py::TestIdempotency -x` | ❌ Wave 0 |
| SETUP-05 | Health report includes pass/fail for all 5 services with correct output format | unit | `pytest tests/test_setup.py::TestHealthReport -x` | ❌ Wave 0 |
| SETUP-05 | MCP health probe (via `--health` flag or stdin) returns True when server starts | integration | `pytest tests/test_setup.py::TestMcpHealthProbe -x` | ❌ Wave 0 |

Note: `setup.sh` itself (the bash script) cannot be directly unit tested with pytest. The testable surface is the Python helper scripts it calls. The bash orchestration is tested by the integration/smoke tests or manual verification.

### Sampling Rate

- **Per task commit:** `python -m pytest tests/test_setup.py -x -q`
- **Per wave merge:** `python -m pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/test_setup.py` — covers SETUP-01 through SETUP-05 (does not exist yet)
- [ ] `scripts/` directory — must be created for `jcodemunch_index.py` and optionally `setup_mcp_config.py`
- [ ] `tests/conftest.py` already exists — check if `tmp_path` fixture sufficient for setup tests (likely yes)

---

## Sources

### Primary (HIGH confidence)

- `setup.sh` (lines 1-109) — Current script structure, color vars, `--quiet` behavior, idempotency pattern
- `.mcp.json` — All 6 server entries and their structure (ground truth for generated config template)
- `.claude/settings.json` — Full hook registration structure (ground truth for merge target and hook→event mapping)
- `.claude/hooks/*.py` — All 13 hook files; confirmed no frontmatter comments exist; event mappings derived from docstrings + runtime checks
- `mcp_server.py` (lines 486-517) — Confirmed: only `--transport` and `--port` CLI args; no `--health` flag
- `pyproject.toml` — pytest config: asyncio_mode = "auto", testpaths = ["tests"]
- `deploy/install-server.sh` — Calls `setup.sh --quiet`; new prompts must not block this flow

### Secondary (MEDIUM confidence)

- MCP protocol stdio transport pattern: derived from `jcodemunch-reindex.py` docstring + jcodemunch MCP tool names observed in hook code. JSON-RPC 2.0 `tools/call` method with `name` + `arguments` parameters is standard MCP protocol.

### Tertiary (LOW confidence)

- jcodemunch `initialize` handshake protocol version `"2024-11-05"` — derived from MCP spec knowledge; not verified against jcodemunch-mcp package source. Mark for validation during implementation.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all tools already in use in this codebase
- Architecture: HIGH — derived from existing code, not speculation
- Pitfalls: HIGH — Pitfalls 1 and 2 verified by direct file inspection; others are logical inferences from code structure
- jcodemunch JSON-RPC protocol: MEDIUM — derived from MCP stdlib patterns and existing hook code; not tested end-to-end

**Research date:** 2026-03-18
**Valid until:** 2026-04-17 (stable tooling — 30 days)
