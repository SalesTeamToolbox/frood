#!/usr/bin/env bash
# recall.sh — Take back control from the VPS coworker.
#
# Gracefully stops the current Claude Code session on the VPS,
# commits any progress, pushes, and pulls the results locally.
#
# Usage:
#   ./recall.sh              # Recall current work (auto-detect)
#   ./recall.sh <work-order-id>  # Recall specific work order
#   ./recall.sh --force      # Force kill without graceful shutdown

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

FORCE=false
WO_ID=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --force)  FORCE=true; shift ;;
        --help|-h)
            echo "Usage: $0 [work-order-id] [--force]"
            exit 0 ;;
        *)  WO_ID="$1"; shift ;;
    esac
done

# ── Preflight ───────────────────────────────────────────────────────

ROOT=$(repo_root)
if [[ -z "$ROOT" ]]; then
    err "Not in a git repository"
    exit 1
fi
cd "$ROOT"

log "Connecting to VPS..."
if ! vps_ping; then
    err "Cannot reach VPS ($COWORK_VPS_HOST)"
    exit 1
fi
ok "VPS reachable"

# ── Check daemon status ────────────────────────────────────────────

DAEMON_PID=$(vps_run "cat $COWORK_PID_FILE 2>/dev/null" || echo "")
if [[ -z "$DAEMON_PID" ]]; then
    warn "No coworker daemon PID file found"
    warn "Daemon may not be running. Pulling latest changes anyway..."
    git pull origin 2>/dev/null || true
    exit 0
fi

# Verify daemon is actually running
DAEMON_ALIVE=$(vps_run "kill -0 $DAEMON_PID 2>/dev/null && echo yes || echo no")
if [[ "$DAEMON_ALIVE" != "yes" ]]; then
    warn "Daemon PID $DAEMON_PID is stale (not running)"
    vps_run "rm -f $COWORK_PID_FILE $COWORK_CLAUDE_PID_FILE"
    log "Pulling latest changes..."
    git pull origin 2>/dev/null || true
    exit 0
fi

# ── Get current VPS status ──────────────────────────────────────────

log "Checking VPS coworker status..."
VPS_STATUS=$(vps_run "cat $COWORK_STATUS_FILE 2>/dev/null" || echo '{"status":"unknown"}')
CURRENT_STATUS=$(echo "$VPS_STATUS" | python3 -c "import json,sys; print(json.load(sys.stdin).get('status','unknown'))" 2>/dev/null)
CURRENT_WO=$(echo "$VPS_STATUS" | python3 -c "import json,sys; print(json.load(sys.stdin).get('work_order_id',''))" 2>/dev/null)

if [[ "$CURRENT_STATUS" == "idle" || "$CURRENT_STATUS" == "polling" ]]; then
    ok "VPS is idle — no active work to recall"
    log "Pulling latest changes..."
    git pull origin 2>/dev/null || true
    exit 0
fi

log "VPS status: $CURRENT_STATUS"
log "Active work order: ${CURRENT_WO:-none}"

# ── Send recall signal ──────────────────────────────────────────────

if [[ "$FORCE" == true ]]; then
    warn "Force-killing VPS claude session..."

    # Kill the claude/auto-resume process directly
    CLAUDE_PID=$(vps_run "cat $COWORK_CLAUDE_PID_FILE 2>/dev/null" || echo "")
    if [[ -n "$CLAUDE_PID" ]]; then
        vps_run "kill -9 $CLAUDE_PID 2>/dev/null; kill -9 -$CLAUDE_PID 2>/dev/null" || true
    fi

    # Then signal daemon to clean up
    vps_run "kill -USR1 $DAEMON_PID" || true
    sleep 2
else
    log "Sending graceful recall signal to daemon (PID $DAEMON_PID)..."
    vps_run "kill -USR1 $DAEMON_PID" || {
        err "Failed to send recall signal"
        exit 1
    }
fi

# ── Wait for VPS to commit and push ────────────────────────────────

log "Waiting for VPS to commit progress and push..."
MAX_WAIT=60
WAITED=0
INTERVAL=3

while [[ $WAITED -lt $MAX_WAIT ]]; do
    sleep "$INTERVAL"
    WAITED=$((WAITED + INTERVAL))

    # Check if daemon has finished cleanup
    NEW_STATUS=$(vps_run "cat $COWORK_STATUS_FILE 2>/dev/null" | \
        python3 -c "import json,sys; print(json.load(sys.stdin).get('status','unknown'))" 2>/dev/null || echo "unknown")

    if [[ "$NEW_STATUS" == "idle" || "$NEW_STATUS" == "polling" || "$NEW_STATUS" == "stopped" ]]; then
        ok "VPS acknowledged recall (status: $NEW_STATUS)"
        break
    fi

    log "  Still waiting... ($WAITED/${MAX_WAIT}s, status: $NEW_STATUS)"
done

if [[ $WAITED -ge $MAX_WAIT ]]; then
    warn "Timed out waiting for VPS cleanup — pulling anyway"
fi

# ── Pull results locally ────────────────────────────────────────────

log "Pulling VPS changes locally..."
git fetch origin 2>/dev/null || true
CURRENT_BRANCH=$(git branch --show-current)
git pull origin "$CURRENT_BRANCH" 2>/dev/null || {
    warn "Pull had conflicts — resolve manually"
}

# If work order had a different branch, fetch that too
if [[ -n "$WO_ID" ]]; then
    WO_BRANCH=$(python3 -c "
import json
wo = json.load(open('$LOCAL_WORK_ORDERS_DIR/$WO_ID.json'))
print(wo.get('branch', ''))
" 2>/dev/null || echo "")

    if [[ -n "$WO_BRANCH" && "$WO_BRANCH" != "$CURRENT_BRANCH" ]]; then
        log "Fetching work order branch: $WO_BRANCH"
        git fetch origin "$WO_BRANCH" 2>/dev/null || true
    fi
elif [[ -n "$CURRENT_WO" ]]; then
    WO_ID="$CURRENT_WO"
fi

# ── Show what was accomplished ──────────────────────────────────────

echo ""
ok "══════════════════════════════════════════════════════════"
ok "  Control reclaimed from VPS"
ok "══════════════════════════════════════════════════════════"
echo ""

if [[ -n "$WO_ID" && -f "$LOCAL_WORK_ORDERS_DIR/$WO_ID.json" ]]; then
    log "Work order $WO_ID status:"
    python3 -c "
import json
wo = json.load(open('$LOCAL_WORK_ORDERS_DIR/$WO_ID.json'))
print(f\"  Status:     {wo['status']}\")
print(f\"  Branch:     {wo.get('branch', 'current')}\")
commits = wo.get('progress', {}).get('commits', [])
files = wo.get('progress', {}).get('files_modified', [])
print(f\"  Commits:    {len(commits)}\")
print(f\"  Files:      {len(files)}\")
if commits:
    print(f\"  Last commit: {commits[-1]}\")
if wo.get('progress', {}).get('error'):
    print(f\"  Error:      {wo['progress']['error']}\")
" 2>/dev/null || true
fi

echo ""
log "Recent VPS commits:"
git log --oneline -5 --author="Agent42 Coworker" 2>/dev/null || git log --oneline -5
echo ""
log "You can now continue working locally with Claude Code."
