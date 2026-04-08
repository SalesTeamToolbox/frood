# Phase 52: Core Identity Rename - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-07
**Phase:** 52-core-identity-rename
**Areas discussed:** Env var fallback pattern, Data directory migration, Hook file scope, Entry point shim

---

## Env Var Fallback Pattern

| Option | Description | Selected |
|--------|-------------|----------|
| Centralized helper | `_env(frood_name, agent42_name, default)` in config.py | |
| Inline getenv chains | `os.getenv("FROOD_X", os.getenv("AGENT42_X", default))` per call site | |
| Config.py only, others direct | Helper in config.py, inline chains elsewhere | |

**User's initial choice:** Centralized helper, but then asked "why are we in need of Agent42 in anything?"

### Follow-up: Backward Compat vs Clean Break

| Option | Description | Selected |
|--------|-------------|----------|
| Fallback with deprecation log | FROOD_* primary, AGENT42_* logs warning | |
| Clean break, no fallback | Only FROOD_* vars work, update .env files manually | ✓ |
| Fallback, no warnings | Silent fallback forever | |

**User's choice:** Clean break — "you have access to the VPS via SSH, so this is simple and fast."
**Notes:** This eliminated the need for a centralized helper function entirely. Straight rename.

---

## Data Directory Migration

| Option | Description | Selected |
|--------|-------------|----------|
| Auto-rename on startup | If .agent42/ exists and .frood/ doesn't, shutil.move() with log | ✓ |
| Clean break, manual rename | Just change paths, SSH and `mv` on VPS | |
| Auto-rename + delete old | Same as auto-rename but removes .agent42/ after | |

**User's choice:** Auto-rename on startup
**Notes:** One exception to the clean-break philosophy — auto-migration prevents data loss if admin forgets.

### Follow-up: Migration Location

| Option | Description | Selected |
|--------|-------------|----------|
| frood.py main() startup | Migration runs at entry point before anything reads data dir | ✓ |
| core/config.py from_env() | Migration at config load time | |

**User's choice:** frood.py main() startup

---

## Hook File Scope

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, include hooks | Rename AGENT42_* env reads and [agent42-*] prefixes in all hook files | ✓ |
| Hooks in Phase 55 | Defer hooks to Phase 55 with test suite updates | |

**User's choice:** Include hooks in Phase 52
**Notes:** Clean break applies to hooks too — they produce user-visible stderr output.

---

## Entry Point Shim

| Option | Description | Selected |
|--------|-------------|----------|
| Deprecation warning + redirect | Print warning to stderr, then import frood.main() | ✓ |
| Silent redirect | Just import and call, no warning | |
| No shim, just rename | Delete agent42.py entirely | |

**User's choice:** Deprecation warning + redirect

---

## Claude's Discretion

- Exact order of file-by-file renaming
- Whether to rename mcp_server.py filename itself
- Edge case handling in config.py for computed paths

## Deferred Ideas

- Frontend localStorage/BroadcastChannel rename (Phase 53)
- Docker/compose rename (Phase 54)
- NPM package rename (Phase 54)
- Qdrant collection rename (Phase 55)
