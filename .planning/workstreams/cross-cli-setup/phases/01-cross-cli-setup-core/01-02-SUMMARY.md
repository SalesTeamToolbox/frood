---
phase: 01-cross-cli-setup-core
plan: 02
subsystem: cross-cli-setup
tags: [mcp, bridge, warehouse, skills, cross-cli]
requires:
  - user_frood_dir()
  - load_manifest()
  - DEFAULT_MANIFEST
provides:
  - SkillBridgeTool (MCP tool `frood_skill`)
  - `frood_skill(action="list")` → five-slice inventory
  - `frood_skill(action="load", name=...)` → markdown body for any slice
affects:
  - "Downstream plans 01-04..01-06 can assume `frood_skill` is live"
  - "OpenCode users can reach warehouse + personas + Frood skills via MCP"
tech-stack:
  added: []
  patterns:
    - "MCP prefixing via `to_mcp_schema` — tool named 'skill', MCP clients see 'frood_skill'"
    - "Async execute wrapper + sync discovery/load workers via asyncio.to_thread"
    - "Graceful-degradation on every filesystem read (missing dir → empty slice)"
    - "SkillLoader reuse (no re-parsing SKILL.md frontmatter)"
key-files:
  created:
    - tools/skill_bridge.py
    - tests/test_skill_bridge.py
  modified:
    - mcp_server.py
decisions:
  - "Tool registry name is 'skill'; the default MCP prefix 'frood_' produces the external name 'frood_skill' (plan note 4 + MCP-01 lock)."
  - "Discovery/load run in threads (asyncio.to_thread) — keeps the tool compatible with CLAUDE.md async-I/O rule while letting pathlib stay synchronous."
  - "Lookup order for `load` mirrors `list`: warehouse skills → commands → agents → personas → frood_skills. First match wins."
  - "Path-traversal guard rejects names containing '/', '\\', or '..' — warehouse identifiers are flat."
metrics:
  duration_minutes: 5
  completed_date: "2026-04-17"
  tasks_completed: 2
  files_created: 2
  files_modified: 1
requirements_satisfied:
  - MCP-01
  - MCP-02
  - MCP-03
  - MCP-04
  - MCP-05
---

# Phase 01 Plan 02: `frood_skill` MCP Bridge Summary

**One-liner:** Added `tools/skill_bridge.py` exposing the `frood_skill` MCP tool — a single on-demand bridge that lets every MCP-capable CLI reach Claude Code's skills/commands/agents warehouse plus Frood's built-in personas and skills, gated by `~/.frood/cli.yaml` warehouse flags and graceful on missing warehouse paths.

## What Was Built

### `tools/skill_bridge.py` (new, ~300 lines)

Public surface:

| Element | Purpose |
| --- | --- |
| `SkillBridgeTool` | `Tool` ABC implementation; `name = "skill"`, external MCP name `frood_skill` |
| `action="list"` | Returns JSON inventory: `{skills, commands, agents, personas, frood_skills}` |
| `action="load" name=X` | Returns `{name, source, body}` — first match across all five slices |

Implementation characteristics:

- **Async-correct.** `execute()` is `async def` per CLAUDE.md; all filesystem work runs off the event loop via `asyncio.to_thread(_discover_all, flags)` / `asyncio.to_thread(_load_one, name, flags)`.
- **Manifest-gated.** `_load_flags()` reads `~/.frood/cli.yaml` via `core.user_frood_dir.load_manifest` and extracts `warehouse.include_claude_warehouse` + `warehouse.include_frood_builtins`. Any failure falls back to both flags `True` — the tool never becomes unavailable due to a missing/broken manifest.
- **Graceful-absent.** Every `_discover_*` function is wrapped in `try: ... except Exception: return []`. Missing `~/.claude/skills-warehouse/`, `commands-warehouse/`, or `agents-warehouse/` directory → empty slice for that category, no exception raised. Verified by `test_missing_warehouse_returns_empty_slices`.
- **Path-traversal safe.** `load` rejects any `name` containing `/`, `\`, or `..` with `error="invalid name"` before touching the filesystem.
- **SkillLoader reuse.** `_discover_frood_skills` / `_load_one` import `skills.loader.SkillLoader` and mirror the exact directory list used by `mcp_server._load_skills()` — no re-parsing SKILL.md frontmatter ourselves, no import cycle with mcp_server.

### `tests/test_skill_bridge.py` (new, 9 tests)

All tests redirect `Path.home()` to `tmp_path` via `monkeypatch.setattr(Path, "home", classmethod(...))` — identical pattern to Plan 01's tests. Coverage:

| Test | Behaviour verified |
| --- | --- |
| `test_list_returns_five_keys` | `list` payload has skills, commands, agents, personas, frood_skills (all lists) |
| `test_missing_warehouse_returns_empty_slices` | No `~/.claude/*-warehouse/` dirs → warehouse slices empty (MCP-05) |
| `test_manifest_disables_claude_warehouse` | `include_claude_warehouse=False` hides skills/commands/agents even when fixtures exist (MCP-04) |
| `test_manifest_disables_builtins` | `include_frood_builtins=False` hides personas + frood_skills (MCP-04) |
| `test_load_warehouse_skill` | `load name=demo` returns body containing `"hello world"` (MCP-03) |
| `test_load_not_found_returns_error` | Unknown name → `ToolResult(success=False, error="not found: ...")` |
| `test_load_rejects_path_traversal` | `"../../etc/passwd"`, `"foo/bar"`, `"foo\\bar"` all rejected as `"invalid name"` |
| `test_load_without_name_returns_error` | Missing `name` kwarg → clean error, no crash |
| `test_registered_in_mcp_server` | `_build_registry()` contains a tool named `"skill"` → MCP exposes `frood_skill` (MCP-01) |

### `mcp_server.py` (modified — single-line addition)

Added `("tools.skill_bridge", "SkillBridgeTool")` inside the Group A (no-arg tools) for-loop in `_build_registry`, positioned immediately after `PersonaTool` so the two related on-demand surfaces cluster visually. Diff is 2 lines (one comma, one new tuple).

## Decisions Made

### Tool registry name is `"skill"` (not `"skill_bridge"`)

The default MCP prefix applied by `Tool.to_mcp_schema()` is `"frood_"`. Per CONTEXT.md D-02 and the `MCP-01` requirement lock, the external tool name MUST be `frood_skill`. Setting `self.name = "skill"` is the only way to produce that external name without touching the prefix machinery. The plan's frontmatter notes this explicitly; followed exactly.

### Discovery + load run on a thread executor

CLAUDE.md mandates async I/O in tools. Warehouse discovery is a pathlib walk — synchronous by nature, and rewriting it with aiofiles would buy nothing (directory iteration has no async pathlib story). The compromise: `execute()` is `async`, but each heavy worker (`_discover_all`, `_load_one`) runs inside `asyncio.to_thread(...)` so the event loop stays free. This matches the pattern used by several existing tools (`repo_map`, `code_intel`) that also do synchronous filesystem work.

### Lookup order for `load` mirrors `list`

Warehouse skills → commands → agents → personas → frood_skills. First match wins. If there's ever a name collision across slices, the warehouse value takes precedence (which is what users editing `~/.claude/*-warehouse/` would expect).

### Path-traversal guard before filesystem touch

`name` that contains `/`, `\`, or `..` is rejected with `error="invalid name"` before any `Path(...)` construction. Warehouse identifiers are flat (e.g., `"demo-cmd"`, `"use"`, `"deploy"`) — there is no legitimate use case for a path separator in a skill name.

### SkillLoader reuse — no re-parsing SKILL.md

The plan explicitly called out "reuse SkillLoader from mcp_server.py; don't re-parse SKILL.md." I solved the import cycle concern by not importing from `mcp_server` at all. Instead `tools/skill_bridge.py` imports `skills.loader.SkillLoader` directly and replicates `mcp_server._load_skills`'s directory list (`skills/builtins`, `skills/workspace`, `<workspace>/.claude/skills`, `<workspace>/custom_skills`). If mcp_server later changes that list, this needs updating — noted as a known coupling point.

## Deviations from Plan

None — plan executed exactly as written. No deviation rules triggered.

## Verification Results

| Command | Result |
| --- | --- |
| `python -m pytest tests/test_skill_bridge.py -v` | 9 passed in 1.71s |
| `python -c "from mcp_server import _build_registry; names = [t['name'] for t in _build_registry().list_tools()]; assert 'skill' in names; print('OK: frood_skill registered')"` | `OK: frood_skill registered` |
| `python -c "import asyncio; from tools.skill_bridge import SkillBridgeTool; r = asyncio.run(SkillBridgeTool().execute(action='list')); print(r.success, r.output[:200])"` | `True` + a JSON snippet with five categories populated from the real user's warehouse |
| `ruff check tools/skill_bridge.py tests/test_skill_bridge.py` | All checks passed |

Note: `ruff check mcp_server.py` surfaces three pre-existing warnings (F841 on `command_filter` line 98, F821 on the `SkillLoader` forward-ref line 321, F841 on `settings` line 590). None of them are caused by this plan's changes and per GSD scope boundary rule they are out-of-scope.

## Success Criteria — All Met

- **MCP-01** — `SkillBridgeTool` is registered in `_build_registry` (test_registered_in_mcp_server)
- **MCP-02** — `list` returns inventory across skills/commands/agents/personas/frood_skills (test_list_returns_five_keys + live smoke check)
- **MCP-03** — `load` returns the full markdown body (test_load_warehouse_skill)
- **MCP-04** — Both manifest flags independently gate their slices (test_manifest_disables_claude_warehouse, test_manifest_disables_builtins)
- **MCP-05** — Missing `~/.claude/*-warehouse/` paths → empty slice, no crash (test_missing_warehouse_returns_empty_slices)

## Commits

| Task | Type | Hash | Message |
| --- | --- | --- | --- |
| TDD RED | test | `d0a071a` | `test(01-02): add failing tests for frood_skill MCP bridge` |
| Task 1 GREEN | feat | `e9a42b9` | `feat(01-02): implement SkillBridgeTool (frood_skill MCP bridge)` |
| Task 2 | feat | `a4248c6` | `feat(01-02): register SkillBridgeTool in MCP _build_registry` |

## Known Stubs

None — this plan delivers a live, tested tool that is fully wired into the MCP registry. There are no placeholder returns, no "coming soon" strings, no unwired imports. Every slice of the inventory is populated on the live machine (verified by the smoke command printing real warehouse entries).

## Known Couplings

- `_discover_frood_skills` / `_load_one` duplicate the skill-directory list used by `mcp_server._load_skills()` (skills/builtins, skills/workspace, workspace/.claude/skills, workspace/custom_skills). If mcp_server changes that list, `tools/skill_bridge.py` needs the same edit. Consolidation candidate for a future plan.

## Self-Check: PASSED

- `tools/skill_bridge.py` — FOUND
- `tests/test_skill_bridge.py` — FOUND
- `mcp_server.py` — registration line present
- Commit `d0a071a` — FOUND in git log
- Commit `e9a42b9` — FOUND in git log
- Commit `a4248c6` — FOUND in git log
- All 9 tests passing; lint clean on new files; plan verify command succeeds
