#!/usr/bin/env bash
# status.sh — Check what the VPS coworker is doing.
#
# Usage:
#   ./status.sh           # Quick status
#   ./status.sh --watch   # Poll every 30s
#   ./status.sh --detail  # Full work order details

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

WATCH=false
DETAIL=false
WATCH_INTERVAL=30

while [[ $# -gt 0 ]]; do
    case "$1" in
        --watch|-w)   WATCH=true; shift ;;
        --detail|-d)  DETAIL=true; shift ;;
        --interval)   WATCH_INTERVAL="$2"; shift 2 ;;
        --help|-h)
            echo "Usage: $0 [--watch] [--detail] [--interval N]"
            exit 0 ;;
        *)  shift ;;
    esac
done

show_status() {
    # ── VPS connectivity ────────────────────────────────────────
    if ! vps_ping; then
        err "Cannot reach VPS ($COWORK_VPS_HOST)"
        return 1
    fi

    # ── Daemon status ───────────────────────────────────────────
    local daemon_pid daemon_alive
    daemon_pid=$(vps_run "cat $COWORK_PID_FILE 2>/dev/null" || echo "")

    if [[ -z "$daemon_pid" ]]; then
        echo -e "  Daemon:     ${RED}not running${RESET}"
        return 0
    fi

    daemon_alive=$(vps_run "kill -0 $daemon_pid 2>/dev/null && echo yes || echo no")
    if [[ "$daemon_alive" != "yes" ]]; then
        echo -e "  Daemon:     ${RED}stale PID $daemon_pid${RESET}"
        return 0
    fi

    echo -e "  Daemon:     ${GREEN}running${RESET} (PID $daemon_pid)"

    # ── Current activity ────────────────────────────────────────
    local status_json status wo_id detail_msg timestamp
    status_json=$(vps_run "cat $COWORK_STATUS_FILE 2>/dev/null" || echo '{}')

    status=$(echo "$status_json" | python3 -c "import json,sys; print(json.load(sys.stdin).get('status','unknown'))" 2>/dev/null)
    wo_id=$(echo "$status_json" | python3 -c "import json,sys; print(json.load(sys.stdin).get('work_order_id',''))" 2>/dev/null)
    detail_msg=$(echo "$status_json" | python3 -c "import json,sys; print(json.load(sys.stdin).get('detail',''))" 2>/dev/null)
    timestamp=$(echo "$status_json" | python3 -c "import json,sys; print(json.load(sys.stdin).get('timestamp',''))" 2>/dev/null)

    local color="$CYAN"
    case "$status" in
        executing) color="$YELLOW" ;;
        idle|polling) color="$GREEN" ;;
        stopped) color="$RED" ;;
    esac

    echo -e "  Status:     ${color}${status}${RESET}"
    [[ -n "$wo_id" ]] && echo "  Work order: $wo_id"
    [[ -n "$detail_msg" ]] && echo "  Detail:     $detail_msg"
    [[ -n "$timestamp" ]] && echo "  Updated:    $timestamp"

    # ── Claude process ──────────────────────────────────────────
    local claude_pid
    claude_pid=$(vps_run "cat $COWORK_CLAUDE_PID_FILE 2>/dev/null" || echo "")
    if [[ -n "$claude_pid" ]]; then
        local claude_alive
        claude_alive=$(vps_run "kill -0 $claude_pid 2>/dev/null && echo yes || echo no")
        if [[ "$claude_alive" == "yes" ]]; then
            echo -e "  Claude CC:  ${YELLOW}active${RESET} (PID $claude_pid)"
        fi
    fi

    # ── Work order details ──────────────────────────────────────
    if [[ "$DETAIL" == true && -n "$wo_id" ]]; then
        echo ""
        log "Work order details:"
        vps_run "python3 core/work_order.py get $wo_id 2>/dev/null" || true
    fi

    # ── Pending work orders ─────────────────────────────────────
    echo ""
    log "Pending work orders:"
    local pending
    pending=$(vps_run "python3 core/work_order.py list --status pending 2>/dev/null" || echo "  (none)")
    if [[ -z "$pending" ]]; then
        echo "  (none)"
    else
        echo "$pending" | while IFS= read -r line; do echo "  $line"; done
    fi

    # ── Recent VPS git activity ─────────────────────────────────
    echo ""
    log "Recent VPS commits:"
    vps_run "git log --oneline -5 2>/dev/null" | while IFS= read -r line; do echo "  $line"; done
}

# ── Main ────────────────────────────────────────────────────────────

echo ""
echo -e "${BOLD}═══ Agent42 VPS Coworker Status ═══${RESET}"
echo ""

if [[ "$WATCH" == true ]]; then
    while true; do
        clear
        echo -e "${BOLD}═══ Agent42 VPS Coworker Status ═══${RESET} (refreshing every ${WATCH_INTERVAL}s, Ctrl+C to stop)"
        echo ""
        show_status || true
        sleep "$WATCH_INTERVAL"
    done
else
    show_status
fi
echo ""
