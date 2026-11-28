# shellcheck shell=bash
#
# One pinned full suite at a time on this machine, first come first served.
# Sourced by ops/verify-commit.sh; not meant to be run directly.
#
# ⚠ WHY: TWO FULL SUITES AT ONCE ON THIS BOX PRODUCE FAILURES THAT BELONG TO NOBODY. Around forty
# agent sessions share one box, and concurrent vitest runs already forced the timeouts up
# 5s → 15s → 30s. A suite that flakes under load writes a FAIL receipt for a commit that is fine,
# and a run that measured another run's slowness is not a measurement. Contention also stretches
# the wall clock for everyone instead of finishing one run fast.
#
# ⚠ AND POLITENESS WITHOUT A QUEUE STARVES. A session that wants a quiet box polls "is any suite
# running?" and waits — while every OTHER session's quick targeted test counts as busy, so no gap ever
# appears. A lock held only by verify-commit — which targeted runs never take — plus a queue in arrival
# order fixes both: runs never overlap, and nobody waits behind somebody who arrived later.
#
# HOW IT WORKS
#   - Everything lives under SUITE_LOCK_ROOT (default ~/.local/state/frood-workstation/suite-lock),
#     so every repo on this box shares ONE lock and one queue instead of a per-repo lock.
#   - A waiter drops a ticket named by arrival time into queue/. The oldest live ticket may try to
#     take held/, which `mkdir` creates atomically — exactly one process can win it.
#   - LIVENESS IS BY FILE TIMESTAMP, NOT PROCESS ID. Waiters touch their ticket every poll; the
#     holder's background heartbeat touches held/owner. A ticket or lock nobody has touched within
#     its stale window belongs to a session that died, and the next waiter removes it. PID checks
#     across separate shells on Windows are not something to bet the queue on.
#   - The caller takes the lock BEFORE creating its worktree, so a session killed while waiting
#     leaves nothing behind: no stray worktree, and no FAIL receipt for a suite that never started.
#   - HISTORY: every acquire/release/break/skip is appended as one JSON line to
#     $SUITE_LOCK_DIR/history.jsonl (rotated at 1 MiB to .1), so load spikes can later be
#     attributed to the suite run that held the lock. The history never fails, never prints,
#     and never changes control flow — it is purely additive observability.
#
# SUITE_LOCK=0 skips it (loudly) for an emergency. The stale windows and poll interval are
# overridable so tests can run the real code in seconds.
#
# Box-wide port of the per-repo suite-lock.sh (sales-team-toolbox and volnova twins), whose header
# records the two incidents that shaped the two-read rule and the token-checked release below. The
# mechanism is identical on purpose: one discipline, every repo.

SUITE_LOCK_POLL="${SUITE_LOCK_POLL:-10}"            # seconds between a waiter's checks
SUITE_LOCK_BEAT="${SUITE_LOCK_BEAT:-30}"            # holder heartbeat interval
SUITE_LOCK_STALE="${SUITE_LOCK_STALE:-300}"        # holder silent this long = dead holder
SUITE_LOCK_WAITER_STALE="${SUITE_LOCK_WAITER_STALE:-120}"   # waiter silent this long = dead waiter
SUITE_LOCK_REPORT="${SUITE_LOCK_REPORT:-60}"        # how often a waiter says where it is

SUITE_LOCK_DIR=""
SUITE_LOCK_TICKET=""
SUITE_LOCK_HELD=0
SUITE_LOCK_BEAT_PID=""
SUITE_LOCK_TOKEN=""     # unique per acquisition; written into held/owner so only its holder releases it
SUITE_LOCK_SINCE=""     # epoch seconds the lock was taken; set at acquire, used for held_s
SUITE_LOCK_TICKET_AT="" # epoch seconds the ticket was written; used for wait_s (wall seconds)

# Seconds since PATH was last touched, or -1 when that cannot be read RIGHT NOW.
#
# -1 MEANS "UNKNOWN", NEVER "OLD". A waiter that reads "cannot see the holder's file" as "the holder
# died long ago" breaks a LIVE lock: on a loaded Windows box a `stat` can fail transiently when it
# collides with another process's `touch` of the same file, and one such collision in ~140 polls is
# enough. So a waiter breaks a lock only on TWO consecutive stale readings, never one — and an
# unreadable holder resets the count, never adds to it.
_suite_lock_age() {
  local m
  m="$(stat -c %Y "$1" 2>/dev/null)" || { echo -1; return; }
  [ -n "$m" ] || { echo -1; return; }
  echo $(( $(date +%s) - m ))
}

# The token in a lock's owner file, or empty when it cannot be read.
_suite_lock_token_of() {
  sed -n 's/^token //p' "$1/owner" 2>/dev/null | head -1
}

_suite_lock_first() {  # oldest ticket; the glob expands sorted and tickets start with a fixed-width time
  local LC_ALL=C         # byte order, so the queue order cannot depend on the caller's locale
  local t
  for t in "$1"/*; do
    [ -e "$t" ] && { printf '%s' "$t"; return; }
  done
}

# JSON-escape a value for embedding in a JSON string: backslash, double quote
# and control characters become a space. Pure bash + tr/sed, no jq/node/python.
_suite_lock_json_escape() {
  local s="$1"
  s="${s//\\/ }"     # backslash -> space
  s="${s//\"/ }"     # double quote -> space
  s="$(printf '%s' "$s" | tr '[:cntrl:]' ' ')"
  printf '%s' "$s"
}

# Append one JSON history line to $SUITE_LOCK_DIR/history.jsonl.
#   _suite_lock_history <event> [key value ...]
# Fields: at (UTC ISO, second precision), event, pid ($$), what (the label),
# plus the extra key/value fields. Never fails, never prints, every write is
# `2>/dev/null || true`; safe under `set -euo pipefail`.
# Rotates history.jsonl to history.jsonl.1 when it is over 1 MiB before append.
_suite_lock_history() {
  local event="$1"
  shift
  local f="${SUITE_LOCK_DIR:-}/history.jsonl" now size what_escaped k v extras=""
  [ -n "$SUITE_LOCK_DIR" ] || return 0
  [ -d "$SUITE_LOCK_DIR" ] || return 0        # skip silently when the dir does not exist yet
  now="$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || echo 0)"
  # rotation before append
  if [ -e "$f" ]; then
    size="$(stat -c %s "$f" 2>/dev/null || echo 0)"
    if [ "${size:-0}" -gt 1048576 ]; then
      { mv "$f" "$f.1"; } 2>/dev/null || true
    fi
  fi
  # build extra JSON fields; integer values are emitted unquoted.
  local first=1
  while [ $# -gt 0 ]; do
    k="$1"; v="${2:-}"; shift 2
    if [ "$first" -eq 1 ]; then first=0; else extras="$extras,"; fi
    case "$v" in
      ''|*[!0-9]*) extras="${extras}\"${k}\":"\"$(_suite_lock_json_escape "$v")"\"" ;;
      *) extras="${extras}\"${k}\":${v}" ;;
    esac
  done
  what_escaped="$(_suite_lock_json_escape "${SUITE_LOCK_HISTORY_WHAT:-}")"
  local sep=""
  [ -n "$extras" ] && sep=","
  { printf '%s\n' "{\"at\":\"${now}\",\"event\":\"${event}\",\"pid\":$$,\"what\":\"${what_escaped}\"${sep}${extras}}" >> "$f"; } 2>/dev/null || true
}

suite_lock_acquire() {  # $1 = one line saying what is about to run, shown to anyone waiting behind it
  local what="${1:-a pinned suite}"
  local LC_ALL=C         # the "ahead of you" count walks the same sorted glob as _suite_lock_first
  if [ "${SUITE_LOCK:-1}" = "0" ]; then
    # Resolve the lock root the same way the main path does, so history can be written.
    if [ -n "${SUITE_LOCK_ROOT:-}" ]; then
      SUITE_LOCK_DIR="$SUITE_LOCK_ROOT"
    elif [ -n "${HOME:-}" ]; then
      SUITE_LOCK_DIR="$HOME/.local/state/frood-workstation/suite-lock"
    else
      local phome=""
      if command -v getent >/dev/null 2>&1; then
        phome="$(getent passwd "$(id -u)" 2>/dev/null | cut -d: -f6)" || phome=""
      fi
      if [ -n "$phome" ]; then
        case "$phome" in
          /*) SUITE_LOCK_DIR="$phome/.local/state/frood-workstation/suite-lock" ;;
        esac
      fi
    fi
    SUITE_LOCK_HISTORY_WHAT="$what"
    _suite_lock_history skip
    echo "==> WARN: SUITE_LOCK=0 — running WITHOUT the box-wide suite lock. A concurrent run can fail this one."
    return 0
  fi

  # Resolve the lock root, set -u-safe:
  #   SUITE_LOCK_ROOT (non-empty) is used as the lock directory as-is;
  #   otherwise ${HOME:-} (non-empty) + /.local/state/frood-workstation/suite-lock;
  #   otherwise the passwd home from getent + that suffix.
  #   An empty HOME never yields "/.local".
  if [ -n "${SUITE_LOCK_ROOT:-}" ]; then
    SUITE_LOCK_DIR="$SUITE_LOCK_ROOT"
  elif [ -n "${HOME:-}" ]; then
    SUITE_LOCK_DIR="$HOME/.local/state/frood-workstation/suite-lock"
  else
    local phome=""
    if command -v getent >/dev/null 2>&1; then
      phome="$(getent passwd "$(id -u)" 2>/dev/null | cut -d: -f6)" || phome=""
    fi
    if [ -n "$phome" ]; then
      case "$phome" in
        /*) SUITE_LOCK_DIR="$phome/.local/state/frood-workstation/suite-lock" ;;
      esac
    fi
  fi

  if [ -z "${SUITE_LOCK_DIR:-}" ]; then
    echo "==> suite lock: ERROR: cannot place the box-wide lock (SUITE_LOCK_ROOT and HOME are unset, and no passwd home)" >&2
    return 2
  fi

  local q held reason
  q="$SUITE_LOCK_DIR/queue" held="$SUITE_LOCK_DIR/held"
  if ! reason="$(mkdir -p "$q" 2>&1)"; then
    echo "==> suite lock: ERROR: cannot create $SUITE_LOCK_DIR: $reason" >&2
    return 2
  fi

  SUITE_LOCK_TICKET="$q/$(date +%s%N)-$$"
  SUITE_LOCK_TICKET_AT="$(date +%s)"
  if ! printf '%s\n' "$what" > "$SUITE_LOCK_TICKET" 2>/dev/null; then
    echo "==> suite lock: ERROR: cannot create $SUITE_LOCK_DIR: cannot write ticket" >&2
    rm -f "$SUITE_LOCK_TICKET"
    return 2
  fi

  local waited=0 last_report=-1 t head ahead age
  local step="${SUITE_LOCK_POLL%.*}"; step="${step:-0}"   # whole seconds, for the "waited" count only
  # Breaking another session's lock is the one irreversible thing a waiter does, so it takes TWO
  # consecutive stale readings, never one — and an unreadable holder resets the count, never adds to it.
  local stale_reads=0 ownerless_since=""
  while :; do
    # If a peer mistook this waiter for dead (starved past the window on a loaded box) and removed its
    # ticket, put it back. The PLACE in the queue is the file NAME, so nothing is lost by recreating it.
    [ -e "$SUITE_LOCK_TICKET" ] || printf '%s\n' "$what" > "$SUITE_LOCK_TICKET"
    touch "$SUITE_LOCK_TICKET"

    # A waiter that stopped touching its ticket has died; it must not block the queue forever.
    for t in "$q"/*; do
      [ -e "$t" ] || continue
      [ "$t" = "$SUITE_LOCK_TICKET" ] && continue
      age="$(_suite_lock_age "$t")"
      if [ "$age" -ge 0 ] && [ "$age" -gt "$SUITE_LOCK_WAITER_STALE" ]; then
        echo "==> suite lock: dropping a dead waiter's ticket ($(head -1 "$t" 2>/dev/null))"
        rm -f "$t"
      fi
    done

    # A holder whose heartbeat stopped has died mid-run; take the lock back from it — but only on
    # evidence, never on a failed read (see _suite_lock_age).
    if [ -d "$held" ]; then
      if [ -e "$held/owner" ]; then
        ownerless_since=""
        age="$(_suite_lock_age "$held/owner")"
        if [ "$age" -lt 0 ]; then
          stale_reads=0                                   # unreadable right now: unknown, not old
        elif [ "$age" -gt "$SUITE_LOCK_STALE" ]; then
          stale_reads=$((stale_reads + 1))
        else
          stale_reads=0
        fi
        if [ "$stale_reads" -ge 2 ]; then
          local blabel="$(head -1 "$held/owner" 2>/dev/null)"
          SUITE_LOCK_HISTORY_WHAT="$blabel"
          _suite_lock_history break-stale
          echo "==> suite lock: breaking a stale lock (no heartbeat for ${SUITE_LOCK_STALE}s+): $blabel"
          rm -rf "$held"
          stale_reads=0
        fi
      else
        # A holder that died between creating the lock and writing its owner file. Timed by THIS
        # waiter's own clock, not the directory's mtime: that mtime is the acquisition time, so on a
        # long healthy run one transient failed `-e` would make it look ancient — the same bug again.
        stale_reads=0
        [ -n "$ownerless_since" ] || ownerless_since="$(date +%s)"
        if [ $(( $(date +%s) - ownerless_since )) -gt "$SUITE_LOCK_STALE" ]; then
          SUITE_LOCK_HISTORY_WHAT=""
          _suite_lock_history break-ownerless
          echo "==> suite lock: breaking a lock with no owner for ${SUITE_LOCK_STALE}s+ (its holder died before writing one)"
          rm -rf "$held"
          ownerless_since=""
        fi
      fi
    else
      stale_reads=0; ownerless_since=""
    fi

    head="$(_suite_lock_first "$q")"
    if [ "$head" = "$SUITE_LOCK_TICKET" ] && mkdir "$held" 2>/dev/null; then
      SUITE_LOCK_TOKEN="$(date +%s%N)-$$-${RANDOM}"
      printf '%s\npid %s, since %s\ntoken %s\n' "$what" "$$" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        "$SUITE_LOCK_TOKEN" > "$held/owner"
      rm -f "$SUITE_LOCK_TICKET"
      SUITE_LOCK_TICKET=""
      SUITE_LOCK_HELD=1
      SUITE_LOCK_SINCE="$(date +%s)"
      local wait_s=$(( SUITE_LOCK_SINCE - SUITE_LOCK_TICKET_AT ))
      [ "$wait_s" -lt 0 ] && wait_s=0
      SUITE_LOCK_HISTORY_WHAT="$what"
      _suite_lock_history acquire wait_s "$wait_s"
      # The heartbeat outlives nothing: it stops when this shell dies or the lock is released, and
      # its output goes nowhere so it cannot hold a caller's pipe open.
      # `|| true` because the caller runs under `set -e`, which a subshell inherits: one failed touch
      # must not silently end the heartbeat and let a peer break a lock that is still in use.
      # ⚠ AND IT STOPS WHEN THE LOCK IS PROVABLY SOMEONE ELSE'S — a readable token that is not ours.
      # Before this it kept touching whatever held/owner it found, so a holder whose lock had been
      # taken kept the NEW holder's lock looking fresh. An unreadable token is not proof; keep beating.
      local tok="$SUITE_LOCK_TOKEN"
      ( while kill -0 "$$" 2>/dev/null && [ -d "$held" ]; do
          cur="$(_suite_lock_token_of "$held")"
          if [ -n "$cur" ] && [ "$cur" != "$tok" ]; then break; fi
          touch "$held/owner" 2>/dev/null || true
          sleep "$SUITE_LOCK_BEAT"
        done ) >/dev/null 2>&1 &
      SUITE_LOCK_BEAT_PID=$!
      [ "$waited" -gt 0 ] && echo "==> suite lock: acquired after ${waited}s"
      return 0
    fi

    if [ "$last_report" -lt 0 ] || [ $(( waited - last_report )) -ge "$SUITE_LOCK_REPORT" ]; then
      ahead=0
      for t in "$q"/*; do
        [ -e "$t" ] || continue
        [ "$t" = "$SUITE_LOCK_TICKET" ] && break
        ahead=$((ahead + 1))
      done
      echo "==> suite lock: waiting — ${ahead} ahead of you; running now: $(head -1 "$held/owner" 2>/dev/null || echo 'nothing (about to start)')"
      last_report="$waited"
    fi
    sleep "$SUITE_LOCK_POLL"
    waited=$(( waited + step ))
  done
}

suite_lock_release() {
  if [ -n "$SUITE_LOCK_BEAT_PID" ]; then
    kill "$SUITE_LOCK_BEAT_PID" 2>/dev/null || true
    SUITE_LOCK_BEAT_PID=""
  fi
  # ⚠ ONLY A LOCK THAT IS STILL OURS. Releasing whatever held/ holds lets a holder whose lock was
  # broken delete the NEW holder's lock on exit and start two suites on top of each other. Now:
  # our token → release; someone else's → leave it and say so; unreadable after retries → leave it
  # (the safe side: at worst the next waiter clears it after the stale window, instead of two suites
  # running at once).
  if [ "$SUITE_LOCK_HELD" = "1" ] && [ -n "$SUITE_LOCK_DIR" ]; then
    local held="$SUITE_LOCK_DIR/held" cur="" i held_s outcome=gone
    held_s=$(( $(date +%s) - ${SUITE_LOCK_SINCE:-0} ))
    [ "$held_s" -lt 0 ] && held_s=0
    for i in 1 2 3; do
      cur="$(_suite_lock_token_of "$held")"
      [ -n "$cur" ] && break
      [ -d "$held" ] || break
      sleep 1
    done
    if [ -n "$cur" ] && [ "$cur" = "$SUITE_LOCK_TOKEN" ]; then
      rm -rf "$held"
      outcome=released
    elif [ -n "$cur" ]; then
      echo "==> suite lock: NOT releasing — the lock now belongs to: $(head -1 "$held/owner" 2>/dev/null)"
      outcome=not-ours
    elif [ -d "$held" ]; then
      echo "==> suite lock: could not read the lock's owner; leaving it for the stale window to clear"
      outcome=unreadable
    fi
    SUITE_LOCK_HISTORY_WHAT="${SUITE_LOCK_HISTORY_WHAT:-a pinned suite}"
    _suite_lock_history release held_s "$held_s" outcome "$outcome"
    SUITE_LOCK_HELD=0
  fi
  if [ -n "$SUITE_LOCK_TICKET" ]; then
    rm -f "$SUITE_LOCK_TICKET"
    SUITE_LOCK_TICKET=""
  fi
}
