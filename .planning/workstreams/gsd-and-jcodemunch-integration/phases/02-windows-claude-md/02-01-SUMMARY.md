---
phase: 02-windows-claude-md
plan: "01"
subsystem: setup
tags: [windows, platform-detection, venv, gitattributes, shell]
dependency_graph:
  requires: [01-03-PLAN.md]
  provides: [windows-git-bash-setup, platform-aware-venv-paths, lf-line-endings]
  affects: [setup.sh, scripts/setup_helpers.py, .gitattributes, tests/test_setup.py]
tech_stack:
  added: []
  patterns: [sys.platform-win32-detection, MINGW-MSYS-CYGWIN-uname-case]
key_files:
  created: [.gitattributes]
  modified: [setup.sh, scripts/setup_helpers.py, tests/test_setup.py]
decisions:
  - "Use sys.platform == 'win32' (not os.name == 'nt') per plan decision D-02 for explicit Windows detection"
  - "Use OS_TYPE (not OS) as uname variable name to avoid collision with create-shortcut subcommand's local OS variable"
  - "The python3 in PYTHON_CMD='python3' assignment is acceptable — it is a string value, not an executable call"
  - "Existing test helpers updated to create platform-correct venv paths so pre-existing tests remain green"
metrics:
  duration: "~15 min"
  completed: "2026-03-25"
  tasks_completed: 2
  files_modified: 4
---

# Phase 02 Plan 01: Windows Git Bash Compatibility Summary

**One-liner:** Platform-aware venv paths via `_venv_python()` helper + `OS_TYPE` detection in setup.sh + `.gitattributes` LF enforcement for Windows Git Bash compatibility.

## What Was Built

### `scripts/setup_helpers.py` — `_venv_python()` helper

Added a new `_venv_python(project_dir: str) -> str` function using `sys.platform` to return the correct Python executable path:

- **Windows** (`sys.platform == "win32"`): `.venv/Scripts/python.exe`
- **Linux/macOS**: `.venv/bin/python`

Both `generate_mcp_config()` and `check_health()` now call `_venv_python(project_dir)` instead of hardcoding `.venv/bin/python`. The `import sys` was moved from the `__main__` block to top-level imports.

### `setup.sh` — Platform detection block

A `OS_TYPE="$(uname -s)"` block was inserted immediately after the logging function definitions (before any subcommands), setting:

- `VENV_ACTIVATE=".venv/Scripts/activate"` and `PYTHON_CMD="python"` for Windows (`MINGW*|MSYS*|CYGWIN*`)
- `VENV_ACTIVATE=".venv/bin/activate"` and `PYTHON_CMD="python3"` for Linux/macOS

All local `python3` calls in setup.sh replaced with `$PYTHON_CMD`:
- Python version check block
- Venv creation: `$PYTHON_CMD -m venv .venv`
- Venv activation: `source "$VENV_ACTIVATE"`
- MCP config, hook registration, CLAUDE.md generation, jcodemunch indexing, health check
- Icon generation in create-shortcut (both calls)
- sync-auth local JSON parsing

Final "Done" message updated to reference `$VENV_ACTIVATE`.

### `.gitattributes` — LF line ending enforcement

Created at repo root enforcing LF endings for `.sh`, `.py`, and `.bash` files via `eol=lf` rules. Prevents CRLF-induced bash failures when checking out on Windows.

### `tests/test_setup.py` — `TestWindowsCompat` class (5 tests)

Added `TestWindowsCompat` with:
1. `test_venv_python_returns_scripts_on_win32` — mock sys.platform=win32, assert Scripts/python.exe
2. `test_venv_python_returns_bin_on_linux` — mock sys.platform=linux, assert bin/python
3. `test_mcp_config_uses_venv_python_win32` — win32 mock, verify .mcp.json command has Scripts/python.exe
4. `test_mcp_config_uses_venv_python_linux` — linux mock, verify .mcp.json has .venv/bin/python
5. `test_health_check_uses_platform_venv_path` — win32 mock, verify subprocess.run gets Scripts/python.exe

**Deviation:** Updated `_make_fake_venv()` helper and one test assertion (`os.path.basename == "python"`) to be platform-aware — they were broken by the correct implementation since they assumed Linux paths. This is a Rule 1 fix (existing tests needed to reflect new correct behavior).

## Commits

| Hash | Type | Description |
|------|------|-------------|
| `12197d2` | test | add failing TestWindowsCompat tests (RED phase) |
| `1b59e9d` | feat | add _venv_python() helper + update both callers |
| `713296a` | feat | setup.sh platform detection + .gitattributes |

## Verification Results

```
python -m pytest tests/test_setup.py -x -q   → 40 passed, 2 skipped
bash -n setup.sh                               → OK (no syntax errors)
test -f .gitattributes                         → EXISTS
grep -c "python3" setup.sh                     → 1 (only PYTHON_CMD="python3" assignment)
grep "_venv_python" scripts/setup_helpers.py   → defined + called in both generate_mcp_config() and check_health()
```

## Decisions Made

1. `sys.platform == "win32"` used (not `os.name == "nt"`) per plan decision D-02 — more explicit, catches WSL edge cases
2. `OS_TYPE` (not `OS`) as platform variable name — avoids collision with existing `OS` variable in create-shortcut subcommand
3. Remote SSH `python3` calls (inside `ssh "$ALIAS" "..."` strings) left as-is — they execute on the remote Linux server, not locally
4. `_make_fake_venv()` updated to create platform-correct venv path — ensures existing tests reflect the new platform-aware behavior

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Pre-existing test helpers assumed Linux-only venv paths**
- **Found during:** Task 1 GREEN phase
- **Issue:** `_make_fake_venv()` always created `.venv/bin/python`; `test_replaces_agent42_entry_with_invalid_path` asserted `os.path.basename(cmd) == "python"`. Both broke on Windows after implementing `_venv_python()`.
- **Fix:** Made `_make_fake_venv()` create the platform-correct path (`Scripts/python.exe` on win32, `bin/python` elsewhere); updated assertion to accept `"python"` or `"python.exe"`.
- **Files modified:** `tests/test_setup.py`
- **Commit:** `1b59e9d`

**2. [Rule 1 - Bug] test_mcp_config_uses_venv_python_linux assertion used forward-slash substring match**
- **Found during:** Task 1 GREEN phase
- **Issue:** `".venv/bin/python" in command` fails on Windows because `os.path.join` produces backslash paths.
- **Fix:** Normalize to forward slashes before comparison: `command.replace("\\", "/")`.
- **Files modified:** `tests/test_setup.py`
- **Commit:** `1b59e9d`

## Known Stubs

None — all functionality is wired. `setup.sh` on Windows will use `PYTHON_CMD="python"` and `VENV_ACTIVATE=".venv/Scripts/activate"`, and `setup_helpers.py` will generate `.venv/Scripts/python.exe` paths. No placeholder values remain.

## Self-Check: PASSED
