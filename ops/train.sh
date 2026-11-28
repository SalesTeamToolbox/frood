#!/usr/bin/env bash
#
# ops/train.sh — board verify -> pinned pytest or node --test -> receipts -> local-HEAD sha readback
#
# Usage: train.sh <ticket>
#
# Runs the per-ticket gate (lint + the pinned tests for the ticket),
# writes <report>/receipt.md, and prints the local-HEAD sha read back from
# `git rev-parse HEAD`. There is no deploy target — Frood public has no prod;
# the readback is local `git rev-parse HEAD` only.
#
# Pinned-test resolution (step 2, first hit wins, source printed to the receipt):
#   a. tests/test_<ticket>_demo.py then tests/test_<ticket>.py        (python convention)
#   b. $main_root/.opencode/board/tickets/<ticket>.json  blast_radius[].test values
#   c. $main_root/.opencode/reports/<ticket>/mandate.md      ^tests: line
#   d. none -> exit 1 "test failure" receipt naming every source tried
# *.py runs under `timeout -k 10 $TRAIN_PYTEST_TIMEOUT <pytest-python> -m pytest <file> -q`
# where <pytest-python> is "$repo_root/.venv/bin/python" when executable, else `python3`
# (venv-first rule; PATH is never changed). (default 1200, log pytest.log);
# *.test.mjs / *.test.js under
# `timeout -k 10 $TRAIN_NODE_TIMEOUT node --test <file>` (default 600, log
# node-test.log). Both logs are emptied at the start of each run, then appended
# per file. Files run serially, one at a time; the first failure stops
# the run. Paths with spaces are not supported (Mandate tests: line).
#
# Box-wide suite lock: before the test gate, train.sh sources
# $repo_root/orchestrator/ops/workstation/suite-lock.sh if it exists, else the
# installed $HOME/.local/lib/frood-workstation/suite-lock.sh, else runs
# unlocked and prints one stderr WARN. It takes the lock with
# suite_lock_acquire "frood train $ticket ($repo_root)" immediately before the
# test loop (lint stays outside it, because lint is cheap and must not queue)
# and releases it on every exit path: an EXIT trap, plus TERM/INT traps that
# kill a running test child first (TERM, wait up to 2 s, then KILL) and then
# release and exit 143/130. While the lock is held, FROOD_SUITE_LOCK_HELD=1 is
# exported to test children so a test that itself runs `make test` cannot
# deadlock on the lock. If the caller already holds the lock
# (FROOD_SUITE_LOCK_HELD=1 in the environment), acquire and release are skipped
# entirely (same rule as the Makefile test target). SUITE_LOCK=0 keeps the
# library's existing behaviour: it warns and takes no lock. Never fail the
# train for a missing lock library.
#
# The receipt gains two lines next to tests_source: — suite_lock_wait_s: N
# (wall seconds spent in acquire; 0 when skipped) and suite_lock:
# held|skipped (FROOD_SUITE_LOCK_HELD)|skipped (SUITE_LOCK=0)|unlocked (no
# lib).
#
# Exit codes: 0 = pass, 1 = test failure, 2 = lint failure.
set -uo pipefail

ticket="${1:?usage: train.sh <ticket>}"

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

# pytest interpreter: the checkout's own .venv/bin/python when executable,
# otherwise python3. Picked once here; never exported, PATH never changed.
if [ -x "$repo_root/.venv/bin/python" ]; then
  PYTEST_PYTHON="$repo_root/.venv/bin/python"
else
  PYTEST_PYTHON="python3"
fi

# ── suite lock library (box-wide lock shared by every repo on this box) ──
suite_lock_lib=""
if [ -f "$repo_root/orchestrator/ops/workstation/suite-lock.sh" ]; then
  suite_lock_lib="$repo_root/orchestrator/ops/workstation/suite-lock.sh"
elif [ -n "${HOME:-}" ] && [ -f "$HOME/.local/lib/frood-workstation/suite-lock.sh" ]; then
  suite_lock_lib="$HOME/.local/lib/frood-workstation/suite-lock.sh"
fi

# suite_lock_* state: set before the test gate and reported on the receipt.
suite_lock_held=0            # 1 = we acquired the lock; only we release it
suite_lock_wait_s=0          # wall seconds spent in acquire (0 when skipped)
suite_lock_line="unlocked (no lib)"

if [ -n "$suite_lock_lib" ]; then
  # shellcheck source=../orchestrator/ops/workstation/suite-lock.sh
  . "$suite_lock_lib"
else
  echo "train: WARN: suite-lock.sh not found — running the test gate without the box-wide lock" >&2
fi

REPORTS_ROOT="${FROOD_REPORTS_ROOT:-$HOME/.opencode/reports/frood-public}"
report_dir="$REPORTS_ROOT/$ticket"
receipt="$report_dir/receipt.md"
lint_log="$report_dir/lint.log"
pytest_log="$report_dir/pytest.log"
node_test_log="$report_dir/node-test.log"

mkdir -p "$report_dir"

started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

TRAIN_PYTEST_TIMEOUT="${TRAIN_PYTEST_TIMEOUT:-1200}"
TRAIN_NODE_TIMEOUT="${TRAIN_NODE_TIMEOUT:-600}"

# main_root: the main checkout holding the untracked board ticket and Mandate
# (a worktree does not have them). Fall back to repo_root if the command fails.
main_root="$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null | sed 's|/\.git$||' || true)"
if [ -z "$main_root" ]; then
  main_root="$repo_root"
fi
ticket_json="$main_root/.opencode/board/tickets/$ticket.json"
mandate_path="$main_root/.opencode/reports/$ticket/mandate.md"

# Resolution globals. tests_receipt_lines is written into the receipt after
# local_head_sha: and before the detail; it is empty for a lint failure
# (exit 2), which happens before any test resolution.
tests_source="none"
tests_list=""
tests_receipt_lines=""

write_receipt() {
  local status="$1" exit_code="$2" detail="${3:-}"
  cat >"$receipt" <<EOF
# train receipt — $ticket

status: $status
started: $started
finished: $(date -u +%Y-%m-%dT%H:%M:%SZ)
exit_code: $exit_code
local_head_sha: $(git rev-parse HEAD)
$tests_receipt_lines
$detail
EOF
}

# ── 1. board verify: lint ───────────────────────────────────────
if [ -x "$repo_root/.venv/bin/ruff" ]; then
  lint_cmd=(make lint)
  lint_label="make lint"
else
  # No project venv in this checkout; fall back to ruff on PATH so the gate
  # still runs (and so train.sh works from a fresh clone before install-dev).
  lint_cmd=(ruff check .)
  lint_label="ruff check . (no .venv; make lint unavailable)"
fi

echo "train: $ticket — $lint_label"
if ! "${lint_cmd[@]}" >"$lint_log" 2>&1; then
  write_receipt "lint failure" 2
  cat "$lint_log" >&2
  echo "train: lint failed (exit 2)"
  exit 2
fi

# ── 2. pinned tests for the ticket ─────────────────────────────
# (a) python convention — <ticket> used verbatim (no hyphen->underscore mapping).
test_file="tests/test_${ticket}_demo.py"
if [ ! -f "$test_file" ]; then
  test_file="tests/test_$ticket.py"
fi

if [ -f "$test_file" ]; then
  tests_source="python-convention"
  tests_list="$test_file"
else
  # (b) board ticket blast_radius[].test values, array order, de-duped first occurrence.
  board_lines=""
  if [ -f "$ticket_json" ]; then
    board_lines="$(python3 - "$ticket_json" <<'PY' 2>&1
import json, sys
path = sys.argv[1]
try:
    with open(path) as f:
        data = json.load(f)
except Exception:
    print("UNREADABLE_JSON " + path)
    sys.exit(0)
tests = []
for entry in (data.get("blast_radius") or []):
    if not isinstance(entry, dict):
        continue
    t = entry.get("test")
    if t is None or t == "":
        continue
    if t not in tests:
        tests.append(t)
for t in tests:
    print(t)
PY
)"
    if [[ "$board_lines" == UNREADABLE_JSON\ * ]]; then
      write_receipt "test failure" 1 "detail: unreadable board ticket json: $ticket_json"
      echo "train: unreadable board ticket json: $ticket_json" >&2
      exit 1
    fi
  fi

  if [ -n "$board_lines" ]; then
    tests_source="board-ticket"
    tests_list="$board_lines"
  else
    # (c) Mandate ^tests: line (only when the ticket JSON yields nothing).
    mandate_raw=""
    if [ -f "$mandate_path" ]; then
      mandate_raw="$(awk '/^tests:/{sub(/^tests:[ \t]*/,""); print; exit}' "$mandate_path")"
    fi
    if [ -n "$mandate_raw" ]; then
      tests_source="mandate"
      # split on commas and whitespace, drop empties, de-dupe keeping order.
      # set -f: a token is a path, never a glob pattern.
      set -f
      tests_list="$(printf '%s\n' ${mandate_raw//,/ } | awk 'NF && !seen[$0]++')"
      set +f
    fi
  fi
fi

# Build the comma-joined receipt value (empty when none).
tests_csv="$(printf '%s\n' "$tests_list" | paste -sd, -)"
tests_receipt_lines="tests_source: $tests_source
tests: $tests_csv
python: $PYTEST_PYTHON"

# (d) nothing found -> exit 1 naming every source tried.
if [ "$tests_source" = "none" ]; then
  write_receipt "test failure" 1 "detail: no tests found for ticket $ticket (tried tests/test_${ticket}_demo.py, tests/test_$ticket.py, $ticket_json, $mandate_path)"
  echo "train: no test file for ticket $ticket" >&2
  exit 1
fi

# Before running anything, every resolved path must exist under repo_root.
while IFS= read -r f; do
  [ -z "$f" ] && continue
  if [ ! -f "$repo_root/$f" ]; then
    write_receipt "test failure" 1 "detail: listed test not found: $f"
    echo "train: listed test not found: $f" >&2
    exit 1
  fi
done <<< "$tests_list"

# child_pid is the pid of the test child currently running under the lock (the
# timeout wrapper). GNU timeout does not forward signals to the command it
# wraps, so the job is launched with job control (`set -m`), which gives it its
# own process group; the TERM/INT traps signal -$child_pid, i.e. the whole
# group, so the test process itself dies and none outlives train.sh.
child_pid=""

# Release the suite lock exactly once: only when we are the ones who acquired
# it (suite_lock_release also guards on SUITE_LOCK_HELD internally).
release_our_lock() {
  if [ "$suite_lock_held" = "1" ]; then
    suite_lock_release
    suite_lock_held=0
  fi
}

on_term() {
  local i
  if [ -n "$child_pid" ] && kill -0 "$child_pid" 2>/dev/null; then
    kill -TERM -- "-$child_pid" 2>/dev/null || true
    for i in 1 2; do
      kill -0 "$child_pid" 2>/dev/null || break
      sleep 1
    done
    if kill -0 "$child_pid" 2>/dev/null; then
      kill -KILL -- "-$child_pid" 2>/dev/null || true
    fi
    wait "$child_pid" 2>/dev/null || true
  fi
  release_our_lock
  exit 143
}

on_int() {
  if [ -n "$child_pid" ] && kill -0 "$child_pid" 2>/dev/null; then
    kill -TERM -- "-$child_pid" 2>/dev/null || true
    wait "$child_pid" 2>/dev/null || true
  fi
  release_our_lock
  exit 130
}

trap 'on_term' TERM
trap 'on_int' INT
trap 'release_our_lock' EXIT

# ── take the box-wide suite lock right before the test gate ─────────────
# Lint (above) stays outside the lock: it is cheap and must not queue.
# The timeouts (TRAIN_PYTEST_TIMEOUT / TRAIN_NODE_TIMEOUT) cover only the test
# run, never the lock wait.
if [ -n "$suite_lock_lib" ]; then
  if [ "${FROOD_SUITE_LOCK_HELD:-0}" = "1" ]; then
    # The caller already holds the lock: skip acquire and release entirely.
    suite_lock_line="skipped (FROOD_SUITE_LOCK_HELD)"
  else
    lock_start="$(date +%s)"
    if suite_lock_acquire "frood train $ticket ($repo_root)"; then
      lock_end="$(date +%s)"
      suite_lock_wait_s=$(( lock_end - lock_start ))
      [ "$suite_lock_wait_s" -lt 0 ] && suite_lock_wait_s=0
      if [ "${SUITE_LOCK:-1}" = "0" ]; then
        # The library warned and took no lock.
        suite_lock_line="skipped (SUITE_LOCK=0)"
      else
        suite_lock_line="held"
        suite_lock_held=1
        # Test children inherit this: a test that runs `make test` must not
        # deadlock trying to take a lock we already hold.
        export FROOD_SUITE_LOCK_HELD=1
      fi
    else
      lock_rc=$?
      write_receipt "test failure" 1 "$tests_receipt_lines
suite_lock_wait_s: 0
suite_lock: unavailable (rc $lock_rc)
detail: suite lock unavailable (rc $lock_rc)"
      echo "train: suite lock unavailable (rc $lock_rc)" >&2
      exit 1
    fi
  fi
fi

tests_receipt_lines="$tests_receipt_lines
suite_lock_wait_s: $suite_lock_wait_s
suite_lock: $suite_lock_line"

# Run one test file under the lock, in the background so a TERM/INT trap can
# kill the child. `set -m` gives the background job its own process group, so
# the trap addresses the whole group (-$child_pid) rather than just the
# timeout wrapper (which does not forward signals).
run_test_file() {
  local f="$1" rc=0
  set -m
  case "$f" in
    *.py)
      timeout -k 10 "$TRAIN_PYTEST_TIMEOUT" "$PYTEST_PYTHON" -m pytest "$f" -q >>"$pytest_log" 2>&1 &
      child_pid=$!
      ;;
    *.test.mjs|*.test.js)
      timeout -k 10 "$TRAIN_NODE_TIMEOUT" node --test "$f" >>"$node_test_log" 2>&1 &
      child_pid=$!
      ;;
  esac
  set +m
  wait "$child_pid"; rc=$?
  child_pid=""
  return $rc
}

# Run serially, one file at a time; the first failure stops the run.
# Logs start empty each run, so a failure never dumps a previous run's output.
: >"$pytest_log"
: >"$node_test_log"
while IFS= read -r f; do
  [ -z "$f" ] && continue
  case "$f" in
    *.py|*.test.mjs|*.test.js)
      run_test_file "$f"; rc=$?
      if [ "$rc" -ne 0 ]; then
        if [ "$rc" -eq 124 ] || [ "$rc" -eq 137 ]; then
          case "$f" in
            *.py) detail="detail: pytest timed out after ${TRAIN_PYTEST_TIMEOUT}s: $f" ;;
            *) detail="detail: node --test timed out after ${TRAIN_NODE_TIMEOUT}s: $f" ;;
          esac
        elif [ "$tests_source" = "python-convention" ]; then
          detail=""  # keep today's behaviour: no detail on a plain pytest failure
        else
          detail="detail: test failed: $f"
        fi
        write_receipt "test failure" 1 "$detail"
        cat "$pytest_log" >&2
        echo "train: pytest failed (exit 1)" >&2
        exit 1
      fi
      ;;
    *)
      write_receipt "test failure" 1 "detail: no runner for $f"
      echo "train: no runner for $f" >&2
      exit 1
      ;;
  esac
done <<< "$tests_list"

# ── 3. receipt + local-HEAD sha readback ────────────────────────
write_receipt "pass" 0
echo "local-HEAD sha: $(git rev-parse HEAD)"
exit 0
