#!/usr/bin/env bash
# coworker-daemon.sh — VPS-side daemon that picks up work orders and runs
# Claude Code sessions autonomously. Leverages auto-resume.sh for multi-
# session execution with context handoff.
#
# Install as systemd service via install-daemon.sh, or run directly:
#   ./coworker-daemon.sh
#
# Recall (take back control):
#   kill -USR1 $(cat /tmp/agent42-coworker.pid)
#   — or use recall.sh from your laptop

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

REPO_DIR="${COWORK_REPO_DIR/#\~/$HOME}"
AUTO_RESUME="$REPO_DIR/scripts/auto-resume.sh"
WO_DIR="$REPO_DIR/$COWORK_WORK_ORDERS_DIR"

# ── State ───────────────────────────────────────────────────────────
CLAUDE_PID=""
CURRENT_WO_ID=""
RECALLED=false
SHUTTING_DOWN=false

# ── Signal handlers ─────────────────────────────────────────────────

handle_recall() {
    log "RECALL signal received — stopping current session gracefully..."
    RECALLED=true
    if [[ -n "$CLAUDE_PID" ]] && kill -0 "$CLAUDE_PID" 2>/dev/null; then
        kill -INT "$CLAUDE_PID" 2>/dev/null || true
    fi
}

handle_shutdown() {
    log "Shutdown signal received..."
    SHUTTING_DOWN=true
    handle_recall
}

handle_wake() {
    log "Wake signal received — checking for work orders now..."
    # Interrupts sleep in main loop, causing immediate poll
}

trap handle_recall SIGUSR1
trap handle_wake SIGUSR2
trap handle_shutdown SIGTERM SIGINT

# ── Helpers ─────────────────────────────────────────────────────────

write_pid() {
    echo $$ > "$COWORK_PID_FILE"
    log "Daemon PID $$ written to $COWORK_PID_FILE"
}

write_status() {
    local status="$1"
    local wo_id="${2:-}"
    local detail="${3:-}"
    cat > "$COWORK_STATUS_FILE" <<STATUSEOF
{
  "daemon_pid": $$,
  "status": "$status",
  "work_order_id": "$wo_id",
  "detail": "$detail",
  "timestamp": "$(date -u -Iseconds)"
}
STATUSEOF
}

update_work_order() {
    local wo_id="$1"
    local new_status="$2"
    shift 2
    python3 "$REPO_DIR/core/work_order.py" --base-dir "$REPO_DIR" update "$wo_id" \
        --status "$new_status" "$@" 2>/dev/null || true
}

commit_progress() {
    local wo_id="$1"
    local reason="$2"
    cd "$REPO_DIR"

    # Stage any uncommitted changes
    local changed
    changed=$(git status --porcelain 2>/dev/null | head -1)
    if [[ -n "$changed" ]]; then
        git add -A
        git commit -m "cowork($wo_id): $reason — auto-commit by coworker daemon" \
            --author="Agent42 Coworker <coworker@agent42.local>" 2>/dev/null || true

        # Record the commit
        local sha
        sha=$(git rev-parse --short HEAD 2>/dev/null)
        update_work_order "$wo_id" "" --add-commit "$sha" 2>/dev/null || true
    fi
}

push_results() {
    local branch="$1"
    cd "$REPO_DIR"
    git push origin "$branch" 2>/dev/null || {
        warn "Push failed for branch $branch — will retry on next cycle"
    }
}

find_pending_work_orders() {
    python3 "$REPO_DIR/core/work_order.py" --base-dir "$REPO_DIR" list --status pending 2>/dev/null || true
}

get_wo_field() {
    local wo_id="$1"
    local field="$2"
    python3 -c "
import json, sys
wo = json.load(open('$WO_DIR/$wo_id.json'))
val = wo
for key in '$field'.split('.'):
    val = val.get(key, '') if isinstance(val, dict) else ''
print(val)
" 2>/dev/null
}

# ── Main execution ──────────────────────────────────────────────────

execute_work_order() {
    local wo_id="$1"
    CURRENT_WO_ID="$wo_id"
    RECALLED=false

    log "═══════════════════════════════════════════════════════════"
    log "Processing work order: $wo_id"
    log "═══════════════════════════════════════════════════════════"

    cd "$REPO_DIR"

    # Read work order fields
    local branch prompt max_turns max_sessions
    branch=$(get_wo_field "$wo_id" "branch")
    max_turns=$(get_wo_field "$wo_id" "constraints.max_turns")
    max_sessions=$(get_wo_field "$wo_id" "constraints.max_sessions")

    max_turns="${max_turns:-$COWORK_MAX_TURNS}"
    max_sessions="${max_sessions:-$COWORK_MAX_SESSIONS}"

    # Build the prompt from work order
    prompt=$(python3 "$REPO_DIR/core/work_order.py" --base-dir "$REPO_DIR" prompt "$wo_id" 2>/dev/null)
    if [[ -z "$prompt" ]]; then
        err "Empty prompt for work order $wo_id — skipping"
        update_work_order "$wo_id" "failed" --error "Empty prompt"
        return 1
    fi

    # Pull latest and checkout branch
    git pull --quiet origin 2>/dev/null || true
    if [[ -n "$branch" ]]; then
        git checkout "$branch" 2>/dev/null || git checkout -b "$branch" 2>/dev/null || {
            err "Cannot checkout branch: $branch"
            update_work_order "$wo_id" "failed" --error "Branch checkout failed: $branch"
            return 1
        }
    fi

    # Mark in-progress
    update_work_order "$wo_id" "in-progress"
    write_status "executing" "$wo_id" "Running claude sessions (max $max_sessions)"

    # Remove stale completion marker
    rm -f "$REPO_DIR/.claude/handoff-complete"

    # Run Claude Code via auto-resume
    log "Launching auto-resume: max_turns=$max_turns, max_sessions=$max_sessions"

    export AUTO_RESUME_MAX_TURNS="$max_turns"
    export AUTO_RESUME_MAX_SESSIONS="$max_sessions"
    unset CLAUDECODE  # Prevent nested-session error

    "$AUTO_RESUME" "$prompt" &
    CLAUDE_PID=$!
    echo "$CLAUDE_PID" > "$COWORK_CLAUDE_PID_FILE"

    # Wait for completion (interruptible by SIGUSR1 for recall)
    wait "$CLAUDE_PID" 2>/dev/null || true
    local exit_code=$?
    CLAUDE_PID=""

    # ── Post-execution ──────────────────────────────────────────

    if [[ "$RECALLED" == true ]]; then
        log "Work order $wo_id RECALLED by user"
        commit_progress "$wo_id" "recalled — user took back control"
        update_work_order "$wo_id" "recalled"
        write_status "idle" "$wo_id" "Recalled by user"
    elif [[ -f "$REPO_DIR/.claude/handoff-complete" ]]; then
        ok "Work order $wo_id COMPLETED"
        commit_progress "$wo_id" "completed — all criteria met"
        update_work_order "$wo_id" "completed"
        write_status "idle" "$wo_id" "Completed successfully"
    else
        warn "Work order $wo_id ended without completion marker"
        commit_progress "$wo_id" "session limit reached — partial progress"
        # Leave as in-progress (can be re-run or recalled)
        write_status "idle" "$wo_id" "Session limit reached, partial progress committed"
    fi

    # Push all results
    local push_branch
    push_branch="${branch:-$(git branch --show-current)}"
    push_results "$push_branch"

    # Also push work order status updates
    git add "$WO_DIR/$wo_id.json" 2>/dev/null || true
    git commit -m "cowork($wo_id): update status to $(get_wo_field "$wo_id" "status")" \
        --author="Agent42 Coworker <coworker@agent42.local>" 2>/dev/null || true
    push_results "$push_branch"

    CURRENT_WO_ID=""
}

# ── Main loop ───────────────────────────────────────────────────────

main() {
    write_pid
    write_status "starting" "" "Daemon starting up"
    ok "Coworker daemon started (PID $$)"
    ok "Watching for work orders in: $WO_DIR"
    ok "Poll interval: ${COWORK_POLL_INTERVAL}s"
    ok "Recall: kill -USR1 $$"

    while [[ "$SHUTTING_DOWN" != true ]]; do
        write_status "polling" "" "Checking for pending work orders"

        # Pull to get any new work orders
        cd "$REPO_DIR"
        git pull --quiet origin 2>/dev/null || true

        # Find pending work orders (oldest first)
        local pending
        pending=$(find_pending_work_orders | head -1)
        local wo_id
        wo_id=$(echo "$pending" | awk '{print $1}' | tr -d '[:space:]')

        if [[ -n "$wo_id" ]]; then
            execute_work_order "$wo_id" || {
                err "Work order $wo_id execution failed"
            }
        else
            write_status "idle" "" "No pending work orders"
        fi

        # Check for shutdown before sleeping
        if [[ "$SHUTTING_DOWN" == true ]]; then
            break
        fi

        # Sleep (interruptible by signals)
        sleep "$COWORK_POLL_INTERVAL" &
        wait $! 2>/dev/null || true
    done

    ok "Coworker daemon shutting down"
    write_status "stopped" "" "Daemon shut down"
    rm -f "$COWORK_PID_FILE" "$COWORK_CLAUDE_PID_FILE"
}

main "$@"
