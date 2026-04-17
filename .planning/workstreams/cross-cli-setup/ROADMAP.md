# Roadmap: Cross-CLI Setup

## Milestone: v1 — Claude Code + OpenCode Parity

**Goal:** Ship a single `frood cli-setup` command + dashboard toggle that writes native MCP configs for Claude Code and OpenCode from a user-level manifest at `~/.frood/cli.yaml`, and expose the Claude Code warehouse through a new `frood_skill` MCP tool so OpenCode gets on-demand skill loading equivalent to `/use`.

### Phases

- [ ] **Phase 01: Cross-CLI Setup Core** — Everything in v1: manifest, MCP bridge tool, CLI subcommand, dashboard panel, tests

### Phase 01: Cross-CLI Setup Core

**Goal:** Deliver the complete v1 feature in a single phase — the scope is tightly coupled (MCP tool is useless without CLI wiring; wiring is useless without dashboard parity) and splitting into micro-phases would add coordination cost without reducing risk.

**Depends on:** Nothing

**Requirements:** CLI-01 through CLI-03, MCP-01 through MCP-05, CMD-01 through CMD-09, DASH-01 through DASH-04, SAFE-01 through SAFE-03, TEST-01 through TEST-04

**Plans:** 6 plans

- [ ] `01-01-PLAN.md` — User manifest + `~/.frood/` bootstrap (CLI-01..03)
- [ ] `01-02-PLAN.md` — `frood_skill` MCP bridge tool + registration (MCP-01..05)
- [ ] `01-03-PLAN.md` — `core/cli_setup.py` adapters: backup, wire, unwire, safety (SAFE-01..03)
- [ ] `01-04-PLAN.md` — `frood cli-setup` CLI subcommand + handler (CMD-01..09)
- [ ] `01-05-PLAN.md` — Dashboard panel + `/api/cli-setup/*` endpoints (DASH-01..04)
- [ ] `01-06-PLAN.md` — Named phase test suite `tests/test_cli_setup.py` (TEST-01..04)

**Success Criteria** (what must be TRUE):

1. `frood cli-setup detect` reports Claude Code + OpenCode installation and wiring state as JSON
2. `frood cli-setup all` wires both CLIs idempotently with timestamped backups of modified config files
3. `frood_skill list` and `frood_skill load <name>` work from both Claude Code and OpenCode sessions
4. Dashboard panel at `/` shows CLI toggles whose off/on state matches CLI wire/unwire byte-for-byte
5. `frood cli-setup unwire <cli>` returns target config files to pre-setup state (byte-identical)
6. Full test suite passes including the new `tests/test_cli_setup.py` cases
7. `~/.frood/cli.yaml` absent → auto-creates with defaults; present with partial keys → defaults fill gaps

**Approved Plan (input to planner):** `C:\Users\rickw\.claude\plans\with-our-claude-code-wobbly-goblet.md`
