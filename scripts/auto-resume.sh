#!/usr/bin/env bash
# auto-resume.sh — Runs Claude Code sessions in a loop with automatic context refresh.
#
# When a session hits its turn limit (context getting full), this script
# starts a fresh session with a resume prompt that carries forward what
# was accomplished. Works with any task — GSD phases, coding, refactoring, etc.
#
# State capture uses `git diff` between sessions (Stop hooks don't fire in
# print mode), plus GSD .planning/ state detection.
#
# Usage:
#   claude-auto-resume "your prompt here"
#   claude-auto-resume "your prompt here" --max-turns 25 --max-sessions 5
#   claude-auto-resume --resume   # Resume from existing handoff.json
#
# Examples:
#   claude-auto-resume "/gsd:execute-phase"
#   claude-auto-resume "Refactor all providers to use the new base class"
#   claude-auto-resume "Fix all failing tests" --max-sessions 3
#
# Environment variables:
#   AUTO_RESUME_MAX_TURNS     Max turns per session (default: 30)
#   AUTO_RESUME_MAX_SESSIONS  Max sessions before stopping (default: 10)
#   AUTO_RESUME_PAUSE         Seconds between sessions (default: 3)
#   CLAUDE_FLAGS              Extra flags to pass to claude (e.g. "--model opus")

set -euo pipefail

# ── Defaults ──────────────────────────────────────────────────────────
MAX_TURNS="${AUTO_RESUME_MAX_TURNS:-30}"
MAX_SESSIONS="${AUTO_RESUME_MAX_SESSIONS:-10}"
PAUSE_SECONDS="${AUTO_RESUME_PAUSE:-3}"
HANDOFF_FILE=".claude/handoff.json"
COMPLETE_MARKER=".claude/handoff-complete"
EXTRA_FLAGS="${CLAUDE_FLAGS:-}"

# ── Color helpers ─────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

log()  { echo -e "${CYAN}[auto-resume]${RESET} $*"; }
warn() { echo -e "${YELLOW}[auto-resume]${RESET} $*"; }
err()  { echo -e "${RED}[auto-resume]${RESET} $*" >&2; }
ok()   { echo -e "${GREEN}[auto-resume]${RESET} $*"; }

# ── Argument parsing ─────────────────────────────────────────────────
PROMPT=""
RESUME_MODE=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --max-turns)
            MAX_TURNS="$2"; shift 2 ;;
        --max-turns=*)
            MAX_TURNS="${1#*=}"; shift ;;
        --max-sessions)
            MAX_SESSIONS="$2"; shift 2 ;;
        --max-sessions=*)
            MAX_SESSIONS="${1#*=}"; shift ;;
        --pause)
            PAUSE_SECONDS="$2"; shift 2 ;;
        --pause=*)
            PAUSE_SECONDS="${1#*=}"; shift ;;
        --resume)
            RESUME_MODE=true; shift ;;
        --help|-h)
            echo "Usage: $0 \"prompt\" [--max-turns N] [--max-sessions N] [--pause N] [--resume]"
            echo ""
            echo "Options:"
            echo "  --max-turns N      Max agentic turns per session (default: 30)"
            echo "  --max-sessions N   Max sessions before stopping (default: 10)"
            echo "  --pause N          Seconds between sessions (default: 3)"
            echo "  --resume           Resume from existing .claude/handoff.json"
            echo ""
            echo "Environment:"
            echo "  CLAUDE_FLAGS       Extra flags for claude (e.g. '--model opus')"
            exit 0
            ;;
        -*)
            err "Unknown flag: $1"; exit 1 ;;
        *)
            PROMPT="$1"; shift ;;
    esac
done

# ── Validation ────────────────────────────────────────────────────────
if [[ -z "$PROMPT" && "$RESUME_MODE" == false ]]; then
    err "No prompt provided. Usage: $0 \"your prompt here\""
    exit 1
fi

if ! command -v claude &>/dev/null; then
    err "claude CLI not found. Install Claude Code first."
    exit 1
fi

# Find python (needed for JSON handling)
PYTHON=""
if command -v python3 &>/dev/null; then
    PYTHON="python3"
elif command -v python &>/dev/null; then
    PYTHON="python"
else
    err "python3 not found (needed for JSON processing)."
    exit 1
fi

# ── Helper: read handoff.json fields ─────────────────────────────────
read_handoff() {
    local field="$1"
    local default="${2:-}"
    if [[ -f "$HANDOFF_FILE" ]]; then
        $PYTHON -c "
import json, sys
try:
    with open('$HANDOFF_FILE') as f:
        data = json.load(f)
    keys = '$field'.split('.')
    val = data
    for k in keys:
        if isinstance(val, dict):
            val = val.get(k)
        else:
            val = None
            break
    if val is None:
        print('$default')
    elif isinstance(val, (list, dict)):
        print(json.dumps(val))
    else:
        print(val)
except Exception:
    print('$default')
" 2>/dev/null
    else
        echo "$default"
    fi
}

# ── Helper: capture session state (replaces Stop hook for -p mode) ───
capture_session_state() {
    local session_num="$1"
    $PYTHON << 'PYEOF'
import json, os, subprocess, glob, re, sys
from datetime import datetime, timezone

HANDOFF = ".claude/handoff.json"

# Load existing handoff
try:
    with open(HANDOFF) as f:
        handoff = json.load(f)
except Exception:
    handoff = {}

# Detect files changed via git
files_modified = []
try:
    result = subprocess.run(
        ["git", "diff", "--name-only", "HEAD"],
        capture_output=True, text=True, timeout=10
    )
    if result.returncode == 0:
        files_modified = [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]
except Exception:
    pass

# Also get untracked files
try:
    result = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        capture_output=True, text=True, timeout=10
    )
    if result.returncode == 0:
        untracked = [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]
        files_modified.extend(untracked)
except Exception:
    pass

# Filter out handoff files themselves
files_modified = [f for f in files_modified if "handoff" not in f and f != ".claude/security-review.md"]

# Detect GSD state
gsd_state = None
planning_dir = ".planning"
if os.path.isdir(planning_dir):
    gsd_state = {
        "planning_dir": planning_dir,
        "project_name": None,
        "roadmap_exists": os.path.exists(os.path.join(planning_dir, "ROADMAP.md")),
        "phases": [],
        "current_phase": None,
    }
    # Read project name
    project_path = os.path.join(planning_dir, "PROJECT.md")
    if os.path.exists(project_path):
        try:
            with open(project_path) as f:
                line = f.readline().strip()
                if line.startswith("# "):
                    gsd_state["project_name"] = line[2:].strip()
        except OSError:
            pass
    # Detect phases
    for d in sorted(glob.glob(os.path.join(planning_dir, "[0-9]*"))):
        if os.path.isdir(d):
            name = os.path.basename(d)
            status = "unknown"
            if os.path.exists(os.path.join(d, "VERIFICATION.md")):
                status = "verified"
            elif os.path.exists(os.path.join(d, "STATE.md")):
                try:
                    with open(os.path.join(d, "STATE.md")) as f:
                        content = f.read(500).lower()
                        if "completed" in content:
                            status = "completed"
                        elif "in_progress" in content:
                            status = "in_progress"
                except OSError:
                    pass
            gsd_state["phases"].append({"name": name, "status": status})
    # Current phase
    for p in gsd_state["phases"]:
        if p["status"] not in ("completed", "verified"):
            gsd_state["current_phase"] = p["name"]
            break

# Get recent git log for context
recent_commits = []
try:
    result = subprocess.run(
        ["git", "log", "--oneline", "-5"],
        capture_output=True, text=True, timeout=10
    )
    if result.returncode == 0:
        recent_commits = [l.strip() for l in result.stdout.strip().split("\n") if l.strip()]
except Exception:
    pass

# Update handoff
session_num = int(sys.argv[1]) if len(sys.argv) > 1 else handoff.get("session_count", 0) + 1
all_modified = set(handoff.get("all_files_modified", []))
all_modified.update(files_modified)

handoff["updated"] = datetime.now(timezone.utc).isoformat()
handoff["session_count"] = session_num
handoff["status"] = "in_progress"
handoff["last_session"] = {
    "files_modified": files_modified,
    "recent_commits": recent_commits,
}
handoff["all_files_modified"] = sorted(all_modified)

if gsd_state:
    handoff["gsd"] = gsd_state
    # Check GSD completion
    if gsd_state.get("phases"):
        all_done = all(p["status"] in ("completed", "verified") for p in gsd_state["phases"])
        if all_done:
            handoff["status"] = "completed"

os.makedirs(os.path.dirname(HANDOFF), exist_ok=True)
with open(HANDOFF, "w") as f:
    json.dump(handoff, f, indent=2)

# Report
n = len(files_modified)
status = handoff["status"]
print(f"[capture] Session #{session_num}: {n} files changed, status={status}", file=sys.stderr)
PYEOF
}

# ── Helper: build resume prompt ──────────────────────────────────────
build_resume_prompt() {
    local session_num="$1"
    local original="$2"

    local files_modified
    files_modified=$(read_handoff "all_files_modified" "[]")
    local last_files
    last_files=$(read_handoff "last_session.files_modified" "[]")
    local recent_commits
    recent_commits=$(read_handoff "last_session.recent_commits" "[]")
    local gsd_phase
    gsd_phase=$(read_handoff "gsd.current_phase" "")
    local gsd_project
    gsd_project=$(read_handoff "gsd.project_name" "")

    cat <<PROMPT
AUTOMATIC SESSION RESUME (session ${session_num}/${MAX_SESSIONS})

You are continuing work from a previous session that ran out of context space.
The original task was:

> ${original}

Files modified across all sessions: ${files_modified}
Files changed in the last session: ${last_files}
Recent git commits: ${recent_commits}
PROMPT

    # Add GSD context
    if [[ -n "$gsd_phase" ]]; then
        cat <<PROMPT

GSD Context:
- Project: ${gsd_project}
- Current phase: ${gsd_phase}
- Continue executing the phase plan from where the previous session left off.
PROMPT
    fi

    cat <<'PROMPT'

INSTRUCTIONS:
1. Review what was already done (check modified files, git diff, git log)
2. Continue the work from where the last session left off
3. Do NOT redo completed work — pick up from where things stopped
4. If the task is FULLY COMPLETE, create a file at .claude/handoff-complete with a brief summary
5. If using GSD, check /gsd:progress for current state
PROMPT
}

# ── Helper: create initial handoff ───────────────────────────────────
create_initial_handoff() {
    local prompt="$1"
    mkdir -p .claude
    $PYTHON -c "
import json
from datetime import datetime, timezone
handoff = {
    'version': 1,
    'created': datetime.now(timezone.utc).isoformat(),
    'original_prompt': $(printf '%s' "$prompt" | $PYTHON -c 'import sys,json; print(json.dumps(sys.stdin.read()))'),
    'session_count': 0,
    'status': 'starting',
    'all_files_modified': []
}
with open('$HANDOFF_FILE', 'w') as f:
    json.dump(handoff, f, indent=2)
"
}

# ── Main loop ─────────────────────────────────────────────────────────
main() {
    # Unset CLAUDECODE so we can spawn fresh sessions (not nesting — each
    # session is independent with its own context window)
    unset CLAUDECODE

    log "${BOLD}Auto-Resume Loop${RESET}"
    log "Max turns/session: ${MAX_TURNS}"
    log "Max sessions: ${MAX_SESSIONS}"

    # Handle resume mode
    if [[ "$RESUME_MODE" == true ]]; then
        if [[ ! -f "$HANDOFF_FILE" ]]; then
            err "No handoff file found at $HANDOFF_FILE. Cannot resume."
            exit 1
        fi
        PROMPT=$(read_handoff "original_prompt" "")
        if [[ -z "$PROMPT" ]]; then
            err "Handoff file has no original_prompt. Cannot resume."
            exit 1
        fi
        log "Resuming from handoff: $(read_handoff 'session_count' '0') sessions completed"
    else
        # Fresh start: create initial handoff
        create_initial_handoff "$PROMPT"
        log "Original prompt: ${PROMPT:0:80}..."
    fi

    # Remove completion marker if it exists from a previous run
    rm -f "$COMPLETE_MARKER"

    echo ""

    local session=1
    local start_session
    start_session=$(read_handoff "session_count" "0")

    while [[ $session -le $MAX_SESSIONS ]]; do
        local total_session=$((start_session + session))

        log "━━━ Session ${session}/${MAX_SESSIONS} (total: #${total_session}) ━━━"

        # Build the prompt for this session
        local session_prompt
        if [[ $session -eq 1 && "$RESUME_MODE" == false ]]; then
            # First session: use original prompt
            session_prompt="$PROMPT

(Running under auto-resume. If the task is fully complete, create .claude/handoff-complete with a summary.)"
        else
            # Subsequent sessions: build resume prompt
            session_prompt=$(build_resume_prompt "$total_session" "$PROMPT")
        fi

        # Run claude session
        # --permission-mode acceptEdits: auto-approve file read/write (needed for
        # non-interactive -p mode), but still prompt for bash commands
        local exit_code=0
        # shellcheck disable=SC2086
        claude -p "$session_prompt" \
            --max-turns "$MAX_TURNS" \
            --permission-mode acceptEdits \
            $EXTRA_FLAGS || exit_code=$?

        log "Session exited with code: ${exit_code}"

        # Capture session state (Stop hooks don't fire in -p mode, so we
        # use git diff + GSD state detection directly)
        capture_session_state "$total_session"

        # Check for completion marker (agent created .claude/handoff-complete)
        if [[ -f "$COMPLETE_MARKER" ]]; then
            echo ""
            ok "━━━ TASK COMPLETE ━━━"
            ok "Completed in ${session} session(s)"
            ok "Summary:"
            cat "$COMPLETE_MARKER"
            echo ""
            rm -f "$COMPLETE_MARKER"
            return 0
        fi

        # Check handoff status (capture_session_state may detect GSD completion)
        local handoff_status
        handoff_status=$(read_handoff "status" "in_progress")
        if [[ "$handoff_status" == "completed" ]]; then
            echo ""
            ok "━━━ TASK COMPLETE (all phases done) ━━━"
            ok "Completed in ${session} session(s)"
            return 0
        fi

        # Check if we've hit max sessions
        if [[ $session -ge $MAX_SESSIONS ]]; then
            echo ""
            warn "━━━ MAX SESSIONS REACHED (${MAX_SESSIONS}) ━━━"
            warn "Task may not be complete. Run with --resume to continue."
            return 1
        fi

        # Pause between sessions
        log "Pausing ${PAUSE_SECONDS}s before next session..."
        sleep "$PAUSE_SECONDS"
        echo ""

        session=$((session + 1))
    done
}

main
