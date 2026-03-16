#!/usr/bin/env bash
# common.sh — Shared configuration and helpers for cowork scripts.

# ── VPS Connection ──────────────────────────────────────────────────
COWORK_VPS_HOST="${COWORK_VPS_HOST:-agent42-prod}"
COWORK_REPO_DIR="${COWORK_REPO_DIR:-~/agent42}"

# ── Paths (VPS-side) ───────────────────────────────────────────────
COWORK_WORK_ORDERS_DIR=".planning/work-orders"
COWORK_PID_FILE="/tmp/agent42-coworker.pid"
COWORK_CLAUDE_PID_FILE="/tmp/agent42-coworker-claude.pid"
COWORK_LOG_FILE="/tmp/agent42-coworker.log"
COWORK_STATUS_FILE="/tmp/agent42-coworker-status.json"

# ── Paths (local) ──────────────────────────────────────────────────
LOCAL_WORK_ORDERS_DIR=".planning/work-orders"

# ── Defaults ────────────────────────────────────────────────────────
COWORK_MAX_TURNS="${COWORK_MAX_TURNS:-30}"
COWORK_MAX_SESSIONS="${COWORK_MAX_SESSIONS:-10}"
COWORK_POLL_INTERVAL="${COWORK_POLL_INTERVAL:-300}"

# ── Color helpers ───────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

log()  { echo -e "${CYAN}[cowork]${RESET} $*"; }
warn() { echo -e "${YELLOW}[cowork]${RESET} $*"; }
err()  { echo -e "${RED}[cowork]${RESET} $*" >&2; }
ok()   { echo -e "${GREEN}[cowork]${RESET} $*"; }

# ── Helpers ─────────────────────────────────────────────────────────

vps_run() {
    ssh "$COWORK_VPS_HOST" "cd $COWORK_REPO_DIR && $*"
}

vps_ping() {
    ssh -o ConnectTimeout=5 "$COWORK_VPS_HOST" "echo ok" &>/dev/null
}

cowork_dir() {
    local dir
    dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    echo "$dir"
}

generate_wo_id() {
    date -u +"%Y%m%d-%H%M%S"
}

repo_root() {
    git rev-parse --show-toplevel 2>/dev/null
}
