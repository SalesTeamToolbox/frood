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
# *.py runs under `timeout -k 10 $TRAIN_PYTEST_TIMEOUT python3 -m pytest <file> -q`
# (default 1200, log pytest.log); *.test.mjs / *.test.js under
# `timeout -k 10 $TRAIN_NODE_TIMEOUT node --test <file>` (default 600, log
# node-test.log). Both logs are emptied at the start of each run, then appended
# per file. Files run serially, one at a time; the first failure stops
# the run. Paths with spaces are not supported (Mandate tests: line).
#
# Exit codes: 0 = pass, 1 = test failure, 2 = lint failure.
set -uo pipefail

ticket="${1:?usage: train.sh <ticket>}"

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

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
tests: $tests_csv"

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

# Run serially, one file at a time; the first failure stops the run.
# Logs start empty each run, so a failure never dumps a previous run's output.
: >"$pytest_log"
: >"$node_test_log"
while IFS= read -r f; do
  [ -z "$f" ] && continue
  case "$f" in
    *.py)
      if timeout -k 10 "$TRAIN_PYTEST_TIMEOUT" python3 -m pytest "$f" -q >>"$pytest_log" 2>&1; then
        :
      else
        rc=$?
        if [ "$rc" -eq 124 ] || [ "$rc" -eq 137 ]; then
          detail="detail: pytest timed out after ${TRAIN_PYTEST_TIMEOUT}s: $f"
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
    *.test.mjs|*.test.js)
      if timeout -k 10 "$TRAIN_NODE_TIMEOUT" node --test "$f" >>"$node_test_log" 2>&1; then
        :
      else
        rc=$?
        if [ "$rc" -eq 124 ] || [ "$rc" -eq 137 ]; then
          detail="detail: node --test timed out after ${TRAIN_NODE_TIMEOUT}s: $f"
        else
          detail="detail: test failed: $f"
        fi
        write_receipt "test failure" 1 "$detail"
        cat "$node_test_log" >&2
        echo "train: node --test failed (exit 1)" >&2
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
