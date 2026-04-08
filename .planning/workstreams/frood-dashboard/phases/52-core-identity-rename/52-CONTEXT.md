# Phase 52: Core Identity Rename - Context

**Gathered:** 2026-04-07
**Status:** Ready for planning

<domain>
## Phase Boundary

The backend fully speaks "frood" — entry point, data directory, env vars, config reads, logger names, print prefixes, MCP module references, and CLAUDE.md markers all use the new name. `agent42.py` becomes a thin deprecation shim. `.agent42/` auto-migrates to `.frood/` on first startup. No backward-compat env var fallbacks — clean break.

</domain>

<decisions>
## Implementation Decisions

### Env Var Strategy
- **D-01:** Clean break — rename all `AGENT42_*` env vars to `FROOD_*` with no fallback. No `_env()` helper function. Straight rename across all files.
- **D-02:** 11 env vars to rename: `AGENT42_WORKSPACE` → `FROOD_WORKSPACE`, `AGENT42_DATA_DIR` → `FROOD_DATA_DIR`, `AGENT42_SEARCH_URL` → `FROOD_SEARCH_URL`, `AGENT42_API_URL` → `FROOD_API_URL`, `AGENT42_ROOT` → `FROOD_ROOT`, `AGENT42_DASHBOARD_URL` → `FROOD_DASHBOARD_URL`, `AGENT42_SSH_ALIAS` → `FROOD_SSH_ALIAS`, `_AGENT42_BROWSER_TOKEN` → `_FROOD_BROWSER_TOKEN`, `AGENT42_VIDEO_MODEL` → `FROOD_VIDEO_MODEL`, `AGENT42_IMAGE_MODEL` → `FROOD_IMAGE_MODEL`, `AGENT42_WORKTREE_DIR` → `FROOD_WORKTREE_DIR`.
- **D-03:** `.env` files (local + VPS) updated as part of deployment. SSH access to VPS is available for this.

### Data Directory Migration
- **D-04:** Default data directory changes from `.agent42/` to `.frood/` in all code paths (~12 defaults in `config.py from_env()`).
- **D-05:** Auto-rename on startup: if `.agent42/` exists and `.frood/` does not, `shutil.move()` with a log message. If both exist, use `.frood/` and log a warning.
- **D-06:** Migration logic lives in `frood.py main()` startup, before anything reads the data dir.

### Entry Point
- **D-07:** Create `frood.py` as the main entry point. Move all logic from `agent42.py` into `frood.py`.
- **D-08:** `agent42.py` becomes a thin deprecation shim (~5 lines): prints "[frood] agent42.py is deprecated — use frood.py" to stderr, then imports and calls `frood.main()`.

### Python Internals
- **D-09:** All `getLogger("agent42.*")` logger names change to `getLogger("frood.*")` — ~100 files across core/, tools/, memory/, dashboard/, agents/, channels/, providers/, skills/.
- **D-10:** All `[agent42-*]` print prefixes change to `[frood-*]` — hooks and test assertions.
- **D-11:** `mcp_server.py`: `_AGENT42_ROOT` variable renamed to `_FROOD_ROOT`. All `AGENT42_*` env reads renamed to `FROOD_*`.
- **D-12:** CLAUDE.md marker injection updated from `AGENT42_MEMORY` to `FROOD_MEMORY`.

### Hook Files (In Scope)
- **D-13:** All `.claude/hooks/` files included in this phase. Rename both `AGENT42_*` env var reads and `[agent42-*]` print prefixes. ~6 hook files: `memory-recall.py`, `memory-learn.py`, `proactive-inject.py`, `cc-memory-sync.py`, `context-loader.py`, `effectiveness-learn.py`, `knowledge-learn-worker.py`, `credential-sync.py`.
- **D-14:** Test files that assert on `[agent42-*]` prefixes (`test_memory_hooks.py`, `test_proactive_injection.py`) updated to match new `[frood-*]` prefixes.

### Claude's Discretion
- Exact order of file-by-file renaming (batch by module or alphabetical)
- Whether to rename `mcp_server.py` filename itself (PY-03 says "references", not filename)
- How to handle any edge cases in config.py from_env() where `.agent42/` appears in computed paths

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Entry Point & Config
- `agent42.py` — Current main entry point (~120 lines). Will become `frood.py`; old file becomes shim.
- `core/config.py` — Settings dataclass with `from_env()` (~800 lines). ~12 `.agent42/` defaults to rename, all `AGENT42_*` env reads to rename.

### MCP Server
- `mcp_server.py` — MCP server module (~650 lines). `_AGENT42_ROOT` variable, `AGENT42_WORKSPACE`, `AGENT42_SEARCH_URL`, `AGENT42_API_URL` env reads.

### Dashboard
- `dashboard/server.py` — Logger name `agent42.server`, FastAPI title already "Frood Dashboard" (Phase 51).
- `dashboard/auth.py` — Logger name `agent42.auth`.
- `dashboard/sidecar.py` — Logger name `agent42.sidecar`.
- `dashboard/websocket_manager.py` — Logger name `agent42.websocket`.

### Hooks
- `.claude/hooks/memory-recall.py` — `AGENT42_SEARCH_URL`, `AGENT42_API_URL`, `AGENT42_ROOT`, `[agent42-memory]` prefixes.
- `.claude/hooks/memory-learn.py` — `AGENT42_SEARCH_URL`, `[agent42-memory]` prefixes.
- `.claude/hooks/proactive-inject.py` — `AGENT42_DASHBOARD_URL`, `AGENT42_DATA_DIR`, `[agent42-learnings]`, `[agent42-recommendations]` prefixes.
- `.claude/hooks/cc-memory-sync.py` — `[agent42-memory]` prefix.
- `.claude/hooks/context-loader.py` — `[agent42]` prefix.
- `.claude/hooks/effectiveness-learn.py` — `AGENT42_DASHBOARD_URL`.
- `.claude/hooks/knowledge-learn-worker.py` — `AGENT42_DASHBOARD_URL`.
- `.claude/hooks/credential-sync.py` — `AGENT42_SSH_ALIAS`.

### Tests
- `tests/test_memory_hooks.py` — Asserts on `[agent42-memory]` prefix strings.
- `tests/test_proactive_injection.py` — Asserts on `[agent42-recommendations]`, `[agent42-learnings]` prefixes.
- `tests/e2e/config.py`, `tests/e2e/discovery.py`, `tests/e2e/runner.py` — `AGENT42_ROOT` references.

### Requirements
- `.planning/workstreams/frood-dashboard/REQUIREMENTS.md` — ENTRY-01..05, DATA-01..03, PY-01..04

</canonical_refs>

<code_context>
## Existing Code Insights

### Blast Radius Summary
| Area | Files | Changes |
|------|-------|---------|
| Logger names (`agent42.*` → `frood.*`) | ~100 | Single-line `getLogger()` calls |
| `AGENT42_*` env vars → `FROOD_*` | ~23 | `os.getenv()` / `os.environ.get()` calls |
| `.agent42/` path defaults → `.frood/` | ~25 | String literals in config and path construction |
| `[agent42-*]` print prefixes → `[frood-*]` | ~10 | Print/f-string statements in hooks + tests |
| `_AGENT42_ROOT` variable | 1 | mcp_server.py variable rename |
| Entry point | 2 | New frood.py + agent42.py shim |

### Established Patterns
- All logger names follow `agent42.{module}` or `agent42.{category}.{module}` pattern — clean regex replacement
- Config `from_env()` is the single source of truth for all env var reads — most AGENT42_* reads are centralized there
- Hook files are standalone Python scripts (no imports from core/) — can be renamed independently

### Integration Points
- `.env` files need updating: local `.env`, `.env.paperclip`, VPS `.env`
- `.env.example` needs FROOD_* naming
- `scripts/setup_helpers.py` references `AGENT42_WORKSPACE` in MCP config generation
- `agent42-service.xml` (Windows service wrapper) references `agent42.py`

</code_context>

<specifics>
## Specific Ideas

- User wants a clean break — no backward-compat env var fallbacks. "You have access to the VPS via SSH, so this is simple and fast."
- Data directory auto-migration is the one exception to clean break — keeps working even if admin forgets to manually rename the dir
- Deprecation shim for agent42.py: print warning to stderr, then delegate to frood.main()

</specifics>

<deferred>
## Deferred Ideas

- **Frontend localStorage/BroadcastChannel rename** — `agent42_token` → `frood_token`, `agent42_auth` → `frood_auth`. Phase 53 scope (FE-01, FE-02).
- **Docker/compose rename** — Service names, volumes, Dockerfile references. Phase 54 scope (INFRA-01..04).
- **NPM package rename** — `@agent42/paperclip-*` → `@frood/paperclip-*`. Phase 54 scope (NPM-01..03).
- **Qdrant collection rename** — `agent42_memory`/`agent42_history` → `frood_*`. Phase 55 scope (QDRANT-01..03).
- **Git repo rename** — GitHub repo URL stays `agent42` — explicitly out of scope per REQUIREMENTS.md.

</deferred>

---

*Phase: 52-core-identity-rename*
*Context gathered: 2026-04-07*
