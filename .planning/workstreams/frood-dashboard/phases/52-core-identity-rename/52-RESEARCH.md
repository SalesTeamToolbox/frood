# Phase 52: Core Identity Rename - Research

**Researched:** 2026-04-07
**Domain:** Python rename/refactor — entry point, env vars, data directory, logger names, print prefixes, CLAUDE.md marker injection
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Clean break — rename all `AGENT42_*` env vars to `FROOD_*` with no fallback. No `_env()` helper function. Straight rename across all files.
- **D-02:** 11 env vars to rename: `AGENT42_WORKSPACE` → `FROOD_WORKSPACE`, `AGENT42_DATA_DIR` → `FROOD_DATA_DIR`, `AGENT42_SEARCH_URL` → `FROOD_SEARCH_URL`, `AGENT42_API_URL` → `FROOD_API_URL`, `AGENT42_ROOT` → `FROOD_ROOT`, `AGENT42_DASHBOARD_URL` → `FROOD_DASHBOARD_URL`, `AGENT42_SSH_ALIAS` → `FROOD_SSH_ALIAS`, `_AGENT42_BROWSER_TOKEN` → `_FROOD_BROWSER_TOKEN`, `AGENT42_VIDEO_MODEL` → `FROOD_VIDEO_MODEL`, `AGENT42_IMAGE_MODEL` → `FROOD_IMAGE_MODEL`, `AGENT42_WORKTREE_DIR` → `FROOD_WORKTREE_DIR`.
- **D-03:** `.env` files (local + VPS) updated as part of deployment. SSH access to VPS is available.
- **D-04:** Default data directory changes from `.agent42/` to `.frood/` in all code paths (~12 defaults in `config.py from_env()`).
- **D-05:** Auto-rename on startup: if `.agent42/` exists and `.frood/` does not, `shutil.move()` with a log message. If both exist, use `.frood/` and log a warning.
- **D-06:** Migration logic lives in `frood.py main()` startup, before anything reads the data dir.
- **D-07:** Create `frood.py` as the main entry point. Move all logic from `agent42.py` into `frood.py`.
- **D-08:** `agent42.py` becomes a thin deprecation shim (~5 lines): prints "[frood] agent42.py is deprecated — use frood.py" to stderr, then imports and calls `frood.main()`.
- **D-09:** All `getLogger("agent42.*")` logger names change to `getLogger("frood.*")` — ~100 files across core/, tools/, memory/, dashboard/, agents/, channels/, providers/, skills/.
- **D-10:** All `[agent42-*]` print prefixes change to `[frood-*]` — hooks and test assertions.
- **D-11:** `mcp_server.py`: `_AGENT42_ROOT` variable renamed to `_FROOD_ROOT`. All `AGENT42_*` env reads renamed to `FROOD_*`.
- **D-12:** CLAUDE.md marker injection updated from `AGENT42_MEMORY` to `FROOD_MEMORY`.
- **D-13:** All `.claude/hooks/` files included in this phase. Rename both `AGENT42_*` env var reads and `[agent42-*]` print prefixes.
- **D-14:** Test files that assert on `[agent42-*]` prefixes updated to match new `[frood-*]` prefixes.

### Claude's Discretion

- Exact order of file-by-file renaming (batch by module or alphabetical)
- Whether to rename `mcp_server.py` filename itself (PY-03 says "references", not filename)
- How to handle any edge cases in config.py from_env() where `.agent42/` appears in computed paths

### Deferred Ideas (OUT OF SCOPE)

- **Frontend localStorage/BroadcastChannel rename** — `agent42_token` → `frood_token`, `agent42_auth` → `frood_auth`. Phase 53 scope (FE-01, FE-02).
- **Docker/compose rename** — Service names, volumes, Dockerfile references. Phase 54 scope (INFRA-01..04).
- **NPM package rename** — `@agent42/paperclip-*` → `@frood/paperclip-*`. Phase 54 scope (NPM-01..03).
- **Qdrant collection rename** — `agent42_memory`/`agent42_history` → `frood_*`. Phase 55 scope (QDRANT-01..03).
- **Git repo rename** — GitHub repo URL stays `agent42` — explicitly out of scope per REQUIREMENTS.md.
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| ENTRY-01 | Main entry point renamed from `agent42.py` to `frood.py` | D-07: copy `agent42.py` logic into new `frood.py`; class and startup strings renamed throughout |
| ENTRY-02 | `agent42.py` backward-compat shim exists that imports and runs `frood.py` | D-08: ~5 line shim; stderr deprecation warning then `import frood; frood.main()` |
| ENTRY-03 | All `AGENT42_*` environment variables renamed to `FROOD_*` (clean break, no fallback) | D-01/D-02: 11 vars across config.py, mcp_server.py, hooks, tools, core modules |
| ENTRY-04 | `core/config.py` Settings reads `FROOD_*` vars | D-01: straight rename in `from_env()` — no fallback helper |
| ENTRY-05 | `.env.example` updated with `FROOD_*` variable names | One comment line `AGENT42_WORKTREE_DIR` to rename; also `agent42` MCP key reference to update |
| DATA-01 | Default data directory changed from `.agent42/` to `.frood/` | D-04: ~30 string literal defaults in config.py dataclass fields + from_env() defaults |
| DATA-02 | On startup, if `.agent42/` exists and `.frood/` does not, auto-migrate with log message | D-05/D-06: `shutil.move()` in `frood.py main()` before any data dir reads |
| DATA-03 | All hardcoded `.agent42/` path references in code updated to `.frood/` | 48 files contain `.agent42` references; filter to code-owned ones (hooks, core, tests, mcp_server) |
| PY-01 | All logger names changed from `agent42.*` to `frood.*` | 107 files with `getLogger("agent42.*")` — single-pattern sed-style replacement |
| PY-02 | All `[agent42-*]` print prefixes changed to `[frood-*]` | 18 occurrences across 6 files (hooks + tests) |
| PY-03 | MCP server module references updated from `agent42` to `frood` | `_AGENT42_ROOT` var + `AGENT42_WORKSPACE/SEARCH_URL/API_URL` reads in `mcp_server.py`; `SERVER_NAME = "agent42"` constant |
| PY-04 | CLAUDE.md marker injection updated from `AGENT42_MEMORY` to `FROOD_MEMORY` | `scripts/setup_helpers.py`: 3 string constants (`_CLAUDE_MD_BEGIN`, `_CLAUDE_MD_END`, `CLAUDE_MD_TEMPLATE`) |
</phase_requirements>

---

## Summary

Phase 52 is a large-surface rename-and-refactor with well-bounded change types. Every change falls into one of six mechanical categories: env var string replacement, path default string replacement, logger name replacement, print prefix replacement, one variable rename, and one new file / one shim file. There are no algorithmic changes, no new dependencies, and no API surface changes.

The blast radius is large (~150+ files touched) but the change density per file is low — usually 1-3 lines. The highest-risk work is `core/config.py` (~30 `.agent42/` defaults to rename) and the entry-point split (`frood.py` as new canonical file, `agent42.py` as shim). The data directory auto-migration is the one piece requiring careful ordering: `shutil.move()` must run before any code reads the data dir.

A critical runtime state exists: the `.agent42/` directory on both local machine and VPS contains live data (Qdrant collections, memory files, session data). The auto-migration handles the directory rename. The `.mcp.available.json` file references `AGENT42_WORKSPACE` — this must be updated. The `agent42-service.xml` Windows service file references `agent42.py` — the shim means it keeps working, but the service ID/name should eventually be updated (this is in-scope since it still invokes the deprecated entry).

**Primary recommendation:** Organise work into four waves: (1) create `frood.py` + `agent42.py` shim + data-dir migration, (2) rename env vars in `core/config.py` + `mcp_server.py` + all calling code, (3) batch-rename all logger names, (4) rename print prefixes + update tests + CLAUDE.md markers. Run `pytest tests/test_memory_hooks.py tests/test_proactive_injection.py tests/test_setup.py` as the phase gate.

---

## Standard Stack

### Core — no new dependencies

All work uses stdlib and existing project tools only. No new packages required.

| Tool | Version | Purpose |
|------|---------|---------|
| Python stdlib `shutil` | stdlib | `shutil.move()` for data directory auto-migration |
| Python stdlib `logging` | stdlib | Logger name hierarchy — `frood.*` replaces `agent42.*` |
| Python stdlib `os.environ.get` | stdlib | Env var reads — straight rename, no new pattern |
| `ruff` | project | Auto-format and lint after edits (PostToolUse hook handles it) |

**Installation:** None required.

---

## Architecture Patterns

### Pattern 1: Entry-Point Split (D-07 / D-08)

**What:** `frood.py` is a complete copy of `agent42.py` with all `agent42` references renamed. `agent42.py` becomes a 5-line shim.

**When to use:** Renaming an entry point while keeping backward-compat invocation.

**`frood.py` structure (renaming from `agent42.py`):**
```python
# frood.py — renamed from agent42.py
# Changes:
#   - class Agent42 → class Frood
#   - logger = logging.getLogger("frood")
#   - FileHandler("frood.log")
#   - atexit message: "Frood process exiting"
#   - data_dir = Path(__file__).parent / ".frood"
#   - print("Frood v2.0 initializing ...")
#   - log messages: "Frood v2.0 initialized", "Frood starting...", etc.
```

**`agent42.py` shim (replacing current content):**
```python
"""agent42.py — deprecated entry point. Use frood.py instead."""
import sys
print("[frood] agent42.py is deprecated — use frood.py", file=sys.stderr)
from frood import main
main()
```

**`test-validator.py` GLOBAL_IMPACT_FILES set:** The hook at `.claude/hooks/test-validator.py` line 43 references `"agent42.py"` in `GLOBAL_IMPACT_FILES`. After the rename, both `"agent42.py"` (shim) and `"frood.py"` (new entry) should be in that set — a change to either triggers a full test suite run.

### Pattern 2: Data Directory Auto-Migration (D-05 / D-06)

**What:** On startup in `frood.py main()`, before creating the `Frood` instance, check for `.agent42/` and migrate.

**Ordering constraint:** Migration MUST run before `Frood.__init__()` accesses `data_dir` paths. Place it in `main()` before the `Frood(...)` constructor call.

```python
# In frood.py main(), before Frood(...) constructor
import shutil
from pathlib import Path

_project_root = Path(__file__).parent
_old_data = _project_root / ".agent42"
_new_data = _project_root / ".frood"

if _old_data.exists() and not _new_data.exists():
    shutil.move(str(_old_data), str(_new_data))
    print(
        "[frood] Migrated data directory: .agent42/ → .frood/",
        file=sys.stderr, flush=True
    )
elif _old_data.exists() and _new_data.exists():
    print(
        "[frood] WARNING: Both .agent42/ and .frood/ exist — using .frood/. "
        "Remove .agent42/ after verifying migration.",
        file=sys.stderr, flush=True
    )
```

### Pattern 3: Env Var Straight Rename (D-01 / D-02)

**What:** Every `os.environ.get("AGENT42_X", ...)` becomes `os.environ.get("FROOD_X", ...)`. No fallback, no helper function.

**Files with AGENT42_* reads:**

| File | Env vars |
|------|----------|
| `core/config.py` | None in dataclass fields — env vars are NOT `AGENT42_*`; the 11 listed vars map to different field names. The config reads generic names like `MEMORY_DIR`, `APPROVAL_LOG_PATH` etc. The 11 `AGENT42_*` vars are read directly in hooks/tools (not config). |
| `mcp_server.py` | `AGENT42_WORKSPACE`, `AGENT42_SEARCH_URL`, `AGENT42_API_URL` |
| `.claude/hooks/memory-recall.py` | `AGENT42_SEARCH_URL`, `AGENT42_API_URL`, `AGENT42_ROOT` |
| `.claude/hooks/memory-learn.py` | `AGENT42_SEARCH_URL` |
| `.claude/hooks/proactive-inject.py` | `AGENT42_DASHBOARD_URL`, `AGENT42_DATA_DIR` |
| `.claude/hooks/effectiveness-learn.py` | `AGENT42_DASHBOARD_URL` |
| `.claude/hooks/knowledge-learn-worker.py` | `AGENT42_DASHBOARD_URL` |
| `.claude/hooks/credential-sync.py` | `AGENT42_SSH_ALIAS` (reads from env + parses .env file line) |
| `tools/video_gen.py` | `AGENT42_VIDEO_MODEL` (string constant `ADMIN_OVERRIDE_ENV`) |
| `tools/image_gen.py` | `AGENT42_IMAGE_MODEL` (string constant `ADMIN_OVERRIDE_ENV`) |
| `core/portability.py` | `AGENT42_WORKTREE_DIR` |
| `core/worktree_manager.py` | `AGENT42_WORKTREE_DIR` |
| `core/task_context.py` | `AGENT42_DATA_DIR` |
| `memory/embeddings.py` | `AGENT42_WORKSPACE` (used in path construction) |
| `scripts/setup_helpers.py` | `AGENT42_WORKSPACE` (in MCP config generation, two functions) |
| `tools/browser_tool.py` | `_AGENT42_BROWSER_TOKEN` (sets env var, not reads) |
| `.mcp.available.json` | `AGENT42_WORKSPACE` in both `agent42` and `agent42-remote` entries |

**Note on `core/config.py`:** The `config.py` `from_env()` does NOT read `AGENT42_*` vars. The `.agent42/` path references are string *defaults* passed to generic env vars like `MEMORY_DIR`, `APPROVAL_LOG_PATH`, etc. These are `DATA-01`/`DATA-03` work, not `ENTRY-03`/`ENTRY-04` env var work.

### Pattern 4: Logger Name Batch Rename (D-09)

**What:** 107 files each have exactly one `getLogger("agent42.*")` call. Pattern is consistent.

**Replacement pattern:** `getLogger("agent42.` → `getLogger("frood.`

All loggers follow `agent42.{module}` or `agent42.{category}.{module}`. After rename: `frood.{module}` or `frood.{category}.{module}`.

**Special case:** `agent42.py` top-level logger is `getLogger("agent42")` → becomes `getLogger("frood")` in `frood.py`.

**Also rename:** `logging.FileHandler("agent42.log")` in `agent42.py` → `logging.FileHandler("frood.log")` in `frood.py`.

### Pattern 5: Print Prefix Rename (D-10)

**What:** 18 occurrences across 6 files.

| File | Old prefix | New prefix |
|------|-----------|-----------|
| `.claude/hooks/memory-recall.py` | `[agent42-memory]`, `[agent42-session-context]` | `[frood-memory]`, `[frood-session-context]` |
| `.claude/hooks/memory-learn.py` | `[agent42-memory]` | `[frood-memory]` |
| `.claude/hooks/cc-memory-sync.py` | `[agent42-memory]` | `[frood-memory]` |
| `.claude/hooks/proactive-inject.py` | `[agent42-learnings]`, `[agent42-recommendations]` | `[frood-learnings]`, `[frood-recommendations]` |
| `.claude/hooks/context-loader.py` | `[agent42]` | `[frood]` |
| `tests/test_memory_hooks.py` | asserts `[agent42-memory]` | assert `[frood-memory]` |
| `tests/test_proactive_injection.py` | asserts `[agent42-recommendations]`, `[agent42-learnings]` | assert `[frood-*]` |

### Pattern 6: CLAUDE.md Marker Injection Rename (D-12 / PY-04)

**What:** `scripts/setup_helpers.py` has three constants to rename:

```python
# Current:
_CLAUDE_MD_BEGIN = "<!-- BEGIN AGENT42 MEMORY -->"
_CLAUDE_MD_END = "<!-- END AGENT42 MEMORY -->"
# and the template body which contains "BEGIN AGENT42 MEMORY" and "END AGENT42 MEMORY"

# After rename:
_CLAUDE_MD_BEGIN = "<!-- BEGIN FROOD MEMORY -->"
_CLAUDE_MD_END = "<!-- END FROOD MEMORY -->"
```

The `CLAUDE_MD_TEMPLATE` string itself also contains `<!-- BEGIN AGENT42 MEMORY -->` and `<!-- END AGENT42 MEMORY -->` markers — those must be updated too.

The template also references `agent42_memory` MCP tool by name in the instruction text. The MCP tool name comes from the MCP server's `SERVER_NAME` in `mcp_server.py` + tool registration. After PY-03 changes `SERVER_NAME = "agent42"` → `SERVER_NAME = "frood"`, the MCP tool name becomes `frood_memory`. The template text must be updated accordingly.

**Existing CLAUDE.md in target projects:** If a user's CLAUDE.md already contains `<!-- BEGIN AGENT42 MEMORY -->` markers, the injection logic will fail to find them (they search for the new `FROOD` markers). The `generate_claude_md_section()` function will then fall back to appending a second block. This is a migration concern: existing CLAUDE.md files need their old markers updated, OR the injection code needs a one-time migration pass.

### Anti-Patterns to Avoid

- **Renaming Qdrant collection names in this phase:** The embedded Qdrant collections are named `agent42_memory` and `agent42_history`. These are explicitly deferred to Phase 55. Do NOT rename them here. The hooks that reference these collection names (`memory-recall.py` lines 406, 485) should retain the collection name strings while only changing the env var reads and print prefixes.
- **Backward-compat fallback for env vars:** D-01 is explicit — no `os.environ.get("FROOD_X") or os.environ.get("AGENT42_X")` pattern. Straight replacement only.
- **Moving `mcp_server.py` filename:** PY-03 says "references", not filename. Keep `mcp_server.py` as the filename.
- **Changing `.mcp.json` MCP server key names:** The key names `"agent42"` and `"agent42-remote"` in `.mcp.available.json` (and `.mcp.json` if active) are infrastructure config — in scope to update. The `SERVER_NAME` constant inside `mcp_server.py` IS in scope (PY-03).

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Batch string replacement across 107 logger files | Custom script | Standard Edit tool calls, grouped by module | Each file has 1 occurrence — individual edits are cleaner and verifiable |
| Data directory migration | Anything async | Synchronous `shutil.move()` in `main()` before `Frood()` constructor | Must complete before any file I/O on data dir |
| Env var fallback | `_env()` helper | D-01 says no fallback — straight `os.environ.get("FROOD_X", default)` | User explicitly rejected backward compat for env vars |

---

## Runtime State Inventory

| Category | Items Found | Action Required |
|----------|-------------|-----------------|
| Stored data — filesystem | `.agent42/` directory exists locally at `C:\Users\rickw\projects\agent42\.agent42\` with subdirs: `memory/`, `qdrant/`, `agents/`, `knowledge/`, `outputs/`, etc. | `shutil.move()` auto-migration in `frood.py main()` (DATA-02). VPS `.agent42/` also exists and must be migrated — handled by the same startup code when frood.py is deployed. |
| Stored data — Qdrant collections | Local embedded Qdrant at `.agent42/qdrant/` has collections `agent42_memory` and `agent42_history` | DEFERRED to Phase 55 (QDRANT-01..03). After the directory auto-migration, these collections will live at `.frood/qdrant/` but keep their names. Phase 55 renames them. |
| Live service config | `.mcp.available.json` has `"agent42"` and `"agent42-remote"` MCP server entries with `AGENT42_WORKSPACE` env vars. `.mcp.json` (active) also has the `agent42` entry with `AGENT42_WORKSPACE`. | Update env key in both files: `AGENT42_WORKSPACE` → `FROOD_WORKSPACE`. MCP server key names (`"agent42"`, `"agent42-remote"`) should also be updated to `"frood"`, `"frood-remote"`. |
| OS-registered state | `agent42-service.xml` Windows service wrapper references `agent42.py` as the Python script to run (line 8: `<arguments>agent42.py</arguments>`). The service ID is `<id>agent42</id>`. | The `agent42.py` shim (ENTRY-02) means the service keeps working without a restart. The service ID/name are cosmetic for this phase — they reference the service registration, not a code path. Flag for Phase 54/55 cosmetic cleanup. |
| Secrets/env vars | `.env` file: no `AGENT42_*` vars present (confirmed by grep — clean). `.env.example` has one: `# AGENT42_WORKTREE_DIR=/path/to/worktrees`. `.env.paperclip` and `.env.paperclip.vps`: no `AGENT42_*` vars. | Update `.env.example` comment. The VPS `.env` also has no `AGENT42_*` vars, so D-03 (`.env` updates) is minimal — only `.env.example` needs the one comment line updated. |
| Build artifacts | `.agent42/` log/state files will move with directory migration. `agent42.log` is written by the entry point — `frood.py` will write `frood.log` instead. | `frood.py` uses `FileHandler("frood.log")`. Old `agent42.log` left in place (not deleted). No special action needed. |

**Migration concern — existing CLAUDE.md files with old markers:** If the project's own `CLAUDE.md` (or any user project) already has `<!-- BEGIN AGENT42 MEMORY -->` markers injected by the current `generate_claude_md_section()`, the renamed code will not find them and will append a second block. This affects the agent42 project's own CLAUDE.md if it was ever generated by setup_helpers. The planner should include a task to check for and update existing marker strings in `CLAUDE.md` as part of the PY-04 work.

---

## Common Pitfalls

### Pitfall 1: config.py defaults vs env vars confusion

**What goes wrong:** Conflating the `AGENT42_*` env var renames (D-02, 11 vars in hooks/tools) with the `.agent42/` path defaults in `config.py` (DATA-01, ~30 occurrences). They are separate changes with different mechanisms.

**Why it happens:** `config.py` `from_env()` uses generic env var names like `MEMORY_DIR`, `APPROVAL_LOG_PATH` — not `AGENT42_*` names. The `.agent42/` string appears in the *default values* of those generic env var reads.

**How to avoid:** ENTRY-03/ENTRY-04 work is confined to 15 non-config files listed above. DATA-01/DATA-03 work is in `config.py` defaults (and other files that hardcode `.agent42/` paths).

### Pitfall 2: Qdrant collection names in hooks — don't rename

**What goes wrong:** While renaming `[agent42-memory]` print prefixes and `.agent42/` path references in `memory-recall.py`, accidentally also renaming the collection name strings `"agent42_memory"` and `"agent42_history"` (lines 406, 485, 502).

**Why it happens:** These strings look like candidates for renaming since they contain `agent42`.

**How to avoid:** The Qdrant collection rename is Phase 55 scope. In this phase, leave `"agent42_memory"` and `"agent42_history"` collection name strings unchanged. Only change env var reads, `.agent42/` path strings, and print prefixes in those hook files.

### Pitfall 3: test-validator.py GLOBAL_IMPACT_FILES needs updating

**What goes wrong:** After renaming `agent42.py` to a shim, the `test-validator.py` hook still triggers a full test run when `agent42.py` changes (correct — the shim is a global impact file), but `frood.py` is the new canonical entry and is NOT in the set, so changes to it won't trigger the full suite.

**How to avoid:** Add `"frood.py"` to `GLOBAL_IMPACT_FILES` in `.claude/hooks/test-validator.py`.

### Pitfall 4: setup_helpers.py CLAUDE_MD_TEMPLATE references agent42_memory tool name

**What goes wrong:** After renaming `SERVER_NAME = "agent42"` → `SERVER_NAME = "frood"` in `mcp_server.py`, the MCP tool that Claude Code invokes becomes `frood_memory` instead of `agent42_memory`. But the CLAUDE_MD_TEMPLATE in setup_helpers.py still says `agent42_memory(action=...)` in its instruction text.

**How to avoid:** When updating the marker constants in setup_helpers.py (PY-04), also update the `agent42_memory` tool name references within `CLAUDE_MD_TEMPLATE` to `frood_memory`. Also update `test_setup.py` assertions that check for `"agent42_memory"` in the template content.

### Pitfall 5: `.mcp.available.json` and `.mcp.json` not covered by pytest

**What goes wrong:** The env var `AGENT42_WORKSPACE` in `.mcp.available.json` and `.mcp.json` is not tested by the Python test suite. After renaming, the MCP server won't receive the workspace correctly until these files are updated.

**How to avoid:** Treat `.mcp.available.json` as in-scope for the env var rename. Update both the env key and the MCP server entry key names.

### Pitfall 6: `memory-recall.py` variable name `agent42_root` (local variable)

**What goes wrong:** `memory-recall.py` has a local variable named `agent42_root` (line 752), a function `try_semantic_search(memory_dir, prompt, agent42_root)` (line 300), and a function `try_agent42_api_search()` (line 350). These are internal variable/function names, not user-visible strings. They should be renamed for consistency but have no behavioral impact if missed.

**How to avoid:** Rename `agent42_root` local variable and `try_agent42_api_search()` function name to `frood_root` and `try_frood_api_search()` for completeness, but these are not blocking.

---

## Code Examples

### frood.py shim for agent42.py
```python
# agent42.py — deprecated entry point shim
# Source: D-08 decision
"""agent42.py — deprecated entry point. Use frood.py instead."""
import sys

print("[frood] agent42.py is deprecated — use frood.py", file=sys.stderr)

from frood import main

main()
```

### Data directory migration in frood.py main()
```python
# Source: D-05, D-06 decisions — placed in main() before Frood() constructor
import shutil
from pathlib import Path

def _migrate_data_dir() -> None:
    """Auto-migrate .agent42/ to .frood/ on first startup."""
    project_root = Path(__file__).parent
    old_dir = project_root / ".agent42"
    new_dir = project_root / ".frood"

    if old_dir.exists() and not new_dir.exists():
        shutil.move(str(old_dir), str(new_dir))
        print(
            "[frood] Data directory migrated: .agent42/ → .frood/",
            file=sys.stderr,
            flush=True,
        )
    elif old_dir.exists() and new_dir.exists():
        print(
            "[frood] WARNING: Both .agent42/ and .frood/ exist — using .frood/. "
            "Remove .agent42/ after verifying migration is complete.",
            file=sys.stderr,
            flush=True,
        )
```

### Logger name pattern (representative)
```python
# Before (in any of the ~107 files):
logger = logging.getLogger("agent42.tools.memory")

# After:
logger = logging.getLogger("frood.tools.memory")
```

### CLAUDE.md marker constants in setup_helpers.py
```python
# Before:
_CLAUDE_MD_BEGIN = "<!-- BEGIN AGENT42 MEMORY -->"
_CLAUDE_MD_END = "<!-- END AGENT42 MEMORY -->"

# After:
_CLAUDE_MD_BEGIN = "<!-- BEGIN FROOD MEMORY -->"
_CLAUDE_MD_END = "<!-- END FROOD MEMORY -->"
```

### mcp_server.py root variable
```python
# Before:
_AGENT42_ROOT = Path(__file__).resolve().parent
if str(_AGENT42_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENT42_ROOT))

# After:
_FROOD_ROOT = Path(__file__).resolve().parent
if str(_FROOD_ROOT) not in sys.path:
    sys.path.insert(0, str(_FROOD_ROOT))
```

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python venv | All phase work | Yes | .venv present | — |
| `shutil` | DATA-02 migration | Yes | stdlib | — |
| `pytest` | Test validation | Yes | 2059 tests collected | — |
| `.agent42/` data dir | DATA-02 migration trigger | Yes | Exists locally | No migration needed if not present |
| VPS SSH access | D-03 .env update | Yes (ssh alias `agent42-prod` configured) | — | — |

**Missing dependencies with no fallback:** None.

**Missing dependencies with fallback:** None.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest |
| Config file | `pytest.ini` or inferred |
| Quick run command | `python -m pytest tests/test_memory_hooks.py tests/test_proactive_injection.py tests/test_setup.py -x -q` |
| Full suite command | `python -m pytest tests/ -x -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| ENTRY-01 | `python frood.py` starts app | smoke | Manual: `python frood.py --no-dashboard &` then kill | Manual only |
| ENTRY-02 | `python agent42.py` prints deprecation warning + delegates | unit | `python agent42.py --no-dashboard 2>&1` contains `[frood]` | Manual only |
| ENTRY-03 | FROOD_* env vars configure app | unit | `python -m pytest tests/test_config.py -x -q` | Yes |
| ENTRY-04 | config.py reads FROOD_* | unit | `python -m pytest tests/test_config.py -x -q` | Yes |
| ENTRY-05 | `.env.example` has FROOD_* | smoke | `grep FROOD .env.example` | Manual check |
| DATA-01 | Default data dir is `.frood/` | unit | `python -m pytest tests/test_config.py -x -q` | Yes |
| DATA-02 | Auto-migration on startup | unit | `python -m pytest tests/test_frood_migration.py -x -q` | No — Wave 0 gap |
| DATA-03 | No `.agent42/` references in code | static | `grep -r '\.agent42' --include="*.py" .` returns only comments | Manual grep |
| PY-01 | No `agent42.*` logger names | static | `grep -r 'getLogger("agent42' --include="*.py" .` returns empty | Manual grep |
| PY-02 | No `[agent42-*]` print prefixes | auto | `python -m pytest tests/test_memory_hooks.py tests/test_proactive_injection.py -x -q` | Yes (after test update) |
| PY-03 | MCP server uses frood references | unit | `python -m pytest tests/test_mcp_server.py -x -q` | Yes |
| PY-04 | CLAUDE.md markers use FROOD_MEMORY | unit | `python -m pytest tests/test_setup.py -x -q` | Yes (after test update) |

### Wave 0 Gaps

- [ ] `tests/test_frood_migration.py` — covers DATA-02 (auto-migration: `.agent42/` → `.frood/` when only old exists; both-exist warning case; neither-exists no-op case)

*(All other test files exist — the test assertions just need updating to match new `frood` strings)*

### Sampling Rate

- **Per task commit:** `python -m pytest tests/test_memory_hooks.py tests/test_proactive_injection.py tests/test_setup.py -x -q`
- **Per wave merge:** `python -m pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

---

## Blast Radius Summary (verified)

| Change Type | Files | How to Find | Occurrences |
|-------------|-------|-------------|-------------|
| `getLogger("agent42.*")` → `getLogger("frood.*")` | 107 | `grep -rn 'getLogger("agent42' --include="*.py"` | 107 |
| `AGENT42_*` env var reads → `FROOD_*` | ~15 | `grep -rn 'AGENT42_' --include="*.py"` | ~35 across 15 files |
| `.agent42/` path defaults → `.frood/` | 48 | `grep -rn '\.agent42' --include="*.py"` | ~178 across 48 files (many in hooks + config) |
| `[agent42-*]` print prefixes → `[frood-*]` | 6 | `grep -rn '\[agent42-' --include="*.py"` | 18 |
| `_AGENT42_ROOT` variable | 1 | `mcp_server.py` | 3 (decl + 2 uses) |
| Entry point: new file + shim | 2 | `agent42.py` → `frood.py` + shim | — |
| CLAUDE.md markers | 1 | `scripts/setup_helpers.py` | 4 string constants + template body |
| Test assertions | ~5 | `test_memory_hooks.py`, `test_proactive_injection.py`, `test_setup.py`, `test_portability.py`, `test_mcp_server.py` | ~20 assertion strings |

**Out-of-scope strings that look like candidates but are NOT this phase:**
- `"agent42_memory"` / `"agent42_history"` Qdrant collection name strings in hooks → Phase 55
- `agent42` in `.mcp.available.json` server key names → in scope (ENTRY-03 / env var rename)
- `agent42` in `agent42-service.xml` service ID/name → cosmetic, shim keeps it working
- `"agent42"` in `SERVER_NAME` in `mcp_server.py` → in scope (PY-03)

---

## Sources

### Primary (HIGH confidence)

- Direct source inspection: `agent42.py`, `core/config.py`, `mcp_server.py`, `scripts/setup_helpers.py`, all hook files — read verbatim
- Live filesystem: `.agent42/` directory structure, `.mcp.available.json`, `.mcp.json` — inspected directly
- Test run: `pytest tests/test_memory_hooks.py tests/test_proactive_injection.py tests/test_setup.py` — 112 passed, 2 skipped (baseline confirmed)
- Grep counts: all blast-radius numbers derived from direct grep runs

### Secondary (MEDIUM confidence)

- None required — this is an internal rename with no external library dependencies

### Tertiary (LOW confidence)

- None

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new dependencies, all stdlib
- Architecture: HIGH — verified by reading all canonical files listed in CONTEXT.md
- Blast radius: HIGH — all counts from live grep runs
- Pitfalls: HIGH — derived from actual code structure found

**Research date:** 2026-04-07
**Valid until:** Stable indefinitely (internal rename — no external dependencies)
