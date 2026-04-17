# Requirements: Cross-CLI Setup

**Defined:** 2026-04-17
**Core Value:** Frood can onboard any MCP-capable CLI (Claude Code, OpenCode, and later Cursor/Aider/Continue) with a single command — preserving the token-budget discipline the user already enjoys in Claude Code (warehoused skills loaded on-demand) across every CLI they use.

## v1 Requirements

### User Manifest & Dir

- [x] **CLI-01**: Introduce `~/.frood/` as a user-level config directory (Frood currently only uses project-local `.frood/`)
- [x] **CLI-02**: `~/.frood/cli.yaml` manifest: per-CLI enable flags, project auto-detect list, warehouse inclusion toggles
- [x] **CLI-03**: Manifest is self-creating with sane defaults on first run; absent file must not crash setup

### MCP Warehouse Bridge

- [x] **MCP-01**: New MCP tool `frood_skill` registered in `mcp_server.py:_build_registry`
- [x] **MCP-02**: `frood_skill(action="list")` returns inventory across `~/.claude/skills-warehouse/`, `commands-warehouse/`, `agents-warehouse/`, Frood built-in personas, and Frood built-in skills
- [x] **MCP-03**: `frood_skill(action="load", name=...)` returns the full markdown body of the named item
- [x] **MCP-04**: Indexing respects manifest flags (include_claude_warehouse, include_frood_builtins)
- [x] **MCP-05**: Missing warehouse paths degrade gracefully (no crash, empty slice in inventory)

### `frood cli-setup` Subcommand

- [x] **CMD-01**: Register `cli-setup` argparse subparser in `frood.py` following existing `backup`/`restore`/`clone` pattern
- [x] **CMD-02**: Implement `CliSetupCommandHandler` in `commands.py` extending `CommandHandler` ABC
- [x] **CMD-03**: `frood cli-setup detect` reports installed CLIs + current wiring state as JSON
- [x] **CMD-04**: `frood cli-setup claude-code` merges a `frood` entry into `~/.claude/settings.json` `mcpServers` block; preserves all other keys byte-for-byte
- [x] **CMD-05**: `frood cli-setup opencode [<path>]` auto-detects or accepts explicit project paths; merges a `frood` entry into each `opencode.json` `mcp` object; preserves providers/instructions/server settings
- [x] **CMD-06**: `frood cli-setup opencode` writes/updates a one-line note in `AGENTS.md` pointing users to `frood_skill list` / `load`
- [x] **CMD-07**: `frood cli-setup all` wires every CLI flagged enabled in the manifest
- [x] **CMD-08**: `frood cli-setup unwire <cli>` removes the `frood` entry from that CLI's config reversibly (round-trip must be byte-identical to original)
- [x] **CMD-09**: All writes idempotent: re-running the same command produces no diff

### Dashboard

- [x] **DASH-01**: `GET /api/cli-setup/detect` mirroring existing admin-guarded endpoint pattern
- [x] **DASH-02**: `POST /api/cli-setup/wire` with `{cli, enabled}` calls the same core functions as the CLI command
- [x] **DASH-03**: Dashboard panel in `dashboard/frontend/dist/app.js` showing detected CLIs, per-CLI toggle, "What this does" blurb, link to docs
- [x] **DASH-04**: Toggle state persisted to `.frood/cli-setup-state.json` (mirrors existing `.frood/toggles.json` pattern)

### Safety & Reversibility

- [x] **SAFE-01**: Every CLI config write creates a timestamped backup beside the target (e.g., `opencode.json.bak-20260417T120000`) before first modification
- [x] **SAFE-02**: `unwire` is tested in the suite for byte-identical round-trip against realistic fixtures
- [x] **SAFE-03**: Setup never disables or removes user's existing MCP servers, plugins, or providers

### Tests

- [ ] **TEST-01**: `tests/test_cli_setup.py` covers merge idempotency for both Claude Code and OpenCode config shapes
- [ ] **TEST-02**: Wire → unwire round-trip byte-identical
- [ ] **TEST-03**: Manifest parser with missing keys → defaults
- [ ] **TEST-04**: `frood_skill list` and `load` return expected inventory against fixture warehouse

## Explicitly Out of Scope (v1)

- Cursor, Aider, Continue integrations (architecture must not paint us into a corner, but no implementation)
- Per-skill dashboard toggles (manifest is source of truth for inclusion)
- Auto-detect-and-prompt on Frood launch (explicit trigger only)
- Rewriting or altering the user's existing `/use` command (Claude Code already works)

## Success Criteria

1. From a fresh checkout, `frood cli-setup all` detects Claude Code + OpenCode, writes configs for both, and is idempotent on re-run
2. An OpenCode session against Frood MCP can invoke `frood_skill list` and receive the same warehouse inventory Claude Code sees via `/use`
3. Dashboard toggle off/on produces the same diffs as CLI wire/unwire
4. Unwire returns both target config files to their pre-setup state (byte-identical)
5. Missing `~/.frood/cli.yaml` does not crash; gets created with defaults
