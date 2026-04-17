---
phase: 01-cross-cli-setup-core
plan: 04
subsystem: cross-cli-setup
tags: [cli, argparse, commands, handler, passthrough]
requires:
  - 01-01 (core/user_frood_dir.py — load_manifest)
  - 01-03 (core/cli_setup.py — detect_all, wire_cli, unwire_cli, OpenCodeSetup)
provides:
  - CliSetupCommandHandler
  - frood cli-setup argparse surface (detect | claude-code | opencode | all | unwire)
affects:
  - "Dashboard (Plan 01-05) consumes the same core dispatch helpers — behavior stays consistent across entry points"
  - "atexit message now goes to stderr so any future stdout-JSON subcommand is safe"
tech-stack:
  added: []
  patterns:
    - "CommandHandler ABC dispatch (precedent: BackupCommandHandler)"
    - "Argparse subparser-with-sub-subparser (standard stdlib pattern)"
    - "Local-import inside handler so monkeypatching core.cli_setup.* at module level works in tests"
key-files:
  created:
    - tests/test_cli_setup_command.py
  modified:
    - commands.py
    - frood.py
decisions:
  - "Handler is a pure forwarder — idempotency, backups, merge logic all live in core/cli_setup.py (Plan 03). This keeps the CLI and dashboard entry points behaviorally identical."
  - "Inside-function imports for core.cli_setup in the handler so tests can monkeypatch module attributes and have the handler pick up the mock at call time."
  - "Routed frood.py's atexit message to stderr so any future stdout-JSON subcommand (detect, claude-code, opencode, all, unwire) stays machine-parseable."
  - "Argparse enforces required 'cli' arg on unwire (exits 2 before the handler runs). The in-handler None check is defensive for programmatic callers constructing Namespace directly."
metrics:
  duration_minutes: 12
  completed_date: "2026-04-17"
  tasks_completed: 3
  files_created: 1
  files_modified: 2
requirements_satisfied:
  - CMD-01
  - CMD-02
  - CMD-03
  - CMD-04
  - CMD-05
  - CMD-06
  - CMD-07
  - CMD-08
  - CMD-09
---

# Phase 01 Plan 04: `frood cli-setup` CLI subcommand Summary

**One-liner:** Exposed `core/cli_setup.py` engines via a new `frood cli-setup` argparse subcommand (`detect | claude-code | opencode | all | unwire`) backed by `CliSetupCommandHandler` — a thin forwarder that prints each core call's return dict as JSON to stdout, with `atexit` messaging moved to stderr so the JSON contract stays clean.

## What Was Built

### `commands.py` (modified)

Added `CliSetupCommandHandler(CommandHandler)` at the end, preserving all three existing handlers unchanged. Surface:

| Sub-action      | Forwards to                                          | JSON stdout shape                                 |
| --------------- | ---------------------------------------------------- | ------------------------------------------------- |
| `detect`        | `core.cli_setup.detect_all()`                        | `{claude-code: {...}, opencode: {...}}` (Plan 03) |
| `claude-code`   | `core.cli_setup.wire_cli("claude-code")`             | `{changed: bool, backup: str \| null, ...}`       |
| `opencode [p]`  | `OpenCodeSetup(project_paths=[Path(p)]?).wire()`     | `{changed: bool, projects: [...]}`                |
| `all`           | iterates manifest.clis; `wire_cli(name, manifest)`   | `{cli_name: <wire_cli result>, ...}` (enabled only) |
| `unwire <cli>`  | `core.cli_setup.unwire_cli(cli)`                     | `{restored: bool, ...}`                           |

Exit-code contract:
- `0` — success
- `1` — core function raised (logged; stderr carries the message)
- `2` — missing or invalid sub-action / missing required arg

Local-import pattern inside `run()` is deliberate — tests monkeypatch `core.cli_setup.wire_cli` etc. at module level and the handler picks up the mock at call time.

### `frood.py` (modified)

Two changes:

1. Added `cli-setup` subparser block after `clone` (~lines 412-451) with five sub-subparsers:
   - `detect`, `claude-code`, `all` — no args
   - `opencode [path]` — optional positional
   - `unwire cli` — required positional (argparse enforces exit 2 automatically)
2. Extended `command_handlers` dict to include `"cli-setup": CliSetupCommandHandler()`.
3. Extended the `from commands import` block to include `CliSetupCommandHandler`.
4. **Deviation (Rule 2):** atexit handler's "Frood process exiting" print now goes to `sys.stderr` instead of the default stdout, so `cli-setup detect` (and any future JSON-emitting subcommand) yields clean stdout parseable by `json.loads()`.

All other subparsers, dashboard/sidecar args, and the default Frood startup logic (lines 424-459 of the original) are untouched.

### `tests/test_cli_setup_command.py` (new, 10 tests)

| # | Test                                         | Covers                                       |
| - | -------------------------------------------- | -------------------------------------------- |
| 1 | `test_handler_detect_prints_json`            | CMD-03: detect → valid JSON with two CLI keys |
| 2 | `test_handler_claude_code_calls_wire_cli`    | CMD-04: claude-code forwards to wire_cli     |
| 3 | `test_handler_opencode_accepts_path`         | CMD-05: opencode with path → `[Path(path)]` |
| 4 | `test_handler_opencode_without_path_passes_none` | CMD-05: opencode w/o path → manifest-driven  |
| 5 | `test_handler_all_only_wires_enabled`        | CMD-07: `all` honors manifest.enabled flags  |
| 6 | `test_handler_unwire_requires_cli_arg`       | CMD-08: unwire missing cli → exit 2          |
| 7 | `test_handler_unwire_forwards_to_core`       | CMD-08: unwire forwards cli name             |
| 8 | `test_handler_propagates_core_exception`     | Error path: core RuntimeError → exit 1       |
| 9 | `test_handler_missing_sub_action_exits_2`    | No action → exit 2, usage hint on stderr     |
| 10 | `test_cli_integration_detect`               | Subprocess: `python frood.py cli-setup detect` exits 0, stdout parses as JSON |

Test 10 is cross-platform (uses `subprocess.run` with the interpreter via `sys.executable` and no env tricks — it reads the real `~/.claude/settings.json` / `opencode.json` of the repo running the test but never mutates them, since `detect` is read-only).

## Decisions Made

### D-01 — Thin-forwarder handler

The handler does **zero** domain logic beyond JSON serialization and sub-action dispatch. Idempotency (CMD-09), backup semantics (SAFE-01/02/03), and merge rules all live in `core/cli_setup.py` (Plan 03). This means Plan 05's dashboard endpoints can call the same functions and get identical behavior — no drift between the two entry points.

### D-02 — Inside-function imports

`run()` imports `core.cli_setup` at call time. This makes `monkeypatch.setattr("core.cli_setup.wire_cli", fake)` actually replace what the handler sees, because the handler resolves the name through the module each call rather than binding a module-level alias. A plain `from core.cli_setup import wire_cli` at the top of `commands.py` would make the tests silently hit the real implementation.

### D-03 — atexit → stderr (Deviation Rule 2)

Before this plan, `frood.py`'s atexit callback printed to stdout. Any future machine-readable subcommand would emit `<valid JSON>\nFrood process exiting (atexit)\n` — unparseable as a single JSON document. Moving the message to stderr fixes the contract for:
- `cli-setup detect` — tested live
- `cli-setup claude-code`, `opencode`, `all`, `unwire` — same pattern
- Any future subcommand following the JSON-stdout convention

### D-04 — Argparse for unwire arg validation

`unwire_action.add_argument("cli", help=...)` makes `cli` **required**. Argparse exits 2 with a usage hint before the handler ever runs — even better than the in-handler `None` check. The in-handler check remains as defense-in-depth for programmatic callers who build a `Namespace(cli=None)` directly (and it's what test 6 covers).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical functionality] atexit print pollutes cli-setup JSON stdout**

- **Found during:** Task 2 verification — `frood cli-setup detect | json.loads` raised `JSONDecodeError: Extra data` because the atexit callback appends "Frood process exiting (atexit)" to stdout after the JSON blob.
- **Issue:** The plan's own verification step (`python frood.py cli-setup detect 2>&1 | python -c "import sys, json; json.loads(sys.stdin.read())"`) would fail without this fix, and so would Task 3's `test_cli_integration_detect`.
- **Fix:** `atexit.register(lambda: print("Frood process exiting (atexit)", file=sys.stderr, flush=True))` — one-line change in `frood.py`.
- **Files modified:** `frood.py`
- **Commit:** folded into `8624e68`

No other deviations. Task 1's handler stub landed as planned; Task 2's subparser shape matches the plan verbatim; Task 3's 7 required tests plus 3 added coverage tests (opencode-without-path, unwire-happy-path, missing-sub-action) all pass.

## Verification Results

| Command | Result |
| --- | --- |
| `python frood.py cli-setup --help` | Prints all five sub-actions |
| `python frood.py cli-setup detect` | Valid JSON with `claude-code` + `opencode` keys |
| `python frood.py cli-setup unwire` (no arg) | Exits 2 with argparse usage hint |
| `python -m pytest tests/test_cli_setup_command.py -v` | 10 passed in 1.83s |
| `ruff check commands.py frood.py tests/test_cli_setup_command.py` | All checks passed |
| `python -c "from commands import CliSetupCommandHandler, CommandHandler; assert issubclass(CliSetupCommandHandler, CommandHandler)"` | No output (assertion holds) |

## Success Criteria — All Met

- **CMD-01** — `cli-setup` argparse subparser registered (frood.py, verified via `--help`)
- **CMD-02** — `CliSetupCommandHandler` extends `CommandHandler` ABC (commands.py, verified via `issubclass` smoke)
- **CMD-03** — `detect` prints JSON (test 1 + test 10 subprocess)
- **CMD-04** — `claude-code` forwards to `wire_cli("claude-code")` (test 2)
- **CMD-05** — `opencode [<path>]` forwards to `OpenCodeSetup` with optional path (tests 3, 4)
- **CMD-06** — AGENTS.md note written by core adapter (Plan 03); handler invokes unchanged (covered by OpenCode test 3 / opencode action wiring)
- **CMD-07** — `all` iterates enabled CLIs in manifest (test 5)
- **CMD-08** — `unwire <cli>` forwards to `unwire_cli` (tests 6, 7)
- **CMD-09** — idempotency delegated to core (verified in Plan 03's safety tests)

## CLI Surface Notes (for Plan 05 dashboard + future docs)

- **No `--flags` beyond the plan minimum.** All sub-actions use positional args or none.
- **All JSON output uses `json.dumps(result, indent=2, default=str)`** — `default=str` means any non-JSON-native value (e.g., `Path`) renders as its string form. This matches what Plan 05 will serialize in `/api/cli-setup/detect`.
- **OS caveats:**
  - No OS-specific code in the handler. `Path(path_arg)` resolves via pathlib so forward/back slashes are both accepted.
  - `test_cli_integration_detect` runs cross-platform via `sys.executable` (no env-var gymnastics).
  - Real-machine smoke on Windows 11: `detect` correctly reports `claude-code.installed=true, wired=false` and Frood's own `opencode.json` as `opencode.wired=true` (because this repo is already wired from Plan 03 adapter smoke).

## Commits

| Task | Type | Hash | Message |
| --- | --- | --- | --- |
| 1 | feat | `f10494a` | `feat(01-04): add CliSetupCommandHandler for frood cli-setup` |
| 2 | feat | `8624e68` | `feat(01-04): register cli-setup argparse subparser + handler mapping` |
| 3 | test | `fa67f54` | `test(01-04): handler-level tests for cli-setup subcommand` |

## Known Stubs

None — the plan ships a fully wired CLI surface. Every sub-action dispatches to a real core function; every test exercises the real handler; the subprocess integration test runs the real binary against the real filesystem in read-only mode.

## Self-Check: PASSED

- `commands.py` — FOUND (CliSetupCommandHandler class present, extends CommandHandler)
- `frood.py` — FOUND (cli-setup subparser + handler mapping + import all in place)
- `tests/test_cli_setup_command.py` — FOUND (10 tests, all passing)
- Commit `f10494a` — FOUND in git log (`feat(01-04): add CliSetupCommandHandler...`)
- Commit `8624e68` — FOUND in git log (`feat(01-04): register cli-setup argparse subparser...`)
- Commit `fa67f54` — FOUND in git log (`test(01-04): handler-level tests...`)
- Lint clean on all three files; all 10 tests green; `python frood.py cli-setup detect` exits 0 with valid JSON
