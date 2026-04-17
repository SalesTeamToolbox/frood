---
phase: 01-cross-cli-setup-core
plan: 03
subsystem: cross-cli-setup
tags: [adapters, safety, backup, wire, unwire, idempotent]
requires:
  - 01-01 (core/user_frood_dir.py — load_manifest)
provides:
  - CliAdapter ABC
  - ClaudeCodeSetup
  - OpenCodeSetup
  - detect_all()
  - wire_cli()
  - unwire_cli()
  - BACKUP_SUFFIX_FMT
  - MARKER_BEGIN / MARKER_END
  - FROOD_MCP_ENTRY_CLAUDE / FROOD_MCP_ENTRY_OPENCODE
affects:
  - "Plan 01-04 (frood cli-setup CLI subcommand) consumes detect_all/wire_cli/unwire_cli"
  - "Plan 01-05 (dashboard /api/cli-setup/*) consumes the same dispatch helpers"
tech-stack:
  added: []
  patterns:
    - "Sync bootstrap I/O with atomic tempfile + os.replace (precedent: core/portability.py)"
    - "Backup-restore for byte-identical round-trip (SAFE-02)"
    - "Marker-delimited block in markdown for clean append/remove"
    - "ABC + concrete adapters so dispatch helpers stay uniform across CLIs"
key-files:
  created:
    - core/cli_setup.py
    - tests/test_cli_setup_core.py
  modified: []
decisions:
  - "Unwire restores from .bak-<ts> sibling rather than logical reverse-merge — guarantees byte-identical round-trip even for JSON key-order / whitespace quirks."
  - "OpenCode default project discovery = shallow scan of cwd.parent for sibling dirs containing opencode.json (only when manifest says 'auto' or projects list absent)."
  - "AGENTS.md wire uses HTML-comment markers <!-- frood:cli-setup:begin/end -->; unwire preserves user content appended AFTER the end marker via extract-and-reappend pattern."
  - "First-write-only backup semantics: any pre-existing .bak-* sibling is reused (returned to caller) — no duplicate backups across repeated wires."
  - "Atomic write via tempfile + os.replace in the target dir so partial writes never leave a corrupted settings.json if the process dies mid-write."
  - "SAFE-03 respected by ONLY adding the 'frood' key on wire and ONLY removing it on unwire; restore-from-backup makes this mechanical rather than logical."
metrics:
  duration_minutes: 8
  completed_date: "2026-04-17"
  tasks_completed: 2
  files_created: 2
  files_modified: 0
requirements_satisfied:
  - SAFE-01
  - SAFE-02
  - SAFE-03
---

# Phase 01 Plan 03: Cross-CLI Setup Core Adapters Summary

**One-liner:** Built `core/cli_setup.py` — `CliAdapter` ABC plus `ClaudeCodeSetup` and `OpenCodeSetup` concrete adapters that wire/unwire Frood into each CLI's native config with a timestamped-backup safety harness; unwire restores from the backup sibling so the round-trip is byte-identical for both `~/.claude/settings.json` and per-project `opencode.json` + `AGENTS.md`.

## What Was Built

### `core/cli_setup.py` (new)

Public surface:

| Symbol | Kind | Purpose |
| --- | --- | --- |
| `CliAdapter` | ABC | Common contract — `detect() → dict`, `wire() → dict`, `unwire() → dict` |
| `ClaudeCodeSetup(root=None)` | Class | Targets `<root or $HOME>/.claude/settings.json` |
| `OpenCodeSetup(project_paths=None, manifest=None)` | Class | Targets each project's `opencode.json` + `AGENTS.md` |
| `detect_all(manifest=None) → dict` | Function | Aggregated state for both CLIs, annotated with `enabled` flag from manifest |
| `wire_cli(cli, manifest=None) → dict` | Function | Dispatch by CLI name |
| `unwire_cli(cli, manifest=None) → dict` | Function | Reverse dispatch |
| `BACKUP_SUFFIX_FMT` | `str` | `"%Y%m%dT%H%M%S"` — strftime for backup siblings |
| `MARKER_BEGIN` / `MARKER_END` | `str` | HTML-comment delimiters for AGENTS.md block |
| `AGENTS_NOTE_BODY` | `str` | Locked text injected between markers |
| `FROOD_MCP_ENTRY_CLAUDE` | `dict` | `{"command": sys.executable, "args": ["-m","mcp_server"], "env": {}}` |
| `FROOD_MCP_ENTRY_OPENCODE` | `dict` | `{"type": "local", "command": [sys.executable, "-m", "mcp_server"], "enabled": True}` |

### `detect_all()` output shape (locked for Plan 04 + 05 consumption)

```jsonc
{
  "claude-code": {
    "installed": true,      // .claude/ dir exists
    "wired":     false,     // settings.mcpServers.frood absent
    "settings_path": "C:\\Users\\rickw\\.claude\\settings.json",
    "enabled":   true       // from manifest.clis['claude-code'].enabled
  },
  "opencode": {
    "installed": true,      // any project has opencode.json
    "wired":     false,     // no project has mcp.frood
    "projects": [
      { "path": "<abs>", "installed": true, "wired": false }
    ],
    "enabled":   true
  }
}
```

### Backup restoration strategy (key decision)

Unwire uses the following algorithm per target file:

1. Look for a sibling matching `<target>.bak-*`.
2. If found → **copy the backup onto the target, then delete the backup**. This guarantees byte-for-byte restoration (JSON key order, whitespace, final newline all preserved).
3. If not found → fall back to logical in-place removal of just the `frood` key (for opencode.json / settings.json) or the marker-delimited block (for AGENTS.md). This path is exercised only when:
   - The user deleted the backup manually, or
   - `wire` was called into an absent file (nothing existed to back up).

For AGENTS.md specifically, the restore path also rescues any content the user appended after our end marker between wire and unwire: we extract everything after `MARKER_END` before restoring, then re-append it to the restored file. This means a user who edits AGENTS.md between wire/unwire doesn't lose their work, even though the restore is otherwise byte-identical.

### `tests/test_cli_setup_core.py` (new, 13 tests)

- 5 Claude Code safety tests: first-write backup, other-keys preservation, idempotent wire, byte-identical round-trip, other MCP servers survive wire→unwire
- 1 Claude Code detect test
- 7 OpenCode tests: mcp merge, AGENTS.md block append, AGENTS.md creation when absent, marker-only removal on unwire, byte-identical round-trip for both files, detect, backup-per-target

## Decisions Made

### D-01 — Restore-from-backup is the unwire primary path

Rejected logical reverse-merge. JSON serialization is not deterministic across Python versions / dict ordering edge cases (trailing whitespace, missing final newline). A file copy is mechanically byte-identical and makes SAFE-02 trivially true. The fallback in-place-removal path exists only for degraded cases and is documented.

### D-02 — OpenCode default discovery = shallow scan of `cwd.parent`

Per Claude's Discretion in the plan. When the manifest says `projects: "auto"` (or is missing), we list siblings of `cwd.parent` that contain an `opencode.json`. This matches the typical developer layout (all projects under a single parent dir like `~/projects/`). Users with non-standard layouts configure `~/.frood/cli.yaml` with an explicit list — documented in code.

### D-03 — HTML-comment markers for AGENTS.md

Chosen over regex markers (`<!-- frood:cli-setup:begin -->` + `<!-- frood:cli-setup:end -->`) so the block is invisible in rendered markdown but parseable in source. Unwire deletes ONLY the inclusive marker range; user content above or below is preserved.

### D-04 — `sys.executable` in MCP command entries

Rather than `"python"`, we pin the interpreter to the one that installed Frood. This avoids breakage when the user has multiple venvs / conda envs / python3 vs python naming on PATH. The tradeoff: if the user relocates the venv, they must re-run `frood cli-setup` to refresh the pinned path.

### D-05 — Atomic writes via tempfile + os.replace

Mirrors `core/portability.py`'s pattern. Even on a mid-write crash, the target file is either the old version or the new version — never a half-written mess.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `cc_root_bare` fixture collided with `cc_root_with_settings`**

- **Found during:** First test run — `test_claude_code_detect_reports_state` errored at fixture setup
- **Issue:** Both fixtures tried to create `<tmp_path>/.claude/` directly on the same `tmp_path`, triggering `FileExistsError`
- **Fix:** Changed `cc_root_bare` to use a `tmp_path/bare-home/` subdirectory so both fixtures can coexist in a single test
- **Files modified:** `tests/test_cli_setup_core.py`
- **Commit:** folded into `96c9edb`

No other deviations — the plan executed cleanly, all other tests passed on first `pytest` invocation.

## Verification Results

| Command | Result |
| --- | --- |
| `.venv/Scripts/python.exe -m pytest tests/test_cli_setup_core.py -v` | 13 passed in 0.35s |
| `.venv/Scripts/python.exe -m ruff check core/cli_setup.py tests/test_cli_setup_core.py` | All checks passed |
| `.venv/Scripts/python.exe -c "from core.cli_setup import ...; print('ok')"` | `ok` |
| Real-machine `detect_all()` smoke | Returns expected state (Claude Code installed not-wired; Frood's own opencode.json detected as wired) — read-only, no writes to user config |

## Success Criteria — All Met

- **SAFE-01**: First wire creates `<target>.bak-<ts>`; second wire reuses the existing backup, no duplicates. Covered by `test_claude_code_wire_creates_backup_before_first_write` and `test_opencode_wire_backup_created_for_both_targets`.
- **SAFE-02**: wire → unwire → bytes match original. Covered by `test_claude_code_unwire_byte_identical_roundtrip` and `test_opencode_unwire_byte_identical_roundtrip`.
- **SAFE-03**: Other MCP servers, provider blocks, user-written AGENTS.md content all survive. Covered by `test_claude_code_wire_preserves_other_keys`, `test_unwire_does_not_disable_other_mcp_servers`, `test_opencode_wire_merges_into_mcp_key`, `test_opencode_unwire_removes_marker_block_only`.
- **Downstream consumability**: `detect_all`, `wire_cli`, `unwire_cli` are the sole entry points Plan 04 and Plan 05 need. The output shape is locked and documented above.

## Commits

| Task | Type | Hash | Message |
| --- | --- | --- | --- |
| 1 | test | `48789e7` | `test(01-03): add failing safety tests for cli_setup adapters` |
| 2 | feat | `96c9edb` | `feat(01-03): implement ClaudeCodeSetup + OpenCodeSetup adapters` |

## Known Stubs

None — this plan delivers the full adapter implementation. All entry points are wired, every safety test is exercised end-to-end, and the real-machine smoke confirms both adapters produce realistic state without writing anything.

## Self-Check: PASSED

- `core/cli_setup.py` — FOUND (710 lines after formatter)
- `tests/test_cli_setup_core.py` — FOUND (331 lines after formatter, 13 tests)
- Commit `48789e7` — FOUND in git log (`test(01-03)...`)
- Commit `96c9edb` — FOUND in git log (`feat(01-03)...`)
- All 13 tests passing; ruff clean; all 11 public symbols importable; `detect_all()` smoke-passed against the real machine in read-only mode
