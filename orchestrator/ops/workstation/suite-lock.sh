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

suite_lock_acquire() {  # $1 = one line saying what is about to run, shown to anyone waiting behind it
  local what="${1:-a pinned suite}"
  local LC_ALL=C         # the "ahead of you" count walks the same sorted glob as _suite_lock_first
  if [ "${SUITE_LOCK:-1}" = "0" ]; then
    echo "==> WARN: SUITE_LOCK=0 — running WITHOUT the box-wide suite lock. A concurrent run can fail this one."
    return 0
  fi

  SUITE_LOCK_DIR="${SUITE_LOCK_ROOT:-$HOME/.local/state/frood-workstation/suite-lock}"
  local q="$SUITE_LOCK_DIR/queue" held="$SUITE_LOCK_DIR/held"
  mkdir -p "$q"

  SUITE_LOCK_TICKET="$q/$(date +%s%N)-$$"
  printf '%s\n' "$what" > "$SUITE_LOCK_TICKET"

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
          echo "==> suite lock: breaking a stale lock (no heartbeat for ${SUITE_LOCK_STALE}s+): $(head -1 "$held/owner" 2>/dev/null)"
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
    local held="$SUITE_LOCK_DIR/held" cur="" i
    for i in 1 2 3; do
      cur="$(_suite_lock_token_of "$held")"
      [ -n "$cur" ] && break
      [ -d "$held" ] || break
      sleep 1
    done
    if [ -n "$cur" ] && [ "$cur" = "$SUITE_LOCK_TOKEN" ]; then
      rm -rf "$held"
    elif [ -n "$cur" ]; then
      echo "==> suite lock: NOT releasing — the lock now belongs to: $(head -1 "$held/owner" 2>/dev/null)"
    elif [ -d "$held" ]; then
      echo "==> suite lock: could not read the lock's owner; leaving it for the stale window to clear"
    fi
    SUITE_LOCK_HELD=0
  fi
  if [ -n "$SUITE_LOCK_TICKET" ]; then
    rm -f "$SUITE_LOCK_TICKET"
    SUITE_LOCK_TICKET=""
  fi
}
