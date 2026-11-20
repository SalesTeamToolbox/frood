#!/usr/bin/env bash
#
# ops/progress.sh — print one ANSI-colored progress bar line for a repo.
#
# Usage: progress.sh <repo>
#
# Prints a single line:
#   🟡/🟢 <repo> <short-sha> [<filled>░] <pct>% — <status line>
#
# Color: YELLOW while in-progress (no PASS/FAIL in the latest verify log),
# GREEN at 100% PASS, RED at FAIL.
#
# Reads progress from `.claude/worktrees/verify-*/.claude/verify.log` and the
# `ops/train.sh` status files (receipts under ~/.opencode/reports/frood-public/*/).
# No network, no external state.
set -uo pipefail

repo="${1:?usage: progress.sh <repo>}"

if ! git -C "$repo" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "progress: not a git repo: $repo" >&2
  exit 2
fi

name="$(basename "$repo")"
sha="$(git -C "$repo" rev-parse --short HEAD 2>/dev/null || echo "unknown")"

RESET="\033[0m"
YELLOW="\033[33m"
GREEN="\033[32m"
RED="\033[31m"

REPORTS_ROOT="/home/user/.opencode/reports/frood-public"

# ── status sources ──────────────────────────────────────────────
# 1. latest verify log (board verify, e.g. STT/Volnova verify-*/verify.log)
verify_log=""
shopt -s nullglob
verify_logs=( "$repo"/.claude/worktrees/verify-*/.claude/verify.log )
if [ "${#verify_logs[@]}" -gt 0 ]; then
  verify_log="$(ls -t "${verify_logs[@]}" 2>/dev/null | head -1)"
fi

# 2. latest train.sh receipt (ops/train.sh status files)
receipt=""
receipts=( "$REPORTS_ROOT"/*/receipt.md )
if [ "${#receipts[@]}" -gt 0 ]; then
  receipt="$(ls -t "${receipts[@]}" 2>/dev/null | head -1)"
fi

# ── determine status / color / pct ──────────────────────────────
status="in progress"
pct=0
color="$YELLOW"
emoji="🟡"

if [ -n "$verify_log" ]; then
  if grep -q "FAIL" "$verify_log"; then
    status="FAIL — $(basename "$verify_log")"
    color="$RED"; emoji="🔴"; pct=0
  elif grep -q "PASS" "$verify_log"; then
    status="PASS — $(basename "$verify_log")"
    color="$GREEN"; emoji="🟢"; pct=100
  else
    status="verifying — $(basename "$verify_log")"
  fi
elif [ -n "$receipt" ]; then
  receipt_status="$(awk -F': ' '/^status: /{print $2}' "$receipt" | tr -d '[:space:]')"
  receipt_ticket="$(basename "$(dirname "$receipt")")"
  case "$receipt_status" in
    pass)
      status="train pass — $receipt_ticket"
      color="$GREEN"; emoji="🟢"; pct=100 ;;
    *fail*)
      status="train fail — $receipt_ticket"
      color="$RED"; emoji="🔴"; pct=0 ;;
    *)
      status="train $receipt_status — $receipt_ticket" ;;
  esac
fi

# ── bar (10 cells) ──────────────────────────────────────────────
width=10
filled=$(( pct * width / 100 ))
bar=""
i=0
while [ "$i" -lt "$filled" ]; do bar="${bar}█"; i=$(( i + 1 )); done
while [ "$i" -lt "$width" ]; do bar="${bar}░"; i=$(( i + 1 )); done

printf "${color}%s %s %s [%s] %d%% — %s${RESET}\n" \
  "$emoji" "$name" "$sha" "$bar" "$pct" "$status"
