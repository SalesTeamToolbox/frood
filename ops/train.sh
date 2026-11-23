#!/usr/bin/env bash
#
# ops/train.sh — board verify -> pinned pytest -> receipts -> local-HEAD sha readback
#
# Usage: train.sh <ticket>
#
# Runs the per-ticket gate (lint + the focused pytest file for the ticket),
# writes <report>/receipt.md, and prints the local-HEAD sha read back from
# `git rev-parse HEAD`. There is no deploy target — Frood public has no prod;
# the readback is local `git rev-parse HEAD` only.
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

mkdir -p "$report_dir"

started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

write_receipt() {
  local status="$1" exit_code="$2" detail="${3:-}"
  cat >"$receipt" <<EOF
# train receipt — $ticket

status: $status
started: $started
finished: $(date -u +%Y-%m-%dT%H:%M:%SZ)
exit_code: $exit_code
local_head_sha: $(git rev-parse HEAD)
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

# ── 2. pinned pytest for the ticket ─────────────────────────────
test_file="tests/test_${ticket}_demo.py"
if [ ! -f "$test_file" ]; then
  test_file="tests/test_$ticket.py"
fi
if [ ! -f "$test_file" ]; then
  write_receipt "test failure" 1 "detail: no pytest file found for ticket $ticket (tried tests/test_${ticket}_demo.py and tests/test_$ticket.py)"
  echo "train: no test file for ticket $ticket" >&2
  exit 1
fi

echo "train: $ticket — pytest $test_file"
if ! python3 -m pytest "$test_file" -q >"$pytest_log" 2>&1; then
  write_receipt "test failure" 1
  cat "$pytest_log" >&2
  echo "train: pytest failed (exit 1)"
  exit 1
fi

# ── 3. receipt + local-HEAD sha readback ────────────────────────
write_receipt "pass" 0
echo "local-HEAD sha: $(git rev-parse HEAD)"
exit 0
