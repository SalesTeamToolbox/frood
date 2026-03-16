#!/usr/bin/env bash
# handoff.sh — Create a work order and send it to the VPS for autonomous execution.
#
# Usage:
#   ./handoff.sh --prompt "Build the caching layer"
#   ./handoff.sh --prompt "Build it" --branch feat/cache --criteria "Tests pass" "Tool registered"
#   ./handoff.sh --plan .planning/phases/14/14-01-PLAN.md --branch feat/cache
#
# This script:
#   1. Creates a work order JSON from your arguments
#   2. Commits and pushes it to the remote
#   3. SSHs to VPS and triggers an immediate pull
#   4. Reports the work order ID for tracking

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

# ── Argument parsing ────────────────────────────────────────────────
PROMPT=""
BRANCH=""
PLAN=""
MAX_TURNS="$COWORK_MAX_TURNS"
MAX_SESSIONS="$COWORK_MAX_SESSIONS"
TIMEOUT=120
MUST_RUN="python -m pytest tests/ -x -q"
CRITERIA=()
NO_TOUCH=()

usage() {
    echo "Usage: $0 --prompt \"task description\" [options]"
    echo ""
    echo "Options:"
    echo "  --prompt TEXT        Task description for Claude Code"
    echo "  --plan PATH          GSD plan file path (alternative to --prompt)"
    echo "  --branch NAME        Git branch to work on (created if needed)"
    echo "  --criteria TEXT...   Acceptance criteria (repeat for multiple)"
    echo "  --no-touch FILE...   Files Claude must not modify"
    echo "  --must-run CMD       Test command (default: pytest)"
    echo "  --max-turns N        Max turns per CC session (default: 30)"
    echo "  --max-sessions N     Max CC sessions (default: 10)"
    echo "  --timeout N          Timeout in minutes (default: 120)"
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --prompt)       PROMPT="$2"; shift 2 ;;
        --plan)         PLAN="$2"; shift 2 ;;
        --branch)       BRANCH="$2"; shift 2 ;;
        --criteria)     shift; while [[ $# -gt 0 && ! "$1" =~ ^-- ]]; do
                            CRITERIA+=("$1"); shift
                        done ;;
        --no-touch)     shift; while [[ $# -gt 0 && ! "$1" =~ ^-- ]]; do
                            NO_TOUCH+=("$1"); shift
                        done ;;
        --must-run)     MUST_RUN="$2"; shift 2 ;;
        --max-turns)    MAX_TURNS="$2"; shift 2 ;;
        --max-sessions) MAX_SESSIONS="$2"; shift 2 ;;
        --timeout)      TIMEOUT="$2"; shift 2 ;;
        --help|-h)      usage ;;
        *)              err "Unknown option: $1"; usage ;;
    esac
done

if [[ -z "$PROMPT" && -z "$PLAN" ]]; then
    err "Either --prompt or --plan is required"
    usage
fi

# ── Preflight checks ───────────────────────────────────────────────

ROOT=$(repo_root)
if [[ -z "$ROOT" ]]; then
    err "Not in a git repository"
    exit 1
fi
cd "$ROOT"

log "Checking VPS connectivity..."
if ! vps_ping; then
    err "Cannot reach VPS ($COWORK_VPS_HOST). Check SSH config."
    exit 1
fi
ok "VPS reachable"

# ── Create work order ──────────────────────────────────────────────

log "Creating work order..."

# Build the python command for creating work order
CREATE_ARGS="create"
[[ -n "$BRANCH" ]] && CREATE_ARGS="$CREATE_ARGS --branch $BRANCH"
[[ -n "$PROMPT" ]] && CREATE_ARGS="$CREATE_ARGS --prompt \"$PROMPT\""
[[ -n "$PLAN" ]] && CREATE_ARGS="$CREATE_ARGS --plan $PLAN"
[[ -n "$MUST_RUN" ]] && CREATE_ARGS="$CREATE_ARGS --must-run \"$MUST_RUN\""
CREATE_ARGS="$CREATE_ARGS --max-turns $MAX_TURNS --max-sessions $MAX_SESSIONS --timeout $TIMEOUT"

# Add criteria
CRITERIA_ARGS=""
if [[ ${#CRITERIA[@]} -gt 0 ]]; then
    CRITERIA_ARGS="--criteria"
    for c in "${CRITERIA[@]}"; do
        CRITERIA_ARGS="$CRITERIA_ARGS \"$c\""
    done
fi

# Add no-touch
NOTOUCH_ARGS=""
if [[ ${#NO_TOUCH[@]} -gt 0 ]]; then
    NOTOUCH_ARGS="--no-touch"
    for f in "${NO_TOUCH[@]}"; do
        NOTOUCH_ARGS="$NOTOUCH_ARGS \"$f\""
    done
fi

RESULT=$(eval python3 core/work_order.py $CREATE_ARGS $CRITERIA_ARGS $NOTOUCH_ARGS)
WO_ID=$(echo "$RESULT" | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")
WO_PATH=$(echo "$RESULT" | python3 -c "import json,sys; print(json.load(sys.stdin)['path'])")

ok "Work order created: $WO_ID"
ok "File: $WO_PATH"

# ── Commit and push ────────────────────────────────────────────────

log "Committing work order..."

# Also commit any staged/unstaged work so VPS has latest code
git add "$WO_PATH"
git add -A 2>/dev/null || true

git commit -m "cowork: create work order $WO_ID for VPS execution

Prompt: ${PROMPT:-$PLAN}
Branch: ${BRANCH:-$(git branch --show-current)}
Max sessions: $MAX_SESSIONS" 2>/dev/null || {
    warn "Nothing to commit (work order may already be staged)"
}

CURRENT_BRANCH=$(git branch --show-current)
log "Pushing to origin/$CURRENT_BRANCH..."
git push origin "$CURRENT_BRANCH" || {
    err "Push failed. Resolve conflicts and retry."
    exit 1
}

# If work order targets a different branch, push that too
if [[ -n "$BRANCH" && "$BRANCH" != "$CURRENT_BRANCH" ]]; then
    git checkout -b "$BRANCH" 2>/dev/null || git checkout "$BRANCH" 2>/dev/null || true
    git push origin "$BRANCH" 2>/dev/null || true
    git checkout "$CURRENT_BRANCH" 2>/dev/null || true
fi

# ── Signal VPS ──────────────────────────────────────────────────────

log "Signaling VPS to pick up work order..."
vps_run "git pull --quiet origin" || warn "VPS pull failed — daemon will pick it up on next poll"

# Check if daemon is running, nudge it
DAEMON_RUNNING=$(vps_run "test -f $COWORK_PID_FILE && kill -0 \$(cat $COWORK_PID_FILE) 2>/dev/null && echo yes || echo no")

if [[ "$DAEMON_RUNNING" == "yes" ]]; then
    ok "Coworker daemon is running on VPS — work will start within ${COWORK_POLL_INTERVAL}s"
    # Wake up the daemon from its sleep
    vps_run "kill -USR2 \$(cat $COWORK_PID_FILE) 2>/dev/null" || true
else
    warn "Coworker daemon is NOT running on VPS"
    warn "Start it with: ssh $COWORK_VPS_HOST 'cd $COWORK_REPO_DIR && scripts/cowork/coworker-daemon.sh &'"
    warn "Or install as service: ssh $COWORK_VPS_HOST 'cd $COWORK_REPO_DIR && scripts/cowork/install-daemon.sh'"
fi

# ── Summary ─────────────────────────────────────────────────────────

echo ""
ok "══════════════════════════════════════════════════════════"
ok "  Work order $WO_ID handed off to VPS"
ok "══════════════════════════════════════════════════════════"
echo ""
log "Track progress:  scripts/cowork/status.sh"
log "Take back:       scripts/cowork/recall.sh $WO_ID"
log "VPS dashboard:   http://163.245.217.2:8000"
echo ""
