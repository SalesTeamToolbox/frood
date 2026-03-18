# Phase 1: Setup Foundation - Context

**Gathered:** 2026-03-18
**Status:** Ready for planning

<domain>
## Phase Boundary

Extend `setup.sh` so that running `bash setup.sh` on a Linux/VPS produces a fully configured Agent42 + Claude Code environment: `.mcp.json` generated with all 6 MCP servers, `.claude/settings.json` patched with all Agent42 hooks, repo indexed in jcodemunch, and a post-setup health report printed to terminal. Re-running setup.sh must be idempotent — no existing configuration overwritten. Target platform: Linux/VPS (Windows support is Phase 2).

</domain>

<decisions>
## Implementation Decisions

### MCP config generation
- Include all 6 servers: `agent42`, `agent42-remote`, `jcodemunch`, `context7`, `github`, `playwright`
- **Merge strategy**: Read existing `.mcp.json` if present, add any Agent42 servers not already in `mcpServers`. Never remove or overwrite existing entries. Only create fresh if `.mcp.json` is missing.
- **SSH alias for agent42-remote**: Prompt during setup — "SSH alias for remote node (leave blank to skip)". If blank, omit `agent42-remote` from the generated config.
- `agent42` entry uses the venv Python path (auto-detected from `.venv/bin/python`) and absolute path to `mcp_server.py`
- `AGENT42_WORKSPACE` env var set to the project root (absolute path)
- `REDIS_URL` defaults to `redis://localhost:6379/0`
- `QDRANT_URL` defaults to `http://localhost:6333`

### Hook registration
- Register **all** hook scripts found in `.claude/hooks/` (every `.py` file)
- Each hook script declares its event via a frontmatter comment in the file (e.g., `# hook: PostToolUse` or `# matcher: Write|Edit`). Setup reads this to determine placement in `settings.json`.
- **Merge strategy**: Read existing `.claude/settings.json`, add any Agent42 hooks not already registered under the correct event key. Never remove existing hook entries.
- Command format: `cd /absolute/project/path && python .claude/hooks/script.py` — matches current convention, reliable regardless of Claude Code cwd.
- Timeout values read from hook frontmatter if present; default to 30s.

### jcodemunch indexing
- A Python helper script spawns `jcodemunch-mcp` as a subprocess and speaks MCP JSON-RPC over stdio: sends `initialize` then `tools/call index_folder` for the project root, waits for completion.
- **If uvx is missing**: auto-install via `pip install uv` (using the activated venv pip), then run `uvx jcodemunch-mcp`.
- Indexing happens inline in setup.sh, blocking — user sees progress, not a background job.
- If indexing fails (non-zero exit or timeout), print `[WARN] jcodemunch indexing failed — run manually: uvx jcodemunch-mcp` and continue (not a hard error).

### Health report format
- **Terminal only** — colored pass/fail printed at end of setup.sh. No file saved.
- **5 services checked**:
  1. MCP server — `python mcp_server.py --health` exits 0 (or equivalent quick probe)
  2. jcodemunch — `uvx jcodemunch-mcp` responds to a ping/list request over JSON-RPC
  3. Qdrant — `GET http://localhost:6333/healthz` returns HTTP 200
  4. Redis — `redis-cli ping` returns `PONG`
  5. Claude Code CLI — `claude --version` exits 0
- **Pass**: `[✓] ServiceName: healthy`
- **Fail**: `[✗] ServiceName: <reason> → Fix: <command>`
- Qdrant and Redis failures are warnings (yellow), not errors — platform still works without them
- MCP server and Claude Code CLI failures are errors (red) — critical path

### Claude's Discretion
- Exact Python JSON-RPC client implementation for jcodemunch indexing (async/sync, timeout values)
- How to probe the MCP server for health (could be a `--health` flag or a test stdin request)
- Exact colored output implementation (ANSI codes, whether to use `tput`)
- Order of setup steps within setup.sh (should come after existing venv/deps steps)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Existing setup entry point
- `setup.sh` — Current setup script. New steps must be added here, preserving the `--quiet` flag behavior (all banners/prompts suppressed in quiet mode). Existing steps (venv, pip, .env, frontend) stay unchanged.

### MCP configuration
- `.mcp.json` — Current developer config. Defines the 6 server entries and their structure. Use as the template for the generated user config.
- `mcp_server.py` — MCP server entry point. Health check mechanism and correct invocation lives here.

### Hook system
- `.claude/settings.json` — Current hook registration format. Merge target for setup.
- `.claude/hooks/` — All hook scripts. Each must have frontmatter comments for event type and matcher. Setup reads these.

### Requirements
- `.planning/workstreams/gsd-and-jcodemunch-integration/REQUIREMENTS.md` — SETUP-01 through SETUP-05 acceptance criteria (exact wording for health check verification)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `setup.sh` (lines 1-109): Existing structure to extend. Has `--quiet` mode, colored logging helpers (`info`, `warn`, `error`), and early-exit error handling via `set -e`. New sections must follow the same logging style.
- `.mcp.json`: 6-server structure to use as template for generated configs.
- `.claude/settings.json`: Existing JSON merge target — hooks use `cd /abs/path && python ...` format.
- `.claude/hooks/*.py`: 10+ hook scripts to be auto-discovered and registered.

### Established Patterns
- Color logging: `GREEN`, `YELLOW`, `RED`, `NC` vars with `info()`, `warn()`, `error()` functions — all new setup output uses these.
- Idempotency pattern: `if [ ! -f ".env" ]; then ... else info "already exists — skipping"; fi` — same pattern for .mcp.json and settings.json.
- `set -e` is active — Python helper scripts must exit 0 on success or explicitly handle errors before calling `exit`.

### Integration Points
- setup.sh end section (currently "── Done ──"): New steps insert before this section.
- `--quiet` flag: All new banners, prompts (including SSH alias prompt), and progress messages must be suppressed when `$QUIET = true`.
- `install-server.sh`: Calls `setup.sh --quiet` — new steps must not break this flow (no interactive prompts without checking `$QUIET`).

</code_context>

<specifics>
## Specific Ideas

- The jcodemunch JSON-RPC helper should be a small standalone Python script (e.g., `scripts/jcodemunch_index.py`) called from setup.sh, not inlined as a bash heredoc
- SSH alias prompt should appear BEFORE the MCP config generation step so it can inform what goes in .mcp.json
- Health report should print a summary line: `Setup complete. X/5 services healthy.` before listing individual results

</specifics>

<deferred>
## Deferred Ideas

- None — discussion stayed within phase scope

</deferred>

---

*Phase: 01-setup-foundation*
*Context gathered: 2026-03-18*
